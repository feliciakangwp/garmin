"""Tiny read-only client for the Garmin Personal API (standard library only)."""
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env.local"
DATA = HERE / "data"
TOKEN_FILE = DATA / "token.json"
BASE = "https://personal.connectapi.garmin.com"
TOKEN_URL = BASE + "/personalapitoken-service/personal-api/personal-api-key/token"
TOKEN_MAX_AGE = 20 * 3600


class ApiError(Exception):
    def __init__(self, status, msg=""):
        super().__init__(f"HTTP {status} {msg}".strip())
        self.status = status


def _ssl_context():
    ctx = ssl.create_default_context()
    for extra in (os.environ.get("SSL_CERT_FILE"), "/root/.ccr/ca-bundle.crt"):
        if extra and os.path.exists(extra):
            ctx.load_verify_locations(extra)
    return ctx


_CTX = _ssl_context()


def read_key():
    """Key from .env.local, falling back to the environment (cloud sessions)."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("GARMIN_PERSONAL_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key
    return os.environ.get("GARMIN_PERSONAL_API_KEY", "").strip()


def _request(url, method="GET", headers=None, timeout=60):
    req = urllib.request.Request(url, method=method, headers=headers or {})
    req.add_header("Accept", "application/json, text/plain")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise ApiError(e.code) from None


def get_token(force=False):
    DATA.mkdir(exist_ok=True)
    if not force and TOKEN_FILE.exists():
        saved = json.loads(TOKEN_FILE.read_text())
        if time.time() - saved.get("created", 0) < TOKEN_MAX_AGE:
            return saved["token"]
    key = read_key()
    if not key:
        raise SystemExit("Your API key is not set in .env.local.")
    try:
        token = _request(TOKEN_URL, "POST", {"Authorization": "ApiKey " + key}).strip()
    except ApiError as e:
        raise SystemExit(
            f"Garmin refused the key ({e}). It may be missing, mistyped or expired: "
            "check .env.local."
        )
    if token.startswith('"'):
        token = json.loads(token)
    TOKEN_FILE.write_text(json.dumps({"token": token, "created": time.time()}))
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return token


def get(path, retries=4):
    """GET a JSON endpoint. Retries on 429/502/503; raises ApiError otherwise."""
    for attempt in range(retries + 1):
        try:
            body = _request(BASE + path, headers={"Authorization": "Bearer " + get_token()})
            time.sleep(0.3)
            return json.loads(body) if body.strip() else None
        except ApiError as e:
            if e.status == 401 and attempt == 0:
                get_token(force=True)
                continue
            if e.status in (429, 502, 503) and attempt < retries:
                time.sleep(3 * (attempt + 1))
                continue
            raise
