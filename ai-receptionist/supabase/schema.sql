-- AI Receptionist — database schema
--
-- Paste this whole file into Supabase → SQL Editor → New query → Run.
-- Running it twice is safe.

create extension if not exists "pgcrypto";

create table if not exists conversations (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  -- Which page of the client's site the visitor was on.
  page_url    text,
  -- The conversation as the visitor saw it: [{ "role": "user", "text": "…" }, …]
  transcript  jsonb not null default '[]'::jsonb,
  -- Everything the assistant learned: budget, area, timeline, contact details.
  lead        jsonb not null default '{}'::jsonb
);

create table if not exists bookings (
  id                uuid primary key default gen_random_uuid(),
  conversation_id   uuid not null references conversations(id) on delete cascade,
  created_at        timestamptz not null default now(),
  starts_at         timestamptz not null,
  kind              text not null check (kind in ('call', 'tour')),
  listing_id        text,
  name              text not null,
  email             text not null,
  phone             text,
  -- Filled in once the slot is mirrored into Google Calendar.
  calendar_event_id text
);

create index if not exists conversations_updated_at_idx on conversations (updated_at desc);
create index if not exists bookings_starts_at_idx on bookings (starts_at);

-- Only the server touches these tables, and it uses the service role key,
-- which bypasses row level security. Turning RLS on with no policies means
-- the public anon key can read nothing, even if it ever leaks.
alter table conversations enable row level security;
alter table bookings enable row level security;
