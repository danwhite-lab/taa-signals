from haa.portfolio import aggregate_holdings, aggregate_holdings_by_currency, convert_currency, execution_security_label, funding_plan, total_weight


def test_aggregate_holdings_combines_duplicate_and_multi_asset_sleeves():
    sleeves = [
        {"name": "HAA", "weight": 60, "target_weights": {"SPY": 1.0}},
        {"name": "Compass", "weight": 40, "target_weights": {"SPY": .5, "IEF": .5}},
    ]
    result = aggregate_holdings(sleeves)
    assert result["SPY"] == {"weight": .8, "sleeves": ["HAA", "Compass"]}
    assert result["IEF"] == {"weight": .2, "sleeves": ["Compass"]}
    assert total_weight(sleeves) == 100


def test_total_weight_allows_drafts_to_be_flagged_by_the_ui():
    assert total_weight([{"weight": 45}, {"weight": 50}]) == 95


def test_mixed_currency_funding_plan_uses_one_total_ils_portfolio_value():
    plan = funding_plan(
        [
            {"id": 1, "weight": 50, "currency": "USD"},
            {"id": 2, "weight": 50, "currency": "ILS"},
        ],
        total_ils=370_000,
        ils_per_usd=3.7,
    )

    assert plan["total_ils"] == 370_000
    assert plan["total_usd"] == 100_000
    assert plan["required"] == {"USD": 50_000, "ILS": 185_000}
    assert plan["sleeves"][0]["allocation_ils"] == 185_000
    assert plan["sleeves"][0]["allocation_native"] == 50_000


def test_ils_only_funding_plan_needs_no_usd_amount():
    plan = funding_plan(
        [
            {"id": 1, "weight": 100, "currency": "ILS"},
        ],
        total_ils=222_000,
        ils_per_usd=3.7,
    )

    assert plan["total_ils"] == 222_000
    assert plan["total_usd"] == 60_000
    assert plan["required"] == {"USD": 0.0, "ILS": 222_000}
    assert convert_currency(10_000, "USD", "ILS", 3.7) == 37_000


def test_holdings_are_grouped_by_execution_currency():
    grouped = aggregate_holdings_by_currency([
        {"name": "USD sleeve", "weight": 50, "currency": "USD", "target_weights": {"SPY": 1.0}},
        {"name": "ILS sleeve", "weight": 50, "currency": "ILS", "target_weights": {"CSPX_IL": 1.0}},
    ])

    assert grouped["USD"]["SPY"]["weight"] == .5
    assert grouped["ILS"]["CSPX_IL"]["weight"] == .5


def test_execution_security_labels_keep_canonical_symbols_out_of_calculation_logic():
    assert execution_security_label("CSPX_IL", "ILS") == "CSPX — 1159250"
    assert execution_security_label("IEF_IL", "ILS") == "IEF — iShares $ Treasury Bond 7–10yr UCITS — 1159268"
    assert execution_security_label("SPMO_IL", "ILS") == "MTF Tracking S&P 500 Momentum (4D) — 5140850"
    assert execution_security_label("AYALON_KASPIT", "ILS") == "Keren Kaspit — 5136866"
    assert execution_security_label("XLE", "ILS") == "XLE — KSM ETF S&P Energy — 1145903"
    assert execution_security_label("XLK", "ILS") == "XLK — iShares S&P 500 IT UCITS — 1159193"
    assert execution_security_label("XLU", "ILS") == "XLU — MTF S&P Utilities — 1150507"
    assert execution_security_label("XLP", "ILS") == "XLP — MTF S&P Consumer Staples — 1150366"
    assert execution_security_label("XLV_IL", "ILS") == "MTF סל S&P Health Care (4D) — 1150390"
    assert execution_security_label("IEF", "ILS") == "IEF — iShares $ Treasury Bond 7–10yr UCITS — 1159268"
    assert execution_security_label("SPY", "ILS") == "CSPX — 1159250"
    assert execution_security_label("VNQ", "ILS") == "IBI DJ US Real Estate — 5131834"
    assert execution_security_label("BIL", "USD") == "BIL USD - 5139076"
    assert execution_security_label("QQQ", "ILS") == "QQQ — 1186063"
    assert execution_security_label("DBC", "ILS") == "GLDM proxy — 1147875"
    assert execution_security_label("GLDM", "ILS") == "GLDM proxy — 1147875"
    assert execution_security_label("VXUS", "ILS") == "VXUS proxy — 5142476"
    assert execution_security_label("ACWX", "ILS") == "ACWX proxy — 5142476"
    assert execution_security_label("TLT", "ILS") == "IEF proxy — 1159268"
    assert execution_security_label("SPY", "USD") == "SPY"
