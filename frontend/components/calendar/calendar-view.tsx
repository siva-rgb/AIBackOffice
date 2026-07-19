'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Video, Calendar, Clock, Users, ExternalLink, CheckCircle } from 'lucide-react';
import { Card, CardHeader } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import { cn } from '@/lib/utils';
import type { CalendarEvent, UnloggedMeeting, CalendarSlot } from '@/lib/api/types';

interface Props {
  todayEvents: CalendarEvent[];
  unlogged: UnloggedMeeting[];
  slots: CalendarSlot[];
}

interface ScheduleForm {
  title: string;
  startDatetime: string;
  durationMinutes: number;
  attendeeEmails: string;
  description: string;
}

const EMPTY_FORM: ScheduleForm = {
  title: '',
  startDatetime: '',
  durationMinutes: 60,
  attendeeEmails: '',
  description: '',
};

export function CalendarView({ todayEvents, unlogged, slots }: Props) {
  const router = useRouter();
  const [form, setForm] = useState<ScheduleForm>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [scheduleSuccess, setScheduleSuccess] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [loggingId, setLoggingId] = useState<string | null>(null);
  const [loggedIds, setLoggedIds] = useState<Set<string>>(new Set());

  function prefillFromSlot(slot: CalendarSlot) {
    const dt = new Date(slot.start);
    const local = new Date(dt.getTime() - dt.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
    setForm((f) => ({ ...f, startDatetime: local }));
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  }

  async function handleSchedule(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setScheduleError(null);
    setScheduleSuccess(false);
    try {
      const res = await authedFetch('/api/calendar/schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: form.title,
          startDatetime: new Date(form.startDatetime).toISOString(),
          durationMinutes: form.durationMinutes,
          attendeeEmails: form.attendeeEmails
            .split(/[,\n]+/)
            .map((e) => e.trim())
            .filter(Boolean),
          description: form.description,
        }),
      });
      if (!res.ok) throw new Error('Scheduling failed');
      setScheduleSuccess(true);
      setForm(EMPTY_FORM);
    } catch (err: unknown) {
      setScheduleError(err instanceof Error ? err.message : 'Failed to schedule');
    } finally {
      setSubmitting(false);
    }
  }

  async function logMeeting(event: UnloggedMeeting) {
    setLoggingId(event.eventId);
    try {
      const res = await authedFetch('/api/meetings/quick-note', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notes: event.title,
          clientId: event.clientIds[0] ?? null,
          meetingDate: event.date,
          title: event.title,
        }),
      });
      if (!res.ok) throw new Error('Failed');
      setLoggedIds((s) => new Set([...s, event.eventId]));
      router.refresh();
    } catch {
      // silently fail — user can retry
    } finally {
      setLoggingId(null);
    }
  }

  return (
    <div className="space-y-6">
      {/* Today's meetings */}
      <Card>
        <CardHeader
          title="Today's meetings"
          subtitle={`${todayEvents.length} event${todayEvents.length !== 1 ? 's' : ''} today`}
        />
        {todayEvents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <Calendar size={28} className="text-gray-300" />
            <p className="mt-3 text-sm font-medium text-gray-500">No meetings today</p>
            <p className="mt-1 text-xs text-gray-400">
              Connect Google Calendar in Settings to see your schedule.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {todayEvents.map((ev) => (
              <li key={ev.id} className="flex items-start gap-3 px-5 py-3.5">
                <Clock size={16} className="mt-0.5 shrink-0 text-gray-400" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-900">{ev.title}</p>
                  <p className="mt-0.5 text-xs text-gray-500">
                    {new Date(ev.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    {ev.clientNames.length > 0 && (
                      <> · {ev.clientNames.join(', ')}</>
                    )}
                  </p>
                </div>
                {ev.meetLink && (
                  <a
                    href={ev.meetLink}
                    target="_blank"
                    rel="noreferrer"
                    className="flex shrink-0 items-center gap-1 rounded-md bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
                  >
                    <Video size={12} /> Join
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Available time slots */}
      {slots.length > 0 && (
        <Card>
          <CardHeader title="Available slots" subtitle="Click to prefill the schedule form below" />
          <div className="flex flex-wrap gap-2 px-5 py-4">
            {slots.map((slot) => (
              <button
                key={slot.start}
                onClick={() => prefillFromSlot(slot)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-left text-xs font-medium text-gray-700 hover:border-kora-300 hover:bg-kora-50 transition-colors"
              >
                {slot.label}
              </button>
            ))}
          </div>
        </Card>
      )}

      {/* Unlogged meetings */}
      {unlogged.length > 0 && (
        <Card>
          <CardHeader
            title="Unlogged meetings"
            subtitle="Past meetings from your calendar not yet in Kora"
          />
          <ul className="divide-y divide-gray-100">
            {unlogged.map((ev) => {
              const isLogged = loggedIds.has(ev.eventId);
              return (
                <li key={ev.eventId} className="flex items-start gap-3 px-5 py-3.5">
                  <Users size={16} className="mt-0.5 shrink-0 text-gray-400" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-gray-900">{ev.title}</p>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {new Date(ev.date).toLocaleDateString()}
                      {ev.clientNames.length > 0 && <> · {ev.clientNames.join(', ')}</>}
                    </p>
                  </div>
                  {isLogged ? (
                    <span className="flex shrink-0 items-center gap-1 text-xs text-emerald-600">
                      <CheckCircle size={13} /> Logged
                    </span>
                  ) : (
                    <button
                      onClick={() => logMeeting(ev)}
                      disabled={loggingId === ev.eventId}
                      className="shrink-0 rounded-md border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                    >
                      {loggingId === ev.eventId ? 'Logging…' : 'Log this'}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      {/* Schedule a meeting */}
      <Card>
        <CardHeader title="Schedule a meeting" subtitle="Creates a Google Meet event — queued for your approval" />
        <form onSubmit={handleSchedule} className="space-y-4 px-5 py-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Title *</label>
              <input
                required
                type="text"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                placeholder="Meeting with client"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Date & time *</label>
              <input
                required
                type="datetime-local"
                value={form.startDatetime}
                onChange={(e) => setForm((f) => ({ ...f, startDatetime: e.target.value }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
              />
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Duration</label>
              <select
                value={form.durationMinutes}
                onChange={(e) => setForm((f) => ({ ...f, durationMinutes: Number(e.target.value) }))}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
              >
                <option value={30}>30 minutes</option>
                <option value={60}>60 minutes</option>
                <option value={90}>90 minutes</option>
                <option value={120}>2 hours</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">
                Attendee emails <span className="text-gray-400">(comma or newline separated)</span>
              </label>
              <textarea
                rows={2}
                value={form.attendeeEmails}
                onChange={(e) => setForm((f) => ({ ...f, attendeeEmails: e.target.value }))}
                placeholder="client@example.com"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
            <textarea
              rows={2}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="Optional agenda or notes"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-kora-500"
            />
          </div>

          {scheduleSuccess && (
            <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
              <CheckCircle size={16} />
              Queued for approval — check the Manager page to confirm.
            </div>
          )}
          {scheduleError && (
            <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{scheduleError}</div>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={submitting}
              className="flex items-center gap-2 rounded-lg bg-kora-600 px-4 py-2 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-50"
            >
              <ExternalLink size={14} />
              {submitting ? 'Scheduling…' : 'Schedule meeting'}
            </button>
          </div>
        </form>
      </Card>
    </div>
  );
}
