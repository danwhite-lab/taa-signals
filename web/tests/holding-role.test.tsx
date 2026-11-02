import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import HoldingEditorRow from '../components/HoldingEditorRow';
import words from '../content/holdings.json';
const row={Security:'US:FAKE',Fund:'Example holding',Currency:'USD',Units:'12','Value (₪ / $)':'120','Outside the rebalance':false};
afterEach(cleanup);
it('keeps a holding compact until its name is opened',()=>{
  render(<HoldingEditorRow row={row} quote={{price:10,fresh:true}} busy={false} onEdit={vi.fn()} onBlur={vi.fn()}/>);
  const summary=screen.getByRole('button',{name:/^Example holding/});
  expect(summary.getAttribute('aria-expanded')).toBe('false');
  expect(summary.parentElement?.querySelector('.holding-editor-content')?.classList.contains('is-open')).toBe(false);
  fireEvent.click(summary);
  expect(summary.getAttribute('aria-expanded')).toBe('true');
  expect(summary.parentElement?.querySelector('.holding-editor-content')?.classList.contains('is-open')).toBe(true);
});

it('uses three compact buttons, shows the picker only for Companion, and sorts friendly names',()=>{
  const edit=vi.fn();const targets=[{id:'US:ZZZ',label:'Zulu fund'},{id:'US:AAA',label:'Alpha fund'},{id:'US:BBB',label:''}];
  const props={row,quote:{price:10,fresh:true},busy:false,onEdit:edit,onBlur:vi.fn(),targets};
  const view=render(<HoldingEditorRow {...props}/>);
  const group=screen.getByRole('group',{name:words.role+' US:FAKE'});
  expect(within(group).getAllByRole('button').map(n=>n.textContent)).toEqual(Object.values(words.roles));
  expect(screen.queryByRole('checkbox')).toBeNull();expect(screen.queryByRole('combobox')).toBeNull();
  expect(within(group).getByRole('button',{name:words.roles.normal}).getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(within(group).getByRole('button',{name:words.roles.companion}));
  expect(edit).toHaveBeenCalledWith('US:FAKE','Role','companion');
  view.rerender(<HoldingEditorRow {...props} role="companion"/>);
  const picker=screen.getByRole('combobox');
  expect(within(picker).getAllByRole('option').map(n=>n.textContent)).toEqual([words.none,'Alpha fund','US:BBB','Zulu fund']);
  fireEvent.change(picker,{target:{value:'US:AAA'}});
  expect(edit).toHaveBeenCalledWith('US:FAKE','Companion of','US:AAA');
  view.rerender(<HoldingEditorRow {...props} role="outside"/>);
  expect(screen.queryByRole('combobox')).toBeNull();
  expect(screen.getByLabelText('Units US:FAKE')).toHaveProperty('value','12');
});

it('names a saved anchor outside current targets, falling back to its security number',()=>{
  const props={row:{...row,'Companion of':'TASE:1234567'},quote:{price:10,fresh:true},busy:false,onEdit:vi.fn(),onBlur:vi.fn()};
  const view=render(<HoldingEditorRow {...props} instruments={{'TASE:1234567':{label:'Example anchor',identifier:'1234567'}}}/>);
  expect(screen.getByRole('option',{name:words.unmatchedCompanion.replace('{fund}','Example anchor 1234567')})).toHaveProperty('selected',true);
  view.rerender(<HoldingEditorRow {...props}/>);
  expect(screen.getByRole('option',{name:words.unmatchedCompanion.replace('{fund}','1234567')})).toHaveProperty('selected',true);
});

it('confirms removal of a plan target inline, supports cancel, and removes non-targets immediately',()=>{
  const edit=vi.fn();const props={row,quote:{price:10,fresh:true},busy:false,onEdit:edit,onBlur:vi.fn(),portfolioName:'My plan'};
  const view=render(<HoldingEditorRow {...props} targets={[{id:'US:FAKE',label:row.Fund,weight:'25%'}]}/>);
  expect(screen.getAllByText(words.inPlan.replace('{weight}','25%')).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button',{name:words.removeFund.replace('{fund}',row.Fund)}));
  expect(edit).not.toHaveBeenCalled();
  expect(screen.getByRole('alert').textContent).toContain(words.removePlanConfirm.replace('{portfolio}','My plan'));
  fireEvent.click(screen.getByRole('button',{name:words.cancelRemoval}));
  expect(screen.queryByRole('alert')).toBeNull();expect(edit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:words.removeFund.replace('{fund}',row.Fund)}));
  fireEvent.click(screen.getByRole('button',{name:words.removeAnyway}));
  expect(edit).toHaveBeenCalledExactlyOnceWith('US:FAKE','Remove',true);
  edit.mockClear();view.rerender(<HoldingEditorRow {...props}/>);
  fireEvent.click(screen.getByRole('button',{name:words.removeFund.replace('{fund}',row.Fund)}));
  expect(edit).toHaveBeenCalledExactlyOnceWith('US:FAKE','Remove',true);
  expect(screen.queryByRole('alert')).toBeNull();
});
