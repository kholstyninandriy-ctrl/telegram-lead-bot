"use client";

import { useEffect, useState } from "react";
import type { Booking, Lead, UiMessage } from "@/lib/types";

interface Row {
  id: string;
  createdAt: string;
  updatedAt: string;
  pageUrl?: string;
  lead: Lead;
  bookings: Booking[];
  messageCount: number;
  transcript: UiMessage[];
}

const money = (value?: number) =>
  value === undefined
    ? null
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(value);

function budget(lead: Lead): string {
  const min = money(lead.budgetMin);
  const max = money(lead.budgetMax);
  if (min && max) return `${min} – ${max}`;
  return max ? `up to ${max}` : min ? `from ${min}` : "—";
}

/** A lead is "qualified" once an agent could actually act on it. */
function isQualified(lead: Lead): boolean {
  return Boolean((lead.email || lead.phone) && (lead.budgetMax || lead.intent));
}

export default function AdminPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const response = await fetch("/api/leads");
        const data = await response.json();
        if (!cancelled) setRows(data.conversations ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    const timer = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const bookingCount = rows.reduce((sum, row) => sum + row.bookings.length, 0);
  const qualifiedCount = rows.filter((row) => isQualified(row.lead)).length;

  return (
    <main className="min-h-screen bg-slate-50 px-6 py-10 text-slate-900">
      <div className="mx-auto max-w-5xl">
        <h1 className="text-2xl font-semibold tracking-tight">Leads</h1>
        <p className="mt-1 text-sm text-slate-500">
          Every conversation the receptionist has had, and what it learned.
        </p>

        <div className="mt-6 grid grid-cols-3 gap-4">
          {[
            { label: "Conversations", value: rows.length },
            { label: "Qualified leads", value: qualifiedCount },
            { label: "Appointments booked", value: bookingCount },
          ].map((stat) => (
            <div key={stat.label} className="rounded-xl border border-slate-200 bg-white p-5">
              <p className="text-3xl font-semibold tabular-nums">{stat.value}</p>
              <p className="mt-1 text-xs uppercase tracking-wide text-slate-500">{stat.label}</p>
            </div>
          ))}
        </div>

        <div className="mt-8 space-y-3">
          {loading && <p className="text-sm text-slate-500">Loading…</p>}

          {!loading && rows.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white p-10 text-center">
              <p className="text-sm text-slate-500">
                No conversations yet. Open the demo site and talk to the widget.
              </p>
            </div>
          )}

          {rows.map((row) => {
            const isOpen = expanded === row.id;
            return (
              <div key={row.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                <button
                  type="button"
                  onClick={() => setExpanded(isOpen ? null : row.id)}
                  className="flex w-full items-start gap-4 px-5 py-4 text-left transition hover:bg-slate-50"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{row.lead.name || "Unnamed visitor"}</span>
                      {row.lead.intent && (
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                          {row.lead.intent}
                        </span>
                      )}
                      {row.bookings.length > 0 && (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
                          booked
                        </span>
                      )}
                    </div>
                    <p className="mt-1 truncate text-sm text-slate-500">
                      {[row.lead.email, row.lead.phone].filter(Boolean).join(" · ") ||
                        "no contact details yet"}
                    </p>
                    <p className="mt-1 text-xs text-slate-400">
                      {budget(row.lead)}
                      {row.lead.neighborhoods?.length
                        ? ` · ${row.lead.neighborhoods.join(", ")}`
                        : ""}
                      {row.lead.timeline ? ` · ${row.lead.timeline.replace(/_/g, " ")}` : ""}
                      {` · ${row.messageCount} messages`}
                    </p>
                  </div>
                  <span className="mt-1 text-xs text-slate-400">
                    {new Date(row.updatedAt).toLocaleString()}
                  </span>
                </button>

                {isOpen && (
                  <div className="border-t border-slate-200 bg-slate-50 px-5 py-4">
                    {row.lead.notes && (
                      <p className="mb-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                        {row.lead.notes}
                      </p>
                    )}

                    {row.bookings.map((booking) => (
                      <p key={booking.id} className="mb-3 text-sm font-medium text-emerald-700">
                        {booking.kind === "tour" ? "Tour" : "Call"} ·{" "}
                        {new Date(booking.startsAt).toLocaleString()}
                        {booking.listingId ? ` · ${booking.listingId}` : ""}
                      </p>
                    ))}

                    <div className="space-y-2">
                      {row.transcript.map((message, index) => (
                        <div
                          key={index}
                          className={
                            message.role === "user" ? "flex justify-end" : "flex justify-start"
                          }
                        >
                          <p
                            className={
                              message.role === "user"
                                ? "max-w-[80%] rounded-xl bg-slate-800 px-3 py-2 text-sm text-white"
                                : "max-w-[80%] whitespace-pre-line rounded-xl bg-white px-3 py-2 text-sm text-slate-700 ring-1 ring-slate-200"
                            }
                          >
                            {message.text}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </main>
  );
}
