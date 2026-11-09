import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import words from '../content/usd-equivalents.json';
import back from '../content/backtest.json';
import multiWords from '../content/backtest-multi.json';
import compareWords from '../content/compare.json';
const mock=vi.hoisted(()=>({back:vi.fn(),compare:vi.fn()}));
vi.mock('../lib/backtestApi',()=>({backtestRequest:mock.back,backtestDownload:vi.fn()}));
vi.mock('../lib/compareApi',()=>({compareRequest:mock.compare,compareDownload:vi.fn()}));
import Multi from '../app/backtest/multi-form';
import Compare from '../app/compare/page';
import {UsdBanner} from '../components/UsdEquivalents';
const mapping={original:'HAA-Simple Israel',resolved:'HAA-Simple',funds:'1159250',assets:'SPY, TIP, IEF, BIL',caveat:'USD implementation; ILS exposure omitted.'};
const models=[{label:'HAA-Simple Israel',strategy:'HAA',variant:'Simple',implementation:'Israel',execution_currency:'ILS',benchmark:'SPY'},{label:'Buy and Hold Gold Israel',strategy:'Buy and Hold',variant:'Gold',implementation:'Israel',execution_currency:'ILS',benchmark:'SPY'}];
const bounds={start_min:'2000-01-31',start_max:'2025-12-31',end_min:'2000-01-31',end_max:'2025-12-31'};
const resolved={enabled:true,currency:'USD',mapping_version:'fixture-v1',mappings:[mapping],bounds};
const table={columns:[],rows:[]};
afterEach(()=>{cleanup();mock.back.mockReset();mock.compare.mockReset();});

const config={models,proxies:[],single_options:[],blend_options:[],benchmarks:[]};
const options=(usd=false)=>({models,label:'HAA-Simple',currency:usd?'USD':'ILS',bounds:usd?bounds:{...bounds,start_min:'2023-01-31',end_min:'2023-01-31'},captions:[],warnings:[],data_validation:table,reference_replay_available:false,reference_caption:''});

it('unified single sleeve refreshes USD dates and preserves literal USD capital',async()=>{
 mock.back.mockImplementation(async(path:string)=>{
  if(path.startsWith('/api/backtest/config'))return config;
  if(path.startsWith('/api/backtest/options'))return options(path.includes('usd_equivalents=true'));
  return {valid:true,message:'valid'};
 });
 mock.compare.mockResolvedValue(resolved);
 const run=vi.fn(async(_body:Record<string,unknown>)=>{});
 render(<Multi mode="portfolio" running={false} onRun={run} onChange={vi.fn()}/>);
 await waitFor(()=>expect(screen.getByLabelText(multiWords.portfolioStart)).toHaveProperty('value','2023-01-31'));
 fireEvent.change(screen.getByLabelText(multiWords.portfolioStart),{target:{value:'2024-01-31'}});
 fireEvent.click(screen.getByRole('switch',{name:words.toggle}));
 await waitFor(()=>expect(mock.back.mock.calls.some(([p])=>p.includes('usd_equivalents=true'))).toBe(true));
 await screen.findByLabelText(back.initial+' (USD)');
 expect(screen.getByLabelText(multiWords.portfolioStart)).toHaveProperty('value','2024-01-31');
 expect(screen.getByLabelText(multiWords.portfolioStart)).toHaveProperty('min','2000-01-31');
 expect(screen.getByLabelText(back.initial+' (USD)')).toHaveProperty('value','100000');
 expect(screen.getByText(`${back.currency}: USD`)).toBeTruthy();
 expect(screen.getByText(/\$100,000/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:back.run}));
 await waitFor(()=>expect(run).toHaveBeenCalled());
 expect(run.mock.calls[0][0]).toMatchObject({label:'HAA-Simple',usd_equivalents:true,initial:100000,start:'2024-01-31'});
 expect(run.mock.calls[0][0]).not.toHaveProperty('sleeves');
});

it('multi-sleeve USD runs retain explicit weights and the portfolio body',async()=>{
 const run=vi.fn(async(_body:Record<string,unknown>)=>{});
 mock.back.mockImplementation(async(path:string)=>path.startsWith('/api/backtest/config')?config:path.startsWith('/api/backtest/options')?options(path.includes('usd_equivalents=true')):{valid:true,message:'valid'});
 mock.compare.mockResolvedValue(resolved);
 render(<Multi mode="portfolio" running={false} onRun={run} onChange={vi.fn()}/>);
 await waitFor(()=>expect(screen.getByRole('button',{name:back.run})).toHaveProperty('disabled',false));
 fireEvent.click(screen.getByRole('switch',{name:words.toggle}));
 await screen.findByText(new RegExp(words.available));
 expect(mock.compare.mock.calls[0][0]).toBe('/api/usd-equivalents/options');
 expect(JSON.parse(mock.compare.mock.calls[0][1].body)).toMatchObject({usd_equivalents:true,mode:'portfolio'});
 fireEvent.click(screen.getByRole('button',{name:multiWords.addSleeve}));
 fireEvent.click(await screen.findByRole('button',{name:'HAA Simple · Israel'}));
 const weights=screen.getAllByLabelText(multiWords.weight);
 fireEvent.change(weights[0],{target:{value:'60'}});fireEvent.change(weights[1],{target:{value:'40'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:back.run})).toHaveProperty('disabled',false));
 fireEvent.click(screen.getByRole('button',{name:back.run}));
 await waitFor(()=>expect(run).toHaveBeenCalled());
 expect(run.mock.calls[0][0]).toMatchObject({mode:'portfolio',usd_equivalents:true,initial:100000,sleeves:[{id:1,model:'HAA-Simple',weight:60},{id:2,model:'HAA-Simple Israel',weight:40}],start:'2023-01-31'});
});

it.each(['models','portfolios'] as const)('Compare %s forwards USD mode and renders mappings',async mode=>{
 mock.compare.mockImplementation(async(path:string,init?:RequestInit)=>{
  if(path==='/api/usd-equivalents/options')return resolved;
  if(path==='/api/compare')return {gate:'selection',reason:'Mock comparison completed'};
  if(path.includes('kind=models'))return {models};
  if(path.includes('kind=portfolios'))return {portfolios:[{id:'a',name:'Alpha',is_default:true},{id:'b',name:'Beta',is_default:false}]};
  return [];
 });
 render(<Compare/>);
 if(mode==='portfolios')fireEvent.click(screen.getByRole('radio',{name:compareWords.modes.portfolios}));
 const summary=screen.getByText(mode==='models'?compareWords.models:compareWords.saved,{selector:'summary'});
 fireEvent.click(summary);
 const names=mode==='models'?['HAA Simple · Israel','Gold Buy and hold · Israel · Hedged execution · Unhedged history']:['Alpha','Beta'];
 for(const name of names)fireEvent.click(await screen.findByRole('checkbox',{name}));
 fireEvent.click(summary);
 fireEvent.click(screen.getByRole('switch',{name:words.toggle}));
 await screen.findByText(new RegExp(words.available));
 await waitFor(()=>expect(screen.getByRole('button',{name:compareWords.run})).toHaveProperty('disabled',false));
 fireEvent.click(screen.getByRole('button',{name:compareWords.run}));
 await screen.findByText('Mock comparison completed');
 const sent=JSON.parse(mock.compare.mock.calls.find(([path])=>path==='/api/compare')![1].body);
 expect(sent).toMatchObject({mode,usd_equivalents:true,initial:100000});
});

it('keeps provenance and caveats readable in an expandable table',()=>{
 render(<UsdBanner value={resolved}/>);
 expect(screen.getByText(words.banner)).toBeTruthy();expect(screen.getByText(words.notice)).toBeTruthy();
 fireEvent.click(screen.getByText(words.sources));
 expect(screen.getByRole('cell',{name:mapping.original})).toBeTruthy();
 expect(screen.getByRole('cell',{name:mapping.caveat})).toBeTruthy();
});
