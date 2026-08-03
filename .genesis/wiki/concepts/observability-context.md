# Observability context (M11)

Three propagation channels, one correlation id.

## Channels

| Channel | Lifetime | Writer | Reader |
|---|---|---|---|
| `request.state.request_id` | one ASGI request | `AccessLogMiddleware` | nothing else (debugging only) |
| `request.state.user_id` | one ASGI request | `get_current_user` | `AccessLogMiddleware` |
| `utils.request_context.current_request_id()` | one task | `AccessLogMiddleware` (`begin_request_context`) | any service-layer code (e.g. `agent_logger`) |
| `utils.request_context.current_user_id()` | one task | `set_user_id()` (called from `get_current_user`) | `agent_logger` (via the JSONB envelope) |
| `agent_logs.output["_request_id"]` | one row | `agent_logger` | anyone reading logs |
| HTTP header `X-Request-ID` (response) | one response | `AccessLogMiddleware` | the caller (and their support ticket) |

## Why two parallel slots (state + contextvar)?

Starlette's `BaseHTTPMiddleware.dispatch()` runs `await call_next(...)` inside a
**spawned anyio task**. ContextVars set on the outer task do not propagate to
the spawned task — that is a documented Python behaviour, not a bug to work
around. Pure ASGI middleware (`AccessLogMiddleware`) does not have this issue
because every `await` is on the same task.

For `get_current_user` (a FastAPI dependency that runs **inside** the spawned
task), we therefore write the user id to BOTH:

* the `ContextVar` (visible to other service code in the same task),
* `request.state.user_id` (which Starlette guarantees is shared across the
  middleware boundary — the access-log middleware reads this).

## The PII scrubber

`app.utils.pii_scrubber.scrub(value)` is the single function every log line
walks through. The catalog lives at the bottom of that module — eight patterns
plus a secret-key deny-list, both pinned by `tests/observability/test_pii_scrubber.py`.

When adding a new secret-shaped token to the catalog:

1. Add the regex to `_PATTERNS` in `app/utils/pii_scrubber.py`.
2. Add a corpus line to `tests/observability/test_pii_scrubber.py`.
3. Run the suite — the catalog pin (`test_secret_keys_catalog_is_explicit` +
   `test_pattern_catalog_has_minimum_coverage`) forces you to update the test
   if you remove a key.

## End-to-end correlation test

`tests/observability/test_end_to_end_trace.py::test_single_request_three_correlated_artefacts`
spins up a minimal FastAPI app with the real `AccessLogMiddleware` and a probe
route that calls `agent_logger.log_action`. It then asserts that the SAME
`request_id` shows up in:

1. the response's `X-Request-ID` header
2. the `kora.access` JSON line (captured via `caplog`)
3. the `agent_logs` row's `output._request_id`

If any of the three channels drift, this test fails — which is the gate.

## What M11 deliberately did NOT add

* **OpenTelemetry SDK / OTLP exporter.** Out of scope per G0; left as a
  follow-up candidate (`observability-otel`) so the structured lines we emit
  can be scraped by an OTel collector without code changes.
* **A new `agent_logs` column.** `request_id` rides inside the existing
  `output` JSONB envelope using the same `_cost_usd` / `_provider_name`
  round-trip pattern already used by other agent metadata. This means:
  * no DB migration
  * no RLS touch
  * the legacy /api/agents/log JSON shape is unchanged
* **prometheus_client.** Same reasoning — log lines can be scraped; not a
  spike goal.
* **Per-route tracing overrides.** One size fits all — every request emits one
  line. Per-route sampling (e.g. drop `/health`) is a follow-up.

## See also

* `.genesis/checkpoints/M11.md` — the build trail
* `app/middleware/access_log.py` — the middleware
* `app/utils/pii_scrubber.py` — the scrubber
* `app/utils/request_context.py` — the contextvar module
