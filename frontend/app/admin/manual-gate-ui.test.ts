import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import React from "react";
import { orderCandidates } from "./candidate-order.ts";
import { pageWindow } from "./page-window.ts";
import * as filters from "./candidate-filters.ts";
const require = createRequire(import.meta.url);
const source = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");
function nodes(tree: any): any[] {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children), ...nodes(tree.props?.footer)];
}
function harness(file: string, name: string, extra: any = {}) {
  const states: any[] = [], refs: any[] = [], deps: any[] = [], cleanups: any[] = [];
  let index = 0, refIndex = 0, effectIndex = 0;
  let queue: any[] = [];
  const events = new Map(), locations: string[] = [];
  const hooks = { ...React,
    useState: (initial: any) => { const i=index++; if (!(i in states)) states[i]=typeof initial==="function" ? initial() : initial;
      return [states[i], (v: any) => { states[i]=typeof v==="function" ? v(states[i]) : v; }]; },
    useRef: (v: any) => {const i=refIndex++; return refs[i] ?? (refs[i]={current:v});},
    useEffect: (fn: any, values: any[]) => {const i=effectIndex++; if (!deps[i] || values.some((v,j)=>v!==deps[i][j])) {
      deps[i]=values; queue.push(()=>{ cleanups[i]?.(); cleanups[i]=fn(); }); }} };
  const mocks: any = { react: hooks, "./candidate-order":{orderCandidates}, "./page-window":{pageWindow},
    "./candidate-filters":filters, "./AdminHomeButton":{ADMIN_HOME_EVENT:"home"}, "../components/Modal":{Modal:"modal"} };
  const module={exports:{} as any};
  runInNewContext(ts.transpileModule(source(file),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2020}}).outputText,
    {module,exports:module.exports,Set,window:{addEventListener:(e:any,f:any)=>events.set(e,f),removeEventListener:(e:any)=>events.delete(e),location:{assign:(v:string)=>locations.push(v)}},
      require:(id:string)=>mocks[id] ?? (id.startsWith(".") ? extra[id] ?? {} : require(id))});
  return { refs, events, locations, render(props:any) { index=0;refIndex=0;effectIndex=0;const tree=module.exports[name](props);const pending=queue;queue=[];pending.forEach(fn=>fn());return tree; } };
}

test("exact display values and selected/level/numeric/ID order, including huge values and NULL",()=>{
  const rows=[{member_id:"b",member_number:"0031",recommendation_level:5},{member_id:"a",member_number:"31",recommendation_level:5},
    {member_id:"huge",member_number:"9".repeat(200),recommendation_level:5},{member_id:"chosen",member_number:"0001",recommendation_level:1},
    {member_id:"null",member_number:null,recommendation_level:null}];
  const ordered=orderCandidates(rows,new Set(["chosen"]));
  assert.deepEqual(ordered.map(r=>r.member_id),["chosen","huge","a","b","null"]);
  assert.equal(ordered[3].member_number,"0031");assert.equal(rows[0].member_number,"0031");
});

test("page window clamps first, last, empty, decreased count and only shows p +/- 3",()=>{
  assert.deepEqual(pageWindow(1,24),{current:1,pages:[1,2,3,4],before:false,after:true});
  assert.deepEqual(pageWindow(12,24),{current:12,pages:[9,10,11,12,13,14,15],before:true,after:true});
  assert.deepEqual(pageWindow(24,24).pages,[21,22,23,24]);
  assert.equal(pageWindow(24,2).current,2); assert.equal(pageWindow(-3,0).current,1);
});

test("shared candidate panel keeps selection, shows ratings, bounds pages and hidden 120 members",()=>{
  const h=harness("./MajorPanels.tsx","CandidateSelectionPanel");
  let selected=new Set<string>();
  const candidates=Array.from({length:120},(_,i)=>({member_id:`id-${i}`,member_number:String(i+1).padStart(4,"0"),display_name:"架空会員",eligible:true,line_linked:false,recommendation_level:i===119?null:5}));
  const props:any={job:{job_id:"job",status:"published"},candidates,selected,filter:"all",setFilter:()=>{},toggle:(id:string)=>{selected=new Set(selected);selected.has(id)?selected.delete(id):selected.add(id);props.selected=selected;},editable:true,busy:false,maxRecipients:null};
  h.render(props);let tree=h.render(props);
  assert.ok(nodes(tree).some(n=>n.props?.children==="おすすめレベル"));
  const next=nodes(tree).find(n=>n.type==="button"&&n.props.children==="次へ");next.props.onClick();tree=h.render(props);
  const checkbox=nodes(tree).find(n=>n.type==="input"&&n.props.type==="checkbox");const id=checkbox.props["data-member-id"];
  let focused=false;h.refs[0].current={querySelectorAll:()=>[{dataset:{memberId:id},focus:()=>{focused=true;}}]};
  checkbox.props.onChange();tree=h.render(props);
  assert.ok(selected.has(id));assert.ok(focused);
  assert.ok(nodes(tree).some(n=>n.type==="input"&&n.props["data-member-id"]===id&&n.props.checked));
  props.selected=new Set(candidates.map(c=>c.member_id));tree=h.render(props);
  nodes(tree).find(n=>n.type==="input"&&n.props.inputMode==="numeric").props.onChange({target:{value:"9999"}});
  tree=h.render(props);const details=nodes(tree).find(n=>n.type==="details");
  assert.ok(details);assert.equal(details.props.open,undefined);assert.equal(nodes(details).filter(n=>n.type==="li").length,120);
  assert.equal(props.selected.size,120);
  assert.equal(nodes(tree).filter(n=>n.type==="input"&&n.props.type==="checkbox").length,0);
});

for (const mode of ["Manual","Automatic"]) test(`${mode}: one shared jobs navigation guards dirty and busy without deleting saved work`,()=>{
  const file=mode==="Manual"?"./page.tsx":"./AutomaticNotification.tsx";
  assert.match(source(file),/<JobsNavigationGuard busy=/);
  const h=harness("./JobsNavigationGuard.tsx","JobsNavigationGuard");
  h.render({busy:true,dirty:true});h.events.get("home")();assert.equal(h.locations.length,0);
  h.render({busy:false,dirty:true});h.events.get("home")();let tree=h.render({busy:false,dirty:true});
  assert.equal(tree.type,"modal");assert.equal(tree.props.placement,"center");
  tree.props.onClose();assert.equal(h.render({busy:false,dirty:true}),null);
  h.events.get("home")();tree=h.render({busy:false,dirty:true});
  nodes(tree).find(n=>n.type==="button"&&n.props.children==="求人一覧へ戻る").props.onClick();
  assert.deepEqual(h.locations,["/admin/jobs"]);
  assert.doesNotMatch(source("./JobsNavigationGuard.tsx"),/removeItem|adminApi/);
});

test("center placement is opt-in, hidden list scrolls, manual edit invalidates validation",()=>{
  const modal=source("../components/Modal.tsx");
  assert.match(modal,/placement = "sheet"/);assert.match(modal,/placement === "center" \? "center" : "flex-end"/);
  assert.match(source("./SelectionModeDialog.tsx"),/<Modal placement="center"/);
  assert.match(source("./page.tsx"),/<Modal placement="center" title="求人を変更/);
  assert.match(source("./page.tsx"),/setValidationSnapshot\(null\); setValidationInvalidation\("対象会員の編集後は再検証してください。"\); setStep\("detail"\)/);
  assert.match(source("./admin.css"),/hidden-selected ul\{max-height:16rem;overflow-y:auto/);
});
