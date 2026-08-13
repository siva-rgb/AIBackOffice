# Hackathon launch — production deployment

Status of the public deployment that evaluators will use, what has been
verified against it, and the two steps that still need a human in a console.

Deployed 2026-08-13 from `a32cf61`.

## URLs

| | |
|---|---|
| **App (submit this)** | https://kora-frontend-m7hwifxt4q-uc.a.run.app |
| API | https://kora-backend-m7hwifxt4q-uc.a.run.app |
| Staging (unchanged) | https://kora-frontend-staging-m7hwifxt4q-uc.a.run.app |

Production and staging are separate Cloud Run services but **share one Supabase
project**. Staging is therefore not a safe place to test destructive changes —
they land in the same database the public deployment serves.

## Judge access

Two paths, deliberately:

**Demo account** — credentials are printed on the login page.
`demo@kora.app` / `Kora-Demo-2026!`
Pro plan, pre-loaded: 5 clients, 5 invoices, 33 transactions, 3 meetings,
8 tasks, 3 stories, 13 semantic memories, 180 agent-log rows.

**Their own account** — signup seeds the sample business on onboarding
completion (`SEED_SAMPLE_DATA_ON_SIGNUP=true`), so a new tenant is not empty.

The demo account is shared, so everyone signed into it sees the same mutable
data and each other's edits. That is accepted for evaluation; the irreversible
failure it would otherwise allow is closed below.

## Safety of the shared account

`DELETE /api/account/delete` is refused (409) for tenants listed in
`PROTECTED_TENANT_IDS`. Without this, one evaluator exercising the GDPR erasure
feature would wipe the seeded business, revoke the owner's Google grant, and
delete the auth identity behind the published login — ending the demo for
everyone arriving afterwards.

The refusal is honest rather than a faked success, and names what still works
(export) and how to get a tenant where deletion is fully enabled (sign up).

Verified live in production against a disposable tenant rather than the demo
account, so a broken guard could not have destroyed the thing it protects.
That test also covered the comma-separated parsing, which the `^@^` gcloud
delimiter in `cloudbuild.yaml` / `ops/deploy.sh` exists to protect.

## Still needs a human — two console steps

Both are on the sign-in path, and the first is a hard blocker.

### 1. Turn off email confirmation (blocker)

Supabase reports `mailer_autoconfirm: false`, so signup ends at *"Check your
email to confirm your account"*. Confirmation goes through Supabase's built-in
SMTP, which is rate-limited to a handful of messages per hour project-wide —
several judges signing up in one window means most never receive it and cannot
get in. `sivananda@gmail.com` is already sitting UNCONFIRMED in the auth table
from exactly this.

> Supabase dashboard → project `dxtaibfbualhhmznqyzh` → **Authentication** →
> **Sign In / Providers** → **Email** → turn **Confirm email** OFF → Save.

### 2. Enable the Google sign-in provider

`external.google: false`, so the **Continue with Google** button — the most
prominent control on both `/login` and `/signup` — errors on click.

This is the Supabase *sign-in* provider. It is unrelated to the Gmail / Drive /
Calendar integration OAuth, which uses the backend's own client and is verified
working (10 scopes, all endpoints 200).

> Supabase dashboard → **Authentication** → **Sign In / Providers** → **Google**
> → enable, paste the OAuth client ID + secret, Save. Supabase shows a callback
> URL of the form `https://dxtaibfbualhhmznqyzh.supabase.co/auth/v1/callback` —
> add that to **Authorised redirect URIs** on the same OAuth client in the
> Google Cloud console (APIs & Services → Credentials).

Re-test both by signing up with a throwaway address and by clicking the Google
button. If Google cannot be configured in time, hide the button — an error on
first click costs more than a missing convenience.

## Verified against production

| Gate | Result |
|---|---|
| G5 smoke (anonymous) | 19 / 19 |
| G4-auto authenticated | 61 passed, 0 failed |
| Tenant isolation AUTH-07 (S1) | 4 / 4 — B cannot read A's invoice, client, contract, or list |
| Stripe webhook BILL-03 | valid accepted, forged + unsigned rejected |
| Plan gating BILL-04 | enforced server-side |
| GDPR export | 28 tables |
| Backend suite | 617 + 19 new, green |
| Vertex AI | `gemini-2.5-flash` + `gemini-embedding-001`, ADC, live |
| Cloud Run CPU | `cpu-throttling=false` — background agent work runs |

Every case measured green at least once. Runs from the development machine show
intermittent locally-reset connections; Cloud Run logged 200 for every request
it actually received, and the gates now report those as unreachable rather than
as product defects.

## Not covered

The manual matrix (UAT_PLAN §4) has never been run: PDF visual correctness, LLM
output quality, and responsive / cross-browser UX all need human judgement.

Known and accepted: no Resend sender domain (D-011), so outbound email reports
non-delivery honestly rather than sending. Shared-drive handling (D-022) is
unverified for want of a Workspace account with a shared drive.
