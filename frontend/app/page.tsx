import Link from 'next/link';
import { Sparkles, ArrowRight, BookOpen, FileText, Bot } from 'lucide-react';

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-kora-600 text-white">
            <Sparkles size={18} />
          </div>
          <span className="text-lg font-bold">Kora</span>
        </div>
        <Link
          href="/dashboard"
          className="rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700"
        >
          Open dashboard
        </Link>
      </header>

      <section className="mx-auto max-w-3xl px-6 py-20 text-center">
        <p className="mb-4 inline-block rounded-full bg-kora-50 px-3 py-1 text-xs font-semibold text-kora-700">
          Fiverr Workspace shut down. We built something better.
        </p>
        <h1 className="text-4xl font-extrabold leading-tight text-gray-900 sm:text-5xl">
          The back-office that <span className="text-kora-600">runs itself.</span>
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-lg text-gray-600">
          Kora is the AI back-office for freelancers — bookkeeping, invoicing, and contracts in one
          place. Your AI agents work while you sleep.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-5 py-3 text-sm font-semibold text-white hover:bg-kora-700"
          >
            Try the live demo <ArrowRight size={16} />
          </Link>
        </div>
        <p className="mt-3 text-xs text-gray-400">
          Runs on seeded demo data — no signup, no credit card.
        </p>
      </section>

      <section className="mx-auto grid max-w-4xl gap-6 px-6 pb-24 sm:grid-cols-3">
        {[
          {
            icon: BookOpen,
            title: 'AI Bookkeeper',
            body: 'Upload a bank statement. Every transaction categorized, deductions flagged, P&L generated.',
          },
          {
            icon: FileText,
            title: 'Invoice Agent',
            body: 'Send invoices, then let AI chase overdue payments automatically on days 3, 7, and 14.',
          },
          {
            icon: Bot,
            title: 'Agent Audit Log',
            body: 'Every autonomous AI decision is logged and exportable — full transparency, no black box.',
          },
        ].map(({ icon: Icon, title, body }) => (
          <div key={title} className="rounded-xl border border-gray-200 p-6">
            <Icon className="text-kora-600" size={24} />
            <h3 className="mt-3 font-semibold text-gray-900">{title}</h3>
            <p className="mt-1 text-sm text-gray-600">{body}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
