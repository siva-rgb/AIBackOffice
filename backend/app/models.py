from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that speaks camelCase JSON to the TypeScript frontend while
    keeping Pythonic snake_case fields. FastAPI serializes by alias by default.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
    )


# --- Enums ------------------------------------------------------------------
class TxType(str, Enum):
    income = "income"
    expense = "expense"


class InvoiceStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    viewed = "viewed"
    paid = "paid"
    overdue = "overdue"
    cancelled = "cancelled"


class AgentType(str, Enum):
    bookkeeper = "bookkeeper"
    invoice_follow_up = "invoice_follow_up"
    contract_generator = "contract_generator"
    cashflow_forecaster = "cashflow_forecaster"
    alert_generator = "alert_generator"
    cross_module = "cross_module"
    supervisor = "supervisor"
    chat = "chat"
    butler = "butler"
    butler_gmail = "butler_gmail"
    butler_drive = "butler_drive"
    butler_calendar = "butler_calendar"
    meeting_agent = "meeting_agent"
    gmail_agent = "gmail_agent"
    calendar_agent = "calendar_agent"
    playbook = "playbook"
    billing = "billing"


# --- Playbook (Agent Intelligence) ------------------------------------------
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
    value: dict[str, Any] = {}
    summary: str | None = None
    confidence: float = 0.5
    source: PlaybookSource = PlaybookSource.observation
    observation_count: int = 1
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    expires_at: str | None = None
    created_at: str


class PlaybookCreate(CamelModel):
    category: PlaybookCategory
    client_id: str | None = None
    key: str = Field(min_length=1, max_length=200)
    value: dict[str, Any] = {}
    summary: str | None = Field(default=None, max_length=500)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: PlaybookSource = PlaybookSource.observation


class PlaybookUpdate(CamelModel):
    summary: str | None = Field(default=None, max_length=500)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


# --- Business profile — standardized business types -------------------------
class BusinessType(str, Enum):
    """Canonical business types. Drives which profile sections surface in the UI
    and how the AI agents weight context. Legacy values are normalized on read
    via `normalize_business_type()`."""

    freelancer = "freelancer"
    online_seller = "online_seller"
    small_business = "small_business"
    agency = "agency"
    startup = "startup"


# Legacy → canonical mapping (older stored values, kept working non-destructively).
_LEGACY_BUSINESS_TYPE: dict[str, str] = {
    "micro_business": "small_business",
    "etsy_seller": "online_seller",
    "fiverr_seller": "online_seller",
    "marketplace_seller": "online_seller",
    "side_hustler": "freelancer",
    "side_project": "freelancer",
    "side_business": "freelancer",
    "solopreneur": "freelancer",
    "consultant": "freelancer",
}


def normalize_business_type(value: str | None) -> str | None:
    """Map any stored/legacy business_type string to a canonical BusinessType
    value. Unknown values pass through unchanged (never raises)."""
    if not value:
        return value
    v = value.strip().lower()
    if v in _LEGACY_BUSINESS_TYPE:
        return _LEGACY_BUSINESS_TYPE[v]
    return v


# --- Business profile — six-domain nested sub-models ------------------------
# All additive & optional: the profile is stored as a single JSONB blob on
# users.profile and fills up over time. Existing flat fields (below) stay the
# canonical source for the invoice/contract agents; these richer objects give
# every agent brand/offering/customer/ops/marketing context.
class BrandIdentity(CamelModel):
    mission: str | None = None
    vision: str | None = None
    values: list[str] = []
    usp: str | None = None  # unique selling proposition
    voice: str | None = None  # brand voice / tone in prose
    colors: list[str] = []  # hex or named brand colors
    logo_url: str | None = None
    style_guidelines: str | None = None


class Offering(CamelModel):
    name: str | None = None
    description: str | None = None
    pricing: str | None = None  # free-text ("$120/hr", "from $2k")
    packages: list[str] = []
    delivery_process: str | None = None
    guarantees: str | None = None


class BuyerPersona(CamelModel):
    name: str | None = None
    description: str | None = None
    pain_points: list[str] = []
    goals: list[str] = []


class Customers(CamelModel):
    buyer_personas: list[BuyerPersona] = []
    industries_served: list[str] = []
    locations: list[str] = []
    pain_points: list[str] = []
    goals: str | None = None


class TeamMember(CamelModel):
    name: str | None = None
    role: str | None = None


class Operations(CamelModel):
    team_members: list[TeamMember] = []
    working_hours: str | None = None
    tools: list[str] = []
    workflows: str | None = None
    sops: list[str] = []  # standard operating procedures


class SocialAccount(CamelModel):
    platform: str | None = None
    handle: str | None = None
    url: str | None = None


class Marketing(CamelModel):
    competitors: list[str] = []
    channels: list[str] = []
    social_accounts: list[SocialAccount] = []
    testimonials: list[str] = []
    case_studies: list[str] = []
    sales_scripts: list[str] = []


class LegalFinancial(CamelModel):
    registration_details: str | None = None  # entity type, registration #
    tax_info: str | None = None  # tax jurisdiction / notes
    invoicing_preferences: str | None = None
    payment_methods: list[str] = []
    contract_notes: str | None = None


# --- Domain models ----------------------------------------------------------
class BusinessProfile(CamelModel):
    """Owner + business profile (stored in users.profile JSONB). All optional —
    fills up over time via onboarding and the Settings page, and is the context
    the supervisor + butler agents read to manage the owner's finances, invoices,
    and contracts.

    Two layers: flat scalar fields (the canonical source the invoice/contract
    agents read) + six additive nested domains (brand/offerings/customers/
    operations/marketing/legal_financial) that give every agent richer context.
    Each nested domain maps to one Settings tab and one top-level JSONB key, so a
    partial save (shallow top-level merge in PATCH /api/profile) never wipes the
    others."""

    # Owner
    display_name: str | None = None  # how they like to be addressed
    role_title: str | None = None  # e.g. "Freelance Brand Designer"
    phone: str | None = None
    # Business
    business_type: str | None = None  # BusinessType: freelancer | online_seller | small_business | agency | startup
    industry: str | None = None  # design, development, writing, crafts, consulting…
    description: str | None = None  # what the business does, in plain English
    website: str | None = None
    founded_year: int | None = None
    address: str | None = None
    business_address: str | None = None  # full postal address for invoices
    timezone: str | None = None
    # Offerings & clients
    services: list[str] = []  # services / products offered
    target_clients: str | None = None  # who they serve
    # Financial preferences (used by invoice / contract / finance agents)
    default_payment_terms_days: int | None = None  # Net X
    default_hourly_rate: float | None = None
    typical_project_value: float | None = None
    invoice_prefix: str | None = None
    tax_id: str | None = None
    default_tax_rate: float | None = None
    payment_methods: list[str] = []  # bank transfer, Stripe, PayPal…
    # Goals (for the supervisor agent)
    monthly_revenue_goal: float | None = None
    annual_revenue_goal: float | None = None
    financial_goals: str | None = None  # free-text priorities / targets
    business_priorities: list[str] = []
    # Invoice sender info (invoice_artifact)
    invoice_footer: str | None = None  # bank details, payment instructions, thank-you note
    # Communication
    brand_tone: str | None = None  # friendly | professional | concise | formal
    # Notification preferences (owner emails — opt-out, default on)
    notify_daily_digest: bool = True  # email the Manager daily digest
    notify_critical_alerts: bool = True  # email on cash-flow danger / payment failed
    # Six-domain nested profile (additive; each maps to one Settings tab)
    brand: BrandIdentity = Field(default_factory=BrandIdentity)
    offerings: list[Offering] = []
    customers: Customers = Field(default_factory=Customers)
    operations: Operations = Field(default_factory=Operations)
    marketing: Marketing = Field(default_factory=Marketing)
    legal_financial: LegalFinancial = Field(default_factory=LegalFinancial)

    @field_validator(
        "brand",
        "customers",
        "operations",
        "marketing",
        "legal_financial",
        mode="before",
    )
    @classmethod
    def _coerce_domain(cls, v):
        # JSONB may store null for a never-touched domain — normalise to {}.
        return v or {}

    @field_validator("business_type", mode="before")
    @classmethod
    def _normalize_type(cls, v):
        return normalize_business_type(v) if isinstance(v, str) else v


class User(CamelModel):
    id: str
    email: str
    full_name: str | None = None
    business_name: str | None = None
    country: str = "US"
    currency: str = "USD"
    plan: Literal["free", "starter", "pro"] = "free"
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    contract_credits: int = 0
    onboarding_completed: bool = False
    profile: BusinessProfile = Field(default_factory=BusinessProfile)
    google_connected: bool = False
    google_email: str | None = None
    # M9.3 — GDPR/CCPA consent capture. Set on first onboarding completion
    # (see routers/users.py::update_me) and updatable via POST /api/account/consent.
    consent_version: str | None = None
    consent_given_at: str | None = None
    created_at: str

    @field_validator("profile", mode="before")
    @classmethod
    def _coerce_profile(cls, v):
        # JSONB may arrive as None (pre-migration) — normalise to an empty profile.
        return v or {}


class Transaction(CamelModel):
    id: str
    user_id: str
    date: str
    description: str
    amount: float
    currency: str = "USD"
    type: TxType
    category: str | None = None
    subcategory: str | None = None
    tax_deductible: bool = False
    source: str = "manual"
    ai_categorized: bool = False
    ai_confidence: float | None = None
    raw_text: str | None = None
    report_id: str | None = None
    # Source-system id (Stripe balance transaction, etc). When present it is the
    # dedupe key instead of (date, description, amount) — two genuine payments
    # from the same client on the same day for the same amount are two rows, not
    # one. See migrations/2026-08-15_transaction_external_id.sql.
    external_id: str | None = None
    created_at: str


class LineItem(CamelModel):
    description: str = Field(min_length=1, max_length=300)
    quantity: float = Field(gt=0, le=100000)
    rate: float = Field(ge=0, le=10_000_000)
    amount: float | None = None


class Invoice(CamelModel):
    id: str
    user_id: str
    invoice_number: str
    client_name: str
    client_email: str
    line_items: list[LineItem] = []
    subtotal: float = 0
    tax_rate: float = 0
    tax_amount: float = 0
    total: float = 0
    currency: str = "USD"
    status: InvoiceStatus = InvoiceStatus.draft
    due_date: str
    notes: str | None = None
    payment_link: str | None = None
    contract_id: str | None = None
    sent_at: str | None = None
    viewed_at: str | None = None
    paid_at: str | None = None
    follow_up_count: int = 0
    last_follow_up_at: str | None = None
    # Invoice enhancements (invoice_artifact)
    invoice_date: str | None = None
    payment_terms: str | None = None
    payment_terms_days: int | None = None
    client_address: str | None = None
    client_tax_id: str | None = None
    po_number: str | None = None
    pdf_path: str | None = None
    email_message_id: str | None = None
    amount_paid: float | None = 0
    created_at: str


class AgentLog(CamelModel):
    id: str
    user_id: str
    agent_type: AgentType
    action: str
    input: Any = None
    output: Any = None
    model_used: str = "gemini-1.5-pro"
    tokens_used: int | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None
    status: Literal["success", "error", "partial"] = "success"
    error_message: str | None = None
    triggered_by: Literal["user", "scheduler", "cross_module", "webhook"] = "user"
    source_record_type: str | None = None
    source_record_id: str | None = None
    created_at: str


class Alert(CamelModel):
    id: str
    user_id: str
    type: str
    severity: Literal["info", "warning", "critical"] = "info"
    title: str
    body: str
    action_label: str | None = None
    action_url: str | None = None
    read: bool = False
    created_at: str


# --- Request bodies ---------------------------------------------------------
PAYMENT_TERMS_MAP: dict[str, int] = {
    "Due on receipt": 0,
    "Net 7": 7,
    "Net 14": 14,
    "Net 21": 21,
    "Net 30": 30,
    "Net 45": 45,
    "Net 60": 60,
}


class CreateInvoiceRequest(CamelModel):
    client_id: str | None = None
    client_name: str = Field(min_length=1, max_length=200)
    client_email: EmailStr
    line_items: list[LineItem] = Field(min_length=1, max_length=50)
    tax_rate: float = Field(default=0, ge=0, le=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    due_date: str
    notes: str | None = Field(default=None, max_length=2000)
    # Invoice enhancements (invoice_artifact)
    invoice_date: str | None = None
    payment_terms: str | None = Field(default="Net 14", max_length=50)
    payment_terms_days: int | None = 14
    client_address: str | None = Field(default=None, max_length=1000)
    client_tax_id: str | None = Field(default=None, max_length=100)
    po_number: str | None = Field(default=None, max_length=100)

    @field_validator("due_date")
    @classmethod
    def _valid_date(cls, v: str) -> str:
        datetime.strptime(v, "%Y-%m-%d")  # raises if not YYYY-MM-DD
        return v


class UpdateInvoiceStatusRequest(CamelModel):
    status: InvoiceStatus


class RecordPaymentRequest(CamelModel):
    amount: float = Field(gt=0)


# --- Contracts (Module 5) ---------------------------------------------------
class ContractType(str, Enum):
    nda = "nda"
    freelance_agreement = "freelance_agreement"
    service_contract = "service_contract"
    refund_policy = "refund_policy"
    ip_transfer = "ip_transfer"


class ContractStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    signed = "signed"
    expired = "expired"
    cancelled = "cancelled"


class Contract(CamelModel):
    id: str
    user_id: str
    type: ContractType
    title: str | None = None
    client_name: str
    client_email: str | None = None
    provider_name: str | None = None
    jurisdiction: str = "US"
    terms: dict[str, Any] = {}
    content_md: str | None = None
    section_explanations: dict[str, str] = {}
    status: ContractStatus = ContractStatus.draft
    signed_at: str | None = None
    created_at: str


class GenerateContractRequest(CamelModel):
    type: ContractType
    client_name: str = Field(min_length=1, max_length=200)
    client_email: EmailStr | None = None
    provider_name: str | None = Field(default=None, max_length=200)
    jurisdiction: str = Field(default="US", min_length=2, max_length=100)
    terms: dict[str, Any] = Field(default_factory=dict)

    @field_validator("terms")
    @classmethod
    def _limit_terms(cls, v: dict) -> dict:
        if len(v) > 30:
            raise ValueError("Too many terms fields")
        return v


class UpdateContractStatusRequest(CamelModel):
    status: ContractStatus


# --- Contract review (risk / loophole analysis) -----------------------------
class ReviewFinding(CamelModel):
    title: str
    severity: Literal["high", "medium", "low"] = "medium"
    category: str | None = None  # payment | liability | ip | termination | confidentiality | scope | jurisdiction | other
    issue: str
    recommendation: str | None = None
    clause_reference: str | None = None


class ContractReview(CamelModel):
    overall_risk: Literal["high", "medium", "low"] = "medium"
    summary: str = ""
    findings: list[ReviewFinding] = []
    missing_clauses: list[str] = []
    favorable_points: list[str] = []
    source: str = "kora"  # 'kora' | 'upload' | 'paste'
    title: str | None = None
    reviewed_at: str


class ReviewTextRequest(CamelModel):
    text: str = Field(min_length=20, max_length=100_000)
    title: str | None = Field(default=None, max_length=200)
    # Optional: persist this received contract so the Butler tracks it.
    client_id: str | None = None
    client_name: str | None = Field(default=None, max_length=200)
    save: bool = False


# --- Supervisor / Business Manager ------------------------------------------
class ManagerTask(CamelModel):
    """A proposed action awaiting the owner's decision (human-in-the-loop queue).

    Created by the supervisor for anything client-facing or irreversible; the
    owner Approves (→ the underlying agent runs) or Dismisses it."""

    id: str
    user_id: str
    kind: str  # send_followup | send_demand | review_contract | …
    title: str
    rationale: str = ""
    severity: Literal["info", "warning", "critical"] = "info"
    status: Literal["proposed", "approved", "dismissed", "done", "failed"] = "proposed"
    payload: dict[str, Any] = {}
    source_record_type: str | None = None
    source_record_id: str | None = None
    created_at: str
    resolved_at: str | None = None


# ===========================================================================
# Butler / AI Business Partner (manager_skill/SKILL.md)
# A context + intelligence layer above the point agents: clients become real
# entities, lightweight engagements track work, quick-capture notes are parsed
# into state, proposals feed contracts, retainers feed cash flow, and a daily
# briefing ties it together. Additive — existing modules are untouched. Clients
# link to invoices/contracts by case-insensitive client-name match (no FK on the
# hot tables), so everything stays backward compatible.
# ===========================================================================
ClientType = Literal["individual", "company", "agency", "marketplace"]
ClientStatus = Literal["active", "inactive", "prospect", "churned"]
HealthLabel = Literal["on_track", "at_risk", "needs_attention", "critical"]
EngagementType = Literal["project", "retainer", "one_off", "ongoing"]
EngagementStatus = Literal["planning", "active", "on_track", "at_risk", "paused", "done", "cancelled"]
NoteType = Literal["meeting", "call", "email", "decision", "blocker", "update", "general"]
CaptureStatus = Literal["pending", "parsed", "failed", "partial"]
ProposalStatus = Literal["draft", "sent", "viewed", "accepted", "declined", "expired"]
PricingType = Literal["fixed", "hourly", "retainer", "milestone"]
BillingCycle = Literal["weekly", "monthly", "quarterly", "annual"]
RetainerStatus = Literal["active", "paused", "cancelled"]

# Task ledger — the canonical record of client work (KORA owns this; external
# PM tools like Notion mirror it via external_ref).
TaskStatus = Literal["todo", "in_progress", "blocked", "done", "cancelled"]
TaskPriority = Literal["low", "medium", "high", "urgent"]
# Where the task came from — auto-captured tasks carry a source_ref so re-runs
# update in place instead of duplicating.
TaskSource = Literal["manual", "meeting", "email", "contract", "agent", "notion"]

# Story layer (ADR-0001) — the unit of work under a Task that carries *qualitative*
# status. This is the level that makes the hierarchy self-filling: the agent writes
# these observations from real evidence, so they are not empty boxes a user must fill.
StoryStatus = Literal["todo", "in_progress", "blocked", "done", "cancelled"]
QualitativeKind = Literal["blocker", "going_well", "not_going_well"]
# Where an observation's evidence came from. `user` means a human wrote or corrected it.
EvidenceSource = Literal["email", "meeting", "drive", "task", "invoice", "agent", "user"]


class Client(CamelModel):
    id: str
    user_id: str
    name: str
    email: str | None = None
    # Additional contact addresses for this client (e.g. a 2nd address or
    # colleagues). Used alongside `email` + the corporate domain for Gmail intel.
    contact_emails: list[str] = []
    phone: str | None = None
    company: str | None = None
    industry: str | None = None
    client_type: ClientType = "individual"
    status: ClientStatus = "active"
    what_we_do: str | None = None  # one sentence: "we build their Shopify store"
    notes_md: str | None = None
    timezone: str | None = None
    currency: str = "USD"
    # Invoice-related (invoice_artifact)
    billing_address: str | None = None
    tax_id: str | None = None
    # Health is computed server-side only (never trust client input).
    health_score: int = 100
    health_label: HealthLabel = "on_track"
    health_updated_at: str | None = None
    last_activity_at: str | None = None
    created_at: str


class Engagement(CamelModel):
    id: str
    user_id: str
    client_id: str
    title: str
    description_md: str | None = None
    engagement_type: EngagementType = "project"
    status: EngagementStatus = "active"
    start_date: str | None = None
    target_end_date: str | None = None
    budget: float | None = None
    budget_currency: str = "USD"
    value_delivered: float = 0
    contract_id: str | None = None
    proposal_id: str | None = None
    created_at: str
    updated_at: str | None = None


class ClientNote(CamelModel):
    id: str
    user_id: str
    client_id: str
    engagement_id: str | None = None
    quick_capture_id: str | None = None
    note_type: NoteType = "general"
    content_md: str
    is_ai_generated: bool = False
    created_at: str


class Task(CamelModel):
    """A unit of client work. KORA is the canonical store; `external_ref` links
    the mirrored row in an external PM tool (Notion page id)."""

    id: str
    user_id: str
    client_id: str | None = None
    engagement_id: str | None = None
    title: str
    description_md: str | None = None
    status: TaskStatus = "todo"
    priority: TaskPriority = "medium"
    due_date: str | None = None
    owner: str | None = None  # "me" | "client" | a person's name
    source: TaskSource = "manual"
    source_ref: str | None = None  # idempotency key for auto-captured tasks
    external_ref: str | None = None  # Notion page id
    external_url: str | None = None
    synced_at: str | None = None
    completed_at: str | None = None
    created_at: str
    updated_at: str | None = None


class StoryObservation(CamelModel):
    """One qualitative judgement about a story, with the evidence that produced it.

    ADR-0001 invariant `qualitative_fields_carry_provenance`: `source_ref` is
    **required**. An observation nobody can trace back to an email, meeting or
    document is not persisted — that is what stops this layer decaying into
    unfalsifiable prose.

    Note the deliberate overload: `Task.source_ref` is an auto-capture *idempotency
    key*; here `source_ref` is an *evidence pointer* (a message id, meeting id,
    file id, …). Same name, different job.
    """

    id: str
    kind: QualitativeKind
    text: str = Field(min_length=1, max_length=1000)
    source: EvidenceSource
    source_ref: str = Field(min_length=1, max_length=300)
    observed_at: str
    # Set when a human writes or corrects this entry. ADR-0001 invariant
    # `user_override_survives_agent_refresh`: a later agent refresh must never
    # mutate or delete an entry carrying this flag.
    user_edited: bool = False


class Story(CamelModel):
    """A unit of work under a Task, carrying progress and qualitative status."""

    id: str
    user_id: str
    task_id: str
    # Denormalized from the parent task so a story can be scoped to a client or
    # project without a join — the roll-up (M2) and per-client views read these hot.
    client_id: str | None = None
    engagement_id: str | None = None
    title: str
    description_md: str | None = None
    status: StoryStatus = "todo"
    progress_pct: int = Field(default=0, ge=0, le=100)
    observations: list[StoryObservation] = []
    completed_at: str | None = None
    created_at: str
    updated_at: str | None = None


class StoryCreate(CamelModel):
    task_id: str
    title: str = Field(min_length=1, max_length=300)
    description_md: str | None = Field(default=None, max_length=5000)
    status: StoryStatus = "todo"
    progress_pct: int = Field(default=0, ge=0, le=100)


class StoryUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description_md: str | None = Field(default=None, max_length=5000)
    status: StoryStatus | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)


class ObservationCreate(CamelModel):
    """Payload for adding an observation. `source_ref` is required by design."""

    kind: QualitativeKind
    text: str = Field(min_length=1, max_length=1000)
    source: EvidenceSource = "user"
    source_ref: str = Field(min_length=1, max_length=300)


class QuickCapture(CamelModel):
    id: str
    user_id: str
    raw_text: str
    source: Literal["web", "mobile", "email", "sms"] = "web"
    parse_status: CaptureStatus = "pending"
    parsed_intent: str | None = None
    parsed_entities: dict[str, Any] = {}
    ai_confidence: float | None = None
    actions_taken: list[dict[str, Any]] = []
    requires_review: bool = False
    created_at: str
    parsed_at: str | None = None


class Proposal(CamelModel):
    id: str
    user_id: str
    client_id: str | None = None
    title: str
    proposal_number: str | None = None
    scope_md: str | None = None
    deliverables_md: str | None = None
    timeline_md: str | None = None
    content_md: str | None = None
    section_explanations: dict[str, str] = {}
    total_amount: float = 0
    currency: str = "USD"
    pricing_type: PricingType = "fixed"
    payment_terms: str | None = None
    status: ProposalStatus = "draft"
    valid_until: str | None = None
    sent_at: str | None = None
    accepted_at: str | None = None
    contract_id: str | None = None
    created_at: str


class Retainer(CamelModel):
    id: str
    user_id: str
    client_id: str | None = None
    title: str
    amount: float
    currency: str = "USD"
    billing_cycle: BillingCycle = "monthly"
    start_date: str
    end_date: str | None = None
    next_invoice_date: str | None = None
    renewal_date: str | None = None
    status: RetainerStatus = "active"
    auto_invoice: bool = True
    created_at: str


# --- Butler request bodies --------------------------------------------------
class ClientCreate(CamelModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    contact_emails: list[EmailStr] = Field(default_factory=list, max_length=20)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    client_type: ClientType = "individual"
    status: ClientStatus = "active"
    what_we_do: str | None = Field(default=None, max_length=500)
    notes_md: str | None = Field(default=None, max_length=5000)
    timezone: str | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    billing_address: str | None = Field(default=None, max_length=1000)
    tax_id: str | None = Field(default=None, max_length=100)


class ClientUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    contact_emails: list[EmailStr] | None = Field(default=None, max_length=20)
    phone: str | None = None
    company: str | None = None
    industry: str | None = None
    client_type: ClientType | None = None
    status: ClientStatus | None = None
    what_we_do: str | None = Field(default=None, max_length=500)
    notes_md: str | None = Field(default=None, max_length=5000)
    timezone: str | None = None
    currency: str | None = None
    billing_address: str | None = Field(default=None, max_length=1000)
    tax_id: str | None = Field(default=None, max_length=100)


class EngagementCreate(CamelModel):
    title: str = Field(min_length=1, max_length=200)
    description_md: str | None = Field(default=None, max_length=2000)
    engagement_type: EngagementType = "project"
    status: EngagementStatus = "active"
    start_date: str | None = None
    target_end_date: str | None = None
    budget: float | None = Field(default=None, ge=0)
    budget_currency: str = "USD"
    contract_id: str | None = None


class EngagementUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description_md: str | None = Field(default=None, max_length=2000)
    engagement_type: EngagementType | None = None
    status: EngagementStatus | None = None
    start_date: str | None = None
    target_end_date: str | None = None
    budget: float | None = Field(default=None, ge=0)
    value_delivered: float | None = Field(default=None, ge=0)


class TaskCreate(CamelModel):
    title: str = Field(min_length=1, max_length=300)
    description_md: str | None = Field(default=None, max_length=5000)
    client_id: str | None = None
    engagement_id: str | None = None
    status: TaskStatus = "todo"
    priority: TaskPriority = "medium"
    due_date: str | None = None
    owner: str | None = Field(default=None, max_length=120)


class TaskUpdate(CamelModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description_md: str | None = Field(default=None, max_length=5000)
    client_id: str | None = None
    engagement_id: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: str | None = None
    owner: str | None = Field(default=None, max_length=120)


class NoteCreate(CamelModel):
    note_type: NoteType = "general"
    content_md: str = Field(min_length=1, max_length=5000)
    engagement_id: str | None = None


class CaptureCreate(CamelModel):
    text: str = Field(min_length=1, max_length=2000)
    source: Literal["web", "mobile", "email", "sms"] = "web"


class ProposalGenerateRequest(CamelModel):
    client_id: str | None = None
    client_name: str | None = Field(default=None, max_length=200)
    client_email: EmailStr | None = None
    title: str = Field(min_length=1, max_length=200)
    scope_description: str = Field(min_length=10, max_length=2000)
    deliverables_raw: str = Field(default="", max_length=2000)
    timeline_description: str = Field(default="", max_length=1000)
    total_amount: float = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    pricing_type: PricingType = "fixed"
    payment_terms: str = Field(default="50% upfront, 50% on completion", max_length=200)
    valid_days: int = Field(default=30, ge=7, le=90)


class RetainerCreate(CamelModel):
    client_id: str | None = None
    client_name: str | None = Field(default=None, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    billing_cycle: BillingCycle = "monthly"
    start_date: str
    end_date: str | None = None
    auto_invoice: bool = True

    @field_validator("start_date")
    @classmethod
    def _valid_start(cls, v: str) -> str:
        datetime.strptime(v, "%Y-%m-%d")
        return v
