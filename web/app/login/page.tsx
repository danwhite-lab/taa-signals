"use client";

import { useState } from "react";
import { supabaseBrowser } from "../../lib/supabaseBrowser";
import TestLogin from "../../components/TestLogin";

export default function Login() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function login() {
    setBusy(true); setError("");
    try {
      const { error: problem } = await supabaseBrowser().auth.signInWithOAuth({
        provider: "google", options: { redirectTo: `${window.location.origin}/auth/callback/` },
      });
      if (problem) throw new Error("Google sign-in could not be started. Please try again.");
    } catch (problem) { setError((problem as Error).message); setBusy(false); }
  }
  return <main className="login-page"><button className="btn btn-primary" disabled={busy} onClick={() => void login()}>
    {busy ? "Opening Google…" : "Sign in with Google"}</button>
    {error && <p role="alert">{error}</p>}<TestLogin /></main>;
}
