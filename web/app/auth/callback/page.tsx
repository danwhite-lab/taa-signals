"use client";

import { useEffect, useState } from "react";
import { completeLogin } from "../../../lib/supabaseBrowser";

export default function Callback() {
  const [error, setError] = useState("");
  useEffect(() => {
    void completeLogin().then(() => window.location.replace("/portfolio/"))
      .catch((problem: Error) => setError(problem.message));
  }, []);
  return <main>{error ? <><p role="alert">{error}</p><a href="/login/">Try login again</a></> :
    <p role="status">Completing sign-in…</p>}</main>;
}
