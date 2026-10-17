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
    except Exception:
        st.error("Holdings were not confirmed saved. Check sync status and reload before retrying.")
        return False


def _load_targets(portfolios, known_instruments, account, ticker_items, replacements, signal_source_error):
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
                raise ValueError("Signal source settings need correction.")
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
            errors.append("Portfolio targets are unavailable. Check the portfolio and signal source settings.")
    else:
        st.info("Save a portfolio on the Portfolio page to compare targets. You can still enter your shared holdings below.")


    return portfolio, targets, instruments, source_rows, errors


def _render_editor(account, instruments, targets, commit_account):
    # Stable keys avoid replacing controls on every saved book revision.
    if st.session_state.get("rebalance_editor_seed") != account["revision"] or any(k not in st.session_state for k in ("rebalance_cash", "rebalance_fx", "rebalance_fx_date")):
        st.session_state["rebalance_cash"] = float(account["cash_ils"])
        st.session_state["rebalance_fx"] = float(account.get("manual_fx") or 0)
        st.session_state["rebalance_fx_date"] = date.fromisoformat(account["manual_fx_date"]) if account.get("manual_fx_date") else date.today()
        st.session_state["rebalance_editor_seed"] = account["revision"]
    st.subheader("Your shared holdings")
    st.caption("Store units, not a frozen ₪ valuation. Save changes after editing. Existing fractional US positions are allowed; proposed buys use whole units in both markets. Update your units after splits or other corporate actions.")
    with st.expander("Add a holding", expanded=False):
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
                st.error("Check the entered units, security details and dated manual prices.")
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
        cash = st.number_input("Unallocated account cash (₪)", min_value=0., value=None, step=1., key="rebalance_cash")
        with st.expander("Manual USD/ILS override"):
            st.caption("Optional: dated broker exchange rate in ₪ per $1. Clear it to use the indicative feed.")
            manual_fx = st.number_input("Manual ₪ per $1 (0 = automatic)", min_value=0., value=None, step=.01, format="%.6f", key="rebalance_fx")
            manual_fx_date = st.date_input("FX observation date", value=None, key="rebalance_fx_date")
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
            st.error("Check the entered units, security details and dated manual prices.")



def _record_step(account, pending, context, commit_account):
    if st.button("Record these buys", key="rebalance_record"):
        st.session_state["rebalance_record_id"] = pending["id"]
    if st.session_state.get("rebalance_record_id") != pending["id"]:
        return
    with st.form(f"rebalance_confirm_{pending['id']}"):
        st.subheader("Record these buys")
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
            st.error("Check the confirmed units and payments, or refresh the buy list.")



def _manual_price(key, account, instrument, commit_account):
    with st.form(f"rebalance_manual_{fingerprint(key)[:12]}"):
        left, middle, right = st.columns([1.3, 1.2, 1])
        price = left.number_input(f"Manual per-unit price ({instrument['currency']})", min_value=0., value=0., format="%.6f", key=f"quick_price_{key}")
        observed = middle.date_input("Observation date", value=date.today(), key=f"quick_date_{key}")
        save = right.form_submit_button("Use manual price")
    if save:
        try:
            updated = deepcopy(account)
            position = updated["positions"].setdefault(key, {**instrument, "units": "0"})
            position.update(manual_price=str(number(price, positive=True)), manual_price_date=observed.isoformat(), manual_entered_at=utc_now())
            updated.update(revision=account["revision"]+1, updated_at=utc_now(), last_operation_id=str(uuid4()))
            if _save(updated, commit_account):
                st.rerun()
        except (ValueError, TypeError):
            st.error("Enter a positive native-currency per-unit price and its actual observation date.")


def render_rebalance_page(portfolios, known_instruments, ticker_items, replacements, commit_account, signal_source_error=None):
    if st.session_state.pop("rebalance_reset_money", False):
        st.session_state["rebalance_new_money"] = 0.
    try:
        account = validate_account(st.session_state.get("holdings_account", empty_account()))
    except (ValueError, KeyError, TypeError):
        st.error("Saved holdings could not be read. No saved data has been changed.")
        return
    value_box = st.container()
    warning_box = st.container()
    comparison_box = st.container()
    new_money = st.number_input("New money (₪)", min_value=0., value=0., step=100., format="%.0f", key="rebalance_new_money")
    action_box = st.container()
    results_box = st.container()
    with st.expander("Portfolio & signal dates", expanded=False):
        portfolio, targets, instruments, source_rows, errors = _load_targets(
            portfolios, known_instruments, account, ticker_items, replacements, signal_source_error)
        for source in source_rows:
            st.caption(f"{source['name']}: actionable signal {source['signal_date']}")
            if source["source_notes"]:
                st.caption("Source substitutions: " + ", ".join(source["source_notes"]))
        if errors:
            st.caption("Targets are unavailable; check the portfolio and source settings.")
    with st.expander("Holdings, units & manual overrides", expanded=False):
        _render_editor(account, instruments, targets, commit_account)

    relevant = set(targets) | {k for k, row in account["positions"].items() if number(row["units"])}
    quotes = {k: market_data.unit_quote(instruments[k], account["positions"].get(k, {})) for k in sorted(relevant)}
    uses_usd = any(instruments[k]["currency"] == "USD" for k in relevant)
    fx = market_data.fx_quote(account) if uses_usd else {"price": "1", "fresh": True, "source": "Not needed: ILS only"}
    blocked = {k for k, q in quotes.items() if q.get("error") or not q.get("fresh")}
    held_blocked = {k for k in blocked if number(account["positions"].get(k, {}).get("units", 0))}
    missing_held = {k for k in held_blocked if quotes[k].get("error") or not quotes[k].get("price")}

    with st.expander("Prices, FX & sync details", expanded=False):
        if st.button("Refresh prices and targets", key="rebalance_refresh"):
            market_data.clear_rebalance_quotes()
            st.session_state.pop("rebalance_pending", None)
            st.rerun()
        st.caption("Actual unadjusted prices only. Public/delayed observations are not guaranteed fills. Five-minute caches. Manual prices are native currency per ONE unit, not agorot or cents.")
        if quotes:
            st.dataframe(pd.DataFrame([{"Security": k, "Price per unit": q.get("price"),
                "Currency": instruments[k]["currency"], "Raw publication (unit unverified)": q.get("raw_published_value"),
                "Observation date": q.get("as_of"), "Retrieved / entered": q.get("fetched_at"),
                "Field": q.get("field"), "Source": q.get("source"),
                "Status": "Cannot price" if q.get("error") else q.get("status")} for k, q in quotes.items()]),
                hide_index=True, use_container_width=True)
        if uses_usd:
            st.dataframe(pd.DataFrame([{"Pair": "ILS per USD", "Rate": fx.get("price"), "Observation date": fx.get("as_of"),
                "Retrieved / entered": fx.get("fetched_at"), "Source": fx.get("source"),
                "Status": "Unavailable" if fx.get("error") else fx.get("status")}]), hide_index=True)
        st.caption("The workspace banner means another save advanced the revision. Reload before saving; safeguards remain active and no holdings are overwritten to dismiss it.")
        if st.session_state.pop("rebalance_message", None):
            st.caption("Shared account changes were confirmed saved.")
        st.caption("Existing unallocated cash is included. Unknown order minimums are not invented. Estimates exclude automatically calculated commissions and spreads.")

    with warning_box:
        for k in sorted(blocked):
            st.caption(f"⚠ {instruments[k]['label']}: price missing or stale.")
            _manual_price(k, account, instruments[k], commit_account)
        if uses_usd and (fx.get("error") or not fx.get("fresh")):
            st.caption("⚠ USD/ILS is missing or stale. Its dated override is in the collapsed holdings section.")
        if st.session_state.get("workspace_conflict"):
            st.caption("Sync paused: reload before saving. Details below.")
        elif st.session_state.get("rebalance_sync_unavailable"):
            st.caption("Sync is temporarily unavailable; saving will retry.")

    comparison, total = [], None
    if not missing_held and not fx.get("error"):
        try:
            comparison, _, total = compare_holdings(account, instruments, targets, quotes, fx["price"])
        except (ValueError, KeyError, TypeError):
            pass
    with value_box:
        st.metric("Account value", f"₪{total:,.2f}" if total is not None else "Unavailable")
    with comparison_box:
        if not comparison:
            comparison = [{"Fund": instruments[k]["label"], "Target %": targets.get(k, 0), "Actual %": None,
                "Status": "Cannot price" if k in blocked else "Valuation incomplete"} for k in sorted(set(targets) | set(account["positions"]))]
        table = pd.DataFrame(comparison, columns=["Fund", "Target %", "Actual %", "Status"])
        if not portfolio or errors:
            table["Target %"] = None
            table["Status"] = "Target unavailable"
        st.dataframe(table.style.format({"Target %": "{:.2%}", "Actual %": "{:.2%}"}, na_rep="—"), hide_index=True, use_container_width=True)

    # Preserve the allocator and its price rules. Skipping an UNHELD fund
    # does not alter account value; keep remaining target weights unchanged.
    eligible = {k: w for k, w in targets.items() if k not in blocked}
    ready = bool(portfolio and not errors and total is not None and not held_blocked and fx.get("fresh") and eligible)
    context = {"portfolio": portfolio, "targets": targets, "quotes": quotes, "fx": fx,
               "new_money": str(number(new_money)), "excluded": sorted(blocked)}
    pending = st.session_state.get("rebalance_pending")
    if pending and (pending["account_hash"] != fingerprint(account) or pending["context_hash"] != fingerprint(context)):
        st.session_state.pop("rebalance_pending", None)
        pending = None
    with action_box:
        generate = st.button("What to buy", key="rebalance_generate", disabled=not ready)
    if generate:
        try:
            pending = make_buy_plan(account, instruments, eligible, quotes, fx["price"], new_money, context)
            st.session_state["rebalance_pending"] = pending
        except (ValueError, KeyError, TypeError):
            st.error("A current valuation is required. Check the price and FX details.")
    if held_blocked:
        with warning_box:
            st.caption("A held fund needs a current manual price before accurate account weights or buys can be calculated.")
    if pending:
        with results_box:
            rows = [{"Fund": instruments[r["id"]]["label"], "Whole units to buy": r["units"], "Estimated cost (₪)": float(r["estimated_ils"])} for r in pending["orders"]]
            if rows:
                st.dataframe(pd.DataFrame(rows).style.format({"Estimated cost (₪)": "{:,.2f}"}), hide_index=True, use_container_width=True)
            else:
                st.caption("No whole-unit order fits the budget, targets and configured minimums.")
            st.caption(f"Leftover: ₪{float(pending['leftover_ils']):,.2f}")
            if blocked:
                st.caption("Partial buy list: unpriced, unheld funds were skipped. Targets were not redistributed.")
            _record_step(account, pending, context, commit_account)
