# Playbook — Schema Reference

---

## Migration SQL

```sql
-- business_playbook: one row per learned fact/pattern/preference/correction
CREATE TABLE business_playbook (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

  -- What kind of knowledge
  category          TEXT NOT NULL CHECK (category IN (
    'correction',          -- explicit user fix (highest priority, never decays)
    'user_preference',     -- learned from edits + approve/dismiss patterns
    'client_intelligence', -- per-client behavior patterns
    'business_pattern',    -- seasonality, billing cycles, pricing
    'business_rule',       -- inferred from repeated behavior
    'extracted_fact'       -- from emails, contracts, documents
  )),

  -- Scoping: null = whole business, non-null = client-specific
  client_id         UUID,   -- no FK to avoid touching clients table; matched by ID

  -- The knowledge
  key               TEXT NOT NULL,        -- e.g. "email_tone", "payment_speed"
  value             JSONB NOT NULL,       -- structured value
  summary           TEXT,                 -- plain English for prompt injection

  -- Confidence and provenance
  confidence        NUMERIC(3,2) DEFAULT 0.50 CHECK (confidence BETWEEN 0.0 AND 1.0),
  source            TEXT NOT NULL CHECK (source IN (
    'onboarding', 'observation', 'correction', 'extraction', 'pattern_detection'
  )),
  observation_count INTEGER DEFAULT 1,

  -- Lifecycle
  first_observed_at TIMESTAMPTZ DEFAULT now(),
  last_observed_at  TIMESTAMPTZ DEFAULT now(),
  expires_at        TIMESTAMPTZ,          -- null = permanent (corrections never expire)

  created_at        TIMESTAMPTZ DEFAULT now(),

  UNIQUE (user_id, category, key, client_id)
);

ALTER TABLE business_playbook ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users_own_playbook" ON business_playbook
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE INDEX idx_playbook_user ON business_playbook(user_id, category);
CREATE INDEX idx_playbook_user_confidence ON business_playbook(user_id, confidence DESC)
  WHERE confidence >= 0.5;
CREATE INDEX idx_playbook_client ON business_playbook(user_id, client_id)
  WHERE client_id IS NOT NULL;

-- Add compressed memory column to users (weekly rollup of top Playbook entries)
ALTER TABLE users ADD COLUMN IF NOT EXISTS kora_memory JSONB DEFAULT '{}'::jsonb;

-- Extend agent_logs agent_type CHECK to include 'playbook'
ALTER TABLE agent_logs DROP CONSTRAINT IF EXISTS agent_logs_agent_type_check;
ALTER TABLE agent_logs ADD CONSTRAINT agent_logs_agent_type_check
  CHECK (agent_type IN (
    'bookkeeper','invoice_follow_up','contract_generator',
    'cashflow_forecaster','alert_generator','cross_module',
    'supervisor','chat','butler',
    'butler_gmail','butler_drive','butler_calendar',
    'meeting_agent','gmail_agent','calendar_agent',
    'playbook'
  ));
```

---

## Pydantic models (add to `app/models.py`)

```python
# ── Playbook ──────────────────────────────────────────────────────────────────

class PlaybookCategory(str, Enum):
    correction = "correction"
    user_preference = "user_preference"
    client_intelligence = "client_intelligence"
    business_pattern = "business_pattern"
    business_rule = "business_rule"
    extracted_fact = "extracted_fact"

class PlaybookSource(str, Enum):
    onboarding = "onboarding"
    observation = "observation"
    correction = "correction"
    extraction = "extraction"
    pattern_detection = "pattern_detection"

class PlaybookEntry(CamelModel):
    id: str
    user_id: str
    category: PlaybookCategory
    client_id: str | None = None
    key: str
    value: dict
    summary: str | None = None
    confidence: float = 0.5
    source: PlaybookSource
    observation_count: int = 1
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    expires_at: str | None = None

class PlaybookCreate(CamelModel):
    category: PlaybookCategory
    client_id: str | None = None
    key: str = Field(..., min_length=1, max_length=200)
    value: dict
    summary: str | None = Field(None, max_length=500)
    source: PlaybookSource = PlaybookSource.observation
    confidence: float = Field(0.5, ge=0.0, le=1.0)

class PlaybookUpdate(CamelModel):
    value: dict | None = None
    summary: str | None = None
    confidence: float | None = None
```

---

## Store helpers — supabase_store.py

```python
# Add to backends/supabase_store.py

# ── Playbook ──────────────────────────────────────────────────────────────────

def upsert_playbook_entry(user_id: str, entry: dict) -> dict:
    """Upsert a Playbook entry. On conflict, bumps observation_count and confidence."""
    existing = sb().table("business_playbook").select("*").eq(
        "user_id", user_id
    ).eq("category", entry["category"]).eq("key", entry["key"]).eq(
        "client_id", entry.get("client_id") or ""  # handle null matching
    ).execute().data

    if existing:
        old = existing[0]
        new_count = old.get("observation_count", 1) + 1
        # Confidence grows with observations: 0.3 → 0.5 → 0.65 → 0.75 → 0.82 → ...
        # Formula: 1 - (1 / (1 + 0.3 * count)), capped at 0.95
        # Corrections always stay 1.0
        if entry["category"] == "correction":
            new_confidence = 1.0
        else:
            new_confidence = min(0.95, 1 - (1 / (1 + 0.3 * new_count)))
            # But never lower than what was explicitly set
            new_confidence = max(new_confidence, entry.get("confidence", 0.5))

        return sb().table("business_playbook").update({
            "value": entry["value"],
            "summary": entry.get("summary") or old.get("summary"),
            "confidence": new_confidence,
            "observation_count": new_count,
            "last_observed_at": "now()",
            "source": entry.get("source", old.get("source")),
        }).eq("id", old["id"]).execute().data[0]
    else:
        row = {
            "user_id": user_id,
            "category": entry["category"],
            "client_id": entry.get("client_id"),
            "key": entry["key"],
            "value": entry["value"],
            "summary": entry.get("summary"),
            "confidence": 1.0 if entry["category"] == "correction" else entry.get("confidence", 0.5),
            "source": entry.get("source", "observation"),
            "observation_count": 1,
        }
        # Set expiry: corrections never expire, others expire in 90 days
        if entry["category"] != "correction":
            from datetime import datetime, timedelta
            row["expires_at"] = (datetime.utcnow() + timedelta(days=90)).isoformat()
        return sb().table("business_playbook").insert(row).execute().data[0]


def get_playbook_entries(
    user_id: str,
    category: str = None,
    client_id: str = None,
    min_confidence: float = 0.5,
    limit: int = 50,
) -> list[dict]:
    """Fetch Playbook entries, filtered and sorted by confidence."""
    q = sb().table("business_playbook").select("*").eq(
        "user_id", user_id
    ).gte("confidence", min_confidence).order(
        "confidence", desc=True
    ).limit(limit)

    if category:
        q = q.eq("category", category)
    if client_id:
        q = q.eq("client_id", client_id)
    return q.execute().data


def get_playbook_corrections(user_id: str) -> list[dict]:
    """Get all corrections (always confidence 1.0, never expired)."""
    return sb().table("business_playbook").select("*").eq(
        "user_id", user_id
    ).eq("category", "correction").execute().data


def get_playbook_for_client(user_id: str, client_id: str) -> list[dict]:
    """Get all Playbook entries scoped to a specific client."""
    return sb().table("business_playbook").select("*").eq(
        "user_id", user_id
    ).eq("client_id", client_id).gte(
        "confidence", 0.5
    ).order("confidence", desc=True).limit(20).execute().data


def update_playbook_entry(user_id: str, entry_id: str, updates: dict) -> dict:
    return sb().table("business_playbook").update(updates).eq(
        "id", entry_id).eq("user_id", user_id).execute().data[0]


def delete_playbook_entry(user_id: str, entry_id: str) -> bool:
    sb().table("business_playbook").delete().eq(
        "id", entry_id).eq("user_id", user_id).execute()
    return True


def decay_playbook_entries(user_id: str) -> int:
    """
    Monthly decay: reduce confidence by 0.1 for entries not observed in 90 days.
    Delete entries that hit 0.0. Corrections never decay.
    Returns count of decayed entries.
    """
    from datetime import datetime, timedelta
    ninety_days_ago = (datetime.utcnow() - timedelta(days=90)).isoformat()
    stale = sb().table("business_playbook").select("id, confidence").eq(
        "user_id", user_id
    ).neq("category", "correction").lt(
        "last_observed_at", ninety_days_ago
    ).execute().data

    decayed = 0
    for entry in stale:
        new_conf = round(entry["confidence"] - 0.1, 2)
        if new_conf <= 0:
            sb().table("business_playbook").delete().eq("id", entry["id"]).execute()
        else:
            sb().table("business_playbook").update(
                {"confidence": new_conf}
            ).eq("id", entry["id"]).execute()
        decayed += 1
    return decayed
```

---

## Store helpers — memory_store.py

```python
# Add to backends/memory_store.py
# In-memory Playbook storage for mock/demo mode

_playbook: dict[str, list[dict]] = {}  # user_id → [entries]

def upsert_playbook_entry(user_id: str, entry: dict) -> dict:
    if user_id not in _playbook:
        _playbook[user_id] = []
    entries = _playbook[user_id]
    # Find existing by category + key + client_id
    existing = next(
        (e for e in entries
         if e["category"] == entry["category"]
         and e["key"] == entry["key"]
         and e.get("client_id") == entry.get("client_id")),
        None
    )
    if existing:
        existing["observation_count"] = existing.get("observation_count", 1) + 1
        existing["value"] = entry["value"]
        if entry.get("summary"):
            existing["summary"] = entry["summary"]
        if entry["category"] == "correction":
            existing["confidence"] = 1.0
        else:
            count = existing["observation_count"]
            existing["confidence"] = min(0.95, 1 - (1 / (1 + 0.3 * count)))
        existing["last_observed_at"] = _now()
        return existing
    else:
        import uuid
        new = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            **entry,
            "confidence": 1.0 if entry["category"] == "correction" else entry.get("confidence", 0.5),
            "observation_count": 1,
            "first_observed_at": _now(),
            "last_observed_at": _now(),
        }
        entries.append(new)
        return new

def get_playbook_entries(user_id: str, category=None, client_id=None,
                         min_confidence=0.5, limit=50) -> list[dict]:
    entries = _playbook.get(user_id, [])
    filtered = [e for e in entries if e.get("confidence", 0) >= min_confidence]
    if category:
        filtered = [e for e in filtered if e["category"] == category]
    if client_id:
        filtered = [e for e in filtered if e.get("client_id") == client_id]
    filtered.sort(key=lambda e: e.get("confidence", 0), reverse=True)
    return filtered[:limit]

def get_playbook_corrections(user_id: str) -> list[dict]:
    return [e for e in _playbook.get(user_id, []) if e["category"] == "correction"]

def get_playbook_for_client(user_id: str, client_id: str) -> list[dict]:
    return get_playbook_entries(user_id, client_id=client_id, limit=20)

def update_playbook_entry(user_id: str, entry_id: str, updates: dict) -> dict:
    for e in _playbook.get(user_id, []):
        if e["id"] == entry_id:
            e.update(updates)
            return e
    return {}

def delete_playbook_entry(user_id: str, entry_id: str) -> bool:
    entries = _playbook.get(user_id, [])
    _playbook[user_id] = [e for e in entries if e["id"] != entry_id]
    return True

def decay_playbook_entries(user_id: str) -> int:
    return 0  # no-op in memory mode
```
