/**
 * Conversation storage.
 *
 * Step 4 swaps the body of these functions for Supabase queries — the rest of
 * the app only ever talks to this module, so nothing else has to change.
 *
 * Until then this is in-memory, which on a serverless host means best-effort:
 * a later request may land on a different instance and see nothing. The chat
 * itself does not depend on it (the browser replays the transcript), so a lost
 * write costs a row in the admin view, never the conversation.
 */
import type { Booking, Conversation, Lead, UiMessage } from "./types";

type Db = Map<string, Conversation>;

// Next.js reloads modules on every edit in dev; hanging the Map off globalThis
// keeps open conversations alive across those reloads.
const globalStore = globalThis as unknown as { __aiReceptionistDb?: Db };
const db: Db = (globalStore.__aiReceptionistDb ??= new Map());

export function createConversation(id?: string, pageUrl?: string): Conversation {
  const now = new Date().toISOString();
  const conversation: Conversation = {
    id: id || crypto.randomUUID(),
    createdAt: now,
    updatedAt: now,
    pageUrl,
    transcript: [],
    lead: {},
    bookings: [],
  };
  db.set(conversation.id, conversation);
  return conversation;
}

export function getConversation(id: string): Conversation | undefined {
  return db.get(id);
}

/** Get the conversation, recreating the row if this instance has never seen it. */
export function ensureConversation(id: string | undefined, pageUrl?: string): Conversation {
  const existing = id ? db.get(id) : undefined;
  return existing ?? createConversation(id, pageUrl);
}

export function appendTurns(id: string, turns: UiMessage[]): void {
  const conversation = db.get(id);
  if (!conversation) return;
  conversation.transcript.push(...turns);
  conversation.updatedAt = new Date().toISOString();
}

/**
 * Replace the stored transcript with the browser's copy.
 *
 * The browser holds the authoritative history, so this keeps the admin view
 * complete even when earlier turns were handled by a different instance.
 */
export function syncTranscript(id: string, transcript: UiMessage[]): void {
  const conversation = db.get(id);
  if (!conversation) return;
  if (transcript.length < conversation.transcript.length) return;
  conversation.transcript = [...transcript];
  conversation.updatedAt = new Date().toISOString();
}

/** Merge in whatever the assistant just learned, without erasing known fields. */
export function updateLead(id: string, patch: Lead): Lead | undefined {
  const conversation = db.get(id);
  if (!conversation) return undefined;
  for (const [key, value] of Object.entries(patch)) {
    if (value !== undefined && value !== null && value !== "") {
      (conversation.lead as Record<string, unknown>)[key] = value;
    }
  }
  conversation.updatedAt = new Date().toISOString();
  return conversation.lead;
}

export function addBooking(id: string, booking: Booking): void {
  const conversation = db.get(id);
  if (!conversation) return;
  conversation.bookings.push(booking);
  conversation.updatedAt = new Date().toISOString();
}

/** Every slot already taken, so the assistant never offers the same time twice. */
export function bookedSlots(): string[] {
  return [...db.values()].flatMap((c) => c.bookings.map((b) => b.startsAt));
}

export function listConversations(): Conversation[] {
  return [...db.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}
