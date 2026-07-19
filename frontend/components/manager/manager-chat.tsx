'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Send, Loader2, Sparkles, User2, ArrowRight } from 'lucide-react';
import { Card, CardHeader } from '@/components/ui';
import { FormattedText } from '@/components/formatted-text';
import { authedFetch } from '@/lib/api/browser';
import type { ChatReply, SuggestedAction } from '@/lib/api/types';

interface Msg {
  role: 'user' | 'assistant';
  content: string;
  actions?: SuggestedAction[];
}

const NAV: Record<string, string> = {
  open_invoices: '/invoices',
  open_contracts: '/contracts',
  open_cashflow: '/cashflow',
  open_bookkeeping: '/bookkeeping',
};

const SUGGESTIONS = [
  'Which invoices are overdue?',
  'How am I doing toward my goal this month?',
  'How is my cash flow looking?',
];

export function ManagerChat({ onRunReview, onActed }: { onRunReview?: () => void; onActed?: () => void }) {
  const router = useRouter();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, busy]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((m) => [...m, { role: 'user', content: q }]);
    setInput('');
    setBusy(true);
    try {
      const res = await authedFetch('/api/manager/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: q, history }),
      });
      const json = (await res.json()) as ChatReply;
      if (!res.ok) throw new Error('chat failed');
      setMessages((m) => [...m, { role: 'assistant', content: json.reply, actions: json.suggestedActions }]);
      if (json.queued && json.queued > 0) onActed?.(); // refresh the approval queue
    } catch {
      setMessages((m) => [...m, { role: 'assistant', content: 'Sorry — I had trouble answering. Please try again.' }]);
    } finally {
      setBusy(false);
    }
  }

  function runAction(a: SuggestedAction) {
    if (a.kind === 'run_review') {
      onRunReview?.();
      return;
    }
    const href = NAV[a.kind];
    if (href) router.push(href);
  }

  return (
    <Card>
      <CardHeader title="Ask your manager" subtitle="Questions about your finances, invoices, contracts — answered from your live data" />
      <div ref={scrollRef} className="kora-scroll max-h-96 space-y-4 overflow-y-auto p-5">
        {messages.length === 0 && (
          <div className="space-y-3">
            <p className="text-sm text-gray-500">Try asking:</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="rounded-full border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:border-kora-300 hover:bg-kora-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`flex gap-2.5 ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${m.role === 'user' ? 'bg-gray-200 text-gray-600' : 'bg-kora-600 text-white'}`}>
              {m.role === 'user' ? <User2 size={14} /> : <Sparkles size={14} />}
            </div>
            <div className={`max-w-[80%] ${m.role === 'user' ? 'text-right' : ''}`}>
              <div className={`inline-block rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${m.role === 'user' ? 'bg-kora-600 text-white' : 'bg-gray-100 text-gray-800'}`}>
                {m.role === 'assistant' ? <FormattedText text={m.content} /> : m.content}
              </div>
              {m.actions && m.actions.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {m.actions.map((a, j) => (
                    <button
                      key={j}
                      onClick={() => runAction(a)}
                      className="inline-flex items-center gap-1 rounded-lg border border-kora-200 bg-white px-2.5 py-1 text-xs font-medium text-kora-700 hover:bg-kora-50"
                    >
                      {a.label} <ArrowRight size={12} />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-kora-600 text-white">
              <Sparkles size={14} />
            </div>
            <div className="inline-flex items-center rounded-2xl bg-gray-100 px-3.5 py-2">
              <Loader2 size={14} className="animate-spin text-gray-400" />
            </div>
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="flex items-center gap-2 border-t border-gray-100 p-3"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask your business manager…"
          className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="inline-flex items-center justify-center rounded-lg bg-kora-600 p-2.5 text-white hover:bg-kora-700 disabled:opacity-50"
        >
          <Send size={16} />
        </button>
      </form>
    </Card>
  );
}
