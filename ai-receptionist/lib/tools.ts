import type Anthropic from "@anthropic-ai/sdk";
import { agency } from "@/config/agency";
import { formatPrice, findListing, searchListings } from "./listings";
import { availableSlots, formatSlot, isSlotAvailable } from "./scheduling";
import { addBooking, updateLead } from "./store";
import type { Booking, Lead } from "./types";

export const tools: Anthropic.Tool[] = [
  {
    name: "search_listings",
    description:
      "Search the agency's current listings. Call this before describing any property — it is the only source of real inventory. Returns at most four matches, cheapest first.",
    input_schema: {
      type: "object",
      properties: {
        minPrice: { type: "number", description: "Lowest acceptable price in USD." },
        maxPrice: { type: "number", description: "Highest acceptable price in USD." },
        minBeds: { type: "number", description: "Minimum number of bedrooms." },
        neighborhood: {
          type: "string",
          description: "Neighborhood name, e.g. 'Mueller'. Partial matches work.",
        },
        propertyType: {
          type: "string",
          enum: ["single-family", "condo", "townhouse"],
          description: "Type of property the visitor wants.",
        },
      },
    },
  },
  {
    name: "save_lead",
    description:
      "Record what you have learned about this visitor. Call it as soon as you learn anything new — a name, a budget, a neighborhood, a timeline — and call it again whenever you learn more. Send only the fields you actually know; previously saved fields are kept. This runs silently; never mention it.",
    input_schema: {
      type: "object",
      properties: {
        name: { type: "string" },
        email: { type: "string" },
        phone: { type: "string" },
        intent: {
          type: "string",
          enum: ["buy", "sell", "rent", "browsing"],
          description: "What the visitor is trying to do.",
        },
        budgetMin: { type: "number", description: "Bottom of their price range in USD." },
        budgetMax: { type: "number", description: "Top of their price range in USD." },
        neighborhoods: {
          type: "array",
          items: { type: "string" },
          description: "Areas they mentioned interest in.",
        },
        propertyType: { type: "string" },
        beds: { type: "number" },
        timeline: {
          type: "string",
          enum: ["asap", "1-3_months", "3-6_months", "6-12_months", "just_looking"],
        },
        preApproved: {
          type: "boolean",
          description: "Whether they already have mortgage pre-approval.",
        },
        notes: {
          type: "string",
          description:
            "Anything else an agent would want to know before the call, in one or two sentences.",
        },
      },
    },
  },
  {
    name: "get_available_slots",
    description:
      "List appointment times that are actually open. Call this before offering any time. Never offer a time this tool did not return.",
    input_schema: {
      type: "object",
      properties: {
        days: {
          type: "number",
          description: "How many days ahead to look. Defaults to 7.",
        },
      },
    },
  },
  {
    name: "book_appointment",
    description:
      "Book a call or an in-person tour in an open slot. Requires a name and an email. Use the exact `iso` value from get_available_slots.",
    input_schema: {
      type: "object",
      properties: {
        iso: {
          type: "string",
          description: "The exact `iso` value of the chosen slot from get_available_slots.",
        },
        kind: {
          type: "string",
          enum: ["call", "tour"],
          description: "A phone call with an agent, or an in-person property tour.",
        },
        name: { type: "string" },
        email: { type: "string" },
        phone: { type: "string" },
        listingId: {
          type: "string",
          description: "Listing id for a tour, e.g. 'HV-1052'. Omit for a general call.",
        },
      },
      required: ["iso", "kind", "name", "email"],
    },
  },
];

/**
 * Runs one tool call and returns the string Claude sees as the tool result.
 *
 * Every failure is returned as a readable message rather than thrown: the model
 * recovers far better from "that slot is taken, here are open ones" than from a
 * 500 that drops the conversation.
 */
export function executeTool(
  name: string,
  input: Record<string, unknown>,
  conversationId: string,
): string {
  switch (name) {
    case "search_listings": {
      const matches = searchListings({
        minPrice: input.minPrice as number | undefined,
        maxPrice: input.maxPrice as number | undefined,
        minBeds: input.minBeds as number | undefined,
        neighborhood: input.neighborhood as string | undefined,
        propertyType: input.propertyType as string | undefined,
      });

      if (matches.length === 0) {
        return "No listings match those criteria. Tell the visitor honestly and offer to widen the budget or the area.";
      }

      return JSON.stringify(
        matches.map((listing) => ({
          id: listing.id,
          address: listing.address,
          neighborhood: listing.neighborhood,
          price: formatPrice(listing.price),
          beds: listing.beds,
          baths: listing.baths,
          sqft: listing.sqft,
          type: listing.propertyType,
          status: listing.status,
          highlights: listing.highlights,
        })),
      );
    }

    case "save_lead": {
      const lead = updateLead(conversationId, input as Lead);
      return lead ? "Saved." : "Conversation not found; nothing saved.";
    }

    case "get_available_slots": {
      const slots = availableSlots(Number(input.days) || 7);
      if (slots.length === 0) {
        return `No open slots in that window. Offer to have someone call them at ${agency.phone}.`;
      }
      return JSON.stringify(slots);
    }

    case "book_appointment": {
      const iso = String(input.iso ?? "");
      if (!isSlotAvailable(iso)) {
        const slots = availableSlots(7, 4);
        return `That time is no longer open. Offer one of these instead: ${JSON.stringify(slots)}`;
      }

      const booking: Booking = {
        id: crypto.randomUUID(),
        startsAt: iso,
        kind: input.kind === "tour" ? "tour" : "call",
        listingId: input.listingId ? String(input.listingId) : undefined,
        name: String(input.name ?? ""),
        email: String(input.email ?? ""),
        phone: input.phone ? String(input.phone) : undefined,
      };

      if (booking.listingId && !findListing(booking.listingId)) {
        return "That listing id does not exist. Run search_listings again and use an id from the results.";
      }

      addBooking(conversationId, booking);
      updateLead(conversationId, {
        name: booking.name,
        email: booking.email,
        phone: booking.phone,
      });

      const where = booking.listingId
        ? ` at ${findListing(booking.listingId)?.address}`
        : "";
      return `Booked: ${booking.kind}${where} on ${formatSlot(iso)}. Confirm this back to the visitor in one sentence.`;
    }

    default:
      return `Unknown tool: ${name}`;
  }
}
