'use client';

import { AlertTriangle, ShieldCheck, ShieldAlert, FileWarning, Lightbulb, CheckCircle2 } from 'lucide-react';
import type { ContractReview as Review, ReviewFinding } from '@/lib/api/types';
import { FormattedText } from '@/components/formatted-text';
import { cn } from '@/lib/utils';

const RISK_STYLE: Record<string, { ring: string; text: string; bg: string; label: string; icon: typeof ShieldAlert }> = {
  high: { ring: 'border-red-200', text: 'text-red-700', bg: 'bg-red-50', label: 'High risk', icon: ShieldAlert },
  medium: { ring: 'border-amber-200', text: 'text-amber-700', bg: 'bg-amber-50', label: 'Medium risk', icon: ShieldAlert },
  low: { ring: 'border-emerald-200', text: 'text-emerald-700', bg: 'bg-emerald-50', label: 'Low risk', icon: ShieldCheck },
};

const SEV_BADGE: Record<string, string> = {
  high: 'bg-red-100 text-red-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-gray-100 text-gray-600',
};

function FindingCard({ f }: { f: ReviewFinding }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <div className="flex items-center gap-2">
        <span className={cn('rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide', SEV_BADGE[f.severity] ?? SEV_BADGE.medium)}>
          {f.severity}
        </span>
        <span className="text-sm font-semibold text-gray-900">{f.title}</span>
        {f.category && <span className="ml-auto text-[11px] text-gray-400">{f.category}</span>}
      </div>
      <FormattedText text={f.issue} className="mt-1.5 text-xs leading-relaxed text-gray-700" />
      {f.recommendation && (
        <div className="mt-1.5 flex items-start gap-1.5 text-xs leading-relaxed text-kora-700">
          <Lightbulb size={13} className="mt-0.5 shrink-0" />
          <FormattedText text={f.recommendation} />
        </div>
      )}
      {f.clauseReference && (
        <p className="mt-1 text-[11px] text-gray-400">Ref: {f.clauseReference}</p>
      )}
    </div>
  );
}

export function ContractReviewView({ review }: { review: Review }) {
  const r = RISK_STYLE[review.overallRisk] ?? RISK_STYLE.medium;
  const RiskIcon = r.icon;
  const ordered = [...review.findings].sort(
    (a, b) => ({ high: 0, medium: 1, low: 2 }[a.severity] - { high: 0, medium: 1, low: 2 }[b.severity]),
  );

  return (
    <div className="space-y-4">
      {/* Risk banner */}
      <div className={cn('flex items-start gap-3 rounded-xl border px-4 py-3', r.ring, r.bg)}>
        <RiskIcon className={cn('mt-0.5 shrink-0', r.text)} size={20} />
        <div>
          <p className={cn('text-sm font-bold', r.text)}>{r.label}</p>
          {review.summary && <FormattedText text={review.summary} className="mt-0.5 text-xs leading-relaxed text-gray-700" />}
        </div>
      </div>

      {/* Findings */}
      {ordered.length > 0 && (
        <div>
          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
            <AlertTriangle size={13} /> Risky / one-sided clauses ({ordered.length})
          </p>
          <div className="space-y-2">
            {ordered.map((f, i) => (
              <FindingCard key={i} f={f} />
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {/* Missing clauses */}
        {review.missingClauses.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
              <FileWarning size={13} /> Missing protections
            </p>
            <ul className="space-y-1.5">
              {review.missingClauses.map((m, i) => (
                <li key={i} className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-500" /> {m}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Favorable */}
        {review.favorablePoints.length > 0 && (
          <div>
            <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
              <ShieldCheck size={13} /> In your favor
            </p>
            <ul className="space-y-1.5">
              {review.favorablePoints.map((m, i) => (
                <li key={i} className="flex items-start gap-2 rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
                  <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-emerald-500" /> {m}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <p className="text-[11px] text-gray-400">
        AI-generated review for information only — not legal advice. Review important agreements with a qualified professional.
      </p>
    </div>
  );
}
