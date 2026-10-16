from copy import deepcopy

import pytest

import haa.rebalance_market as market
import haa.supabase_sync as sync
from haa.rebalance_holdings import empty_account, fingerprint, security
from test_saved_portfolio_ui import account, open_app, button


@pytest.fixture
def rebalance_account(account, monkeypatch):
    instrument = security('GLD', 'US')
    book = empty_account()
    book['positions'][instrument['id']] = {**instrument, 'units': '5'}
    remote = {'revision': 1, 'payload': {'holdings_account': book}}
    monkeypatch.setattr(sync, 'load_workspace', lambda *a: deepcopy(remote))
    def save(url, key, session, payload, revision):
        if revision != remote['revision']:
            return None
        remote.update(revision=revision+1, payload=deepcopy(payload))
        return revision+1
    monkeypatch.setattr(sync, 'save_workspace', save)
    account.extend([{'id': 'first', 'name': 'Gold', 'updated_at': 'v1', 'is_default': False,
                     'payload': {'version': 1, 'name': 'Gold', 'total_ils': 1000, 'ils_per_usd': 3.5,
                                 'sleeves': [{'model': 'Buy and Hold Gold GLD', 'weight': 100}]}},
                    {'id': 'second', 'name': 'Another portfolio', 'updated_at': 'v2', 'is_default': False,
                     'payload': {'version': 1, 'name': 'Another portfolio', 'total_ils': 9999, 'ils_per_usd': 9.,
                                 'sleeves': [{'model': 'Buy and Hold Gold GLD', 'weight': 100}]}}])
    monkeypatch.setattr(market, 'load_portfolio_signals', lambda labels, *a: ([
        {'name': label, 'currency': 'USD', 'target_weights': {'GLD': 1.},
         'signal_date': '2026-09-30', 'source_notes': []} for label in labels], []))
    monkeypatch.setattr(market, 'unit_quote', lambda *a: {'price': '10', 'fresh': True, 'as_of': '2026-10-15',
                                                       'source': 'Test actual raw quote', 'field': 'Unadjusted close'})
    monkeypatch.setattr(market, 'fx_quote', lambda *a: {'price': '3.5', 'fresh': True, 'as_of': '2026-10-15', 'source': 'Test FX'})
    return remote


def visit():
    app = open_app()
    app.radio(key='page').set_value('Rebalance Holdings').run()
    assert not app.exception
    return app


def test_page_uses_one_book_when_switching_portfolios_and_on_fresh_device(rebalance_account):
    app = visit()
    original = deepcopy(app.session_state['holdings_account'])
    app.selectbox(key='rebalance_portfolio_id').set_value('second').run()
    assert not app.exception
    assert app.session_state['holdings_account'] == original
    assert rebalance_account['payload']['holdings_account'] == original
    phone = visit()
    assert phone.session_state['holdings_account'] == original
    assert any(metric.label == 'Account value, including unallocated cash' and metric.value == '₪175.00' for metric in phone.metric)


def test_edit_units_then_done_records_only_actual_units_and_unspent_cash(rebalance_account):
    app = visit()
    editor = f"rebalance_editor_0_{fingerprint(['US:GLD'])[:12]}"
    app.session_state[editor] = {'edited_rows': {0: {'Units': 6.}}, 'added_rows': [], 'deleted_rows': []}
    button(app, 'Save holdings').click().run()
    assert not app.exception
    assert float(rebalance_account['payload']['holdings_account']['positions']['US:GLD']['units']) == 6.
    app.number_input(key='rebalance_new_money').set_value(100.).run()
    button(app, 'Generate buy list').click().run()
    assert not app.exception
    pending = app.session_state['rebalance_pending']
    assert pending['orders'][0]['units'] == 2
    confirmation_key = f"rebalance_confirmation_{pending['id']}"
    app.session_state[confirmation_key] = {'edited_rows': {0: {'Units bought': 1, 'Actual paid (₪)': 36.}}, 'added_rows': [], 'deleted_rows': []}
    app.checkbox[0].set_value(True)
    button(app, 'Done — record buys and remaining cash').click().run()
    assert not app.exception, [e.message for e in app.exception]
    saved = rebalance_account['payload']['holdings_account']
    assert float(saved['positions']['US:GLD']['units']) == 7
    assert float(saved['cash_ils']) == 64
    assert saved['last_operation_id'] == pending['id']
    assert 'rebalance_pending' not in rebalance_account['payload']
    assert app.number_input(key='rebalance_new_money').value == 0
    app.run()
    assert rebalance_account['payload']['holdings_account'] == saved


def test_stale_or_unavailable_prices_never_produce_automatic_buys(rebalance_account, monkeypatch):
    monkeypatch.setattr(market, 'unit_quote', lambda *a: {'price': '10', 'fresh': False, 'as_of': '2026-09-01', 'source': 'Old fund publication'})
    app = visit()
    assert button(app, 'Generate buy list').disabled
    assert any('blocked' in item.value for item in app.warning)
    monkeypatch.setattr(market, 'unit_quote', lambda *a: {'error': 'No raw price', 'fresh': False})
    app.run()
    assert not app.exception
    assert any('price unavailable' in item.value for item in app.warning)
    assert button(app, 'Save holdings')


def test_failed_save_does_not_change_account_or_show_success(rebalance_account, monkeypatch):
    app = visit()
    original = deepcopy(rebalance_account['payload']['holdings_account'])
    monkeypatch.setattr(sync, 'save_workspace', lambda *a: None)
    editor = f"rebalance_editor_0_{fingerprint(['US:GLD'])[:12]}"
    app.session_state[editor] = {'edited_rows': {0: {'Units': 123.}}, 'added_rows': [], 'deleted_rows': []}
    button(app, 'Save holdings').click().run()
    assert not app.exception
    assert rebalance_account['payload']['holdings_account'] == original
    assert app.session_state['holdings_account'] == original
    assert any('not confirmed saved' in item.value for item in app.error)


def test_missing_targets_leave_holdings_editable_and_existing_dashboards_available(rebalance_account, monkeypatch):
    monkeypatch.setattr(market, 'load_portfolio_signals', lambda *a: ([], ['Signal source unavailable']))
    app = visit()
    assert button(app, 'Save holdings')
    assert not any(item.label == 'Generate buy list' for item in app.button)
    app.radio(key='page').set_value('Today').run()
    assert not app.exception


def test_empty_account_without_portfolio_can_add_funds_and_save_units(rebalance_account, account):
    account.clear()
    rebalance_account['payload']['holdings_account'] = empty_account()
    app = visit()
    assert button(app, 'Save holdings')
    app.selectbox(key='rebalance_add_choice').set_value('TASE:5131792').run()
    button(app, 'Add selected fund').click().run()
    assert not app.exception
    saved = rebalance_account['payload']['holdings_account']
    assert saved['positions']['TASE:5131792']['units'] == '0'
    editor = f"rebalance_editor_1_{fingerprint(['TASE:5131792'])[:12]}"
    app.session_state[editor] = {'edited_rows': {0: {'Units': 20.}}, 'added_rows': [], 'deleted_rows': []}
    button(app, 'Save holdings').click().run()
    assert not app.exception
    assert float(rebalance_account['payload']['holdings_account']['positions']['TASE:5131792']['units']) == 20
    assert not any(item.label == 'Generate buy list' for item in app.button)
