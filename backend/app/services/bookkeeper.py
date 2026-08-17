from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .. import store
from ..models import Transaction
from ..utils.csv_parser import ParsedRow
from ..utils.security import safe_sanitize
from . import agent_logger
from .cross_module import on_reconciliation_done, reconcile_payments
from .vertex_ai import generate_with_retry, get_ai

BATCH_SIZE = 50
LOW_CONFIDENCE = 0.7


@dataclass
class IngestResult:
    inserted: int
    duplicates_skipped: int
    low_confidence: int
    avg_confidence: float
    reconciled: int = 0


def ingest_transactions(user_id: str, currency: str, rows: list[ParsedRow]) -> IngestResult:
    """Insert raw rows, AI-categorize in batches of 50, persist + log
    (SKILL.md §5 Module 2)."""
    now = datetime.now(timezone.utc).isoformat()
    candidate = [
        Transaction(
            id=store.uid("tx"),
            user_id=user_id,
            date=r.date,
            description=r.description,
            amount=r.amount,
            currency=currency,
            type=r.type,
            source="csv",
            ai_categorized=False,
            raw_text=r.description,
            created_at=now,
        )
        for r in rows
    ]

    inserted = store.insert_transactions(candidate)
    duplicates = len(candidate) - len(inserted)

    ai = get_ai()
    confidence_sum = 0.0
    low_conf = 0

    for i in range(0, len(inserted), BATCH_SIZE):
        batch = inserted[i : i + BATCH_SIZE]
        items = [
            {
                "id": t.id,
                "date": t.date,
                # sanitize user-supplied description before it enters the prompt
                "description": safe_sanitize(t.description, max_len=500),
                "amount": t.amount,
            }
            for t in batch
        ]
        try:
            from .playbook import apply_corrections_before_llm

            already_corrected, items = apply_corrections_before_llm(user_id, items)
            # Write corrected categories back to Transaction objects in batch.
            corrected_by_id = {d["id"]: d for d in already_corrected if isinstance(d, dict)}
            for t in batch:
                if t.id in corrected_by_id:
                    t.category = corrected_by_id[t.id].get("category", t.category)
                    t.ai_categorized = True
                    t.ai_confidence = 1.0
        except Exception:
            already_corrected = []
        try:
            call = generate_with_retry(lambda: ai.categorize_transactions(items))
            by_id = {r["id"]: r for r in call.data}
            for t in batch:
                res = by_id.get(t.id)
                if not res:
                    continue
                t.category = res["category"]
                t.subcategory = res["subcategory"]
                t.tax_deductible = res["tax_deductible"]
                t.ai_confidence = res["confidence"]
                t.ai_categorized = True
                confidence_sum += res["confidence"]
                if res["confidence"] < LOW_CONFIDENCE:
                    low_conf += 1

            agent_logger.log_action(
                user_id=user_id,
                agent_type="bookkeeper",
                action=f"Categorized {len(batch)} transactions from uploaded CSV",
                input={"batchSize": len(batch), "descriptions": [t.description for t in batch[:5]]},
                output={
                    "categorized": len(call.data),
                    "lowConfidence": sum(1 for r in call.data if r["confidence"] < LOW_CONFIDENCE),
                    "sample": call.data[:5],
                },
                model_used=call.model_used,
                tokens_used=call.tokens_used,
                latency_ms=call.latency_ms,
                cost_usd=call.cost_usd,
                triggered_by="user",
                source_record_type="transaction",
            )
        except Exception as exc:
            # Graceful degradation (SKILL.md §17): flag batch, still log error.
            for t in batch:
                t.category = "other_income" if t.type == "income" else "other_expense"
                t.ai_confidence = 0
                t.ai_categorized = False
            low_conf += len(batch)
            agent_logger.log_action(
                user_id=user_id,
                agent_type="bookkeeper",
                action=f"Categorization failed for {len(batch)} transactions, flagged for review",
                input={"batchSize": len(batch)},
                output={"error": str(exc)},
                status="error",
                error_message=str(exc),
                triggered_by="user",
                source_record_type="transaction",
            )

    # Persist categories/confidence (no-op in memory; writes to Supabase).
    if inserted:
        store.upsert_transactions(inserted)

    # Cross-module: see if any newly-imported income settles an open invoice.
    reconciled = 0
    if inserted:
        try:
            recon_result = reconcile_payments(user_id, inserted, triggered_by="cross_module")
            reconciled = recon_result.get("matched", 0)
            # Chain: refresh cashflow if any payments were matched.
            try:
                on_reconciliation_done(user_id, recon_result)
            except Exception as exc:
                print(f"[bookkeeper] post-reconcile chain failed: {exc}")
        except Exception as exc:  # never fail an upload because reconciliation hiccuped
            print(f"[bookkeeper] reconciliation skipped: {exc}")

    avg = round(confidence_sum / len(inserted), 2) if inserted else 0.0
    return IngestResult(len(inserted), duplicates, low_conf, avg, reconciled)


def recategorize_uncategorized(user_id: str, max_txns: int = 50) -> int:
    """Re-run AI categorization over transactions that were never successfully
    categorized (e.g. an upload where the AI call failed). Safe/reversible — the
    supervisor runs this automatically. Returns how many were categorized."""
    pending = [t for t in store.list_transactions(user_id) if not t.ai_categorized][:max_txns]
    if not pending:
        return 0
    ai = get_ai()
    items = [{"id": t.id, "date": t.date, "description": safe_sanitize(t.description, max_len=500), "amount": t.amount} for t in pending]
    try:
        call = generate_with_retry(lambda: ai.categorize_transactions(items))
    except Exception:
        return 0
    by_id = {r["id"]: r for r in call.data}
    updated = []
    for t in pending:
        r = by_id.get(t.id)
        if not r:
            continue
        t.category = r["category"]
        t.subcategory = r["subcategory"]
        t.tax_deductible = r["tax_deductible"]
        t.ai_confidence = r["confidence"]
        t.ai_categorized = True
        updated.append(t)
    if updated:
        store.upsert_transactions(updated)
        agent_logger.log_action(
            user_id=user_id,
            agent_type="bookkeeper",
            action=f"Auto-categorized {len(updated)} transaction(s) during manager review",
            input={"count": len(updated)},
            output={"categorized": len(updated)},
            model_used=call.model_used,
            tokens_used=call.tokens_used,
            latency_ms=call.latency_ms,
            cost_usd=call.cost_usd,
            triggered_by="cross_module",
            source_record_type="transaction",
        )
    return len(updated)
