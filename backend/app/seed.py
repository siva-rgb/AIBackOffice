from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from .models import (
    AgentLog,
    Alert,
    Client,
    ClientNote,
    Contract,
    Engagement,
    Invoice,
    LineItem,
    Proposal,
    Retainer,
    Transaction,
    User,
)

DEMO_USER_ID = "demo-user"


def _sid(prefix: str) -> str:
    # UUIDs so the same seed works for both the in-memory store and Supabase
    # (where every id column is type UUID). Prefix kept for call-site readability.
    return str(uuid.uuid4())


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _date_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


def _date_days_ahead(days: int) -> str:
    return _date_days_ago(-days)


def build_seed(user_id: str = DEMO_USER_ID) -> dict:
    user = User(
        id=user_id,
        email="alex@studio.example",
        full_name="Alex Rivera",
        business_name="Rivera Studio",
        country="US",
        currency="USD",
        plan="pro",
        onboarding_completed=True,
        created_at=_iso_days_ago(95),
    )

    # Stable id so the signed contract and its auto-created milestone invoice
    # can be linked (powers the contract-grounded demand-letter demo).
    harbor_contract_id = _sid("ctr")

    # [days_ago, description, amount, type, category, subcategory, deductible, conf]
    seeds = [
        (88, "TRANSFER FROM ACME CORP - PROJECT ALPHA", 4200, "income", "client_payment", "project", False, 0.98),
        (85, "ADOBE SYSTEMS *CREATIVECLOUD", 54.99, "expense", "software_subscriptions", "design_tools", True, 0.97),
        (84, "FIGMA.COM SUBSCRIPTION", 15, "expense", "software_subscriptions", "design_tools", True, 0.96),
        (82, "NOTION.SO", 10, "expense", "software_subscriptions", "productivity", True, 0.94),
        (80, "UBER TRIP 2381", 23.4, "expense", "travel_transport", "rideshare", True, 0.88),
        (78, "STARBUCKS STORE 114", 8.75, "expense", "meals_entertainment", "coffee", True, 0.72),
        (70, "STRIPE PAYOUT", 1800, "income", "client_payment", "retainer", False, 0.95),
        (66, "AMAZON WEB SERVICES", 41.22, "expense", "software_subscriptions", "cloud_hosting", True, 0.93),
        (64, "GODADDY DOMAINS", 19.99, "expense", "software_subscriptions", "domains_hosting", True, 0.9),
        (60, "TRANSFER FROM BLUE LABEL LLC", 3500, "income", "client_payment", "project", False, 0.97),
        (58, "WEWORK MEMBERSHIP", 220, "expense", "utilities_internet", "coworking", True, 0.85),
        (55, "DELTA AIR LINES", 412.3, "expense", "travel_transport", "flights", True, 0.91),
        (52, "APPLE STORE - MAGIC KEYBOARD", 149, "expense", "hardware_equipment", "accessories", True, 0.89),
        (48, "GOOGLE WORKSPACE", 12, "expense", "software_subscriptions", "productivity", True, 0.95),
        (45, "TRANSFER FROM ACME CORP - PROJECT ALPHA", 4200, "income", "client_payment", "project", False, 0.98),
        (42, "LINKEDIN ADS", 180, "expense", "marketing_advertising", "social_ads", True, 0.9),
        (40, "LEGALZOOM CONSULT", 99, "expense", "professional_services", "legal", True, 0.86),
        (38, "SPOTIFY PREMIUM", 11.99, "expense", "software_subscriptions", "media", False, 0.8),
        (35, "STRIPE PAYOUT", 950, "income", "client_payment", "project", False, 0.94),
        (33, "OFFICEWORKS SUPPLIES", 64.2, "expense", "office_supplies", None, True, 0.78),
        (30, "ZOOM.US SUBSCRIPTION", 14.99, "expense", "software_subscriptions", "productivity", True, 0.93),
        (28, "TRANSFER FROM BLUE LABEL LLC - APR RETAINER", 3200, "income", "client_payment", "retainer", False, 0.97),
        (25, "UDEMY COURSE - ADVANCED MOTION", 89, "expense", "education_training", "course", True, 0.84),
        (22, "CHASE BANK MONTHLY FEE", 12, "expense", "bank_fees", None, False, 0.66),
        (20, "AMAZON WEB SERVICES", 47.8, "expense", "software_subscriptions", "cloud_hosting", True, 0.93),
        (18, "DOORDASH - CLIENT LUNCH", 38.5, "expense", "meals_entertainment", "meals", True, 0.71),
        (15, "TRANSFER FROM NOVA AGENCY", 2750, "income", "client_payment", "project", False, 0.96),
        (12, "ADOBE SYSTEMS *CREATIVECLOUD", 54.99, "expense", "software_subscriptions", "design_tools", True, 0.97),
        (10, "FACEBOOK ADS", 240, "expense", "marketing_advertising", "social_ads", True, 0.9),
        (8, "B&H PHOTO - MONITOR", 389, "expense", "hardware_equipment", "displays", True, 0.88),
        (6, "FIGMA.COM SUBSCRIPTION", 15, "expense", "software_subscriptions", "design_tools", True, 0.96),
        (4, "TRANSFER FROM ACME CORP", 1200, "income", "client_payment", "project", False, 0.92),
        (2, "NOTION.SO", 10, "expense", "software_subscriptions", "productivity", True, 0.94),
    ]

    transactions: list[Transaction] = []
    for days_ago, desc, amount, t, cat, sub, ded, conf in seeds:
        signed = -abs(amount) if t == "expense" else abs(amount)
        transactions.append(
            Transaction(
                id=_sid("tx"),
                user_id=user_id,
                date=_date_days_ago(days_ago),
                description=desc,
                amount=signed,
                currency="USD",
                type=t,
                category=cat,
                subcategory=sub,
                tax_deductible=ded,
                source="csv",
                ai_categorized=True,
                ai_confidence=conf,
                raw_text=desc,
                created_at=_iso_days_ago(days_ago),
            )
        )

    invoices: list[Invoice] = [
        Invoice(
            id=_sid("inv"),
            user_id=user_id,
            invoice_number="INV-2026-001",
            client_name="Acme Corp",
            client_email="ap@acme.example",
            line_items=[LineItem(description="Brand identity system", quantity=1, rate=4200, amount=4200)],
            subtotal=4200,
            tax_rate=0,
            tax_amount=0,
            total=4200,
            currency="USD",
            status="paid",
            due_date=_date_days_ago(50),
            sent_at=_iso_days_ago(64),
            viewed_at=_iso_days_ago(63),
            paid_at=_iso_days_ago(52),
            follow_up_count=0,
            created_at=_iso_days_ago(64),
        ),
        Invoice(
            id=_sid("inv"),
            user_id=user_id,
            invoice_number="INV-2026-014",
            client_name="Nova Agency",
            client_email="billing@nova.example",
            line_items=[LineItem(description="Landing page design", quantity=1, rate=2750, amount=2750)],
            subtotal=2750,
            tax_rate=0,
            tax_amount=0,
            total=2750,
            currency="USD",
            status="sent",
            due_date=_date_days_ahead(9),
            sent_at=_iso_days_ago(6),
            viewed_at=_iso_days_ago(5),
            follow_up_count=0,
            created_at=_iso_days_ago(6),
        ),
        Invoice(
            id=_sid("inv"),
            user_id=user_id,
            invoice_number="INV-2026-009",
            client_name="Blue Label LLC",
            client_email="accounts@bluelabel.example",
            line_items=[LineItem(description="Monthly retainer — design + motion", quantity=1, rate=3500, amount=3500)],
            subtotal=3500,
            tax_rate=0,
            tax_amount=0,
            total=3500,
            currency="USD",
            status="overdue",
            due_date=_date_days_ago(16),
            notes="Retainer for May.",
            sent_at=_iso_days_ago(30),
            viewed_at=_iso_days_ago(29),
            follow_up_count=2,
            last_follow_up_at=_iso_days_ago(9),
            created_at=_iso_days_ago(30),
        ),
        Invoice(
            id=_sid("inv"),
            user_id=user_id,
            invoice_number="INV-2026-021",
            client_name="Harbor Co",
            client_email="ops@harbor.example",
            line_items=[LineItem(description="Website redesign — project kickoff milestone", quantity=1, rate=3000, amount=3000)],
            subtotal=3000,
            tax_rate=0,
            tax_amount=0,
            total=3000,
            currency="USD",
            status="overdue",
            due_date=_date_days_ago(12),
            notes="Auto-created from signed contract (kickoff milestone).",
            contract_id=harbor_contract_id,
            sent_at=_iso_days_ago(19),
            viewed_at=_iso_days_ago(18),
            follow_up_count=2,
            last_follow_up_at=_iso_days_ago(5),
            created_at=_iso_days_ago(19),
        ),
        Invoice(
            id=_sid("inv"),
            user_id=user_id,
            invoice_number="INV-2026-017",
            client_name="Kestrel Studio",
            client_email="hello@kestrel.example",
            line_items=[
                LineItem(description="Pitch deck template", quantity=1, rate=600, amount=600),
                LineItem(description="Icon set", quantity=2, rate=150, amount=300),
            ],
            subtotal=900,
            tax_rate=0,
            tax_amount=0,
            total=900,
            currency="USD",
            status="draft",
            due_date=_date_days_ahead(21),
            follow_up_count=0,
            created_at=_iso_days_ago(1),
        ),
    ]

    overdue = invoices[2]
    pay = overdue.payment_link

    agent_logs: list[AgentLog] = [
        AgentLog(
            id=_sid("log"),
            user_id=user_id,
            agent_type="bookkeeper",
            action="Categorized 33 transactions from uploaded CSV",
            input={"batchSize": 33, "source": "csv"},
            output={"categorized": 33, "lowConfidence": 4, "avgConfidence": 0.89},
            model_used="gemini-1.5-pro",
            tokens_used=1480,
            latency_ms=4120,
            cost_usd=0.0102,
            status="success",
            triggered_by="user",
            source_record_type="transaction",
            created_at=_iso_days_ago(34),
        ),
        AgentLog(
            id=_sid("log"),
            user_id=user_id,
            agent_type="invoice_follow_up",
            action=f"Sent gentle reminder for {overdue.invoice_number} to {overdue.client_name}",
            input={"invoiceNumber": overdue.invoice_number, "daysOverdue": 3, "attempt": 1},
            output={
                "subject": f"Quick reminder: invoice {overdue.invoice_number}",
                "body": (
                    f"Hi {overdue.client_name},\n\nThis is a friendly reminder that invoice "
                    f"{overdue.invoice_number} for $3,500.00 was due a few days ago. "
                    f"It may have simply slipped through \u2014 no worries at all if so."
                    f"\n\nYou can pay securely here: {pay}\n\nBest,\nRivera Studio"
                ),
                "delivered": True,
            },
            model_used="gemini-1.5-pro",
            tokens_used=540,
            latency_ms=2210,
            cost_usd=0.0061,
            status="success",
            triggered_by="scheduler",
            source_record_type="invoice",
            source_record_id=overdue.id,
            created_at=_iso_days_ago(13),
        ),
        AgentLog(
            id=_sid("log"),
            user_id=user_id,
            agent_type="invoice_follow_up",
            action=f"Sent firm follow-up for {overdue.invoice_number} to {overdue.client_name}",
            input={"invoiceNumber": overdue.invoice_number, "daysOverdue": 7, "attempt": 2},
            output={
                "subject": f"Payment overdue: invoice {overdue.invoice_number} ($3,500.00)",
                "body": (
                    f"Hi {overdue.client_name},\n\nI'm following up on invoice "
                    f"{overdue.invoice_number} for $3,500.00, which is now 7 days overdue. "
                    f"My earlier reminder may have been missed.\n\nCould you confirm when "
                    f"payment will be processed, or let me know if there's an issue I can "
                    f"help resolve?\n\nYou can pay securely here: {pay}\n\nThanks,\nRivera Studio"
                ),
                "delivered": True,
            },
            model_used="gemini-1.5-pro",
            tokens_used=610,
            latency_ms=2480,
            cost_usd=0.0068,
            status="success",
            triggered_by="scheduler",
            source_record_type="invoice",
            source_record_id=overdue.id,
            created_at=_iso_days_ago(9),
        ),
        AgentLog(
            id=_sid("log"),
            user_id=user_id,
            agent_type="alert_generator",
            action="Generated daily digest — 2 alerts",
            input={"window": "30d"},
            output={"alerts": ["invoice_pile_up", "deduction_opportunity"]},
            model_used="gemini-1.5-pro",
            tokens_used=720,
            latency_ms=3010,
            cost_usd=0.0079,
            status="success",
            triggered_by="scheduler",
            created_at=_iso_days_ago(1),
        ),
        AgentLog(
            id=_sid("log"),
            user_id=user_id,
            agent_type="cashflow_forecaster",
            action="Refreshed 90-day cash flow forecast",
            input={"horizonDays": 90},
            output={"confidenceScore": 0.81, "projectedBalance30d": 7480},
            model_used="gemini-1.5-pro",
            tokens_used=1190,
            latency_ms=3890,
            cost_usd=0.0094,
            status="success",
            triggered_by="scheduler",
            created_at=_iso_days_ago(1),
        ),
    ]

    alerts: list[Alert] = [
        Alert(
            id=_sid("alert"),
            user_id=user_id,
            type="invoice_pile_up",
            severity="warning",
            title="Overdue invoice needs attention",
            body=f"{overdue.client_name} is 16 days late on {overdue.invoice_number} ($3,500). Kora has sent 2 follow-ups.",
            action_label="View invoice",
            action_url="/invoices",
            read=False,
            created_at=_iso_days_ago(1),
        ),
        Alert(
            id=_sid("alert"),
            user_id=user_id,
            type="deduction_opportunity",
            severity="info",
            title="Possible missed tax deductions",
            body="Spotify Premium and a bank fee were not tagged deductible. Review them before quarter-end.",
            action_label="Review bookkeeping",
            action_url="/bookkeeping",
            read=False,
            created_at=_iso_days_ago(1),
        ),
    ]

    contracts: list[Contract] = [
        Contract(
            id=harbor_contract_id,
            user_id=user_id,
            type="freelance_agreement",
            title="Freelance Agreement — Harbor Co",
            client_name="Harbor Co",
            client_email="ops@harbor.example",
            provider_name="Rivera Studio",
            jurisdiction="US-CA",
            terms={
                "project_description": "Website redesign and brand refresh",
                "total_fee": 6000,
                "payment_schedule": "milestone",
                "milestones": [
                    {"label": "Project kickoff", "amount": 3000, "due_in_days": 7},
                    {"label": "Final delivery", "amount": 3000, "due_in_days": 45},
                ],
                "revision_rounds": 2,
            },
            content_md=(
                "# FREELANCE AGREEMENT\n\n_This document was generated by Kora AI as a starting "
                "point. It has not been reviewed by a licensed attorney._\n\n"
                '**Parties:** Rivera Studio ("Provider") and Harbor Co ("Client").\n\n'
                "## 1. Scope of Work\nWebsite redesign and brand refresh.\n\n"
                "## 2. Payment Terms\nTotal fee $6,000.00, paid in two milestones: $3,000 at "
                "kickoff and $3,000 on final delivery. Net 14 days from invoice.\n\n"
                "## 3. Revisions\nTwo rounds of revisions are included.\n\n"
                "## 4. Intellectual Property\nUpon full payment, all IP transfers to the Client.\n\n"
                "## 5. Signatures\nProvider: ____________  Client: ____________\n"
            ),
            section_explanations={
                "1": "What work you're agreeing to deliver.",
                "2": "When and how much you get paid.",
                "3": "How many revision rounds are included before extra charges apply.",
                "4": "Who owns the work once it's paid for.",
                "5": "Where both parties sign.",
            },
            status="signed",
            signed_at=_iso_days_ago(20),
            created_at=_iso_days_ago(22),
        ),
    ]

    # --- Butler: clients, engagements, notes, proposals, retainers ----------
    # Names match the invoice/contract client_name values so the name-based
    # linkage (clients ↔ invoices/contracts) lights up in the demo.
    harbor_id = _sid("cli")
    bluelabel_id = _sid("cli")
    acme_id = _sid("cli")
    nova_id = _sid("cli")

    clients: list[Client] = [
        Client(
            id=harbor_id,
            user_id=user_id,
            name="Harbor Co",
            email="ops@harbor.example",
            company="Harbor Co",
            industry="E-commerce",
            client_type="company",
            status="active",
            what_we_do="Full website redesign and brand refresh.",
            health_score=48,
            health_label="needs_attention",
            health_updated_at=_iso_days_ago(1),
            last_activity_at=_iso_days_ago(5),
            created_at=_iso_days_ago(24),
        ),
        Client(
            id=bluelabel_id,
            user_id=user_id,
            name="Blue Label LLC",
            email="accounts@bluelabel.example",
            company="Blue Label LLC",
            industry="Marketing",
            client_type="agency",
            status="active",
            what_we_do="Monthly design + motion retainer.",
            health_score=62,
            health_label="at_risk",
            health_updated_at=_iso_days_ago(1),
            last_activity_at=_iso_days_ago(9),
            created_at=_iso_days_ago(70),
        ),
        Client(
            id=acme_id,
            user_id=user_id,
            name="Acme Corp",
            email="ap@acme.example",
            company="Acme Corp",
            industry="Technology",
            client_type="company",
            status="active",
            what_we_do="Brand identity system and ongoing design support.",
            health_score=92,
            health_label="on_track",
            health_updated_at=_iso_days_ago(1),
            last_activity_at=_iso_days_ago(4),
            created_at=_iso_days_ago(90),
        ),
        Client(
            id=nova_id,
            user_id=user_id,
            name="Nova Agency",
            email="billing@nova.example",
            company="Nova Agency",
            industry="Marketing",
            client_type="agency",
            status="active",
            what_we_do="Landing page design for client campaigns.",
            health_score=80,
            health_label="on_track",
            health_updated_at=_iso_days_ago(1),
            last_activity_at=_iso_days_ago(6),
            created_at=_iso_days_ago(40),
        ),
        Client(
            id=_sid("cli"),
            user_id=user_id,
            name="Sarah Kim",
            email="sarah@kimcreative.example",
            industry="Writing",
            client_type="individual",
            status="prospect",
            what_we_do="Potential brand copywriting collaboration.",
            health_score=70,
            health_label="on_track",
            health_updated_at=_iso_days_ago(1),
            last_activity_at=_iso_days_ago(26),
            created_at=_iso_days_ago(30),
        ),
    ]

    engagements: list[Engagement] = [
        Engagement(
            id=_sid("eng"),
            user_id=user_id,
            client_id=harbor_id,
            title="Website redesign",
            description_md="Full redesign + brand refresh, two milestones.",
            engagement_type="project",
            status="at_risk",
            start_date=_date_days_ago(22),
            target_end_date=_date_days_ahead(20),
            budget=6000,
            value_delivered=3000,
            contract_id=harbor_contract_id,
            created_at=_iso_days_ago(22),
            updated_at=_iso_days_ago(5),
        ),
        Engagement(
            id=_sid("eng"),
            user_id=user_id,
            client_id=bluelabel_id,
            title="Monthly design + motion retainer",
            description_md="Ongoing creative retainer.",
            engagement_type="retainer",
            status="active",
            start_date=_date_days_ago(70),
            budget=3500,
            value_delivered=10500,
            created_at=_iso_days_ago(70),
            updated_at=_iso_days_ago(9),
        ),
        Engagement(
            id=_sid("eng"),
            user_id=user_id,
            client_id=acme_id,
            title="Brand identity system",
            description_md="Logo, type, guidelines.",
            engagement_type="project",
            status="done",
            start_date=_date_days_ago(88),
            target_end_date=_date_days_ago(50),
            budget=4200,
            value_delivered=4200,
            created_at=_iso_days_ago(88),
            updated_at=_iso_days_ago(50),
        ),
    ]

    client_notes: list[ClientNote] = [
        ClientNote(
            id=_sid("note"),
            user_id=user_id,
            client_id=harbor_id,
            engagement_id=engagements[0].id,
            note_type="blocker",
            content_md="Waiting on final copy from client before the second milestone.",
            is_ai_generated=False,
            created_at=_iso_days_ago(5),
        ),
        ClientNote(
            id=_sid("note"),
            user_id=user_id,
            client_id=bluelabel_id,
            note_type="update",
            content_md="Delivered April motion set; May retainer invoice overdue.",
            is_ai_generated=False,
            created_at=_iso_days_ago(9),
        ),
    ]

    proposals: list[Proposal] = [
        Proposal(
            id=_sid("prop"),
            user_id=user_id,
            client_id=nova_id,
            title="Q3 Campaign Landing Pages",
            proposal_number="PROP-2026-001",
            scope_md="Design and build three campaign landing pages.",
            content_md=(
                "# Proposal — Q3 Campaign Landing Pages\n\n## 1. Executive Summary\n"
                "A focused engagement to ship three high-converting landing pages for Nova "
                "Agency's Q3 campaigns.\n\n## 2. Scope of Work\nDesign and build three "
                "responsive landing pages.\n\n## 5. Investment\nTotal: $3,600 (fixed).\n"
            ),
            total_amount=3600,
            currency="USD",
            pricing_type="fixed",
            payment_terms="50% upfront, 50% on completion",
            status="sent",
            valid_until=_date_days_ahead(20),
            sent_at=_iso_days_ago(3),
            created_at=_iso_days_ago(4),
        ),
    ]

    retainers: list[Retainer] = [
        Retainer(
            id=_sid("ret"),
            user_id=user_id,
            client_id=bluelabel_id,
            title="Monthly design + motion — Blue Label",
            amount=3500,
            currency="USD",
            billing_cycle="monthly",
            start_date=_date_days_ago(70),
            next_invoice_date=_date_days_ahead(2),
            status="active",
            auto_invoice=True,
            created_at=_iso_days_ago(70),
        ),
    ]

    return {
        "users": [user],
        "transactions": transactions,
        "invoices": invoices,
        "agent_logs": agent_logs,
        "alerts": alerts,
        "contracts": contracts,
        "clients": clients,
        "engagements": engagements,
        "client_notes": client_notes,
        "proposals": proposals,
        "retainers": retainers,
    }
