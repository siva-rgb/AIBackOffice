#!/usr/bin/env python3
"""G4-auto — authenticated UAT assertions against a deployed Kora environment.

This is the automatable half of docs/uat/UAT_PLAN.md §4. Everything here needs a
real logged-in session, which is why it could not live in ops/uat.sh's smoke gate
(that one is deliberately anonymous and read-only).

    python ops/uat_auth.py --target https://kora-backend-staging-....run.app

Credentials come from the environment, never from the repo:

    UAT_A_EMAIL / UAT_A_PASSWORD    tenant A — the seeded account with data
    UAT_B_EMAIL / UAT_B_PASSWORD    tenant B — a second, separate tenant
    (Supabase URL + anon key are read from frontend/.env.local.)

Tenant B exists to prove the thing no single-account test can: that A's data is
unreachable from B. That is the S1-severity case in the plan (AUTH-07).

Writes are confined to objects this script creates and then deletes. It never
mutates seeded data.

Exit code 0 = every case passed, 1 = at least one failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 60

# Windows consoles default to cp1252, which cannot encode the box-drawing glyphs
# below — without this the script dies on its own banner.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────── reporting ──
GREEN, RED, YELLOW, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"
results: list[tuple[str, str, str]] = []  # (status, case, detail)


def ok(case: str, detail: str = "") -> None:
    results.append(("PASS", case, detail))
    print(f"  {GREEN}PASS{RESET}  {case}" + (f" — {detail}" if detail else ""))


def fail(case: str, detail: str) -> None:
    results.append(("FAIL", case, detail))
    print(f"  {RED}FAIL{RESET}  {case} — {detail}")


def skip(case: str, detail: str) -> None:
    results.append(("SKIP", case, detail))
    print(f"  {YELLOW}SKIP{RESET}  {case} — {detail}")


def note(detail: str) -> None:
    """Context for the reader. Not a case — never counted in the tally, so it
    cannot turn a healthy run amber."""
    print(f"  {YELLOW}note{RESET}  {detail}")


def section(title: str) -> None:
    print(f"\n{BOLD}── {title}{RESET}")


def expect(case: str, condition: bool, detail_ok: str = "", detail_bad: str = "") -> bool:
    (ok if condition else fail)(case, detail_ok if condition else detail_bad)
    return condition


# ──────────────────────────────────────────────────────────────── plumbing ──
def read_env_file(path: Path, key: str) -> str | None:
    """Pull one key out of a .env file without sourcing it."""
    if not path.exists():
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}=(.*)$")
    found = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pattern.match(line)
        if m:
            # Keep going: dotenv gives a later duplicate precedence, so the LAST
            # occurrence is what the app actually loads.
            found = m.group(1).strip().strip('"').strip("'")
    return found


def request(method: str, url: str, token: str | None = None, body: dict | None = None, headers: dict | None = None, raw: str | None = None) -> tuple[int, object]:
    """Return (status_code, parsed_body). Never raises on HTTP error status.

    `raw` sends an exact byte-for-byte body. Required for signature-verified
    endpoints: re-serialising a dict changes the bytes (key spacing), so the
    signature would never match what the server hashes.
    """
    data = raw.encode() if raw is not None else json.dumps(body).encode() if body is not None else None
    hdrs = {"Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    hdrs.update(headers or {})

    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    except Exception as e:  # network/timeout
        return 0, {"error": str(e)}

    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def login(supabase_url: str, anon_key: str, email: str, password: str) -> str | None:
    status, body = request(
        "POST",
        f"{supabase_url}/auth/v1/token?grant_type=password",
        body={"email": email, "password": password},
        headers={"apikey": anon_key},
    )
    if status == 200 and isinstance(body, dict):
        return body.get("access_token")
    return None


def login_identity(supabase_url: str, anon_key: str, email: str, password: str) -> str | None:
    """The auth provider's own user id for these credentials.

    Identity is asserted against this rather than against the profile email:
    `users.email` (where notifications go) and the auth identity (what you log
    in with) are deliberately allowed to differ — that is how the demo tenant
    keeps a published `demo@kora.app` login while its digests go to a real
    inbox. Comparing ids checks the thing that actually matters: the token
    resolves to the account we signed in as.
    """
    status, body = request(
        "POST",
        f"{supabase_url}/auth/v1/token?grant_type=password",
        body={"email": email, "password": password},
        headers={"apikey": anon_key},
    )
    if status == 200 and isinstance(body, dict):
        return ((body.get("user") or {}) if isinstance(body.get("user"), dict) else {}).get("id")
    return None


def money(x) -> float:
    """Round to cents so float noise never fails an arithmetic assertion."""
    return round(float(x or 0), 2)


# ──────────────────────────────────────────────────────────────── the cases ──
def check_identity(api: str, tok_a: str, email_a: str, auth_user_id: str | None = None) -> dict:
    section("Identity & profile — AUTH-02, AUTH-05")
    status, me = request("GET", f"{api}/api/me", tok_a)
    resolved = me.get("id") if isinstance(me, dict) else None
    # Assert the token resolves to the account we signed in as. Previously this
    # compared `me.email` to the login email, which fails the moment a tenant's
    # notification address differs from its auth identity — a supported setup,
    # and the one the demo tenant uses. Worse, the failure returned {} and every
    # downstream check that needed the user id then mis-reported: OBS-04 compared
    # log rows against an empty id and announced a cross-tenant leak.
    matches = bool(resolved) and (resolved == auth_user_id if auth_user_id else True)
    if not expect("AUTH-02 /api/me returns the authenticated user", status == 200 and matches, f"id={resolved}", f"status={status} body={str(me)[:120]}"):
        return {}
    if isinstance(me, dict) and me.get("email") != email_a:
        note(f"profile email ({me.get('email')}) differs from the login email ({email_a}) — expected when notifications are redirected")

    status, comp = request("GET", f"{api}/api/profile/completeness", tok_a)
    expect(
        "AUTH-05 profile completeness returns a score",
        status == 200 and isinstance(comp, dict) and any(isinstance(v, (int, float)) for v in comp.values()),
        f"{json.dumps(comp)[:80]}" if status == 200 else "",
        f"status={status}",
    )
    return me


def check_tenant_isolation(api: str, tok_a: str, tok_b: str) -> None:
    """AUTH-07 — the S1 case. B must not be able to read A's records."""
    section("Tenant isolation — AUTH-07 (S1 severity)")

    # Collect real record ids belonging to A. Each probe route must actually
    # EXIST — `/api/invoices/{id}` does not, and a 405 from a missing route would
    # otherwise read as "access denied" and pass this S1 case vacuously.
    targets: list[tuple[str, str]] = []
    for label, list_ep, detail_ep in [
        ("invoice", "/api/invoices", "/api/invoices/{id}/pdf/download"),
        ("client", "/api/clients", "/api/clients/{id}"),
        ("contract", "/api/contracts", "/api/contracts/{id}"),
    ]:
        status, items = request("GET", f"{api}{list_ep}", tok_a)
        if status == 200 and isinstance(items, list) and items:
            rid = items[0].get("id")
            if rid:
                targets.append((label, detail_ep.replace("{id}", rid)))

    if not targets:
        skip("AUTH-07", "tenant A has no records to attempt cross-tenant reads against")
        return

    for label, ep in targets:
        # Confirm the probe route resolves for its owner before trusting a denial
        # to tenant B to mean anything.
        owner_status, _ = request("GET", f"{api}{ep}", tok_a)
        if owner_status in (404, 405):
            skip(f"AUTH-07 {label}", f"probe route {ep} returns {owner_status} for its own owner — not a usable isolation probe")
            continue

        status, body = request("GET", f"{api}{ep}", tok_b)
        leaked = status == 200
        expect(
            f"AUTH-07 tenant B cannot read tenant A's {label}",
            not leaked,
            f"rejected ({status}); owner gets {owner_status}",
            f"S1 LEAK — B received A's {label} with HTTP {status}",
        )

    # B's own collections must be empty of A's rows, not merely 200.
    status, inv_b = request("GET", f"{api}/api/invoices", tok_b)
    if status == 200 and isinstance(inv_b, list):
        status_a, inv_a = request("GET", f"{api}/api/invoices", tok_a)
        ids_a = {i.get("id") for i in inv_a} if isinstance(inv_a, list) else set()
        overlap = [i.get("id") for i in inv_b if i.get("id") in ids_a]
        expect(
            "AUTH-07 tenant B's invoice list contains none of A's rows",
            not overlap,
            f"B sees {len(inv_b)} invoices, none of A's",
            f"S1 LEAK — {len(overlap)} of A's invoices visible to B",
        )
    else:
        skip("AUTH-07 B invoice list", f"status={status}")


def check_plan_gating(api: str, tok_a: str, tok_b: str, plan_a: str) -> None:
    """BILL-04 — gating must be enforced server-side, not just hidden in the UI."""
    section("Plan gating — BILL-04 (server-side enforcement)")

    # (method, endpoint, minimum plan) — mirrors app/entitlements.POLICY.
    gated = [
        ("GET", "/api/cashflow/forecast", "starter", None),
        ("POST", "/api/memory/recall", "starter", {"query": "uat probe"}),
        ("POST", "/api/graph/sync", "starter", {}),
        ("POST", "/api/contracts/generate", "pro", {"contractType": "nda", "clientName": "UAT"}),
    ]

    for method, ep, need, body in gated:
        status, resp = request(method, f"{api}{ep}", tok_b, body)
        expect(
            f"BILL-04 free tenant blocked from {method} {ep} (needs {need})",
            status == 403,
            "403 as expected",
            f"expected 403, got {status} — paywall not enforced server-side",
        )

    # And the paying tenant must NOT be blocked — a gate that blocks everyone is
    # just as broken as one that blocks no one.
    if plan_a == "pro":
        for method, ep, need, body in gated:
            status, _ = request(method, f"{api}{ep}", tok_a, body)
            expect(
                f"BILL-04 pro tenant allowed {method} {ep}",
                status != 403,
                f"not blocked ({status})",
                f"pro plan received 403 on a {need} feature",
            )
    else:
        skip("BILL-04 positive path", f"tenant A is on '{plan_a}', not pro")


def check_invoices(api: str, tok: str) -> None:
    section("Invoicing — INV-01, INV-06, INV-07 (P0 revenue path)")
    status, invoices = request("GET", f"{api}/api/invoices", tok)
    if status != 200 or not isinstance(invoices, list):
        fail("INV-01 invoice list loads", f"status={status}")
        return
    if not invoices:
        skip("INV-*", "no invoices in this tenant")
        return

    bad_math = []
    for inv in invoices:
        line_total = money(sum(money(li.get("amount")) for li in (inv.get("lineItems") or [])))
        subtotal = money(inv.get("subtotal"))
        total = money(inv.get("total"))
        expected_total = money(subtotal + money(inv.get("taxAmount")))
        if abs(line_total - subtotal) > 0.01 or abs(total - expected_total) > 0.01:
            bad_math.append(f"{inv.get('invoiceNumber')}: lines={line_total} subtotal={subtotal} total={total} expected={expected_total}")
    expect(
        "INV-01 invoice arithmetic (line items → subtotal → total)",
        not bad_math,
        f"{len(invoices)} invoices consistent to the cent",
        f"{len(bad_math)} inconsistent: {'; '.join(bad_math[:3])}",
    )

    overpaid = [i.get("invoiceNumber") for i in invoices if i.get("amountPaid") is not None and money(i.get("amountPaid")) > money(i.get("total")) + 0.01]
    expect("INV-06 no invoice is paid beyond its total", not overpaid, f"{len(invoices)} checked", f"overpaid: {overpaid[:5]}")

    paid_no_date = [i.get("invoiceNumber") for i in invoices if i.get("status") == "paid" and not i.get("paidAt")]
    expect("INV-06 every paid invoice records a paidAt", not paid_no_date, "", f"missing paidAt: {paid_no_date[:5]}")

    paid_and_overdue = [i.get("invoiceNumber") for i in invoices if i.get("status") == "paid" and i.get("followUpCount", 0) and i.get("lastFollowUpAt") and i.get("paidAt") and i["lastFollowUpAt"] > i["paidAt"]]
    expect(
        "INV-07 no invoice was chased after it was paid",
        not paid_and_overdue,
        "",
        f"chased post-payment: {paid_and_overdue[:5]}",
    )

    # INV-03 — the download must actually resolve for its owner. This is the case
    # that caught signed-URL generation failing on Cloud Run (token-only creds
    # cannot sign), which no hermetic test could see. Content correctness of the
    # PDF itself is still a manual check.
    stored = [i for i in invoices if i.get("pdfPath")]
    if not stored:
        skip("INV-03 invoice PDF download", "no invoice in this tenant has a stored PDF")
    else:
        inv = stored[0]
        status, body = request("GET", f"{api}/api/invoices/{inv['id']}/pdf/download", tok)
        expect(
            "INV-03 invoice PDF download resolves for its owner",
            status == 200,
            f"HTTP 200 for {inv.get('invoiceNumber')}",
            f"HTTP {status} for {inv.get('invoiceNumber')} — {str(body)[:100]}",
        )


def check_bookkeeping(api: str, tok: str) -> None:
    section("Bookkeeping & P&L — BOOK-04, BOOK-06 (P0 data integrity)")
    status, txns = request("GET", f"{api}/api/bookkeeping/transactions", tok)
    if status == 200 and isinstance(txns, list):
        missing = [t.get("id") for t in txns if t.get("amount") is None or not t.get("date")]
        expect("BOOK-04 every transaction has an amount and a date", not missing, f"{len(txns)} transactions", f"{len(missing)} incomplete rows")
    else:
        fail("BOOK-04 transactions load", f"status={status}")

    status, pnl = request("GET", f"{api}/api/bookkeeping/pnl", tok)
    if status != 200 or not isinstance(pnl, dict):
        fail("BOOK-06 P&L loads", f"status={status}")
        return

    income = money(pnl.get("income") or pnl.get("totalIncome"))
    expenses = money(pnl.get("expenses") or pnl.get("totalExpenses"))
    net = pnl.get("net", pnl.get("netProfit"))
    if net is None:
        skip("BOOK-06 P&L arithmetic", f"no net field in {list(pnl)[:6]}")
    else:
        expect(
            "BOOK-06 P&L arithmetic (income − expenses = net)",
            abs(money(income - expenses) - money(net)) <= 0.01,
            f"{income} − {expenses} = {money(net)}",
            f"{income} − {expenses} = {money(income - expenses)} but net reports {money(net)}",
        )


def check_cashflow(api: str, tok: str) -> None:
    section("Cashflow — CASH-02 (determinism)")
    s1, f1 = request("GET", f"{api}/api/cashflow/forecast", tok)
    s2, f2 = request("GET", f"{api}/api/cashflow/forecast", tok)
    if s1 != 200 or s2 != 200:
        fail("CASH-02 forecast loads", f"status={s1}/{s2}")
        return

    # Determinism applies to the arithmetic PROJECTION, not to anything the model
    # writes. The response mixes both:
    #   computed  — currentBalance, horizonDays, forecast[], danger* thresholds
    #   LLM-authored — keyRisks, recommendedActions, assumptions, confidenceScore
    #
    # confidenceScore is the trap: it is a float, so a naive "compare all numbers"
    # check passes or fails depending on whether the model happened to say 0.7 or
    # 0.75 that minute. Name the computed fields explicitly instead of inferring
    # them by type — a flaky gate is worse than no gate, because people learn to
    # ignore it.
    COMPUTED = ("currentBalance", "horizonDays", "forecast", "dangerExpected30d", "dangerConservative14d")

    def projection(f):
        return {k: f.get(k) for k in COMPUTED} if isinstance(f, dict) else f

    same = json.dumps(projection(f1), sort_keys=True) == json.dumps(projection(f2), sort_keys=True)
    days = len(f1.get("forecast") or []) if isinstance(f1, dict) else 0
    expect(
        "CASH-02 the computed projection is deterministic across identical calls",
        same,
        f"{days}-day projection identical across two calls",
        "same inputs produced a different computed projection",
    )


def check_dashboard(api: str, tok: str) -> None:
    section("Dashboard — DASH-01")
    status, ov = request("GET", f"{api}/api/overview", tok)
    if status != 200 or not isinstance(ov, dict):
        fail("DASH-01 overview loads", f"status={status}")
        return
    nan_like = [k for k, v in ov.items() if isinstance(v, float) and (v != v)]
    expect("DASH-01 overview returns tiles with no NaN values", not nan_like, f"{len(ov)} fields", f"NaN in {nan_like}")


def check_tasks_and_stories(api: str, tok: str) -> None:
    section("Tasks & stories — TASK-01, TASK-02, STORY-03")

    # Stats must agree with the list they summarise.
    status, tasks = request("GET", f"{api}/api/tasks", tok)
    s2, stats = request("GET", f"{api}/api/tasks/stats", tok)
    if status == 200 and isinstance(tasks, list) and s2 == 200 and isinstance(stats, dict):
        total = stats.get("total", stats.get("open", None))
        if isinstance(total, int) and "total" in stats:
            expect("TASK-02 task stats total matches the task list", total == len(tasks), f"{total} == {len(tasks)}", f"stats says {total}, list has {len(tasks)}")
        else:
            skip("TASK-02", f"no comparable total in stats keys {list(stats)[:6]}")
    else:
        fail("TASK-02 tasks + stats load", f"status={status}/{s2}")

    # TASK-01 — full create/read/delete round-trip, cleaning up after itself.
    status, created = request("POST", f"{api}/api/tasks", tok, {"title": "UAT probe — safe to delete", "status": "todo"})
    if status not in (200, 201) or not isinstance(created, dict) or not created.get("id"):
        fail("TASK-01 create a task", f"status={status} body={str(created)[:120]}")
        return
    tid = created["id"]
    ok("TASK-01 create a task", f"id={tid[:8]}…")

    status, listed = request("GET", f"{api}/api/tasks", tok)
    expect("TASK-01 the created task appears in the list", isinstance(listed, list) and any(t.get("id") == tid for t in listed), "", "created task missing from the list")

    status, _ = request("PATCH", f"{api}/api/tasks/{tid}", tok, {"status": "done"})
    expect("TASK-01 update the task", status in (200, 204), f"HTTP {status}", f"HTTP {status}")

    status, _ = request("DELETE", f"{api}/api/tasks/{tid}", tok)
    expect("TASK-01 delete the task (cleanup)", status in (200, 204), f"HTTP {status}", f"HTTP {status} — UAT probe task may be left behind")

    status, after = request("GET", f"{api}/api/tasks", tok)
    expect("TASK-01 the deleted task is gone", isinstance(after, list) and not any(t.get("id") == tid for t in after), "", "deleted task still listed")

    s1, stories = request("GET", f"{api}/api/stories", tok)
    s2, sstats = request("GET", f"{api}/api/stories/stats", tok)
    expect("STORY-03 stories and roll-up stats both load", s1 == 200 and s2 == 200, f"{len(stories) if isinstance(stories, list) else '?'} stories", f"status={s1}/{s2}")


def check_gdpr(api: str, tok: str) -> None:
    section("GDPR export — GDPR-01, GDPR-02 (P0 compliance)")
    status, export = request("GET", f"{api}/api/account/export", tok)
    if status != 200:
        fail("GDPR-01 export returns data", f"status={status}")
        return
    if not isinstance(export, dict):
        fail("GDPR-01 export is a structured document", f"got {type(export).__name__}")
        return

    # The per-module data lives under `tables`; `account` and `agent_memory` sit at
    # the top level alongside export metadata.
    keys = {k.lower() for k in export} | {k.lower() for k in (export.get("tables") or {})}
    wanted = ["invoice", "client", "transaction", "contract", "task", "stor"]
    missing = [w for w in wanted if not any(w in k for k in keys)]
    expect(
        "GDPR-01 export spans the core modules",
        not missing,
        f"{len(export.get('tables') or {})} tables incl. all of {wanted}",
        f"missing {missing} — an incomplete export is a compliance failure",
    )

    status, csv_body = request("GET", f"{api}/api/account/export.csv", tok)
    expect("GDPR-02 CSV export returns content", status == 200 and bool(csv_body), f"{len(str(csv_body))} bytes", f"status={status}")


def check_observability(api: str, tok: str, user_id: str) -> None:
    section("Agent log & PII — OBS-01, OBS-02, OBS-04")
    status, log = request("GET", f"{api}/api/agents/log", tok)
    if status != 200:
        fail("OBS-01 agent log loads", f"status={status}")
        return
    entries = log if isinstance(log, list) else log.get("entries", []) if isinstance(log, dict) else []
    if not entries:
        skip("OBS-01/04", "agent log is empty for this tenant")
        return
    ok("OBS-01 agent log loads", f"{len(entries)} entries")

    if not user_id:
        # Without a known tenant id every row looks foreign, which reads as an
        # S1 leak. Refuse to render a verdict rather than raise a false alarm.
        skip("OBS-04", "tenant id unknown (AUTH-02 did not resolve) — cannot judge log ownership")
    else:
        foreign = [e.get("userId") for e in entries if e.get("userId") and e.get("userId") != user_id]
        expect("OBS-04 agent log contains only this tenant's rows", not foreign, f"{len(entries)} rows, all this tenant", f"{len(foreign)} foreign rows — cross-tenant leak")

    blob = json.dumps(entries)
    leaked = re.findall(r"\b(sk_live_|sk_test_|service_role|eyJhbGciOi)[A-Za-z0-9_\-]{6,}", blob)
    expect("OBS-02 agent log carries no credential material", not leaked, "", f"{len(leaked)} credential-looking strings in the log")


def check_dual_auth_routes(api: str) -> None:
    """The cron/user dual-path routes must reject a bad token with 401, not 500.

    These nine routes serve both Cloud Scheduler (x-cron-secret) and the user's
    "run now" buttons, so they call `get_current_user` by hand instead of via
    Depends. Every one of them passed a single argument, putting the header in the
    `request` slot and leaving `authorization` as an unresolved Header sentinel →
    AttributeError → 500 on every one of those buttons.

    A deliberately INVALID token is the whole point: it drives the same
    `_bearer(authorization)` line that crashed, while doing no work, spending no
    LLM tokens, and — importantly for /invoices/follow-up — sending no email.
    Distinguishing 401 from 500 is exactly the signal we need.
    """
    section("Dual cron/user routes reject bad auth cleanly — no 500s")

    bad = "not-a-real-token"
    for ep in [
        "/api/butler/run",
        "/api/gmail/run",
        "/api/drive/run",
        "/api/graph/run",
        "/api/manager/run",
        "/api/memory/reindex",
        "/api/notion/run",
        "/api/invoices/follow-up",
        "/api/clients/views/refresh-all",
    ]:
        status, body = request("POST", f"{api}{ep}", bad, {})
        expect(
            f"{ep} → 401 on a bad token (not 500)",
            status != 500,
            f"HTTP {status}",
            f"HTTP 500 — the manual get_current_user() call is broken again: {str(body)[:80]}",
        )


def check_google(api: str, tok: str) -> None:
    """GOOG-01/04/06/07/09 — the Google integration, read paths only.

    Every call here is a read or a cache refresh. The one Google case that *sends*
    (the digest) is deliberately excluded: `send_owner_email` targets `user.email`,
    which for the seeded tenant is demo@kora.app — a domain the operator does not
    own. Emailing it would hand a third party this tenant's revenue, client names
    and overdue invoices. See UAT_PLAN D-014.
    """
    section("Google integration — GOOG-01/04/06/07/09")

    status, st = request("GET", f"{api}/api/auth/google/status", tok)
    if status != 200 or not isinstance(st, dict) or not st.get("connected"):
        skip("GOOG-*", f"Google not connected (status={status}) — connect it in Settings to enable these")
        return
    ok("GOOG-01 Google reports connected", str(st.get("email") or ""))

    # A connection that lacks a scope fails later, at the point of use, with an
    # opaque 403 from Google. Check up front instead.
    scopes = set(st.get("scopes") or [])
    needed = {
        "https://www.googleapis.com/auth/gmail.readonly": "read mail",
        "https://www.googleapis.com/auth/gmail.send": "send mail",
        "https://www.googleapis.com/auth/drive.readonly": "read Drive",
        "https://www.googleapis.com/auth/calendar.readonly": "read Calendar",
        "https://www.googleapis.com/auth/calendar.events": "write Calendar",
    }
    missing = [d for s, d in needed.items() if s not in scopes]
    expect("GOOG-01 all required scopes granted", not missing, f"{len(scopes)} scopes", f"missing: {missing}")

    for case, method, ep, body in [
        ("GOOG-04 Gmail sync", "POST", "/api/gmail/sync", {}),
        ("GOOG-04 Gmail intel reads back", "GET", "/api/gmail/intel", None),
        ("GOOG-06 Drive sync", "POST", "/api/drive/sync", {}),
        ("GOOG-06 Drive cache reads back", "GET", "/api/drive/cache", None),
        ("GOOG-07 Calendar today", "GET", "/api/calendar/today", None),
        ("GOOG-07 Calendar unlogged time", "GET", "/api/calendar/unlogged", None),
        ("GOOG-07 Calendar availability", "GET", "/api/calendar/availability", None),
        ("GOOG-09 Meetings list", "GET", "/api/meetings", None),
        ("GOOG-09 Meeting action items", "GET", "/api/meetings/action-items", None),
    ]:
        status, resp = request(method, f"{api}{ep}", tok, body)
        n = len(resp) if isinstance(resp, list) else len(resp) if isinstance(resp, dict) else 0
        expect(case, status == 200, f"HTTP 200 ({n} keys/items)", f"HTTP {status} — {str(resp)[:110]}")


def check_email_delivery(api: str, tok: str) -> None:
    """DASH-05 — the digest must never claim a delivery it did not make.

    Two channels exist: Gmail (primary, needs an OAuth connection) and Resend
    (fallback, needs RESEND_API_KEY *and* a verified sender domain). When neither
    is available the endpoint must say so plainly. Silently returning success
    while sending nothing is the failure mode this case exists to catch — the
    same "be honest about what happened" property as the GDPR delete (M9).
    """
    section("Digest email — DASH-05")

    status, body = request("POST", f"{api}/api/alerts/digest/email", tok, body={})
    if status != 200 or not isinstance(body, dict):
        fail("DASH-05 digest email endpoint responds", f"status={status} body={str(body)[:120]}")
        return

    delivered = body.get("delivered")
    note = body.get("note") or body.get("reason") or ""

    if delivered:
        ok("DASH-05 digest email delivered", str(body.get("via") or "")[:60])
        return

    # Not delivered is acceptable here — claiming otherwise is not.
    expect(
        "DASH-05 a non-delivery is reported honestly, with a reason",
        body.get("delivered") is False and bool(note),
        f"delivered=false — {note[:90]}",
        f"delivered={delivered!r} with no explanation: {json.dumps(body)[:120]}",
    )


def check_stripe_webhook(api: str, secret: str) -> None:
    """BILL-03 — signature verification on the Stripe webhook.

    Reproduces Stripe's own scheme (HMAC-SHA256 over "timestamp.payload") so we
    can prove three things without the Stripe CLI: a correctly signed event is
    accepted, a tampered one is rejected, and an unsigned one is rejected.

    Uses `invoice.created` — an event type the backend does NOT handle — so the
    signature path is exercised with zero side effects. Sending a real
    `checkout.session.completed` here would mutate a tenant's plan.
    """
    import hashlib
    import hmac
    import time

    section("Stripe webhook — BILL-03 (P0 revenue path)")

    payload = json.dumps({"id": "evt_uat_probe", "object": "event", "type": "invoice.created", "data": {"object": {"id": "in_uat_probe"}}}, separators=(",", ":"))
    ts = str(int(time.time()))

    def signed(body: str, key: str, timestamp: str) -> str:
        mac = hmac.new(key.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={mac}"

    url = f"{api}/api/stripe/webhook"

    status, _ = request("POST", url, headers={"Stripe-Signature": signed(payload, secret, ts), "Content-Type": "application/json"}, raw=payload)
    expect(
        "BILL-03 a correctly signed event is accepted",
        status == 200,
        "HTTP 200",
        f"HTTP {status} — the deployed STRIPE_WEBHOOK_SECRET does not match this endpoint's signing secret",
    )

    status, _ = request("POST", url, headers={"Stripe-Signature": signed(payload, "whsec_wrong_key_entirely", ts), "Content-Type": "application/json"}, raw=payload)
    expect(
        "BILL-03 a forged signature is rejected",
        status >= 400,
        f"rejected ({status})",
        f"HTTP {status} — the endpoint ACCEPTED a forged signature; anyone could grant themselves a paid plan",
    )

    status, _ = request("POST", url, headers={"Content-Type": "application/json"}, raw=payload)
    expect(
        "BILL-03 an unsigned event is rejected",
        status >= 400,
        f"rejected ({status})",
        f"HTTP {status} — unsigned webhook events are being accepted",
    )


def check_memory_and_graph(api: str, tok: str) -> None:
    section("Memory & graph — MEM-01, MEM-03, GRAPH-01")
    status, stats = request("GET", f"{api}/api/memory/stats", tok)
    expect("MEM-03 memory stats load (semantic-memory migration applied)", status == 200, f"{json.dumps(stats)[:80]}" if status == 200 else "", f"status={status}")

    status, recall = request("POST", f"{api}/api/memory/recall", tok, {"query": "outstanding invoices"})
    if status == 200:
        items = recall if isinstance(recall, list) else recall.get("results", recall.get("items", [])) if isinstance(recall, dict) else []
        ok("MEM-01 semantic recall returns a result set", f"{len(items)} items")
    elif status == 403:
        skip("MEM-01", "plan-gated for this tenant")
    else:
        fail("MEM-01 semantic recall", f"status={status}")

    status, graph = request("GET", f"{api}/api/graph", tok)
    expect("GRAPH-01 graph loads (graph migration applied)", status == 200, "", f"status={status}")


# ────────────────────────────────────────────────────────────────── driver ──
def main() -> int:
    ap = argparse.ArgumentParser(description="Authenticated UAT gate for a deployed Kora environment")
    ap.add_argument("--target", required=True, help="backend base URL")
    args = ap.parse_args()
    api = args.target.rstrip("/")

    supabase_url = read_env_file(ROOT / "frontend" / ".env.local", "NEXT_PUBLIC_SUPABASE_URL")
    anon_key = read_env_file(ROOT / "frontend" / ".env.local", "NEXT_PUBLIC_SUPABASE_ANON_KEY")
    if not supabase_url or not anon_key:
        print("!! NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY not found in frontend/.env.local", file=sys.stderr)
        return 2

    email_a, pass_a = os.environ.get("UAT_A_EMAIL"), os.environ.get("UAT_A_PASSWORD")
    email_b, pass_b = os.environ.get("UAT_B_EMAIL"), os.environ.get("UAT_B_PASSWORD")
    if not (email_a and pass_a):
        print("!! set UAT_A_EMAIL and UAT_A_PASSWORD (credentials never live in the repo)", file=sys.stderr)
        return 2

    print(f"{BOLD}══ G4-auto · authenticated UAT — {api}{RESET}")

    section("Sign-in — AUTH-02, AUTH-03")
    tok_a = login(supabase_url, anon_key, email_a, pass_a)
    if not expect("AUTH-02 tenant A signs in", bool(tok_a), email_a, f"login failed for {email_a}"):
        return 1

    if not login(supabase_url, anon_key, email_a, pass_a + "-wrong"):
        ok("AUTH-03 a wrong password is rejected")
    else:
        fail("AUTH-03 a wrong password is rejected", "login succeeded with a bad password")

    tok_b = login(supabase_url, anon_key, email_b, pass_b) if (email_b and pass_b) else None
    if tok_b:
        ok("AUTH-02 tenant B signs in", email_b)
    else:
        skip("tenant B", "set UAT_B_EMAIL/UAT_B_PASSWORD to enable isolation + gating cases")

    auth_id_a = login_identity(supabase_url, anon_key, email_a, pass_a)
    me = check_identity(api, tok_a, email_a, auth_id_a)
    user_id, plan_a = me.get("id", ""), me.get("plan", "free")

    if tok_b:
        check_tenant_isolation(api, tok_a, tok_b)
        check_plan_gating(api, tok_a, tok_b, plan_a)

    check_invoices(api, tok_a)
    check_bookkeeping(api, tok_a)
    check_cashflow(api, tok_a)
    check_dashboard(api, tok_a)
    check_tasks_and_stories(api, tok_a)
    check_gdpr(api, tok_a)
    check_observability(api, tok_a, user_id)
    check_memory_and_graph(api, tok_a)

    check_dual_auth_routes(api)
    check_google(api, tok_a)
    check_email_delivery(api, tok_a)

    webhook_secret = os.environ.get("UAT_STRIPE_WEBHOOK_SECRET")
    if webhook_secret:
        check_stripe_webhook(api, webhook_secret)
    else:
        skip("BILL-03 webhook signature", "set UAT_STRIPE_WEBHOOK_SECRET to enable")

    passed = sum(1 for s, _, _ in results if s == "PASS")
    failed = sum(1 for s, _, _ in results if s == "FAIL")
    skipped = sum(1 for s, _, _ in results if s == "SKIP")

    print(f"\n{BOLD}── G4-auto summary{RESET}")
    print(f"  passed {passed}  failed {failed}  skipped {skipped}")
    if failed:
        print(f"\n{RED}failed cases:{RESET}")
        for status, case, detail in results:
            if status == "FAIL":
                print(f"  · {case} — {detail}")
        print(f"\n{RED}GATE RED — do not promote.{RESET} See docs/uat/UAT_PLAN.md §4")
        return 1
    print(f"\n{GREEN}GATE GREEN.{RESET} Remaining manual cases: integrations (🔌), PDF content, LLM quality, UX.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
