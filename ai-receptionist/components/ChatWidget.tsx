"use client";

import { useEffect, useRef, useState } from "react";
import type { UiMessage } from "@/lib/types";

interface Props {
  agencyName: string;
  assistantName: string;
  welcomeMessage: string;
}

const QUICK_REPLIES = ["I'm buying", "I'm selling", "Just browsing"];

export default function ChatWidget({ agencyName, assistantName, welcomeMessage }: Props) {
  const [messages, setMessages] = useState<UiMessage[]>([
    { role: "assistant", text: welcomeMessage },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const conversationId = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  // Keeps the message listener below pointing at the current send().
  const sendRef = useRef<(text: string) => void>(() => {});
  useEffect(() => {
    sendRef.current = send;
  });

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      // The host page can ask us to start with a question already asked —
      // e.g. someone clicked "Ask about this property".
      if (event.source !== window.parent || event.data?.type !== "ai-receptionist:prefill") return;
      if (typeof event.data.text === "string") sendRef.current(event.data.text);
    }

    window.addEventListener("message", onMessage);
    // Tell the host page we can receive messages now.
    window.parent.postMessage({ type: "ai-receptionist:ready" }, "*");
    return () => window.removeEventListener("message", onMessage);
  }, []);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;

    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setInput("");
    setBusy(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversationId: conversationId.current,
          message: trimmed,
          // The browser owns the transcript: the server may be a fresh
          // instance that has never seen this conversation.
          history: messages,
          // The page the widget is embedded on, not the iframe's own URL.
          pageUrl: document.referrer || undefined,
        }),
      });

      const data = await response.json();
      conversationId.current = data.conversationId ?? conversationId.current;
      if (data.detail) console.error("[ai-receptionist]", data.detail);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: data.reply ?? "Sorry, I didn't catch that." },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: "I lost the connection for a second — could you resend that?" },
      ]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  const showQuickReplies = messages.length === 1 && !busy;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-black/5">
      <header
        className="flex items-center gap-3 px-4 py-3 text-white"
        style={{ backgroundColor: "var(--brand)" }}
      >
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 text-sm font-semibold">
          {assistantName.slice(0, 1)}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{assistantName}</p>
          <p className="truncate text-xs text-white/80">{agencyName} · replies instantly</p>
        </div>
        <button
          type="button"
          aria-label="Close chat"
          onClick={() => window.parent.postMessage({ type: "ai-receptionist:close" }, "*")}
          className="rounded-full p-1.5 text-white/80 transition hover:bg-white/20 hover:text-white"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path
              d="M4 4l8 8M12 4l-8 8"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto bg-slate-50 px-4 py-4">
        {messages.map((message, index) => (
          <div
            key={index}
            className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
          >
            <div
              className={
                message.role === "user"
                  ? "max-w-[82%] rounded-2xl rounded-br-sm px-3.5 py-2.5 text-sm text-white"
                  : "max-w-[82%] whitespace-pre-line rounded-2xl rounded-bl-sm bg-white px-3.5 py-2.5 text-sm text-slate-700 shadow-sm ring-1 ring-slate-200"
              }
              style={message.role === "user" ? { backgroundColor: "var(--brand)" } : undefined}
            >
              {message.text}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex justify-start">
            <div className="flex gap-1 rounded-2xl rounded-bl-sm bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200">
              {[0, 1, 2].map((i) => (
                <span key={i} className="typing-dot h-1.5 w-1.5 rounded-full bg-slate-400" />
              ))}
            </div>
          </div>
        )}

        {showQuickReplies && (
          <div className="flex flex-wrap gap-2 pt-1">
            {QUICK_REPLIES.map((reply) => (
              <button
                key={reply}
                type="button"
                onClick={() => send(reply)}
                className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-400 hover:text-slate-900"
              >
                {reply}
              </button>
            ))}
          </div>
        )}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
        className="flex items-center gap-2 border-t border-slate-200 bg-white px-3 py-3"
      >
        <input
          ref={inputRef}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Type your message…"
          maxLength={2000}
          className="min-w-0 flex-1 rounded-full bg-slate-100 px-4 py-2.5 text-sm text-slate-800 outline-none placeholder:text-slate-400 focus:bg-slate-50 focus:ring-2 focus:ring-slate-300"
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          aria-label="Send message"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-white transition disabled:opacity-40"
          style={{ backgroundColor: "var(--brand)" }}
        >
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path
              d="M3 10l14-6-6 14-2-6-6-2z"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
        </button>
      </form>
    </div>
  );
}
