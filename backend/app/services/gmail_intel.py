from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from ..config import settings
from ..utils.security import sanitize_prompt_input
from . import agent_logger
from .google_auth import get_user_credentials
from .vertex_ai import generate_with_retry, get_ai


def _db():
    from supabase import create_client

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


# Free/public providers — never match a client by these domains, or a domain
# query like `from:gmail.com` would match unrelated people.
_PUBLIC_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "ymail.com",
    "yahoo.co.uk",
    "outlook.com",
    "hotmail.com",
    "hotmail.co.uk",
    "live.com",
    "msn.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "gmx.com",
    "gmx.net",
    "zoho.com",
    "mail.com",
    "yandex.com",
    "fastmail.com",
}

# Deeper-analysis caps (Feature 3). Bounded so token cost stays predictable.
_MAX_THREADS_FETCH = 15  # thread refs pulled from Gmail
_MAX_THREADS_ANALYZE = 5  # threads read in full by the LLM
_MAX_MSGS_PER_THREAD = 3  # most-recent messages read per analyzed thread
_MAX_BODY_CHARS = 4000  # per-message body cap
_MAX_COMBINED_CHARS = 8000  # total text sent to the LLM


# ─── Client → search-term helpers (Feature 1) ────────────────────────────────


def _domain_of(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return (email.rsplit("@", 1)[-1] or "").strip().lower() or None


def _client_search_terms(client: dict) -> tuple[list[str], list[str]]:
    """Return (addresses, domains) that identify this client in Gmail.

    Combines the primary `email` with any `contact_emails`, plus the corporate
    domain of each (public providers excluded). Domain matching is what lets the
    agent capture mail from a client's second address or a colleague at the same
    company — the biggest gap in exact-address-only matching."""
    addresses: list[str] = []
    raw = [client.get("email")] + list(client.get("contact_emails") or [])
    for e in raw:
        if e and "@" in e:
            e = e.strip().lower()
            if e not in addresses:
                addresses.append(e)

    domains: list[str] = []
    for e in addresses:
        d = _domain_of(e)
        if d and d not in _PUBLIC_EMAIL_DOMAINS and d not in domains:
            domains.append(d)
    return addresses, domains


def _build_gmail_query(addresses: list[str], domains: list[str]) -> str:
    """Gmail search matching any known address or corporate domain, either
    direction. `from:acme.com` matches anyone @acme.com."""
    terms: list[str] = []
    for a in addresses:
        terms += [f"from:{a}", f"to:{a}"]
    for d in domains:
        terms += [f"from:{d}", f"to:{d}"]
    return " OR ".join(terms)


def _get_message_body(service, msg_id: str) -> str:
    """Fetch + extract the plain-text body of one message (best-effort). Used by
    the deeper-analysis path so the LLM reads real content, not just snippets."""
    try:
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    except Exception:
        return ""

    def _walk(payload) -> str:
        mime = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data")
        if mime == "text/plain" and data:
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
            except Exception:
                return ""
        out = ""
        for part in payload.get("parts", []) or []:
            out += _walk(part)
            if len(out) > _MAX_BODY_CHARS:
                break
        return out

    return _walk(msg.get("payload", {}))[:_MAX_BODY_CHARS].strip()


# ─── Main entry point ────────────────────────────────────────────────────────


def sync_client_email_intel(user_id: str, force_refresh: bool = False) -> None:
    """Sync Gmail intelligence for all active clients with an email address.

    Triggered on-demand (POST /api/gmail/sync), by the daily scheduler
    (POST /api/gmail/run), and by real-time push (POST /api/gmail/push).
    Silently skips when Google is not connected.
    """
    if not settings.SUPABASE_URL:
        return

    creds = get_user_credentials(user_id)
    if not creds:
        return

    from googleapiclient.discovery import build

    db = _db()
    # select("*") so the new contact_emails column is included when present and
    # tolerated when the migration hasn't been applied yet.
    clients = db.table("clients").select("*").eq("user_id", user_id).eq("status", "active").not_.is_("email", "null").execute().data

    service = build("gmail", "v1", credentials=creds)
    for client in clients:
        try:
            _process_client_threads(user_id, client, service, db, force_refresh)
        except Exception as exc:
            print(f"[gmail-intel] failed for {client.get('name')}: {exc}")


def _process_client_threads(user_id: str, client: dict, service, db, force_refresh: bool) -> None:
    client_id = client["id"]
    client_name = client["name"]

    addresses, domains = _client_search_terms(client)
    if not addresses:
        return
    query = _build_gmail_query(addresses, domains)

    if not force_refresh:
        cache = db.table("email_intel_cache").select("id, processed_at, last_message_id").eq("user_id", user_id).eq("client_id", client_id).execute().data

        if cache and cache[0].get("processed_at"):
            processed = datetime.fromisoformat(cache[0]["processed_at"].replace("Z", "+00:00"))
            if processed.tzinfo is None:
                processed = processed.replace(tzinfo=timezone.utc)
            age_secs = (datetime.now(timezone.utc) - processed).total_seconds()
            if age_secs < 86400:
                if not _has_new_messages(service, query, cache[0].get("last_message_id")):
                    return

    threads = _fetch_client_threads(service, query)
    if not threads:
        return

    primary_email = addresses[0]
    intel = _analyze_threads(user_id, client_name, primary_email, addresses, threads, service)

    last_msg_id = None
    if threads:
        msgs = threads[0].get("messages", [])
        if msgs:
            last_msg_id = msgs[-1].get("id")

    now = datetime.now(timezone.utc)
    db.table("email_intel_cache").upsert(
        {
            "user_id": user_id,
            "client_id": client_id,
            "client_name": client_name,
            "thread_count": len(threads),
            "last_message_id": last_msg_id,
            "last_contact_days": intel.get("last_contact_days"),
            "last_contact_direction": intel.get("last_contact_direction"),
            "sentiment": intel.get("sentiment"),
            "relationship_health": intel.get("relationship_health"),
            "summary": intel.get("summary"),
            "action_needed": intel.get("action_needed", False),
            "action_description": intel.get("action_description"),
            "commitments_pending": intel.get("commitments_pending", []),
            "financial_mentions": intel.get("financial_mentions", []),
            "open_questions": intel.get("open_questions", []),
            "processed_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        },
        on_conflict="user_id,client_id",
    ).execute()
    try:
        from .playbook import observe_email_intel

        observe_email_intel(user_id, client_id, intel)
    except Exception:
        pass

    # Semantic memory — make this client's email summary recallable by meaning.
    try:
        from .memory_recall import remember

        summary = (intel.get("summary") or "").strip()
        if summary:
            remember(
                user_id,
                "email_intel",
                f"{client_name}: {summary}",
                client_id=client_id,
                ref_type="email_intel_cache",
                ref_id=str(client_id),
                salience=0.6,
                source="email",
            )
    except Exception:
        pass

    if (intel.get("last_contact_days") or 999) < 7:
        db.table("clients").update(
            {
                "last_activity_at": now.isoformat(),
            }
        ).eq("id", client_id).execute()


def _fetch_client_threads(service, query: str) -> list:
    result = (
        service.users()
        .threads()
        .list(
            userId="me",
            q=query,
            maxResults=_MAX_THREADS_FETCH,
        )
        .execute()
    )
    thread_refs = result.get("threads", [])
    if not thread_refs:
        return []
    full_threads = []
    for ref in thread_refs[:_MAX_THREADS_FETCH]:
        thread = (
            service.users()
            .threads()
            .get(
                userId="me",
                id=ref["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            .execute()
        )
        full_threads.append(thread)
    return full_threads


def _has_new_messages(service, query: str, last_known_id: str | None) -> bool:
    if not last_known_id:
        return True
    result = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=1,
        )
        .execute()
    )
    messages = result.get("messages", [])
    if not messages:
        return False
    return messages[0]["id"] != last_known_id


def _analyze_threads(
    user_id: str,
    client_name: str,
    client_email: str,
    addresses: list[str],
    threads: list,
    service,
) -> dict:
    # Build the LLM context from full message bodies (Feature 3), not just
    # snippets — richer signal, bounded by the caps above.
    thread_summaries = []
    for thread in threads[:_MAX_THREADS_ANALYZE]:
        parts = []
        for msg in thread.get("messages", [])[-_MAX_MSGS_PER_THREAD:]:
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            body = _get_message_body(service, msg["id"]) or msg.get("snippet", "")
            parts.append(f"[{headers.get('Date', '')}] From: {headers.get('From', '')}\n{body}")
        if parts:
            thread_summaries.append("\n---\n".join(parts))

    if not thread_summaries:
        return {"sentiment": "neutral", "relationship_health": "unknown"}

    # Days since last message + direction (deterministic, not LLM).
    last_contact_days = 999
    last_contact_direction = "unknown"
    last_msg = threads[0].get("messages", [{}])[-1]
    last_hdrs = {h["name"]: h["value"] for h in last_msg.get("payload", {}).get("headers", [])}
    try:
        last_dt = parsedate_to_datetime(last_hdrs.get("Date", ""))
        last_contact_days = (datetime.now(last_dt.tzinfo) - last_dt).days
        from_email = (last_hdrs.get("From", "") or "").lower()
        last_contact_direction = "from_client" if any(a in from_email for a in addresses) else "from_me"
    except Exception:
        pass

    combined = sanitize_prompt_input("\n\n===\n\n".join(thread_summaries)[:_MAX_COMBINED_CHARS])

    prompt = f"""Analyze these email threads between a business owner and their client.
Extract structured business intelligence.

CLIENT: {client_name} ({client_email})
DAYS SINCE LAST MESSAGE: {last_contact_days}
LAST MESSAGE DIRECTION: {last_contact_direction}

EMAIL THREADS (most recent messages, full text):
<emails>
{combined}
</emails>

Return ONLY valid JSON:
{{
  "sentiment": "positive|neutral|cautious|strained",
  "relationship_health": "strong|healthy|needs_attention|at_risk",
  "summary": "2 sentences: current state of this client relationship",
  "action_needed": true or false,
  "action_description": "specific action if needed, null if not",
  "commitments_pending": [{{"who": "me|client", "what": "commitment", "mentioned_date": "date or null"}}],
  "open_questions": ["unanswered question or unresolved item"],
  "financial_mentions": [{{"type": "invoice|payment|quote|refund", "amount": null, "context": "brief"}}],
  "suggested_reply": "one sentence draft if action_needed, null otherwise"
}}

Be conservative. If the threads are too brief, return neutral with no action."""

    intel = {"sentiment": "neutral", "relationship_health": "unknown"}
    latency_ms = model_used = tokens_used = cost_usd = None

    try:
        ai = get_ai()
        call = generate_with_retry(
            lambda: ai.analyze_email_threads(
                {
                    "prompt": prompt,
                    "client_name": client_name,
                }
            )
        )
        latency_ms = call.latency_ms
        model_used = call.model_used
        tokens_used = call.tokens_used
        cost_usd = call.cost_usd
        raw = call.data if isinstance(call.data, str) else json.dumps(call.data)
        intel = json.loads(raw.replace("```json", "").replace("```", "").strip())
    except Exception as exc:
        print(f"[gmail-intel] analysis failed for {client_name}: {exc}")

    intel["last_contact_days"] = last_contact_days
    intel["last_contact_direction"] = last_contact_direction

    agent_logger.log_action(
        user_id=user_id,
        agent_type="butler_gmail",
        action=f"Analyzed email threads for {client_name}",
        input={"client_email": client_email, "addresses_matched": len(addresses), "threads_processed": len(thread_summaries)},
        output={"sentiment": intel.get("sentiment"), "action_needed": intel.get("action_needed")},
        model_used=model_used or "deterministic",
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        triggered_by="scheduler",
        source_record_type="email_intel_cache",
    )
    return intel


# ─── Real-time push: Gmail watch + Pub/Sub (Feature 4) ───────────────────────


def register_gmail_watch(user_id: str) -> dict:
    """Register a Gmail push-notification watch on INBOX → the Pub/Sub topic.

    Gmail then publishes to the topic on every mailbox change; the topic's push
    subscription hits POST /api/gmail/push. Watches expire after ~7 days and must
    be re-registered. Requires GMAIL_PUBSUB_TOPIC configured and the topic granted
    publish rights to gmail-api-push@system.gserviceaccount.com."""
    if not settings.GMAIL_PUBSUB_TOPIC:
        raise ValueError("GMAIL_PUBSUB_TOPIC not configured")
    creds = get_user_credentials(user_id)
    if not creds:
        raise ValueError("Google account not connected")

    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds)
    resp = (
        service.users()
        .watch(
            userId="me",
            body={
                "topicName": settings.GMAIL_PUBSUB_TOPIC,
                "labelIds": ["INBOX"],
                "labelFilterBehavior": "INCLUDE",
            },
        )
        .execute()
    )

    history_id = resp.get("historyId")
    expiration = resp.get("expiration")  # ms-epoch string
    if settings.SUPABASE_URL:
        exp_iso = None
        if expiration:
            exp_iso = datetime.fromtimestamp(int(expiration) / 1000, tz=timezone.utc).isoformat()
        try:
            _db().table("google_connections").update(
                {
                    "watch_history_id": str(history_id) if history_id else None,
                    "watch_expiration": exp_iso,
                }
            ).eq("user_id", user_id).execute()
        except Exception as exc:
            print(f"[gmail-watch] could not persist watch state: {exc}")

    return {"historyId": history_id, "expiration": expiration}


def renew_watch_if_configured(user_id: str) -> None:
    """Best-effort re-registration of the Gmail push watch (they expire ~7 days).
    Safe no-op when push isn't configured or the user isn't connected."""
    if not settings.GMAIL_PUBSUB_TOPIC:
        return
    try:
        register_gmail_watch(user_id)
    except Exception as exc:
        print(f"[gmail-watch] renew failed for {user_id}: {exc}")


def handle_push_notification(email_address: str) -> None:
    """Pub/Sub webhook handler: map the mailbox email to a Kora user and refresh
    that user's client email intel. Kept cheap + idempotent (the per-client 24h
    cache + new-message check prevents redundant LLM calls)."""
    if not (settings.SUPABASE_URL and email_address):
        return
    rows = _db().table("google_connections").select("user_id").eq("google_email", email_address).eq("connected", True).execute().data
    if not rows:
        return
    try:
        sync_client_email_intel(rows[0]["user_id"], force_refresh=True)
    except Exception as exc:
        print(f"[gmail-push] sync failed for {email_address}: {exc}")
