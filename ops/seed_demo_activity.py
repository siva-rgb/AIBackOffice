"""Seed realistic meeting activity into a demo tenant.

The Meetings, Tasks and Stories surfaces were empty, which made three pages of a
working product look unfinished. This drives the *real* pipeline rather than
inserting rows: each note goes through `POST /api/meetings/quick-note`, which
runs the meeting agent, which extracts decisions/commitments/risks/next steps,
which creates action items, which the task ledger auto-captures as tasks. So the
seeded data also demonstrates the end-to-end flow it is standing in for.

Stories hang off tasks (`StoryCreate.task_id`), so they are created last, from
whatever tasks the extraction actually produced.

    python ops/seed_demo_activity.py --target <backend-url> [--dry-run]

Credentials come from the environment / frontend/.env.local, never from source:
    KORA_SEED_EMAIL, KORA_SEED_PASSWORD  (default: the demo tenant)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Clients are resolved by name at runtime — ids differ per environment.
MEETINGS = [
    {
        "client": "Acme Corp",
        "title": "Acme — Q3 site redesign kickoff",
        "notes": """Kickoff call with Priya and Tom from Acme Corp about the Q3 marketing site redesign.

We agreed the scope covers five templates: home, product, pricing, case study and a blog index. Anything beyond that is a change request, billed separately at the standard day rate.

Priya confirmed the budget is approved at 18,000 USD, split 50% up front and 50% on delivery. I said I would raise the deposit invoice this week so their finance team can process it before month end.

Tom raised that their brand refresh is still with the agency and final logo files will not land until the 22nd. We agreed to build in greyscale and swap assets in at the end, but flagged this as a schedule risk — if the logos slip past the 22nd the delivery date moves with them.

Decisions: five templates only; greyscale-first build; delivery target is the last Friday of the quarter.

I committed to sending the project plan and the deposit invoice by Friday. Priya will send brand guidelines and access to their staging environment. Tom will chase the agency on the logo files and confirm by the 15th.

We also discussed ongoing support after launch. Priya is interested in a monthly retainer but wants to see the project land first, so we parked it until the delivery review.""",
    },
    {
        "client": "Nova Agency",
        "title": "Nova — overdue invoice and scope change",
        "notes": """Call with Daniel at Nova Agency, mostly about the outstanding invoice.

Nova's invoice is past due. Daniel apologised and explained their client payment came in late, which pushed their whole payables run. He committed to paying in full within ten working days and asked us not to pause the work in the meantime.

I agreed to keep the current sprint running but said we would not start the next phase until the balance clears. Daniel accepted that.

Second topic was scope. Nova want to add a second language to the portal — the current build assumes English only. That is a real change: it affects the CMS structure, the routing and the QA matrix. I estimated it as roughly two additional weeks and said I would send a written change request with a firm number.

Risk I flagged internally: this is the second time Nova have paid late, and they are now asking for more scope on top of an unpaid balance. Worth watching.

Next steps: I send the change request for the second language by Wednesday. Daniel sends written confirmation of the payment date from their finance team. We review both at next week's check-in.""",
    },
    {
        "client": "Sarah Kim",
        "title": "Sarah Kim — brand identity scoping",
        "notes": """Introductory scoping call with Sarah Kim, who runs a small photography studio and is launching a new print business.

She needs a full brand identity: logo, colour system, type choices, and templates for invoices and packaging inserts. She does not need a website yet — she is on a hosted store and happy with it.

Budget is the open question. Sarah said she has around 4,000 USD but is flexible if the value is there. I explained our usual identity package sits above that, and proposed a reduced scope that fits: logo plus colour and type system, with the templates as an optional second phase.

Sarah was happy with that and asked for a written proposal. She wants to start next month.

Decisions: phase one is identity only; templates deferred to phase two; kickoff targeted for the first week of next month.

I committed to sending a proposal with both phases priced separately by Monday. Sarah will send examples of brands she likes and her existing photography portfolio so we can judge tone.

No risks flagged — small, well-defined piece of work with a motivated client.""",
    },
]

STORIES = [
    {"match": "deposit invoice", "title": "Raise and send the Acme deposit invoice", "status": "in_progress", "progress": 60},
    {"match": "change request", "title": "Price the Nova second-language change request", "status": "todo", "progress": 0},
    {"match": "proposal", "title": "Draft the Sarah Kim identity proposal", "status": "in_progress", "progress": 30},
]


def read_env_file(path: Path, key: str) -> str | None:
    """Last match wins — dotenv gives a later duplicate precedence."""
    try:
        hit = None
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{key}="):
                hit = line.split("=", 1)[1].strip().strip('"').strip("'")
        return hit
    except OSError:
        return None


def call(method: str, url: str, token: str | None = None, body: dict | None = None, api_key: str | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if api_key:
        req.add_header("apikey", api_key)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw
    except Exception as exc:  # network / timeout
        return 0, str(exc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="backend base URL")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    supabase_url = read_env_file(ROOT / "frontend" / ".env.local", "NEXT_PUBLIC_SUPABASE_URL")
    anon = read_env_file(ROOT / "frontend" / ".env.local", "NEXT_PUBLIC_SUPABASE_ANON_KEY")
    email = os.environ.get("KORA_SEED_EMAIL", "demo@kora.app")
    password = os.environ.get("KORA_SEED_PASSWORD")
    if not (supabase_url and anon and password):
        print("!! need NEXT_PUBLIC_SUPABASE_URL/_ANON_KEY in frontend/.env.local and KORA_SEED_PASSWORD in env", file=sys.stderr)
        return 2

    status, body = call("POST", f"{supabase_url}/auth/v1/token?grant_type=password", api_key=anon, body={"email": email, "password": password})
    token = (body or {}).get("access_token") if isinstance(body, dict) else None
    if not token:
        print(f"!! login failed ({status}): {body}", file=sys.stderr)
        return 2
    print(f"authenticated as {email}")

    status, clients = call("GET", f"{args.target}/api/clients", token=token)
    by_name = {c["name"]: c["id"] for c in clients} if isinstance(clients, list) else {}
    print(f"clients: {list(by_name)}")

    if args.dry_run:
        print("dry run — nothing written")
        return 0

    created = []
    for m in MEETINGS:
        cid = by_name.get(m["client"])
        if not cid:
            print(f"  skip {m['title']} — no client named {m['client']!r}")
            continue
        status, resp = call(
            "POST",
            f"{args.target}/api/meetings/quick-note",
            token=token,
            body={"clientId": cid, "title": m["title"], "notes": m["notes"]},
        )
        print(f"  [{status}] {m['title']} -> {resp}")
        if status == 200 and isinstance(resp, dict):
            created.append(resp.get("meeting_id"))
        time.sleep(2)

    if not created:
        print("no meetings created; stopping before stories")
        return 1

    # The meeting agent runs as a background task; give it room to extract.
    print("waiting for extraction...")
    time.sleep(45)

    status, tasks = call("GET", f"{args.target}/api/tasks", token=token)
    tasks = tasks if isinstance(tasks, list) else []
    print(f"tasks after extraction: {len(tasks)}")

    made = 0
    for spec in STORIES:
        task = next((t for t in tasks if spec["match"].lower() in (t.get("title") or "").lower()), None)
        task = task or (tasks[made] if made < len(tasks) else None)
        if not task:
            continue
        status, resp = call(
            "POST",
            f"{args.target}/api/stories",
            token=token,
            body={"taskId": task["id"], "title": spec["title"], "status": spec["status"], "progressPct": spec["progress"]},
        )
        print(f"  [{status}] story: {spec['title']}")
        made += status in (200, 201)

    print(f"\nseeded {len(created)} meetings, {made} stories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
