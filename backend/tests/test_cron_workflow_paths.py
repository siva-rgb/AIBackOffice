"""Every path the scheduler calls must be a route this app actually serves.

The invoice follow-up job asked for ``/api/invoices/run-follow-ups``. The route
is ``/api/invoices/follow-up``. Nothing connected the two, so the job returned
405 on every scheduled run from the day it was written — and because the job
only echoed a status code, the log said ``HTTP 405`` and nothing else. A URL in
a YAML file is the one kind of caller the type checker and the test suite never
see, which is exactly why it needs pinning here.

This reads the workflow rather than a list copied out of it. A copy would have
agreed with itself while disagreeing with the app, which is the failure being
prevented.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from app.main import app


WORKFLOW = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "cron.yml"
CALLER = pathlib.Path(__file__).resolve().parents[2] / ".github" / "scripts" / "cron-call.sh"


def _workflow_paths() -> dict[str, str]:
    """{job name: the /api path it POSTs to}, read straight from the workflow."""
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for job, body in spec["jobs"].items():
        for step in body["steps"]:
            match = re.search(r"cron-call\.sh\s+(/\S+)", step.get("run", ""))
            if match:
                found[job] = match.group(1)
    return found


def _post_routes() -> set[str]:
    return {r.path for r in app.routes if "POST" in getattr(r, "methods", set())}


@pytest.mark.skipif(not WORKFLOW.exists(), reason="workflow not present in this checkout")
class TestScheduledPathsResolve:
    def test_the_workflow_still_defines_every_job(self):
        """A job silently dropped from the workflow is a agent that stops running."""
        assert set(_workflow_paths()) == {
            "supervisor",
            "butler",
            "invoices",
            "gmail",
            "drive",
            "graph",
            "memory",
            "notion",
            "client_views",
        }

    @pytest.mark.parametrize("job,path", sorted(_workflow_paths().items()))
    def test_each_scheduled_path_is_a_real_post_route(self, job, path):
        routes = _post_routes()
        assert path in routes, f"cron job '{job}' POSTs {path}, which this app does not serve"

    def test_the_invoice_job_uses_the_route_that_exists(self):
        """The specific regression: /run-follow-ups was never a route."""
        assert _workflow_paths()["invoices"] == "/api/invoices/follow-up"


@pytest.mark.skipif(not CALLER.exists(), reason="caller script not present in this checkout")
class TestTheCallerItself:
    def test_it_sends_a_request_body(self):
        """Cloud Run answers 411 Length Required to a POST with no body, before
        the request ever reaches this app. The body is load-bearing."""
        assert "-d '{}'" in CALLER.read_text(encoding="utf-8")

    def test_it_refuses_to_run_with_an_unset_url(self):
        """An empty KORA_API_URL previously produced a bare '/api/...' and a
        curl exit code, with nothing naming the missing secret."""
        src = CALLER.read_text(encoding="utf-8")
        assert "KORA_API_URL" in src and "Missing repository secret" in src

    def test_it_prints_the_response_body_on_failure(self):
        """A status code alone sent us to the server logs to find the reason."""
        src = CALLER.read_text(encoding="utf-8")
        assert "response body" in src
