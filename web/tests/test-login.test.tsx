import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { randomBytes } from "node:crypto";
import words from "../content/auth.json";

const mock=vi.hoisted(()=>({available:vi.fn(),finish:vi.fn(),session:null as null|{access_token:string},callback:null as null|((event:string,session:unknown)=>void)}));
vi.mock("../lib/testLogin",()=>({testLoginAvailable:mock.available,finishTestLogin:mock.finish}));
vi.mock("../lib/supabaseBrowser",()=>({supabaseBrowser:()=>({auth:{
  getSession:async()=>({data:{session:mock.session},error:null}),
  onAuthStateChange:(callback:(event:string,session:unknown)=>void)=>{mock.callback=callback;return {data:{subscription:{unsubscribe(){}}}};}
}})}));
import TestLogin from "../components/TestLogin";
import Badge from "../components/TestLoginBadge";
afterEach(()=>{cleanup();vi.unstubAllGlobals();mock.available.mockReset();mock.finish.mockReset();mock.session=null;mock.callback=null;});

it("renders nothing until the server positively enables the feature",async()=>{
  mock.available.mockResolvedValue(false);const value=render(<TestLogin/>);
  await waitFor(()=>expect(mock.available).toHaveBeenCalled());expect(value.container.innerHTML).toBe("");
});

it("has empty credential fields and sends only on submit, guards duplicates",async()=>{
  mock.available.mockResolvedValue(true);let resolve!:()=>void;mock.finish.mockImplementation(()=>new Promise<void>(done=>{resolve=done;}));
  render(<TestLogin/>);await screen.findByText(words.testTitle);
  const email=randomBytes(12).toString("hex")+"@example.invalid",password=randomBytes(24).toString("base64url");
  expect(screen.getByLabelText(words.email)).toHaveProperty("value","");expect(screen.getByLabelText(words.password)).toHaveProperty("value","");
  expect(mock.finish).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText(words.email),{target:{value:email}});fireEvent.change(screen.getByLabelText(words.password),{target:{value:password}});
  const form=screen.getByLabelText(words.password).closest("form")!;fireEvent.submit(form);fireEvent.submit(form);
  expect(mock.finish).toHaveBeenCalledTimes(1);expect(mock.finish).toHaveBeenCalledWith(email,password);
  resolve();await waitFor(()=>expect(screen.getByLabelText(words.password)).toHaveProperty("value",""));
});

it("never displays raw failures and clears the entered password",async()=>{
  mock.available.mockResolvedValue(true);mock.finish.mockRejectedValue(new Error(randomBytes(20).toString("hex")));
  render(<TestLogin/>);await screen.findByText(words.testTitle);
  fireEvent.submit(screen.getByLabelText(words.password).closest("form")!);
  await screen.findByRole("alert");expect(screen.getByRole("alert").textContent).toBe(words.failure);
  expect(screen.getByLabelText(words.password)).toHaveProperty("value","");
});

it("shows a badge only after a verified status and clears on sign-out",async()=>{
  mock.session={access_token:"mock-access"};const fetcher=vi.fn(async()=>new Response(JSON.stringify({is_test_login:true})));
  vi.stubGlobal("fetch",fetcher);render(<Badge/>);await screen.findByText(words.badge);
  expect(fetcher).toHaveBeenCalledWith("/api/test-login/status",expect.objectContaining({cache:"no-store",headers:{Authorization:"Bearer mock-access"}}));
  await act(async()=>mock.callback?.("SIGNED_OUT",null));expect(screen.queryByText(words.badge)).toBeNull();
});

it("does not mislabel ordinary users or trust late responses for a previous user",async()=>{
  mock.session={access_token:"mock-access"};let resolve!:(response:Response)=>void;
  vi.stubGlobal("fetch",vi.fn(()=>new Promise<Response>(done=>{resolve=done;})));
  render(<Badge/>);await waitFor(()=>expect(resolve).toBeTypeOf("function"));
  await act(async()=>mock.callback?.("SIGNED_OUT",null));
  await act(async()=>resolve(new Response(JSON.stringify({is_test_login:true}))));
  expect(screen.queryByText(words.badge)).toBeNull();
});

it("hides the badge for non-test accounts",async()=>{
  mock.session={access_token:"mock-access"};vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify({is_test_login:false}))));
  const value=render(<Badge/>);await waitFor(()=>expect(fetch).toHaveBeenCalled());expect(value.container.innerHTML).toBe("");
});
