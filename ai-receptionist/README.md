# AI Receptionist

A chat receptionist for real estate agencies. It answers questions about
listings, qualifies the visitor (budget, area, property type, timeline),
captures their contact details, and books a call or a tour — then shows you
everything it collected.

Built to be dropped onto an agency's existing website with one line of HTML.

## Run it locally

```bash
npm install
npm run dev
```

Then open:

| URL | What it is |
| --- | --- |
| http://localhost:3000 | Demo agency site with the widget in the corner |
| http://localhost:3000/admin | Every conversation, lead and booking |
| http://localhost:3000/widget | The chat panel on its own |

With no API key set, the widget replies from a short script so you can check
the UI. Add `ANTHROPIC_API_KEY` to `.env.local` for real conversations.

## Re-branding it for a client

Everything agency-specific is environment variables — see `.env.example`.
Change the name, city, phone, brand colour and opening hours, replace
`data/listings.json` with their inventory, and redeploy. No code changes.

## Embedding on a client's site

```html
<script src="https://YOUR-APP.vercel.app/embed.js" data-color="#1f6feb" defer></script>
```

The script draws the bubble and loads the chat in an iframe, so the host page's
CSS cannot affect the widget and vice versa. `data-position="left"` docks it to
the other corner.

## Where things live

```
config/agency.ts     everything that makes this one agency's receptionist
data/listings.json   demo inventory the assistant is allowed to talk about
lib/prompt.ts        the receptionist's persona and rules
lib/tools.ts         what the assistant can do: search, save lead, book
lib/claude.ts        the model loop
lib/store.ts         conversation storage (Supabase, or memory without it)
supabase/schema.sql  run this once in the Supabase SQL editor
lib/scheduling.ts    appointment slots, in the agency's timezone
app/api/chat         the widget's only endpoint
public/embed.js      the one line a client adds to their site
```
