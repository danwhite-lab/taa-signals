"""Isolated Rebalance Holdings UI; existing dashboards do not render here."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from uuid import uuid4

import pandas as pd
import streamlit as st

from .rebalance_holdings import (apply_purchases, combined_targets, compare_holdings, empty_account,
                                 fingerprint, make_buy_plan, number, security, validate_account)
from . import rebalance_market as market_data
from .rebalance_market import utc_now


def _save(candidate, commit_account):
    try:
        validate_account(candidate)
        commit_account(candidate)
        st.session_state.pop("rebalance_pending", None)
        return True
    except Exception as exc:
        st.error(f"Holdings were not confirmed saved. {exc}")
        return False


def render_rebalance_page(portfolios, known_instruments, ticker_items, replacements, commit_account, signal_source_error=None):
    st.title("Rebalance Holdings")
    st.caption("One shared account. Compare it with a saved portfolio, then direct available cash toward its current targets. Buy only; no brokerage orders are placed.")
    if st.session_state.pop("rebalance_reset_money", False):
        st.session_state["rebalance_new_money"] = 0.
    if message := st.session_state.pop("rebalance_message", None):
        st.success(message)
    try:
        account = validate_account(st.session_state.get("holdings_account", empty_account()))
    except (ValueError, KeyError, TypeError) as exc:
        st.error(f"Saved holdings could not be read: {exc}. Your data has not been overwritten.")
        return
    if st.button("Refresh prices and targets", key="rebalance_refresh"):
        market_data.clear_rebalance_quotes()
        st.session_state.pop("rebalance_pending", None)
    portfolio = None
    targets, instruments, source_rows, errors = {}, dict(known_instruments), [], []
    for key, row in account["positions"].items():
        instruments[key] = {field: row[field] for field in ("id", "identifier", "market", "currency", "label")}
    if portfolios:
        options = {row["id"]: row for row in portfolios}
        if st.session_state.get("rebalance_portfolio_id") not in options:
            st.session_state["rebalance_portfolio_id"] = next(iter(options))
        selected = st.selectbox("Compare against portfolio", tuple(options), format_func=lambda key: options[key]["name"], key="rebalance_portfolio_id")
        portfolio = options[selected]
        try:
            if signal_source_error:
                raise ValueError(f"Signal source settings need correction: {signal_source_error}")
            sleeves = portfolio["payload"]["sleeves"]
            if len({s["model"] for s in sleeves}) != len(sleeves):
                raise ValueError("Duplicate strategy sleeves in saved portfolio.")
            with st.spinner("Loading completed portfolio targets..."):
                signals, errors = market_data.load_portfolio_signals(tuple(s["model"] for s in sleeves), ticker_items, replacements)
            if not errors:
                by_name = {s["name"]: s for s in signals}
                source_rows = [{**by_name[s["model"]], "weight": s["weight"]} for s in sleeves]
                target_instruments, targets = combined_targets(source_rows)
                for key, item in target_instruments.items():
                    if key in instruments and instruments[key]["currency"] != item["currency"]:
                        raise ValueError(f"{key}: saved holding currency conflicts with the selected implementation.")
                    instruments[key] = item
        except Exception as exc:
            errors.append(str(exc))
    else:
        st.info("Save a portfolio on the Portfolio page to compare targets. You can still enter your shared holdings below.")

    st.subheader("Your shared holdings")
    st.caption("Store units, not a frozen ₪ valuation. Save changes after editing. Existing fractional US positions are allowed; proposed buys use whole units in both markets. Update your units after splits or other corporate actions.")
    with st.expander("Add a holding", expanded=not bool(account["positions"])):
        choice = st.selectbox("Fund", sorted(instruments), format_func=lambda key: f"{instruments[key]['label']} · {instruments[key]['currency']} · {key}", key="rebalance_add_choice") if instruments else None
        if st.button("Add selected fund", key="rebalance_add", disabled=not choice or choice in account["positions"]):
            updated = deepcopy(account)
            updated["positions"][choice] = {**instruments[choice], "units": "0"}
            updated.update(revision=account["revision"]+1, updated_at=utc_now(), last_operation_id=str(uuid4()))
            if _save(updated, commit_account):
                st.rerun()
        with st.form("rebalance_custom_fund"):
            st.caption("Not listed? Add the actual security, not a proxy or index.")
            market = st.selectbox("Market", ("US", "TASE"), key="rebalance_custom_market")
            identifier = st.text_input("Ticker or TASE security ID", key="rebalance_custom_identifier")
            currency = st.selectbox("Execution currency", ("Market default", "USD", "ILS"), key="rebalance_custom_currency")
            custom_add = st.form_submit_button("Add custom holding")
        if custom_add:
            try:
                item = security(identifier, market, None if currency == "Market default" else currency)
                if item["id"] in account["positions"]:
                    raise ValueError("This holding already exists.")
                updated = deepcopy(account)
                updated["positions"][item["id"]] = {**item, "units": "0"}
                updated.update(revision=account["revision"]+1, updated_at=utc_now(), last_operation_id=str(uuid4()))
                if _save(updated, commit_account):
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    visible_ids = sorted(set(account["positions"]) | set(targets))
    editor_rows = []
    for key in visible_ids:
        row = account["positions"].get(key, {})
        editor_rows.append({"Security": key, "Fund": instruments[key]["label"], "Currency": instruments[key]["currency"],
                            "Units": float(row.get("units", 0)), "Manual price per unit": float(row["manual_price"]) if row.get("manual_price") else None,
                            "Price date": date.fromisoformat(row["manual_price_date"]) if row.get("manual_price_date") else None,
                            "Minimum order (₪)": float(row.get("minimum_ils", 0)), "Remove": False})
    editor_columns = ["Security", "Fund", "Currency", "Units", "Manual price per unit", "Price date", "Minimum order (₪)", "Remove"]
    with st.form("rebalance_holdings_form"):
        edited = st.data_editor(pd.DataFrame(editor_rows, columns=editor_columns), hide_index=True,
            disabled=["Security", "Fund", "Currency"], use_container_width=True,
            column_config={"Units": st.column_config.NumberColumn(min_value=0., format="%.6f"),
                           "Manual price per unit": st.column_config.NumberColumn(min_value=0., format="%.6f"),
                           "Price date": st.column_config.DateColumn(),
                           "Minimum order (₪)": st.column_config.NumberColumn(min_value=0., format="%.2f"),
                           "Remove": st.column_config.CheckboxColumn()},
            key=f"rebalance_editor_{account['revision']}_{fingerprint(visible_ids)[:12]}")
        st.caption("Manual prices are native currency per ONE unit: ₪ for ILS funds, dollars for USD funds—not agorot or cents. Blank means automatic feed. Minimum 0 means unknown/not configured, not a verified broker minimum.")
        cash = st.number_input("Unallocated account cash (₪)", min_value=0., value=float(account["cash_ils"]), step=1., key=f"rebalance_cash_{account['revision']}")
        with st.expander("Manual USD/ILS override"):
            st.caption("Optional: dated broker exchange rate in ₪ per $1. Clear it to use the indicative feed.")
            manual_fx = st.number_input("Manual ₪ per $1 (0 = automatic)", min_value=0., value=float(account.get("manual_fx") or 0), step=.01, format="%.6f", key=f"rebalance_fx_{account['revision']}")
            manual_fx_date = st.date_input("FX observation date", value=date.fromisoformat(account["manual_fx_date"]) if account.get("manual_fx_date") else date.today(), key=f"rebalance_fx_date_{account['revision']}")
        save = st.form_submit_button("Save holdings", type="primary")
    if save:
        try:
            updated = deepcopy(account)
            for row in edited.to_dict("records"):
                key = row["Security"]
                if row["Remove"]:
                    updated["positions"].pop(key, None)
                    continue
                old = account["positions"].get(key, {})
                price = row["Manual price per unit"]
                has_price = price is not None and not pd.isna(price)
                stamp = row["Price date"]
                price_date = None if stamp is None or pd.isna(stamp) else pd.Timestamp(stamp).date().isoformat()
                position = {**instruments[key], "units": str(number(row["Units"])),
                            "minimum_ils": str(number(row["Minimum order (₪)"])),
                            "manual_price": str(number(price, positive=True)) if has_price else None,
                            "manual_price_date": price_date if has_price else None}
                same_override = position["manual_price"] == old.get("manual_price") and position["manual_price_date"] == old.get("manual_price_date")
                position["manual_entered_at"] = old.get("manual_entered_at") if same_override else utc_now()
                updated["positions"][key] = position
            updated.update(cash_ils=str(number(cash)), revision=account["revision"]+1,
                           manual_fx=str(number(manual_fx, positive=True)) if manual_fx else None,
                           manual_fx_date=manual_fx_date.isoformat() if manual_fx else None,
                           updated_at=utc_now(), last_operation_id=str(uuid4()))
            if _save(updated, commit_account):
                st.session_state["rebalance_message"] = "Shared holdings saved to your account."
                st.rerun()
        except (ValueError, TypeError) as exc:
            st.error(str(exc))

    relevant = set(targets) | {key for key, row in account["positions"].items() if number(row["units"])}
    quotes = {key: market_data.unit_quote(instruments[key], account["positions"].get(key, {})) for key in sorted(relevant)}
    uses_usd = any(instruments[key]["currency"] == "USD" for key in relevant)
    fx = market_data.fx_quote(account) if uses_usd else {"price": "1", "fresh": True, "source": "Not needed: ILS holdings only"}
    st.subheader("Prices and freshness")
    st.caption("Free public/delayed observations, not live executable quotes. Quote caches refresh after five minutes or with Refresh above. Freshness is checked against the latest completed exchange session; missing funds, old fund publications and unknown quote units are not guessed.")
    if quotes:
        st.dataframe(pd.DataFrame([{"Security": key, "Price per unit": quote.get("price"), "Currency": instruments[key]["currency"],
                                   "Raw publication (unit unverified)": quote.get("raw_published_value"),
                                   "Observation date": quote.get("as_of"), "Retrieved / entered": quote.get("fetched_at"),
                                   "Field": quote.get("field"), "Source": quote.get("source"),
                                   "Status": quote.get("error") or quote.get("status")} for key, quote in quotes.items()]), hide_index=True, use_container_width=True)
    if uses_usd:
        st.caption(f"USD/ILS: {fx.get('price', 'Unavailable')} ₪ per $1 · observed {fx.get('as_of', '—')} · retrieved/entered {fx.get('fetched_at', '—')} · {fx.get('source', '—')} · {fx.get('status', fx.get('error', ''))}")
    for error in errors:
        st.warning(error)
    for source in source_rows:
        st.caption(f"{source['name']}: actionable signal {source['signal_date']}" + (" · Source substitutions: " + ", ".join(source["source_notes"]) if source["source_notes"] else ""))
    if not portfolio or errors or not targets:
        st.info("A complete set of actionable portfolio targets is required for the comparison and buy list. Your holdings remain editable.")
        return
    if fx.get("error"):
        st.warning(f"Cannot value USD holdings: {fx['error']}")
        return
    try:
        comparison, _, total = compare_holdings(account, instruments, targets, quotes, fx["price"])
    except ValueError as exc:
        st.warning(str(exc))
        return
    st.subheader("Target versus actual")
    st.metric("Account value, including unallocated cash", f"₪{total:,.2f}")
    st.dataframe(pd.DataFrame(comparison).drop(columns="id").style.format({"Target %": "{:.2%}", "Actual %": "{:.2%}", "Value (₪)": "{:,.2f}", "Gap (₪)": "{:,.2f}"}, na_rep="—"), hide_index=True, use_container_width=True)
    if any(row["Status"] == "Overweight" for row in comparison):
        st.info("Some funds are overweight. This page will not suggest selling; new cash may not bring every fund back to target.")
    stale = [key for key, quote in quotes.items() if not quote.get("fresh")]
    if stale or not fx.get("fresh"):
        st.warning("Valuation uses dated observations shown above. Automatic buy sizing is blocked until all required prices and FX are current, or replaced by explicitly dated broker observations.")
    new_money = st.number_input("New money (₪)", min_value=0., value=0., step=100., format="%.0f", key="rebalance_new_money")
    st.caption(f"Available for purchases: existing cash ₪{float(account['cash_ils']):,.2f} + new money ₪{new_money:,.0f}. Prices and FX are estimates; commissions/spread are not automatically deducted. Leave a cash buffer if needed.")
    context = {"portfolio": portfolio, "targets": targets, "quotes": quotes, "fx": fx, "new_money": str(number(new_money))}
    pending = st.session_state.get("rebalance_pending")
    if pending and (pending["account_hash"] != fingerprint(account) or pending["context_hash"] != fingerprint(context)):
        st.session_state.pop("rebalance_pending", None)
        pending = None
        st.info("Inputs changed. Generate a fresh buy list before recording purchases.")
    if st.button("Generate buy list", key="rebalance_generate", disabled=bool(stale or not fx.get("fresh"))):
        try:
            pending = make_buy_plan(account, instruments, targets, quotes, fx["price"], new_money, context)
            st.session_state["rebalance_pending"] = pending
        except ValueError as exc:
            st.error(str(exc))
    if not pending:
        return
    st.subheader("Buy list — whole units only")
    order_rows = [{"Security": row["id"], "Fund": instruments[row["id"]]["label"], "Units to buy": row["units"],
                   "Currency": instruments[row["id"]]["currency"], "Estimated native cost": float(number(row["price_native"]) * row["units"]),
                   "Estimated cost (₪)": float(row["estimated_ils"])} for row in pending["orders"]]
    if order_rows:
        st.dataframe(pd.DataFrame(order_rows).style.format({"Estimated native cost": "{:,.2f}", "Estimated cost (₪)": "{:,.2f}"}), hide_index=True, use_container_width=True)
    else:
        st.info("No feasible whole-unit purchases fit the budget, targets and configured minimums. The money can remain unallocated.")
    st.metric("Estimated leftover cash", f"₪{float(pending['leftover_ils']):,.2f}")
    st.caption("Unknown broker minimums are not invented. Whole-unit constraints can leave cash unused. This buy list is a suggestion, not an executed order.")
    with st.form(f"rebalance_confirm_{pending['id']}"):
        st.subheader("Record completed purchases")
        st.caption("After trading, enter units actually bought and actual ₪ paid (including fees charged to this cash budget). For USD orders, enter the ₪ equivalent you actually used. Zero means not bought. Unspent cash stays in this shared account.")
        confirmations = [{"Security": row["id"], "Units bought": 0, "Actual paid (₪)": 0.} for row in pending["orders"]]
        confirmed = st.data_editor(pd.DataFrame(confirmations, columns=["Security", "Units bought", "Actual paid (₪)"]), hide_index=True,
            disabled=["Security"], column_config={"Units bought": st.column_config.NumberColumn(min_value=0, step=1, format="%d"),
                                                  "Actual paid (₪)": st.column_config.NumberColumn(min_value=0., format="%.2f")}, key=f"rebalance_confirmation_{pending['id']}")
        acknowledge = st.checkbox("I confirm these purchases and the cash deposited. This does not place orders.")
        done = st.form_submit_button("Done — record buys and remaining cash", type="primary")
    if done:
        if not acknowledge:
            st.error("Confirm the completed purchases before recording them.")
            return
        try:
            confirmation_rows = [{"id": row["Security"], "units": row["Units bought"], "paid_ils": row["Actual paid (₪)"]} for row in confirmed.to_dict("records")]
            updated = apply_purchases(account, pending, confirmation_rows, context)
            updated["updated_at"] = utc_now()
            if _save(updated, commit_account):
                st.session_state["rebalance_reset_money"] = True
                st.session_state["rebalance_message"] = "Confirmed units and remaining cash saved to your shared account."
                st.rerun()
        except ValueError as exc:
            st.error(str(exc))
