/**
 * Conversation storage.
 *
 * Backed by Supabase when it is configured, and by an in-memory map when it is
 * not, so the app runs from a fresh clone with no database. Everything here is
 * async because the database is; nothing else in the app knows which backend
 * is in play.
 *
 * The chat itself never depends on a successful read: the browser replays the
 * transcript on every message. A failed write costs a row in the admin view,
 * never the conversation.
 */
import { db, hasDatabase } from "./supabase";
import type { Booking, Conversation, Lead, UiMessage } from "./types";

type Memory = Map<string, Conversation>;

// Next.js reloads modules on every edit in dev; hanging the map off globalThis
// keeps open conversations alive across those reloads.
const globalStore = globalThis as unknown as { __aiReceptionistDb?: Memory };
const memory: Memory = (globalStore.__aiReceptionistDb ??= new Map());

interface ConversationRow {
  id: string;
  created_at: string;
  updated_at: string;
  page_url: string | null;
  transcript: UiMessage[] | null;
  lead: Lead | null;
}

interface BookingRow {
  id: string;
  starts_at: string;
  kind: string;
  listing_id: string | null;
  name: string;
  email: string;
  phone: string | null;
  calendar_event_id: string | null;
  conversation_id: string;
}

function toBooking(row: BookingRow): Booking {
  return {
    id: row.id,
    startsAt: new Date(row.starts_at).toISOString(),
    kind: row.kind === "tour" ? "tour" : "call",
    listingId: row.listing_id ?? undefined,
    name: row.name,
    email: row.email,
    phone: row.phone ?? undefined,
    calendarEventId: row.calendar_event_id ?? undefined,
  };
}

function blank(id: string, pageUrl?: string): Conversation {
  const now = new Date().toISOString();
  return {
    id,
    createdAt: now,
    updatedAt: now,
    pageUrl,
    transcript: [],
    lead: {},
    bookings: [],
  };
}

/**
 * Create the conversation if it is new, and store the transcript we were given.
 *
 * A shorter transcript than the one on file means a stale or replayed request,
 * so the stored one wins.
 */
export async function saveConversation(
  id: string,
  transcript: UiMessage[],
  pageUrl?: string,
): Promise<void> {
  if (!hasDatabase) {
    const existing = memory.get(id) ?? blank(id, pageUrl);
    if (transcript.length >= existing.transcript.length) existing.transcript = [...transcript];
    existing.updatedAt = new Date().toISOString();
    memory.set(id, existing);
    return;
  }

  const { data } = await db()
    .from("conversations")
    .select("transcript")
    .eq("id", id)
    .maybeSingle<{ transcript: UiMessage[] | null }>();

  if (data && (data.transcript?.length ?? 0) > transcript.length) return;

  await db()
    .from("conversations")
    .upsert(
      {
        id,
        page_url: pageUrl ?? null,
        transcript,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "id" },
    );
}

/** Merge in whatever the assistant just learned, without erasing known fields. */
export async function updateLead(id: string, patch: Lead): Promise<void> {
  const clean: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(patch)) {
    if (value !== undefined && value !== null && value !== "") clean[key] = value;
  }
  if (Object.keys(clean).length === 0) return;

  if (!hasDatabase) {
    const existing = memory.get(id) ?? blank(id);
    existing.lead = { ...existing.lead, ...clean };
    existing.updatedAt = new Date().toISOString();
    memory.set(id, existing);
    return;
  }

  const { data } = await db()
    .from("conversations")
    .select("lead")
    .eq("id", id)
    .maybeSingle<{ lead: Lead | null }>();

  await db()
    .from("conversations")
    .update({ lead: { ...(data?.lead ?? {}), ...clean }, updated_at: new Date().toISOString() })
    .eq("id", id);
}

export async function addBooking(id: string, booking: Booking): Promise<void> {
  if (!hasDatabase) {
    const existing = memory.get(id) ?? blank(id);
    existing.bookings.push(booking);
    existing.updatedAt = new Date().toISOString();
    memory.set(id, existing);
    return;
  }

  await db().from("bookings").insert({
    id: booking.id,
    conversation_id: id,
    starts_at: booking.startsAt,
    kind: booking.kind,
    listing_id: booking.listingId ?? null,
    name: booking.name,
    email: booking.email,
    phone: booking.phone ?? null,
  });
}

/** Every slot already taken, so the assistant never offers the same time twice. */
export async function bookedSlots(): Promise<string[]> {
  if (!hasDatabase) {
    return [...memory.values()].flatMap((c) => c.bookings.map((b) => b.startsAt));
  }

  const { data } = await db()
    .from("bookings")
    .select("starts_at")
    .gte("starts_at", new Date().toISOString())
    .returns<{ starts_at: string }[]>();

  return (data ?? []).map((row) => new Date(row.starts_at).toISOString());
}

export async function listConversations(limit = 200): Promise<Conversation[]> {
  if (!hasDatabase) {
    return [...memory.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }

  const { data: rows } = await db()
    .from("conversations")
    .select("*")
    .order("updated_at", { ascending: false })
    .limit(limit)
    .returns<ConversationRow[]>();

  const conversations = rows ?? [];
  if (conversations.length === 0) return [];

  const { data: bookingRows } = await db()
    .from("bookings")
    .select("*")
    .in(
      "conversation_id",
      conversations.map((row) => row.id),
    )
    .returns<BookingRow[]>();

  const byConversation = new Map<string, Booking[]>();
  for (const row of bookingRows ?? []) {
    const list = byConversation.get(row.conversation_id) ?? [];
    list.push(toBooking(row));
    byConversation.set(row.conversation_id, list);
  }

  return conversations.map((row) => ({
    id: row.id,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    pageUrl: row.page_url ?? undefined,
    transcript: row.transcript ?? [],
    lead: row.lead ?? {},
    bookings: byConversation.get(row.id) ?? [],
  }));
}
