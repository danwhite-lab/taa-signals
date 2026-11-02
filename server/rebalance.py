"""Account notebook orchestration only. Allocation and recording stay in haa.

No brokerage writes, private shared cache, database save path, or Streamlit import.
"""
from copy import deepcopy
from uuid import UUID, uuid4
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from haa import data
from haa.constants import ASSETS, FRED_ASSETS, OECD_CLI_DIFFUSION_ASSET
from haa.model_catalog import MODEL_CATALOG
from haa.buy_and_hold_funds import BUY_AND_HOLD_FUNDS
from haa.rebalance_holdings import (empty_account, validate_account, number, security,
    execution_security, combined_targets, rebalance_targets, compare_holdings,
    make_buy_plan, apply_purchases, fingerprint, CompanionError, excluded_holdings)
from haa.tase_data import TASE_ISRAEL_ASSET_IDS
from haa.portfolio import EXECUTION_SECURITY_LABELS
from . import private_api as private, rebalance_quotes as market
from .rebalance_editor import _preview_positions

router = APIRouter()


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: str | None = None
    account_hash: str | None = None
    new_money: str = "0"


class Editor(Request):
    rows: list[dict] = Field(max_length=200)
    cash: str
    manual_fx: str = ""
    manual_fx_date: str | None = None


class Recording(Request):
    plan: dict
    confirmations: list[dict] = Field(max_length=200)
    acknowledge: bool = False


def loaded(session):
    workspace = private.workspace(session)
    try:
        account = validate_account(workspace["payload"].get("holdings_account", empty_account()))
    except Exception:
        raise HTTPException(400, "Saved holdings could not be read. No saved data has been changed.") from None
    return workspace, account, private.portfolios(session)


def checked(account, expected):
    if expected is not None and fingerprint(account) != expected:
        raise HTTPException(409, "Holdings changed. Sync is paused; reload before saving. Nothing was overwritten.")


def known_instruments():
    assets = tuple(dict.fromkeys(a for m in MODEL_CATALOG for a in getattr(m.model_class, "data_assets", ASSETS)))
    # An index is a data series, never a fund a user can hold. Keep unexpected
    # invalid assets loud instead of broadly swallowing security() errors.
    non_tradable = {item.holding_asset for item in BUY_AND_HOLD_FUNDS.values()
                    if item.price_only or (item.yahoo_ticker or "").startswith("^")}
    assets = tuple(asset for asset in assets if asset not in non_tradable)
    yahoo = tuple(a for a in assets if a not in (*TASE_ISRAEL_ASSET_IDS, *FRED_ASSETS, OECD_CLI_DIFFUSION_ASSET))
    instruments = {}
    for item in [*(security(a, "US") for a in yahoo), *(execution_security(a, "ILS") for a in TASE_ISRAEL_ASSET_IDS)]:
        instruments[item["id"]] = item
    return instruments, yahoo


def selected_portfolio(portfolios, portfolio_id):
    options = {p["id"]: p for p in portfolios}
    default = next((item for item in portfolios if item.get("is_default") is True), None)
    selected = portfolio_id or (default or {}).get("id")
    return options, options.get(selected) if selected in options else default or next(iter(options.values()), None)


def targets_for(workspace, portfolios, portfolio_id, account):
    private.checked_allocation_mode(workspace["payload"])
    instruments, yahoo = known_instruments()
    instruments.update({k: {f: row[f] for f in ("id", "identifier", "market", "currency", "label")} for k, row in account["positions"].items()})
    options, portfolio = selected_portfolio(portfolios, portfolio_id)
    # The Rebalance page always opens on the saved default.  A picker change is
    # still honoured for that request, but an obsolete workspace preference
    # must never silently replace the user's default portfolio.
    if portfolio_id and portfolio_id not in options:
        raise HTTPException(400, "Reload and choose an available saved portfolio.")
    source = "Workspace ticker settings; uploaded replacements are not stored in the workspace and are unavailable here."
    rows, targets, errors, diagnostics = [], {}, [], []
    try:
        raw = workspace["payload"].get("ticker_text")
        skipped = []
        if raw is not None:
            # Keep parser validation strict for retained roles. Only complete
            # ROLE=TICKER lines for catalogue roles that no longer exist are
            # ignored, so an old preference cannot blank all targets.
            retained = []
            for entry in raw.replace(",", "\n").splitlines():
                stripped = entry.strip()
                role = stripped.split("=", 1)[0].strip().upper() if "=" in stripped else None
                if role and role not in yahoo:
                    skipped.append(role)
                else:
                    retained.append(entry)
            retained_text = "\n".join(retained)
            try:
                tickers = data.parse_ticker_map(retained_text, yahoo)
            except ValueError as exc:
                # Only a complete, otherwise-valid old map may receive new
                # catalogue defaults. Other validation remains strict.
                if not str(exc).startswith("Missing Yahoo ticker mapping for:"):
                    raise
                supplied = {entry.split("=", 1)[0].strip().upper() for entry in retained if "=" in entry}
                missing = sorted(set(yahoo) - supplied)
                defaults = data.default_ticker_map(yahoo)
                tickers = data.parse_ticker_map(retained_text + "\n" + "\n".join(f"{role}={defaults[role]}" for role in missing), yahoo)
                note = "Used built-in default tickers for missing roles: " + ", ".join(missing) + ". Saved settings were not changed."
                source += " " + note
                diagnostics.append({"stage": "ticker", "code": "ticker_defaulted", "message": note, "roles": missing})
            if skipped:
                source += " Ignored saved lines for removed roles: " + ", ".join(sorted(set(skipped)))
        else:
            tickers = data.default_ticker_map(yahoo)
        if raw is None:
            source = "Default ticker settings; no workspace ticker settings or uploaded replacements are available. No source was silently substituted."
        if portfolio:
            sleeves = portfolio["payload"]["sleeves"]
            if len({s["model"] for s in sleeves}) != len(sleeves):
                raise ValueError()
            known_labels = {item.label for item in MODEL_CATALOG}
            if any(not isinstance(s.get("model"), str) or s["model"] not in known_labels for s in sleeves):
                safe = "The selected portfolio contains an unavailable saved strategy. Choose an available model on the Portfolio page."
                return portfolio, instruments, rows, {}, [safe], source, [{"stage": "model", "code": "saved_model_unavailable", "message": safe}]
            signals, errors = market.load_portfolio_signals(tuple(s["model"] for s in sleeves), tuple(tickers.items()), {})
            if errors:
                labels = [s["model"] for s in sleeves]
                safe = "Completed targets are unavailable for: " + ", ".join(labels) + ". Check those sleeve data and signal settings."
                errors, diagnostics = [safe], [{"stage": "sleeve", "code": "sleeve_unavailable", "message": safe, "models": labels}]
            if not errors:
                by_name = {s["name"]: s for s in signals}
                rows = [{**by_name[s["model"]], "weight": s["weight"]} for s in sleeves]
                target_instruments, targets = combined_targets(rows)
                for key, item in target_instruments.items():
                    if key in instruments and instruments[key]["currency"] != item["currency"]:
                        raise ValueError()
                    instruments[key] = item
    except ValueError as exc:
        message = str(exc)
        if "Missing Yahoo ticker mapping" in message: code, safe = "ticker_missing", "Saved ticker settings are missing a current data role. Check Yahoo Finance ticker sources."
        elif "appears more than once" in message: code, safe = "ticker_duplicate", "Saved ticker settings repeat a current data role. Check Yahoo Finance ticker sources."
        elif "cannot be empty" in message: code, safe = "ticker_blank", "Saved ticker settings have a blank ticker. Check Yahoo Finance ticker sources."
        elif "ROLE=TICKER" in message: code, safe = "ticker_malformed", "Saved ticker settings contain an invalid entry. Use ROLE=TICKER lines."
        else: code, safe = "target_validation", "Portfolio targets could not be combined. Check the selected portfolio's sleeves and weights."
        errors, diagnostics = [safe], [{"stage": "ticker" if code.startswith("ticker_") else "targets", "code": code, "message": safe}]
        targets = {}
    except Exception:
        safe = "A selected sleeve could not produce a completed target. Check its data and signal status."
        errors, diagnostics = [safe], [{"stage": "sleeve", "code": "sleeve_unavailable", "message": safe}]
        targets = {}
    return portfolio, instruments, rows, targets, errors, source, diagnostics


def sell_review(account, targets, instruments, available=True):
    """Review full exits only; never change holdings or finance buy orders."""
    excluded = excluded_holdings(account, targets)
    result = []
    for key, position in sorted(account["positions"].items()):
        units = number(position["units"])
        if not units:
            continue
        identifier = instruments[key]["identifier"].upper()
        protected = identifier == "1159250" or identifier.split(".")[0] == "CSPX"
        sell = (available and not protected and key not in excluded
                and not position.get("companion_of") and number(targets.get(key, 0)) == 0)
        result.append({"id": key, "action": "sell" if sell else "keep",
                       "before_units": str(units), "after_units": "0" if sell else str(units)})
    return result


def snapshot(workspace, account, portfolios, request):
    started = perf_counter()
    mode = private.checked_allocation_mode(workspace["payload"])
    portfolio, instruments, sources, targets, errors, source, diagnostics = targets_for(workspace, portfolios, request.portfolio_id, account)
    targets = rebalance_targets(account, targets)
    excluded = excluded_holdings(account, targets)
    visible = set(targets) | set(account["positions"])
    quotes = {k: market.unit_quote(instruments[k], account["positions"].get(k, {})) for k in sorted(visible)}
    relevant = set(targets) | {k for k, row in account["positions"].items() if number(row["units"])}
    uses_usd = any(instruments[k]["currency"] == "USD" for k in relevant)
    fx = market.fx_quote(account) if uses_usd else {"price": "1", "fresh": True, "source": "Not needed: ILS only"}
    # A published but late price remains usable. Keep "blocked" exclusively
    # for prices that cannot value a holding at all.
    blocked = {k for k in relevant if quotes[k].get("error") or quotes[k].get("price") is None}
    stale = {k for k in relevant if k not in blocked and not quotes[k].get("fresh")}
    held_blocked = {k for k in blocked - excluded if number(account["positions"].get(k, {}).get("units", 0))}
    missing_held = {k for k in held_blocked if quotes[k].get("error") or not quotes[k].get("price")}
    needs_fx = any(instruments[k]["currency"] == "USD" for k in relevant - excluded)
    rebalance_fx = fx if needs_fx else {"price": "1", "fresh": True}
    comparison, total, full_total = [], None, None
    if not missing_held and not rebalance_fx.get("error") and rebalance_fx.get("price") is not None:
        try:
            comparison, _, total = compare_holdings(account, instruments, targets, quotes, rebalance_fx["price"])
        except (ValueError, KeyError, TypeError):
            pass
    try:
        full = deepcopy(account)
        for row in full["positions"].values():
            row["outside_rebalance"] = False
            row.pop("companion_of", None)
        if not fx.get("error"):
            _, _, full_total = compare_holdings(full, instruments, {}, quotes, fx["price"])
    except (ValueError, KeyError, TypeError):
        pass
    if not comparison:
        comparison = [{"id": k, "Fund": instruments[k]["label"], "Target %": targets.get(k, 0), "Actual %": None,
                       "Status": "Cannot price" if k in blocked else "Valuation incomplete"} for k in sorted(visible)]
    for row in comparison:
        if not portfolio or errors:
            row.update({"Target %": None, "Status": "Target unavailable"})
        if row["id"] in excluded:
            row.update({"Target %": None, "Actual %": None, "Status": "Outside the rebalance"})
        anchor = account["positions"].get(row["id"], {}).get("companion_of")
        if anchor:
            row.update(companion_of=anchor, **{"Target %": None, "Actual %": None,
                "Status": "Outside the rebalance" if row["id"] in excluded else "Companion"})
        row["target_display"] = f'{row["Target %"]:.2%}' if row.get("Target %") is not None else "—"
        row["actual_display"] = f'{row["Actual %"]:.2%}' if row.get("Actual %") is not None else "—"
    eligible = {k: w for k, w in targets.items() if k not in blocked}
    ready = bool(portfolio and not errors and total is not None and not held_blocked and not rebalance_fx.get("error") and rebalance_fx.get("price") is not None and eligible)
    active_quotes = {k: quotes[k] for k in sorted(relevant)}
    context = {"portfolio": portfolio, "targets": targets, "quotes": active_quotes, "fx": fx, "allocation_mode": mode,
               "new_money": str(number(request.new_money)), "excluded": sorted(blocked), "editor": fingerprint(account)}
    editor_rows = []
    for key in sorted(visible):
        p, q = account["positions"].get(key, {}), quotes[key]
        current = q.get("fresh") and not q.get("error") and q.get("price")
        editor_rows.append({"Security": key, "Fund": instruments[key]["label"], "Currency": instruments[key]["currency"],
            "Outside the rebalance": p.get("outside_rebalance", False), "Enter as": "Units", "Units": f'{number(p.get("units", 0)):.2f}', "Units edited": False,
            "Value (₪ / $)": f'{number(p.get("units", 0)) * number(q["price"], positive=True):.2f}' if (not q.get("error") and q.get("price") is not None) else "",
            "Manual price per unit": p.get("manual_price"), "Price date": p.get("manual_price_date"),
            "Minimum order (₪)": p.get("minimum_ils", "0"), "Remove": False})
        if p.get("companion_of"):
            editor_rows[-1]["Companion of"] = p["companion_of"]
    return {"workspace_revision": workspace["revision"], "account": account, "account_hash": fingerprint(account),
        "portfolios": [{"id": p["id"], "name": p["name"], "is_default": p.get("is_default") is True} for p in portfolios], "portfolio_id": portfolio["id"] if portfolio else None, "allocation_mode": mode,
        # The add-holding catalogue is requested separately.  The initial page
        # only needs instruments already held or targeted.
        "instruments": {key: instruments[key] for key in visible}, "rows": editor_rows, "quotes": quotes, "fx": fx, "source_settings": source,
        "sell_review": sell_review(account, targets, instruments, bool(portfolio and not errors)),
        "signals": sources, "errors": errors, "target_diagnostics": diagnostics, "targets": targets, "eligible": eligible, "comparison": comparison,
        "target_funds": [{"id": k, "label": target_display_name(k, instruments[k])} for k in targets],
        "total_ils": str(total) if total is not None else None, "full_total_ils": str(full_total) if full_total is not None else None,
        "total_display": f"₪{total:,.2f}" if total is not None else "Unavailable",
        "full_total_display": f"₪{full_total:,.2f}" if full_total is not None else "Unavailable",
        "blocked": sorted(blocked), "stale": sorted(stale), "held_blocked": sorted(held_blocked), "partial": bool(blocked-excluded),
        "ready": ready, "context": context, "rebalance_fx": rebalance_fx,
        "overweight": any(r["Status"] == "Overweight" for r in comparison),
        "seconds": round(perf_counter()-started, 6)}


def target_display_name(key, instrument):
    """Prefer existing friendly labels, resolving aliases by actual security ID."""
    label = instrument.get("label", "")
    if label and label not in {key, instrument["identifier"]} and not ("_" in label and label.isupper() and " " not in label):
        return label
    for (currency, asset), friendly in EXECUTION_SECURITY_LABELS.items():
        if currency == instrument["currency"] and instrument["market"] == "TASE" and TASE_ISRAEL_ASSET_IDS.get(asset) == instrument["identifier"]:
            return friendly
    return key


def safe(operation):
    try:
        return operation()
    except HTTPException:
        raise
    except CompanionError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception:
        raise HTTPException(400, "Check the entered units, security details and dated manual prices. No data was saved.") from None


@router.get("/api/rebalance")
def get_page(portfolio_id: str | None = None, session=Depends(private.authenticated)):
    return safe(lambda: snapshot(*loaded(session), Request(portfolio_id=portfolio_id)))


@router.get("/api/rebalance/instruments")
def instruments(session=Depends(private.authenticated)):
    return safe(lambda: {"instruments": known_instruments()[0]})


@router.post("/api/rebalance/refresh")
def refresh(body: Request, session=Depends(private.authenticated)):
    market.clear_rebalance_quotes()
    return safe(lambda: snapshot(*loaded(session), body))


@router.post("/api/rebalance/security")
def add_security(body: dict, session=Depends(private.authenticated)):
    def add():
        if set(body) - {"identifier", "market", "currency"}:
            raise ValueError()
        return security(body["identifier"], body["market"], body.get("currency"))
    return safe(add)


def semantic(account):
    result = deepcopy(account)
    for key in ("revision", "last_operation_id", "updated_at"):
        result.pop(key, None)
    for p in result["positions"].values():
        p.pop("manual_entered_at", None)
        if not p.get("companion_of"):
            p.pop("companion_of", None)
        for key, default in (("outside_rebalance", False), ("minimum_ils", "0"), ("manual_price", None), ("manual_price_date", None)):
            p.setdefault(key, default)
        for key in ("units", "minimum_ils"):
            p[key] = str(number(p[key]).normalize())
    result.setdefault("manual_fx", None)
    result.setdefault("manual_fx_date", None)
    result["cash_ils"] = str(number(result["cash_ils"]).normalize())
    if result["manual_fx"] is not None:
        result["manual_fx"] = str(number(result["manual_fx"]).normalize())
    return result


@router.post("/api/rebalance/editor")
def editor(body: Editor, session=Depends(private.authenticated)):
    def prepare():
        workspace, account, portfolios = loaded(session)
        checked(account, body.account_hash)
        if not body.cash.strip():
            raise HTTPException(400, "Enter unallocated account cash, or enter 0 if there is none.")
        _, instruments, _, targets, _, _, _ = targets_for(workspace, portfolios, body.portfolio_id, account)
        seen = set()
        for row in body.rows:
            key = row["Security"]
            if key in seen:
                raise ValueError()
            seen.add(key)
            if key not in instruments:
                m, identifier = key.split(":", 1)
                item = security(identifier, m, row["Currency"])
                if item["id"] != key:
                    raise ValueError()
                instruments[key] = item
            if row.get("Enter as") not in {"Units", "Value"} or type(row.get("Outside the rebalance", False)) is not bool:
                raise ValueError()
            if row.get("Companion of") is not None and not isinstance(row["Companion of"], str):
                raise CompanionError("Companion of must be a valid security ID, or empty.")
            # A two-decimal display must not round stored fractional US units.
            # The browser marks an explicit units edit; unchanged cells retain
            # their exact confirmed decimal string. Value conversion stays in
            # the verbatim helper below.
            if row.get("Units edited") is False and key in account["positions"]:
                row["Units"] = account["positions"][key]["units"]
        positions, preview, errors = _preview_positions(account, instruments, body.rows)
        if errors:
            return {"errors": errors, "preview": preview, "account": None}
        candidate = deepcopy(account)
        candidate.update(positions=positions, cash_ils=str(number(body.cash)),
                         manual_fx=str(number(body.manual_fx, positive=True)) if body.manual_fx and number(body.manual_fx) else None,
                         manual_fx_date=body.manual_fx_date if body.manual_fx and number(body.manual_fx) else None)
        validate_account(candidate)
        rebalance_targets(candidate, targets)
        if account.get("last_operation_id") and semantic(candidate) == semantic(account):
            candidate = account
        else:
            candidate.update(revision=account["revision"]+1, updated_at=market.utc_now(), last_operation_id=str(uuid4()))
        for p in preview:
            for field in ("Current value (₪ / $)", "Units to save"):
                p[field] = f"{p[field]:,.2f}" if p[field] is not None else "—"
            if p["Price observation date"] is not None:
                p["Price observation date"] = str(p["Price observation date"])
        return {"errors": [], "preview": preview, "account": candidate,
                "quotes": {k: market.unit_quote(instruments[k], p) for k, p in positions.items()}}
    return safe(prepare)


def planned(state, request):
    if not state["ready"]:
        raise HTTPException(400, "A valuation is required. Check the missing price and FX details.")
    return make_buy_plan(state["account"], state["instruments"], state["eligible"], state["quotes"],
                         state["rebalance_fx"]["price"], request.new_money, state["context"], state["allocation_mode"])


@router.post("/api/rebalance/plan")
def plan(body: Request, session=Depends(private.authenticated)):
    def generate():
        workspace, account, portfolios = loaded(session)
        checked(account, body.account_hash)
        state = snapshot(workspace, account, portfolios, body)
        result = planned(state, body)
        return {"plan": result, "state": state}
    return safe(generate)


@router.post("/api/rebalance/record")
def record(body: Recording, session=Depends(private.authenticated)):
    def prepare():
        workspace, account, portfolios = loaded(session)
        UUID(body.plan["id"])
        if not body.acknowledge:
            raise HTTPException(400, "Confirm the completed purchases before recording them.")
        if account.get("last_operation_id") == body.plan["id"]:
            return {"account": account}
        checked(account, body.account_hash)
        state = snapshot(workspace, account, portfolios, body)
        expected = planned(state, body)
        if {k: v for k, v in expected.items() if k != "id"} != {k: v for k, v in body.plan.items() if k != "id"}:
            raise HTTPException(409, "Inputs changed. Generate a fresh buy list before recording purchases.")
        candidate = apply_purchases(account, body.plan, body.confirmations, state["context"])
        candidate["updated_at"] = market.utc_now()
        return {"account": candidate}
    return safe(prepare)
