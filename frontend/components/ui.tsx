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
