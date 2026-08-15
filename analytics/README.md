# kora-analytics

A standalone usage dashboard for the Kora deployment — its own container, its
own dependencies, its own Cloud Run service. It reads the product's database and
writes nothing, so it can be deployed, restarted or deleted with no effect on
the product.

Nothing here imports from `../backend` or `../frontend`, and the Docker build
context is this directory alone, so it cannot quietly grow a dependency on them.

## What it answers

Whether real people, rather than the team, have used the product — and what they
did. Accounts belonging to the team are reported **separately** rather than
folded into the headline: the demo tenant is the shared evaluator login and holds
most of the seeded sample data, so counting it as outside interest would inflate
the number badly, and anyone who recognises `demo@kora.app` in the list would
reasonably discount the rest.

Two joins matter, and both have already caused a bug in this codebase:

- `auth.users` ↔ `public.users` join **by id, never by email**. The demo tenant's
  profile email was repointed once already: its auth email is `demo@kora.app`
  while its profile row reads `pandasivananda0@gmail.com`. An email join splits
  one person into two rows.
- "Signed in" comes from `auth.users.last_sign_in_at`, never from activity rows.
  Seeded data carries a `user_id` without anyone having logged in, and conflating
  the two credits the product with visitors it never had.

## Running it locally

```bash
pip install -r requirements.txt
export SUPABASE_URL=...  SUPABASE_SERVICE_ROLE_KEY=...
uvicorn app.main:app --port 8099
```

Then open <http://127.0.0.1:8099/>.

## Deploying

```bash
bash analytics/deploy.sh
```

Builds through Cloud Build (no local Docker daemon needed) and deploys to Cloud
Run as `kora-analytics`. Credentials are bound from Secret Manager.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `SUPABASE_URL` | — | required |
| `SUPABASE_SERVICE_ROLE_KEY` | — | required; reads across tenants |
| `ANALYTICS_SHOW_EMAILS` | `false` | publish full addresses — see below |
| `ANALYTICS_TEST_ACCOUNTS` | demo, tester, uat-tenant-b, pandasivananda0 | counted separately |
| `ANALYTICS_PRODUCT_URL` | — | adds an "open the app" link |
| `ANALYTICS_CACHE_TTL` | `60` | seconds a snapshot is reused |

### About `ANALYTICS_SHOW_EMAILS`

The service runs **without authentication**, so anything it renders is readable
by anyone who has the URL. Addresses are therefore masked by default —
`kt••••00@gmail.com` — which keeps every number, timeline and per-person row
intact while leaving the address undeliverable. An identifier is not a statistic.

The mask keeps two characters at each end rather than one because two of the real
testers (`kteja4000` and `krishnateja.thallapalli`) collapse to an identical
`k••••••@gmail.com` under a single initial, making two people look like one row —
which defeats the purpose of the table. Short local parts narrow the window
instead, so `demo` never masks to `de••mo` and spell itself back out.

To publish real addresses:

```bash
gcloud run services update kora-analytics --region us-central1 \
  --update-env-vars ANALYTICS_SHOW_EMAILS=true
```

Worth a thought first: the people in that table signed up to help test a product,
not to have their personal address published on the open internet.

## Security posture

The service holds a service-role key, which is precisely the credential that
bypasses row-level security — that is why it can report across tenants at all.
Two properties keep that safe and both are deliberate:

- every route is a **parameterless read**; no user input reaches a query;
- there is **no write path** in the service at all.

If the URL should stop being public, remove the invoker binding — no code change:

```bash
gcloud run services remove-iam-policy-binding kora-analytics \
  --region us-central1 --member=allUsers --role=roles/run.invoker
```

## Tests

```bash
python -m pytest tests/ -q
```
