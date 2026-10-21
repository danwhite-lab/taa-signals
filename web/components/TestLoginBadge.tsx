"use client";
import { useEffect, useState } from "react";
import text from "../content/auth.json";
import { supabaseBrowser } from "../lib/supabaseBrowser";

export default function TestLoginBadge() {
  const [visible,setVisible]=useState(false);
  useEffect(()=>{
    let active=true,revision=0;let unsubscribe=()=>{};
    async function check(token?: string) {
      const current=++revision;setVisible(false);if(!token)return;
      try {
        const response=await fetch("/api/test-login/status",{cache:"no-store",headers:{Authorization:`Bearer ${token}`}});
        const value=response.ok ? await response.json() : null;
        if(active && current===revision)setVisible(value?.is_test_login===true);
      } catch { /* A failed check must never label an unverified user. */ }
    }
    try {
      const auth=supabaseBrowser().auth;
      const subscription=auth.onAuthStateChange((_event,session)=>{void check(session?.access_token);});
      unsubscribe=()=>subscription.data.subscription.unsubscribe();
      const initialRevision=revision;
      void auth.getSession().then(({data,error})=>{if(active && initialRevision===revision)void check(error ? undefined : data.session?.access_token);}).catch(()=>{});
    } catch { /* Sign-in is not configured or there is no browser session. */ }
    return ()=>{active=false;revision++;unsubscribe();};
  },[]);
  return visible ? <strong className="preview-badge" role="status">{text.badge}</strong> : null;
}
