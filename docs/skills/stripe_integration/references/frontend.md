# Stripe — Frontend Reference

---

## Pricing page (`/pricing`)

```tsx
// app/(dashboard)/pricing/page.tsx
// Accessible to all users. Shows current plan and upgrade/downgrade options.

"use client"
import { useState, useEffect } from "react"
import { apiGet, apiPost } from "@/lib/api/client"

interface BillingStatus {
  plan: string
  subscription: { status: string } | null
}

const PLANS = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    period: "forever",
    features: ["20 transactions/month", "1 contract/month", "Manual invoicing"],
    priceId: null,
  },
  {
    id: "starter",
    name: "Starter",
    price: "$29",
    period: "/month",
    features: [
      "Unlimited transactions",
      "Invoice follow-up agent",
      "Proactive AI alerts",
      "Morning briefing",
      "Quick capture",
    ],
    priceId: process.env.NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID,
    popular: true,
  },
  {
    id: "pro",
    name: "Pro",
    price: "$49",
    period: "/month",
    features: [
      "Everything in Starter",
      "Contract generator",
      "Proposal generator",
      "Cash flow forecast",
      "Full Butler + Google intel",
      "Retainer tracking",
    ],
    priceId: process.env.NEXT_PUBLIC_STRIPE_PRO_PRICE_ID,
  },
]

export default function PricingPage() {
  const [loading, setLoading] = useState<string | null>(null)
  const [currentPlan, setCurrentPlan] = useState<string>("free")

  useEffect(() => {
    // Fetch user's current plan
    apiGet<BillingStatus>("/stripe/billing")
      .then(data => setCurrentPlan(data.plan || "free"))
      .catch(() => {})
  }, [])

  async function handleSubscribe(priceId: string) {
    setLoading(priceId)
    try {
      const { checkout_url } = await apiPost<{ checkout_url: string }>(
        "/stripe/checkout",
        { priceId }
      )
      window.location.href = checkout_url
    } catch (err) {
      alert("Failed to start checkout. Please try again.")
      setLoading(null)
    }
  }

  async function handleUpgrade(priceId: string) {
    setLoading(priceId)
    try {
      const result = await apiPost<{ plan: string }>(
        "/stripe/upgrade",
        { newPriceId: priceId }
      )
      setCurrentPlan(result.plan)
      setLoading(null)
    } catch (err) {
      alert("Failed to change plan. Please try again.")
      setLoading(null)
    }
  }

  function getButtonState(plan: typeof PLANS[0]) {
    if (plan.id === currentPlan) {
      return { label: "Current plan", action: null, disabled: true, variant: "outline" }
    }
    if (plan.id === "free") {
      return { label: "Downgrade to Free", action: null, disabled: true, variant: "outline" }
      // Downgrade to free = cancel subscription (done from /settings/billing)
    }
    if (currentPlan === "free") {
      // Free → paid = new checkout
      return {
        label: `Subscribe to ${plan.name}`,
        action: () => handleSubscribe(plan.priceId!),
        disabled: false,
        variant: "primary",
      }
    }
    // Paid → different paid = upgrade/downgrade
    const isUpgrade = PLANS.findIndex(p => p.id === plan.id) >
                      PLANS.findIndex(p => p.id === currentPlan)
    return {
      label: isUpgrade ? `Upgrade to ${plan.name}` : `Switch to ${plan.name}`,
      action: () => handleUpgrade(plan.priceId!),
      disabled: false,
      variant: isUpgrade ? "primary" : "outline",
    }
  }

  return (
    <div className="max-w-4xl mx-auto py-8">
      <h1 className="text-2xl font-medium text-center mb-2">Choose your plan</h1>
      <p className="text-center text-muted-foreground mb-8">
        Start free. Upgrade when you're ready.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {PLANS.map(plan => {
          const btn = getButtonState(plan)
          const isCurrent = plan.id === currentPlan
          return (
            <div
              key={plan.name}
              className={`rounded-lg border p-6 ${
                isCurrent ? "border-primary ring-1 ring-primary" : ""
              } ${plan.popular && !isCurrent ? "border-primary/50" : ""}`}
            >
              {isCurrent && (
                <span className="text-xs font-medium text-primary mb-2 block">
                  Your current plan
                </span>
              )}
              {plan.popular && !isCurrent && (
                <span className="text-xs font-medium text-muted-foreground mb-2 block">
                  Most popular
                </span>
              )}
              <h3 className="text-lg font-medium">{plan.name}</h3>
              <div className="mt-2 mb-4">
                <span className="text-3xl font-medium">{plan.price}</span>
                <span className="text-muted-foreground">{plan.period}</span>
              </div>
              <ul className="space-y-2 mb-6">
                {plan.features.map(f => (
                  <li key={f} className="text-sm flex gap-2">
                    <span className="text-green-500">✓</span> {f}
                  </li>
                ))}
              </ul>
              <button
                onClick={btn.action || undefined}
                disabled={btn.disabled || loading === plan.priceId}
                className={`w-full rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 ${
                  btn.variant === "primary"
                    ? "bg-primary text-primary-foreground"
                    : "border text-muted-foreground"
                }`}
              >
                {loading === plan.priceId ? "Processing..." : btn.label}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

---

## Billing settings (`/settings/billing`)

```tsx
// app/(dashboard)/settings/billing/page.tsx

"use client"
import { useState, useEffect } from "react"
import { apiGet, apiPost } from "@/lib/api/client"

interface BillingInfo {
  plan: string
  subscription: {
    id: string
    status: string
    current_period_end: number
    cancel_at_period_end: boolean
    plan_amount: number
  } | null
}

export default function BillingSettingsPage() {
  const [billing, setBilling] = useState<BillingInfo | null>(null)
  const [cancelling, setCancelling] = useState(false)

  useEffect(() => {
    apiGet<BillingInfo>("/stripe/billing").then(setBilling)

    // Handle success redirect from checkout
    const params = new URLSearchParams(window.location.search)
    if (params.get("success") === "true") {
      // Refresh billing info after a short delay (webhook may still be processing)
      setTimeout(() => apiGet<BillingInfo>("/stripe/billing").then(setBilling), 2000)
    }
  }, [])

  async function handleCancel() {
    if (!confirm("Cancel your subscription? You'll keep access until the end of the current billing period.")) return
    setCancelling(true)
    await apiPost("/stripe/cancel", {})
    setBilling(prev => prev ? {
      ...prev,
      subscription: prev.subscription
        ? { ...prev.subscription, cancel_at_period_end: true }
        : null
    } : null)
    setCancelling(false)
  }

  async function handleReactivate() {
    await apiPost("/stripe/reactivate", {})
    apiGet<BillingInfo>("/stripe/billing").then(setBilling)
  }

  async function openCustomerPortal() {
    try {
      const { portal_url } = await apiPost<{ portal_url: string }>("/stripe/portal", {})
      window.location.href = portal_url
    } catch {
      alert("Could not open billing portal. Please try again.")
    }
  }

  if (!billing) return <div>Loading...</div>

  return (
    <div className="max-w-2xl space-y-6">
      <h2 className="text-xl font-medium">Billing</h2>

      <div className="rounded-lg border p-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">Current plan</p>
            <p className="text-lg font-medium capitalize">{billing.plan}</p>
          </div>
          {billing.plan === "free" && (
            <a
              href="/pricing"
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            >
              Upgrade
            </a>
          )}
          {billing.plan === "starter" && (
            <a
              href="/pricing"
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            >
              Upgrade to Pro
            </a>
          )}
        </div>

        {billing.subscription && (
          <div className="mt-4 pt-4 border-t space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Status</span>
              <span className={
                billing.subscription.status === "active" ? "text-green-600" : "text-amber-600"
              }>
                {billing.subscription.status}
                {billing.subscription.cancel_at_period_end && " (cancelling)"}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Amount</span>
              <span>${billing.subscription.plan_amount}/month</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Current period ends</span>
              <span>{new Date(billing.subscription.current_period_end * 1000).toLocaleDateString()}</span>
            </div>

            {billing.subscription.cancel_at_period_end ? (
              <button
                onClick={handleReactivate}
                className="text-sm text-primary hover:underline"
              >
                Reactivate subscription
              </button>
            ) : (
              <div className="flex gap-4 items-center pt-1">
                <button
                  onClick={openCustomerPortal}
                  className="text-sm text-primary hover:underline"
                >
                  Manage payment method
                </button>
                <button
                  onClick={handleCancel}
                  disabled={cancelling}
                  className="text-sm text-destructive hover:underline"
                >
                  {cancelling ? "Cancelling..." : "Cancel subscription"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
```

---

## Frontend environment variables

Add to `frontend/.env.local`:
```
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxx
NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID=price_xxxxxxxxxxxx
NEXT_PUBLIC_STRIPE_PRO_PRICE_ID=price_xxxxxxxxxxxx
```

---

## Upgrade prompts (show in-app when user hits plan limits)

When a Free user tries to access a paid feature and gets a 403:

```tsx
// components/UpgradePrompt.tsx
function UpgradePrompt({ feature, requiredPlan }: { feature: string; requiredPlan: string }) {
  return (
    <div className="rounded-lg border border-primary/20 bg-primary/5 p-6 text-center">
      <h3 className="text-lg font-medium mb-2">Upgrade to unlock {feature}</h3>
      <p className="text-sm text-muted-foreground mb-4">
        This feature requires the {requiredPlan} plan.
      </p>
      <a
        href="/pricing"
        className="inline-block rounded-lg bg-primary px-6 py-2 text-sm
                   font-medium text-primary-foreground"
      >
        View plans
      </a>
    </div>
  )
}
```
