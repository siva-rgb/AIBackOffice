import Link from 'next/link';
import { Sparkles } from 'lucide-react';

/**
 * Header for the pages a visitor sees before signing in.
 *
 * Shared rather than repeated so the landing page, the plans page and the about
 * page cannot drift into three slightly different navs — the usual way a small
 * marketing site starts looking untended.
 */
export function PublicHeader({ current }: { current?: 'plans' | 'about' }) {
  const link = (href: string, label: string, key: 'plans' | 'about') =>
    current === key ? (
      <span key={href} className="text-sm font-semibold text-gray-900">
        {label}
      </span>
    ) : (
      <Link
        key={href}
        href={href}
        className="text-sm font-medium text-gray-600 hover:text-gray-900"
      >
        {label}
      </Link>
    );

  return (
    <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
      <Link href="/" className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-kora-600 text-white">
          <Sparkles size={18} />
        </div>
        <span className="text-lg font-bold">Kora</span>
      </Link>

      <nav className="flex items-center gap-5 sm:gap-6">
        {link('/plans', 'Plans', 'plans')}
        {link('/about', 'About', 'about')}
        <Link
          href="/dashboard"
          className="rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700"
        >
          Open dashboard
        </Link>
      </nav>
    </header>
  );
}
