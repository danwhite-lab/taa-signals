"""Offline auth tests. Credentials are generated at runtime, never fixtures."""
import hashlib
import json
import secrets
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from starlette.requests import Request
from test_api import client, module, ROOT
from test_private_api import signed_in, HEADERS
from server import test_login as page


@pytest.fixture
def configured(monkeypatch,signed_in):
    email=secrets.token_hex(12)+"@example.invalid"
    password=secrets.token_urlsafe(32)
    monkeypatch.setenv("TEST_LOGIN_ENABLED","true")
    monkeypatch.setenv("TEST_LOGIN_EMAIL",email)
    monkeypatch.setenv("TEST_LOGIN_PASSWORD",password)
    monkeypatch.setenv("VERCEL_ENV","preview")
    monkeypatch.setattr(page,"LIMIT",page.AttemptLimit())
    sdk=Mock()
    sdk.auth.sign_in_with_password.return_value=SimpleNamespace(user=SimpleNamespace(id="fake-test-user",email=email),session=SimpleNamespace(access_token="mock-access",refresh_token="mock-refresh"))
    factory=Mock(return_value=sdk);monkeypatch.setattr(page,"create_client",factory)
    return email,password,sdk,factory


@pytest.mark.parametrize("name",["TEST_LOGIN_ENABLED","TEST_LOGIN_EMAIL","TEST_LOGIN_PASSWORD"])
@pytest.mark.parametrize("empty",[False,True])
def test_each_missing_or_empty_gate_is_404(configured,monkeypatch,name,empty):
    if empty:monkeypatch.setenv(name,"")
    else:monkeypatch.delenv(name)
    for response in (client.get("/api/test-login"),client.post("/api/test-login",json={}),client.get("/api/test-login/status",headers=HEADERS)):
        assert response.status_code==404 and response.json()=={"detail":"Sign-in failed"}
        assert response.headers["cache-control"]=="no-store, private"
    configured[3].assert_not_called()


@pytest.mark.parametrize("enabled",["false","True","1"])
def test_enabled_requires_exact_true(configured,monkeypatch,enabled):
    monkeypatch.setenv("TEST_LOGIN_ENABLED",enabled)
    assert client.get("/api/test-login").status_code==404


@pytest.mark.parametrize("allow",[None,"false","True"])
def test_production_requires_explicit_extra_true(configured,monkeypatch,allow):
    monkeypatch.setenv("VERCEL_ENV","production")
    if allow is not None:monkeypatch.setenv("TEST_LOGIN_ALLOW_PRODUCTION",allow)
    assert client.get("/api/test-login").status_code==404
    assert client.post("/api/test-login",json={}).status_code==404


def test_explicit_production_and_unknown_platform_environment(configured,monkeypatch):
    monkeypatch.setenv("VERCEL","1");monkeypatch.setenv("VERCEL_ENV","production");monkeypatch.setenv("TEST_LOGIN_ALLOW_PRODUCTION","true")
    assert client.get("/api/test-login").json()=={"enabled":True}
    monkeypatch.delenv("VERCEL_ENV")
    assert client.get("/api/test-login").status_code==404


def test_success_returns_only_tokens_and_uses_public_key_no_server_refresh(configured,caplog):
    email,password,sdk,factory=configured
    response=client.post("/api/test-login",json={"email":email,"password":password})
    assert response.status_code==200 and response.json()=={"access_token":"mock-access","refresh_token":"mock-refresh"}
    assert response.headers["cache-control"]=="no-store, private" and response.headers["pragma"]=="no-cache"
    assert "set-cookie" not in response.headers
    sdk.auth.sign_in_with_password.assert_called_once_with({"email":email,"password":password})
    assert factory.call_args.args==("https://mock.invalid","mock-public")
    assert not factory.call_args.kwargs["options"].auto_refresh_token and not factory.call_args.kwargs["options"].persist_session
    assert email not in response.text+caplog.text and password not in response.text+caplog.text


@pytest.mark.parametrize("wrong",["email","password","both"])
def test_wrong_credentials_constant_time_both_checks_generic(configured,monkeypatch,wrong,caplog):
    email,password,_,factory=configured
    compare=Mock(wraps=page.hmac.compare_digest);monkeypatch.setattr(page.hmac,"compare_digest",compare)
    response=client.post("/api/test-login",json={"email":email if wrong=="password" else secrets.token_hex(8),"password":password if wrong=="email" else secrets.token_urlsafe(16)})
    assert response.status_code==400 and response.json()=={"detail":"Sign-in failed"}
    assert compare.call_count==2 and all(len(v)==32 for call in compare.call_args_list for v in call.args)
    factory.assert_not_called()
    assert email not in response.text+caplog.text and password not in response.text+caplog.text


def test_provider_exception_and_wrong_returned_user_are_private(configured,caplog):
    email,password,sdk,_=configured
    sdk.auth.sign_in_with_password.side_effect=RuntimeError(email+password)
    response=client.post("/api/test-login",json={"email":email,"password":password})
    assert response.status_code==400 and response.json()=={"detail":"Sign-in failed"}
    assert email not in response.text+caplog.text and password not in response.text+caplog.text
    sdk.auth.sign_in_with_password.side_effect=None
    sdk.auth.sign_in_with_password.return_value.user.email=secrets.token_hex(8)
    assert client.post("/api/test-login",json={"email":email,"password":password}).status_code==400


def test_rate_limit_five_in_fifteen_minutes_and_recovery(configured,monkeypatch):
    now=[1000.];monkeypatch.setattr(page,"monotonic",lambda:now[0])
    for _ in range(5):assert client.post("/api/test-login",json={}).status_code==400
    response=client.post("/api/test-login",json={})
    assert response.status_code==429 and response.json()=={"detail":"Sign-in failed"}
    # IPs are hashed, credentials never enter limiter state.
    assert all(isinstance(key,bytes) and len(key)==32 for key in page.LIMIT.entries)
    now[0]+=901
    assert client.post("/api/test-login",json={}).status_code==400


def test_trusted_platform_ip_and_bounded_fail_closed_limit(configured,monkeypatch):
    request=Request({"type":"http","client":("192.0.2.1",1),"headers":[(b"x-vercel-forwarded-for",b"192.0.2.2")]})
    assert page.client_ip(request)=="192.0.2.1"
    monkeypatch.setenv("VERCEL","1")
    assert page.client_ip(request)=="192.0.2.2"
    limit=page.AttemptLimit()
    limit.entries.update({hashlib.sha256(str(i).encode()).digest():page.deque([page.monotonic()]) for i in range(4096)})
    assert not limit.allow("new-ip") and len(limit.entries)==4096


@pytest.mark.parametrize("body",[[],{}, {"email":None,"password":None},{"email":"invalid","password":"invalid","extra":True}])
def test_invalid_shapes_generic(configured,body):
    response=client.post("/api/test-login",json=body)
    assert response.status_code==400 and response.json()=={"detail":"Sign-in failed"}


def test_malformed_oversized_cross_origin_and_wrong_method(configured):
    email,password,_,factory=configured
    body={"email":email,"password":password}
    for kwargs in ({"content":"{"},{"content":"X"*8193,"headers":{"content-type":"application/json"}},
                   {"json":body,"headers":{"origin":"https://different.invalid"}},
                   {"json":body,"headers":{"sec-fetch-site":"cross-site"}}):
        response=client.post("/api/test-login",**kwargs)
        assert response.status_code==400 and response.json()=={"detail":"Sign-in failed"}
    factory.assert_not_called()
    assert client.put("/api/test-login",json=body).json()=={"detail":"Sign-in failed"}


def test_badge_uses_verified_email_never_user_metadata(configured,monkeypatch):
    email,_,_,_=configured
    assert client.get("/api/test-login/status").status_code==401
    def verify(*args):return {"user_id":"fake-test-user","email":email,"access_token":"mock-token"}
    monkeypatch.setattr(module.private_api.sync,"verified_session",verify)
    assert client.get("/api/test-login/status",headers=HEADERS).json()=={"is_test_login":True}
    monkeypatch.setattr(module.private_api.sync,"verified_session",lambda *a:{"user_id":"other-user","email":"other","user_metadata":{"is_test_login":True}})
    assert client.get("/api/test-login/status",headers=HEADERS).json()=={"is_test_login":False}


def test_no_credentials_in_files_and_google_flow_unchanged():
    source=(ROOT/"web/app/login/page.tsx").read_text()
    assert 'provider: "google"' in source and '/auth/callback/' in source
    for path in ("web/lib/testLogin.ts","web/components/TestLogin.tsx","web/components/TestLoginBadge.tsx"):
        text=(ROOT/path).read_text()
        assert "process.env.TEST_LOGIN" not in text and "NEXT_PUBLIC_TEST" not in text
        assert "console." not in text and "auth.signInWithPassword" not in text
