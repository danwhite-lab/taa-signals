"""Optional test-user password exchange. No stored credentials or auth bypass."""
from collections import OrderedDict, deque
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from supabase import ClientOptions, create_client
from .private_api import authenticated, public_config

WORDS = json.loads((Path(__file__).resolve().parents[1]/"web/content/auth.json").read_text())
router = APIRouter()


def failure(status=400):
    return HTTPException(status, WORDS["failure"])


def config():
    email, password = os.environ.get("TEST_LOGIN_EMAIL", ""), os.environ.get("TEST_LOGIN_PASSWORD", "")
    environment = os.environ.get("VERCEL_ENV", "")
    allowed = environment != "production" or os.environ.get("TEST_LOGIN_ALLOW_PRODUCTION") == "true"
    # Fail closed if Vercel's deployment classification is not available.
    if os.environ.get("VERCEL") == "1" and environment not in {"preview", "production", "development"}:
        allowed = False
    if os.environ.get("TEST_LOGIN_ENABLED") != "true" or not email.strip() or not password or not allowed:
        raise failure(404)
    return email, password


def same(left, right):
    # Fixed-length digests support Unicode and avoid compare_digest length leaks.
    return hmac.compare_digest(hashlib.sha256(left.encode()).digest(), hashlib.sha256(right.encode()).digest())


class AttemptLimit:
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()

    def allow(self, identity):
        key = hashlib.sha256(identity.encode()).digest()
        now = monotonic()
        with self.lock:
            for old, times in list(self.entries.items()):
                while times and times[0] <= now-900: times.popleft()
                if not times: del self.entries[old]
            if key not in self.entries:
                if len(self.entries) >= 4096: return False
                self.entries[key] = deque()
            times = self.entries[key]
            if len(times) >= 5: return False
            times.append(now)
            return True


LIMIT = AttemptLimit()


def client_ip(request):
    # Only trust this platform-overwritten header when actually running on Vercel.
    value = request.headers.get("x-vercel-forwarded-for", "") if os.environ.get("VERCEL") == "1" else ""
    try: return str(ipaddress.ip_address(value.split(",")[0].strip()))
    except ValueError: return request.client.host if request.client else "unknown"


def exchange(email, password):
    try:
        url, key = public_config()  # Public key only; never service_role/admin.
        response = create_client(url, key, options=ClientOptions(auto_refresh_token=False, persist_session=False)).auth.sign_in_with_password({"email":email, "password":password})
        session, user = response.session, response.user
        if not session or not user or not user.id or not same(user.email or "", email): raise ValueError()
        if not session.access_token or not session.refresh_token: raise ValueError()
        return {"access_token":session.access_token, "refresh_token":session.refresh_token}
    except Exception:
        # Never return/log provider errors: they may contain credentials/tokens.
        raise failure() from None


@router.get("/api/test-login")
def availability():
    config()
    return {"enabled":True}


@router.post("/api/test-login")
async def login(request: Request):
    email, password = config()
    if not LIMIT.allow(client_ip(request)): raise failure(429)
    try:
        origin = request.headers.get("origin")
        own = (request.url.scheme, request.url.netloc)
        if origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != own: raise ValueError()
        if request.headers.get("sec-fetch-site") == "cross-site": raise ValueError()
        if request.headers.get("content-type", "").split(";")[0] != "application/json": raise ValueError()
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192: raise ValueError()
        values = json.loads(body)
        if not isinstance(values, dict) or set(values) != {"email", "password"}: raise ValueError()
        entered_email, entered_password = values["email"], values["password"]
        if not isinstance(entered_email, str) or not isinstance(entered_password, str): raise ValueError()
        matches_email = same(entered_email, email)
        matches_password = same(entered_password, password)
        if not (matches_email & matches_password): raise ValueError()
    except Exception:
        raise failure() from None
    tokens = await run_in_threadpool(exchange, email, password)
    return JSONResponse(tokens)


@router.get("/api/test-login/status")
def status(settings=Depends(config), session=Depends(authenticated)):
    email, _ = settings
    return {"is_test_login":same(session.get("email", ""), email)}
