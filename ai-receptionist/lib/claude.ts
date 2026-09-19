import Anthropic from "@anthropic-ai/sdk";
import { agency } from "@/config/agency";
import { systemPrompt } from "./prompt";
import { executeTool, tools } from "./tools";
import type { UiMessage } from "./types";

/** Claude Opus 5 is the default. Set CLAUDE_MODEL=claude-sonnet-5 for a cheaper, faster demo. */
const MODEL = process.env.CLAUDE_MODEL || "claude-opus-5";

/** A runaway tool loop would burn tokens silently; six rounds is far more than a booking needs. */
const MAX_TOOL_ROUNDS = 6;

/** Plenty for a receptionist chat, and it caps what one conversation can cost. */
const MAX_HISTORY_TURNS = 40;

export const hasApiKey = () => Boolean(process.env.ANTHROPIC_API_KEY);

let client: Anthropic | null = null;
function getClient(): Anthropic {
  client ??= new Anthropic();
  return client;
}

function textOf(content: Anthropic.ContentBlock[]): string {
  return content
    .filter((block): block is Anthropic.TextBlock => block.type === "text")
    .map((block) => block.text)
    .join("\n")
    .trim();
}

/**
 * Turn the visible transcript into API messages.
 *
 * A conversation opens with the assistant's greeting, but the API requires the
 * first message to be from the user — so leading assistant turns are dropped.
 */
function toMessages(history: UiMessage[], userText: string): Anthropic.MessageParam[] {
  const recent = history.slice(-MAX_HISTORY_TURNS);
  const firstUser = recent.findIndex((turn) => turn.role === "user");
  const usable = firstUser === -1 ? [] : recent.slice(firstUser);

  return [
    ...usable.map((turn) => ({ role: turn.role, content: turn.text })),
    { role: "user" as const, content: userText },
  ];
}

/**
 * Feed one visitor message through the receptionist and return what it says.
 *
 * `history` is the conversation so far as the visitor saw it. Tool calls (lead
 * capture, listing search, booking) run inside this one request and are never
 * replayed on the next one — only the resulting text is.
 */
export async function respond(
  conversationId: string,
  userText: string,
  history: UiMessage[],
): Promise<string> {
  if (!hasApiKey()) return demoReply(history.length);

  const anthropic = getClient();
  const messages = toMessages(history, userText);

  for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
    const response = await anthropic.messages.create({
      model: MODEL,
      max_tokens: 1024,
      // The persona never varies within a deployment, so it caches cleanly and
      // costs ~10% of full price on every turn after the first.
      system: [{ type: "text", text: systemPrompt(), cache_control: { type: "ephemeral" } }],
      output_config: { effort: "low" },
      tools,
      messages,
    });

    if (response.stop_reason === "refusal") {
      return `I'm not able to help with that one — but I can get you to a person. Call us at ${agency.phone}.`;
    }

    const toolUses = response.content.filter(
      (block): block is Anthropic.ToolUseBlock => block.type === "tool_use",
    );

    if (toolUses.length === 0) {
      return textOf(response.content) || "Sorry, could you say that another way?";
    }

    // Within one request the assistant turn must be echoed back whole, tool
    // blocks and all, and every result goes back in a single user message.
    messages.push({ role: "assistant", content: response.content });
    messages.push({
      role: "user",
      content: toolUses.map((toolUse) => ({
        type: "tool_result" as const,
        tool_use_id: toolUse.id,
        content: executeTool(
          toolUse.name,
          (toolUse.input ?? {}) as Record<string, unknown>,
          conversationId,
        ),
      })),
    });
  }

  return `Let me get an agent on this with you — you can reach us at ${agency.phone}.`;
}

/**
 * Scripted stand-in so the widget is testable before any API key exists.
 * Replaced entirely by the real model the moment ANTHROPIC_API_KEY is set.
 */
function demoReply(turnCount: number): string {
  const script = [
    `Happy to help! What's your price range, roughly?`,
    `Got it. Which parts of ${agency.city} are you looking at?`,
    `Good choice. Are you hoping to move soon, or still early in the search?`,
    `That helps. What's the best email to send matching listings to?`,
    `Perfect — would Tuesday at 10am or Wednesday at 2pm work for a quick call with one of our agents?`,
  ];
  const index = Math.min(Math.floor(turnCount / 2), script.length - 1);
  return `${script[index]}\n\n(Demo mode — add ANTHROPIC_API_KEY for real AI replies.)`;
}
