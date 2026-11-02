/* State-level races use the real frontend module and a minimal DOM test double.
   Layout and browser behavior are verified separately in the local preview. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname,'../clinical/static/assistant.js'),'utf8');

function element(tag, text = '') {
  return {tag, text, children:[], value:'', dataset:{}, disabled:false, isConnected:true,
    append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.children=nodes;},
    prepend(...nodes){this.children.unshift(...nodes);},
    setAttribute(key,value){this[key]=value;},
    click(){return this.onclick?.();},
    get textContent(){return String(this.text||'')+this.children.map(n=>n.textContent||'').join('');},
    set textContent(value){this.text=value;this.children=[];}};
}
function find(root,id){if(root.id===id)return root;for(const node of root.children||[]){const found=find(node,id);if(found)return found;}return null;}
function label(root,text){if(root.tag==='button'&&root.text===text)return root;for(const node of root.children||[]){const found=label(node,text);if(found)return found;}return null;}
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}
async function fixture(handler) {
  const listeners={},requests=[],box=element('main');
  const window={addEventListener(name,fn){listeners[name]=fn;},Department:{useAssistantRecords(){throw Error('Unexpected business handoff');}}};
  vm.runInNewContext(source,{window,location:{hash:''},crypto:webcrypto,structuredClone,AbortController});
  const ctx={el:element,isCurrent:()=>true,api:async(path,body,signal)=>{
    requests.push({path,body,signal});if(path==='department/assistant/drafts'&&body===undefined)return {drafts:[]};
    return handler(path,body,signal);
  }};
  await window.DepartmentAssistant.render(box,ctx);
  const input=(id,value)=>{const control=find(box,id);assert.ok(control,id);control.value=value;control.oninput();};
  const intake=()=>{const task=find(box,'assistant_task');task.value='intake';task.onchange();};
  const dirty=()=>{let prevented=false;listeners.beforeunload({preventDefault(){prevented=true;}});return prevented;};
  return {box,window,ctx,requests,input,intake,dirty};
}

test('editing while a save is in flight preserves new text and advances its base revision',async()=>{
  const wait=deferred();let writes=0;
  const f=await fixture(async(path,body)=>{writes++;if(writes===1)return wait.promise;return {revision:2};});
  f.input('assistant_instruction','Synthetic first draft');
  const pending=find(f.box,'assistant_save').onclick();
  f.input('assistant_instruction','Synthetic later edit');
  wait.resolve({revision:1});await pending;
  assert.equal(find(f.box,'assistant_instruction').value,'Synthetic later edit');
  assert.equal(f.dirty(),true);
  await find(f.box,'assistant_save').onclick();
  const saves=f.requests.filter(r=>r.body?.expected_revision!==undefined);
  assert.equal(saves[0].body.draft.instruction,'Synthetic first draft');
  assert.equal(saves[1].body.expected_revision,1);
  assert.equal(saves[1].body.draft.instruction,'Synthetic later edit');
  assert.equal(f.dirty(),false);
});

test('late recognition cannot reinstall candidates after source editing',async()=>{
  const wait=deferred();const f=await fixture(()=>wait.promise);f.intake();
  f.input('assistant_text','Synthetic original');
  const pending=find(f.box,'assistant_prepare').onclick();
  f.input('assistant_text','Synthetic changed source');
  wait.resolve({records:[],original_records:[],missing:[],supplements:[]});await pending;
  assert.equal(find(f.box,'assistant_handoff').disabled,true);
  assert.equal(find(f.box,'assistant_intake_result').children.some(n=>n.tag==='h3'),false);
});

test('logout aborts owned work and ignores a late save acknowledgement',async()=>{
  const wait=deferred();const f=await fixture(()=>wait.promise);
  f.input('assistant_instruction','Synthetic session content');
  const pending=find(f.box,'assistant_save').onclick();
  const request=f.requests.find(r=>r.body?.expected_revision===0);
  f.window.DepartmentAssistant.clear();assert.equal(request.signal.aborted,true);
  wait.resolve({revision:5});await pending;
  await f.window.DepartmentAssistant.render(f.box,f.ctx);
  assert.equal(find(f.box,'assistant_instruction').value,'');
  assert.equal(f.dirty(),false);
  assert.equal(find(f.box,'assistant_save_status').textContent.includes('5'),false);
});

test('a conflict retains edits and saves the explicit copy under a new identity',async()=>{
  let writes=0;
  const f=await fixture(async()=>{if(++writes===1)throw Object.assign(new Error('conflict'),{status:409});return {revision:1};});
  f.input('assistant_instruction','Synthetic retained edit');
  await find(f.box,'assistant_save').onclick();
  assert.equal(f.dirty(),true);
  const feedback=find(f.box,'assistant_feedback');assert.equal(feedback.children.at(-1).tag,'button');
  feedback.children.at(-1).click();await new Promise(resolve=>setImmediate(resolve));
  const saves=f.requests.filter(r=>r.body?.expected_revision!==undefined);
  assert.equal(saves.length,2);assert.notEqual(saves[0].path,saves[1].path);
  assert.equal(saves[1].body.expected_revision,0);
  assert.equal(saves[1].body.draft.instruction,'Synthetic retained edit');
  assert.equal(f.dirty(),false);
});

test('cancelling recognition discards even a successful late response',async()=>{
  const wait=deferred();const f=await fixture(()=>wait.promise);f.intake();
  f.input('assistant_text','Synthetic pending text');
  const pending=find(f.box,'assistant_prepare').onclick();
  find(f.box,'assistant_cancel').click();
  assert.equal(f.requests.at(-1).signal.aborted,true);
  wait.resolve({records:[],original_records:[],missing:[],supplements:[]});await pending;
  assert.equal(find(f.box,'assistant_intake_result').children.some(n=>n.tag==='h3'),false);
  assert.equal(find(f.box,'assistant_activity').textContent.includes('已取消'),true);
  assert.equal(find(f.box,'assistant_text').value,'Synthetic pending text');
});

test('guided fields reject empty answers, distinguish unavailable and preserve provenance',async()=>{
  const record={record_id:'REC-'+'a'.repeat(24),subject_code:'SYN-1',date:'2026-01-01',symptoms:'Synthetic',tongue:'',pulse:'',syndrome:'S',principle:'P',prescription:'H',source_sha256:'b'.repeat(64)};
  const f=await fixture(async(path,body)=>({records:[record],original_records:[record],supplements:body.supplements,
    missing:['tongue','pulse'].map(field=>body.supplements.find(s=>s.field===field)||{record_id:record.record_id,field,status:'not_asked',value:'',origin:'unknown'})}));
  f.intake();f.input('assistant_text','Synthetic source');await find(f.box,'assistant_prepare').click();
  const initialRequests=f.requests.length;
  await find(f.box,'assistant_next').click();assert.equal(f.requests.length,initialRequests);
  await find(f.box,'assistant_unavailable').click();
  assert.equal(find(f.box,'assistant_progress').textContent.includes('无法提供 1'),true);
  const status=find(f.box,'assistant_status_'+record.record_id+'_pulse');status.value='recorded';status.onchange();
  const origin=find(f.box,'assistant_origin_'+record.record_id+'_pulse');origin.value='clinician';origin.onchange();
  f.input('assistant_value_'+record.record_id+'_pulse','Synthetic pulse observation');
  await find(f.box,'assistant_next').click();
  const supplement=f.requests.at(-1).body.supplements;
  assert.equal(supplement[0].status,'unavailable');assert.equal(supplement[0].value,'');
  assert.equal(supplement[1].origin,'clinician');assert.equal(supplement[1].value,'Synthetic pulse observation');
  assert.equal(find(f.box,'assistant_progress').textContent.includes('尚未记录 0'),true);
  assert.equal(find(f.box,'assistant_handoff').disabled,true);
});

test('historical recovery previews before loading and appends using the current base revision',async()=>{
  let savedBody,base=0;
  const f=await fixture(async(path,body)=>{
    if(body?.expected_revision!==undefined){savedBody=structuredClone(body.draft);base++;return {revision:base};}
    if(path.endsWith('/history'))return {versions:[{revision:1,saved_at:'2026-11-02T00:00:00Z'}],next_before:null};
    if(path.endsWith('/revisions/1'))return {revision:1,saved_at:'2026-11-02T00:00:00Z',draft:{...savedBody,instruction:'Historical synthetic title'}};
    throw Error('Unexpected request');
  });
  f.input('assistant_instruction','Current synthetic title');await find(f.box,'assistant_save').click();
  f.input('assistant_instruction','Second synthetic title');await find(f.box,'assistant_save').click();
  await find(f.box,'assistant_history_open').click();await label(f.box,'查看版本 1').click();
  assert.equal(find(f.box,'assistant_instruction').value,'Second synthetic title');
  find(f.box,'assistant_restore').click();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(find(f.box,'assistant_instruction').value,'Historical synthetic title');assert.equal(f.dirty(),true);
  await find(f.box,'assistant_save').click();
  const writes=f.requests.filter(r=>r.body?.expected_revision!==undefined);
  assert.equal(writes.at(-1).body.expected_revision,2);
  assert.equal(writes.at(-1).body.draft.instruction,'Historical synthetic title');
  assert.equal(find(f.box,'assistant_save_status').textContent.includes('3'),true);
});

test('historical recovery refuses to replace unsaved edits',async()=>{
  let savedBody;
  const f=await fixture(async(path,body)=>{
    if(body){savedBody=body.draft;return {revision:1};}
    if(path.endsWith('/history'))return {versions:[{revision:1,saved_at:'2026-11-02T00:00:00Z'}],next_before:null};
    return {revision:1,saved_at:'2026-11-02T00:00:00Z',draft:savedBody};
  });
  f.input('assistant_instruction','Saved title');await find(f.box,'assistant_save').click();
  await find(f.box,'assistant_history_open').click();await label(f.box,'查看版本 1').click();
  f.input('assistant_instruction','Unsaved title');find(f.box,'assistant_restore').click();
  assert.equal(find(f.box,'assistant_instruction').value,'Unsaved title');assert.equal(f.dirty(),true);
});
