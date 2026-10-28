"""Verbatim editor conversion helpers; only the UI/cache dependency is adapted."""
from decimal import ROUND_FLOOR
import pandas as pd
from haa.rebalance_holdings import number
from . import rebalance_quotes as market_data
from .rebalance_quotes import utc_now

def _quote_cells(quote):
    available = not quote.get("error") and quote.get("price") is not None
    stamp = quote.get("as_of")
    try:
        observed = pd.Timestamp(stamp).date() if stamp else None
    except (ValueError, TypeError, OverflowError):
        observed = None
    return {"Price per unit (₪ / $)": float(number(quote["price"], positive=True)) if available else None,
            "Price observation date": observed,
            "Price source": "Manual override" if quote.get("field") == "Manual per-unit price" else "Automatic",
            "Price status": "Unavailable" if not available else "Current" if quote.get("fresh") else "Stale"}

def _preview_positions(account, instruments, rows):
    """Draft value-to-unit entry only; use the existing actual-price checks."""
    positions, preview, errors = {}, [], []
    for row in rows:
        key = row["Security"]
        if row["Remove"]:
            continue
        try:
            old = account["positions"].get(key, {})
            price, stamp = row["Manual price per unit"], row["Price date"]
            has_price = price is not None and not pd.isna(price)
            price_date = None if stamp is None or pd.isna(stamp) else pd.Timestamp(stamp).date().isoformat()
            if has_price and not price_date:
                errors.append(f"{instruments[key]['label']}: enter the date of the price you are copying.")
                continue
            position = {**instruments[key], "units": str(number(0 if row["Enter as"] == "Value" else row["Units"])),
                        "outside_rebalance": bool(row.get("Outside the rebalance", False)),
                        "minimum_ils": str(number(row["Minimum order (₪)"])),
                        "manual_price": str(number(price, positive=True)) if has_price else None,
                        "manual_price_date": price_date if has_price else None}
            if row.get("Companion of"):
                position["companion_of"] = row["Companion of"]
            same = position["manual_price"] == old.get("manual_price") and position["manual_price_date"] == old.get("manual_price_date")
            position["manual_entered_at"] = old.get("manual_entered_at") if same else utc_now()
            quote = market_data.unit_quote(instruments[key], position)
            current = bool(not quote.get("error") and quote.get("price"))
            if row["Enter as"] == "Value":
                if not current:
                    errors.append(f"{instruments[key]['label']}: value entry needs a current price; enter a dated manual price in this row first.")
                    continue
                units = number(row["Value (₪ / $)"]) / number(quote["price"], positive=True)
                if instruments[key]["market"] == "TASE":
                    units = units.to_integral_value(rounding=ROUND_FLOOR)
                position["units"] = str(units)
            if instruments[key]["market"] == "TASE" and number(position["units"]) != number(position["units"]).to_integral_value():
                errors.append(f"{instruments[key]['label']}: enter whole TASE units.")
                continue
            positions[key] = position
            preview.append({"Fund": instruments[key]["label"], "Currency": instruments[key]["currency"],
                            "Current value (₪ / $)": float(number(position["units"]) * number(quote["price"], positive=True)) if current else None,
                            "Units to save": float(position["units"]),
                            "Price per unit (₪ / $)": _quote_cells(quote)["Price per unit (₪ / $)"],
                            "Price observation date": _quote_cells(quote)["Price observation date"],
                            "Price status": ("Current published fund valuation" if quote.get("valuation_kind") == "fund_nav" and quote.get("fresh") else "Current" if quote.get("fresh") else "Stale") if current else "Missing — no conversion"})
        except (ValueError, TypeError, KeyError):
            errors.append(f"{instruments[key]['label']}: check the value, units and dated manual price.")
    return positions, preview, errors
