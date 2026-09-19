import type Anthropic from "@anthropic-ai/sdk";

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

export interface Conversation {
  id: string;
  createdAt: string;
  updatedAt: string;
  pageUrl?: string;
  /** Raw Claude turns — what we replay to the model on every request. */
  messages: Anthropic.MessageParam[];
  lead: Lead;
  bookings: Booking[];
}

/** One row of the transcript as the browser and the admin table see it. */
export interface UiMessage {
  role: "user" | "assistant";
  text: string;
}
