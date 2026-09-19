import Script from "next/script";
import HeroBackdrop from "@/components/HeroBackdrop";
import Logo from "@/components/Logo";
import { agency } from "@/config/agency";
import { formatPrice, listings } from "@/lib/listings";

/**
 * A stand-in agency website, so the widget can be demonstrated in the place it
 * will actually live. Swap this page for the client's real site — or drop the
 * embed.js line onto their site — and nothing else changes.
 *
 * Every control on this page reaches the assistant, because on a demo a dead
 * button reads as a broken product.
 */
export default function HomePage() {
  const featured = listings.filter((listing) => listing.featured);

  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="sticky top-0 z-20 border-b border-white/40 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2.5">
            <span style={{ color: "var(--brand)" }}>
              <Logo size={32} />
            </span>
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

      <section className="relative isolate flex min-h-[86vh] items-center overflow-hidden">
        <HeroBackdrop />

        <div className="mx-auto w-full max-w-3xl px-6 py-20">
          <div className="rounded-3xl bg-white/75 px-8 py-14 text-center shadow-[0_24px_80px_rgba(15,23,42,0.28)] ring-1 ring-white/60 backdrop-blur-2xl sm:px-14">
            <p className="text-sm font-medium uppercase tracking-[0.2em] text-slate-600">
              {agency.city}, {agency.state}
            </p>
            <h1 className="mt-5 text-4xl font-semibold tracking-tight sm:text-5xl">
              Find the right home in {agency.city} — without the runaround.
            </h1>
            <p className="mx-auto mt-5 max-w-xl text-lg text-slate-700">
              {agency.name} specializes in {agency.specialty}. Every inquiry gets an answer in
              seconds, day or night.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <a
                href="#listings"
                className="rounded-lg px-5 py-3 text-sm font-medium text-white shadow-lg transition hover:opacity-90"
                style={{ backgroundColor: "var(--brand)" }}
              >
                Browse listings
              </a>
              <button
                type="button"
                data-ai-receptionist
                data-ai-receptionist-message="I'd like to book a consultation."
                className="rounded-lg border border-slate-300 bg-white/70 px-5 py-3 text-sm font-medium transition hover:border-slate-400 hover:bg-white"
              >
                Book a consultation
              </button>
            </div>
            <p className="mt-9 text-sm text-slate-600">
              ↘︎ Every button on this page reaches the AI receptionist. Try it — or ask the bubble
              in the corner about a two-bedroom in Brooklyn.
            </p>
          </div>
        </div>
      </section>

      <section id="listings" className="scroll-mt-16 border-t border-slate-200 bg-white py-20">
        <div className="mx-auto max-w-6xl px-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">Featured listings</h2>
              <p className="mt-2 text-sm text-slate-500">
                Tap any home and the receptionist picks up the conversation about it.
              </p>
            </div>
            <button
              type="button"
              data-ai-receptionist
              data-ai-receptionist-message="What else do you have that isn't on the website?"
              className="text-sm font-medium transition hover:underline"
              style={{ color: "var(--brand)" }}
            >
              See what else is available →
            </button>
          </div>

          <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {featured.map((listing) => (
              <button
                key={listing.id}
                type="button"
                data-ai-receptionist
                data-ai-receptionist-message={`Tell me about ${listing.address}.`}
                className="group overflow-hidden rounded-2xl border border-slate-200 bg-white text-left transition hover:-translate-y-1 hover:border-slate-300 hover:shadow-2xl"
              >
                <div className="relative h-52 overflow-hidden">
                  <img
                    src={listing.image}
                    alt={`${listing.address}, ${listing.neighborhood}`}
                    width={900}
                    height={600}
                    loading="lazy"
                    className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
                  />
                  <span className="absolute left-3 top-3 rounded-full bg-white/90 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide text-slate-700 backdrop-blur">
                    {listing.neighborhood}
                  </span>
                </div>
                <div className="p-5">
                  <p className="text-lg font-semibold">{formatPrice(listing.price)}</p>
                  <p className="mt-1 text-sm text-slate-600">{listing.address}</p>
                  <p className="mt-3 text-xs text-slate-500">
                    {listing.beds} bd · {listing.baths} ba · {listing.sqft.toLocaleString()} sqft
                  </p>
                  <p
                    className="mt-4 text-xs font-medium opacity-0 transition group-hover:opacity-100"
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

      <footer className="border-t border-slate-200 bg-slate-50 py-12">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 text-sm text-slate-500">
          <p className="flex items-center gap-2 font-medium text-slate-700">
            <span style={{ color: "var(--brand)" }}>
              <Logo size={20} />
            </span>
            {agency.name}
          </p>
          <p>
            {agency.phone} · {agency.email}
          </p>
          <p className="text-xs">Demo site. Listings are illustrative and not offers of sale.</p>
        </div>
      </footer>

      {/* The one line a client adds to their own website. */}
      <Script src="/embed.js" data-color={agency.brandColor} strategy="afterInteractive" />
    </div>
  );
}
