"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { supabaseBrowser } from "../lib/supabaseBrowser";

export default function AuthGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const publicPage = pathname.startsWith("/login") || pathname.startsWith("/auth/callback");
  const [userId, setUserId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (publicPage) return;
    let active = true;
    let authRevision = 0;
    let unsubscribe = () => {};
    try {
      const client = supabaseBrowser();
      const subscription = client.auth.onAuthStateChange((_event, session) => {
        authRevision += 1;
        if (active) { setUserId(session?.user.id ?? null); setReady(true); }
      });
      unsubscribe = () => subscription.data.subscription.unsubscribe();
      const loadedAt = authRevision;
      void client.auth.getSession().then(({ data, error: problem }) => {
        if (!active || loadedAt !== authRevision) return;
        if (problem) setError("Could not restore your sign-in. Please sign in again.");
        setUserId(data.session?.user.id ?? null); setReady(true);
      }).catch(() => { if (active) setError("Could not restore sign-in."); });
    } catch (problem) { setError((problem as Error).message); }
    return () => { active = false; unsubscribe(); };
  }, [publicPage]);
  if (publicPage) return children;
  if (error) return <main><p role="alert">{error}</p><a href="/login/">Go to login</a></main>;
  if (!ready) return <main><p role="status">Checking sign-in…</p></main>;
  if (!userId) return <main className="login-page"><a className="button-link" href="/login/">Sign in with Google</a></main>;
  // Remount all private state if another account signs in on the same browser.
  return <div key={userId}>{children}</div>;
}
