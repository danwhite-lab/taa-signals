from copy import deepcopy

import pytest

import haa.supabase_sync as sync
from haa.rebalance_holdings import empty_account


def candidate():
    account = empty_account()
    account.update(revision=1, cash_ils='100', last_operation_id='unique-test-operation')
    return {'holdings_account': account, 'portfolio_name': 'Unchanged setting'}


def test_holdings_save_uses_existing_user_scoped_revision_checked_storage(monkeypatch):
    calls = []
    def save(url, key, session, payload, revision):
        calls.append((session['user_id'], deepcopy(payload), revision))
        return revision+1
    monkeypatch.setattr(sync, 'save_workspace', save)
    result = sync.save_holdings_workspace('url', 'public-key', {'user_id': 'one-user'}, candidate(), 5)
    assert result['revision'] == 6
    assert calls == [('one-user', candidate(), 5)]


@pytest.mark.parametrize('response_lost', [False, True])
def test_lost_response_recovers_exact_saved_operation_without_reapplying(monkeypatch, response_lost):
    remote = {'revision': 6, 'payload': candidate()}
    def save(*args):
        if response_lost:
            raise TimeoutError('Server committed but response lost')
        return None
    monkeypatch.setattr(sync, 'save_workspace', save)
    monkeypatch.setattr(sync, 'load_workspace', lambda *a: deepcopy(remote))
    assert sync.save_holdings_workspace('url', 'key', {}, candidate(), 5) == remote


def test_other_device_conflict_never_overwrites_or_claims_success(monkeypatch):
    remote = {'revision': 7, 'payload': candidate()}
    remote['payload']['holdings_account']['cash_ils'] = '999'
    before = deepcopy(remote)
    monkeypatch.setattr(sync, 'save_workspace', lambda *a: None)
    monkeypatch.setattr(sync, 'load_workspace', lambda *a: deepcopy(remote))
    with pytest.raises(RuntimeError, match='another device'):
        sync.save_holdings_workspace('url', 'key', {}, candidate(), 5)
    assert remote == before


def test_no_operation_id_is_rejected_before_database_access(monkeypatch):
    payload = candidate()
    payload['holdings_account']['last_operation_id'] = None
    monkeypatch.setattr(sync, 'save_workspace', lambda *a: pytest.fail('Must validate first'))
    with pytest.raises(ValueError): sync.save_holdings_workspace('url', 'key', {}, payload, 1)
