# Stripe — Local Testing Guide

Everything here uses Stripe Test Mode. No real money. No real credit cards.

---

## Step 1 — Make sure everything is running

Open THREE terminal windows:

```bash
# Terminal 1: FastAPI backend
cd backend
uvicorn app.main:app --reload --port 8000

# Terminal 2: Next.js frontend
cd frontend
npm run dev

# Terminal 3: Stripe CLI webhook listener
stripe listen --forward-to localhost:8000/api/stripe/webhook
```

Copy the `whsec_` secret from Terminal 3 into your `.env` as `STRIPE_WEBHOOK_SECRET`.
Restart the backend (Terminal 1) so it picks up the new secret.

---

## Step 2 — Test the checkout flow

### From the frontend:
1. Log in to Kora
2. Go to /pricing
3. Click "Subscribe to Starter ($29/mo)"
4. You're redirected to Stripe's hosted checkout page
5. Enter test card: `4242 4242 4242 4242`
   - Expiry: any future date (e.g. `12/28`)
   - CVC: any 3 digits (e.g. `424`)
   - ZIP: any 5 digits (e.g. `42424`)
6. Click Pay
7. You're redirected back to /settings/billing?success=true

### What happens behind the scenes:
- Stripe sends `checkout.session.completed` webhook → your backend
- Backend stores `stripe_customer_id` on the user record
- Stripe sends `customer.subscription.created` webhook → your backend
- Backend reads the price ID → maps to "starter" → updates `users.plan`

### Check in Terminal 3 (Stripe CLI):
You should see:
```
2026-06-27 09:15:23  --> checkout.session.completed [evt_xxxxx]
2026-06-27 09:15:23  <-- [200] POST http://localhost:8000/api/stripe/webhook
2026-06-27 09:15:24  --> customer.subscription.created [evt_xxxxx]
2026-06-27 09:15:24  <-- [200] POST http://localhost:8000/api/stripe/webhook
```

### Verify in the database:
```sql
SELECT plan, stripe_customer_id, stripe_subscription_id 
FROM users WHERE email = 'your@email.com';
-- Should show: plan = 'starter', stripe_customer_id = 'cus_xxx', stripe_subscription_id = 'sub_xxx'
```

---

## Step 3 — Test plan enforcement

After subscribing to Starter, try accessing Pro-only features:
- POST /api/contracts/generate → should return 403 with "upgrade required"
- POST /api/cashflow/forecast → should return 403

Then test upgrading: go through checkout again with the Pro price ID.
After the webhook processes, the same endpoints should return 200.

---

## Step 4 — Test cancellation

1. Go to /settings/billing
2. Click "Cancel subscription"
3. This calls POST /api/stripe/cancel
4. In Stripe Dashboard: Subscriptions → find the subscription → status should show "Cancelling at period end"

To simulate the actual cancellation (end of billing period):
```bash
# In another terminal, trigger the cancellation event manually:
stripe trigger customer.subscription.deleted
```

Check Terminal 3: you should see the event forwarded and the response 200.
Check the database: `users.plan` should now be `'free'`.

---

## Step 5 — Test with different card scenarios

Stripe provides test card numbers for different scenarios:

| Card number | Scenario |
|---|---|
| `4242 4242 4242 4242` | Successful payment |
| `4000 0000 0000 3220` | Requires 3D Secure authentication |
| `4000 0000 0000 0002` | Card declined |
| `4000 0000 0000 9995` | Insufficient funds |
| `4000 0000 0000 0341` | Declined after attaching |

Use these to test error handling:
- Declined card → checkout shows error → user stays on checkout page
- 3D Secure → authentication popup → then success or failure
- Insufficient funds → payment_intent.payment_failed webhook fires

---

## Step 6 — Trigger webhook events manually (without checkout)

The Stripe CLI can simulate events directly:

```bash
# Simulate a new subscription
stripe trigger customer.subscription.created

# Simulate subscription cancellation  
stripe trigger customer.subscription.deleted

# Simulate a payment failure
stripe trigger invoice.payment_failed

# Simulate a successful payment
stripe trigger invoice.payment_succeeded

# Simulate a checkout completion
stripe trigger checkout.session.completed
```

These send synthetic events — the customer/subscription IDs won't match your
test user. But they verify your webhook handler processes each event type
without crashing.

---

## Step 7 — Check the Stripe Dashboard

Go to: https://dashboard.stripe.com/test/payments

You should see your test payment. Click on it to see:
- Amount: $29.00
- Status: Succeeded
- Customer: the email you used
- Subscription: linked

Go to: https://dashboard.stripe.com/test/subscriptions

You should see an active subscription for your test user.

Go to: https://dashboard.stripe.com/test/webhooks

You should see webhook delivery attempts with status 200.

---

## Troubleshooting

**Webhook returns 400 "Invalid signature":**
- The `STRIPE_WEBHOOK_SECRET` doesn't match. Copy the `whsec_` value from the
  `stripe listen` output and restart your backend.
- The webhook handler is parsing the body as JSON before passing to `construct_event`.
  It MUST be raw bytes.

**Checkout redirects but plan doesn't update:**
- Check Terminal 3 — is the webhook being forwarded?
- Check backend logs — any errors in the webhook handler?
- Check the database — is `stripe_customer_id` being stored?
- Common issue: `client_reference_id` not set in checkout session → webhook
  can't find the user. Check that `user_id` is being passed.

**"No such price" error:**
- You're using a Price ID from one Stripe account but API keys from another.
- Or you're using a live Price ID with test API keys. All IDs must be from
  the same mode (test or live).

**Frontend can't redirect to Stripe:**
- Check that `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` is set in `.env.local`.
- Check browser console for CORS errors — the checkout URL should be a
  Stripe domain, not your own.
