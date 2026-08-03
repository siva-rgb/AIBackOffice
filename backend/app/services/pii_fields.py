"""Application-level encryption for sensitive PII fields (M7e).

Tax IDs and bank/payment details are encrypted at the store boundary before
they reach the database. Uses the same Fernet key as OAuth token encryption
(`TOKEN_ENCRYPTION_KEY`). Legacy plaintext rows decrypt transparently.

Encrypted values are prefixed with `enc:v1:` so we can distinguish ciphertext
from legacy cleartext during reads and migrations.
"""

from __future__ import annotations

from typing import Any

from ..models import BusinessProfile, Client, Invoice, User
from .token_encryption import get_fernet

_PREFIX = "enc:v1:"

_USER_PROFILE_PII = ("tax_id", "invoice_footer")


def encrypt_field(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if value.startswith(_PREFIX):
        return value
    token = get_fernet().encrypt(value.encode()).decode()
    return f"{_PREFIX}{token}"


def decrypt_field(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    if not value.startswith(_PREFIX):
        return value  # legacy plaintext
    token = value[len(_PREFIX) :]
    return get_fernet().decrypt(token.encode()).decode()


def _encrypt_profile_dict(profile: dict[str, Any]) -> dict[str, Any]:
    out = dict(profile)
    for key in _USER_PROFILE_PII:
        if key in out and out[key] is not None:
            out[key] = encrypt_field(out[key])
    return out


def _decrypt_profile_dict(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not profile:
        return profile
    out = dict(profile)
    for key in _USER_PROFILE_PII:
        if key in out and out[key] is not None:
            out[key] = decrypt_field(out[key])
    return out


def decrypt_user(user: User | None) -> User | None:
    if not user:
        return user
    profile = user.profile
    if isinstance(profile, BusinessProfile):
        p = profile.model_copy(deep=True)
        p.tax_id = decrypt_field(p.tax_id)
        p.invoice_footer = decrypt_field(p.invoice_footer)
        return user.model_copy(update={"profile": p})
    if isinstance(profile, dict):
        decrypted = _decrypt_profile_dict(profile) or {}
        return user.model_copy(update={"profile": BusinessProfile(**decrypted)})
    return user


def encrypt_user_patch(patch: dict) -> dict:
    out = dict(patch)
    if "profile" in out and isinstance(out["profile"], dict):
        out["profile"] = _encrypt_profile_dict(out["profile"])
    return out


def decrypt_client(client: Client | None) -> Client | None:
    if not client:
        return client
    return client.model_copy(update={"tax_id": decrypt_field(client.tax_id)})


def encrypt_client(client: Client) -> Client:
    return client.model_copy(update={"tax_id": encrypt_field(client.tax_id)})


def encrypt_client_patch(patch: dict) -> dict:
    out = dict(patch)
    if "tax_id" in out and out["tax_id"] is not None:
        out["tax_id"] = encrypt_field(out["tax_id"])
    return out


def decrypt_invoice(inv: Invoice | None) -> Invoice | None:
    if not inv:
        return inv
    return inv.model_copy(update={"client_tax_id": decrypt_field(inv.client_tax_id)})


def encrypt_invoice(invoice: Invoice) -> Invoice:
    return invoice.model_copy(update={"client_tax_id": encrypt_field(invoice.client_tax_id)})


def encrypt_invoice_patch(patch: dict) -> dict:
    out = dict(patch)
    if "client_tax_id" in out and out["client_tax_id"] is not None:
        out["client_tax_id"] = encrypt_field(out["client_tax_id"])
    return out
