"""Generate the public picker data from repository declarations, with no data fetch.

Run from the repository root with PYTHONPATH=src:. python scripts/build_picker_metadata.py.
The small label index is used by closed views. Association details are a lazy web chunk.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from haa import constants as c
from haa.buy_and_hold_funds import BUY_AND_HOLD_FUNDS
from haa.data import default_ticker_map
from haa.model_catalog import MODEL_CATALOG
from haa.portfolio import EXECUTION_SECURITY_LABELS, EXECUTION_REPLACEMENTS
from haa.rebalance_holdings import execution_security, security
from haa.strategies import buy_and_hold as bh
from haa.strategies.inflation_compass_steady import InflationCompassBase
from haa.strategies.growth_inflation import GrowthInflationBase
from haa.tase_data import TASE_ISRAEL_ASSET_IDS, TASE_ETF_ASSETS

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "web/content"


def inputs(model):
    """Return execution roles and signal inputs, keeping timing and holdings separate."""
    cls = model.model_class
    family = model.strategy
    signal = getattr(cls, "signal_assets", None)
    if family == "Buy and Hold":
        if cls is bh.TA125SmartMomentum:
            return (c.TA125_SMART_MOMENTUM_ASSET,), ()
        if cls is bh.BuyAndHoldJapan:
            return (), ()
        return ("ACWI" if cls is bh.BuyAndHoldACWI else cls.holding_asset,), ()
    if family == "Century Momentum":
        return tuple(cls.execution_proxies.values()) if model.implementation == "Israel" else (cls.equity_asset, cls.defensive_asset), signal
    if family == "HAA":
        if model.variant == "Simple":
            return tuple(cls.execution_proxies.values()) if model.implementation == "Israel" else ("SPY", "IEF", "BIL"), c.ASSETS
        if model.variant == "Simple Leveraged 2x":
            return ("SSO", "IEF", "BIL"), c.ASSETS
        if model.variant == "HAA 4 Leveraged 2x":
            return c.HAA4_LEVERAGED_HOLDINGS, signal
        if model.variant == "Classic Leveraged 2x (No QQQ)":
            return c.CLASSIC_LEVERAGED_HOLDINGS, signal
        if model.variant == "Classic (No QQQ)":
            return (*cls.offensive_assets, *cls.defensive_assets), c.CLASSIC_DATA_ASSETS
    if family in {"HAA", "BAA", "VAA", "Chimeric Asset Allocation"}:
        holdings = tuple(dict.fromkeys((*cls.offensive_assets, *cls.defensive_assets)))
        if model.implementation == "Israel":
            holdings = tuple(cls.execution_proxies[asset] for asset in holdings)
        return holdings, signal or c.VAA_G4_DATA_ASSETS
    if family in {"GEM", "GGCEM"}:
        holdings = tuple(cls.execution_proxies.values()) if model.implementation == "Israel" else signal
        return holdings, (*signal, c.OECD_CLI_DIFFUSION_ASSET) if family == "GGCEM" else signal
    if issubclass(cls, InflationCompassBase):
        holdings = tuple(c.INFLATION_COMPASS_ISRAEL_EXECUTION_MAP.values()) if model.implementation == "Israel" else ("XLE", "XLK", "XLU", "XLP", "IEF")
        return holdings, ("SPY", *cls.positive_weights, *cls.negative_weights, *c.FRED_ASSETS)
    if issubclass(cls, GrowthInflationBase):
        return tuple(dict.fromkeys(asset for _, weights in cls.allocations.values() for asset in weights)), ("SPY", *cls.positive_sectors, *cls.negative_sectors)
    if family == "Orthogonal Alpha":
        return ("QLD", "BTAL"), signal
    if family == "Momentum-Correlation Triplet":
        return (*cls.candidate_assets, "BIL"), signal
    if family == "A-RVol Shifter":
        if model.implementation == "Documented interpretation":
            return ("TQQQ", "QLD", "BIL"), signal
        return ("RVOL_3X_IL", "RVOL_QQQ_IL", "RVOL_CASH_IL"), signal
    return None, signal


def metadata():
    overrides = json.loads((ROOT / "data/picker_display_overrides.json").read_text())
    words = json.loads((CONTENT / "pickers.json").read_text())
    known, labels, aliases = {}, defaultdict(set), defaultdict(set)
    for (market, identifier), replacement in EXECUTION_REPLACEMENTS.items():
        for listing, number in ((market, identifier), replacement):
            item = security(number, listing)
            known[item["id"]] = item
    for asset, number in TASE_ISRAEL_ASSET_IDS.items():
        history = security(number, "TASE")
        known.setdefault(history["id"], history)
        aliases[history["id"]].add(asset)

    def register(item, asset):
        key = item["id"]
        known[key] = item
        labels[key].add(item["label"])
        # This is only the known broker-facing label, never an input or saved value.
        labels[key].add(re.sub(r"\s+[-–—]\s+\d{7}$", "", item["label"]))
        if asset != item["identifier"] and (item["market"] == "US" or TASE_ISRAEL_ASSET_IDS.get(asset) == item["identifier"]):
            aliases[key].add(asset)
        return key

    for currency, asset in EXECUTION_SECURITY_LABELS:
        register(execution_security(asset, currency), asset)
    excluded = {*c.FRED_ASSETS, c.OECD_CLI_DIFFUSION_ASSET, *TASE_ISRAEL_ASSET_IDS,
                *(fund.holding_asset for fund in BUY_AND_HOLD_FUNDS.values() if fund.price_only)}
    for model in MODEL_CATALOG:
        for asset in getattr(model.model_class, "data_assets", c.ASSETS):
            if asset not in excluded:
                register(security(asset, "US"), asset)

    def series(asset):
        if asset in overrides["series"]:
            return {"identifier": default_ticker_map([asset])[asset], "aliases": [asset], **overrides["series"][asset]}
        if asset in TASE_ISRAEL_ASSET_IDS:
            number = TASE_ISRAEL_ASSET_IDS[asset]
            return {"identifier": number, "name": overrides["funds"].get(f"TASE:{number}", {}).get("name"),
                    "aliases": [asset], "type": "Fund price", "currency": "ILS", "source": "TASE" if asset in TASE_ETF_ASSETS else "Maya"}
        return {"identifier": default_ticker_map([asset])[asset], "name": overrides["funds"].get(f"US:{asset}", {}).get("name"),
                "aliases": [asset], "type": "Market price", "currency": "USD", "source": "Yahoo Finance"}

    model_labels, models = {}, {}
    for model in MODEL_CATALOG:
        cls = model.model_class
        holdings, signal = inputs(model)
        ids = None if holdings is None else list(dict.fromkeys(
            register(execution_security(asset, model.execution_currency), asset) for asset in holdings))
        flags = overrides["versions"].get(model.label, [])
        if model.signal_mode == "daily":
            flags = [*flags, "daily"]
        name = model.strategy
        version = [model.variant, model.implementation]
        if name == "Buy and Hold":
            name = f"{name} · {model.variant}"
            version = [words["israel"] if cls is bh.BuyAndHoldGoldIsrael else model.implementation]
        israel = (model.implementation == "Israel" or model.implementation.startswith("US signals / TASE")
                  or cls in {bh.BuyAndHoldGoldIsrael, bh.BuyAndHoldHarelBondsIsrael, bh.TA125SmartMomentum})
        model_labels[model.label] = {
            "name": name, "family": model.strategy,
            "version": list(dict.fromkeys(filter(None, [*version, *(words[flag] for flag in flags)]))),
            "filter": "israel" if israel else "originals",
        }
        # Validation substitutes are hypothetical unless this implementation actually uses them for returns.
        profile = getattr(cls, "validation_profile", None)
        proxies = []
        if hasattr(cls, "execution_proxies"):
            proxies.extend({"series": series(proxy.proxy_asset), "note": proxy.description}
                           for proxy in profile.proxy_substitutions if proxy.proxy_asset in cls.execution_proxies.values())
        fund = next((fund for fund in BUY_AND_HOLD_FUNDS.values() if fund.name == model.label), None)
        if fund and fund.source_status == "proxy":
            proxies.append({"series": series(fund.holding_asset), "note": fund.source_note})
        models[model.label] = {"held": ids, "signal": None if signal is None else [series(asset) for asset in dict.fromkeys(signal)],
                               "benchmark": series(cls.benchmark_asset) if getattr(cls, "benchmark_asset", None) else None,
                               "proxies": proxies, "notes": model.description,
                               "source": "src/" + cls.__module__.replace(".", "/") + ".py"}
    funds, fund_labels = {}, {}
    for key, item in known.items():
        identifier = item["identifier"]
        raw_labels = {identifier, *labels[key]}
        # Prefer a name from the local asset role, rather than a US return proxy label.
        local = [EXECUTION_SECURITY_LABELS.get(("ILS", asset), "") for asset in aliases[key]]
        local_names = sorted(re.sub(r"\s+[-–—]\s+\d{7}$", "", name) for name in local if name)
        default_name = local_names[0] if local_names else identifier
        provider_ids = default_ticker_map(aliases[key])
        entry = {**item, "name": default_name, "full_name": local_names[0] if local_names else None,
                 "ticker": identifier if item["market"] == "US" else None,
                 "security_number": identifier if item["market"] == "TASE" else None,
                 "aliases": sorted(aliases[key]),
                 "provider_identifiers": sorted({ticker for alias, ticker in provider_ids.items() if ticker != alias and ticker != identifier}),
                 "tracks": None, "underlying_currency": None, "domicile": None, "ucits": None,
                 "source": "src/haa/portfolio.py and src/haa/tase_data.py" if item["market"] == "TASE" else "server/rebalance.py"}
        entry.update(overrides["funds"].get(key, {}))
        funds[key] = entry
        if entry["name"] != identifier or raw_labels != {identifier}:
            fund_labels[key] = {"name": entry["name"], "labels": sorted(raw_labels)}
    return {"models": model_labels, "funds": fund_labels}, {"models": models, "funds": funds}


def write(name, groups):
    # One line per record keeps generated diffs focused on the changed model/fund.
    records = []
    for key, group in groups.items():
        body = ",\n".join(f"    {json.dumps(item, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}"
                           for item, value in sorted(group.items()))
        records.append(f'  "{key}": {{\n{body}\n  }}')
    (CONTENT / name).write_text("{\n" + ",\n".join(records) + "\n}\n", encoding="utf-8")


if __name__ == "__main__":
    labels, details = metadata()
    write("picker-labels.json", labels)
    write("picker-metadata.json", details)
