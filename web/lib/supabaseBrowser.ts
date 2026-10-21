import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | undefined;

export function supabaseBrowser(): SupabaseClient {
  if (typeof window === "undefined") throw new Error("Sign-in requires a browser.");
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) throw new Error("Sign-in is not configured. Set the public Supabase environment variables and rebuild.");
  client ??= createClient(url, key, {
    auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true,
      detectSessionInUrl: false },
  });
  return client;
}

// One exchange even under React Strict Mode; don't replay a consumed PKCE code.
let callback: Promise<void> | undefined;
export function completeLogin(): Promise<void> {
  callback ??= (async () => {
    const query = new URLSearchParams(window.location.search);
    if (query.has("error")) throw new Error("Google sign-in was not completed. Please try again.");
    const code = query.get("code");
    if (!code) throw new Error("Sign-in code is missing. Start again from Login.");
    const { error } = await supabaseBrowser().auth.exchangeCodeForSession(code);
    window.history.replaceState({}, "", "/auth/callback/");
    if (error) throw new Error("Sign-in could not be completed. Start again in the same browser.");
  })();
  return callback;
}
