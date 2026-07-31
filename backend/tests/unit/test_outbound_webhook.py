"""Unit tests for the outbound webhook signer + payload (V38, KAN-302).

No database, no network: the signing scheme (:mod:`app.webhook_signing`) and the
payload builder (:mod:`app.outbound._build_payload`) are pure, so we test them
directly. The key property is **symmetry with the inbound GitHub webhook** — the
signature a downstream receiver recomputes over our raw body must match the
``X-Hub-Signature-256`` we send, exactly as the inbound receiver verifies GitHub.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

from app import outbound
from app.webhook_signing import sign, verify


def _receiver_signature(secret: str, body: bytes) -> str:
    """What a downstream receiver independently computes (the reference impl)."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --- the signer -------------------------------------------------------------


def test_sign_matches_a_receivers_independent_hmac():
    secret = "s3cr3t"
    body = b'{"hello":"world"}'
    assert sign(secret, body) == _receiver_signature(secret, body)


def test_sign_has_the_github_sha256_prefix_and_hex_digest():
    sig = sign("k", b"body")
    assert sig.startswith("sha256=")
    hexpart = sig[len("sha256=") :]
    assert len(hexpart) == 64 and int(hexpart, 16) >= 0  # 32-byte digest, valid hex


def test_verify_roundtrips_its_own_signature():
    secret, body = "key", b"payload-bytes"
    assert verify(secret, body, sign(secret, body)) is True


def test_verify_rejects_wrong_secret():
    body = b"payload"
    assert verify("right", body, sign("wrong", body)) is False


def test_verify_rejects_tampered_body():
    secret = "key"
    good = sign(secret, b"original")
    assert verify(secret, b"tampered", good) is False


def test_verify_rejects_missing_or_malformed_header():
    assert verify("k", b"b", None) is False
    assert verify("k", b"b", "") is False
    assert verify("k", b"b", "deadbeef") is False  # no sha256= prefix


def test_sign_differs_by_secret():
    body = b"same-body"
    assert sign("a", body) != sign("b", body)


# --- the payload ------------------------------------------------------------


def _fake_notification():
    from datetime import datetime, timezone

    return SimpleNamespace(
        id=42,
        kind="assigned",
        body="KAN-7 assigned to agent:foo",
        board_id=3,
        card_id=7,
        created_at=datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc),
    )


def test_build_payload_shape():
    payload = outbound._build_payload(_fake_notification())
    assert payload["event"] == "notification.created"
    n = payload["notification"]
    assert n["id"] == 42
    assert n["kind"] == "assigned"
    assert n["board_id"] == 3
    assert n["card_id"] == 7
    assert "KAN-7" in n["body"]
    assert n["created_at"].startswith("2026-07-25T12:00:00")


def test_built_payload_signs_and_verifies_end_to_end():
    """The exact bytes we serialize + sign must verify with the board's secret —
    the property the integration test asserts against a real receiver."""
    secret = "board-secret"
    payload = outbound._build_payload(_fake_notification())
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = sign(secret, body)
    assert signature == _receiver_signature(secret, body)
    assert verify(secret, body, signature) is True
