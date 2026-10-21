"""Opt-in currency-specific broker fees. Legacy engines remain unchanged when off."""
from dataclasses import dataclass
import math


class SleeveTaxBooks:
    """Delegate to the existing ledger; never net losses between sleeves."""
    def __init__(self, tax_rate):
        self.tax_rate = tax_rate
        self.ledgers = {}

    @property
    def cost_bases(self):
        return {a:b for ledger in self.ledgers.values() for a,b in ledger.cost_bases.items()}

    def ledger(self, asset):
        from .tax import IsraeliTaxState
        sleeve = asset.split('::', 1)[0] if '::' in asset else ''
        if sleeve not in self.ledgers:
            self.ledgers[sleeve] = IsraeliTaxState(tax_rate=self.tax_rate)
        return self.ledgers[sleeve]

    def buy(self, asset, amount):
        self.ledger(asset).buy(asset, amount)

    def sell(self, proceeds, asset, cost_basis_sold):
        return self.ledger(asset).sell(proceeds, asset=asset, cost_basis_sold=cost_basis_sold)


@dataclass(frozen=True)
class TradingFees:
    currency: str
    ils_percent: float = .05
    ils_minimum: float = 2.
    usd_flat: float = 5.

    @property
    def active(self):
        return bool(self.ils_percent or self.ils_minimum) if self.currency == 'ILS' else bool(self.usd_flat)

    def __post_init__(self):
        if self.currency not in {"ILS", "USD"}:
            raise ValueError("Trading fees require an explicit ILS or USD execution currency.")
        if any(not math.isfinite(v) or v < 0 for v in (self.ils_percent, self.ils_minimum, self.usd_flat)) or self.ils_percent > 10:
            raise ValueError("Invalid trading fee assumptions.")

    def charge(self, notional):
        if notional <= 0:
            return 0.
        return max(notional * self.ils_percent / 100, self.ils_minimum) if self.currency == "ILS" else self.usd_flat

    def purchase(self, budget, deficits):
        """Proportional purchases whose actual notionals plus fees fit cash.

        No fee on cash that is not traded. Too-small orders fail explicitly;
        they never create negative cash or silently omit a strategy holding.
        """
        needed = sum(deficits.values())
        if needed <= 0 or budget <= 0:
            return {}, 0.
        def cost(net):
            return net + sum(self.charge(net * d / needed) for d in deficits.values())
        floor = self.ils_minimum if self.currency == "ILS" else self.usd_flat
        if budget <= len(deficits) * floor:
            raise ValueError("Trading fees consume purchase cash; increase capital/deposit or reduce fees.")
        lo, hi = 0., min(needed, budget)
        for _ in range(80):
            mid = (lo + hi) / 2
            if cost(mid) <= budget: lo = mid
            else: hi = mid
        buys = {a: lo * d / needed for a, d in deficits.items()}
        return buys, sum(self.charge(v) for v in buys.values())

    def buy_fee(self, budget):
        _, fee = self.purchase(budget, {"asset": budget})
        return fee


def rebalance(positions, cash, weights, fees, tax=None):
    """Execute sales then cash-funded buys; call the existing tax ledger unchanged."""
    from copy import deepcopy
    total = sum(positions.values()) + cash
    epsilon = max(total, 1.) * 1e-12
    def budget(final):
        ledger = deepcopy(tax)
        cost = final
        for asset in dict.fromkeys((*positions, *weights)):
            current = positions.get(asset, 0.)
            target = final*weights.get(asset, 0.)
            delta = target-current
            if abs(delta) <= epsilon: continue
            fee = fees.charge(abs(delta))
            cost += fee
            if delta < 0 and ledger is not None:
                basis = ledger.cost_bases.get(asset, 0.)*(-delta)/current
                cost += ledger.sell(-delta-fee, asset=asset, cost_basis_sold=basis)['tax_paid']
        return cost
    lo, hi = 0., total
    if budget(hi) > total:
        for _ in range(80):
            mid = (lo+hi)/2
            if budget(mid) <= total: lo = mid
            else: hi = mid
        final = lo
    else: final = total
    if final <= epsilon:
        raise ValueError("Trading fees consume portfolio capital; increase capital/deposit or reduce fees.")
    desired = {a: final*w for a, w in weights.items()}
    orders, events = [], []
    for asset, current in list(positions.items()):
        sale = max(0., current - desired.get(asset, 0.))
        if sale <= epsilon: continue
        fee = fees.charge(sale)
        proceeds = sale - fee
        levy = 0.
        if tax is not None:
            basis = tax.cost_bases.get(asset, 0.) * sale / current
            event = tax.sell(proceeds, asset=asset, cost_basis_sold=basis)
            levy = event["tax_paid"]
            events.append({"sold_asset": asset, "proceeds": proceeds, **event})
        positions[asset] -= sale
        cash += proceeds - levy
        orders.append({"asset": asset, "side": "sell", "notional": sale, "fee": fee, "tax_paid": levy})
    deficits = {a: max(0., d-positions.get(a, 0.)) for a, d in desired.items()}
    deficits = {a: d for a, d in deficits.items() if d > epsilon}
    for asset, purchase in deficits.items():
        fee = fees.charge(purchase)
        positions[asset] = positions.get(asset, 0.) + purchase
        cash -= purchase + fee
        if tax is not None: tax.buy(asset, purchase + fee)
        orders.append({"asset": asset, "side": "buy", "notional": purchase, "fee": fee, "tax_paid": 0.})
    if cash < -epsilon:
        raise ValueError("Trading fees exceed available cash; no borrowing is modeled.")
    return max(0., cash), orders, events


def totals(result):
    frame = result.daily if result.daily is not None else result.monthly
    return {book: float(frame[book + "_fee"].sum()) if book + "_fee" in frame else 0.
            for book in ("pre_tax", "after_tax")}
