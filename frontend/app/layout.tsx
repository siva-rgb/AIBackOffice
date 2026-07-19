import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Kora — AI back-office for freelancers',
  description:
    'The back-office that runs itself. AI bookkeeping, invoicing, contracts, and proactive financial alerts.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans">{children}</body>
    </html>
  );
}
