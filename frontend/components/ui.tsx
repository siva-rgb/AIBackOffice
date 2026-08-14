import { cn } from '@/lib/utils';

export function Card({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('rounded-xl border border-gray-200 bg-white shadow-sm', className)}>
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between border-b border-gray-100 px-5 py-4">
      <div>
        <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: 'default' | 'green' | 'red' | 'amber' | 'brand';
}) {
  const toneClass = {
    default: 'text-gray-900',
    green: 'text-emerald-600',
    red: 'text-red-600',
    amber: 'text-amber-600',
    brand: 'text-kora-600',
  }[tone];
  return (
    <Card className="p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <p className={cn('mt-2 text-2xl font-bold tabular-nums', toneClass)}>{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </Card>
  );
}

const STATUS_STYLES: Record<string, string> = {
  // invoice
  draft: 'bg-gray-100 text-gray-600',
  sent: 'bg-blue-100 text-blue-700',
  viewed: 'bg-purple-100 text-purple-700',
  paid: 'bg-emerald-100 text-emerald-700',
  overdue: 'bg-red-100 text-red-700',
  cancelled: 'bg-gray-100 text-gray-400',
  // alert severity
  info: 'bg-blue-100 text-blue-700',
  warning: 'bg-amber-100 text-amber-700',
  critical: 'bg-red-100 text-red-700',
  // agent status
  success: 'bg-emerald-100 text-emerald-700',
  error: 'bg-red-100 text-red-700',
  partial: 'bg-amber-100 text-amber-700',
  // trigger
  scheduler: 'bg-indigo-100 text-indigo-700',
  user: 'bg-gray-100 text-gray-600',
  cross_module: 'bg-fuchsia-100 text-fuchsia-700',
  webhook: 'bg-cyan-100 text-cyan-700',
};

export function Badge({ value, label }: { value: string; label?: string }) {
  const style = STATUS_STYLES[value] ?? 'bg-gray-100 text-gray-600';
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize',
        style,
      )}
    >
      {label ?? value.replace(/_/g, ' ')}
    </span>
  );
}

/* ── Loading placeholders ───────────────────────────────────────────────────
 *
 * Every dashboard route is an async server component with `force-dynamic`, so
 * navigation waits on a server round trip. Without a `loading.tsx` Next keeps
 * the PREVIOUS page on screen for that whole time and renders nothing new —
 * the click appears to do nothing at all, which is what users reported.
 *
 * These mirror the real Card/StatCard geometry so the layout does not jump when
 * the content arrives. `aria-hidden` keeps the decorative bars out of the
 * accessibility tree; the surrounding region announces the loading state once.
 */

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('animate-pulse rounded bg-gray-200', className)} />;
}

/** Screen-reader announcement + visual bars. One per loading route. */
export function LoadingRegion({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div role="status" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

export function SkeletonStatCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3 h-7 w-32" />
          <Skeleton className="mt-3 h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

/** A card with a header and `rows` list items — the shape most pages use. */
export function SkeletonCard({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('rounded-xl border border-gray-200 bg-white shadow-sm', className)}>
      <div className="border-b border-gray-100 px-5 py-4">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-2 h-3 w-56" />
      </div>
      <div className="divide-y divide-gray-100">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="px-5 py-4">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="mt-2 h-3 w-1/3" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function SkeletonPageHeading() {
  return (
    <div className="mb-6">
      <Skeleton className="h-7 w-64" />
      <Skeleton className="mt-2 h-4 w-80" />
    </div>
  );
}
