import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { readFileSync } from "node:fs";
import { Fees, TaxControls, defaultFees } from "../components/BacktestAssumptions";
import { savedOrder, savedChoices, byLabel } from "../lib/ui-order";
import text from "../content/backtest.json";

afterEach(cleanup);

it('orders default first and remaining names case-insensitively without mutating the input',async()=>{
  const rows=[{id:'z',name:'Zulu'},{id:'b',name:'beta'},{id:'a',name:'Alpha'}];
  const ordered=await savedChoices(rows,async()=>[{id:'z',is_default:true}]);
  expect(ordered.map(r=>r.id)).toEqual(['z','a','b']);
  expect(rows.map(r=>r.id)).toEqual(['z','b','a']);
  expect(savedOrder([{name:'z',is_default:false},{name:'a',is_default:true}]).map(r=>r.name)).toEqual(['a','z']);
  expect(['Zulu','beta','Alpha'].sort(byLabel)).toEqual(['Alpha','beta','Zulu']);
  expect((await savedChoices(rows,async()=>{throw Error('Unavailable');})).map(r=>r.id)).toEqual(['a','b','z']);
});

it('keeps fee values and tax rate when toggles disable their shared row controls',()=>{
  function Form(){
    const [fees,setFees]=useState(defaultFees),[tax,setTax]=useState(true),[rate,setRate]=useState(25);
    return <Fees value={fees} onChange={patch=>setFees(value=>({...value,...patch}))}>
      <TaxControls enabled={tax} rate={rate} onEnabled={setTax} onRate={setRate}/>
    </Fees>;
  }
  render(<Form/>);
  const disclosure=screen.getByText('How fees work').closest('details')!;
  expect(disclosure.open).toBe(false);expect(disclosure.textContent).toContain(text.feeHelp);
  fireEvent.change(screen.getByLabelText(text.usdFlatFee),{target:{value:'9'}});
  fireEvent.click(screen.getByLabelText(text.feesEnabled));
  for(const label of [text.ilsFeePercent,text.ilsMinimumFee,text.usdFlatFee])expect(screen.getByLabelText(label)).toHaveProperty('disabled',true);
  expect(screen.getByLabelText(text.usdFlatFee)).toHaveProperty('value','9');
  fireEvent.click(screen.getByLabelText(text.taxEnabled));
  expect(screen.getByLabelText(text.taxRate)).toHaveProperty('disabled',true);
  expect(screen.getByLabelText(text.taxRate)).toHaveProperty('value','25');
  const feesRow=screen.getByLabelText(text.feesEnabled).closest('.assumption-row')!;
  expect(feesRow.nextElementSibling?.contains(screen.getByLabelText(text.taxEnabled))).toBe(true);
});

it('defines shared light buttons, accent, destructive, focus and selected-list styles once',()=>{
  const css=readFileSync('./app/globals.css','utf8');
  expect(css).toContain('--accent: #1d4ed8');
  for(const name of ['.btn-primary','.btn-destructive','.list-row.is-selected','.segment:has(input:checked)',':focus-visible'])expect(css).toContain(name);
  expect(css).not.toContain('button { background: #17202a');
  expect(css).toContain('.list-date');expect(css).toContain('.assumption-row');
});
