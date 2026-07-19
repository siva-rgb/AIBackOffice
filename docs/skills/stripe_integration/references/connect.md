# Stripe Connect — User's Own Stripe Account for Bookkeeping

Users connect their Stripe account so the bookkeeper reads their real
charges, payouts, refunds, and fees automatically. This is a THIRD data
source alongside CSV upload and PDF bank statement — additive, not replacing.

```
Data sources for the bookkeeper (all three coexist):
  1. CSV upload        → existing, unchanged
  2. PDF bank statement → skill 06, unchanged
  3. Stripe Connect    → THIS feature (real-time from user's Stripe)
```

---

## Prerequisites — Stripe Connect platform setup

Before building, you must enable Connect on your Stripe account. This is a
one-time setup in the Stripe Dashboard (separate from the billing products
you already created).

### Step 1: Enable Connect

Go to: Stripe Dashboard → Settings → Connect (or: https://dashboard.stripe.com/test/settings/connect)
Click "Get started with Connect"
Platform type: select "Platform or marketplace"
Complete the basic form (business name, URL, description)

### Step 2: Get the Connect client_id

Go to: Dashboard → Settings → Connect → OAuth
(or: https://dashboard.stripe.com/test/settings/connect/oauth)

You'll see a **Client ID** that starts with `ca_` (e.g. `ca_FkyHCg7X8mlvCUdMDao4mMxagUfhIwXb`)
This is different from your API keys. Copy it.

### Step 3: Set redirect URIs

On the same page, under "Redirects":
Add: `http://localhost:3000/api/auth/stripe/callback`
Add: `https://kora.app/api/auth/stripe/callback`

### Step 4: Environment variables

```bash
# Add to backend/.env (alongside existing STRIPE_SECRET_KEY):
STRIPE_CONNECT_CLIENT_ID=ca_xxxxxxxxxxxxxxxxxxxx
STRIPE_CONNECT_REDIRECT_URI=http://localhost:3000/api/auth/stripe/callback
```

---

## Schema — stripe_connections table

```sql
CREATE TABLE stripe_connections (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE UNIQUE,

  -- Connected account identity
  stripe_account_id   TEXT NOT NULL,      -- acct_xxxxx (the user's Stripe account ID)
  stripe_email        TEXT,               -- email on their Stripe account

  -- OAuth tokens (encrypted — same pattern as Google OAuth)
  access_token_enc    TEXT NOT NULL,       -- Fernet-encrypted
  refresh_token_enc   TEXT,               -- Fernet-encrypted
  token_scope         TEXT DEFAULT 'read_only',
  livemode            BOOLEAN DEFAULT FALSE,

  -- Sync state
  connected           BOOLEAN DEFAULT TRUE,
  last_sync_at        TIMESTAMPTZ,
  last_sync_txn_count INTEGER DEFAULT 0,
  sync_cursor         TEXT,               -- last balance_transaction ID for pagination
  last_error          TEXT,

  created_at          TIMESTAMPTZ DEFAULT now(),
  updated_at          TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE stripe_connections ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_stripe" ON stripe_connections
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());
```

---

## Backend — OAuth flow

```python
# backend/app/routers/stripe_connect.py
"""
Stripe Connect OAuth — user connects their own Stripe account.
Separate router from stripe_billing.py (which handles Kora's own billing).
"""
import os
import stripe
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from app.dependencies import get_current_user
from app.services.token_encryption import encrypt_token, decrypt_token
from app import store
from datetime import datetime

router = APIRouter(prefix="/stripe-connect", tags=["stripe-connect"])

CONNECT_CLIENT_ID = os.environ.get("STRIPE_CONNECT_CLIENT_ID", "")
CONNECT_REDIRECT_URI = os.environ.get("STRIPE_CONNECT_REDIRECT_URI", "")
STRIPE_SECRET = os.environ.get("STRIPE_SECRET_KEY", "")


@router.get("/connect")
async def connect_stripe(user=Depends(get_current_user)):
    """
    Generate the Stripe Connect OAuth URL.
    Frontend redirects the browser here.
    """
    if not CONNECT_CLIENT_ID:
        raise HTTPException(500, "Stripe Connect not configured")

    # Build OAuth URL with read_only scope
    auth_url = (
        f"https://connect.stripe.com/oauth/authorize"
        f"?response_type=code"
        f"&client_id={CONNECT_CLIENT_ID}"
        f"&scope=read_only"
        f"&state={user['id']}"
        f"&redirect_uri={CONNECT_REDIRECT_URI}"
    )
    return {"auth_url": auth_url}


@router.get("/callback")
async def stripe_connect_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
):
    """
    Stripe redirects here after the user grants/denies permission.
    state = user_id (set in /connect).
    """
    frontend_url = os.environ.get("NEXT_PUBLIC_APP_URL", "http://localhost:3000")

    if error:
        return RedirectResponse(
            f"{frontend_url}/settings?stripe_connect_error={error}"
        )

    if not code or not state:
        return RedirectResponse(
            f"{frontend_url}/settings?stripe_connect_error=missing_params"
        )

    user_id = state

    try:
        # Exchange authorization code for access token
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://connect.stripe.com/oauth/token",
                data={
                    "client_secret": STRIPE_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                },
                timeout=15.0,
            )
            data = response.json()

        if "error" in data:
            return RedirectResponse(
                f"{frontend_url}/settings?stripe_connect_error={data['error']}"
            )

        # Extract token data
        access_token = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")
        stripe_account_id = data.get("stripe_user_id", "")
        livemode = data.get("livemode", False)
        scope = data.get("scope", "read_only")

        # Get the connected account's email
        stripe_email = ""
        try:
            acct = stripe.Account.retrieve(stripe_account_id)
            stripe_email = acct.get("email", "")
        except Exception:
            pass

        # Encrypt tokens before storage
        access_enc = encrypt_token(access_token)
        refresh_enc = encrypt_token(refresh_token) if refresh_token else None

        # Store in DB
        store.upsert_stripe_connection(user_id, {
            "stripe_account_id": stripe_account_id,
            "stripe_email": stripe_email,
            "access_token_enc": access_enc,
            "refresh_token_enc": refresh_enc,
            "token_scope": scope,
            "livemode": livemode,
            "connected": True,
            "last_error": None,
        })

        from app.services.agent_logger import log_agent_action
        log_agent_action(
            user_id=user_id,
            agent_type="billing",
            action=f"Connected Stripe account: {stripe_email or stripe_account_id}",
            input_data={},
            output_data={"account_id": stripe_account_id, "scope": scope},
            latency_ms=0,
            triggered_by="user",
        )

        return RedirectResponse(
            f"{frontend_url}/settings?stripe_connect_success=true"
        )

    except Exception as e:
        return RedirectResponse(
            f"{frontend_url}/settings?stripe_connect_error=token_exchange_failed"
        )


@router.get("/status")
async def stripe_connect_status(user=Depends(get_current_user)):
    """Get connection status for settings page."""
    conn = store.get_stripe_connection(user["id"])
    if not conn or not conn.get("connected"):
        return {"connected": False}
    return {
        "connected": True,
        "email": conn.get("stripe_email"),
        "account_id": conn.get("stripe_account_id"),
        "last_sync": conn.get("last_sync_at"),
        "last_sync_count": conn.get("last_sync_txn_count", 0),
        "livemode": conn.get("livemode", False),
    }


@router.delete("/disconnect")
async def disconnect_stripe(user=Depends(get_current_user)):
    """Revoke access and remove connection."""
    conn = store.get_stripe_connection(user["id"])
    if not conn:
        return {"disconnected": True}

    # Revoke the connection via Stripe API
    try:
        stripe.OAuth.deauthorize(
            client_id=CONNECT_CLIENT_ID,
            stripe_user_id=conn["stripe_account_id"],
        )
    except Exception:
        pass  # revocation failure should not block local cleanup

    store.delete_stripe_connection(user["id"])
    return {"disconnected": True}


@router.post("/sync")
async def trigger_sync(user=Depends(get_current_user)):
    """
    Manually trigger a sync of the user's Stripe transactions.
    Returns the extracted transactions for review (same format as CSV/PDF).
    """
    from app.services.stripe_sync import sync_stripe_transactions
    result = await sync_stripe_transactions(user["id"])
    return result
```

---

## Backend — Transaction sync service

```python
# backend/app/services/stripe_sync.py
"""
Pull transactions from a user's connected Stripe account and normalize
into Kora's transaction format. Same output as CSV upload and PDF extraction.
"""
import stripe
from datetime import datetime, timedelta
from app import store
from app.services.token_encryption import decrypt_token
from app.services.agent_logger import log_agent_action

# Stripe API calls on behalf of connected accounts use the platform's
# secret key + the connected account's ID (NOT the user's access token).
# This is simpler and more reliable than using the access token directly.


async def sync_stripe_transactions(
    user_id: str,
    days_back: int = 30,
) -> dict:
    """
    Pull balance transactions from the user's connected Stripe account.
    Returns transactions in the same format as CSV/PDF uploads.
    """
    start = datetime.utcnow()

    conn = store.get_stripe_connection(user_id)
    if not conn or not conn.get("connected"):
        return {"error": "Stripe not connected", "transactions": []}

    account_id = conn["stripe_account_id"]

    try:
        # Pull balance transactions (the most comprehensive view)
        # This includes: charges, payouts, refunds, fees, adjustments
        since = int((datetime.utcnow() - timedelta(days=days_back)).timestamp())

        all_txns = []
        has_more = True
        starting_after = conn.get("sync_cursor")  # resume from last sync

        while has_more:
            params = {
                "limit": 100,
                "created": {"gte": since},
                "stripe_account": account_id,
            }
            if starting_after:
                params["starting_after"] = starting_after

            balance_txns = stripe.BalanceTransaction.list(**params)
            all_txns.extend(balance_txns.data)
            has_more = balance_txns.has_more

            if balance_txns.data:
                starting_after = balance_txns.data[-1].id

            # Safety: max 500 transactions per sync
            if len(all_txns) >= 500:
                break

        # Normalize into Kora's transaction format
        transactions = _normalize_stripe_transactions(all_txns)

        # Update sync state
        store.update_stripe_connection(user_id, {
            "last_sync_at": datetime.utcnow().isoformat(),
            "last_sync_txn_count": len(transactions),
            "sync_cursor": starting_after,
            "last_error": None,
        })

        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        log_agent_action(
            user_id=user_id,
            agent_type="billing",
            action=f"Synced {len(transactions)} transactions from Stripe",
            input_data={"account_id": account_id, "days_back": days_back},
            output_data={"transaction_count": len(transactions)},
            latency_ms=latency_ms,
            triggered_by="user",
        )

        return {
            "transactions": transactions,
            "source": "stripe_connect",
            "account_email": conn.get("stripe_email", ""),
            "synced_count": len(transactions),
        }

    except stripe.error.StripeError as e:
        store.update_stripe_connection(user_id, {
            "last_error": str(e),
        })
        return {"error": f"Stripe API error: {str(e)}", "transactions": []}


def _normalize_stripe_transactions(balance_txns: list) -> list[dict]:
    """
    Convert Stripe balance transactions into Kora's transaction format.
    This is deterministic — no LLM needed. Stripe data is already structured.
    """
    transactions = []

    for bt in balance_txns:
        # Map Stripe transaction types to Kora types
        stripe_type = bt.get("type", "")
        description = bt.get("description", "") or ""

        # Determine Kora type (income vs expense)
        amount = bt.get("amount", 0) / 100  # Stripe amounts are in cents
        currency = (bt.get("currency", "usd") or "usd").upper()

        if stripe_type == "charge":
            kora_type = "income"
            category = "client_payment"
            if not description:
                description = "Stripe charge"

        elif stripe_type == "payout":
            # Payouts are money leaving Stripe to the bank — not an expense,
            # it's a transfer. Skip for bookkeeping purposes (the charge is the income).
            continue

        elif stripe_type == "refund":
            kora_type = "expense"  # negative income adjustment
            category = "refund_given"
            amount = -abs(amount)
            if not description:
                description = "Stripe refund"

        elif stripe_type == "stripe_fee":
            kora_type = "expense"
            category = "bank_fees"
            amount = -abs(amount)
            if not description:
                description = "Stripe processing fee"

        elif stripe_type == "adjustment":
            kora_type = "income" if amount > 0 else "expense"
            category = "other_income" if amount > 0 else "other_expense"
            if not description:
                description = "Stripe adjustment"

        elif stripe_type in ("transfer", "transfer_reversal"):
            continue  # internal Stripe movements — skip

        else:
            kora_type = "income" if amount > 0 else "expense"
            category = "other_income" if amount > 0 else "other_expense"

        # Extract date
        created = bt.get("created", 0)
        date_str = datetime.utcfromtimestamp(created).strftime("%Y-%m-%d") if created else ""

        # Try to find customer name (from the charge's customer field)
        customer_name = ""
        source = bt.get("source")
        if source and isinstance(source, str) and source.startswith("ch_"):
            try:
                charge = stripe.Charge.retrieve(
                    source,
                    stripe_account=bt.get("account", ""),
                )
                customer_name = charge.get("billing_details", {}).get("name", "")
            except Exception:
                pass

        transactions.append({
            "date": date_str,
            "description": f"{customer_name + ' — ' if customer_name else ''}{description}",
            "amount": round(amount, 2),
            "type": kora_type,
            "currency": currency,
            "category": category,
            "source": "stripe_connect",
            "ai_categorized": True,   # pre-categorized from Stripe type — no LLM needed
            "ai_confidence": 0.95,    # high confidence because Stripe data is structured
            "raw_text": f"Stripe {stripe_type}: {description}",
            "uncertain": False,
        })

    return transactions
```

---

## Store helpers (both backends)

```python
# ── supabase_store.py ─────────────────────────────────────────────────────

def upsert_stripe_connection(user_id: str, data: dict) -> dict:
    data["user_id"] = user_id
    data["updated_at"] = "now()"
    return sb().table("stripe_connections").upsert(
        data, on_conflict="user_id"
    ).execute().data[0]

def get_stripe_connection(user_id: str) -> dict | None:
    result = sb().table("stripe_connections").select("*").eq(
        "user_id", user_id
    ).eq("connected", True).execute().data
    return result[0] if result else None

def update_stripe_connection(user_id: str, updates: dict) -> dict:
    updates["updated_at"] = "now()"
    return sb().table("stripe_connections").update(updates).eq(
        "user_id", user_id
    ).execute().data[0]

def delete_stripe_connection(user_id: str):
    sb().table("stripe_connections").delete().eq("user_id", user_id).execute()


# ── memory_store.py ───────────────────────────────────────────────────────

_stripe_connections: dict[str, dict] = {}

def upsert_stripe_connection(user_id: str, data: dict) -> dict:
    data["user_id"] = user_id
    _stripe_connections[user_id] = {**_stripe_connections.get(user_id, {}), **data}
    return _stripe_connections[user_id]

def get_stripe_connection(user_id: str) -> dict | None:
    conn = _stripe_connections.get(user_id)
    return conn if conn and conn.get("connected") else None

def update_stripe_connection(user_id: str, updates: dict) -> dict:
    if user_id in _stripe_connections:
        _stripe_connections[user_id].update(updates)
    return _stripe_connections.get(user_id, {})

def delete_stripe_connection(user_id: str):
    _stripe_connections.pop(user_id, None)
```

---

## How synced transactions enter the bookkeeper

Stripe transactions come **pre-categorized** — charges are `client_payment`,
refunds are `refund_given`, fees are `bank_fees`. No LLM call needed for
categorization. Confidence is 0.95 (not 1.0 because the description might
be vague).

The sync returns transactions in the same format as CSV/PDF upload:
```json
{
  "transactions": [...],
  "source": "stripe_connect",
  "synced_count": 47
}
```

The frontend shows these in the same review table. The user approves and
they're saved to the `transactions` table with `source = "stripe_connect"`.

From there, the existing bookkeeper pipeline takes over:
- Playbook corrections are checked (but rarely needed — Stripe data is clean)
- Low-confidence items are flagged (rare with Stripe data)
- P&L aggregation includes Stripe transactions alongside CSV/PDF ones

---

## Frontend — Settings section

```tsx
// Add to settings page alongside Google connection

function StripeConnectSection() {
  const [status, setStatus] = useState<{
    connected: boolean; email?: string; last_sync?: string;
    last_sync_count?: number
  } | null>(null)
  const [syncing, setSyncing] = useState(false)

  useEffect(() => {
    apiGet("/stripe-connect/status").then(setStatus)
  }, [])

  async function handleConnect() {
    const { auth_url } = await apiGet<{ auth_url: string }>("/stripe-connect/connect")
    window.location.href = auth_url
  }

  async function handleSync() {
    setSyncing(true)
    try {
      const result = await apiPost("/stripe-connect/sync", {})
      if (result.transactions?.length > 0) {
        // Navigate to bookkeeping with synced transactions for review
        // Or show inline review
        alert(`Synced ${result.synced_count} transactions from Stripe`)
      } else {
        alert("No new transactions found")
      }
    } finally {
      setSyncing(false)
    }
  }

  async function handleDisconnect() {
    if (!confirm("Disconnect your Stripe account? Kora will stop syncing transactions.")) return
    await apiDelete("/stripe-connect/disconnect")
    setStatus({ connected: false })
  }

  if (!status) return <div>Loading...</div>

  return (
    <div className="rounded-lg border p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold">Stripe Account</h3>
          <p className="text-sm text-muted-foreground">
            Auto-import charges, refunds, and fees for bookkeeping
          </p>
        </div>
        {status.connected ? (
          <div className="flex items-center gap-3">
            <span className="w-2 h-2 rounded-full bg-green-500 inline-block"/>
            <span className="text-sm font-medium">{status.email}</span>
            <button onClick={handleSync} disabled={syncing}
              className="text-sm text-primary hover:underline">
              {syncing ? "Syncing..." : "Sync now"}
            </button>
            <button onClick={handleDisconnect}
              className="text-sm text-destructive hover:underline">
              Disconnect
            </button>
          </div>
        ) : (
          <button onClick={handleConnect}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground">
            Connect Stripe
          </button>
        )}
      </div>

      {!status.connected && (
        <div className="rounded-md bg-muted p-4 text-sm space-y-2">
          <p className="font-medium">What Kora will access (read-only):</p>
          <ul className="space-y-1 text-muted-foreground">
            <li>✓ Incoming payments (charges)</li>
            <li>✓ Refunds and adjustments</li>
            <li>✓ Stripe processing fees</li>
            <li>✗ Kora cannot create charges or move money</li>
          </ul>
        </div>
      )}

      {status.connected && status.last_sync && (
        <p className="text-xs text-muted-foreground">
          Last synced: {new Date(status.last_sync).toLocaleString()}
          {" · "}{status.last_sync_count} transactions
        </p>
      )}
    </div>
  )
}
```

---

## Next.js callback proxy

```typescript
// frontend/app/api/auth/stripe/callback/route.ts
import { NextRequest, NextResponse } from "next/server"

export async function GET(request: NextRequest) {
  const queryString = request.nextUrl.searchParams.toString()
  const apiUrl = `${process.env.NEXT_PUBLIC_API_URL}/stripe-connect/callback?${queryString}`
  const response = await fetch(apiUrl, { redirect: "manual" })
  const location = response.headers.get("location")
  if (location) return NextResponse.redirect(location)
  return NextResponse.json({ error: "callback_failed" }, { status: 500 })
}
```

---

## Register the router

```python
# In app/main.py:
from app.routers.stripe_connect import router as stripe_connect_router
app.include_router(stripe_connect_router, prefix="/api")
```

---

## What this does NOT change

- CSV upload: completely untouched (separate route, separate handler)
- PDF bank statement upload: completely untouched (separate route, separate handler)
- The `transactions` table schema: unchanged (Stripe transactions use `source = "stripe_connect"`)
- The bookkeeper categorization: unchanged (Stripe transactions arrive pre-categorized)
- The cashflow forecast: automatically includes Stripe transactions (they're in the same table)
- Kora's own billing (05-stripe billing skill): completely separate router, separate purpose
