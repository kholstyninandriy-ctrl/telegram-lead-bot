/**
 * Appointment slots, expressed in the agency's own timezone.
 *
 * Slots are generated from the agency config (working days, opening hours,
 * appointment length) rather than stored, so changing office hours is a config
 * edit and nothing more.
 */
import { agency } from "@/config/agency";
import { bookedSlots } from "./store";

export interface Slot {
  /** Exact instant, in UTC. This is what we store and send to Google Calendar. */
  iso: string;
  /** Human label in the agency's timezone, e.g. "Tue, Sep 23 at 10:00 AM". */
  label: string;
}

/** How far ahead of the given instant the timezone runs, in milliseconds. */
function tzOffsetMs(date: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
    .formatToParts(date)
    .filter((p) => p.type !== "literal");

  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value ?? 0);
  // Some ICU builds report midnight as hour 24 in hour12:false mode.
  const asUtc = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour") % 24,
    get("minute"),
    get("second"),
  );
  return asUtc - date.getTime();
}

/** Turn a wall-clock time in `timeZone` into the matching UTC instant. */
function zonedTimeToUtc(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  timeZone: string,
): Date {
  const naive = Date.UTC(year, month - 1, day, hour, minute);
  // One refinement pass settles the ambiguity around DST transitions.
  let ts = naive - tzOffsetMs(new Date(naive), timeZone);
  ts = naive - tzOffsetMs(new Date(ts), timeZone);
  return new Date(ts);
}

function zonedParts(date: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);

  const value = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const weekdayIndex = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(value("weekday"));
  return {
    year: Number(value("year")),
    month: Number(value("month")),
    day: Number(value("day")),
    weekday: weekdayIndex,
  };
}

export function formatSlot(iso: string): string {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: agency.timezone,
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

/**
 * Open slots over the next `days` days.
 *
 * Skips non-working days, anything already booked, and anything less than two
 * hours out — nobody can make a tour that starts in ten minutes. `perDay` keeps
 * the list spread across days so the assistant can offer a real choice of days
 * rather than four consecutive times this morning.
 */
export function availableSlots(days = 7, limit = 12, perDay = 4): Slot[] {
  const now = Date.now();
  const earliest = now + 2 * 60 * 60 * 1000;
  const taken = new Set(bookedSlots());
  const slots: Slot[] = [];

  for (let dayOffset = 0; dayOffset < days && slots.length < limit; dayOffset++) {
    const dayAnchor = new Date(now + dayOffset * 24 * 60 * 60 * 1000);
    const { year, month, day, weekday } = zonedParts(dayAnchor, agency.timezone);
    if (!agency.workingDays.includes(weekday)) continue;

    let onThisDay = 0;
    for (
      let minutes = agency.openHour * 60;
      minutes < agency.closeHour * 60 && slots.length < limit && onThisDay < perDay;
      minutes += agency.appointmentMinutes
    ) {
      const start = zonedTimeToUtc(
        year,
        month,
        day,
        Math.floor(minutes / 60),
        minutes % 60,
        agency.timezone,
      );
      const iso = start.toISOString();
      if (start.getTime() < earliest || taken.has(iso)) continue;
      slots.push({ iso, label: formatSlot(iso) });
      onThisDay++;
    }
  }

  return slots;
}

/**
 * True when `iso` is a real, still-free slot — guards against invented times.
 * Unlike the offer list, this checks every slot in the window, not a sample.
 */
export function isSlotAvailable(iso: string): boolean {
  return availableSlots(14, 500, 1000).some((slot) => slot.iso === iso);
}
