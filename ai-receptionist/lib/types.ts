export type Intent = "buy" | "sell" | "rent" | "browsing";
export type Timeline = "asap" | "1-3_months" | "3-6_months" | "6-12_months" | "just_looking";

/** Everything the receptionist manages to learn about the visitor. */
export interface Lead {
  name?: string;
  email?: string;
  phone?: string;
  intent?: Intent;
  budgetMin?: number;
  budgetMax?: number;
  neighborhoods?: string[];
  propertyType?: string;
  beds?: number;
  timeline?: Timeline;
  preApproved?: boolean;
  notes?: string;
}

export interface Booking {
  id: string;
  startsAt: string; // ISO 8601, UTC
  kind: "call" | "tour";
  listingId?: string;
  name: string;
  email: string;
  phone?: string;
  /** Set once the slot is mirrored into Google Calendar (step 5). */
  calendarEventId?: string;
}

/**
 * One line of the conversation, exactly as the visitor saw it.
 *
 * The transcript is deliberately plain text rather than raw API content
 * blocks: tool calls and the model's internal reasoning belong to a single
 * request and replaying them across turns is what broke the deployed chat.
 * Text replays safely on any model, survives a server restart, and is what
 * the admin view wants anyway.
 */
export interface UiMessage {
  role: "user" | "assistant";
  text: string;
}

export interface Conversation {
  id: string;
  createdAt: string;
  updatedAt: string;
  pageUrl?: string;
  transcript: UiMessage[];
  lead: Lead;
  bookings: Booking[];
}
