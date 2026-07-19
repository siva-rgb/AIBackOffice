---
name: kora-security-privacy
description: >
  Implement security hardening, privacy protection, and legal compliance for Kora.
  Use this skill when building any security feature, writing or updating privacy
  policy or terms of service, implementing data encryption, setting up GDPR/CCPA
  compliance, securing Google OAuth tokens, protecting financial data, configuring
  CSP headers, implementing account deletion, or auditing the security posture.
  Triggers on: "security", "privacy", "GDPR", "CCPA", "encryption", "data protection",
  "privacy policy", "terms of service", "account deletion", "data retention",
  "token security", "API security", "sensitive data", "compliance".
---

# Kora Security & Privacy

> "Users trust Kora with their financial data, client relationships, and email access.
>  That trust is the product. Break it once and the product is dead."

Read the reference files in this order:
1. `references/data-map.md`             — every piece of data Kora collects and where it lives
2. `references/threat-model.md`         — what can go wrong, how to prevent it, and code-level security patterns
3. `references/google-privacy.md`       — Google OAuth specific protections and Limited Use compliance
4. `legal/privacy-policy.md`            — deployable privacy policy content
5. `legal/terms-of-service.md`          — deployable ToS content

---

## 1. The security promise to users

Kora handles four categories of sensitive data:

| Data type | Sensitivity | Examples |
|---|---|---|
| Financial data | HIGH | Transaction amounts, income, expenses, bank statement content |
| Client PII | HIGH | Client names, emails, phone numbers, addresses, tax IDs |
| Google account data | CRITICAL | OAuth tokens, email content, calendar events, Drive files |
| Business intelligence | MEDIUM | Playbook patterns, health scores, engagement status |

The promise: your data is encrypted, never sold, never used to train AI models,
accessible only to you, and deletable on demand. Every piece of this promise
must be technically enforced, not just stated in a policy.

---

## 2. Core security principles

1. **Encrypt at rest.** OAuth tokens are Fernet-encrypted before DB storage.
   Supabase encrypts the database volume. No plaintext secrets in the DB.

2. **Encrypt in transit.** All traffic over HTTPS. Supabase connections use TLS.
   Google API calls use TLS. Resend API calls use TLS.

3. **Minimize data collection.** Only collect what the agent needs to function.
   Never read personal Gmail threads. Never browse full Drive.

4. **Minimize data retention.** email_intel_cache expires after 24 hours.
   drive_doc_cache expires after processing. Meeting transcripts are processed
   and can be purged after MOM extraction.

5. **Never sell, never train.** User data is never shared with third parties
   for advertising or AI model training. Data goes to Gemini for processing
   but Google's Vertex AI API does not use customer data for training.

6. **User controls everything.** Users can disconnect Google, delete their
   account, export their data, and see/edit/delete everything Kora learned
   about them (the Playbook viewer).

7. **Log everything, expose nothing.** Agent logs record every AI decision
   but never contain raw email bodies, full transaction details, or PII
   in error reports (Sentry strips financial data).

---

## 3. What NOT to do (common mistakes)

```
✗ NEVER log full email content to console, Sentry, or agent_logs
✗ NEVER store OAuth tokens in plaintext — always Fernet-encrypt
✗ NEVER send SUPABASE_SERVICE_ROLE_KEY to the frontend
✗ NEVER include raw financial data in error payloads
✗ NEVER read Gmail threads that don't match a known client email
✗ NEVER browse the user's full Google Drive
✗ NEVER store credit card numbers (Stripe handles this via PCI compliance)
✗ NEVER send user data to any service other than Supabase, Google Cloud, Resend, and Stripe
✗ NEVER trust client-side plan values — always verify server-side
✗ NEVER process webhooks without signature verification
```

---

## 4. Compliance targets

| Regulation | Applies to | Key requirements | Status |
|---|---|---|---|
| GDPR | EU users | Consent, right to delete, data portability, DPA | Must implement |
| CCPA | California users | Right to know, right to delete, no sale of data | Must implement |
| India DPDP Act 2023 | Indian users | Consent, purpose limitation, data retention | Must implement |
| CAN-SPAM | All email recipients | Unsubscribe link, physical address, honest subjects | Must implement |
| Google API ToS | All users who connect Google | Limited use, no secondary use, data minimization | Must implement |

---

## 5. Build order

**Phase 1 — Security headers + CORS (2 hours)**
CSP, HSTS, X-Frame-Options, CORS configuration.

**Phase 2 — Data protection audit (half day)**
Verify: RLS on all tables, explicit user_id filters, token encryption,
no plaintext secrets, Sentry data scrubbing.

**Phase 3 — Legal pages (half day)**
Deploy privacy policy, terms of service, cookie notice at /privacy, /terms.
Read `legal/privacy-policy.md` and `legal/terms-of-service.md`.

**Phase 4 — Account deletion endpoint (2 hours)**
GDPR right to be forgotten. Delete all data across Supabase + GCS + Google revocation.

**Phase 5 — Data export endpoint (2 hours)**
GDPR right to portability. Export all user data as JSON.

**Phase 6 — Google-specific privacy (2 hours)**
Ensure Gmail/Drive data handling meets Google's Limited Use Requirements.
Read `references/google-privacy.md`.
