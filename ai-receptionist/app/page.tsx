import Script from "next/script";
import { agency } from "@/config/agency";
import { formatPrice, listings } from "@/lib/listings";

/**
 * A stand-in agency website, so the widget can be demonstrated in the place it
 * will actually live. Swap this page for the client's real site — or drop the
 * embed.js line onto their site — and nothing else changes.
 */
export default function HomePage() {
  const featured = listings.filter((l) => l.status === "active").slice(0, 6);

  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2.5">
            <div
              className="h-8 w-8 rounded-lg"
              style={{ backgroundColor: "var(--brand)" }}
              aria-hidden="true"
            />
            <span className="text-lg font-semibold tracking-tight">{agency.name}</span>
          </div>
          <nav className="hidden items-center gap-7 text-sm text-slate-600 sm:flex">
            <a href="#listings" className="transition hover:text-slate-900">
              Buy
            </a>
            <button
              type="button"
              data-ai-receptionist
              data-ai-receptionist-message="I'm thinking about selling my home."
              className="transition hover:text-slate-900"
            >
              Sell
            </button>
            <button
              type="button"
              data-ai-receptionist
              data-ai-receptionist-message="Can I speak with one of your agents?"
              className="transition hover:text-slate-900"
            >
              Agents
            </button>
            <a href={`tel:${agency.phone.replace(/\D/g, "")}`} className="font-medium text-slate-900">
              {agency.phone}
            </a>
          </nav>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-6 pb-16 pt-20 text-center">
        <p className="text-sm font-medium uppercase tracking-widest text-slate-500">
          {agency.city}, {agency.state}
        </p>
        <h1 className="mx-auto mt-4 max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
          Find the right home in {agency.city} — without the runaround.
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-lg text-slate-600">
          {agency.name} specializes in {agency.specialty}. Every inquiry gets an answer in
          seconds, day or night.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <a
            href="#listings"
            className="rounded-lg px-5 py-3 text-sm font-medium text-white transition hover:opacity-90"
            style={{ backgroundColor: "var(--brand)" }}
          >
            Browse listings
          </a>
          <button
            type="button"
            data-ai-receptionist
            data-ai-receptionist-message="I'd like to book a consultation."
            className="rounded-lg border border-slate-300 px-5 py-3 text-sm font-medium transition hover:border-slate-400 hover:bg-slate-50"
          >
            Book a consultation
          </button>
        </div>
        <p className="mt-10 text-sm text-slate-500">
          ↘︎ Every button on this page reaches the AI receptionist. Try it — or ask the bubble
          in the corner about a three-bedroom under $600k.
        </p>
      </section>

      <section id="listings" className="scroll-mt-16 border-t border-slate-200 bg-slate-50 py-16">
        <div className="mx-auto max-w-6xl px-6">
          <h2 className="text-2xl font-semibold tracking-tight">Featured listings</h2>
          <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {featured.map((listing) => (
              <button
                key={listing.id}
                type="button"
                data-ai-receptionist
                data-ai-receptionist-message={`Tell me about ${listing.address}.`}
                className="group overflow-hidden rounded-xl border border-slate-200 bg-white text-left transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-lg"
              >
                <div className="flex h-36 items-center justify-center bg-gradient-to-br from-slate-200 to-slate-300 text-xs font-medium uppercase tracking-widest text-slate-500">
                  {listing.neighborhood}
                </div>
                <div className="p-5">
                  <p className="text-lg font-semibold">{formatPrice(listing.price)}</p>
                  <p className="mt-1 text-sm text-slate-600">{listing.address}</p>
                  <p className="mt-3 text-xs text-slate-500">
                    {listing.beds} bd · {listing.baths} ba · {listing.sqft.toLocaleString()} sqft
                  </p>
                  <p
                    className="mt-3 text-xs font-medium opacity-0 transition group-hover:opacity-100"
                    style={{ color: "var(--brand)" }}
                  >
                    Ask about this home →
                  </p>
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-200 py-10">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 text-sm text-slate-500">
          <p className="font-medium text-slate-700">{agency.name}</p>
          <p>
            {agency.phone} · {agency.email}
          </p>
          <p className="text-xs">
            Demo site. Listings are illustrative and not offers of sale.
          </p>
        </div>
      </footer>

      {/* The one line a client adds to their own website. */}
      <Script src="/embed.js" data-color={agency.brandColor} strategy="afterInteractive" />
    </div>
  );
}
