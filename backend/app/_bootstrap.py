"""Process bootstrap — must be imported before any outbound HTTPS client.

On corporate networks an intercepting proxy re-signs external TLS with a private
root CA. Python's bundled certifi store doesn't trust it, so Supabase / Stripe /
Resend calls fail with CERTIFICATE_VERIFY_FAILED. `truststore` makes Python use
the OS (Windows) trust store, which already contains the corporate root CA — one
line that fixes TLS for every external integration.
"""

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover - truststore optional / non-corporate envs
    pass
