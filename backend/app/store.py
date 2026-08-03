from __future__ import annotations

import uuid

from .config import settings

# Data-access dispatcher. Selects the backend once at import based on
# KORA_DATA_BACKEND and re-exports its functions, so the rest of the app keeps
# calling `store.<fn>(...)` unchanged whether running on the in-memory store or
# Supabase. IDs are UUIDs (valid for Supabase's UUID columns and fine in memory).

if settings.KORA_DATA_BACKEND == "supabase":
    from .backends import supabase_store as _b
else:
    from .backends import memory_store as _b

from .services import pii_fields as _pii


def uid(prefix: str = "") -> str:
    return str(uuid.uuid4())


# Re-export the backend surface (PII fields encrypted at this boundary).
def get_user(user_id: str):
    return _pii.decrypt_user(_b.get_user(user_id))


def get_user_by_email(email: str):
    return _pii.decrypt_user(_b.get_user_by_email(email))


def get_user_by_stripe_customer(customer_id: str):
    return _pii.decrypt_user(_b.get_user_by_stripe_customer(customer_id))


def update_user(user_id: str, patch: dict):
    return _pii.decrypt_user(_b.update_user(user_id, _pii.encrypt_user_patch(patch)))


def verify_token(token: str):
    return _pii.decrypt_user(_b.verify_token(token))


list_transactions = _b.list_transactions
insert_transactions = _b.insert_transactions
upsert_transactions = _b.upsert_transactions
update_transaction = _b.update_transaction


def list_invoices(user_id: str):
    return [_pii.decrypt_invoice(i) for i in _b.list_invoices(user_id)]


def get_invoice(user_id: str, invoice_id: str):
    return _pii.decrypt_invoice(_b.get_invoice(user_id, invoice_id))


def insert_invoice(invoice):
    return _pii.decrypt_invoice(_b.insert_invoice(_pii.encrypt_invoice(invoice)))


def update_invoice(user_id: str, invoice_id: str, patch: dict):
    return _pii.decrypt_invoice(_b.update_invoice(user_id, invoice_id, _pii.encrypt_invoice_patch(patch)))


update_invoice_pdf = _b.update_invoice_pdf
update_invoice_email = _b.update_invoice_email
next_invoice_number = _b.next_invoice_number

list_agent_logs = _b.list_agent_logs
list_all_agent_logs = _b.list_all_agent_logs
insert_agent_log = _b.insert_agent_log

list_alerts = _b.list_alerts
insert_alert = _b.insert_alert
alert_fired_recently = _b.alert_fired_recently
mark_alert_read = _b.mark_alert_read

list_contracts = _b.list_contracts
get_contract = _b.get_contract
insert_contract = _b.insert_contract
update_contract = _b.update_contract

list_manager_tasks = _b.list_manager_tasks
get_manager_task = _b.get_manager_task
find_open_manager_task = _b.find_open_manager_task
insert_manager_task = _b.insert_manager_task
update_manager_task = _b.update_manager_task

get_manager_memory = _b.get_manager_memory
set_manager_memory = _b.set_manager_memory


# Butler: clients / engagements / notes


def list_clients(user_id: str, status: str | None = None):
    return [_pii.decrypt_client(c) for c in _b.list_clients(user_id, status)]


def get_client(user_id: str, client_id: str):
    return _pii.decrypt_client(_b.get_client(user_id, client_id))


def insert_client(client):
    return _pii.decrypt_client(_b.insert_client(_pii.encrypt_client(client)))


def update_client(user_id: str, client_id: str, patch: dict):
    return _pii.decrypt_client(_b.update_client(user_id, client_id, _pii.encrypt_client_patch(patch)))


delete_client = _b.delete_client

list_engagements = _b.list_engagements
get_engagement = _b.get_engagement
insert_engagement = _b.insert_engagement
update_engagement = _b.update_engagement

list_client_notes = _b.list_client_notes
insert_client_note = _b.insert_client_note

# Task ledger (canonical record of client work; Notion mirrors via external_ref)
list_tasks = _b.list_tasks
get_task = _b.get_task
find_task_by_source_ref = _b.find_task_by_source_ref
find_task_by_external_ref = _b.find_task_by_external_ref
insert_task = _b.insert_task
update_task = _b.update_task
delete_task = _b.delete_task

# Story layer (children of tasks; ADR-0001)
list_stories = _b.list_stories
get_story = _b.get_story
insert_story = _b.insert_story
update_story = _b.update_story
delete_story = _b.delete_story
delete_stories_for_task = _b.delete_stories_for_task

# Butler: quick captures
list_captures = _b.list_captures
get_capture = _b.get_capture
insert_capture = _b.insert_capture
update_capture = _b.update_capture

# Butler: proposals
list_proposals = _b.list_proposals
get_proposal = _b.get_proposal
insert_proposal = _b.insert_proposal
update_proposal = _b.update_proposal

# Butler: retainers
list_retainers = _b.list_retainers
get_retainer = _b.get_retainer
insert_retainer = _b.insert_retainer
update_retainer = _b.update_retainer

# Butler: briefing continuity
get_butler_memory = _b.get_butler_memory
set_butler_memory = _b.set_butler_memory

# Client view cache (M3 PM agent fan-out)
get_client_view = _b.get_client_view
upsert_client_view = _b.upsert_client_view
delete_client_view = _b.delete_client_view

# Playbook (Agent Intelligence)
upsert_playbook_entry = _b.upsert_playbook_entry
get_playbook_entries = _b.get_playbook_entries
get_playbook_corrections = _b.get_playbook_corrections
get_playbook_for_client = _b.get_playbook_for_client
update_playbook_entry = _b.update_playbook_entry
delete_playbook_entry = _b.delete_playbook_entry
decay_playbook_entries = _b.decay_playbook_entries

# Graph memory (kg_nodes / kg_edges)
upsert_kg_node = _b.upsert_kg_node
upsert_kg_edge = _b.upsert_kg_edge
get_kg_nodes = _b.get_kg_nodes
get_kg_edges = _b.get_kg_edges
delete_kg_for_user = _b.delete_kg_for_user

# Semantic memory (agent_memory)
upsert_agent_memory = _b.upsert_agent_memory
get_agent_memory = _b.get_agent_memory
delete_agent_memory_for_user = _b.delete_agent_memory_for_user
delete_agent_memory = _b.delete_agent_memory
# M10 — pgvector ANN search (Supabase-only; mock backend returns [])
vector_search_agent_memory = _b.vector_search_agent_memory

# Notion connection (task ledger mirror)
upsert_notion_connection = _b.upsert_notion_connection
get_notion_connection = _b.get_notion_connection
update_notion_connection = _b.update_notion_connection
delete_notion_connection = _b.delete_notion_connection

# Stripe Connect
upsert_stripe_connection = _b.upsert_stripe_connection
get_stripe_connection = _b.get_stripe_connection
update_stripe_connection = _b.update_stripe_connection
delete_stripe_connection = _b.delete_stripe_connection

# M9 — GDPR/CCPA
list_user_data = _b.list_user_data
delete_user_data = _b.delete_user_data
record_deletion = _b.record_deletion
get_google_token = _b.get_google_token
create_import_job = _b.create_import_job
get_import_job = _b.get_import_job
update_import_job = _b.update_import_job
list_deletion_log = _b.list_deletion_log
