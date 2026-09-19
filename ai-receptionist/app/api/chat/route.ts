import { NextResponse } from "next/server";
import { agency } from "@/config/agency";
import { hasApiKey, respond } from "@/lib/claude";
import { appendTurns, ensureConversation, syncTranscript } from "@/lib/store";
import type { UiMessage } from "@/lib/types";

export const runtime = "nodejs";

const MAX_MESSAGE_CHARS = 2000;
const MAX_HISTORY_TURNS = 60;

interface ChatRequest {
  conversationId?: string;
  message?: string;
  pageUrl?: string;
  /** The conversation so far, as the browser has it. */
  history?: unknown;
}

/** The history arrives from the browser, so nothing in it is trusted as-is. */
function cleanHistory(raw: unknown): UiMessage[] {
  if (!Array.isArray(raw)) return [];

  return raw
    .filter(
      (turn): turn is UiMessage =>
        !!turn &&
        typeof turn === "object" &&
        ((turn as UiMessage).role === "user" || (turn as UiMessage).role === "assistant") &&
        typeof (turn as UiMessage).text === "string",
    )
    .slice(-MAX_HISTORY_TURNS)
    .map((turn) => ({ role: turn.role, text: turn.text.slice(0, MAX_MESSAGE_CHARS) }));
}

export async function POST(request: Request) {
  let body: ChatRequest;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const message = body.message?.trim();
  if (!message) {
    return NextResponse.json({ error: "message is required" }, { status: 400 });
  }
  if (message.length > MAX_MESSAGE_CHARS) {
    return NextResponse.json({ error: "message is too long" }, { status: 400 });
  }

  const history = cleanHistory(body.history);
  const conversation = ensureConversation(body.conversationId, body.pageUrl);
  syncTranscript(conversation.id, history);

  try {
    const reply = await respond(conversation.id, message, history);
    appendTurns(conversation.id, [
      { role: "user", text: message },
      { role: "assistant", text: reply },
    ]);

    return NextResponse.json({
      conversationId: conversation.id,
      reply,
      demoMode: !hasApiKey(),
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    console.error("[chat] failed:", detail);

    return NextResponse.json({
      conversationId: conversation.id,
      reply: `Sorry — something went wrong on our end. You can reach us directly at ${agency.phone}.`,
      error: true,
      // Set DEBUG_ERRORS=1 to see the real reason in the widget while testing.
      detail: process.env.DEBUG_ERRORS === "1" ? detail : undefined,
    });
  }
}
