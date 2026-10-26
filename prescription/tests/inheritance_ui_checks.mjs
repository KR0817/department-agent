import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import test from 'node:test';

const html=fs.readFileSync(process.argv[2],'utf8');
const output=process.argv[3];
const decode=value=>value.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
const source=JSON.parse(html.match(/<script id="inheritance-data" type="application\/json">(.*?)<\/script>/s)[1]);

function setup(transform){
  const elements=new Map(),downloads=[];
  class Element{
    constructor(id){this.id=id;this.html='';this.textContent='';this.hidden=false;this.disabled=false;this.checked=false;this.attributes={};this.listeners={};this.items=[];this.inputs=[];this.current='';this.multiple=false;}
    set innerHTML(value){this.html=value;this.items=[...value.matchAll(/<option[^>]*value="([^"]*)"[^>]*>(.*?)<\/option>/gs)].map((m,i)=>({value:decode(m[1]),textContent:decode(m[2]),selected:i===0}));this.inputs=[...value.matchAll(/<input[^>]*type="checkbox"[^>]*value="([^"]*)"([^>]*)>/g)].map(m=>({value:decode(m[1]),checked:/\bchecked\b/.test(m[2])}));if(this.items.length)this.current=this.items[0].value;}
    get innerHTML(){return this.html;}
    get options(){return this.items;}
    get selectedOptions(){return this.items.filter(o=>o.selected);}
    get value(){return this.current;}
    set value(value){this.current=value;for(const option of this.items)option.selected=option.value===value;}
    querySelectorAll(selector){if(selector==='input:checked')return this.inputs.filter(n=>n.checked);if(selector==='input,select,textarea,button'){const block=html.match(new RegExp('<form id="'+this.id+'"[^>]*>(.*?)</form>','s'))?.[1]||'';return [...block.matchAll(/<(?:input|select|textarea|button)[^>]*\bid="([^"]+)"/g)].map(m=>el(m[1]));}return [];}
    addEventListener(type,fn){this.listeners[type]=fn;}
    setAttribute(key,value){this.attributes[key]=String(value);}
    focus(){this.focused=true;}
  }
  const el=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
  for(const match of html.matchAll(/<(?:button|input|textarea|select|div|form|section|tbody|span|p)\b[^>]*\bid="([^"]+)"[^>]*>/g)){const node=el(match[1]);node.checked=/\bchecked\b/.test(match[0]);node.disabled=/\bdisabled\b/.test(match[0]);node.hidden=/\bhidden\b/.test(match[0]);node.multiple=/\bmultiple\b/.test(match[0]);}
  for(const match of html.matchAll(/<select\b[^>]*id="([^"]+)"[^>]*>(.*?)<\/select>/gs))el(match[1]).innerHTML=match[2];
  const payload=JSON.parse(JSON.stringify(source));transform?.(payload);el('inheritance-data').textContent=JSON.stringify(payload);
  class DownloadURL{static createObjectURL(blob){downloads.push({blob});return 'blob:synthetic';}static revokeObjectURL(){}}
  const document={getElementById:el,body:{appendChild(){}},createElement:()=>({click(){downloads.at(-1).name=this.download;},remove(){}})};
  const context=vm.createContext({document,URL:DownloadURL,Blob,setTimeout:fn=>fn()});
  vm.runInContext(html.match(/<script id="inheritance-controller">(.*?)<\/script>/s)[1],context);
  const fire=(id,type,extra={})=>{assert.ok(el(id).listeners[type],`${id}.${type} must be bound`);el(id).listeners[type]({target:el(id),preventDefault(){},...extra});};
  const change=(id,value)=>{el(id).value=value;fire(id,'change');};
  const click=id=>fire(id,'click');
  const submit=id=>fire(id,'submit');
  const selectChecks=(id,values)=>{for(const item of el(id).inputs)item.checked=values.includes(item.value);};
  const setFields=values=>{for(const [id,value] of Object.entries(values))el(id).value=value;};
  const bundle=async()=>{click('export-draft');return JSON.parse(await downloads.at(-1).blob.text());};
  return {el,fire,change,click,submit,downloads,selectChecks,setFields,bundle,payload};
}

test('five real navigation handlers and keyboard navigation preserve selected state',()=>{
  const f=setup();assert.equal(f.el('stage-1').hidden,false);assert.equal(f.el('stage-2').hidden,true);
  for(let i=1;i<=5;i++){f.click('step-'+i);assert.equal(f.el('stage-'+i).hidden,false);assert.equal(f.el('step-'+i).attributes['aria-current'],'step');}
  f.fire('step-5','keydown',{key:'Home'});assert.equal(f.el('stage-1').hidden,false);assert.equal(f.el('step-1').focused,true);
  assert.match(f.el('synthetic-notice').textContent,/合成/);assert.match(f.el('draft-meta').textContent,/无本页修改/);
});

test('source filters and dependent approval protection use the actual edit form',async()=>{
  const f=setup();f.change('source-filter','pending');assert.match(f.el('source-rows').innerHTML,/SRC-SYN-C/);assert.doesNotMatch(f.el('source-rows').innerHTML,/SRC-SYN-A/);
  f.change('review-record','SRC-SYN-A');f.change('review-status','pending');assert.equal(f.el('review-reviewer').disabled,true);f.submit('review-form');assert.equal(f.el('review-message').attributes['data-error'],'true');
  assert.equal((await f.bundle()).sources.find(s=>s.source_id==='SRC-SYN-A').review_status,'confirmed');
  f.change('review-kind','physician');f.change('review-record','P-SYN-A');f.change('review-status','rejected');f.el('review-reviewer').value='R-SYN-01';f.submit('review-form');assert.match(f.el('review-message').textContent,/批准/);
  f.change('review-record','P-SYN-C');f.change('review-status','confirmed');f.el('review-reviewer').value='R-SYN-01';f.submit('review-form');assert.match(f.el('review-message').textContent,/来源/);
});

test('adjacent comparison exposes missing dose and severity without inventing changes',()=>{
  const f=setup();f.click('step-2');f.change('visit-select','V-3');assert.match(f.el('dose-comparison').innerHTML,/无法确定/);assert.match(f.el('dose-comparison').innerHTML,/剂量缺失/);assert.match(f.el('symptom-changes').innerHTML,/未知/);assert.match(f.el('visit-comparison').innerHTML,/记录证候/);
  f.change('case-select','C-SYN-03');f.change('visit-select','V-2');assert.match(f.el('pair-warning').innerHTML,/顺序未明确/);assert.match(f.el('medicine-changes').innerHTML,/不推断/);assert.doesNotMatch(f.el('dose-comparison').innerHTML,/<table/);
  f.fire('timeline','click',{target:{closest:()=>({dataset:{visit:'V-3'}})}});assert.equal(f.el('visit-select').value,'V-3');assert.match(f.el('pair-warning').innerHTML,/顺序未明确/);
});

test('source, annotation and experience forms export a validator-ready revision with exact parent hash',async()=>{
  const f=setup();f.change('review-record','SRC-SYN-C');f.change('review-status','confirmed');f.el('review-reviewer').value='R-SYN-01';f.submit('review-form');assert.equal(f.el('review-message').attributes['data-error'],'false');
  f.change('review-kind','physician');f.change('review-record','P-SYN-C');f.change('review-status','confirmed');f.el('review-reviewer').value='R-SYN-01';f.submit('review-form');assert.equal(f.el('review-message').attributes['data-error'],'false');
  f.click('step-3');f.change('annotation-select','A-SYN-03');f.setFields({'annotation-statement':'Synthetic reviewer interpretation after source review.','annotation-status':'approved','annotation-reviewer':'R-SYN-01'});f.submit('annotation-form');assert.equal(f.el('annotation-message').attributes['data-error'],'false');
  f.change('experience-select','');f.setFields({'experience-title':'Synthetic reviewed experience','experience-statement':'Recorded patterns for synthetic classroom discussion.','experience-scope':'Synthetic observations only.','experience-exception-note':'No exception pairs entered.','experience-status':'approved','experience-reviewer':'R-SYN-01'});
  f.selectChecks('experience-support',['C-SYN-05|V-1|V-2']);f.selectChecks('experience-annotations',['A-SYN-03']);f.submit('experience-form');assert.equal(f.el('experience-message').attributes['data-error'],'false');
  const revised=await f.bundle();assert.equal(revised.revision,source.bundle.revision+1);assert.equal(revised.parent_sha256,source.view.validation.content_sha256);assert.equal(revised.annotations.find(a=>a.annotation_id==='A-SYN-03').status,'approved');assert.equal(revised.experiences.at(-1).status,'approved');assert.deepEqual(revised.cases,source.bundle.cases);assert.equal(source.bundle.sources[2].review_status,'pending');
  assert.match(f.el('experience-summary').innerHTML,/不同受试者/);assert.match(f.el('experience-summary').innerHTML,/不表示不存在例外/);
  if(output)fs.writeFileSync(path.join(output,'edited-bundle.json'),JSON.stringify(revised));
  f.change('experience-select',revised.experiences.at(-1).experience_id);f.el('experience-statement').value='Edited synthetic experience statement.';f.submit('experience-form');assert.equal(f.el('experience-message').attributes['data-error'],'false');
  const edited=await f.bundle();assert.equal(edited.experiences.length,revised.experiences.length);assert.equal(edited.experiences.at(-1).statement,'Edited synthetic experience statement.');if(output)fs.writeFileSync(path.join(output,'revised-existing-bundle.json'),JSON.stringify(edited));
});

test('experience support overlap, algorithm-only approval and unknown attribution fail closed',async()=>{
  const f=setup();f.change('experience-select','');f.setFields({'experience-title':'Candidate','experience-statement':'Synthetic candidate pattern.','experience-scope':'Synthetic only.','experience-exception-note':'Unknown exceptions.','experience-status':'approved','experience-reviewer':'R-SYN-01'});
  f.selectChecks('experience-support',['C-SYN-01|V-2|V-3']);f.selectChecks('experience-annotations',['A-SYN-02']);f.submit('experience-form');assert.match(f.el('experience-message').textContent,/非算法批注/);
  f.selectChecks('experience-support',['C-SYN-01|V-1|V-2']);f.selectChecks('experience-annotations',['A-SYN-01']);f.selectChecks('experience-exceptions',['C-SYN-01|V-1|V-2']);f.submit('experience-form');assert.match(f.el('experience-message').textContent,/同时/);
  f.change('annotation-select','A-SYN-03');f.setFields({'annotation-status':'approved','annotation-reviewer':'R-SYN-01'});f.submit('annotation-form');assert.match(f.el('annotation-message').textContent,/已确认归属/);
  assert.equal((await f.bundle()).experiences.length,source.bundle.experiences.length);
  f.change('annotation-select','A-SYN-02');assert.equal(f.el('annotation-origin').disabled,true);f.el('annotation-origin').value='retrospective';f.el('annotation-statement').value='Still an algorithm hypothesis after review.';f.submit('annotation-form');assert.equal((await f.bundle()).annotations.find(a=>a.annotation_id==='A-SYN-02').origin,'algorithm');
});

test('privacy and core text limits are enforced before mutating editable records',async()=>{
  const f=setup();f.change('annotation-select','A-SYN-01');
  for(const unsafe of ['<img src=x onerror=alert(1)>','https://example.test','Review example.com','customscheme://host','javascript:alert(1)','１３８００１３８０００','2026-10-24','24/10/2026','first\u0000last','first\nlast']){f.el('annotation-statement').value=unsafe;f.submit('annotation-form');assert.equal(f.el('annotation-message').attributes['data-error'],'true',unsafe);}
  f.change('experience-select','E-SYN-01');f.el('experience-title').value='X'.repeat(121);f.submit('experience-form');assert.equal(f.el('experience-message').attributes['data-error'],'true');
  assert.deepEqual((await f.bundle()).annotations,source.bundle.annotations);
});

test('all rendered content is escaped even if embedded data is programmatically replaced',()=>{
  const f=setup(p=>{p.bundle.physicians[0].label='A <img src=x onerror=alert(1)> & "quoted"';p.bundle.vocabulary.symptoms[0].label='<script>bad()</script>';p.bundle.experiences[0].statement='<svg onload=bad()>';});
  assert.match(f.el('physician-rows').innerHTML,/&lt;img/);assert.doesNotMatch(f.el('physician-rows').innerHTML,/<img/);assert.match(f.el('visit-comparison').innerHTML,/&lt;script&gt;/);assert.doesNotMatch(f.el('experience-summary').innerHTML,/<svg/);
});

test('retrieval excludes the entire subject and pending sources and explains exact Jaccard',()=>{
  const f=setup();f.click('step-4');let results=f.el('search-results').innerHTML;assert.doesNotMatch(results,/C-SYN-01|C-SYN-02|C-SYN-05/);assert.match(results,/C-SYN-03|C-SYN-04/);assert.match(results,/匹配：/);assert.match(results,/仅当前：/);assert.match(results,/仅候选：/);assert.match(results,/6 \/ 6/);
  f.el('search-same-physician').checked=true;f.fire('search-same-physician','change');assert.match(f.el('search-results').innerHTML,/暂无可比记录/);
  f.el('search-same-physician').checked=false;f.fire('search-same-physician','change');
  for(const kind of ['conditions','symptoms','tongues','pulses','contexts']){f.el('feature-'+kind).checked=false;f.fire('feature-'+kind,'change');}assert.match(f.el('search-results').innerHTML,/暂无可比记录/);
  f.el('feature-syndromes').checked=true;f.fire('feature-syndromes','change');assert.match(f.el('search-query').innerHTML,/证候解释/);assert.doesNotMatch(f.el('search-query').innerHTML,/后续观察|黄芪/);
});

test('current retrieval features ignore outcomes, medicines and later-visit observations',()=>{
  const a=setup(),b=setup(p=>{p.bundle.cases[0].visits[0].prescription=[];p.bundle.cases[0].visits[0].outcome_codes=['SYN_CHANGE'];p.bundle.cases[0].visits[2].pre.symptoms=[];});
  assert.equal(a.el('search-query').innerHTML,b.el('search-query').innerHTML);assert.equal(a.el('search-results').innerHTML,b.el('search-results').innerHTML);
});

test('rehearsal actual submit gates reveal, exports the recorded reasoning and clears on visit change',async()=>{
  const f=setup();f.click('step-5');f.change('visit-select','V-2');assert.equal(f.el('training-reveal').hidden,true);assert.equal(f.el('training-reveal').innerHTML,'');
  const before=f.el('training-observations').innerHTML+f.el('training-previous').innerHTML;assert.doesNotMatch(before,/气虚记录|气阴两虚记录|益气治则记录|合成后续观察|回顾解释|算法假设/);const prior=source.bundle.cases[0].visits[0].prescription[0];assert.match(f.el('training-previous').innerHTML,/黄芪/);assert.ok(f.el('training-previous').innerHTML.includes(`${prior.dose} ${prior.unit}`));assert.doesNotMatch(f.el('training-previous').innerHTML,/20 g/);
  f.submit('training-form');assert.equal(f.el('training-reveal').hidden,true);f.click('export-attempt');assert.equal(f.downloads.length,0);
  f.setFields({'training-syndrome':'Synthetic syndrome reasoning.','training-principle':'Synthetic principle reasoning.','training-plan':'Review the previous recorded dose.','training-rationale':'Synthetic observations support discussion only.'});f.submit('training-form');assert.equal(f.el('training-reveal').hidden,false);assert.match(f.el('training-reveal').innerHTML,/20 g|气虚记录/);assert.match(f.el('training-reveal').innerHTML,/回顾解释/);
  f.click('export-attempt');const attempt=JSON.parse(await f.downloads[0].blob.text());assert.equal(attempt.case_id,'C-SYN-01');assert.equal(attempt.visit_id,'V-2');assert.equal(attempt.learner_reasoning.rationale,'Synthetic observations support discussion only.');assert.equal(attempt.bundle_sha256,source.view.validation.content_sha256);assert.equal(attempt.automatic_score,null);assert.equal(attempt.clinical_safety_assessed,false);
  f.change('visit-select','V-3');assert.equal(f.el('training-reveal').hidden,true);assert.equal(f.el('training-reveal').innerHTML,'');assert.equal(f.el('training-rationale').value,'');assert.equal(f.el('export-attempt').disabled,true);
  f.change('case-select','C-SYN-03');f.change('visit-select','V-2');assert.match(f.el('training-previous').innerHTML,/无顺序明确/);
});

test('rehearsal reveals only loaded annotations so its exported content hash remains truthful',async()=>{
  const f=setup();f.change('annotation-select','A-SYN-01');f.el('annotation-statement').value='DRAFT MENTOR ALTERED';f.submit('annotation-form');assert.equal(f.el('annotation-message').attributes['data-error'],'false');f.change('visit-select','V-2');
  f.setFields({'training-syndrome':'Synthetic reasoning.','training-principle':'Synthetic principle.','training-plan':'Synthetic plan.','training-rationale':'Synthetic rationale.'});f.submit('training-form');assert.doesNotMatch(f.el('training-reveal').innerHTML,/DRAFT MENTOR ALTERED/);assert.ok(f.el('training-reveal').innerHTML.includes(source.bundle.annotations[0].statement));f.click('export-attempt');assert.equal(JSON.parse(await f.downloads[0].blob.text()).bundle_sha256,source.view.validation.content_sha256);
});

test('nonsynthetic pages remain read-only even when disabled actions are invoked directly',()=>{
  const f=setup(p=>{p.bundle.synthetic=false;p.bundle.local_authorization=true;p.bundle.deidentified=true;});assert.match(f.el('global-status').textContent,/受控 work 目录/);assert.equal(f.el('export-draft').disabled,true);assert.equal(f.el('annotation-statement').disabled,true);assert.equal(f.el('training-rationale').disabled,true);
  for(const id of ['save-review','save-annotation','save-experience','save-rehearsal'])assert.equal(f.el(id).disabled,true);
  f.change('review-record','SRC-SYN-C');f.change('review-status','confirmed');f.el('review-reviewer').value='R-SYN-01';f.submit('review-form');assert.match(f.el('source-rows').innerHTML,/pending/);
  f.change('annotation-select','A-SYN-01');f.el('annotation-statement').value='Attempted clinical edit.';f.submit('annotation-form');f.change('annotation-select','A-SYN-01');assert.equal(f.el('annotation-statement').value,source.bundle.annotations[0].statement);
  f.change('experience-select','E-SYN-01');f.el('experience-title').value='Attempted clinical experience edit';f.submit('experience-form');f.change('experience-select','E-SYN-01');assert.equal(f.el('experience-title').value,source.bundle.experiences[0].title);
  f.setFields({'training-syndrome':'Synthetic reasoning.','training-principle':'Synthetic principle.','training-plan':'Synthetic plan.','training-rationale':'Synthetic rationale.'});f.submit('training-form');assert.equal(f.el('training-reveal').hidden,true);f.click('export-draft');f.click('export-attempt');assert.equal(f.downloads.length,0);assert.match(f.el('draft-meta').textContent,/无本页修改/);
  f.click('step-2');f.change('visit-select','V-2');assert.match(f.el('visit-comparison').innerHTML,/记录处方/);f.click('step-4');assert.match(f.el('search-results').innerHTML,/候选访次/);
});
