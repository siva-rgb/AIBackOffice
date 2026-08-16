'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  LayoutDashboard,
  BookOpen,
  FileText,
  FileSignature,
  TrendingUp,
  Bot,
  Sparkles,
  HelpCircle,
  Settings,
  BrainCircuit,
  Briefcase,
  CreditCard,
  LogOut,
  Menu,
  X,
  Loader2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { getSupabaseBrowser } from '@/lib/supabase/client';

const NAV = [
  { href: '/dashboard', label: 'Overview', icon: LayoutDashboard },
  { href: '/manager', label: 'Business Manager', icon: BrainCircuit },
  { href: '/butler', label: 'Butler', icon: Briefcase },
  { href: '/bookkeeping', label: 'Bookkeeping', icon: BookOpen },
  { href: '/invoices', label: 'Invoices', icon: FileText },
  { href: '/contracts', label: 'Contracts', icon: FileSignature },
  { href: '/cashflow', label: 'Cash flow', icon: TrendingUp },
  { href: '/agents', label: 'AI Agents', icon: Bot },
  { href: '/settings', label: 'Business profile', icon: Settings },
  // Pricing existed as a page but was reachable only from Settings → Billing,
  // so nobody evaluating the product ever saw what it costs.
  { href: '/pricing', label: 'Plans & pricing', icon: CreditCard },
  { href: '/how-it-works', label: 'How it works', icon: HelpCircle },
];

function SidebarContent({
  pathname,
  profile,
  initials,
  onClose,
  onSignOut,
  pending,
  onNavigate,
}: {
  pathname: string;
  profile: { name: string; email: string } | null;
  initials: string;
  onClose?: () => void;
  onSignOut: () => void;
  /** href of the item just clicked, while its page is still rendering */
  pending: string | null;
  onNavigate: (href: string) => void;
}) {
  return (
    <>
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 py-5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-kora-600 text-white">
          <Sparkles size={18} />
        </div>
        <div className="flex-1">
          <p className="text-base font-bold leading-none text-gray-900">Kora</p>
          <p className="text-[10px] uppercase tracking-wide text-gray-400">AI back-office</p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close navigation"
            className="rounded-md p-1 text-gray-400 hover:text-gray-600"
          >
            <X size={20} />
          </button>
        )}
      </div>

      {/* Nav — scrollable when items overflow */}
      <nav className="flex-1 overflow-y-auto space-y-1 px-3 py-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + '/');
          // These routes render on the server, so a click is followed by a
          // round trip. Marking the item you clicked answers "did that
          // register?" immediately, and it names the destination — which the
          // content-area skeleton cannot do.
          const navigating = pending === href && !active;
          return (
            <Link
              key={href}
              href={href}
              onClick={() => onNavigate(href)}
              aria-busy={navigating}
              className={cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'bg-kora-50 text-kora-700'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900',
                navigating && 'bg-gray-50 text-gray-900',
              )}
            >
              {navigating ? <Loader2 size={18} className="animate-spin text-kora-600" /> : <Icon size={18} />}
              {label}
            </Link>
          );
        })}
      </nav>

      {/* User footer */}
      <div className="border-t border-gray-100 px-3 py-3">
        <div className="flex items-center gap-3 px-2 py-1">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-kora-100 text-sm font-semibold text-kora-700">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-gray-900">{profile?.name ?? 'Kora user'}</p>
            <p className="truncate text-xs text-gray-400">{profile?.email ?? ''}</p>
          </div>
        </div>
        <button
          onClick={onSignOut}
          className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-gray-500 hover:bg-gray-50 hover:text-gray-900"
        >
          <LogOut size={18} /> Sign out
        </button>
      </div>
    </>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const supabase = getSupabaseBrowser();
  const [profile, setProfile] = useState<{ name: string; email: string } | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  // Which nav item was just clicked, so it can show a spinner while the server
  // renders the destination. Cleared once the pathname actually changes.
  const [pending, setPending] = useState<string | null>(null);

  // Close drawer on navigation
  useEffect(() => { setMobileOpen(false); setPending(null); }, [pathname]);

  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      const u = data.user;
      if (u) {
        const name = (u.user_metadata?.full_name as string) || u.email?.split('@')[0] || 'You';
        setProfile({ name, email: u.email ?? '' });
      }
    });
  }, [supabase]);

  async function signOut() {
    await supabase.auth.signOut();
    router.replace('/login');
    router.refresh();
  }

  const initials = (profile?.name ?? 'K')
    .split(' ')
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  const sharedProps = { pathname, profile, initials, onSignOut: signOut, pending, onNavigate: setPending };

  return (
    <>
      {/* Desktop sidebar — always visible at lg+ */}
      <aside className="hidden lg:flex w-60 flex-col border-r border-gray-200 bg-white">
        <SidebarContent {...sharedProps} />
      </aside>

      {/* Mobile — floating hamburger button */}
      <button
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation"
        className="lg:hidden fixed top-4 left-4 z-40 flex h-9 w-9 items-center justify-center rounded-lg border border-gray-200 bg-white shadow-sm text-gray-600 hover:text-gray-900"
      >
        <Menu size={18} />
      </button>

      {/* Mobile — backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile — slide-in drawer */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex w-60 flex-col border-r border-gray-200 bg-white transition-transform duration-200 lg:hidden',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <SidebarContent {...sharedProps} onClose={() => setMobileOpen(false)} />
      </aside>
    </>
  );
}
