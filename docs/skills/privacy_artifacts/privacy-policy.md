# Kora — Privacy Policy

*Last updated: [INSERT DATE]*
*Effective date: [INSERT DATE]*

Deploy this at `/privacy` on your website. Replace bracketed placeholders before publishing.

---

## Privacy Policy

Kora ("we," "us," "our") operates the kora.app website and the Kora application (the "Service"). This Privacy Policy explains how we collect, use, share, and protect your information when you use our Service.

By using Kora, you agree to the collection and use of information as described in this policy. If you do not agree, please do not use the Service.

### 1. Information We Collect

**Information you provide directly:**
- Account information: your name, email address, and password when you create an account
- Business information: your business name, address, country, industry, timezone, currency, and tax identification numbers
- Financial data: transaction records you upload (bank statements, CSV files), invoice details, payment amounts, and expense records
- Client information: names, email addresses, phone numbers, billing addresses, and tax IDs of your clients
- Documents: contracts, proposals, and other business documents you create or upload
- Communications: notes, meeting records, and quick capture entries you submit
- Payment information: processed by Stripe — we never see or store your credit card numbers

**Information collected from Google (when you connect your Google account):**
- Gmail: email thread metadata and snippets involving your clients only. We never read personal emails, newsletters, or promotional messages. We do not store full email content — only AI-generated summaries.
- Google Calendar: event titles, times, and attendee information for your upcoming meetings.
- Google Drive: files in your designated "Kora" folder and Google Meet transcripts. We do not browse or access other areas of your Drive.
- Google account email address and basic profile information.

We request only the Google permissions necessary to provide the Service. You can disconnect your Google account at any time from Settings, which immediately stops all data access and deletes cached Google data.

**Information collected automatically:**
- Usage data: pages visited, features used, and actions taken within the Service
- Device information: browser type, operating system, and screen size
- We do not use cookies for tracking or advertising. We use Vercel Analytics, which is privacy-first and does not use cookies.

### 2. How We Use Your Information

We use your information solely to provide and improve the Service:

- **Financial management:** categorize transactions, generate profit and loss reports, forecast cash flow, and track invoices
- **Client management:** monitor client relationships, track engagement status, and manage communications
- **AI-powered operations:** generate morning briefings, draft follow-up emails, create contracts and proposals, and provide business recommendations
- **Communication:** send transactional emails (invoice delivery, follow-up reminders, morning briefings) from our domain or from your connected Gmail address (only with your explicit approval for each email)
- **Billing:** process subscription payments via Stripe
- **Improvement:** analyze usage patterns to improve the Service (aggregated, never individual)

**AI processing disclosure:** Your business data — including transaction descriptions, email snippets, contract terms, and meeting transcripts — is sent to Google's Gemini AI (via Google Cloud Vertex AI) for processing. This processing generates transaction categories, email drafts, contract content, business briefings, and other AI outputs. Google's Vertex AI API does not use customer data for model training as per their API Terms of Service.

### 3. How We Share Your Information

We share your information only with the following service providers, solely to operate the Service:

| Provider | Data shared | Purpose |
|---|---|---|
| Google Cloud (Vertex AI) | Business data sent as AI prompts | AI processing (categorization, drafting, analysis) |
| Supabase | All structured data | Database hosting and authentication |
| Stripe | Payment details (handled by Stripe directly) | Subscription billing |
| Resend | Recipient email addresses and email content | Email delivery |
| Sentry | Error data (financial information stripped) | Error monitoring |
| Google APIs | Your own Google data (via your OAuth consent) | Gmail, Calendar, Drive integration |

**We do not:**
- Sell your data to anyone, ever
- Share your data with advertisers
- Use your data to train AI models
- Share your data with data brokers
- Transfer your data to any party not listed above

### 4. Data Security

We protect your information using:

- **Encryption in transit:** all data is transmitted over HTTPS/TLS
- **Encryption at rest:** Supabase encrypts the database. Google OAuth tokens are additionally encrypted using AES-256 (Fernet) before storage
- **Access control:** Row Level Security (RLS) ensures you can only access your own data. Every database query is scoped to your user ID
- **Security headers:** HSTS, CSP, X-Frame-Options, and other standard protections
- **Input validation:** all user input is validated and sanitized before processing
- **No plaintext secrets:** API keys, tokens, and credentials are stored as encrypted environment variables, never in code

### 5. Data Retention

| Data type | Retention period |
|---|---|
| Account and business information | Until you delete your account |
| Transaction and invoice records | 7 years from creation (tax compliance) |
| Contracts and proposals | 7 years from creation |
| AI-processed email summaries | 24 hours (automatically refreshed) |
| Agent activity logs | 1 year |
| Business Playbook (learned patterns) | Until confidence decays to zero or you delete them |
| Google OAuth tokens | Until you disconnect Google |

After account deletion, all your data is permanently removed within 30 days. Some aggregated, non-identifying statistics may be retained for service improvement.

### 6. Your Rights

Depending on your location, you may have the following rights:

- **Right to access:** view all data Kora holds about you (Settings → Export Data)
- **Right to correction:** edit any data Kora has learned about you (Settings → What Kora Knows)
- **Right to deletion:** delete your account and all associated data (Settings → Delete Account)
- **Right to portability:** export all your data in JSON format (Settings → Export Data)
- **Right to withdraw consent:** disconnect Google at any time, cancel your subscription at any time
- **Right to object:** contact us to object to specific data processing activities

**For EU/UK users (GDPR):** Our legal basis for processing is: (a) contract performance (providing the Service you signed up for), (b) legitimate interest (improving the Service), and (c) consent (Google account connection). You may contact [INSERT EMAIL] for GDPR-related requests.

**For California users (CCPA):** We do not sell personal information. You have the right to know what data we collect, request deletion, and not be discriminated against for exercising your rights.

**For Indian users (DPDP Act):** We process your data based on your consent and for the purpose of providing the Service. You may withdraw consent at any time by deleting your account.

### 7. Google API Services User Data Policy

Kora's use and transfer of information received from Google APIs adheres to the Google API Services User Data Policy, including the Limited Use requirements. Specifically:

- We only access the Google data types described in Section 1
- We only use Google data to provide and improve the features you consented to
- We do not transfer Google data to others except as described in Section 3
- We do not use Google data for advertising
- We do not use Google data to train AI models
- We allow you to revoke Google access at any time

### 8. Children's Privacy

Kora is designed for business use and is not intended for children under 16. We do not knowingly collect information from children under 16. If you believe we have collected such information, contact us immediately.

### 9. Changes to This Policy

We may update this Privacy Policy from time to time. We will notify you of material changes by email or in-app notification at least 14 days before the changes take effect.

### 10. Contact Us

For privacy-related questions, data requests, or concerns:

- Email: privacy@kora.app
- Address: [INSERT BUSINESS ADDRESS]

For Google-related data concerns, you can also disconnect your Google account at any time from the Settings page in the Kora application.

---

*This privacy policy covers the Kora application at kora.app.*
