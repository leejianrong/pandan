"""OAuth 2.1 authorization_code + PKCE grant primitives (ADR 0026, KAN-1735).
Pure-logic unit tests — no DB, mirrors ``tests/unit/test_oauth_client.py``'s
style for this same feature area."""
from __future__ import annotations

import base64
import hashlib

from app import oauth_authorize as oa


def _challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


class _FakeURL:
    def __init__(self, base: str) -> None:
        self._base = base

    def __str__(self) -> str:
        return self._base


class _FakeRequest:
    def __init__(self, base_url: str) -> None:
        self.base_url = _FakeURL(base_url)


# --- verify_pkce ---------------------------------------------------------


def test_verify_pkce_accepts_matching_verifier():
    verifier = "a" * 43  # RFC 7636 §4.1: 43-128 chars
    assert oa.verify_pkce(verifier, _challenge_for(verifier)) is True


def test_verify_pkce_rejects_wrong_verifier():
    verifier = "a" * 43
    other = "b" * 43
    assert oa.verify_pkce(other, _challenge_for(verifier)) is False


def test_verify_pkce_rejects_garbage_challenge():
    assert oa.verify_pkce("a" * 43, "not-a-real-challenge") is False


# --- secret generation -----------------------------------------------------


def test_generate_authorization_code_is_high_entropy_and_unique():
    codes = {oa.generate_authorization_code() for _ in range(50)}
    assert len(codes) == 50
    assert all(len(c) >= 32 for c in codes)


def test_generate_refresh_token_is_high_entropy_and_unique():
    tokens = {oa.generate_refresh_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) >= 32 for t in tokens)


# --- canonical_mcp_resource -------------------------------------------------


def test_canonical_mcp_resource_derives_from_request_origin():
    assert (
        oa.canonical_mcp_resource(_FakeRequest("http://localhost:8000/"))
        == "http://localhost:8000/mcp"
    )
    assert (
        oa.canonical_mcp_resource(_FakeRequest("https://simple-kanban-jian.fly.dev"))
        == "https://simple-kanban-jian.fly.dev/mcp"
    )
