import { serverGet } from '@/lib/api/server';
import type { CalendarEvent, UnloggedMeeting, CalendarSlot } from '@/lib/api/types';
import { BackendDown } from '@/components/backend-down';
import { CalendarView } from '@/components/calendar/calendar-view';

export const dynamic = 'force-dynamic';
export const metadata = { title: 'Calendar — Kora' };

export default async function CalendarPage() {
  let todayEvents: CalendarEvent[];
  let unlogged: UnloggedMeeting[];
  let slots: CalendarSlot[];
  try {
    [todayEvents, unlogged, slots] = await Promise.all([
      serverGet<CalendarEvent[]>('/api/calendar/today'),
      serverGet<UnloggedMeeting[]>('/api/calendar/unlogged'),
      serverGet<CalendarSlot[]>('/api/calendar/availability'),
    ]);
  } catch {
    return <BackendDown />;
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Calendar</h1>
        <p className="mt-1 text-sm text-gray-500">
          Today&apos;s meetings, unlogged events, and scheduling.
        </p>
      </header>
      <CalendarView todayEvents={todayEvents} unlogged={unlogged} slots={slots} />
    </div>
  );
}
