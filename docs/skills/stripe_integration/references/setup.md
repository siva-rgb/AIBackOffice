# Stripe — Dashboard Setup Guide

Everything in Test Mode. No real money. Takes ~30 minutes.

---

## Step 1 — Create a Stripe account

Go to: https://dashboard.stripe.com/register
Sign up with your email. No business verification needed for test mode.

After signup, you land on the Dashboard. You're already in **Test Mode** by default.
The toggle at the top right says "Test mode" with an orange badge. Leave it there.

---

## Step 2 — Get your API keys

Go to: Dashboard → Developers → API keys (or: https://dashboard.stripe.com/test/apikeys)

You'll see two keys:
- **Publishable key:** starts with `pk_test_...` — safe to use in frontend code
- **Secret key:** starts with `sk_test_...` — server-side only, NEVER in frontend

Click "Reveal test key" to copy the secret key.

Add both to your `.env`:
```
STRIPE_SECRET_KEY=sk_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

And to your frontend `.env.local`:
```
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## Step 3 — Create your products and prices

Go to: Dashboard → Product catalog → + Add product
(or: https://dashboard.stripe.com/test/products/create)

### Product 1: Kora Starter

```
Name:           Kora Starter
Description:    Unlimited transactions, invoice follow-ups, AI alerts, morning briefing
Price:          $29.00 USD
Billing period: Monthly
```

Click "Save product." You'll see a page with the product details.
Find the **Price** section — it shows a Price ID like `price_1Qxxxxxxxxxxxx`.
Copy this Price ID → add to `.env`:
```
STRIPE_STARTER_PRICE_ID=price_1Qxxxxxxxxxxxx
```

### Product 2: Kora Pro

```
Name:           Kora Pro
Description:    Everything in Starter + contracts, proposals, cash flow, full Butler
Price:          $49.00 USD
Billing period: Monthly
```

Copy the Price ID → add to `.env`:
```
STRIPE_PRO_PRICE_ID=price_1Qyyyyyyyyyyyy
```

### Product 3: Contract Document (one-time)

```
Name:           Kora Contract Document
Description:    Generate one professional contract
Price:          $9.00 USD
Billing period: One time (NOT recurring)
```

Copy the Price ID → add to `.env`:
```
STRIPE_CONTRACT_PRICE_ID=price_1Qzzzzzzzzzzzz
```

---

## Step 4 — Install the Stripe CLI (for local webhook testing)

The Stripe CLI lets you forward webhook events to your local backend.
Without it, webhooks only work after deployment.

### macOS:
```bash
brew install stripe/stripe-cli/stripe
```

### Linux:
```bash
# Download latest release
curl -L https://github.com/stripe/stripe-cli/releases/latest/download/stripe_linux_x86_64.tar.gz -o stripe-cli.tar.gz
tar -xvf stripe-cli.tar.gz
sudo mv stripe /usr/local/bin/
```

### Windows:
Download from: https://github.com/stripe/stripe-cli/releases/latest

### Login to the CLI:
```bash
stripe login
```
This opens a browser window. Click "Allow access." The CLI is now linked to your Stripe account.

---

## Step 5 — Start the webhook listener

In a separate terminal (keep it running while testing):

```bash
stripe listen --forward-to localhost:8000/api/stripe/webhook
```

The CLI outputs:
```
> Ready! Your webhook signing secret is whsec_xxxxxxxxxxxxxxxx
```

**Copy this `whsec_` value** → add to `.env`:
```
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxxxxx
```

IMPORTANT: This secret changes every time you restart `stripe listen`.
For local development, update it each session. For production, you'll
set a permanent webhook secret in the Stripe Dashboard.

---

## Step 6 — Install the Python Stripe SDK

```bash
cd backend
pip install stripe --break-system-packages
echo "stripe>=8.0.0" >> requirements.txt
```

---

## Summary of what you now have

```
Dashboard:
  ✓ Stripe account in Test Mode
  ✓ 3 products created (Starter, Pro, Contract)
  ✓ 3 Price IDs copied to .env

Local:
  ✓ Stripe CLI installed and logged in
  ✓ Webhook listener running → forwarding to localhost:8000
  ✓ stripe Python SDK installed
  
Environment:
  ✓ STRIPE_SECRET_KEY (sk_test_...)
  ✓ STRIPE_PUBLISHABLE_KEY (pk_test_...)
  ✓ STRIPE_WEBHOOK_SECRET (whsec_...)
  ✓ STRIPE_STARTER_PRICE_ID (price_...)
  ✓ STRIPE_PRO_PRICE_ID (price_...)
  ✓ STRIPE_CONTRACT_PRICE_ID (price_...)
```
