import { afterEach, expect, it } from "vitest";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { healthRevision } from "../build/health-revision";

const roots: string[] = [];
afterEach(()=>{for(const root of roots.splice(0)) rmSync(root,{recursive:true,force:true});});
function fixture() {
  const root=mkdtempSync(join(tmpdir(),'health-revision-'));roots.push(root);
  for(const dir of ['server','src/haa','data/deep_history','web/content','web/app']) mkdirSync(join(root,dir),{recursive:true});
  for(const file of ['server/strategy_health.py','src/haa/strategy_health.py','data/deep_history/cash.csv','data/usd_equivalents.json','web/content/strategy-health.json','web/content/usd-equivalents.json'])
    writeFileSync(join(root,file),'original');
  return root;
}
it.each(['server/strategy_health.py','src/haa/strategy_health.py','data/deep_history/cash.csv','data/usd_equivalents.json','web/content/strategy-health.json'])("invalidates saved Health when %s changes",file=>{
  const root=fixture(), before=healthRevision(root);
  writeFileSync(join(root,file),'changed');
  expect(healthRevision(root)).not.toBe(before);
});
it('is stable across builds and ignores unrelated UI and Python bytecode',()=>{
  const root=fixture(),before=healthRevision(root);
  writeFileSync(join(root,'web/app/page.tsx'),'unrelated change');
  mkdirSync(join(root,'server/__pycache__'));
  writeFileSync(join(root,'server/__pycache__/ignored.pyc'),'compiled');
  expect(healthRevision(root)).toBe(before);
  writeFileSync(join(root,'server/new_loader.py'),'new calculation dependency');
  expect(healthRevision(root)).not.toBe(before);
});
