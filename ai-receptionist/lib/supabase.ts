import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/**
 * Supabase is optional.
 *
 * With the two variables below set, conversations persist. Without them the
 * app still runs — everything falls back to memory — so a fresh clone works
 * before anyone has created a database.
 */
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

export const hasDatabase = Boolean(url && serviceKey);

let client: SupabaseClient | null = null;

export function db(): SupabaseClient {
  if (!url || !serviceKey) {
    throw new Error("Supabase is not configured");
  }
  // The service role key bypasses row level security, so this client must only
  // ever be constructed on the server. Never import this module into a
  // component that runs in the browser.
  client ??= createClient(url, serviceKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  return client;
}
