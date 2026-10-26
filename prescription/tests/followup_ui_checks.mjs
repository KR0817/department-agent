import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const html=fs.readFileSync(process.argv[2],'utf8');
function setup(){
  const elements=new Map(),events=new Map(),downloads=[],stack=[];let cursor=-1;
  const element=id=>{
    if(!elements.has(id))elements.set(id,{id,innerHTML:'',textContent:'',hidden:false,disabled:false,value:'',checked:id==='fold-combos',dataset:{},listeners:{},attributes:{},
      get options(){return [...this.innerHTML.matchAll(/<option[^>]*value="([^"]*)"[^>]*>(.*?)<\/option>/g)].map(match=>({value:match[1],textContent:match[2]}))},
      addEventListener(type,fn){const previous=this.listeners[type];this.listeners[type]=event=>{previous?.(event);fn(event)}},setAttribute(name,value){this.attributes[name]=String(value)},getAttribute(name){return this.attributes[name]??null},focus(options){this.focused=true;this.focusOptions=options},scrollIntoView(){this.scrolled=true}});
    return elements.get(id);
  };
  for(const id of ['dashboard-data','supplement-data'])element(id).textContent=html.match(new RegExp('<script id="'+id+'" type="application/json">(.*?)</script>','s'))[1];
  element('analysis-source').innerHTML='<option value="primary">Primary</option><option value="supplement">Supplement</option>';
  const annual=['prevalence','addition','removal'].map(annual=>Object.assign(element('annual-'+annual),{dataset:{annual}}));
  const sizes=['all','2','3'].map(size=>Object.assign(element('size-'+size),{dataset:{size}}));
  const location={href:'http://127.0.0.1:18877/index.html',search:''};
  const updateUrl=url=>{location.href=String(url);location.search=new URL(url).search};
  const clone=value=>JSON.parse(JSON.stringify(value));
  const history={replaceState(state,_title,url){if(cursor<0){cursor=0;stack.push(clone(state))}else stack[cursor]=clone(state);updateUrl(url)},pushState(state,_title,url){stack.splice(++cursor);stack.push(clone(state));updateUrl(url)},back(){if(cursor>0){cursor--;events.get('popstate')({state:stack[cursor]})}},forward(){if(cursor+1<stack.length){cursor++;events.get('popstate')({state:stack[cursor]})}},get state(){return stack[cursor]}};
  class TestURL extends URL{static createObjectURL(blob){downloads.push({blob});return 'blob:fixture'}static revokeObjectURL(){}}
  const document={getElementById:element,title:'',body:{appendChild(){}},addEventListener(type,fn){events.set('document-'+type,fn)},createElement:()=>({click(){downloads.at(-1).name=this.download},remove(){}}),querySelectorAll:selector=>({'.annual-btn':annual,'.filter-btn[data-size]':sizes}[selector]||[])};
  const context=vm.createContext({document,location,history,URL:TestURL,URLSearchParams,Blob,setTimeout:fn=>fn(),addEventListener:(type,fn)=>events.set(type,fn)});
  vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
  // The network adapter has its own tested runtime. Exercise the actual base
  // source/history handlers plus this adapter, not replicas of their behavior.
  vm.runInContext(html.match(/<script id="followup-ui-script">([\s\S]*?)<\/script>/)[1],context);
  const change=(id,value)=>element(id).listeners.change({target:{value}});
  return {element,events,history,downloads,change,run:code=>vm.runInContext(code,context)};
}

test('same-scope disclosed values zero and missing remain distinct without input mutation',()=>{
  const f=setup();f.run('globalThis.saved=JSON.stringify(data);render()');assert.equal(f.run('JSON.stringify(data)===saved'),true);
  assert.match(f.element('followup-summary').innerHTML,/0\.0%/);assert.match(f.element('followup-summary').innerHTML,/>40</);assert.match(f.element('followup-summary').innerHTML,/>55</);
  assert.match(f.element('followup-additions').innerHTML,/0\.0%/);assert.match(f.element('followup-additions').innerHTML,/未公开 \/ 未估计/);
  assert.match(f.element('followup-additions').innerHTML,/Herb &lt;unsafe&amp;&quot;&gt;/);assert.doesNotMatch(f.element('followup-additions').innerHTML,/<unsafe/);
  assert.match(f.element('followup-availability').innerHTML,/保留药味汇总 · 未提供/);assert.match(f.element('followup-availability').innerHTML,/同药剂量增减 · 未提供/);
  f.run("research.modes=[{group:'ra_strict',median_patient_jaccard:999}];render()");assert.doesNotMatch(f.element('followup-summary').innerHTML,/999/);
});

test('period direction annual selection and missing years preserve exact published denominators',()=>{
  const f=setup();f.change('followup-item','Herb A');f.change('followup-period','2020');
  assert.match(f.element('followup-additions').innerHTML,/0 \/ 20/);assert.match(f.element('followup-additions').innerHTML,/0\.0%/);
  f.change('followup-direction','addition');assert.equal(f.element('followup-removal-panel').hidden,true);assert.equal(f.element('followup-addition-panel').hidden,false);
  f.change('followup-period','2021');assert.equal(f.element('followup-export').disabled,true);assert.match(f.element('followup-additions').innerHTML,/未公开不等于零/);
  const row=f.element('followup-annual').innerHTML.match(/<tr data-period-selected="true">([\s\S]*?)<\/tr>/)[1];assert.match(row,/2021/);assert.equal((row.match(/未公开/g)||[]).length,6);assert.doesNotMatch(row,/0\.0%/);
  f.change('followup-period','2022');assert.match(f.element('followup-additions').innerHTML,/12 \/ 30/);assert.match(f.element('followup-annual').innerHTML,/6 \/ 30/);
});

test('all global group stratum and query choices update the dedicated section',()=>{
  const f=setup();f.change('followup-period','2022');f.change('followup-group','sjd');assert.equal(f.run('selected'),'sjd');assert.equal(f.element('followup-period').value,'all');assert.equal(f.element('followup-item').disabled,true);assert.match(f.element('followup-scope').textContent,/干燥/);
  f.change('followup-group','ra');f.run("selectStratum('sex','female')");assert.equal(f.element('followup-export').disabled,true);assert.doesNotMatch(f.element('followup-additions').innerHTML,/10 \/ 40/);assert.match(f.element('followup-scope').textContent,/Female/);
  f.run("selectStratum('overall','all')");f.element('search').value='no-match';f.element('search').listeners.input({target:f.element('search')});assert.equal(f.element('followup-export').disabled,true);assert.equal(f.element('followup-item').disabled,true);assert.match(f.element('followup-status').textContent,/no-match/);
});

test('real search input handlers keep follow-up display export and clearing in the same scope',async()=>{
  const f=setup(),search=f.element('search');search.value=' Herb A ';search.listeners.input({target:search});
  assert.equal(f.run('query'),'herb a');assert.match(f.element('item-list').innerHTML,/Herb A/);assert.match(f.element('followup-status').textContent,/herb a/);
  assert.match(f.element('followup-additions').innerHTML,/Herb A/);assert.doesNotMatch(f.element('followup-additions').innerHTML,/unsafe/);assert.doesNotMatch(f.element('followup-item').innerHTML,/unsafe/);
  f.element('followup-export').listeners.click();const csv=await f.downloads[0].blob.text();assert.match(csv,/"herb a"/);assert.doesNotMatch(csv,/unsafe/);
  search.value='no-match';search.listeners.input({target:search});assert.equal(f.element('followup-export').disabled,true);assert.equal(f.element('followup-item').disabled,true);assert.doesNotMatch(f.element('followup-additions').innerHTML,/Herb A/);
  f.element('followup-export').listeners.click();assert.equal(f.downloads.length,1);
  f.element('clear-search').listeners.click();assert.equal(f.run('query'),'');assert.equal(search.value,'');assert.equal(f.element('followup-export').disabled,false);assert.match(f.element('followup-additions').innerHTML,/unsafe/);
});

test('actual source reset and history restore local selections with source-scoped keys',()=>{
  const f=setup();f.change('followup-item','Herb A');f.change('followup-period','2022');f.change('followup-direction','removal');
  const before=JSON.parse(JSON.stringify(f.run('captureViewState()')));assert.equal(before.followup_view.period,'2022');assert.equal(before.followup_view.direction,'removal');
  f.run("switchAnalysisSource('supplement')");assert.equal(f.run('data.source_identity.key'),'supplement');assert.equal(f.element('followup-period').value,'all');assert.equal(f.element('followup-direction').value,'both');assert.doesNotMatch(f.element('followup-item').innerHTML,/>Herb A</);
  f.history.back();assert.equal(f.run('data.source_identity.key'),'primary');assert.equal(f.element('followup-period').value,'2022');assert.equal(f.element('followup-direction').value,'removal');assert.equal(f.element('followup-item').value,'Herb A');
  f.history.forward();assert.equal(f.run('data.source_identity.key'),'supplement');assert.equal(f.element('followup-period').value,'all');
  f.history.back();f.run('resetDashboardView()');assert.equal(f.element('followup-period').value,'all');assert.equal(f.element('followup-direction').value,'both');
  f.history.back();assert.equal(f.element('followup-period').value,'2022');assert.equal(f.element('followup-direction').value,'removal');
});

test('old history without new fields resets local state instead of retaining a future choice',()=>{
  const f=setup();f.change('followup-period','2022');f.change('followup-direction','removal');
  f.run('globalThis.oldView=captureViewState();delete oldView.followup_view;applyViewState(oldView)');
  assert.equal(f.element('followup-period').value,'all');assert.equal(f.element('followup-direction').value,'both');
});

test('privacy blocks every longitudinal output and export even with populated payload tables',()=>{
  const f=setup();f.run('data.privacy={longitudinal_enabled:false};render()');
  assert.equal(f.element('followup-export').disabled,true);assert.equal(f.element('followup-export-annual').disabled,true);assert.equal(f.element('followup-direction').disabled,true);assert.equal(f.element('followup-period').disabled,true);assert.equal(f.element('followup-item').disabled,true);
  assert.doesNotMatch(f.element('followup-summary').innerHTML,/>40</);assert.doesNotMatch(f.element('followup-summary').innerHTML,/>55</);assert.doesNotMatch(f.element('followup-additions').innerHTML,/Herb A/);
  f.element('followup-export').listeners.click();f.element('followup-export-annual').listeners.click();assert.equal(f.downloads.length,0);
  f.run('data.privacy.longitudinal_enabled=true;render()');assert.equal(f.element('followup-export').disabled,false);
});

test('CSV preserves values scope and formula safety and task checklist is not annotation evidence',async()=>{
  const f=setup();f.change('followup-item','Herb A');f.change('followup-period','2022');f.change('followup-direction','removal');f.element('followup-export').listeners.click();
  const csv=await f.downloads[0].blob.text();assert.match(csv,/"primary"/);assert.match(csv,/"2022"/);assert.match(csv,/"removal"/);assert.match(csv,/"30","6","\.2","\.2"/);assert.doesNotMatch(csv,/"addition"/);
  f.element('followup-export-annual').listeners.click();const annual=await f.downloads[1].blob.text();assert.match(annual,/"all_disclosed_years"/);assert.match(annual,/"20","0","0","0"/);assert.doesNotMatch(annual,/"2021"/);
  f.run("data.changes.push({...data.changes[0],item_name:'=UNTRUSTED()'});render()");f.change('followup-period','all');f.change('followup-direction','both');f.element('followup-export').listeners.click();assert.match(await f.downloads[2].blob.text(),/"'=UNTRUSTED\(\)"/);
  f.element('followup-checklist').listeners.click();const checklist=JSON.parse(await f.downloads[3].blob.text());assert.equal(checklist.kind,'research_task_checklist');assert.equal(checklist.contains_case_data,false);assert.equal(checklist.contains_annotation_results,false);assert.equal(checklist.tasks.length,7);assert.ok(checklist.tasks.every(row=>row.status==='not_started'&&row.evidence_status==='not_attached'));
});

test('duplicate annual scopes remain unavailable and missing data produce useful empty states',()=>{
  const f=setup();f.change('followup-item','Herb A');f.run('data.yearChanges.push({...data.yearChanges[0],repeat_patients:999});render()');
  const row=f.element('followup-annual').innerHTML.match(/<tr[^>]*><td>2020<\/td>([\s\S]*?)<\/tr>/)[1];assert.doesNotMatch(row,/999/);assert.match(row,/未公开/);
  f.run('data.groups=[];data.changes=[];data.yearChanges=[];data.yearSummaries=[];data.longitudinal=[];selected="";render()');assert.equal(f.element('followup-group').disabled,true);assert.equal(f.element('followup-item').disabled,true);assert.equal(f.element('followup-export').disabled,true);assert.match(f.element('followup-annual').innerHTML,/没有可公开/);
});

test('clinical preparation tabs have native activation and roving keyboard focus',()=>{
  const f=setup();f.element('followup-benchmark-tab').listeners.click();assert.equal(f.element('followup-benchmark-panel').hidden,false);assert.equal(f.element('followup-clinical-panel').hidden,true);assert.equal(f.element('followup-benchmark-tab').attributes['aria-selected'],'true');
  let prevented=false;f.element('followup-benchmark-tab').listeners.keydown({key:'ArrowLeft',preventDefault(){prevented=true}});assert.equal(prevented,true);assert.equal(f.element('followup-clinical-panel').hidden,false);assert.equal(f.element('followup-clinical-tab').focused,true);assert.equal(f.element('followup-clinical-tab').focusOptions.preventScroll,true);
});
