from copy import deepcopy
from decimal import Decimal

import pytest

from haa.rebalance_holdings import (apply_purchases, combined_targets, compare_holdings, empty_account,
                                   execution_security, make_buy_plan, security, validate_account)
from haa.workspace_sync import snapshot, restore


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
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 1000, {})
    assert {row['id']: row['units'] for row in plan['orders']} == {'TASE:1149038': 60, 'TASE:1187079': 20}
    assert Decimal(plan['leftover_ils']) == 0
    assert account == original


def test_most_underweight_first_and_never_sell_overweight_or_removed_targets():
    account, instruments, quotes, targets = setup_book(units=(100, 0))
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 100, {})
    assert [(row['id'], row['units']) for row in plan['orders']] == [('TASE:1187079', 5)]
    targets = {'TASE:1187079': 1.0}
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 100, {})
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
    small = make_buy_plan(account, instruments, targets, quotes, 1, 10, {})
    assert [(r['id'], r['units']) for r in small['orders']] == [('TASE:1149038', 10)]
    larger = make_buy_plan(account, instruments, targets, quotes, 1, 100, {})
    assert {r['id']: r['units'] for r in larger['orders']} == {'TASE:1149038': 70, 'TASE:1187079': 30}


def test_small_budget_and_minimum_order_leave_money_unallocated():
    account, instruments, quotes, targets = setup_book()
    account['positions']['TASE:1149038']['minimum_ils'] = '100'
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 9, {})
    assert not plan['orders'] and Decimal(plan['leftover_ils']) == 9
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 100, {})
    assert all(row['id'] != 'TASE:1149038' for row in plan['orders'])  # Do not overshoot its 60 target to meet 100 minimum.
    assert Decimal(plan['leftover_ils']) == 60


def test_units_rounded_before_costs_with_exact_decimal_prices():
    account, instruments, quotes, targets = setup_book(prices=('3.333', '17.89'))
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 101, {})
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
    plan = make_buy_plan(account, {key: instrument}, {key: 1.}, quotes, '3.5', 800, {})
    assert plan['orders'][0]['units'] == 2
    assert Decimal(plan['orders'][0]['estimated_ils']) == 700
    assert Decimal(plan['leftover_ils']) == 100


@pytest.mark.parametrize('invalid', ['-1', 'NaN', 'Infinity', '1.5'])
def test_invalid_tase_units_are_rejected(invalid):
    account, *_ = setup_book(units=(invalid, 0))
    with pytest.raises(ValueError): validate_account(account)


def test_missing_stale_prices_block_plans_even_for_an_off_target_holding():
    account, instruments, quotes, targets = setup_book(units=(10, 0))
    quotes['TASE:1149038']['fresh'] = False
    with pytest.raises(ValueError): make_buy_plan(account, instruments, {'TASE:1187079': 1.}, quotes, 1, 500, {})
    quotes['TASE:1149038'] = {'error': 'no price'}
    with pytest.raises(ValueError): compare_holdings(account, instruments, targets, quotes, 1)


def test_done_uses_actual_units_and_actual_spend_and_is_idempotent():
    account, instruments, quotes, targets = setup_book(cash=50)
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 950, {'signal': 'same'})
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
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 1000, {})
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
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 2, {})
    updated = apply_purchases(account, plan, [], {})
    assert Decimal(updated['cash_ils']) == 2
    state = {'holdings_account': updated, 'rebalance_portfolio_id': 'another-portfolio',
             'rebalance_pending': plan, 'supabase_session': {'access_token': 'secret'}}
    assert restore(snapshot(state)) == {k: state[k] for k in ('holdings_account', 'rebalance_portfolio_id')}


def test_large_low_price_budget_does_not_require_one_iteration_per_unit():
    account, instruments, quotes, targets = setup_book(prices=('0.01', '0.01'))
    plan = make_buy_plan(account, instruments, targets, quotes, 1, 1_000_000, {})
    assert sum(row['units'] for row in plan['orders']) == 100_000_000
