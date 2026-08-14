"""The frontend's API URL is frozen at build time, so it must be the stable one.

Next inlines ``NEXT_PUBLIC_*`` into the bundle during ``npm run build``. That
makes the value the deploy script passes as ``NEXT_PUBLIC_API_URL`` permanent for
the life of that image — and the image built during a canary deploy is the exact
image ``prod-promote`` later routes 100% of traffic to.

``prod-canary`` used to bake the canary-*tagged* revision URL, reasoning that
canary frontend traffic should hit canary backend traffic. Correct about intent,
wrong about lifetime: promoting shipped a production frontend hard-wired to a
tagged revision, so every CI run re-pointed the live site at whatever that tag
meant that day. It had to be untangled by hand after three separate deploys.

Nothing is lost by using the stable URL. The backend service is itself split
``canary=N``, so that share of requests to the stable URL are already served by
the canary revision — the canary code gets real traffic through the split built
for it, not through a hostname frozen into a bundle.
"""

from __future__ import annotations

import pathlib
import re

import pytest


DEPLOY_SH = pathlib.Path(__file__).resolve().parents[2] / "ops" / "deploy.sh"

pytestmark = pytest.mark.skipif(not DEPLOY_SH.exists(), reason="ops/deploy.sh not in this checkout")


def _source() -> str:
    return DEPLOY_SH.read_text(encoding="utf-8")


def test_the_frontend_never_builds_against_a_canary_url():
    """The regression, stated directly."""
    src = _source()
    offenders = [line.strip() for line in src.splitlines() if re.search(r"backend_url\s+canary", line) and not line.lstrip().startswith("#")]
    assert not offenders, f"prod-canary would bake a tagged revision URL into the frontend image: {offenders}"


def test_backend_url_resolves_the_stable_service_url():
    src = _source()
    body = src.split("backend_url() {", 1)[1].split("\n}", 1)[0]
    assert "status.url" in body, "backend_url should read the service's stable URL"
    assert "select(.tag==" not in body, "backend_url should not resolve a tagged revision"


def test_the_canary_split_is_still_what_exercises_the_new_revision():
    """Using the stable URL is only safe because the split still exists."""
    src = _source()
    assert '--to-tags="canary=${CANARY_PERCENT}"' in src
