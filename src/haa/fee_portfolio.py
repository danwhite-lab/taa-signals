"""Replay existing mixed-portfolio execution schedules with monetary fee books.

Only used for opt-in broker fees plus sleeve transfers. A one-off return-stream
rescale cannot model flat fees after capital has moved between sleeves.
Strategy decisions, execution dates and the existing sleeve-transfer tax
approximation are reused, not regenerated here.
"""
import pandas as pd
from .tax import IsraeliTaxState
from .trading_fees import rebalance


def replay(sleeves, results, daily, initial, fees, taxed, tax_rate, mode, cap_sleeve, cap, reset):
    from .mixed_portfolio import _rebalance_dates
    weights = {n: w for n, (w, _) in sleeves.items()}
    dates = daily.index
    books = {b: {n: {"positions": {}, "cash": initial*w, "tax": IsraeliTaxState(tax_rate=tax_rate)}
                 for n, w in weights.items()} for b in ("pre-tax", "after-tax")}
    transfer_tax = IsraeliTaxState(tax_rate=tax_rate)
    transfer_bases = {b: {} for b in books}
    reviews = _rebalance_dates(dates, mode)
    schedules = {n: {pd.Timestamp(r.execution_date): r for _, r in result.audit.iterrows()}
                 for n, result in results.items()}
    previous_targets = {}
    rows, navs, events, audits = [], [], [], []
    previous_date = None
    for date in dates:
        before = {b: sum(sum(s["positions"].values())+s["cash"] for s in book.values()) for b, book in books.items()}
        opening = {b: 0. for b in books}
        paid = {b: 0. for b in books}
        flow_open = flow_close = purchases = 0.
        changed = 0
        for name, (weight, model) in sleeves.items():
            us_daily = model.decisions.attrs.get("execution_frequency") == "daily" and not model.decisions.attrs.get("local_daily_execution")
            scheduled = schedules[name].get(date)
            target = (scheduled.get("target_weights", {scheduled.get("selected_asset"): 1.}) if scheduled is not None
                      else previous_targets.get(name))
            contribution = float(results[name].daily.loc[date, "contribution"])
            if us_daily: flow_open += contribution
            else: flow_close += contribution
            details = []
            for book, states in books.items():
                state = states[name]
                positions = state["positions"]
                close = model.daily_prices
                opens = model.daily_open_prices
                # Match the existing engines: US daily at next open; all other
                # strategy fills at the scheduled close/NAV.
                if previous_date is not None:
                    for asset in positions:
                        prior = close.loc[previous_date, asset]
                        opening[book] += positions[asset] * (opens.loc[date, asset]/prior if opens is not None else 1.)
                        positions[asset] *= (opens if us_daily else close).loc[date, asset]/prior
                opening[book] += state["cash"]
                if previous_date is None: opening[book] += sum(positions.values())
                state["cash"] += contribution
                execute = scheduled is not None and (not us_daily or target != previous_targets.get(name) or contribution)
                if execute:
                    state["cash"], orders, realized = rebalance(positions, state["cash"], target, fees,
                        state["tax"] if book == "after-tax" and taxed else None)
                    paid[book] += sum(o["fee"] for o in orders)
                    details.extend({"book": book, **o} for o in orders)
                    if book == "pre-tax": purchases += sum(o["notional"] for o in orders if o["side"] == "buy")
                    events.extend({"date": date, "signal_date": scheduled.get("signal_date", scheduled.get("decision_date")),
                                   "sold_sleeve": name, "tax_level": "strategy sleeve", **e} for e in realized)
                if us_daily:
                    for asset in positions:
                        positions[asset] *= close.loc[date, asset]/opens.loc[date, asset]
            if details:
                changed += 1
                audits.append({**scheduled.to_dict(), "sleeve": name, "security_trades": details})
            if target is not None: previous_targets[name] = target
        if previous_date is None:
            for book, states in books.items():
                transfer_bases[book] = {n: sum(s["positions"].values())+s["cash"] for n, s in states.items()}
        transferred = False
        transfer_notional = transfer_levy = 0.
        if date in reviews:
            pre_values = {n: sum(s["positions"].values())+s["cash"] for n, s in books["pre-tax"].items()}
            if mode == "annual_target" or pre_values[cap_sleeve]/sum(pre_values.values()) > cap:
                targets = weights.copy()
                if mode == "rvol_cap":
                    targets = {n: reset if n == cap_sleeve else w/(1-weights[cap_sleeve])*(1-reset) for n, w in weights.items()}
                for book, states in books.items():
                    fees_paid, orders, realized = transfer(states, transfer_bases[book], targets, fees,
                        transfer_tax if book == "after-tax" and taxed else None)
                    paid[book] += fees_paid
                    if book == 'pre-tax': transfer_notional = sum(o['notional'] for o in orders)
                    else: transfer_levy = sum(e['tax_paid'] for e in realized)
                    events.extend({"date": date, "tax_level": "portfolio sleeve transfer", **e} for e in realized)
                    audits.append({"execution_date": date, "sleeve": "portfolio transfer", "book": book,
                                   "execution_timing": 'quarter-end close' if mode == 'rvol_cap' else 'year-end close',
                                   "rebalance_mode": mode, "target_weights": targets, "security_trades": orders, "transfer_fees": fees_paid})
                transferred = True
        values = {book: sum(sum(s["positions"].values())+s["cash"] for s in states.values()) for book, states in books.items()}
        row = daily.loc[date].to_dict()
        for book, prefix in (("pre-tax", "pre_tax"), ("after-tax", "after_tax")):
            row[prefix+"_value"] = values[book]
            row[prefix+"_fee"] = paid[book]
            row[prefix+"_monthly_return"] = opening[book]/before[book]*(values[book]-flow_close)/(opening[book]+flow_open)-1
        row["allocation_change"] = changed + int(transferred)
        row['portfolio_rebalance'] = transferred
        row['portfolio_rebalance_tax'] = transfer_levy
        row['portfolio_rebalance_turnover'] = transfer_notional/values['pre-tax']
        row["turnover"] = purchases/before["pre-tax"] + row['portfolio_rebalance_turnover']
        rows.append(row)
        navs.append({n: sum(s["positions"].values())+s["cash"] for n, s in books["pre-tax"].items()})
        previous_date = date
    return pd.DataFrame(rows, index=dates), pd.DataFrame(navs, index=dates), pd.DataFrame(events), pd.DataFrame(audits)


def transfer(states, bases, targets, fees, tax):
    """Transfer at close, charging each security side and retaining sleeve tax model."""
    values = {n: sum(s["positions"].values())+s["cash"] for n, s in states.items()}
    total = sum(values.values())
    epsilon = max(total, 1.)*1e-12
    desired = {n: total*w for n, w in targets.items()}
    orders, events = [], []
    cash = 0.
    for name, state in states.items():
        sale = max(0., values[name]-desired[name])
        if sale <= epsilon: continue
        proportion = sale/values[name]
        proceeds = state["cash"]*proportion
        state["cash"] *= 1-proportion
        for asset, current in list(state["positions"].items()):
            notional = current*proportion
            if notional <= epsilon: continue
            fee = fees.charge(notional)
            proceeds += notional-fee
            state["positions"][asset] -= notional
            state["tax"].cost_bases[asset] = state["tax"].cost_bases.get(asset, 0.)*(1-proportion)
            orders.append({"sleeve": name, "asset": asset, "side": "sell", "notional": notional, "fee": fee})
        sold_basis = bases[name]*proportion
        bases[name] -= sold_basis
        if tax is not None:
            tax.cost_bases[name] = bases[name]+sold_basis
            event = tax.sell(proceeds, asset=name, cost_basis_sold=sold_basis)
            events.append({"sold_sleeve": name, "proceeds": proceeds, **event})
            proceeds -= event["tax_paid"]
        cash += proceeds
    # Cash is distributed to underweight sleeves, then to their existing
    # security mix. No strategy signal is changed by a capital transfer.
    deficits = {}
    for name, state in states.items():
        current = sum(state["positions"].values())+state["cash"]
        deficit = max(0., desired[name]-current)
        if deficit <= epsilon: continue
        if current <= 0: raise ValueError("Cannot fund an empty sleeve without execution holdings.")
        for asset, value in state["positions"].items():
            if value <= epsilon: continue
            key = (name, asset)
            deficits[key] = deficit*value/current
    buys, _ = fees.purchase(cash, deficits)
    for (name, asset), amount in buys.items():
        fee = fees.charge(amount)
        states[name]["positions"][asset] += amount
        states[name]["tax"].buy(asset, amount+fee)
        bases[name] += amount+fee
        cash -= amount+fee
        orders.append({"sleeve": name, "asset": asset, "side": "buy", "notional": amount, "fee": fee})
    if cash > epsilon:
        # Floating residual cash belongs to a funded sleeve, never disappears.
        states[next(iter(states))]["cash"] += cash
    return sum(o["fee"] for o in orders), orders, events
