import {afterEach,expect,it} from 'vitest';
import {activePortfolio,activateDeviceUser,clearDeviceResults,readDeviceResult,resultKey,saveDeviceResult,syncPortfolio} from '../lib/device-results';
const portfolio=(id='p',revision='one')=>[{id,is_default:true,updated_at:revision,payload:{name:id}}];
afterEach(()=>localStorage.clear());
it('keys results by account and saved portfolio revision, clearing all sections on a portfolio change',()=>{
  activateDeviceUser('a');const p=syncPortfolio('a',portfolio())!;const scope={userId:'a',portfolio:p};
  const keys=['today','health','preview'].map(section=>{saveDeviceResult(scope,section,{complete:true},()=>true);return resultKey(scope,section);});
  expect(readDeviceResult(scope,'health',()=>true)?.result).toEqual({complete:true});
  expect(readDeviceResult({userId:'b',portfolio:p},'health',()=>true)).toBeNull();
  syncPortfolio('a',portfolio('p','two'));
  for(const key of keys)expect(localStorage.getItem(key)).toBeNull();
  expect(activePortfolio('a')).not.toBe(p);
  saveDeviceResult(scope,'health',{late:true},()=>true);
  expect(localStorage.getItem(keys[1])).toBeNull();
});
it('clears device results on sign-out and account switch without changing unrelated preferences',()=>{
  localStorage.setItem('unrelated','keep');activateDeviceUser('a');const scope={userId:'a',portfolio:syncPortfolio('a',portfolio())!};
  saveDeviceResult(scope,'preview',{complete:true},()=>true);activateDeviceUser(null);
  expect(localStorage.getItem(resultKey(scope,'preview'))).toBeNull();
  activateDeviceUser('a');syncPortfolio('a',portfolio());saveDeviceResult(scope,'today',{},()=>true);
  activateDeviceUser('b');expect(localStorage.getItem(resultKey(scope,'today'))).toBeNull();
  expect(localStorage.getItem('unrelated')).toBe('keep');
});
it('never overwrites a good snapshot with partial data and safely rejects corrupt stored JSON',()=>{
  activateDeviceUser('a');const scope={userId:'a',portfolio:syncPortfolio('a',portfolio())!};
  saveDeviceResult(scope,'health',{complete:true},()=>true);const before=localStorage.getItem(resultKey(scope,'health'));
  expect(saveDeviceResult(scope,'health',{complete:false},()=>false)).toBeNull();
  expect(localStorage.getItem(resultKey(scope,'health'))).toBe(before);
  localStorage.setItem(resultKey(scope,'health'),'broken');expect(readDeviceResult(scope,'health',()=>true)).toBeNull();
  clearDeviceResults('a');expect(activePortfolio('a')).toBeNull();
});
