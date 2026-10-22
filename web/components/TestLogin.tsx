"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import text from "../content/auth.json";
import { finishTestLogin, testLoginAvailable } from "../lib/testLogin";

export default function TestLogin() {
  const [enabled,setEnabled]=useState(false), [email,setEmail]=useState(""), [password,setPassword]=useState("");
  const [busy,setBusy]=useState(false), [error,setError]=useState("");
  const inFlight=useRef(false);
  useEffect(()=>{
    const controller=new AbortController();
    void testLoginAvailable(controller.signal).then(value=>{if(!controller.signal.aborted)setEnabled(value);});
    return ()=>controller.abort();
  },[]);
  async function submit(event: FormEvent) {
    event.preventDefault();if(inFlight.current)return;
    inFlight.current=true;setBusy(true);setError("");
    try {await finishTestLogin(email,password);}
    catch {setError(text.failure);}
    finally {setPassword("");inFlight.current=false;setBusy(false);}
  }
  if(!enabled)return null;
  return <section className="test-login"><h2>{text.testTitle}</h2><form onSubmit={event=>void submit(event)}>
    <fieldset disabled={busy}>
      <label>{text.email}<input type="email" autoComplete="username" maxLength={320} required value={email} onChange={e=>setEmail(e.target.value)}/></label>
      <label>{text.password}<input type="password" autoComplete="current-password" maxLength={4096} required value={password} onChange={e=>setPassword(e.target.value)}/></label>
      <button className="btn btn-secondary" type="submit">{busy ? text.busy : text.submit}</button>
    </fieldset>{error && <p role="alert">{error}</p>}
  </form></section>;
}
