import { Sidebar } from '@/components/sidebar';

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="kora-scroll flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-8 py-8 pt-16 lg:pt-8">{children}</div>
      </main>
    </div>
  );
}
