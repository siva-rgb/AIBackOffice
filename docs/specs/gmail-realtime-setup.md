# Gmail intel — deployment & real-time push setup

Covers the runtime steps for the 2026-07-15 Gmail intel upgrades (tracker §2.16).

## 0. Apply the migration (required for all four features)

Run in the Supabase SQL editor:

```sql
-- backend/migrations/2026-07-15_gmail_intel_upgrades.sql
alter table clients
  add column if not exists contact_emails text[] default '{}';
alter table google_connections
  add column if not exists watch_history_id text,
  add column if not exists watch_expiration timestamptz;
```

Features 1–3 work immediately after this. Feature 4 (real-time push) needs the Pub/Sub setup below **and** a deployed, publicly reachable backend.

## 1. Feature 1 — multi-contact matching (no infra)

- Domain matching works automatically from each client's primary `email` (corporate domains only).
- To add extra addresses, set `contact_emails` on a client via `PATCH /api/clients/{id}` (or the client form once the UI field is added), e.g. `{"contactEmails": ["ap@acme.com", "cfo@acme.com"]}`.

## 2. Feature 2 — daily scheduled sync (no infra beyond existing cron)

- Endpoint `POST /api/gmail/run` (cron-secret gated) is live.
- The GitHub Actions workflow `.github/workflows/cron.yml` fires it **06:30 UTC daily** once `KORA_API_URL` + `KORA_CRON_SECRET` repo secrets are set (same secrets the other cron jobs use).
- Manual run: Actions → "Kora scheduled agent runs" → Run workflow → job = `gmail`.

## 3. Feature 4 — real-time push (Gmail watch → Pub/Sub)

Only after the backend is deployed with a public HTTPS URL (Cloud Run).

### 3a. Create the Pub/Sub topic
```bash
gcloud pubsub topics create gmail-intel --project=auto-business-prod
```

### 3b. Let Gmail publish to it (required, exact member)
```bash
gcloud pubsub topics add-iam-policy-binding gmail-intel \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher" --project=auto-business-prod
```

### 3c. Create a push subscription → the deployed webhook
```bash
gcloud pubsub subscriptions create gmail-intel-push \
  --topic=gmail-intel \
  --push-endpoint="https://<YOUR_BACKEND_URL>/api/gmail/push" \
  --project=auto-business-prod
```
(For production, secure the endpoint with a Pub/Sub OIDC token / verification token.)

### 3d. Configure the backend
```
GMAIL_PUBSUB_TOPIC=projects/auto-business-prod/topics/gmail-intel
```

### 3e. Register a watch per connected user
- Call `POST /api/gmail/watch` (authed) once per user — or wire it into the OAuth callback.
- Gmail watches **expire after ~7 days**; re-register periodically (e.g. piggyback on the daily `gmail` cron).

### Enable the Pub/Sub API
```bash
gcloud services enable pubsub.googleapis.com --project=auto-business-prod
```

## Notes / limits
- Push is **not** testable on localhost — Pub/Sub cannot reach `http://localhost`. Use `/api/gmail/sync` or `/api/gmail/run` for local testing.
- Deeper analysis (Feature 3) increases per-client token cost (full bodies vs snippets); the caps in `gmail_intel.py` (`_MAX_*`) bound it.
