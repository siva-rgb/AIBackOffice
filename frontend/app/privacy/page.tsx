import { LegalShell, H2, P, UL, Callout } from '@/components/legal/legal-shell';

export const metadata = {
  title: 'Privacy Policy — Kora',
  description: 'How Kora collects, uses, and protects your data.',
};

export default function PrivacyPage() {
  return (
    <LegalShell title="Privacy Policy" updated="May 30, 2026">
      <P>
        This Privacy Policy explains how Kora (&quot;Kora&quot;, &quot;we&quot;, &quot;us&quot;) collects, uses, and
        protects your information when you use our AI back-office platform. By using Kora you agree to the
        practices described here.
      </P>

      <H2>1. Data we collect</H2>
      <UL
        items={[
          'Account data: your name, email address, and business name.',
          'Financial data: transactions you upload or enter, invoices, and the categories the AI assigns.',
          'Contract data: the parties, terms, and documents you generate.',
          'Usage data: basic, privacy-first analytics about how the product is used (no cross-site tracking cookies).',
        ]}
      />

      <H2>2. How we use your data</H2>
      <P>
        We process your data solely to provide the service: categorizing transactions, generating P&amp;L
        reports and cash-flow forecasts, drafting invoices and contracts, and sending you alerts and digests.
        We do not sell your data, and we do not use your financial or contract content to train third-party
        models.
      </P>

      <H2>3. AI processing disclosure</H2>
      <P>
        Kora uses large language models to provide automated categorization, forecasting, and document
        generation. Relevant portions of your financial and document data are sent to our AI provider strictly
        to produce these outputs for you. AI-generated output may contain errors and should be reviewed.
      </P>

      <H2>4. Legal basis for processing (GDPR)</H2>
      <UL
        items={[
          'Contract performance: processing necessary to deliver the service you signed up for.',
          'Legitimate interest: improving reliability and security of the service.',
        ]}
      />

      <H2>5. Third-party processors</H2>
      <UL
        items={[
          'Supabase — database and authentication.',
          'AI gateway / Google Cloud — automated processing of financial and document data.',
          'Stripe — payment processing (we never see or store your card numbers).',
          'Resend — transactional email delivery.',
        ]}
      />

      <H2>6. Data retention</H2>
      <UL
        items={[
          'Transaction and financial records are retained for up to 7 years to support tax compliance.',
          'Account data is deleted within 30 days after you cancel your account.',
        ]}
      />

      <H2>7. Your rights</H2>
      <P>
        Depending on your jurisdiction (including the EU/EEA under GDPR and California under CCPA), you have the
        right to access, correct, export, and delete your personal data. You can export your data or request
        account deletion at any time from your account settings, or by emailing us.
      </P>

      <H2>8. Security</H2>
      <P>
        Data is encrypted in transit and at rest. Access to production data is restricted, and financial
        details are excluded from error-monitoring logs.
      </P>

      <Callout>
        This policy is provided as a clear summary for the Kora MVP and is not a substitute for tailored legal
        advice. Before commercial launch, have it reviewed by qualified counsel.
      </Callout>

      <H2>9. Contact</H2>
      <P>
        For privacy questions or to exercise your rights, contact{' '}
        <a href="mailto:privacy@kora.app" className="text-kora-600 hover:underline">privacy@kora.app</a>.
      </P>
    </LegalShell>
  );
}
