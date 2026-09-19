import { NextResponse } from "next/server";
import { listConversations } from "@/lib/store";

export const runtime = "nodejs";

/** Feeds the /admin table: one row per conversation, with its transcript. */
export async function GET() {
  const rows = listConversations().map((conversation) => ({
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
