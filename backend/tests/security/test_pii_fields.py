"""M7e — Application-level PII field encryption."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import store
from app.backends import memory_store
from app.models import Client, Invoice
from app.seed import DEMO_USER_ID
from app.services.pii_fields import decrypt_field, encrypt_field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_encrypt_decrypt_round_trip():
    plain = "GB123456789"
    enc = encrypt_field(plain)
    assert enc != plain
    assert enc.startswith("enc:v1:")
    assert decrypt_field(enc) == plain


def test_legacy_plaintext_passes_through():
    assert decrypt_field("GB123456789") == "GB123456789"


@pytest.fixture
def _restore_demo_profile():
    user = store.get_user(DEMO_USER_ID)
    original = user.profile.model_dump(mode="json") if user else {}
    yield
    store.update_user(DEMO_USER_ID, {"profile": original})


def test_user_profile_tax_id_encrypted_at_rest(_restore_demo_profile):
    merged = store.get_user(DEMO_USER_ID).profile.model_dump(mode="json")
    merged["tax_id"] = "TAX-SECRET-99"
    store.update_user(DEMO_USER_ID, {"profile": merged})

    raw = memory_store.get_user(DEMO_USER_ID)
    raw_profile = raw.profile if isinstance(raw.profile, dict) else raw.profile.model_dump()
    assert raw_profile["tax_id"] != "TAX-SECRET-99"
    assert raw_profile["tax_id"].startswith("enc:v1:")

    via_store = store.get_user(DEMO_USER_ID)
    assert via_store.profile.tax_id == "TAX-SECRET-99"


def test_client_tax_id_encrypted_at_rest(user_id):
    client = Client(
        id="c-pii",
        user_id=user_id,
        name="Acme",
        tax_id="CLIENT-TAX-1",
        created_at=_now(),
    )
    store.insert_client(client)

    raw = next(c for c in memory_store._clients if c.id == "c-pii")
    assert raw.tax_id.startswith("enc:v1:")

    loaded = store.get_client(user_id, "c-pii")
    assert loaded.tax_id == "CLIENT-TAX-1"


def test_invoice_client_tax_id_encrypted_at_rest(user_id):
    inv = Invoice(
        id="inv-pii",
        user_id=user_id,
        invoice_number="INV-001",
        client_name="Acme",
        client_email="a@acme.com",
        client_tax_id="INV-TAX-42",
        status="draft",
        total=100.0,
        due_date="2026-08-01",
        created_at=_now(),
    )
    store.insert_invoice(inv)

    raw = next(i for i in memory_store._invoices if i.id == "inv-pii")
    assert raw.client_tax_id.startswith("enc:v1:")

    loaded = store.get_invoice(user_id, "inv-pii")
    assert loaded.client_tax_id == "INV-TAX-42"
