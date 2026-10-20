import text from "../content/auth.json";
import { supabaseBrowser } from "./supabaseBrowser";

export async function testLoginAvailable(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch("/api/test-login", {cache:"no-store", signal});
    return response.ok && (await response.json()).enabled === true;
  } catch { return false; }
}

export async function finishTestLogin(email: string, password: string,
  navigate: (path: string) => void = path => window.location.replace(path)): Promise<void> {
  try {
    const response = await fetch("/api/test-login", {method:"POST", cache:"no-store",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify({email,password})});
    if (!response.ok) throw new Error();
    const tokens = await response.json();
    if (typeof tokens.access_token !== "string" || typeof tokens.refresh_token !== "string") throw new Error();
    const {data,error} = await supabaseBrowser().auth.setSession({access_token:tokens.access_token,refresh_token:tokens.refresh_token});
    if (error || !data.session) throw new Error();
    navigate("/portfolio/");
  } catch { throw new Error(text.failure); }
}
