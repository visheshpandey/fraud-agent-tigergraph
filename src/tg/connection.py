"""TigerGraph connection helper. Reads credentials from `.env` (never hardcoded).

Does NOT use `TigerGraphConnection.getToken()`. pyTigerGraph 2.0.4 attaches a
default `tigergraph`/`tigergraph` Basic-auth header to the token request itself
(see `_prep_req`'s `self._cached_auth`, which ignores the `authMode` argument),
and Savanna rejects that header with a 401 before the secret in the body is ever
checked — confirmed by comparing a raw `requests.post` to `/gsql/v1/tokens`
(200, works) against `conn.getToken(secret)` (401, fails) with an identical
body. Fetching the JWT manually and constructing the connection with `apiToken=`
sidesteps the bug entirely.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv
from pyTigerGraph import TigerGraphConnection

load_dotenv()

TOKEN_LIFETIME_SECONDS = 999_999  # ~11.5 days; re-run to refresh when it expires


def _fetch_jwt(host: str, secret: str) -> str:
    resp = requests.post(
        f"{host}/gsql/v1/tokens",
        json={"secret": secret, "lifetime": TOKEN_LIFETIME_SECONDS},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def get_connection(graphname: str | None = None) -> TigerGraphConnection:
    host = os.environ["TG_HOST"]
    secret = os.environ["TG_SECRET"]
    graphname = graphname or os.environ.get("TG_GRAPHNAME", "FraudGraph")

    token = _fetch_jwt(host, secret)
    return TigerGraphConnection(host=host, graphname=graphname, apiToken=token)


if __name__ == "__main__":
    conn = get_connection()
    print("echo:", conn.echo())
    print("version:", conn.getVer())
