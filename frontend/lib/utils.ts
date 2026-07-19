// Shared formatting + small helpers used across server and client components.

export function formatMoney(amount: number, currency = 'USD'): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function daysBetween(fromIsoDate: string, toDate = new Date()): number {
  const from = new Date(fromIsoDate + (fromIsoDate.length === 10 ? 'T00:00:00Z' : ''));
  const ms = toDate.getTime() - from.getTime();
  return Math.floor(ms / 86_400_000);
}

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}

// Human-friendly label for category slugs e.g. software_subscriptions → Software Subscriptions
export function humanize(slug: string | null): string {
  if (!slug) return 'Uncategorized';
  return slug
    .split(/[_\s]+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export function titleForAgent(type: string): string {
  return humanize(type);
}
