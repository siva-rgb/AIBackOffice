'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Briefcase, Calendar, Video, Mail, HardDrive } from 'lucide-react';
import { cn } from '@/lib/utils';

// Butler is the communication hub: Clients + the four Google/comms surfaces
// (Calendar, Meetings, Email, Drive) live here as tabs. The tab bar is hidden on
// a single-client workspace (/butler/clients/...) which has its own tabs.
const TABS = [
  { href: '/butler', label: 'Clients', icon: Briefcase },
  { href: '/butler/calendar', label: 'Calendar', icon: Calendar },
  { href: '/butler/meetings', label: 'Meetings', icon: Video },
  { href: '/butler/email', label: 'Email', icon: Mail },
  { href: '/butler/drive', label: 'Drive', icon: HardDrive },
];

export default function ButlerLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const hideTabs = pathname.startsWith('/butler/clients');

  return (
    <div className="space-y-6">
      {!hideTabs && (
        <nav className="flex gap-1 overflow-x-auto border-b border-gray-200">
          {TABS.map(({ href, label, icon: Icon }) => {
            const active = href === '/butler' ? pathname === '/butler' : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  'flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                  active
                    ? 'border-kora-600 text-kora-700'
                    : 'border-transparent text-gray-500 hover:text-gray-800',
                )}
              >
                <Icon size={16} />
                {label}
              </Link>
            );
          })}
        </nav>
      )}
      {children}
    </div>
  );
}
