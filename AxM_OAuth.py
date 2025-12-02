#!/usr/bin/env python3
"""
AxM_OAuth.py

Silent, minimal, secure utility for obtaining Apple School/Business Manager
OAuth2 access tokens using ES256 client assertions.

- Loads config from AxM_Variables.env (same folder)
- Generates JWT client assertion
- Retrieves new token if needed
- Retries once on 429 (60 seconds wait)
- Encrypts cached token using Fernet (key stored in .env)
- Logs ONLY whether token is reused or newly generated

Public function:
    get_access_token_and_scope()
"""

import os
import json
import time
import uuid
import datetime as dt

import requests
from dotenv import load_dotenv
from authlib.jose import jwt
from Crypto.PublicKey import ECC
from cryptography.fernet import Fernet, InvalidToken


# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, "AxM_Variables.env")
CACHE_FILE = os.path.join(BASE_DIR, "AxM_Token.cache")

TOKEN_URL = "https://account.apple.com/auth/oauth2/token"
AUDIENCE = "https://account.apple.com/auth/oauth2/v2/token"


# ---------------------------------------------------------
# Config
# ---------------------------------------------------------
def _load_config():
    load_dotenv(ENV_FILE)

    cfg = {
        "CLIENT_ID": os.getenv("APPLE_CLIENT_ID"),
        "KEY_ID": os.getenv("APPLE_KEY_ID"),
        "PRIVATE_KEY_PATH": os.getenv("APPLE_PRIVATE_KEY_PATH"),
        "SCOPE": os.getenv("APPLE_SCOPE"),
        "FERNET_KEY": os.getenv("AXM_FERNET_KEY"),
    }

    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise RuntimeError(
            f"Missing environment variables in AxM_Variables.env: {', '.join(missing)}"
        )

    return cfg


def _fernet(cfg):
    try:
        return Fernet(cfg["FERNET_KEY"].encode())
    except Exception:
        raise RuntimeError("Invalid Fernet key in AXM_FERNET_KEY")


# ---------------------------------------------------------
# Cache
# ---------------------------------------------------------
def _load_cached_token(cfg):
    if not os.path.exists(CACHE_FILE):
        return None

    f = _fernet(cfg)
    try:
        raw = f.decrypt(open(CACHE_FILE, "rb").read())
        cache = json.loads(raw.decode())
    except Exception:
        return None

    required = ("access_token", "expires_at", "client_id", "scope")
    if not all(k in cache for k in required):
        return None

    now = int(time.time())

    if cache["client_id"] != cfg["CLIENT_ID"]:
        return None
    if cache["scope"] != cfg["SCOPE"]:
        return None
    if now >= cache["expires_at"]:
        return None

    return cache


def _save_cached_token(cfg, token_response):
    access_token = token_response.get("access_token")
    expires_in = token_response.get("expires_in")

    if not access_token or expires_in is None:
        return

    now = int(time.time())
    expires_at = now + max(int(expires_in) - 30, 0)

    cache = {
        "access_token": access_token,
        "expires_at": expires_at,
        "client_id": cfg["CLIENT_ID"],
        "scope": cfg["SCOPE"],
        "token_type": token_response.get("token_type", "Bearer"),
    }

    f = _fernet(cfg)
    encrypted = f.encrypt(json.dumps(cache).encode())

    with open(CACHE_FILE, "wb") as fh:
        fh.write(encrypted)

    try:
        os.chmod(CACHE_FILE, 0o600)
    except Exception:
        pass


# ---------------------------------------------------------
# JWT
# ---------------------------------------------------------
def _build_client_assertion(cfg):
    issued = int(dt.datetime.now(dt.timezone.utc).timestamp())
    expires = issued + 86400 * 180

    header = {"alg": "ES256", "kid": cfg["KEY_ID"]}
    payload = {
        "sub": cfg["CLIENT_ID"],
        "iss": cfg["CLIENT_ID"],
        "aud": AUDIENCE,
        "iat": issued,
        "exp": expires,
        "jti": str(uuid.uuid4()),
    }

    try:
        with open(cfg["PRIVATE_KEY_PATH"]) as fh:
            key = ECC.import_key(fh.read())
    except Exception as e:
        raise RuntimeError("Failed to load private key") from e

    try:
        encoded = jwt.encode(
            header=header,
            payload=payload,
            key=key.export_key(format="PEM"),
        )
    except Exception as e:
        raise RuntimeError("Failed to generate JWT client assertion") from e

    return encoded.decode() if isinstance(encoded, bytes) else encoded


# ---------------------------------------------------------
# Token request
# ---------------------------------------------------------
def _request_new_token(cfg, assertion):
    data = {
        "grant_type": "client_credentials",
        "client_id": cfg["CLIENT_ID"],
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion,
        "scope": cfg["SCOPE"],
    }

    for attempt in (1, 2):
        resp = requests.post(TOKEN_URL, data=data)
        
        if resp.status_code == 429:
            if attempt == 1:
                print("INFO: Apple returned 429, waiting 60 seconds before retry.")
                time.sleep(60)
                continue
            raise RuntimeError("Apple returned HTTP 429 twice.")

        if resp.status_code == 400:
            raise RuntimeError(
                "HTTP 400 from Apple. Check APPLE_CLIENT_ID / APPLE_KEY_ID / APPLE_SCOPE."
            )

        try:
            resp.raise_for_status()
            return resp.json()
        except Exception:
            raise RuntimeError(f"Apple token error: {resp.text}")

    raise RuntimeError("Unexpected token flow")


# ---------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------
def get_access_token_and_scope():
    """
    Returns:
        access_token (str), scope (str)
    """
    cfg = _load_config()

    # Check cache first
    cache = _load_cached_token(cfg)
    if cache:
        seconds_left = cache["expires_at"] - int(time.time())
        print(f"INFO: Using existing cached token ({seconds_left} seconds until expiry).")
        return cache["access_token"], cache["scope"]

    print("INFO: Cached token not found or expired. Generating new Apple token...")

    # Create new token
    assertion = _build_client_assertion(cfg)
    token = _request_new_token(cfg, assertion)

    _save_cached_token(cfg, token)

    print("INFO: New token generated and cached securely.")
    return token["access_token"], token.get("scope", cfg["SCOPE"])


# Disable printing token on CLI
if __name__ == "__main__":
    try:
        _, scope = get_access_token_and_scope()
        print("INFO: Token retrieval successful. (Token not displayed)")
        print("Scope:", scope)
    except Exception as e:
        print("ERROR:", e)
        raise SystemExit(1)