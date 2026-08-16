import Link from 'next/link';
import {
  Mail,
  BookOpen,
  FileText,
  FileSignature,
  TrendingUp,
  Bot,
  BrainCircuit,
} from 'lucide-react';
import { PublicHeader } from '@/components/marketing/public-header';

export const metadata = {
  title: 'About Kora',
  description: 'What Kora is, who it is for, and how to get in touch.',
};

const MODULES = [
  {
    icon: BookOpen,
    name: 'AI Bookkeeper',
    body: 'Upload a bank statement and every transaction is categorised, deductions flagged, and a P&L generated as a PDF.',
  },
  {
    icon: FileText,
    name: 'Invoice Agent',
    body: 'Create and send invoices, then let Kora chase the late ones on its own — day 3, day 7, day 14, escalating the tone each time.',
  },
  {
    icon: FileSignature,
    name: 'Contracts',
    body: 'Draft a contract from a short brief, get every clause explained in plain English, and have risky terms flagged before you sign.',
  },
  {
    icon: TrendingUp,
    name: 'Cash-flow forecast',
    body: 'A 90-day projection across best, likely and worst cases — with the reasoning written out, not just a number.',
  },
  {
    icon: BrainCircuit,
    name: 'Business Manager',
    body: 'Ask it anything about your business — "how am I tracking against my revenue goal?" — and it answers from your real figures.',
  },
  {
    icon: Bot,
    name: 'Agent audit log',
    body: 'Every autonomous decision is recorded with the model used, tokens, latency and cost. Nothing happens that you cannot inspect.',
  },
];

export default function AboutPage() {
  return (
    <main className="min-h-screen bg-white">
      <PublicHeader current="about" />

      <section className="mx-auto max-w-5xl px-6 pt-10">
        <div className="max-w-3xl">
          <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
            About Kora
          </h1>
          <p className="mt-5 text-lg text-gray-600">
            Kora is an AI back-office for freelancers and small businesses — the admin half of
            running a business, handled for you.
          </p>
          <p className="mt-4 text-gray-600">
            Most people who work for themselves are good at the work and resent everything around
            it: categorising transactions, writing the invoice, remembering to chase it, working out
            whether next month is going to be tight. That work is necessary, repetitive, and almost
            never the reason anyone started a business.
          </p>
          <p className="mt-4 text-gray-600">
            So Kora does it. Not as a chatbot bolted onto a spreadsheet, but as a set of agents that
            hold your actual books, your actual clients and your actual contracts, and act on them —
            chasing an overdue invoice while you sleep, flagging a cash-flow gap before it becomes
            one, reading a contract properly before you sign it.
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 py-16">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
          What&apos;s inside
        </h2>
        <div className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {MODULES.map(({ icon: Icon, name, body }) => (
            <div key={name} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <Icon size={20} className="text-kora-600" />
              <h3 className="mt-3 text-base font-semibold text-gray-900">{name}</h3>
              <p className="mt-1.5 text-sm text-gray-600">{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 pb-8">
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-6">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-500">
            Built with
          </h2>
          <p className="mt-3 text-sm text-gray-600">
            A Next.js front end talking to a Python/FastAPI back end that owns all data and AI. The
            agents run on Google Vertex AI (Gemini), with Supabase for auth and storage and Stripe
            for payments. Every AI call is logged with its real model, token count, latency and cost
            — which is why the audit log can show you exactly what was done and what it cost.
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-5xl px-6 pb-20">
        <div className="rounded-xl border border-kora-200 bg-kora-50 p-6">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
            <Mail size={18} className="text-kora-600" /> Get in touch
          </h2>
          <p className="mt-2 text-sm text-gray-700">
            Questions, bugs, feature requests, or you just tried it and want to tell me what was
            wrong with it — all genuinely welcome. It reaches me directly.
          </p>
          <a
            href="mailto:pandasivananda@gmail.com"
            className="mt-4 inline-block rounded-lg bg-kora-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-kora-700"
          >
            pandasivananda@gmail.com
          </a>
          <p className="mt-4 text-sm text-gray-600">
            Want to try it first?{' '}
            <Link href="/plans" className="font-medium text-kora-700 hover:underline">
              Early users get Pro free for 90 days
            </Link>
            .
          </p>
        </div>
      </section>

      <footer className="border-t border-gray-100 px-6 py-8 text-center text-sm text-gray-500">
        <Link href="/plans" className="text-kora-600 hover:underline">
          Plans
        </Link>
        {' · '}
        <Link href="/privacy" className="text-kora-600 hover:underline">
          Privacy
        </Link>
        {' · '}
        <Link href="/terms" className="text-kora-600 hover:underline">
          Terms
        </Link>
      </footer>
    </main>
  );
}
