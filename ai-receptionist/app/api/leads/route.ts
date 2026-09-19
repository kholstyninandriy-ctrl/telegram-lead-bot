import { NextResponse } from "next/server";
import { listConversations } from "@/lib/store";

export const runtime = "nodejs";

/**
 * Feeds the /admin table: one row per conversation, with its transcript.
 *
 * Set ADMIN_PASSWORD and the endpoint requires it. Leave it unset and the
 * endpoint is open — fine for a demo with invented leads, not for real ones.
 */
export async function GET(request: Request) {
  const password = process.env.ADMIN_PASSWORD;
  if (password && request.headers.get("x-admin-key") !== password) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const rows = (await listConversations()).map((conversation) => ({
    id: conversation.id,
    createdAt: conversation.createdAt,
    updatedAt: conversation.updatedAt,
    pageUrl: conversation.pageUrl,
    lead: conversation.lead,
    bookings: conversation.bookings,
    messageCount: conversation.transcript.length,
    transcript: conversation.transcript,
  }));

  return NextResponse.json({ conversations: rows });
}
