# Playbook — Frontend Reference

A settings sub-page where users can see, edit, and delete everything Kora has learned.
This is the trust layer — the user audits the source. If the source is correct, the output
is correct. If the source is wrong, they fix it here.

---

## New route

```
/settings/playbook   — "What Kora knows" page
```

Add a link in the settings sidebar/nav: "What Kora knows" with icon `ti-brain`.

---

## TypeScript types (add to `lib/api/types.ts`)

```typescript
export interface PlaybookEntry {
  id: string
  userId: string
  category: "correction" | "user_preference" | "client_intelligence" |
            "business_pattern" | "business_rule" | "extracted_fact"
  clientId: string | null
  key: string
  value: Record<string, unknown>
  summary: string | null
  confidence: number
  source: "onboarding" | "observation" | "correction" | "extraction" | "pattern_detection"
  observationCount: number
  firstObservedAt: string | null
  lastObservedAt: string | null
  expiresAt: string | null
}
```

---

## API routes (backend)

```python
# backend/app/routers/playbook.py
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app import store
from app.models import PlaybookCreate, PlaybookUpdate
from app.services.playbook import detect_patterns, compress_playbook_to_memory

router = APIRouter(prefix="/playbook", tags=["playbook"])

@router.get("")
async def list_playbook(
    category: str = None,
    client_id: str = None,
    user=Depends(get_current_user),
):
    """List all Playbook entries for the current user."""
    return store.get_playbook_entries(
        user["id"],
        category=category,
        client_id=client_id,
        min_confidence=0.0,  # show everything in the viewer, even low confidence
        limit=200,
    )

@router.post("")
async def create_entry(body: PlaybookCreate, user=Depends(get_current_user)):
    """Manually add a Playbook entry (user tells Kora something)."""
    from app.utils.security import sanitize_prompt_input
    entry = body.model_dump()
    if entry.get("summary"):
        entry["summary"] = sanitize_prompt_input(entry["summary"])
    return store.upsert_playbook_entry(user["id"], entry)

@router.patch("/{entry_id}")
async def update_entry(
    entry_id: str,
    body: PlaybookUpdate,
    user=Depends(get_current_user),
):
    """Edit a Playbook entry (user corrects what Kora learned)."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    return store.update_playbook_entry(user["id"], entry_id, updates)

@router.delete("/{entry_id}")
async def delete_entry(entry_id: str, user=Depends(get_current_user)):
    """Delete a Playbook entry (user says 'forget this')."""
    store.delete_playbook_entry(user["id"], entry_id)
    return {"deleted": True}

@router.post("/detect")
async def run_pattern_detection(user=Depends(get_current_user)):
    """Trigger pattern detection (analyze history for new patterns)."""
    patterns = detect_patterns(user["id"])
    return {"detected": len(patterns), "patterns": patterns}

@router.post("/compress")
async def compress_memory(user=Depends(get_current_user)):
    """Compress Playbook into kora_memory for faster prompt injection."""
    memory = compress_playbook_to_memory(user["id"])
    return memory

@router.get("/stats")
async def playbook_stats(user=Depends(get_current_user)):
    """Summary stats for the Playbook viewer header."""
    entries = store.get_playbook_entries(
        user["id"], min_confidence=0.0, limit=500
    )
    from collections import Counter
    by_category = Counter(e.get("category", "") for e in entries)
    return {
        "total": len(entries),
        "corrections": by_category.get("correction", 0),
        "preferences": by_category.get("user_preference", 0),
        "clientIntelligence": by_category.get("client_intelligence", 0),
        "businessPatterns": by_category.get("business_pattern", 0),
        "businessRules": by_category.get("business_rule", 0),
        "extractedFacts": by_category.get("extracted_fact", 0),
        "highConfidence": len([e for e in entries if e.get("confidence", 0) >= 0.7]),
    }
```

---

## Frontend page

```
app/(dashboard)/settings/playbook/page.tsx
```

### Layout

Header section:
- Title: "What Kora knows"
- Subtitle: "Everything Kora has learned about your business. Edit or remove anything that's wrong."
- Stats row: [Total entries] [Corrections] [High confidence] [Patterns detected]
- Two buttons: "Detect patterns" (POST /playbook/detect) and "Refresh memory" (POST /playbook/compress)

Category tabs (filter the list):
- All | Corrections | Preferences | Client intel | Patterns | Rules | Facts

Entry list:
- Each entry is a card showing:
  [Confidence indicator: green ≥0.7, amber 0.5-0.69, gray <0.5]
  [Category badge]
  [Key as title]
  [Summary as body text]
  [Observation count: "Observed 5 times"]
  [Last observed: "3 days ago"]
  [Edit button] [Delete button]

- Clicking Edit opens an inline form to change the summary and confidence
- Clicking Delete shows a confirmation dialog

### Empty state

```
Icon: ti-brain (large, muted)
Title: "Kora hasn't learned anything yet"
Body: "As you use Kora — approving actions, correcting categories,
       editing email drafts — it learns your preferences and patterns.
       The more you use it, the smarter it gets."
```

### Confidence indicator component

```typescript
function ConfidenceDot({ confidence }: { confidence: number }) {
  const color = confidence >= 0.7
    ? "bg-green-500"
    : confidence >= 0.5
    ? "bg-amber-500"
    : "bg-gray-400"
  const label = confidence >= 0.7
    ? "High confidence"
    : confidence >= 0.5
    ? "Medium confidence"
    : "Low confidence"
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${color}`}
      title={`${label} (${Math.round(confidence * 100)}%)`}
    />
  )
}
```

### Category badge colors

```
correction          → red badge    (these are permanent fixes)
user_preference     → blue badge
client_intelligence → purple badge
business_pattern    → teal badge
business_rule       → amber badge
extracted_fact      → gray badge
```

### Seed data for demo (memory_store)

Add to the demo seed so the page isn't empty in mock mode:

```python
# In memory_store.py seed or app/seed.py
_playbook["demo-user-id"] = [
    {
        "id": "pb-1",
        "user_id": "demo-user-id",
        "category": "correction",
        "client_id": None,
        "key": "category_override_adobe systems",
        "value": {"description_pattern": "adobe systems", "old_category": "other_expense",
                  "new_category": "software_subscriptions"},
        "summary": '"adobe systems" → software_subscriptions (corrected from other_expense)',
        "confidence": 1.0,
        "source": "correction",
        "observation_count": 1,
        "first_observed_at": "2026-06-01T10:00:00Z",
        "last_observed_at": "2026-06-01T10:00:00Z",
    },
    {
        "id": "pb-2",
        "user_id": "demo-user-id",
        "category": "user_preference",
        "client_id": None,
        "key": "email_style",
        "value": {"tone": "direct", "length_preference": "shorter"},
        "summary": "User prefers direct, shorter emails",
        "confidence": 0.72,
        "source": "observation",
        "observation_count": 4,
        "first_observed_at": "2026-06-02T08:00:00Z",
        "last_observed_at": "2026-06-15T09:00:00Z",
    },
    {
        "id": "pb-3",
        "user_id": "demo-user-id",
        "category": "client_intelligence",
        "client_id": "harbor-design-id",
        "key": "payment_reliability",
        "value": {"reliability": "slow_but_pays", "paid_percentage": 85,
                  "total_invoices": 7},
        "summary": "Payment reliability: slow but pays (85% on time, 7 invoices)",
        "confidence": 0.82,
        "source": "pattern_detection",
        "observation_count": 7,
        "first_observed_at": "2026-06-05T07:00:00Z",
        "last_observed_at": "2026-06-15T07:00:00Z",
    },
    {
        "id": "pb-4",
        "user_id": "demo-user-id",
        "category": "business_rule",
        "client_id": None,
        "key": "skip_send_followup",
        "value": {"kind": "send_followup", "reason": "repeatedly dismissed day-3 follow-ups"},
        "summary": "User consistently dismisses day-3 invoice follow-ups — consider skipping",
        "confidence": 0.71,
        "source": "observation",
        "observation_count": 5,
        "first_observed_at": "2026-06-03T09:00:00Z",
        "last_observed_at": "2026-06-14T09:00:00Z",
    },
]
```
