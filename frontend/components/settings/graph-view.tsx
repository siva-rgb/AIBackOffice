'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Network, RefreshCw, Loader2, Building2, Users, FileText, FileSignature, Briefcase, Sparkles } from 'lucide-react';
import { Card } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import type { KgGraph, KgNode } from '@/lib/api/types';

const TYPE_ICON: Record<string, typeof FileText> = {
  business: Building2,
  client: Users,
  invoice: FileText,
  contract: FileSignature,
  engagement: Briefcase,
  proposal: FileText,
  retainer: FileText,
  fact: Sparkles,
};

const REL_COLOR: Record<string, string> = {
  PAID: 'text-emerald-600',
  ISSUED: 'text-amber-600',
  SIGNED: 'text-blue-600',
  HAS_ENGAGEMENT: 'text-violet-600',
  MET_ABOUT: 'text-violet-600',
  MENTIONS: 'text-gray-500',
  RELATED_TO: 'text-gray-500',
};

export function GraphView({ graph }: { graph: KgGraph }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  const byId = useMemo(() => {
    const m: Record<string, KgNode> = {};
    for (const n of graph.nodes) m[n.id] = n;
    return m;
  }, [graph.nodes]);

  // Group each client's outgoing/incoming relations (excluding the business hub).
  const clients = useMemo(() => {
    const clientNodes = graph.nodes
      .filter((n) => n.nodeType === 'client')
      .sort((a, b) => (b.salience ?? 0) - (a.salience ?? 0));
    return clientNodes.map((c) => {
      const relations = graph.edges
        .filter((e) => e.srcId === c.id || e.dstId === c.id)
        .map((e) => {
          const otherId = e.srcId === c.id ? e.dstId : e.srcId;
          return { rel: e.rel, node: byId[otherId] };
        })
        .filter((r) => r.node && r.node.nodeType !== 'business');
      return { client: c, relations };
    });
  }, [graph, byId]);

  async function rebuild() {
    setBusy(true);
    setMsg(null);
    try {
      const res = await authedFetch('/api/graph/sync', { method: 'POST' });
      if (!res.ok) throw new Error();
      const j = await res.json().catch(() => ({}));
      setMsg({ text: `Rebuilt — ${j.nodes ?? 0} entities, ${j.edges ?? 0} relationships.`, ok: true });
      router.refresh();
    } catch {
      setMsg({ text: 'Could not rebuild. If this is a fresh setup, apply the graph migration first.', ok: false });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-gray-500">
          {graph.nodes.length} entit{graph.nodes.length === 1 ? 'y' : 'ies'} · {graph.edges.length} relationship
          {graph.edges.length === 1 ? '' : 's'}
        </p>
        <button
          onClick={rebuild}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Rebuild memory
        </button>
      </div>

      {msg && (
        <div className={`rounded-lg px-4 py-3 text-sm ${msg.ok ? 'bg-blue-50 text-blue-800' : 'bg-red-50 text-red-700'}`}>
          {msg.text}
        </div>
      )}

      {clients.length === 0 ? (
        <Card className="p-8 text-center">
          <Network className="mx-auto text-gray-300" size={28} />
          <p className="mt-3 text-sm font-medium text-gray-500">No relationship memory yet</p>
          <p className="mt-1 text-xs text-gray-400">
            Click <span className="font-medium">Rebuild memory</span> to map your clients and everything linked to
            them — invoices, contracts, engagements and learned facts.
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          {clients.map(({ client, relations }) => {
            const health = client.props?.healthLabel as string | undefined;
            return (
              <Card key={client.id} className="p-4">
                <div className="mb-2 flex items-center gap-2">
                  <Users size={15} className="text-gray-400" />
                  <span className="text-sm font-semibold text-gray-900">{client.label}</span>
                  {health && health !== 'on_track' && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold capitalize text-amber-700">
                      {health.replace('_', ' ')}
                    </span>
                  )}
                </div>
                {relations.length === 0 ? (
                  <p className="text-xs text-gray-400">No linked records yet.</p>
                ) : (
                  <ul className="space-y-1">
                    {relations.map((r, i) => {
                      const Icon = TYPE_ICON[r.node.nodeType] ?? FileText;
                      return (
                        <li key={i} className="flex items-center gap-2 text-xs text-gray-600">
                          <span className={`font-mono font-semibold ${REL_COLOR[r.rel] ?? 'text-gray-500'}`}>{r.rel}</span>
                          <span className="text-gray-300">→</span>
                          <Icon size={13} className="text-gray-400" />
                          <span className="truncate">{r.node.label}</span>
                          {r.node.props?.status && (
                            <span className="text-gray-400">({String(r.node.props.status)})</span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
