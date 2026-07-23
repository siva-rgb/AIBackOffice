'use client';

import { useEffect, useState, useCallback } from 'react';
import {
  ChevronRight, Loader2, Briefcase, AlertTriangle, Ban, Clock, FolderOpen, ListTodo,
} from 'lucide-react';
import { Card } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import { humanize, cn } from '@/lib/utils';
import type { ClientTree, ProjectNode, TaskRollup, Story, HealthLabel } from '@/lib/api/types';
import { StoryCard } from './story-card';

const HEALTH_CHIP: Record<HealthLabel, string> = {
  on_track: 'bg-emerald-100 text-emerald-700',
  at_risk: 'bg-amber-100 text-amber-700',
  needs_attention: 'bg-orange-100 text-orange-700',
  critical: 'bg-red-100 text-red-700',
};

function HealthBadge({ score, label }: { score: number; label: HealthLabel }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold', HEALTH_CHIP[label] ?? 'bg-gray-100 text-gray-600')}>
      <span className="tabular-nums">{score}</span> · {humanize(label)}
    </span>
  );
}

function ProgressBar({ pct }: { pct: number }) {
  const tone = pct >= 80 ? 'bg-emerald-500' : pct >= 40 ? 'bg-blue-500' : 'bg-gray-300';
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-100">
        <div className={cn('h-full rounded-full', tone)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right text-[11px] tabular-nums text-gray-500">{pct}%</span>
    </div>
  );
}

export function ProjectTree({ clientId }: { clientId: string }) {
  const [tree, setTree] = useState<ClientTree | null>(null);
  const [storiesByTask, setStoriesByTask] = useState<Record<string, Story[]>>({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [treeRes, storyRes] = await Promise.all([
        authedFetch(`/api/clients/${clientId}/tree`),
        authedFetch(`/api/stories?client_id=${clientId}`),
      ]);
      const t: ClientTree = treeRes.ok ? await treeRes.json() : null;
      const stories: Story[] = storyRes.ok ? await storyRes.json() : [];
      const grouped: Record<string, Story[]> = {};
      for (const s of stories) (grouped[s.taskId] ||= []).push(s);
      setTree(t);
      setStoriesByTask(grouped);
    } catch {
      setTree(null);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <Card className="flex items-center justify-center gap-2 p-8 text-sm text-gray-400">
        <Loader2 size={16} className="animate-spin" /> Building the picture…
      </Card>
    );
  }

  if (!tree || (tree.projects.length === 0 && tree.unassignedTasks.length === 0)) {
    return (
      <Card className="p-8 text-center">
        <FolderOpen className="mx-auto text-gray-300" size={26} />
        <p className="mt-3 text-sm font-medium text-gray-500">No projects or tasks yet</p>
        <p className="mt-1 text-xs text-gray-400">
          Add an engagement and some tasks — or let Kora capture them from meetings, email and
          contracts. Stories, progress and blockers roll up here automatically.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {/* Client-level roll-up — the top of the hierarchy (M2, server-computed) */}
      {tree.hasData && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-gray-50/60 px-4 py-2.5">
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-700">
            <FolderOpen size={15} className="text-gray-400" />
            Overall delivery
            <span className="text-xs font-normal text-gray-400">
              · {tree.taskCount} task(s), {tree.storyCount} story(ies)
            </span>
          </div>
          <div className="flex items-center gap-3">
            <ProgressBar pct={tree.progressPct} />
            <HealthBadge score={tree.score} label={tree.label} />
          </div>
        </div>
      )}

      {tree.projects.map((p) => (
        <ProjectRow key={p.engagementId} project={p} storiesByTask={storiesByTask} onChanged={load} />
      ))}

      {tree.unassignedTasks.length > 0 && (
        <UnfiledRow tasks={tree.unassignedTasks} storiesByTask={storiesByTask} onChanged={load} />
      )}
    </div>
  );
}

function ProjectRow({
  project, storiesByTask, onChanged,
}: { project: ProjectNode; storiesByTask: Record<string, Story[]>; onChanged: () => void }) {
  const [open, setOpen] = useState(true);
  return (
    <Card className="overflow-hidden">
      <button onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-gray-50">
        <ChevronRight size={16} className={cn('shrink-0 text-gray-400 transition-transform', open && 'rotate-90')} />
        <Briefcase size={15} className="shrink-0 text-gray-400" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-gray-900">{project.title}</p>
          <p className="text-[11px] text-gray-400">{humanize(project.status)} · {project.taskCount} task(s)</p>
        </div>
        <div className="hidden sm:block"><ProgressBar pct={project.progressPct} /></div>
        {project.hasData && <HealthBadge score={project.score} label={project.label} />}
      </button>

      {open && (
        <div className="space-y-2 border-t border-gray-100 bg-gray-50/50 px-3 py-3">
          {project.tasks.length === 0 ? (
            <p className="px-2 py-3 text-xs text-gray-400">No tasks in this project yet.</p>
          ) : (
            project.tasks.map((t) => (
              <TaskRow key={t.taskId} task={t} stories={storiesByTask[t.taskId] ?? []} onChanged={onChanged} />
            ))
          )}
        </div>
      )}
    </Card>
  );
}

function UnfiledRow({
  tasks, storiesByTask, onChanged,
}: { tasks: TaskRollup[]; storiesByTask: Record<string, Story[]>; onChanged: () => void }) {
  const [open, setOpen] = useState(true);
  return (
    <Card className="overflow-hidden border-dashed">
      <button onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-gray-50">
        <ChevronRight size={16} className={cn('shrink-0 text-gray-400 transition-transform', open && 'rotate-90')} />
        <ListTodo size={15} className="shrink-0 text-gray-400" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-gray-700">Unfiled work</p>
          <p className="text-[11px] text-gray-400">{tasks.length} task(s) not attached to a project</p>
        </div>
      </button>
      {open && (
        <div className="space-y-2 border-t border-gray-100 bg-gray-50/50 px-3 py-3">
          {tasks.map((t) => (
            <TaskRow key={t.taskId} task={t} stories={storiesByTask[t.taskId] ?? []} onChanged={onChanged} />
          ))}
        </div>
      )}
    </Card>
  );
}

function TaskRow({
  task, stories, onChanged,
}: { task: TaskRollup; stories: Story[]; onChanged: () => void }) {
  const [open, setOpen] = useState(task.blockerCount > 0 || task.isOverdue);
  const hasChildren = stories.length > 0;

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <button
        onClick={() => hasChildren && setOpen((o) => !o)}
        className={cn('flex w-full items-center gap-2.5 px-3 py-2.5 text-left', hasChildren && 'hover:bg-gray-50')}
      >
        <ChevronRight
          size={14}
          className={cn('shrink-0 text-gray-300 transition-transform', open && 'rotate-90', !hasChildren && 'invisible')}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-gray-800">{task.title}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px]">
            <span className="capitalize text-gray-400">{humanize(task.status)}</span>
            {task.storyCount > 0 && (
              <span className="text-gray-400">· {task.doneStoryCount}/{task.storyCount} stories</span>
            )}
            {task.blockerCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 font-semibold text-red-700">
                <Ban size={9} /> {task.blockerCount} blocker{task.blockerCount > 1 ? 's' : ''}
              </span>
            )}
            {task.stalledCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 font-medium text-amber-600">
                <Clock size={9} /> {task.stalledCount} stalled
              </span>
            )}
            {task.isOverdue && (
              <span className="inline-flex items-center gap-1 rounded bg-red-100 px-1.5 py-0.5 font-semibold text-red-700">
                <AlertTriangle size={9} /> overdue
              </span>
            )}
          </div>
        </div>
        <ProgressBar pct={task.progressPct} />
      </button>

      {open && hasChildren && (
        <div className="space-y-2 border-t border-gray-100 px-3 py-2.5">
          {stories.map((s) => (
            <StoryCard key={s.id} story={s} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  );
}
