/**
 * Conversation storage.
 *
 * Step 4 swaps the body of these functions for Supabase queries — the rest of
 * the app only ever talks to this module, so nothing else has to change.
 * Until then everything lives in memory and is lost when the server restarts.
 */
import type Anthropic from "@anthropic-ai/sdk";
import type { Booking, Conversation, Lead } from "./types";

type Db = Map<string, Conversation>;

// Next.js reloads modules on every edit in dev; hanging the Map off globalThis
// keeps open conversations alive across those reloads.
const globalStore = globalThis as unknown as { __aiReceptionistDb?: Db };
const db: Db = (globalStore.__aiReceptionistDb ??= new Map());

export function createConversation(pageUrl?: string): Conversation {
  const now = new Date().toISOString();
  const conversation: Conversation = {
    id: crypto.randomUUID(),
    createdAt: now,
    updatedAt: now,
    pageUrl,
    messages: [],
    lead: {},
    bookings: [],
  };
  db.set(conversation.id, conversation);
  return conversation;
}

export function getConversation(id: string): Conversation | undefined {
  return db.get(id);
}

export function appendMessages(id: string, messages: Anthropic.MessageParam[]): void {
  const conversation = db.get(id);
  if (!conversation) return;
  conversation.messages.push(...messages);
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
