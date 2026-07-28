# SOP — `TOKEN_ENCRYPTION_KEY` Rotation & Recovery

> **Audience:** on-call engineers, deployment owners. **Status:** Active.
> **Owner:** security. **Last reviewed:** 2026-07-28 (M3 milestone).

This document describes how to **rotate** the Fernet key used by
`backend/app/services/token_encryption.py` to encrypt OAuth, Notion, and
Stripe-Connect tokens at rest, and how to **recover** when something goes
wrong (lost key, leaked key, or — the most common case — encrypted tokens
becoming unreadable after a key change).

The key is **mandatory at startup**: a missing, empty, or malformed
`TOKEN_ENCRYPTION_KEY` aborts the process with exit code 1
(`tests/security/test_token_encryption.py::test_subprocess_exits_nonzero_without_valid_key`).
There is **no random-key fallback** — generating one at runtime would silently
destroy every encrypted token in the database on the next restart.

---

## 1 · Where the key lives

| Environment | Storage | Bound as |
|---|---|---|
| Local dev | `backend/.env` | `TOKEN_ENCRYPTION_KEY=...` (gitignored) |
| CI (GitHub Actions) | n/a — `conftest.py` injects a fixed test key | `os.environ["TOKEN_ENCRYPTION_KEY"]` |
| Cloud Run (production) | Google Secret Manager | env var `TOKEN_ENCRYPTION_KEY` (see `cloudbuild.yaml` §14) |

Never commit the production key. Never echo it in logs. The
`_scrub_sensitive_data` Sentry hook (in `app/main.py`) redacts fields whose
name contains `token` / `secret`, but **the key itself** is not a field — it
is the encryption context. Treat any leak as **credential compromise**.

## 2 · Generating a new key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Output is a 44-character url-safe base64 string (32 random bytes encoded).
**Generate one per environment** — never reuse a key across dev / staging /
prod. The format is fixed by `cryptography.fernet.Fernet`; no Kora-specific
framing is applied.

## 3 · Rotation procedure (planned, zero-downtime)

Fernet supports **multi-key decryption** via `Fernet.rotate()` /
`MultiFernet`. The current implementation is a single-key Fernet, so the
practical procedure today is **hard cutover**, not zero-downtime rotation.
Hard cutover is acceptable because:

1. The key only protects **OAuth/Notion/Stripe-Connect refresh tokens** —
   losing decryptability means affected users must re-authenticate once,
   not data loss.
2. Refresh-token expiry (Google: ≤ 12h with activity, ≤ 6 months otherwise;
   Notion/Stripe: longer) bounds how many users are affected.
3. Multi-key rotation is a **deliberate future change** — the security bar
   for *that* work is higher (it needs `MultiFernet` plumbing + a migration
   to re-encrypt existing rows). It does not belong in a fail-closed fix.

### 3.1 Pre-flight

1. Snapshot `secrets` table contents (rows with `access_token_enc`,
   `refresh_token_enc`). Use `pg_dump --data-only -t secrets` (or the
   Supabase dashboard) — never paste ciphertext into chat.
2. Announce the rotation window in `#oncall` (≥ 30 min lead time).
3. Verify the **new** key decrypts a test ciphertext before touching prod:
   ```bash
   python -c "
   from cryptography.fernet import Fernet
   f = Fernet('<new-key>')
   print(f.decrypt('<test-ciphertext>'))
   "
   ```

### 3.2 Cutover

1. Generate the new key (see §2).
2. Update Secret Manager: `gcloud secrets versions add TOKEN_ENCRYPTION_KEY --data-file=-`.
3. Roll Cloud Run: a new revision picks up the new env var. **All existing
   encrypted tokens become unreadable on first decrypt.** This is expected.
4. On the next request from each user that hits an encrypted token, the
   `InvalidToken` exception bubbles up to the OAuth reconnect flow
   (`services/google_auth.py::get_user_credentials` flags the connection
   for reconnect). The user sees "Please reconnect Google / Notion" — no
   data loss, no privilege escalation.

### 3.3 Post-cutover

1. Monitor Sentry / error rate for `InvalidToken` (a brief spike is normal).
2. After 24h with no `InvalidToken` errors, mark the old key version as
   `disabled` in Secret Manager (do not delete for 30 days — see §5).
3. Update `docs/specs/tracker.md` with the rotation date.

## 4 · Recovery: "we lost the key"

If the **only copy** of the production key is gone (lost laptop, ex-employee,
accidental secret-version destroy):

1. **Accept the loss.** There is no way to recover Fernet ciphertexts
   without the key — that is the property the control enforces.
2. **Trigger a forced reconnect** for every user. The cleanest way is:
   ```sql
   UPDATE oauth_connections SET access_token_enc = NULL, refresh_token_enc = NULL;
   ```
   (for the relevant table once identified — schema is in
   `docs/specs/schema.sql`).
3. Users re-authenticate. No data is leaked (no key = no ciphertext
   recovery, so no adversary gets them either).
4. Generate a **new** key (see §2), deploy it, resume service.

## 5 · Recovery: "the key was leaked"

If an **adversary** obtains the production key:

1. **Treat every encrypted token as compromised.** Rotate immediately per
   §3 — do not wait for the planned window.
2. **Revoke the underlying OAuth grants** at the provider:
   - Google: `https://myaccount.google.com/permissions` (manual) or
     revoke via the Admin SDK for Workspace tenants.
   - Notion: integration settings → delete integration.
   - Stripe Connect: disconnect the connected account from the platform.
3. **Force-reconnect all users** per §4 step 2.
4. **Post-mortem**: how did the key escape? Open an ADR in
   `.genesis/decisions/` with the root cause and the prevention.

The old key stays valid for `InvalidToken` decryption for 30 days
post-rotation, so a leaked key's blast radius is bounded to that window
even if step 1 is delayed.

## 6 · Testing locally

The smoke test in `tests/security/test_token_encryption.py` simulates both
the missing-key and malformed-key failure paths in a subprocess. To run it
by hand:

```bash
cd backend
TOKEN_ENCRYPTION_KEY="" python -c "from app.services.token_encryption import load_key"
# → StartupError: TOKEN_ENCRYPTION_KEY is not set. ... (exit 1)

TOKEN_ENCRYPTION_KEY=garbage python -c "from app.services.token_encryption import load_key"
# → StartupError: TOKEN_ENCRYPTION_KEY is malformed ... (exit 1)
```

## 7 · Multi-key rotation (future work, **out of scope for M3**)

When the operational bar for rotation rises (e.g. SOC2 demands zero user
reconnects during rotation), the path is:

1. Switch `load_key()` to build `MultiFernet([old_key, new_key])`.
2. Write a one-shot script that re-encrypts every existing row with
   `new_key` (read with `old_key`, write with `new_key`).
3. After the migration completes, drop `old_key` from `MultiFernet`.

This needs its own milestone — not part of the fail-closed fix that M3
delivers.

---

**See also:**
- `app/services/token_encryption.py` — implementation + inline docstring.
- `tests/security/test_token_encryption.py` — M3.3 smoke test.
- `cloudbuild.yaml` §14 — Secret Manager binding.
- `docs/specs/tracker.md` row 477 — historical context (the 2026-07-15
  `os.environ` → `settings` bug that motivated M3).
