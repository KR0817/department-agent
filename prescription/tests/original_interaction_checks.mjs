import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const html=fs.readFileSync(process.argv[2],'utf8');
function setup(){
  const elements=new Map(),events=new Map(),downloads=[],stack=[];
  let cursor=-1;
  const element=id=>{
    if(!elements.has(id))elements.set(id,{innerHTML:'',textContent:'',hidden:false,disabled:false,value:'',checked:id==='fold-combos',dataset:{},listeners:{},attributes:{},
      get options(){return [...this.innerHTML.matchAll(/<option[^>]*value="([^"]*)"[^>]*>(.*?)<\/option>/g)].map(match=>({value:match[1],textContent:match[2]}))},
      addEventListener(type,fn){this.listeners[type]=fn},setAttribute(key,value){this.attributes[key]=value},focus(){this.focused=true},scrollIntoView(){this.scrolled=true}});
    return elements.get(id);
  };
  for(const id of ['dashboard-data','supplement-data'])element(id).textContent=html.match(new RegExp('<script id="'+id+'" type="application/json">(.*?)</script>','s'))[1];
  element('analysis-source').innerHTML='<option value="primary">Primary</option><option value="supplement">Supplement</option>';
  const annual=['prevalence','addition','removal'].map(annual=>Object.assign(element('annual-'+annual),{dataset:{annual}}));
  const sizes=['all','2','3'].map(size=>Object.assign(element('size-'+size),{dataset:{size}}));
  const location={href:'http://127.0.0.1:18877/index.html',search:''};
  const updateUrl=url=>{location.href=String(url);location.search=new URL(url).search};
  const clone=value=>JSON.parse(JSON.stringify(value));
  const history={
    replaceState(state,_title,url){if(cursor<0){cursor=0;stack.push(clone(state))}else stack[cursor]=clone(state);updateUrl(url)},
    pushState(state,_title,url){stack.splice(++cursor);stack.push(clone(state));updateUrl(url)},
    back(){if(cursor>0){cursor--;const state=stack[cursor];events.get('popstate')({state})}},
    get state(){return stack[cursor]}
  };
  class TestURL extends URL{static createObjectURL(blob){downloads.push({blob});return 'blob:fixture'}static revokeObjectURL(){}}
  const document={getElementById:element,title:'',body:{appendChild(){}},addEventListener(type,fn){events.set('document-'+type,fn)},
    createElement:()=>({click(){downloads.at(-1).name=this.download},remove(){}}),
    querySelectorAll:selector=>({'.annual-btn':annual,'.filter-btn[data-size]':sizes}[selector]||[])};
  const context=vm.createContext({document,location,history,URL:TestURL,URLSearchParams,Blob,setTimeout:fn=>fn(),addEventListener:(type,fn)=>events.set(type,fn)});
  vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
  return {element,events,history,downloads,run:code=>vm.runInContext(code,context)};
}

test('original source overview and navigation use real-neutral context',()=>{
  const {element,run}=setup();
  assert.equal(element('disease-overview').hidden,false);
  assert.equal(element('reference-section').hidden,true);
  assert.doesNotMatch(element('overview-summary').textContent,/合成/);
  assert.match(element('overview-summary').textContent,/100/);
  assert.match(element('overview-summary').textContent,/已公开分析组/);
  run("groupFilter='comorbidity';renderNav()");
  assert.equal(run('navigationGroups().length'),2);
  assert.match(element('group-nav').innerHTML,/ra__sjd/);
  assert.doesNotMatch(element('group-nav').innerHTML,/data-group="ra"/);
  assert.match(element('version').textContent,/test-renderer/);
});

test('comparison count joins are unique, context exact and presentation only',()=>{
  const {element,run}=setup();
  run("globalThis.before=JSON.stringify(data);renderComparisons()");
  assert.equal(run('comparisonDisplayRows()[0].combination_repeat_patients'),'20');
  assert.equal(run('comparisonDisplayRows()[0].single_repeat_patients'),'40');
  assert.equal(run('comparisonDisplayRows()[0].single_patients_with_change'),'10');
  assert.equal(run('comparisonDisplayRows()[0].single_counts_availability'),'unique_change_row');
  assert.equal(run('JSON.stringify(data)===before'),true);
  assert.match(element('comparison-combo').innerHTML,/10 \/ 20/);
  run("data.changes.push({...data.changes[0]});renderComparisons()");
  assert.equal(run("comparisonDisplayRows().find(row=>row.change_type==='addition').single_repeat_patients"),'');
  assert.equal(run("comparisonDisplayRows().find(row=>row.change_type==='addition').single_counts_availability"),'not_disclosed_or_ambiguous');
  run("data.changes=data.changes.filter(row=>row.group!=='ra');data.changes.push({group:'ra',stratum_type:'sex',stratum:'female',item_name:'Herb A',change_type:'addition',patients_with_change:'99',repeat_patients:'100'});renderComparisons()");
  assert.equal(run('comparisonDisplayRows()[0].single_repeat_patients'),'');
  assert.doesNotMatch(element('comparison-combo').innerHTML,/99 \/ 100/);
});

test('direction, signed CSV and counts match the same displayed rows',async()=>{
  const {element,run,downloads}=setup();
  element('comparison-direction').listeners.change({target:{value:'removal'}});
  assert.equal(run('comparisonDisplayRows().length'),1);
  assert.equal(run('comparisonExportRows()[0].mean_transition_fraction_difference'),-.1);
  assert.equal(run('comparisonExportRows()[0].single_repeat_patients'),40);
  assert.match(element('comparison-count').textContent,/1 \/ 1/);
  element('export-comparison').listeners.click();
  assert.match(await downloads[0].blob.text(),/"-0.1"/);
  assert.doesNotMatch(await downloads[0].blob.text(),/"'-0.1"/);
  run("selectDiseaseGroup('ra__as')");
  assert.equal(element('comparison-empty').hidden,false);
  assert.equal(element('export-comparison').disabled,true);
  assert.equal(run('comparisonDisplayRows().length'),0);
});

test('native drug buttons focus cross-group data independently of list and annual filters',()=>{
  const {element,events,run}=setup();
  assert.match(element('item-list').innerHTML,/<button type="button" class="drug-focus" data-focus-drug="Herb A"/);
  assert.match(element('addition-list').innerHTML,/data-focus-drug="Herb A"/);
  assert.match(element('combo-list').innerHTML,/data-focus-drug="Herb B"/);
  assert.match(element('comparison-combo').innerHTML,/data-focus-drug="Herb A"/);
  run("query='unrelated';annualItem='independent';");
  events.get('document-click')({target:{closest:selector=>selector.includes('focus-drug')?{dataset:{focusDrug:'Herb A'}}:null}});
  assert.equal(run('researchItem'),'Herb A');
  assert.equal(run('query'),'unrelated');
  assert.equal(run('annualItem'),'independent');
  assert.equal(element('item-research').focused,true);
  assert.match(element('item-comparison').innerHTML,/20 \/ 40/);
  assert.match(element('item-comparison').innerHTML,/未公开 \/ 未估计/);
  assert.equal(run("itemExportRows().find(row=>row.group==='sjd'&&row.metric==='addition').numerator"),'');
  assert.equal(element('item-to-annual').disabled,false);
  assert.equal(element('item-to-network').disabled,false);
  element('clear-drug-focus').listeners.click();
  assert.equal(run('researchItem'),'');
  assert.equal(run('query'),'unrelated');
  assert.equal(element('export-item').disabled,true);
  run('render()');assert.equal(run('researchItem'),'');
});

test('history restores source, group, stratum and drug without patient reference values',()=>{
  const {element,history,run}=setup();
  run("focusDrug('Herb A',false);selectStratum('sex','female');selectDiseaseGroup('sjd')");
  assert.equal(run('selected'),'sjd');
  history.back();
  assert.equal(run('selected'),'ra');
  assert.equal(run('stratumType'),'sex');
  assert.equal(run('stratum'),'female');
  assert.equal(run('researchItem'),'Herb A');
  element('reference-age').value='52';element('reference-sex').value='female';
  assert.doesNotMatch(run('JSON.stringify(captureViewState())'),/reference|52/);
  run("selectDiseaseGroup('ra__sjd');switchAnalysisSource('supplement')");
  assert.equal(run('researchItem'),'');
  assert.equal(run('selected'),'as');
  assert.equal(element('reference-age').value,'');
  history.back();
  assert.equal(run('activeSource'),'primary');
  assert.equal(run('selected'),'ra__sjd');
  assert.equal(run('researchItem'),'Herb A');
});

test('full reset clears dependent filters and restores folded combinations',()=>{
  const {element,run}=setup();
  run("selectDiseaseGroup('ra__sjd');focusDrug('Herb A',false);query='x';comparisonDirection='removal';comparisonKey='ra__sjd|ra';comboSize='3';groupFilter='comorbidity';limit=20;annualMetric='removal';annualItem='old';networkItem='old';");
  element('fold-combos').checked=false;element('export-status').textContent='old';
  element('reset-view').listeners.click();
  assert.equal(run('selected'),'ra');assert.equal(run('query'),'');assert.equal(run('researchItem'),'');
  assert.equal(run('comparisonDirection'),'all');assert.equal(run('comboSize'),'all');assert.equal(run('groupFilter'),'all');
  assert.equal(run('limit'),12);assert.equal(run('annualMetric'),'prevalence');
  assert.equal(element('fold-combos').checked,true);assert.equal(element('export-status').textContent,'');
  assert.equal(element('comparison-direction').value,'all');assert.equal(element('research-item').disabled,false);
});
