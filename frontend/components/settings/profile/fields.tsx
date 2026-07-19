'use client';

import { Plus, Trash2 } from 'lucide-react';
import { inputCls } from './templates';

// Module-scope so component identity is stable across renders (otherwise inputs
// remount on every keystroke and lose focus).
export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-gray-600">{label}</span>
      {children}
    </label>
  );
}

export function TextField(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  inputMode?: React.HTMLAttributes<HTMLInputElement>['inputMode'];
}) {
  return (
    <Field label={props.label}>
      <input
        className={inputCls}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        placeholder={props.placeholder}
        inputMode={props.inputMode}
      />
    </Field>
  );
}

export function TextAreaField(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <Field label={props.label}>
      <textarea
        className={inputCls}
        rows={props.rows ?? 2}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        placeholder={props.placeholder}
      />
    </Field>
  );
}

// Add/remove editor for an array of objects (offerings, personas, team, socials…).
// rows is the current array; render(row, update, i) draws one row's fields.
export function RowsEditor<T>(props: {
  rows: T[];
  empty: () => T;
  onChange: (rows: T[]) => void;
  addLabel: string;
  render: (row: T, update: (patch: Partial<T>) => void, index: number) => React.ReactNode;
}) {
  const { rows, empty, onChange, addLabel, render } = props;
  return (
    <div className="space-y-3">
      {rows.map((row, i) => (
        <div key={i} className="relative rounded-lg border border-gray-200 bg-gray-50/60 p-4">
          <button
            type="button"
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
            aria-label="Remove"
            className="absolute right-2 top-2 rounded p-1 text-gray-400 hover:text-red-600"
          >
            <Trash2 size={14} />
          </button>
          {render(
            row,
            (patch) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r))),
            i,
          )}
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...rows, empty()])}
        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:border-kora-400 hover:text-kora-700"
      >
        <Plus size={13} /> {addLabel}
      </button>
    </div>
  );
}
