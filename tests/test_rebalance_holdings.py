from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR

import pytest

from haa.rebalance_holdings import (apply_purchases, combined_targets, compare_holdings, empty_account,
                                   execution_security, make_buy_plan, rebalance_targets, security, validate_account)
from haa.workspace_sync import snapshot, restore


@pytest.mark.parametrize('mode,expected',[
    ('proportional','5e57d6102f6d505c4cacd241be204777da6be13ec6a904a6cb089e0f81be3e5b'),
    ('biggest_gap_first','7d94c327a8107aecf09875cbde9732be37482a1e860992eee0fbfa70f3ab1269')])
def test_no_companion_outputs_match_main_golden_bytes(mode,expected):
    from haa.rebalance_holdings import fingerprint
    account,instruments,quotes,targets=setup_book(units=(3,5),cash=10)
    rows,_,_=compare_holdings(account,instruments,targets,quotes,1)
    assert fingerprint(rows)=='8b0d84b6554a36bb55285c413aa667f4d2f26e95f1b3958deefc8922da104e53'
    plan=make_buy_plan(account,instruments,targets,quotes,1,200,{},allocation_mode=mode)
    plan.pop('id')
    assert fingerprint(plan)==expected


def test_companion_anchor_may_be_unheld_and_fingerprint_invalidates_recording():
    account,instruments,quotes,targets=setup_book(units=(10,0))
    legacy,anchor=list(targets)
    account['positions'][legacy]['companion_of']=anchor
    targets={anchor:1.}
    account['positions'].pop(anchor)
    rows,values,total=compare_holdings(account,instruments,targets,quotes,1)
    assert values[anchor]==total==Decimal('100')
    assert next(r for r in rows if r['id']==anchor)['Actual %']==1.
    plan=make_buy_plan(account,instruments,targets,quotes,1,100,{},allocation_mode='proportional')
    account['positions'][legacy].pop('companion_of')
    with pytest.raises(ValueError,match='changed'):
        apply_purchases(account,plan,[],{})


def setup_book(units=(0, 0), prices=(10, 20), cash=0):
    securities = [security("1149038", "TASE", "ILS", "Nasdaq"), security("1187079", "TASE", "ILS", "Leveraged Nasdaq")]
    instruments = {s['id']: s for s in securities}
    account = empty_account()
    account['cash_ils'] = str(cash)
    for s, quantity in zip(securities, units):
        account['positions'][s['id']] = {**s, 'units': str(quantity)}
    quotes = {s['id']: {'price': str(p), 'fresh': True} for s, p in zip(securities, prices)}
    targets = dict(zip(instruments, [.6, .4]))
    return account, instruments, quotes, targets


@pytest.mark.parametrize('targeted', [False, True])
@pytest.mark.parametrize('quote_state', ['current', 'stale', 'missing'])
@pytest.mark.parametrize('mode', ['biggest_gap_first', 'proportional'])
def test_outside_holding_matches_removal_for_targets_and_buys(targeted, quote_state, mode):
    account, instruments, quotes, targets = setup_book(units=(7, 3), cash=23)
    outside = security('GLD', 'US')
    key = outside['id']
    instruments[key] = outside
    account['positions'][key] = {**outside, 'units': '90', 'outside_rebalance': True}
    quotes[key] = {'price': '10', 'fresh': quote_state == 'current'} if quote_state != 'missing' else {'error': 'Missing'}
    if targeted:
        targets = {k: w / 2 for k, w in targets.items()} | {key: .5}
    removed = deepcopy(account)
    del removed['positions'][key]
    remaining_targets = {k: w for k, w in targets.items() if k != key}
    weight = sum(remaining_targets.values())
    remaining_targets = {k: w / weight for k, w in remaining_targets.items()}
    original = deepcopy(account)
    rows, values, total = compare_holdings(account, instruments, targets, quotes, None)
    expected_rows, expected_values, expected_total = compare_holdings(removed, instruments, remaining_targets, quotes, None)
    assert total == expected_total and values == expected_values
    assert [r for r in rows if r['id'] != key] == expected_rows
    outside_row = next(r for r in rows if r['id'] == key)
    assert outside_row['Status'] == 'Outside the rebalance'
    assert outside_row['Target %'] is outside_row['Actual %'] is outside_row['Gap (₪)'] is None
    actual = make_buy_plan(account, instruments, targets, quotes, None, 257, {}, allocation_mode=mode)
    expected = make_buy_plan(removed, instruments, remaining_targets, quotes, None, 257, {}, allocation_mode=mode)
    for field in ('orders', 'leftover_ils', 'available_ils', 'instruments'):
        assert actual[field] == expected[field]
    assert account == original


def test_default_off_is_exactly_legacy_and_exclusion_invalidates_recording():
    account, instruments, quotes, targets = setup_book(units=(3, 5), cash=10)
    rows, values, total = compare_holdings(account, instruments, targets, quotes, 1)
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 200, {}, allocation_mode="biggest_gap_first")
    explicit = deepcopy(account)
    for row in explicit['positions'].values():
        row['outside_rebalance'] = False
    assert compare_holdings(explicit, instruments, targets, quotes, 1) == (rows, values, total)
    other = make_buy_plan(explicit, instruments, targets, quotes, 1, 200, {}, allocation_mode="biggest_gap_first")
    assert other['orders'] == plan['orders'] and other['leftover_ils'] == plan['leftover_ils']
    explicit['positions']['TASE:1149038']['outside_rebalance'] = True
    with pytest.raises(ValueError, match='changed'):
        apply_purchases(explicit, plan, [], {})


def test_all_targets_outside_leaves_budget_and_validates_flag():
    account, instruments, quotes, targets = setup_book(units=(5, 9), cash=11)
    for row in account['positions'].values():
        row['outside_rebalance'] = True
    assert rebalance_targets(account, targets) == {}
    rows, values, total = compare_holdings(account, instruments, targets, {}, None)
    assert total == 11 and not values
    assert all(r['Status'] == 'Outside the rebalance' for r in rows)
    plan = make_buy_plan(account, instruments, targets, {}, None, 100, {}, allocation_mode="biggest_gap_first")
    assert plan['orders'] == [] and Decimal(plan['leftover_ils']) == 111
    account['positions']['TASE:1149038']['outside_rebalance'] = 'false'
    with pytest.raises(ValueError, match='on or off'):
        validate_account(account)


def test_aliases_merge_actual_security_but_currencies_and_us_funds_stay_distinct():
    instruments, targets = combined_targets([
        {'weight': 50, 'currency': 'ILS', 'target_weights': {'SPY': 1}},
        {'weight': 30, 'currency': 'ILS', 'target_weights': {'CSPX_IL': 1}},
        {'weight': 20, 'currency': 'USD', 'target_weights': {'SPY': 1}},
    ])
    assert targets == {'TASE:1159250': .8, 'US:SPY': .2}
    assert len(instruments) == 2
    assert execution_security('BIL', 'USD')['id'] == 'TASE:5139076'  # Same existing dashboard execution label.


def test_empty_account_allocates_to_targets_in_whole_units_without_mutating_inputs():
    account, instruments, quotes, targets = setup_book()
    original = deepcopy(account)
    rows, _, total = compare_holdings(account, instruments, targets, quotes, 1)
    assert not total and all(row['Actual %'] is None for row in rows)
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 1000, {}, allocation_mode="biggest_gap_first")
    assert {row['id']: row['units'] for row in plan['orders']} == {'TASE:1149038': 60, 'TASE:1187079': 20}
    assert Decimal(plan['leftover_ils']) == 0
    assert account == original


def test_most_underweight_first_and_never_sell_overweight_or_removed_targets():
    account, instruments, quotes, targets = setup_book(units=(100, 0))
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 100, {}, allocation_mode="biggest_gap_first")
    assert [(row['id'], row['units']) for row in plan['orders']] == [('TASE:1187079', 5)]
    targets = {'TASE:1187079': 1.0}
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 100, {}, allocation_mode="biggest_gap_first")
    assert all(row['id'] == 'TASE:1187079' and row['units'] > 0 for row in plan['orders'])
    rows, _, _ = compare_holdings(account, instruments, targets, quotes, 1)
    assert next(r for r in rows if r['id'] == 'TASE:1149038')['Status'] == 'Overweight'


def test_small_deposit_can_fund_only_the_largest_gap_even_when_two_funds_are_underweight():
    account, instruments, quotes, targets = setup_book(prices=(1, 1))
    other = security('BIL', 'US')
    instruments[other['id']] = other
    account['positions'][other['id']] = {**other, 'units': '100'}
    quotes[other['id']] = {'price': '1', 'fresh': True}
    rows, _, _ = compare_holdings(account, instruments, targets, quotes, 1)
    assert all(r['Status'] == 'Underweight' for r in rows if r['id'] in targets)
    small = make_buy_plan(account, instruments, targets, quotes, 1, 10, {}, allocation_mode="biggest_gap_first")
    assert [(r['id'], r['units']) for r in small['orders']] == [('TASE:1149038', 10)]
    larger = make_buy_plan(account, instruments, targets, quotes, 1, 100, {}, allocation_mode="biggest_gap_first")
    assert {r['id']: r['units'] for r in larger['orders']} == {'TASE:1149038': 70, 'TASE:1187079': 30}


def test_small_budget_and_minimum_order_leave_money_unallocated():
    account, instruments, quotes, targets = setup_book()
    account['positions']['TASE:1149038']['minimum_ils'] = '100'
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 9, {}, allocation_mode="biggest_gap_first")
    assert not plan['orders'] and Decimal(plan['leftover_ils']) == 9
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 100, {}, allocation_mode="biggest_gap_first")
    assert all(row['id'] != 'TASE:1149038' for row in plan['orders'])  # Do not overshoot its 60 target to meet 100 minimum.
    assert Decimal(plan['leftover_ils']) == 60


def test_units_rounded_before_costs_with_exact_decimal_prices():
    account, instruments, quotes, targets = setup_book(prices=('3.333', '17.89'))
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 101, {}, allocation_mode="biggest_gap_first")
    spent = sum(Decimal(row['estimated_ils']) for row in plan['orders'])
    assert spent + Decimal(plan['leftover_ils']) == 101
    assert all(isinstance(row['units'], int) for row in plan['orders'])
    assert spent <= 101


def test_usd_values_and_buy_costs_converted_using_one_dated_fx_rate():
    instrument = security('TQQQ', 'US')
    key = instrument['id']
    account = empty_account()
    account['positions'][key] = {**instrument, 'units': '2.5'}
    quotes = {key: {'price': '100', 'fresh': True}}
    _, values, total = compare_holdings(account, {key: instrument}, {key: 1.}, quotes, '3.5')
    assert total == values[key] == Decimal('875')
    plan = make_buy_plan(account, {key: instrument}, {key: 1.}, quotes, '3.5', 800, {}, allocation_mode="biggest_gap_first")
    assert plan['orders'][0]['units'] == 2
    assert Decimal(plan['orders'][0]['estimated_ils']) == 700
    assert Decimal(plan['leftover_ils']) == 100


@pytest.mark.parametrize('invalid', ['-1', 'NaN', 'Infinity', '1.5'])
def test_invalid_tase_units_are_rejected(invalid):
    account, *_ = setup_book(units=(invalid, 0))
    with pytest.raises(ValueError): validate_account(account)


@pytest.mark.parametrize('mode', ['biggest_gap_first', 'proportional'])
def test_missing_prices_block_plans_even_for_an_off_target_holding_but_stale_prices_value(mode):
    account, instruments, quotes, targets = setup_book(units=(10, 0))
    quotes['TASE:1149038']['fresh'] = False
    assert make_buy_plan(account, instruments, {'TASE:1187079': 1.}, quotes, 1, 500, {}, allocation_mode=mode)["orders"]
    quotes['TASE:1149038'] = {'error': 'no price'}
    with pytest.raises(ValueError): compare_holdings(account, instruments, targets, quotes, 1)


def test_done_uses_actual_units_and_actual_spend_and_is_idempotent():
    account, instruments, quotes, targets = setup_book(cash=50)
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 950, {'signal': 'same'}, allocation_mode="biggest_gap_first")
    updated = apply_purchases(account, plan, [{'id': 'TASE:1149038', 'units': 50, 'paid_ils': '501.25'}], {'signal': 'same'})
    assert updated['positions']['TASE:1149038']['units'] == '50'
    assert updated['positions']['TASE:1187079']['units'] == '0'
    assert Decimal(updated['cash_ils']) == Decimal('498.75')
    assert updated['revision'] == 1
    assert apply_purchases(updated, plan, [], {}) == updated
    assert account['positions']['TASE:1149038']['units'] == '0'


@pytest.mark.parametrize('problem', ['changed_target', 'changed_holding', 'too_many', 'overspent', 'no_paid', 'duplicate'])
def test_invalid_confirmation_cannot_change_holdings(problem):
    account, instruments, quotes, targets = setup_book()
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 1000, {}, allocation_mode="biggest_gap_first")
    rows = [{'id': 'TASE:1149038', 'units': 1, 'paid_ils': 10}]
    context = {}
    if problem == 'changed_target': context = {'changed': True}
    elif problem == 'changed_holding': account['positions']['TASE:1149038']['units'] = '1'
    elif problem == 'too_many': rows[0]['units'] = 10000
    elif problem == 'overspent': rows[0]['paid_ils'] = 1001
    elif problem == 'no_paid': rows[0]['paid_ils'] = 0
    elif problem == 'duplicate': rows *= 2
    original = deepcopy(account)
    with pytest.raises(ValueError): apply_purchases(account, plan, rows, context)
    assert account == original


def test_cash_only_done_and_shared_book_roundtrip_do_not_store_pending_plans_or_auth():
    account, instruments, quotes, targets = setup_book()
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 2, {}, allocation_mode="biggest_gap_first")
    updated = apply_purchases(account, plan, [], {})
    assert Decimal(updated['cash_ils']) == 2
    state = {'holdings_account': updated, 'rebalance_portfolio_id': 'another-portfolio',
             'rebalance_pending': plan, 'supabase_session': {'access_token': 'secret'}}
    assert restore(snapshot(state)) == {k: state[k] for k in ('holdings_account', 'rebalance_portfolio_id')}


def test_large_low_price_budget_does_not_require_one_iteration_per_unit():
    account, instruments, quotes, targets = setup_book(prices=('0.01', '0.01'))
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 1_000_000, {}, allocation_mode="biggest_gap_first")
    assert sum(row['units'] for row in plan['orders']) == 100_000_000


@pytest.fixture
def allocation_fixture():
    # Entirely synthetic: cash 1176 + deposit 8000 = 9176.
    # Included ballast 40524 + cash + deposit = post-deposit value 49700.
    # Gaps: 24850, 9940, 8449, 6461. Outside value is deliberately ignored.
    D = Decimal
    items = [security(str(1200001+i), "TASE", label=label) for i, label in
             enumerate(["Expensive fund", "Gold-like fund", "Cheap bonds", "Ballast", "Outside"])]
    usd = security("TEST", "US", label="USD fund")
    expensive, gold, bonds, ballast, outside = [i["id"] for i in items]
    instruments = {i["id"]: i for i in [*items, usd]}
    holdings = {expensive:D("0"), gold:D("0"), usd["id"]:D("0"), bonds:D("0"),
                ballast:D("40524"), outside:D("99")}
    prices = {expensive:D("7620"), gold:D("26.63"), usd["id"]:D("100"),
              bonds:D("1.12"), ballast:D("1"), outside:D("999")}
    targets = {expensive:D("0.5"), gold:D("0.2"), usd["id"]:D("0.17"), bonds:D("0.13")}
    minimums = {k:D("0") for k in holdings}  # Minimum ORDER AMOUNTS, not commissions/lots.
    account = empty_account()
    account["cash_ils"] = str(D("1176"))
    account["positions"] = {k:{**instruments[k], "units":str(v), "minimum_ils":str(minimums[k]),
                              "outside_rebalance":k==outside} for k,v in holdings.items()}
    quotes = {k:{"price":str(v), "fresh":k!=outside} for k,v in prices.items()}
    return account, instruments, targets, quotes, D("3.5"), D("8000")


def test_synthetic_biggest_gap_first_hand_calculation(allocation_fixture):
    plan = make_buy_plan(*allocation_fixture, {}, "biggest_gap_first")
    # Water-fill: 9176 < 24850-9940, so one expensive unit costs 7620.
    # Remaining 1556: gold first gets ceil((9940-8449)/26.63)=56 units,
    # then floor((1556-56*26.63)/26.63)=2 more; remaining 11.46.
    # USD's 350 unit cannot fit; bonds get floor(11.46/1.12)=10, leaving .26.
    assert {r["id"]:r["units"] for r in plan["orders"]} == {
        "TASE:1200001":1, "TASE:1200002":58, "TASE:1200003":10}
    assert Decimal(plan["leftover_ils"]) == Decimal("9176")-Decimal("7620")-58*Decimal("26.63")-10*Decimal("1.12")
    assert Decimal(plan["leftover_ils"]) == Decimal("0.26")
    assert plan["unspent_by_fund"] == {}


def proportional_working(fixture, account=None, deposit=None):
    original, instruments, targets, quotes, fx, new_money = fixture
    account = account if account is not None else original
    deposit = new_money if deposit is None else deposit
    D = Decimal
    costs = {k:D(quotes[k]["price"])*(fx if instruments[k]["currency"]=="USD" else D("1")) for k in targets}
    # Independent arithmetic from declared holdings, not allocator/compare_holdings output.
    total = D(account["cash_ils"]) + sum(
        (D(p["units"])*D(quotes[k]["price"])*(fx if p["currency"]=="USD" else D("1"))
         for k,p in account["positions"].items() if not p["outside_rebalance"]), D("0"))
    budget = D(account["cash_ils"])+deposit
    gaps = {k:max(D("0"),w*(total+deposit)-D(account["positions"][k]["units"])*costs[k]) for k,w in targets.items()}
    shares = {k:min(gap,budget*gap/sum(gaps.values())) for k,gap in gaps.items()}
    quantities = {k:int((share/costs[k]).to_integral_value(rounding=ROUND_FLOOR)) for k,share in shares.items()}
    return budget, costs, gaps, shares, quantities


def test_synthetic_proportional_independent_shares(allocation_fixture):
    plan = make_buy_plan(*allocation_fixture, {}, "proportional")
    budget, costs, gaps, shares, quantities = proportional_working(allocation_fixture)
    # Shares: 4588, 1835.20, 1559.92, 1192.88.
    # floors: 0 expensive, 68 gold, 4 USD, 1065 cheap bonds.
    assert quantities == {"TASE:1200001":0,"TASE:1200002":68,"US:TEST":4,"TASE:1200003":1065}
    actual = {r["id"]:r["units"] for r in plan["orders"]}
    assert actual == {k:q for k,q in quantities.items() if q}
    assert shares["TASE:1200001"] < costs["TASE:1200001"]
    for key,share in shares.items():
        spent = quantities[key]*costs[key]
        assert spent <= share and spent <= gaps[key]
        assert Decimal(plan["unspent_by_fund"][key]) == share-spent
    leftover = budget-sum(quantities[k]*costs[k] for k in quantities)
    assert Decimal(plan["leftover_ils"]) == leftover == Decimal("4772.36")
    assert sum(map(Decimal,plan["unspent_by_fund"].values())) == leftover
    assert "TASE:1200005" not in plan["instruments"]


def test_proportional_does_not_redistribute_or_use_commission_as_minimum():
    account, instruments, quotes, _ = setup_book(prices=(100,1))
    ballast=security("DUMMY","US")
    instruments[ballast["id"]]=ballast
    account["positions"][ballast["id"]]={**ballast,"units":"100"}
    quotes[ballast["id"]]={"price":"1","fresh":True}
    targets = {k:Decimal("0.5") for k in ("TASE:1149038","TASE:1187079")}
    # Existing 100 + deposit 100 -> each gap 100; each proportional share 50.
    plan = make_buy_plan(account,instruments,targets,quotes,1,100,{},"proportional")
    assert {r["id"]:r["units"] for r in plan["orders"]} == {"TASE:1187079":50}
    assert Decimal(plan["leftover_ils"]) == 50
    legacy=make_buy_plan(account,instruments,targets,quotes,1,100,{},"biggest_gap_first")
    assert {r["id"]:r["units"] for r in legacy["orders"]} == {"TASE:1187079":100}
    assert Decimal(legacy["leftover_ils"])==0
    # A minimum ORDER AMOUNT of 60 at cost 1 needs 60 units; share 50 cannot meet it.
    account["positions"]["TASE:1187079"]["minimum_ils"]="60"
    assert not make_buy_plan(account,instruments,targets,quotes,1,100,{},"proportional")["orders"]
    # No minimum configured -> one-unit minimum only, not a minimum commission.
    account["positions"]["TASE:1187079"]["minimum_ils"]="0"
    assert make_buy_plan(account,instruments,targets,quotes,1,2,{},"proportional")["orders"][0]["units"] == 1


def test_proportional_fully_funded_eligible_gap_leaves_extra_cash():
    account,instruments,quotes,_=setup_book(units=(0,5), prices=(1,20))
    # A priced subset with weight .2 retains its weight, as with skipped unheld targets.
    plan=make_buy_plan(account,instruments,{"TASE:1149038":Decimal(".2")},quotes,1,100,{},"proportional")
    assert plan["orders"][0]["units"] == 40  # gap=.2*(100 existing+100 new)
    assert Decimal(plan["leftover_ils"]) == 60


@pytest.mark.parametrize("invalid", ["other",None,"",False,[],{}])
def test_invalid_allocation_mode_fails_closed(allocation_fixture,invalid):
    from haa.allocation_mode import ALLOCATION_MODE_ERROR
    with pytest.raises(ValueError,match=ALLOCATION_MODE_ERROR):
        make_buy_plan(*allocation_fixture,{},invalid)


def test_proportional_cash_carry_forward_partial_fills_and_no_reservations(allocation_fixture):
    account,instruments,targets,quotes,fx,deposit=allocation_fixture
    context={"allocation_mode":"proportional"}
    plan=make_buy_plan(*allocation_fixture,context,"proportional")
    # Partial real confirmation: fewer than proposed, actual paid includes a synthetic cost.
    updated=apply_purchases(account,plan,[{"id":"TASE:1200002","units":10,"paid_ils":"268"}],context)
    assert Decimal(updated["cash_ils"]) == Decimal("9176")-Decimal("268")
    assert set(updated)==set(account)
    assert updated["positions"]["TASE:1200005"]==account["positions"]["TASE:1200005"]
    second_deposit=Decimal("3000")
    budget,costs,gaps,shares,quantities=proportional_working(allocation_fixture,updated,second_deposit)
    second=make_buy_plan(updated,instruments,targets,quotes,fx,second_deposit,context,"proportional")
    repeat=make_buy_plan(updated,instruments,targets,quotes,fx,second_deposit,context,"proportional")
    assert second["orders"]==repeat["orders"]
    assert second["unspent_by_fund"]==repeat["unspent_by_fund"]
    assert Decimal(second["available_ils"])==budget==Decimal("8908")+Decimal("3000")
    assert {r["id"]:r["units"] for r in second["orders"]}=={k:q for k,q in quantities.items() if q}
    assert {k:Decimal(v) for k,v in second["unspent_by_fund"].items()}=={k:shares[k]-quantities[k]*costs[k] for k in shares}
    assert "unspent_by_fund" not in updated


def test_proportional_full_fills_keep_pooled_leftover_and_mode_context(allocation_fixture):
    account,instruments,targets,quotes,fx,deposit=allocation_fixture
    context={"allocation_mode":"proportional"}
    plan=make_buy_plan(*allocation_fixture,context,"proportional")
    confirmations=[{"id":r["id"],"units":r["units"],"paid_ils":r["estimated_ils"]} for r in plan["orders"]]
    updated=apply_purchases(account,plan,confirmations,context)
    assert Decimal(updated["cash_ils"])==Decimal("4772.36")
    following=make_buy_plan(updated,instruments,targets,quotes,fx,Decimal("1000"),context,"proportional")
    assert Decimal(following["available_ils"])==Decimal("4772.36")+Decimal("1000")
