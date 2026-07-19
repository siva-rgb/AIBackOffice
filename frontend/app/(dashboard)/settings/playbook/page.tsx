import { serverGet } from '@/lib/api/server';
import type { PlaybookEntry, PlaybookStats, KgGraph } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { PlaybookViewer } from '@/components/settings/playbook-viewer';
import { GraphView } from '@/components/settings/graph-view';
import { MemoryRecall } from '@/components/settings/memory-recall';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'What Kora knows — Kora' };

export default async function PlaybookPage() {
  let entries: PlaybookEntry[];
  let stats: PlaybookStats;
  try {
    [entries, stats] = await Promise.all([
      serverGet<PlaybookEntry[]>('/api/playbook'),
      serverGet<PlaybookStats>('/api/playbook/stats'),
    ]);
  } catch {
    return <BackendDown />;
  }

  // Graph memory is best-effort — if the migration isn't applied yet, show an
  // empty graph (with a Rebuild button) rather than failing the whole page.
  let graph: KgGraph = { nodes: [], edges: [] };
  try {
    graph = await serverGet<KgGraph>('/api/graph');
  } catch {
    graph = { nodes: [], edges: [] };
  }

  return (
    <div className="space-y-10">
      <div className="space-y-8">
        <header>
          <h1 className="text-2xl font-bold text-gray-900">What Kora knows</h1>
          <p className="mt-1 text-sm text-gray-500">
            Kora learns from your corrections and patterns over time. Review and manage what it has learned.
          </p>
        </header>
        <PlaybookViewer entries={entries} stats={stats} />
      </div>

      <div className="space-y-4">
        <header>
          <h2 className="text-lg font-bold text-gray-900">Relationship memory</h2>
          <p className="mt-1 text-sm text-gray-500">
            The graph your agents traverse — each client and everything linked to them (invoices, contracts,
            engagements and facts learned from email &amp; meetings).
          </p>
        </header>
        <GraphView graph={graph} />
      </div>

      <div className="space-y-4">
        <header>
          <h2 className="text-lg font-bold text-gray-900">Recall memory</h2>
          <p className="mt-1 text-sm text-gray-500">
            Search everything Kora has learned by <span className="font-medium">meaning</span>, not just keywords —
            the same hybrid semantic recall the agents use when planning and drafting.
          </p>
        </header>
        <MemoryRecall />
      </div>
    </div>
  );
}
