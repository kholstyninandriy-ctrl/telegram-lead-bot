import { NextResponse } from "next/server";
import { listConversations } from "@/lib/store";
import type { UiMessage } from "@/lib/types";

export const runtime = "nodejs";

/** Feeds the /admin table: one row per conversation, with its transcript. */
export async function GET() {
  const rows = listConversations().map((conversation) => {
    const transcript: UiMessage[] = [];

    for (const message of conversation.messages) {
      // The SDK's role union also allows "system"; we never write those turns.
      if (message.role !== "user" && message.role !== "assistant") continue;
      const role = message.role;

      // Plain-string turns come from the demo responder; block arrays from Claude.
      if (typeof message.content === "string") {
        transcript.push({ role, text: message.content });
        continue;
      }
      // Tool calls and tool results are part of the machinery, not the chat —
      // the admin view only shows what the visitor actually saw.
      for (const block of message.content) {
        if (block.type === "text") {
          transcript.push({ role, text: block.text });
        }
      }
    }

    return {
      id: conversation.id,
      createdAt: conversation.createdAt,
      updatedAt: conversation.updatedAt,
      pageUrl: conversation.pageUrl,
      lead: conversation.lead,
      bookings: conversation.bookings,
      messageCount: transcript.length,
      transcript,
    };
  });

  return NextResponse.json({ conversations: rows });
}
