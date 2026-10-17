from copy import deepcopy
from datetime import date
import json

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


def edit_holdings(app, changes):
    ids = sorted(next(t.value for t in app.dataframe if 'Security' in t.value and 'Units' in t.value)['Security'])
    key = f"rebalance_editor_{app.session_state['holdings_account']['revision']}_{fingerprint(ids)[:12]}"
    app.session_state[key] = {'edited_rows': changes, 'added_rows': [], 'deleted_rows': []}
    app.run()
    assert not app.exception


def save_edited_holdings(app):
    # AppTest has no data-editor interaction API: re-submit its cell deltas
    # with the button event, as the browser does for the real widget.
    ids = sorted(next(t.value for t in app.dataframe if 'Security' in t.value and 'Units' in t.value)['Security'])
    key = f"rebalance_editor_{app.session_state['holdings_account']['revision']}_{fingerprint(ids)[:12]}"
    app.session_state[key] = deepcopy(app.session_state[key])
    button(app, 'Save holdings').click().run()


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
    assert any('Price missing or stale:' in item.value for item in app.caption)
    monkeypatch.setattr(market, 'unit_quote', lambda *a: {'error': 'No raw price', 'fresh': False})
    app.run()
    assert not app.exception
    assert any('Price missing or stale:' in item.value for item in app.caption)
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
    assert saved['positions'] == {}
    editor = f"rebalance_editor_0_{fingerprint(['TASE:5131792'])[:12]}"
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


def test_money_and_buy_button_first_holdings_open_and_single_cash_fx_controls(rebalance_account):
    app = visit()
    for _ in range(3):
        visible = list(visible_nodes(app.main))
        assert [n.label for n in visible if n.type == 'number_input'] == ['New money (₪)', 'Unallocated account cash (₪)']
        assert [n.label for n in visible if n.type == 'button'] == ['What to buy', 'Save holdings']
        tables = [n for n in visible if n.type in ('arrow_data_frame', 'dataframe')]
        assert len(tables) == 3, [n.type for n in visible]
        assert 'Units' in tables[0].value.columns
        assert 'Units to save' in tables[1].value.columns
        assert list(tables[2].value.columns) == ['Fund', 'Target %', 'Actual %', 'Status']
        assert next(i for i, n in enumerate(visible) if n.type == 'number_input' and n.label == 'New money (₪)') < visible.index(tables[0])
        assert next(i for i, n in enumerate(visible) if n.type == 'button' and n.label == 'What to buy') < visible.index(tables[0])
        assert list(app.expander)[-1].label == 'Portfolio & signal dates'
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
    assert not any(n.key and n.key.startswith('quick_price_') for n in app.number_input)
    assert 'Manual price per unit' in app.dataframe[0].value
    assert not any(b.label == 'Record these buys' for b in app.button)


def test_row_dated_manual_price_unblocks_a_held_fund(rebalance_account, monkeypatch):
    monkeypatch.setattr(market, 'unit_quote', lambda instrument, position:
        {'price': position['manual_price'], 'fresh': True, 'source': 'Manual test observation'}
        if position.get('manual_price') else {'error': 'Cannot price', 'fresh': False})
    app = visit()
    assert button(app, 'What to buy').disabled
    assert app.dataframe[0].value['Price date'].isna().all()
    edit_holdings(app, {0: {'Manual price per unit': 12., 'Price date': date(2026, 10, 15)}})
    save_edited_holdings(app)
    assert not app.exception
    saved = rebalance_account['payload']['holdings_account']['positions']['US:GLD']
    assert saved['manual_price'] is not None, app.dataframe[0].value.to_dict('records')
    assert float(saved['manual_price']) == 12
    assert saved['manual_price_date'] == '2026-10-15'
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


def test_manual_price_requires_explicit_observation_date(rebalance_account, monkeypatch):
    monkeypatch.setattr(market, 'unit_quote', lambda *a: {'error': 'Cannot price', 'fresh': False})
    app = visit()
    before = deepcopy(rebalance_account['payload']['holdings_account'])
    assert app.dataframe[0].value['Price date'].isna().all()
    edit_holdings(app, {0: {'Manual price per unit': 12.}})
    save_edited_holdings(app)
    assert not app.exception
    assert any('enter the date of the price you are copying' in c.value for c in app.caption)
    assert rebalance_account['payload']['holdings_account'] == before
    assert button(app, 'What to buy').disabled


def test_empty_cash_has_specific_error_and_does_not_save(rebalance_account):
    app = visit()
    before = deepcopy(rebalance_account['payload']['holdings_account'])
    app.number_input(key='rebalance_cash').set_value(None)
    button(app, 'Save holdings').click().run()
    assert not app.exception
    assert [e.value for e in app.error] == ['Enter unallocated account cash, or enter 0 if there is none.']
    assert rebalance_account['payload']['holdings_account'] == before
    app.number_input(key='rebalance_cash').set_value(0.)
    button(app, 'Save holdings').click().run()
    assert not app.error


def test_overweight_note_only_appears_when_relevant(rebalance_account, monkeypatch):
    app = visit()
    assert not any('Overweight, buy-only' in c.value for c in app.caption)
    monkeypatch.setattr(market, 'load_portfolio_signals', lambda labels, *a: ([
        {'name': labels[0], 'currency': 'USD', 'target_weights': {'GLD': .5, 'IEF': .5},
         'signal_date': '2026-09-30', 'source_notes': []}], []))
    app.run()
    assert any(c.value == 'Overweight, buy-only so nothing to buy' for c in app.caption)
    app.number_input(key='rebalance_new_money').set_value(35.).run()
    button(app, 'What to buy').click().run()
    assert all(r['id'] != 'US:GLD' for r in app.session_state['rebalance_pending']['orders'])


def test_changed_inputs_note_clears_after_new_buy_list(rebalance_account):
    app = visit()
    assert not any('Inputs changed' in c.value for c in app.caption)
    app.number_input(key='rebalance_new_money').set_value(100.).run()
    button(app, 'What to buy').click().run()
    app.number_input(key='rebalance_new_money').set_value(200.).run()
    assert 'rebalance_pending' not in app.session_state
    assert any(c.value == 'Inputs changed, press What to buy again' for c in app.caption)
    app.run()
    assert any('Inputs changed' in c.value for c in app.caption)
    button(app, 'What to buy').click().run()
    assert not any('Inputs changed' in c.value for c in app.caption)
    edit_holdings(app, {0: {'Units': 6.}})
    save_edited_holdings(app)
    assert any('Inputs changed' in c.value for c in app.caption)


def test_value_entry_previews_usd_units_before_saving_units_only(rebalance_account):
    app = visit()
    edit_holdings(app, {0: {'Enter as': 'Value', 'Value (₪ / $)': 65.}})
    preview = app.dataframe[1].value
    assert preview.iloc[0]['Currency'] == 'USD'
    assert preview.iloc[0]['Current value (₪ / $)'] == 65.
    assert preview.iloc[0]['Units to save'] == 6.5
    assert rebalance_account['payload']['holdings_account']['positions']['US:GLD']['units'] == '5'
    assert button(app, 'What to buy').disabled
    save_edited_holdings(app)
    saved = rebalance_account['payload']['holdings_account']['positions']['US:GLD']
    assert float(saved['units']) == 6.5
    assert 'Value (₪ / $)' not in saved
    assert not button(app, 'What to buy').disabled


def test_ils_value_entry_previews_whole_tase_units_without_adding_cash(rebalance_account):
    instrument = security('1147875', 'TASE')
    book = empty_account()
    book['positions'][instrument['id']] = {**instrument, 'units': '3'}
    rebalance_account['payload']['holdings_account'] = book
    app = visit()
    edit_holdings(app, {0: {'Enter as': 'Value', 'Value (₪ / $)': 25.}})
    preview = app.dataframe[1].value.iloc[0]
    assert preview['Currency'] == 'ILS'
    assert preview['Units to save'] == 2
    assert preview['Current value (₪ / $)'] == 20.
    save_edited_holdings(app)
    saved = rebalance_account['payload']['holdings_account']
    assert saved['positions'][instrument['id']]['units'] == '2'
    assert saved['cash_ils'] == '0.0'


@pytest.mark.parametrize('quote', [{'error': 'unavailable', 'fresh': False}, {'price': '10', 'fresh': False}])
def test_value_entry_never_converts_with_missing_or_stale_price(rebalance_account, monkeypatch, quote):
    monkeypatch.setattr(market, 'unit_quote', lambda *a: quote)
    app = visit()
    before = deepcopy(rebalance_account['payload']['holdings_account'])
    edit_holdings(app, {0: {'Enter as': 'Value', 'Value (₪ / $)': 60.}})
    assert any('value entry needs a current price' in c.value for c in app.caption)
    save_edited_holdings(app)
    assert rebalance_account['payload']['holdings_account'] == before
    assert button(app, 'What to buy').disabled
    assert not any(n.key and n.key.startswith('quick_price_') for n in app.number_input)


def test_value_entry_can_use_dated_manual_price_in_the_same_row(rebalance_account, monkeypatch):
    monkeypatch.setattr(market, 'unit_quote', lambda instrument, position:
        {'price': position['manual_price'], 'fresh': True} if position.get('manual_price') and position.get('manual_price_date')
        else {'error': 'missing', 'fresh': False})
    app = visit()
    edit_holdings(app, {0: {'Enter as': 'Value', 'Value (₪ / $)': 60.,
                            'Manual price per unit': 12., 'Price date': date(2026, 10, 15)}})
    assert app.dataframe[1].value.iloc[0]['Units to save'] == 5
    save_edited_holdings(app)
    saved = rebalance_account['payload']['holdings_account']['positions']['US:GLD']
    assert float(saved['units']) == 5
    assert saved['manual_price_date'] == '2026-10-15'
    assert not button(app, 'What to buy').disabled


def test_unsaved_unit_edit_invalidates_list_and_hides_record_step(rebalance_account):
    app = visit()
    app.number_input(key='rebalance_new_money').set_value(100.).run()
    button(app, 'What to buy').click().run()
    assert button(app, 'Record these buys')
    edit_holdings(app, {0: {'Units': 7.}})
    assert button(app, 'What to buy').disabled
    assert not any(b.label == 'Record these buys' for b in app.button)
    assert any(c.value == 'Inputs changed, press What to buy again' for c in app.caption)


def test_record_step_requires_at_least_one_order(rebalance_account):
    app = visit()
    assert not any(b.label == 'Record these buys' for b in app.button)
    button(app, 'What to buy').click().run()
    assert app.session_state['rebalance_pending']['orders'] == []
    assert not any(b.label == 'Record these buys' for b in app.button)
    app.number_input(key='rebalance_new_money').set_value(100.).run()
    button(app, 'What to buy').click().run()
    assert app.session_state['rebalance_pending']['orders']
    assert button(app, 'Record these buys')


def test_bottom_portfolio_selector_still_changes_targets(rebalance_account, account, monkeypatch):
    account[1]['payload']['sleeves'][0]['model'] = 'Buy and Hold IEF'
    monkeypatch.setattr(market, 'load_portfolio_signals', lambda labels, *a: ([
        {'name': label, 'currency': 'USD', 'target_weights': {'IEF' if label == 'Buy and Hold IEF' else 'GLD': 1.},
         'signal_date': '2026-09-30', 'source_notes': []} for label in labels], []))
    app = visit()
    assert app.expander[-1].label == 'Portfolio & signal dates'
    assert not app.expander[-1].proto.expanded
    app.selectbox(key='rebalance_portfolio_id').set_value('second').run()
    assert not app.exception
    comparison = next(t.value for t in app.dataframe if 'Target %' in t.value)
    assert comparison.loc[comparison['Fund'] == 'IEF', 'Target %'].iloc[0] == 1.


def test_value_only_edit_saves_and_repopulates_values_on_reload(rebalance_account):
    app = visit()
    assert app.dataframe[0].value.iloc[0]['Value (₪ / $)'] == 50.
    edit_holdings(app, {0: {'Value (₪ / $)': 65.}})
    assert app.dataframe[1].value.iloc[0]['Units to save'] == 6.5
    save_edited_holdings(app)
    assert float(rebalance_account['payload']['holdings_account']['positions']['US:GLD']['units']) == 6.5
    assert app.dataframe[0].value.iloc[0]['Value (₪ / $)'] == 65.
    assert app.dataframe[0].value.iloc[0]['Units'] == 6.5
    assert any(s.value == 'Holdings saved.' for s in app.success)
    assert any(n.type == 'success' and n.value == 'Holdings saved.' for n in visible_nodes(app.main))
    phone = visit()
    assert phone.dataframe[0].value.iloc[0]['Value (₪ / $)'] == 65.
    assert phone.dataframe[0].value.iloc[0]['Units'] == 6.5


def test_last_edited_value_or_units_cell_drives_save(rebalance_account):
    app = visit()
    edit_holdings(app, {0: {'Value (₪ / $)': 65.}})
    assert app.dataframe[1].value.iloc[0]['Units to save'] == 6.5
    edit_holdings(app, {0: {'Value (₪ / $)': 65., 'Units': 8.}})
    assert app.dataframe[1].value.iloc[0]['Units to save'] == 8.
    edit_holdings(app, {0: {'Value (₪ / $)': 35., 'Units': 8.}})
    assert app.dataframe[1].value.iloc[0]['Units to save'] == 3.5
    save_edited_holdings(app)
    assert float(rebalance_account['payload']['holdings_account']['positions']['US:GLD']['units']) == 3.5


def test_failed_value_save_keeps_draft_and_never_shows_saved(rebalance_account, monkeypatch):
    app = visit()
    before = deepcopy(rebalance_account['payload']['holdings_account'])
    edit_holdings(app, {0: {'Value (₪ / $)': 65.}})
    monkeypatch.setattr(sync, 'save_workspace', lambda *a: None)
    save_edited_holdings(app)
    assert not app.exception
    assert rebalance_account['payload']['holdings_account'] == before
    assert app.dataframe[1].value.iloc[0]['Units to save'] == 6.5
    assert not app.success
    assert any('not confirmed saved' in e.value for e in app.error)


def test_missing_price_is_blank_not_zero_when_rehydrating_saved_values(rebalance_account, monkeypatch):
    monkeypatch.setattr(market, 'unit_quote', lambda *a: {'error': 'unavailable', 'fresh': False})
    app = visit()
    assert app.dataframe[0].value['Value (₪ / $)'].isna().all()
    assert app.dataframe[0].value.iloc[0]['Units'] == 5.


def test_units_display_two_decimals_without_rounding_saved_positions(rebalance_account):
    rebalance_account['payload']['holdings_account']['positions']['US:GLD']['units'] = '5.12345'
    app = visit()
    editor_config = json.loads(app.dataframe[0].proto.columns)
    preview_config = json.loads(app.dataframe[1].proto.columns)
    assert editor_config['Units']['type_config']['format'] == '%.2f'
    assert preview_config['Units to save']['type_config']['format'] == '%.2f'
    button(app, 'Save holdings').click().run()
    assert float(rebalance_account['payload']['holdings_account']['positions']['US:GLD']['units']) == 5.12345


def test_add_fund_preserves_value_draft_cash_and_fx_without_saving(rebalance_account):
    app = visit()
    before = deepcopy(rebalance_account['payload']['holdings_account'])
    app.selectbox(key='rebalance_add_choice').set_value('TASE:5131792').run()
    edit_holdings(app, {0: {'Value (₪ / $)': 65.}})
    key = f"rebalance_editor_0_{fingerprint(['US:GLD'])[:12]}"
    app.session_state[key] = deepcopy(app.session_state[key])
    app.number_input(key='rebalance_cash').set_value(25.)
    app.number_input(key='rebalance_fx').set_value(4.)
    app.date_input(key='rebalance_fx_date').set_value(date(2026, 10, 15))
    button(app, 'Add selected fund').click().run()
    assert not app.exception
    assert rebalance_account['payload']['holdings_account'] == before
    editor = next(t.value for t in app.dataframe if 'Security' in t.value and 'Units' in t.value)
    assert list(editor['Security']) == ['TASE:5131792', 'US:GLD']
    assert editor.loc[editor['Security'] == 'US:GLD', 'Value (₪ / $)'].iloc[0] == 65.
    preview = next(t.value for t in app.dataframe if 'Units to save' in t.value)
    assert preview.loc[preview['Fund'] == 'GLD', 'Units to save'].iloc[0] == 6.5
    assert app.number_input(key='rebalance_cash').value == 25.
    assert app.number_input(key='rebalance_fx').value == 4.
    assert button(app, 'What to buy').disabled
    assert not app.success
    save_edited_holdings(app)
    saved = rebalance_account['payload']['holdings_account']
    assert float(saved['positions']['US:GLD']['units']) == 6.5
    assert saved['positions']['TASE:5131792']['units'] == '0.0'
    assert float(saved['cash_ils']) == 25.
    assert float(saved['manual_fx']) == 4.


def test_add_custom_preserves_unit_and_dated_price_drafts(rebalance_account):
    app = visit()
    before = deepcopy(rebalance_account['payload']['holdings_account'])
    changes = {0: {'Units': 7.25, 'Manual price per unit': 12.,
                   'Price date': date(2026, 10, 15), 'Minimum order (₪)': 50.}}
    edit_holdings(app, changes)
    key = f"rebalance_editor_0_{fingerprint(['US:GLD'])[:12]}"
    app.session_state[key] = deepcopy(app.session_state[key])
    app.text_input(key='rebalance_custom_identifier').set_value('ZZTEST')
    button(app, 'Add custom holding').click().run()
    assert not app.exception
    assert rebalance_account['payload']['holdings_account'] == before
    editor = next(t.value for t in app.dataframe if 'Security' in t.value and 'Units' in t.value)
    row = editor.loc[editor['Security'] == 'US:GLD'].iloc[0]
    assert row['Units'] == 7.25
    assert row['Manual price per unit'] == 12.
    assert row['Minimum order (₪)'] == 50.
    assert str(row['Price date'])[:10] == '2026-10-15'
    assert 'US:ZZTEST' in list(editor['Security'])
    save_edited_holdings(app)
    assert float(rebalance_account['payload']['holdings_account']['positions']['US:GLD']['units']) == 7.25


def test_repeated_additions_keep_drafts_attached_to_security_not_row_index(rebalance_account):
    app = visit()
    app.selectbox(key='rebalance_add_choice').set_value('US:IEF').run()
    edit_holdings(app, {0: {'Value (₪ / $)': 65.}})
    key = f"rebalance_editor_0_{fingerprint(['US:GLD'])[:12]}"
    app.session_state[key] = deepcopy(app.session_state[key])
    button(app, 'Add selected fund').click().run()
    app.selectbox(key='rebalance_add_choice').set_value('TASE:5131792').run()
    button(app, 'Add selected fund').click().run()
    assert not app.exception
    preview = next(t.value for t in app.dataframe if 'Units to save' in t.value)
    assert preview.loc[preview['Fund'] == 'GLD', 'Units to save'].iloc[0] == 6.5
    save_edited_holdings(app)
    saved = rebalance_account['payload']['holdings_account']['positions']
    assert float(saved['US:GLD']['units']) == 6.5
    assert float(saved['US:IEF']['units']) == 0
    assert float(saved['TASE:5131792']['units']) == 0


def test_failed_save_after_add_retains_both_new_row_and_original_draft(rebalance_account, monkeypatch):
    app = visit()
    before = deepcopy(rebalance_account['payload']['holdings_account'])
    app.selectbox(key='rebalance_add_choice').set_value('US:IEF').run()
    edit_holdings(app, {0: {'Value (₪ / $)': 65.}})
    key = f"rebalance_editor_0_{fingerprint(['US:GLD'])[:12]}"
    app.session_state[key] = deepcopy(app.session_state[key])
    button(app, 'Add selected fund').click().run()
    monkeypatch.setattr(sync, 'save_workspace', lambda *a: None)
    save_edited_holdings(app)
    assert not app.exception
    assert rebalance_account['payload']['holdings_account'] == before
    editor = next(t.value for t in app.dataframe if 'Security' in t.value and 'Units' in t.value)
    assert 'US:IEF' in list(editor['Security'])
    assert editor.loc[editor['Security'] == 'US:GLD', 'Value (₪ / $)'].iloc[0] == 65.
    assert not app.success


def test_add_keeps_unpriced_value_draft_without_guessing_or_saving(rebalance_account, monkeypatch):
    monkeypatch.setattr(market, 'unit_quote', lambda *a: {'error': 'missing', 'fresh': False})
    app = visit()
    before = deepcopy(rebalance_account['payload']['holdings_account'])
    app.selectbox(key='rebalance_add_choice').set_value('US:IEF').run()
    edit_holdings(app, {0: {'Value (₪ / $)': 65.}})
    key = f"rebalance_editor_0_{fingerprint(['US:GLD'])[:12]}"
    app.session_state[key] = deepcopy(app.session_state[key])
    button(app, 'Add selected fund').click().run()
    assert not app.exception
    editor = next(t.value for t in app.dataframe if 'Security' in t.value and 'Units' in t.value)
    assert editor.loc[editor['Security'] == 'US:GLD', 'Value (₪ / $)'].iloc[0] == 65.
    assert any('value entry needs a current price' in c.value for c in app.caption)
    save_edited_holdings(app)
    assert rebalance_account['payload']['holdings_account'] == before
    assert button(app, 'What to buy').disabled
