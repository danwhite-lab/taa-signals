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
    assert any(metric.label == 'Account value' and metric.value == '₪175.00' for metric in phone.metric)


def test_edit_units_then_done_records_only_actual_units_and_unspent_cash(rebalance_account):
    app = visit()
    editor = f"rebalance_editor_0_{fingerprint(['US:GLD'])[:12]}"
    app.session_state[editor] = {'edited_rows': {0: {'Units': 6.}}, 'added_rows': [], 'deleted_rows': []}
    button(app, 'Save holdings').click().run()
    assert not app.exception
    assert float(rebalance_account['payload']['holdings_account']['positions']['US:GLD']['units']) == 6.
    app.number_input(key='rebalance_new_money').set_value(100.).run()
    button(app, 'What to buy').click().run()
    assert not app.exception
    pending = app.session_state['rebalance_pending']
    assert pending['orders'][0]['units'] == 2
    button(app, 'Record these buys').click().run()
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
    assert button(app, 'What to buy').disabled
    assert any('price missing or stale' in item.value for item in app.caption)
    monkeypatch.setattr(market, 'unit_quote', lambda *a: {'error': 'No raw price', 'fresh': False})
    app.run()
    assert not app.exception
    assert any('price missing or stale' in item.value for item in app.caption)
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
    assert button(app, 'What to buy').disabled
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
    assert button(app, 'What to buy').disabled


def visible_nodes(node):
    """Collapsed sections are intentionally rendered but not default-visible."""
    if getattr(node, 'type', None) == 'expander':
        return
    yield node
    for child in getattr(node, 'children', {}).values():
        yield from visible_nodes(child)


def test_minimal_default_screen_and_single_cash_fx_controls_after_repeated_saves(rebalance_account):
    app = visit()
    for _ in range(3):
        visible = list(visible_nodes(app.main))
        assert [n.label for n in visible if n.type == 'number_input'] == ['New money (₪)']
        assert [n.label for n in visible if n.type == 'button'] == ['What to buy']
        tables = [n for n in visible if n.type in ('arrow_data_frame', 'dataframe')]
        assert len(tables) == 1, [n.type for n in visible]
        assert list(tables[0].value.columns) == ['Fund', 'Target %', 'Actual %', 'Status']
        assert len([n for n in app.number_input if n.label == 'Unallocated account cash (₪)']) == 1
        assert len([n for n in app.number_input if n.label == 'Manual ₪ per $1 (0 = automatic)']) == 1
        assert all(not e.proto.expanded for e in app.expander)
        button(app, 'Save holdings').click().run()
        assert not app.exception


def test_missing_unheld_target_is_skipped_without_redistributing_target_weights(rebalance_account, monkeypatch):
    monkeypatch.setattr(market, 'load_portfolio_signals', lambda labels, *a: ([
        {'name': labels[0], 'currency': 'USD', 'target_weights': {'GLD': .5, 'IEF': .5},
         'signal_date': '2026-09-30', 'source_notes': []}], []))
    monkeypatch.setattr(market, 'unit_quote', lambda instrument, position:
        {'error': 'unavailable', 'fresh': False} if instrument['id'] == 'US:IEF' else
        {'price': '10', 'fresh': True, 'source': 'Synthetic test quote'})
    app = visit()
    app.number_input(key='rebalance_new_money').set_value(100.).run()
    assert not button(app, 'What to buy').disabled
    button(app, 'What to buy').click().run()
    plan = app.session_state['rebalance_pending']
    # Existing account is 175; GLD target after deposit is 137.5, below its
    # existing value. Removing the missing fund must NOT turn this into 100% GLD.
    assert plan['orders'] == []
    assert float(plan['leftover_ils']) == 100
    assert app.number_input(key='quick_price_US:IEF')


def test_inline_dated_manual_price_unblocks_a_held_fund(rebalance_account, monkeypatch):
    monkeypatch.setattr(market, 'unit_quote', lambda instrument, position:
        {'price': position['manual_price'], 'fresh': True, 'source': 'Manual test observation'}
        if position.get('manual_price') else {'error': 'Cannot price', 'fresh': False})
    app = visit()
    assert button(app, 'What to buy').disabled
    app.number_input(key='quick_price_US:GLD').set_value(12.)
    button(app, 'Use manual price').click().run()
    assert not app.exception
    saved = rebalance_account['payload']['holdings_account']['positions']['US:GLD']
    assert float(saved['manual_price']) == 12
    assert saved['manual_price_date']
    assert not button(app, 'What to buy').disabled, [(n.label, n.disabled) for n in app.button]


def test_provider_errors_never_echo_private_values(rebalance_account, monkeypatch):
    marker = 'PRIVATE_AMOUNT_SENTINEL'
    monkeypatch.setattr(market, 'unit_quote', lambda *a: {'error': marker, 'fresh': False})
    app = visit()
    assert not app.exception
    assert all(marker not in item.value for item in list(app.error) + list(app.warning) + list(app.caption))
    for table in app.dataframe:
        assert marker not in table.value.to_string()


def test_identical_concurrent_save_is_acknowledged_without_a_conflict_banner(rebalance_account, monkeypatch):
    app = visit()
    def identical_save(url, key, session, payload, revision):
        rebalance_account.update(revision=revision+1, payload=deepcopy(payload))
        return None  # Another request already saved exactly this snapshot.
    monkeypatch.setattr(sync, 'save_workspace', identical_save)
    app.session_state['workspace_last_saved'] = {}
    app.run()
    assert not app.exception
    assert 'workspace_conflict' not in app.session_state or not app.session_state['workspace_conflict']
    assert app.session_state['workspace_revision'] == rebalance_account['revision']
    assert not any('another device' in warning.value for warning in app.warning)


def test_real_conflict_is_quiet_but_keeps_the_save_guard(rebalance_account, monkeypatch):
    app = visit()
    before = deepcopy(rebalance_account['payload']['holdings_account'])
    monkeypatch.setattr(sync, 'save_workspace', lambda *a: None)
    app.session_state['workspace_last_saved'] = {}
    app.session_state['portfolio_name'] = 'Changed local test preference'
    app.run()
    assert not app.exception
    assert app.session_state['workspace_conflict']
    assert not any('another device' in warning.value for warning in app.warning)
    assert any('Sync paused' in item.value for item in app.caption)
    button(app, 'Save holdings').click().run()
    assert rebalance_account['payload']['holdings_account'] == before
    assert any('not confirmed saved' in error.value for error in app.error)
