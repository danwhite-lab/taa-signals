import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { existsSync, readFileSync } from "node:fs";

const mock=vi.hoisted(()=>({redirect:vi.fn((path:string)=>{throw new Error(`Redirect: ${path}`);})}));
vi.mock('next/navigation',()=>({usePathname:()=>'/strategy-catalogue/',redirect:mock.redirect}));
vi.mock('../components/TestLoginBadge',()=>({default:()=> <strong>TEST LOGIN</strong>}));
import Catalogue from '../app/strategy-catalogue/page';
import Home from '../app/page';
import RulesRedirect from '../app/rules/page';
import Navigation from '../components/top-navigation';
import { metadata as catalogueMetadata } from '../app/strategy-catalogue/layout';

afterEach(()=>{cleanup();vi.unstubAllGlobals();mock.redirect.mockClear();});

it('uses the catalogue nav link and Signalboard home link while keeping TEST LOGIN',()=>{
  render(<Navigation/>);
  // next/link normalizes trailing slashes in the test runtime.
  expect(screen.getByRole('link',{name:'Signalboard'}).getAttribute('href')?.replace(/\/$/,'')).toBe('/today');
  const link=screen.getByRole('link',{name:'Strategy Catalogue'});
  expect(link.getAttribute('href')?.replace(/\/$/,'')).toBe('/strategy-catalogue');
  expect(link.getAttribute('aria-current')).toBe('page');
  expect(screen.queryByText('Preview')).toBeNull();
  expect(screen.queryByRole('link',{name:'Rules'})).toBeNull();
  expect(screen.getByText('TEST LOGIN')).toBeTruthy();
});

it('redirects home to Today and the old Rules route to the catalogue',()=>{
  expect(()=>Home()).toThrow('Redirect: /today/');
  expect(()=>RulesRedirect()).toThrow('Redirect: /strategy-catalogue/');
  expect(mock.redirect.mock.calls.map(call=>call[0])).toEqual(['/today/','/strategy-catalogue/']);
  expect(readFileSync('./app/page.tsx','utf8')).not.toContain('/api/strategies');
  expect(existsSync('./app/price-check')).toBe(false);
});

it('uses the new document titles and leaves the API rewrite configuration alone',()=>{
  expect(catalogueMetadata.title).toBe('Strategy Catalogue');
  const layout=readFileSync('./app/layout.tsx','utf8');
  expect(layout).toContain('title: "Signalboard"');
  expect(layout).not.toContain('migration preview');
  const config=JSON.parse(readFileSync('../vercel.json','utf8'));
  expect(config.cleanUrls).toBeUndefined();
});

const model=(label:string,currency:string)=>({label,strategy:label,variant:null,implementation:'Example implementation',execution_currency:currency,
  markdown:`## ${label} rules\n\nOriginal **unchanged** wording.`,risk_warning:`${label} risk warning`,description_missing:false});

it('sorts generic models alphabetically, selects the first and shows currency and unchanged rules',async()=>{
  const rows=[model('Zulu','ILS'),model('alpha','USD'),model('Beta','ILS')];
  const fetcher=vi.fn(async()=>new Response(JSON.stringify({models:rows,implementation_notes:'Original implementation notes.',source:'shared source'})));
  vi.stubGlobal('fetch',fetcher);render(<Catalogue/>);
  const list=await screen.findByRole('list',{name:'Strategies'});
  const buttons=within(list).getAllByRole('button');
  expect(buttons.map(b=>b.textContent)).toEqual(['alpha USD','Beta ILS','Zulu ILS']);
  expect(buttons[0].getAttribute('aria-pressed')).toBe('true');
  expect(screen.queryByRole('combobox')).toBeNull();
  expect(screen.getByRole('heading',{level:1}).textContent).toBe('Strategy Catalogue');
  expect(screen.getByText('Strategy Catalogue',{selector:'.eyebrow'})).toBeTruthy();
  expect(screen.getByRole('heading',{name:'alpha rules'})).toBeTruthy();
  fireEvent.click(buttons[2]);
  expect(screen.getByRole('heading',{name:'Zulu rules'})).toBeTruthy();
  expect(screen.getByText('Zulu risk warning')).toBeTruthy();
  expect(screen.getByText('Original implementation notes.')).toBeTruthy();
  expect(screen.getByText('unchanged',{selector:'strong'})).toBeTruthy();
  expect(screen.queryByText(/Migration preview/)).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher).toHaveBeenCalledWith('/api/rules',expect.objectContaining({cache:'no-store'}));
});

it('keeps missing descriptions and retry errors visible',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response('Example failure',{status:503})).mockResolvedValueOnce(new Response(JSON.stringify({models:[{...model('Example','ILS'),description_missing:true,markdown:null}],implementation_notes:'',source:'shared'}))));
  render(<Catalogue/>);await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button',{name:'Try again'}));
  await screen.findByText(/This implementation has no rule description/);
});
