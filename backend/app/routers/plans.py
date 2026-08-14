"""Publishes the plan comparison the pricing page renders.

The page used to hold its own copy of the tiers. That copy drifted from the
entitlement table and ended up advertising a cash-flow forecast as Pro when
Starter unlocks it, and selling several capabilities that nothing gates at all.
Serving the comparison from the same module that enforces access means the two
cannot disagree — and the Stripe price ids come from backend settings rather
than being inlined into the bundle at build time, so rotating a price no longer
needs a frontend rebuild.

Unauthenticated on purpose: what a plan costs is public information, and the
page must render before it knows who is looking.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..config import settings
from ..entitlements import plans_payload

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.get("")
async def list_plans() -> dict:
    return {
        "plans": plans_payload(
            {
                "starter": settings.STRIPE_STARTER_PRICE_ID,
                "pro": settings.STRIPE_PRO_PRICE_ID,
            }
        )
    }
