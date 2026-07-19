---
name: kora-stripe
description: >
  Implement Stripe billing for Kora: subscription plans (Free/Starter/Pro),
  one-time purchases (pay-per-document), Stripe Checkout, webhook handling,
  and plan enforcement. Also covers testing with Stripe CLI and test cards.
  Use this skill when building any Stripe integration: checkout flow, webhook
  handler, plan gating, billing settings, subscription management, or pricing
  page. Triggers on: "stripe", "billing", "subscription", "checkout",
  "payment", "plan enforcement", "pricing", "upgrade", "downgrade".
---

# Kora Stripe Billing

> "Users can't pay = not a product. This makes Kora a real SaaS."

Two integrations, same skill:
- **Phase 1:** Kora billing — users subscribe to plans, Kora charges them
- **Phase 2:** User's Stripe Connect — user connects their own Stripe so the
  bookkeeper reads their real income/expenses automatically

Read the reference files in this order:
1. `references/setup.md`        — Stripe Dashboard setup, test mode, products, CLI
2. `references/backend.md`      — FastAPI: checkout, webhooks, plan enforcement
3. `references/frontend.md`     — pricing page, checkout button, billing settings
4. `references/testing.md`      — complete local testing flow with dummy data
5. `references/connect.md`      — Stripe Connect: OAuth, sync service, transaction import

---

## 1. Plans and pricing

| Plan | Price | Stripe product | Features |
|---|---|---|---|
| Free | $0 | No Stripe product needed | 20 txns/mo, 1 contract/mo, manual invoicing |
| Starter | $29/mo | `kora_starter` | Unlimited txns, invoice follow-ups, alerts, morning briefing |
| Pro | $49/mo | `kora_pro` | Everything + contracts, proposals, cash flow, full Butler |
| Pay-per-doc | $9 one-time | `kora_contract_doc` | Single contract generation for Free users |

---

## 2. Codebase patterns

- **Models:** Pydantic v2 `CamelModel` with camelCase aliases
- **Store:** `store.py` dispatcher → both `memory_store.py` and `supabase_store.py`
- **Webhook handler:** lives in FastAPI (not Next.js) because the backend handles all business logic
- **Plan field:** `users.plan` column (already exists in schema: `free | starter | pro`)
- **Auth:** `get_current_user` dependency on all routes
- **The webhook MUST receive raw bytes** — not parsed JSON — for signature verification

---

## 3. Build order

**Phase 1 — Stripe Dashboard setup (30 minutes)**
Create account, products, prices, get API keys.
Read `references/setup.md`.

**Phase 2 — Backend: checkout + webhooks + plan enforcement (half day)**
FastAPI routes for creating checkout sessions, handling webhooks, checking plans.
Read `references/backend.md`.

**Phase 3 — Frontend: pricing page + billing settings (half day)**
Pricing cards, checkout redirect, plan management UI.
Read `references/frontend.md`.

**Phase 4 — Local testing with dummy data (1 hour)**
Stripe CLI, test cards, simulating the full flow.
Read `references/testing.md`.

**Phase 5 — Stripe Connect: user's own account for bookkeeping (half day)**
Enable Connect in Dashboard, OAuth flow, transaction sync, frontend.
Read `references/connect.md`.

---

## 4. Environment variables

```bash
# Stripe billing (use test keys)
STRIPE_SECRET_KEY=sk_test_xxxxxxxxxxxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxx
STRIPE_STARTER_PRICE_ID=price_xxxxxxxxxxxx
STRIPE_PRO_PRICE_ID=price_xxxxxxxxxxxx
STRIPE_CONTRACT_PRICE_ID=price_xxxxxxxxxxxx

# Stripe Connect (user's own Stripe account)
STRIPE_CONNECT_CLIENT_ID=ca_xxxxxxxxxxxx
STRIPE_CONNECT_REDIRECT_URI=http://localhost:3000/api/auth/stripe/callback

# Frontend
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxx
```

---

## 5. New files

```
backend/app/
  routers/stripe_billing.py     — checkout, webhook, upgrade, portal, cancel
  routers/stripe_connect.py     — Connect OAuth, sync, disconnect
  services/billing.py           — plan enforcement helpers
  services/stripe_sync.py       — transaction sync + normalization

frontend/
  app/(dashboard)/pricing/page.tsx           — pricing cards (shows current plan)
  app/(dashboard)/settings/billing/page.tsx  — subscription management + portal link
  app/api/webhooks/stripe/route.ts           — webhook proxy
  app/api/auth/stripe/callback/route.ts      — Connect callback proxy
  components/settings/StripeConnectSection.tsx — connect button + sync status
```

---

## 6. API routes summary

```
Phase 1 — Kora billing:
  POST /api/stripe/checkout     — create Stripe Checkout session
  POST /api/stripe/upgrade      — change plan on active subscription
  POST /api/stripe/cancel       — cancel at end of period
  POST /api/stripe/reactivate   — undo cancellation
  POST /api/stripe/portal       — Stripe Customer Portal URL
  GET  /api/stripe/billing      — current plan + subscription status
  POST /api/stripe/webhook      — webhook handler (no auth)

Phase 2 — User's Stripe Connect:
  GET  /api/stripe-connect/connect    — generate Connect OAuth URL
  GET  /api/stripe-connect/callback   — OAuth callback
  GET  /api/stripe-connect/status     — connection status
  POST /api/stripe-connect/sync       — pull transactions
  DELETE /api/stripe-connect/disconnect — revoke + remove
```
