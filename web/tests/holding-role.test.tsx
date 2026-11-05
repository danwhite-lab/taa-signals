import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import HoldingEditorRow from '../components/HoldingEditorRow';
import words from '../content/holdings.json';
const row={Security:'US:FAKE',Fund:'Example holding',Currency:'USD',Units:'12','Value (₪ / $)':'120','Outside the rebalance':false};
const base={row,quote:{price:10,fresh:true,as_of:'2026-11-03'},busy:false,onEdit:vi.fn(),onBlur:vi.fn()};
const view=(props:Parameters<typeof HoldingEditorRow>[0]=base)=> <table><tbody><HoldingEditorRow {...props}/></tbody></table>;
const details=()=>document.getElementById('holding-options-US%3AFAKE')!;
const expand=()=>fireEvent.click(screen.getByRole('button',{name:words.detailsFund.replace('{fund}',row.Fund)}));
const menu=()=>fireEvent.click(screen.getByLabelText(words.actionsFund.replace('{fund}',row.Fund)));
afterEach(()=>{cleanup();vi.clearAllMocks();});

it('renders one compact editable row and only reveals price fields after Expand and Edit',()=>{
 render(view());
 const holding=screen.getByRole('row',{name:row.Fund});
 expect(within(holding).getAllByRole('cell')).toHaveLength(5);
 expect(screen.getByLabelText('Value (₪ / $) US:FAKE')).toHaveProperty('value','120');
 expect(screen.queryByRole('button',{name:words.editPrice})).toBeNull();
 expect(screen.queryByRole('button',{name:words.removeFund.replace('{fund}',row.Fund)})).toBeNull();
 expand();const edit=within(details()).getByRole('button',{name:words.editPrice});
 expect(edit.getAttribute('aria-expanded')).toBe('false');expect(screen.queryByRole('textbox',{name:'Manual override per unit US:FAKE'})).toBeNull();
 fireEvent.click(edit);
 fireEvent.change(screen.getByLabelText('Manual override per unit US:FAKE'),{target:{value:'3.7286'}});
 fireEvent.change(screen.getByLabelText('Manual price date US:FAKE'),{target:{value:'2026-11-03'}});
 fireEvent.change(screen.getByLabelText('Minimum order (₪) US:FAKE'),{target:{value:'100'}});
 expect(base.onEdit.mock.calls).toEqual([['US:FAKE','Manual price per unit','3.7286'],['US:FAKE','Price date','2026-11-03'],['US:FAKE','Minimum order (₪)','100']]);
 expect(screen.queryByRole('button',{name:/Apply|Save/})).toBeNull();
});

it('uses a Type dropdown, expands companion selection, and preserves saved anchors and sorting',()=>{
 const edit=vi.fn();const targets=[{id:'US:ZZZ',label:'Zulu fund'},{id:'US:AAA',label:'Alpha fund'},{id:'US:BBB',label:''}];
 const props={...base,onEdit:edit,targets};const v=render(view(props));
 const role=screen.getByRole('combobox',{name:words.role+' US:FAKE'});
 expect(within(role).getAllByRole('option').map(n=>n.textContent)).toEqual(Object.values(words.roles));
 fireEvent.change(role,{target:{value:'companion'}});expect(edit).toHaveBeenCalledWith('US:FAKE','Role','companion');
 v.rerender(view({...props,role:'companion'}));
 const picker=screen.getByRole('combobox',{name:words.companion+' US:FAKE'});
 expect(within(picker).getAllByRole('option').map(n=>n.textContent)).toEqual([words.none,'Alpha fund','US:BBB','Zulu fund']);
 fireEvent.change(picker,{target:{value:'US:AAA'}});expect(edit).toHaveBeenCalledWith('US:FAKE','Companion of','US:AAA');
 v.rerender(view({...props,role:'outside'}));expect(screen.queryByRole('combobox',{name:words.companion+' US:FAKE'})).toBeNull();
});

it('names a saved anchor outside current targets and falls back to its security number',()=>{
 const props={...base,row:{...row,'Companion of':'TASE:1234567'}};
 const v=render(view({...props,instruments:{'TASE:1234567':{label:'Example anchor',identifier:'1234567'}}}));expand();
 expect(screen.getByRole('option',{name:words.unmatchedCompanion.replace('{fund}','Example anchor 1234567')})).toHaveProperty('selected',true);
 v.rerender(view(props));expect(screen.getByRole('option',{name:words.unmatchedCompanion.replace('{fund}','1234567')})).toHaveProperty('selected',true);
});

it('confirms target removal from the menu and removes non-targets immediately',()=>{
 const edit=vi.fn();const props={...base,onEdit:edit,portfolioName:'My plan'};
 const v=render(view({...props,targets:[{id:'US:FAKE',label:row.Fund,weight:'25%'}]}));
 menu();fireEvent.click(screen.getByRole('button',{name:words.removeFund.replace('{fund}',row.Fund)}));expect(edit).not.toHaveBeenCalled();
 expect(screen.getByRole('alert').textContent).toContain(words.removePlanConfirm.replace('{portfolio}','My plan'));
 fireEvent.click(screen.getByRole('button',{name:words.cancelRemoval}));expect(screen.queryByRole('alert')).toBeNull();
 menu();fireEvent.click(screen.getByRole('button',{name:words.removeFund.replace('{fund}',row.Fund)}));fireEvent.click(screen.getByRole('button',{name:words.removeAnyway}));
 expect(edit).toHaveBeenCalledExactlyOnceWith('US:FAKE','Remove',true);
 edit.mockClear();v.rerender(view(props));menu();fireEvent.click(screen.getByRole('button',{name:words.removeFund.replace('{fund}',row.Fund)}));
 expect(edit).toHaveBeenCalledExactlyOnceWith('US:FAKE','Remove',true);
});
