'use client';

import React from 'react';
import { cn } from '@/lib/utils';

// Lightweight, dependency-free renderer for the markdown-ish text LLM agents
// produce (bold, italics, inline code, bullet/numbered lists, simple headings).
// Safe by construction — builds React nodes, never uses dangerouslySetInnerHTML.

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  // **bold** | `code` | *italic* | _italic_
  const regex = /(\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*|_([^_]+)_)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[2] !== undefined) nodes.push(<strong key={`${keyPrefix}-${i}`}>{m[2]}</strong>);
    else if (m[3] !== undefined)
      nodes.push(
        <code key={`${keyPrefix}-${i}`} className="rounded bg-black/10 px-1 py-0.5 text-[0.85em]">
          {m[3]}
        </code>,
      );
    else if (m[4] !== undefined) nodes.push(<em key={`${keyPrefix}-${i}`}>{m[4]}</em>);
    else if (m[5] !== undefined) nodes.push(<em key={`${keyPrefix}-${i}`}>{m[5]}</em>);
    last = m.index + m[0].length;
    i++;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function FormattedText({ text, className }: { text?: string | null; className?: string }) {
  const lines = (text || '').replace(/\r\n/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let key = 0;

  const flush = () => {
    if (!list) return;
    const { ordered, items } = list;
    blocks.push(
      ordered ? (
        <ol key={`l-${key++}`} className="my-1 list-decimal space-y-0.5 pl-5">
          {items.map((it, idx) => <li key={idx}>{renderInline(it, `li-${idx}`)}</li>)}
        </ol>
      ) : (
        <ul key={`l-${key++}`} className="my-1 list-disc space-y-0.5 pl-5">
          {items.map((it, idx) => <li key={idx}>{renderInline(it, `li-${idx}`)}</li>)}
        </ul>
      ),
    );
    list = null;
  };

  for (const raw of lines) {
    const trimmed = raw.trim();
    const bullet = /^[-*•]\s+(.*)/.exec(trimmed);
    const numbered = /^\d+[.)]\s+(.*)/.exec(trimmed);
    const heading = /^(#{1,3})\s+(.*)/.exec(trimmed);

    if (bullet) {
      if (!list || list.ordered) { flush(); list = { ordered: false, items: [] }; }
      list.items.push(bullet[1]);
      continue;
    }
    if (numbered) {
      if (!list || !list.ordered) { flush(); list = { ordered: true, items: [] }; }
      list.items.push(numbered[1]);
      continue;
    }
    flush();
    if (trimmed === '') continue;
    if (heading) {
      blocks.push(
        <p key={`h-${key++}`} className="mt-2 mb-0.5 font-semibold">
          {renderInline(heading[2], 'h')}
        </p>,
      );
      continue;
    }
    blocks.push(
      <p key={`p-${key++}`} className="my-0.5">
        {renderInline(trimmed, `p-${key}`)}
      </p>,
    );
  }
  flush();

  return <div className={cn('space-y-0.5', className)}>{blocks}</div>;
}
