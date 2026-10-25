"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import { publicConfig } from "@/lib/config";

let client: SupabaseClient | undefined;
export function browserSupabase() {
  const config = publicConfig();
  if (!config) throw new Error("Supabase connection is not configured.");
  client ??= createBrowserClient(config.url, config.key);
  return client;
}
