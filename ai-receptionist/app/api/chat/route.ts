import { NextResponse } from "next/server";
import { agency } from "@/config/agency";
import { hasApiKey, respond } from "@/lib/claude";
import { createConversation, getConversation } from "@/lib/store";

export const runtime = "nodejs";

interface ChatRequest {
  conversationId?: string;
  message?: string;
  pageUrl?: string;
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
  if (message.length > 2000) {
    return NextResponse.json({ error: "message is too long" }, { status: 400 });
  }

  // An unknown id means the server restarted under an open widget; start fresh
  // rather than 404-ing a visitor who is mid-sentence.
  const conversation =
    (body.conversationId ? getConversation(body.conversationId) : undefined) ??
    createConversation(body.pageUrl);

  try {
    const reply = await respond(conversation.id, message);
    return NextResponse.json({
      conversationId: conversation.id,
      reply,
      demoMode: !hasApiKey(),
    });
  } catch (error) {
    console.error("[chat] failed:", error);
    return NextResponse.json(
      {
        conversationId: conversation.id,
        reply: `Sorry — something went wrong on our end. You can reach us directly at ${agency.phone}.`,
        error: true,
      },
      { status: 200 },
    );
  }
}
