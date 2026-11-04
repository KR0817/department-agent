/* Real knowledge UI state with synthetic responses; no model or network access. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('../frontend/node_modules/jsdom');
const source = fs.readFileSync(path.join(__dirname, '../clinical/static/department.js'), 'utf8');
const catalog = {index_sha256:'a'.repeat(64), sources:[], collaboration:{enabled:true,providers:['local','kimi']},consultation:{enabled:true,providers:[
  {provider:'local',model:'qwen3:14b',configured:true,enabled:true},
  {provider:'deepseek',model:'deepseek-flash',configured:true,enabled:true},
  {provider:'kimi',model:'kimi-k2.6',configured:false,enabled:false}]}};
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}
function answer(text='Synthetic response only.'){return {kind:'herb',subject:'SyntheticHerb',status:'answer',provider:'local',sections:[{key:'identity',text,evidence_ids:[]}],references:[],evidence_status:'no_matching_passages'};}
async function fixture(handler=async()=>answer(), inventory=catalog){
  const dom=new JSDOM('<main id="content"></main>',{runScripts:'outside-only',url:'http://127.0.0.1:19999'}),w=dom.window;
  w.matchMedia=()=>({matches:false});w.HTMLElement.prototype.scrollIntoView=()=>{};
  w.eval(source);
  let current=true;const requests=[],box=w.document.getElementById('content');
  const ctx={el:(tag,text,cls)=>{const e=w.document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;},
    error:(target,error)=>{target.textContent='Synthetic error: '+error.name;},isCurrent:()=>current,
    api:async(path,body,signal)=>{requests.push({path,body,signal});return path.endsWith('/catalog')?structuredClone(inventory):handler(path,body,signal);}};
  await w.Department.render('knowledge',box,ctx);
  const get=id=>w.document.getElementById(id);
  const change=(id,value)=>{const control=get(id);control.value=value;control.dispatchEvent(new w.Event('change'));};
  const input=(id,value)=>{const control=get(id);control.value=value;control.dispatchEvent(new w.Event('input'));};
  const submit=()=>box.querySelector('form').onsubmit({preventDefault(){}});
  const herb=()=>{change('department_mode','herb');input('department_subject','SyntheticHerb');input('department_question','Explain this fictional item.');};
  return {w,box,ctx,get,change,input,submit,herb,requests,setCurrent:value=>{current=value;}};
}

test('herb and formula modes send the explicit API contract and render model text safely',async()=>{
  const f=await fixture(async()=>answer('<img src=x onerror=alert(1)> Synthetic text'));
  f.herb();await f.submit();
  const sent=f.requests.at(-1);assert.equal(sent.path,'department/knowledge/consult');
  assert.equal(sent.body.kind,'herb');assert.equal(sent.body.provider,'local');assert.equal(sent.body.subject,'SyntheticHerb');
  assert.equal(f.get('department_answer').querySelector('img'),null);
  assert.match(f.get('department_answer').textContent,/<img src=x/);
  f.change('department_mode','formula');assert.equal(f.get('department_answer').querySelector('article'),null);
  f.input('department_subject','SyntheticFormula');await f.submit();assert.equal(f.requests.at(-1).body.kind,'formula');
  f.w.close();
});

test('API choice requires public-topic confirmation and missing configuration stays visible',async()=>{
  const f=await fixture();f.herb();f.change('department_provider','deepseek');
  assert.equal(f.get('department_ask').disabled,true);assert.equal(f.get('department_public_topic').parentElement.hidden,false);
  f.get('department_public_topic').checked=true;f.get('department_public_topic').dispatchEvent(new f.w.Event('change'));
  assert.equal(f.get('department_ask').disabled,false);await f.submit();
  assert.equal(f.requests.at(-1).body.public_topic_confirmed,true);assert.equal(f.requests.at(-1).body.provider,'deepseek');
  f.change('department_provider','kimi');assert.equal(f.get('department_ask').disabled,true);
  assert.match(f.get('department_model_status').textContent,/\u5c1a\u672a\u914d\u7f6e/);f.w.close();
});

test('editing a pending question aborts waiting and discards the stale answer',async()=>{
  const wait=deferred(),f=await fixture(()=>wait.promise);f.herb();const pending=f.submit();const request=f.requests.at(-1);
  f.input('department_question','Changed fictional question.');assert.equal(request.signal.aborted,true);
  wait.resolve(answer('STALE-MARKER'));await pending;
  assert.doesNotMatch(f.get('department_answer').textContent,/STALE-MARKER/);assert.equal(f.get('department_ask').disabled,false);f.w.close();
});

test('changing mode or provider cannot install an old answer',async()=>{
  for(const [id,value] of [['department_mode','formula'],['department_provider','deepseek']]){
    const wait=deferred(),f=await fixture(()=>wait.promise);f.herb();const pending=f.submit();
    f.change(id,value);wait.resolve(answer('STALE-MARKER'));await pending;
    assert.doesNotMatch(f.get('department_answer').textContent,/STALE-MARKER/);f.w.close();
  }
});

test('a new view rejects responses belonging to the prior rendered view',async()=>{
  const wait=deferred(),f=await fixture(()=>wait.promise);f.herb();const pending=f.submit();
  f.setCurrent(false);f.setCurrent(true);await f.w.Department.render('knowledge',f.box,f.ctx);
  wait.resolve(answer('STALE-VIEW'));await pending;assert.doesNotMatch(f.get('department_answer').textContent,/STALE-VIEW/);f.w.close();
});

test('cancel and logout abort pending work and clear answer state',async()=>{
  for(const logout of [false,true]){
    const wait=deferred(),f=await fixture(()=>wait.promise);f.herb();const pending=f.submit(),request=f.requests.at(-1);
    if(logout)f.w.Department.clear();else f.get('department_cancel').click();
    assert.equal(request.signal.aborted,true);wait.resolve(answer('STALE-SESSION'));await pending;
    if(logout)await f.w.Department.render('knowledge',f.box,f.ctx);
    assert.doesNotMatch(f.get('department_answer').textContent,/STALE-SESSION/);f.w.close();
  }
});

test('literature mode retains its original extraction payload',async()=>{
  const f=await fixture(async()=>({status:'insufficient',extracts:[]}));
  f.input('department_question','Synthetic literature question');await f.submit();
  assert.equal(f.requests.at(-1).path,'department/knowledge/extract');assert.equal('provider' in f.requests.at(-1).body,false);
  assert.equal(f.get('department_subject').parentElement.hidden,true);f.w.close();
});

function expertAnswer(){return {workflow:'expert-knowledge-v1',kind:'herb',subject:'SyntheticHerb',status:'partial',
  roles:{tcm:'completed',evidence:'failed',pharmacy:'completed',synthesis:'completed'},
  reports:{tcm:{status:'complete',claims:[{id:'tcm:1',text:'<img src=x> Synthetic claim',basis:'model_knowledge'}],uncertainties:[]},
    evidence:{status:'failed',claims:[],uncertainties:[]},pharmacy:{status:'complete',claims:[],uncertainties:[],concerns:[{text:'RETAINED-REVIEW-CONCERN',claim_ids:['tcm:1']}]}}
  ,synthesis:{overview:'Synthetic summary.',selected_claim_ids:['tcm:1'],unresolved:[]},references:[],result_sha256:'b'.repeat(64)};}

test('expert mode defaults to local independently of single provider and retains failures and concerns',async()=>{
  const f=await fixture(async path=>path.endsWith('/collaborate')?
    {job_id:'synthetic',status:'running',stage:'tcm',roles:{tcm:'running'}}:
    {job_id:'synthetic',status:'partial',result:expertAnswer()});
  f.herb();f.change('department_provider','deepseek');f.change('department_collaboration','experts');
  assert.equal(f.get('department_provider').parentElement.hidden,true);
  const pending=f.submit();await new Promise(done=>setTimeout(done,10));
  assert.match(f.box.textContent,/中医知识：处理中/);await pending;
  const sent=f.requests.find(row=>row.path.endsWith('/collaborate'));
  assert.equal(sent.body.provider,'local');assert.match(f.get('department_answer').textContent,/部分角色未完成/);
  assert.match(f.get('department_answer').textContent,/RETAINED-REVIEW-CONCERN/);
  assert.equal(f.get('department_answer').querySelector('img'),null);
  assert.equal(f.get('department_expert_review').checked,false);
  f.get('department_expert_review').checked=true;f.get('department_expert_review').dispatchEvent(new f.w.Event('change'));
  f.change('department_collaboration','single');assert.equal(f.get('department_expert_review'),null);f.w.close();
});

test('expert cancellation during polling requests server cancellation and discards later results',async()=>{
  const f=await fixture(async path=>path.endsWith('/cancel')?{status:'cancel_requested'}:
    {job_id:'synthetic',status:'running',stage:'tcm',roles:{tcm:'running'}});
  f.herb();f.change('department_collaboration','experts');const pending=f.submit();
  await new Promise(done=>setTimeout(done,10));f.get('department_cancel').click();await pending;
  assert.ok(f.requests.some(row=>row.path.endsWith('/synthetic/cancel')));
  assert.equal(f.get('department_ask').disabled,false);assert.doesNotMatch(f.get('department_answer').textContent,/Synthetic summary/);f.w.close();
});

test('logout interrupts polling delays and a late job creation is cancelled',async()=>{
  for(const late of [false,true]){
    const wait=deferred(),f=await fixture(async path=>path.endsWith('/cancel')?{status:'cancel_requested'}:
      late?wait.promise:{job_id:'synthetic',status:'running',stage:'tcm',roles:{tcm:'running'}});
    f.herb();f.change('department_collaboration','experts');const pending=f.submit();
    await new Promise(done=>setTimeout(done,10));f.w.Department.clear();
    if(late)wait.resolve({job_id:'synthetic',status:'running',roles:{}});
    await pending;assert.ok(f.requests.some(row=>row.path.endsWith('/synthetic/cancel')));f.w.close();
  }
});

test('a failed progress request asks the server to stop remaining roles',async()=>{
  const f=await fixture(async path=>{
    if(path.endsWith('/collaborate'))return {job_id:'synthetic',status:'running',roles:{tcm:'running'}};
    if(path.endsWith('/cancel'))return {status:'cancel_requested'};
    throw Error('Synthetic network failure');
  });
  f.herb();f.change('department_collaboration','experts');await f.submit();
  assert.ok(f.requests.some(row=>row.path.endsWith('/synthetic/cancel')));
  assert.equal(f.get('department_ask').disabled,false);f.w.close();
});

test('hybrid expert selection requires public acknowledgment and displays actual role models',async()=>{
  const inventory=structuredClone(catalog);Object.assign(inventory.consultation.providers[2],{configured:true,enabled:true,model:'kimi-k3.1-pro'});
  const models={tcm:{provider:'kimi',model:'kimi-k3.1-pro'},evidence:{provider:'local',model:'qwen3:14b'}};
  const result={...expertAnswer(),provider:'kimi',role_models:models,model_calls:[{role:'tcm',status:'completed',provider:'kimi'}]};
  const f=await fixture(async path=>path.endsWith('/collaborate')?
    {job_id:'hybrid',status:'running',role_models:models,roles:{tcm:'running',evidence:'running'}}:
    {status:'partial',result},inventory);
  f.herb();f.change('department_collaboration','experts');f.change('department_expert_provider','kimi');
  assert.equal(f.get('department_ask').disabled,true);assert.equal(f.get('department_public_topic').parentElement.hidden,false);
  assert.match(f.get('department_model_status').textContent,/kimi-k3.1-pro/);
  f.get('department_public_topic').checked=true;f.get('department_public_topic').dispatchEvent(new f.w.Event('change'));
  assert.equal(f.get('department_ask').disabled,false);const pending=f.submit();await new Promise(done=>setTimeout(done,10));
  assert.match(f.box.textContent,/Kimi API \/ kimi-k3.1-pro/);assert.match(f.box.textContent,/本地 \/ qwen3:14b/);await pending;
  const sent=f.requests.find(row=>row.path.endsWith('/collaborate'));
  assert.equal(sent.body.provider,'kimi');assert.equal(sent.body.public_topic_confirmed,true);
  assert.match(f.get('department_answer').textContent,/本地 \+ Kimi/);
  f.change('department_expert_provider','local');assert.equal(f.get('department_public_topic').checked,false);
  assert.equal(f.get('department_expert_review'),null);f.w.close();
});

test('hybrid missing key and old backend block dispatch; provider changes cancel a pending job',async()=>{
  for(const supported of [true,false]){
    const inventory=structuredClone(catalog);if(!supported)delete inventory.collaboration.providers;
    const f=await fixture(undefined,inventory);f.herb();f.change('department_collaboration','experts');f.change('department_expert_provider','kimi');
    assert.equal(f.get('department_ask').disabled,true);await f.submit();
    assert.equal(f.requests.filter(row=>row.path.endsWith('/collaborate')).length,0);f.w.close();
  }
  const f=await fixture(async()=>({job_id:'synthetic',status:'running',roles:{}}));
  f.herb();f.change('department_collaboration','experts');const pending=f.submit();await new Promise(done=>setTimeout(done,10));
  f.change('department_expert_provider','kimi');await pending;
  assert.ok(f.requests.some(row=>row.path.endsWith('/synthetic/cancel')));f.w.close();
});

test('all-Kimi requires separate public evidence consent and does not require an available local model',async()=>{
  const inventory=structuredClone(catalog);inventory.collaboration.modes=['local','local_kimi','all_kimi'];
  inventory.consultation.providers[0].enabled=false;
  Object.assign(inventory.consultation.providers[2],{configured:true,enabled:true,model:'kimi-k3.1-pro'});
  const models=Object.fromEntries(['tcm','evidence','pharmacy','synthesis'].map(role=>[role,{provider:'kimi',model:'kimi-k3.1-pro'}]));
  const f=await fixture(async()=>({...expertAnswer(),execution:'all_kimi',provider:'kimi',role_models:models}),inventory);
  f.herb();f.change('department_collaboration','experts');f.change('department_expert_provider','kimi_all');
  assert.equal(f.get('department_public_evidence').parentElement.hidden,false);
  f.get('department_public_topic').checked=true;f.get('department_public_topic').dispatchEvent(new f.w.Event('change'));
  assert.equal(f.get('department_ask').disabled,true);
  f.get('department_public_evidence').checked=true;f.get('department_public_evidence').dispatchEvent(new f.w.Event('change'));
  assert.equal(f.get('department_ask').disabled,false);assert.match(f.get('department_model_status').textContent,/最多 4 次/);
  await f.submit();const sent=f.requests.at(-1).body;
  assert.equal(sent.provider,'kimi');assert.equal(sent.expert_mode,'all_kimi');assert.equal(sent.public_evidence_confirmed,true);
  assert.match(f.get('department_answer').textContent,/全部 Kimi 3.1/);
  assert.match(f.get('department_answer').textContent,/已发送本次通用问题/);
  f.change('department_expert_provider','kimi');assert.equal(f.get('department_public_evidence').checked,false);
  assert.equal(f.get('department_public_evidence').parentElement.hidden,true);f.w.close();
});

test('all-Kimi cannot silently use an older Kimi model or unsupported server',async()=>{
  for(const supported of [false,true]){
    const inventory=structuredClone(catalog);if(supported)inventory.collaboration.modes=['all_kimi'];
    Object.assign(inventory.consultation.providers[2],{configured:true,enabled:true,model:'kimi-k2.6'});
    const f=await fixture(undefined,inventory);f.herb();f.change('department_collaboration','experts');f.change('department_expert_provider','kimi_all');
    for(const id of ['department_public_topic','department_public_evidence']){f.get(id).checked=true;f.get(id).dispatchEvent(new f.w.Event('change'));}
    assert.equal(f.get('department_ask').disabled,true);await f.submit();
    assert.equal(f.requests.filter(row=>row.path.endsWith('/collaborate')).length,0);f.w.close();
  }
});
