"""Configuration for the standalone analytics service.

Deliberately independent of the main backend's settings module. This service
ships as its own container so it can be deployed, restarted or taken down
without touching the product — sharing a config object would have quietly
reintroduced the coupling the separation exists to avoid.
"""

from __future__ import annotations

import os


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    raw = os.getenv(name, default) or ""
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


# Read-only credentials for the product's database. The service role key is
# required because this reads ACROSS tenants, which is exactly what row-level
# security forbids for an ordinary key — and exactly why this service must never
# accept user input that reaches a query.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Accounts that are the team's own, not evidence of outside interest. Counting
# them in the headline would inflate it with the demo tenant that holds most of
# the seeded activity, and a judge who recognises demo@kora.app would reasonably
# discount everything else on the page. They are reported, separately and
# labelled, so the totals still reconcile against the raw database.
TEST_ACCOUNTS = _csv(
    "ANALYTICS_TEST_ACCOUNTS",
    "demo@kora.app,tester@kora.app,uat-tenant-b@kora.app,pandasivananda0@gmail.com",
)

# Whether to publish full email addresses.
#
# OFF by default, and the default is the point: this service runs without
# authentication, so anything it renders is readable by anyone who has the URL.
# The people in this table signed up to help test a product, not to have their
# personal address published on the open internet. Masking keeps every number,
# every timeline and every per-person row intact — an identifier is not a
# statistic — while leaving the addresses unreadable to a passer-by.
#
# Set ANALYTICS_SHOW_EMAILS=true to publish them in full. It takes one env var,
# and it is a deliberate act rather than an accident of the default.
SHOW_EMAILS = _flag("ANALYTICS_SHOW_EMAILS", False)

# Seconds to reuse a computed snapshot. A demo means refreshing the page in
# front of people; without this each refresh re-reads every table.
CACHE_TTL_SECONDS = int(os.getenv("ANALYTICS_CACHE_TTL", "60"))

PRODUCT_URL = os.getenv("ANALYTICS_PRODUCT_URL", "")
