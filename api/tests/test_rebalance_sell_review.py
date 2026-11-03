from copy import deepcopy
from server.rebalance import sell_review
from haa.rebalance_holdings import empty_account, security


def test_sell_review_full_exits_protects_cspx_and_respects_roles():
    items = [security('GLD', 'US'), security('IEF', 'US'), security('CSPX.L', 'US'), security('1159250', 'TASE'), security('BIL', 'US'), security('SPY', 'US')]
    instruments = {item['id']: item for item in items}
    account = empty_account()
    account['positions'] = {item['id']: {**item, 'units': '3', 'minimum_ils': '0'} for item in items}
    account['positions']['US:BIL']['outside_rebalance'] = True
    account['positions']['US:SPY']['companion_of'] = 'US:IEF'
    original = deepcopy(account)
    rows = {row['id']: row for row in sell_review(account, {'US:IEF': 1}, instruments)}
    assert rows['US:GLD'] == {'id': 'US:GLD', 'action': 'sell', 'before_units': '3', 'after_units': '0'}
    for key in instruments.keys() - {'US:GLD'}:
        assert rows[key]['action'] == 'keep'
        assert rows[key]['after_units'] == '3'
    assert account == original
    assert all(row['action'] == 'keep' for row in sell_review(account, {}, instruments, False))


def test_pending_gold_replacement_withholds_only_the_old_gold_position():
    old_gold = security('1147875', 'TASE', 'ILS', 'Old unhedged gold')
    tachlit = security('5141627', 'TASE', 'ILS', 'Tachlit hedged gold')
    ief = security('IEF', 'US')
    cspx = security('CSPX.L', 'US')
    outside = security('BIL', 'US')
    companion = security('SPY', 'US')
    items = [old_gold, tachlit, ief, cspx, outside, companion]
    instruments = {item['id']: item for item in items}
    account = empty_account()
    account['positions'] = {item['id']: {**item, 'units': '3', 'minimum_ils': '0'} for item in items}
    account['positions'][outside['id']]['outside_rebalance'] = True
    account['positions'][companion['id']]['companion_of'] = tachlit['id']

    rows = {row['id']: row for row in sell_review(
        account, {tachlit['id']: 1}, instruments, available=True, withheld={old_gold['id']})}

    assert rows[old_gold['id']]['action'] == 'pending'
    assert rows[old_gold['id']]['after_units'] == '3'
    assert rows[ief['id']]['action'] == 'sell'
    for item in (tachlit, cspx, outside, companion):
        assert rows[item['id']]['action'] == 'keep'
