import Link from 'next/link';
import { Sparkles } from 'lucide-react';

// Shared chrome for static legal pages (/privacy, /terms). Server component.
export function LegalShell({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-gray-200">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-5">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-kora-600 text-white">
              <Sparkles size={18} />
            </div>
            <span className="text-lg font-bold">Kora</span>
          </Link>
          <nav className="flex gap-5 text-sm text-gray-500">
            <Link href="/privacy" className="hover:text-gray-900">Privacy</Link>
            <Link href="/terms" className="hover:text-gray-900">Terms</Link>
          </nav>
        </div>
      </header>

      <article className="mx-auto max-w-3xl px-6 py-12">
        <h1 className="text-3xl font-extrabold text-gray-900">{title}</h1>
        <p className="mt-2 text-sm text-gray-400">Last updated: {updated}</p>
        <div className="prose-kora mt-8 space-y-6 text-sm leading-relaxed text-gray-700">
          {children}
        </div>
        <p className="mt-12 border-t border-gray-100 pt-6 text-xs text-gray-400">
          Questions? Contact{' '}
          <a href="mailto:privacy@kora.app" className="text-kora-600 hover:underline">privacy@kora.app</a>.
        </p>
      </article>
    </div>
  );
}

// Small typographic helpers so each page reads cleanly without a markdown lib.
export function H2({ children }: { children: React.ReactNode }) {
  return <h2 className="text-lg font-semibold text-gray-900">{children}</h2>;
}

export function P({ children }: { children: React.ReactNode }) {
  return <p className="text-gray-700">{children}</p>;
}

export function UL({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="list-disc space-y-1.5 pl-5 text-gray-700">
      {items.map((it, i) => (
        <li key={i}>{it}</li>
      ))}
    </ul>
  );
}

export function Callout({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      {children}
    </div>
  );
}
