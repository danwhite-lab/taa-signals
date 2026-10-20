import { afterEach, expect, it, vi } from "vitest";
import { randomBytes } from "node:crypto";
import words from "../content/auth.json";
const mock=vi.hoisted(()=>({setSession:vi.fn()}));
vi.mock("../lib/supabaseBrowser",()=>({supabaseBrowser:()=>({auth:{setSession:mock.setSession}})}));
import { finishTestLogin, testLoginAvailable } from "../lib/testLogin";
afterEach(()=>{vi.unstubAllGlobals();mock.setSession.mockReset();});

it.each([404,500])("hides the form on status %s",async(status)=>{
  vi.stubGlobal("fetch",vi.fn(async()=>new Response("",{status})));expect(await testLoginAvailable()).toBe(false);
});
it("hides the form on network failure and requires enabled true",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>{throw new Error();}));expect(await testLoginAvailable()).toBe(false);
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify({enabled:true}))));expect(await testLoginAvailable()).toBe(true);
});
it("installs the normal browser session and uses Google's landing page",async()=>{
  const email=randomBytes(12).toString("hex")+"@example.invalid",password=randomBytes(24).toString("base64url");
  const fetcher=vi.fn(async()=>new Response(JSON.stringify({access_token:"mock-access",refresh_token:"mock-refresh"})));
  vi.stubGlobal("fetch",fetcher);mock.setSession.mockResolvedValue({data:{session:{user:{id:"fake-test-user"}}},error:null});
  const navigate=vi.fn();await finishTestLogin(email,password,navigate);
  expect(fetcher).toHaveBeenCalledWith("/api/test-login",expect.objectContaining({method:"POST",cache:"no-store",body:JSON.stringify({email,password})}));
  expect(mock.setSession).toHaveBeenCalledWith({access_token:"mock-access",refresh_token:"mock-refresh"});expect(navigate).toHaveBeenCalledWith("/portfolio/");
});
it.each([400,429,500])("uses only the generic message for status %s",async(status)=>{
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(randomBytes(32).toString("hex"),{status})));
  await expect(finishTestLogin("","",vi.fn())).rejects.toThrow(words.failure);expect(mock.setSession).not.toHaveBeenCalled();
});
it("never navigates when session installation fails",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify({access_token:"mock-access",refresh_token:"mock-refresh"}))));
  mock.setSession.mockResolvedValue({data:{session:null},error:new Error(randomBytes(20).toString("hex"))});
  const navigate=vi.fn();await expect(finishTestLogin("","",navigate)).rejects.toThrow(words.failure);expect(navigate).not.toHaveBeenCalled();
});
