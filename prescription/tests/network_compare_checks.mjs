import assert from 'node:assert/strict';
import test from 'node:test';
import {setup} from './network_3d_checks.mjs';

const decode=value=>String(value).replaceAll('&quot;','"').replaceAll('&#39;',"'").replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');
function twoCohorts(payload){
  if(payload.provenance.dataset_id.includes('secondary'))return payload;
  const nodes=payload.research.nodes.filter((_,index)=>index%2===0&&index!==0).reverse().map(row=>({...row,group:'sjd_strict',patients:'200',exposed_patients:'0',prevalence:'0'}));
  const names=new Set(nodes.map(row=>row.item_name)),edges=payload.research.edges.filter(row=>names.has(row.item_1)&&names.has(row.item_2)).map(row=>({...row,group:'sjd_strict',cooccurrence_patients:'0',support:'0',cosine_similarity:'0',lift:''}));
  payload.research.cohorts.push({group:'sjd_strict',label:'Synthetic second strict cohort',patients:'200'});payload.research.nodes.push(...nodes);payload.research.edges.push(...edges);return payload;
}
const make=()=>setup({transform:twoCohorts});

test('coordinates use a sorted same-source universe and remain identical for reordered subsets',()=>{
  const {run}=make();
  assert.equal(run('(()=>{const universe=researchRows("nodes"),left=MingYiRxNetwork3D.layout(universe.filter(r=>r.group==="ra_strict"),universe),right=MingYiRxNetwork3D.layout(universe.filter(r=>r.group==="sjd_strict").reverse(),universe.slice().reverse());return right.every(p=>JSON.stringify(p)===JSON.stringify(left.find(q=>q.name===p.name)))})()'),true);
  assert.equal(run('(()=>{const a=MingYiRxNetworkCompare.exported();return a.panels[1].layout.every(p=>JSON.stringify(p)===JSON.stringify(a.coordinate_universe.find(q=>q.name===p.name)))})()'),true);
});

test('label collision policy keeps priorities while rejecting overlapping rectangles',()=>{
  const {run,click,element}=make();
  assert.equal(run('(()=>{const graph={nodes:["Z","B","A"].map(item_name=>({item_name})),edges:[]},points=new Map(graph.nodes.map(r=>[r.item_name,{name:r.item_name,x:150,y:160,scale:1}])),labels=MingYiRxNetwork3D.labelPositions(graph,points,"Z",null,300,300,"all"),boxes=[...labels.values()];return labels.has("Z")&&boxes.every((a,i)=>boxes.slice(i+1).every(b=>!(a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y)))})()'),true);
  const before=element('network3d-label-status').textContent;click('network3d-label-all');assert.equal(element('network3d-label-all').getAttribute('aria-pressed'),'true');assert.notEqual(element('network3d-label-status').textContent,before);
  assert.equal(run('captureViewState().network_3d.labels'),'all');
});

test('search locates a disclosed node outside the cap without changing source rows',()=>{
  const {run,element}=make();run('globalThis.savedRows=JSON.stringify(data)');element('network3d-search').value='Herb 71';element('network3d-search').emit('input');assert.match(element('network3d-search-results').innerHTML,/Herb 71/);
  assert.equal(run('MingYiRxNetwork3D.locate("Herb 71")'),true);assert.equal(run('MingYiRxNetwork.getSnapshot().selected'),'Herb 71');assert.equal(run('MingYiRxNetwork.getSnapshot().graph.nodes.some(r=>r.item_name==="Herb 71")'),true);assert.equal(run('JSON.stringify(data)===savedRows'),true);
  assert.equal(run('MingYiRxNetwork.getSnapshot().mode'),'all');
  assert.equal(run('(()=>{const p=MingYiRxNetwork3D.layout(strictRows("nodes"),researchRows("nodes")).find(row=>row.name==="Herb 71"),q=MingYiRxNetwork3D.project(p,MingYiRxNetwork3D.getCamera());return q.z < -214&&Math.abs(q.x-480)<.01&&Math.abs(q.y-320)<.01})()'),true);
  assert.equal(run('MingYiRxNetwork3D.locate("Undisclosed")'),false);assert.match(element('network3d-detail').innerHTML,/Herb 71/);
});

test('comparison keeps zero, missing rows and each original denominator separate',()=>{
  const {element,change,run}=make();change('network-compare-drug','Herb 02');
  assert.match(element('network-compare-right-value').innerHTML,/0 \/ 200/);assert.match(element('network-compare-right-value').innerHTML,/0\.0%/);assert.match(element('network-compare-left-value').innerHTML,/68 \/ 100/);
  change('network-compare-drug','Herb 00');assert.match(element('network-compare-right-value').innerHTML,/\u672a\u516c\u5f00/);assert.doesNotMatch(element('network-compare-right-value').innerHTML,/0 \/ 200/);
  assert.equal(run('MingYiRxNetworkCompare.exported().panels[0].cohort.patients'),'30');assert.equal(run('MingYiRxNetworkCompare.exported().panels[1].cohort.patients'),'200');
});

test('camera is linked across both panels and explorer with no mutations',()=>{
  const {element,run}=make();run('globalThis.savedRows=JSON.stringify(data)');
  element('network-compare-left-scene').emit('keydown',{key:'ArrowRight'});const left=element('network-compare-left-scene').getAttribute('data-camera'),right=element('network-compare-right-scene').getAttribute('data-camera');assert.equal(left,right);assert.equal(left,element('network3d-scene').getAttribute('data-camera'));
  const a=element('network-compare-left-scene').svg.nodes.find(n=>n.getAttribute('data-compare-node')==='Herb 02'),b=element('network-compare-right-scene').svg.nodes.find(n=>n.getAttribute('data-compare-node')==='Herb 02');assert.equal(a.getAttribute('transform'),b.getAttribute('transform'));assert.equal(run('JSON.stringify(data)===savedRows'),true);
});

test('source isolation, distinct cohorts, history restoration and reset are coherent',()=>{
  const {element,change,run}=make();change('network-compare-left','sjd_strict');assert.equal(element('network-compare-right').value,'ra_strict');change('network-compare-drug','Herb 02');run('globalThis.savedCompare=captureViewState()');
  change('analysis-source','supplement');assert.equal(element('network-compare-content').hidden,true);assert.equal(element('network-compare-export').disabled,true);assert.doesNotMatch(element('network-compare-detail').innerHTML,/Herb/);
  run('applyViewState(savedCompare)');assert.equal(element('network-compare-content').hidden,false);assert.equal(element('network-compare-left').value,'sjd_strict');assert.equal(element('network-compare-drug').value,'Herb 02');
  run('resetDashboardView()');assert.equal(element('network-compare-left').value,'ra_strict');assert.equal(element('network3d-label-focus').getAttribute('aria-pressed'),'true');
});

test('comparison JSON contains both scopes, xyz and original rows without pooling',async()=>{
  const {click,downloads,run}=make();run('globalThis.savedRows=JSON.stringify(data)');click('network-compare-export');const value=JSON.parse(await downloads.at(-1).blob.text());
  assert.equal(value.schema_version,'mingyirx-fixed-frame-v1');assert.equal(value.panels.length,2);assert.equal(value.panels[0].disclosed_nodes.length,72);assert.equal(value.panels[1].disclosed_nodes.length,35);assert.equal(value.coordinate_universe.length,72);assert.ok(value.coordinate_universe.some(p=>p.z!==0));assert.equal(value.panels[1].disclosed_nodes[0].patients,'200');assert.equal(run('JSON.stringify(data)===savedRows'),true);assert.equal(value.panels[1].disclosed_edges[0].lift,'');
});

test('overlapping pointer targets do not alternate without pointer movement',()=>{
  const {element,pointer}=make(),scene=element('network3d-scene'),nodes=scene.svg.nodes;pointer('pointermove',nodes[0],100,100);const first=element('network3d-tooltip').innerHTML;pointer('pointermove',nodes[1],100,100);assert.equal(element('network3d-tooltip').innerHTML,first);pointer('pointermove',nodes[1],101,100);assert.notEqual(element('network3d-tooltip').innerHTML,first);
});

test('one-cohort and empty-source states do not permit fabricated comparisons',()=>{
  const one=setup();assert.equal(one.element('network-compare-content').hidden,true);one.click('network-compare-export');assert.equal(one.downloads.length,0);
  const none=setup({transform:payload=>{payload.research.nodes=[];payload.research.edges=[];return payload}});assert.equal(none.element('network-compare-content').hidden,true);assert.match(none.element('network-compare-unavailable').innerHTML,/0/);
});

test('selection preserves comparison node focus and subsequent keyboard camera control',()=>{
  const {element}=make(),scene=element('network-compare-left-scene'),node=scene.svg.nodes.find(item=>item.getAttribute('data-compare-node')==='Herb 02');
  node.focus();scene.emit('focusin',{target:node});scene.emit('keydown',{target:node,key:'Enter'});
  const restored=scene.svg.nodes.find(item=>item.getAttribute('data-compare-node')==='Herb 02');assert.equal(restored.focused,true);const before=scene.getAttribute('data-camera');scene.emit('keydown',{target:restored,key:'ArrowRight'});assert.notEqual(scene.getAttribute('data-camera'),before);assert.equal(restored.focused,true);
});

test('explicit unavailable cohort denominator is preserved instead of replaced by node counts',()=>{
  const {element,run}=setup({transform:payload=>{twoCohorts(payload);for(const cohort of payload.research.cohorts)cohort.patients=null;return payload}});
  assert.match(element('network-compare-left-scope').textContent,/\u672a\u516c\u5f00/);assert.match(element('network-compare-right-scope').textContent,/\u672a\u516c\u5f00/);assert.doesNotMatch(element('network-compare-right-scope').textContent,/200/);assert.equal(run('MingYiRxNetworkCompare.exported().panels[1].cohort.patients'),null);
});

test('comparison pointer drag and touch select share camera and exact-value edge details',()=>{
  const {element}=make(),scene=element('network-compare-right-scene'),target=scene.svg.nodes[0],event={target,button:0,pointerId:4,pointerType:'touch',clientX:100,clientY:100};
  scene.emit('pointerdown',event);scene.emit('pointermove',{...event,clientX:155,clientY:130});scene.emit('pointerup',{...event,clientX:155,clientY:130});assert.equal(scene.captured.size,0);assert.equal(scene.getAttribute('data-camera'),element('network-compare-left-scene').getAttribute('data-camera'));
  const next=scene.svg.nodes[0],name=next.getAttribute('data-compare-node');scene.emit('pointerdown',{...event,target:next});scene.emit('pointerup',{...event,target:next});assert.equal(element('network-compare-drug').value,name);
  scene.emit('pointermove',{target:scene.svg.edges[0],pointerType:'mouse'});assert.match(element('network-compare-detail').innerHTML,/Lift/);assert.match(element('network-compare-detail').innerHTML,/\u672a\u516c\u5f00/);
});

test('hostile labels stay escaped in both comparison panels and table',()=>{
  const hostile='<img src=x onerror="attack">',fixture=setup({transform:payload=>{twoCohorts(payload);const old=payload.research.nodes[0].item_name;for(const row of payload.research.nodes)if(row.item_name===old)row.item_name=hostile;for(const row of payload.research.edges){if(row.item_1===old)row.item_1=hostile;if(row.item_2===old)row.item_2=hostile}return payload}});
  assert.doesNotMatch(fixture.element('network-compare-left-scene').innerHTML,/<img /);assert.match(fixture.element('network-compare-nodes-table').innerHTML,/&lt;img/);assert.doesNotMatch(fixture.element('network-compare-detail').innerHTML,/<img /);
});

test('reset then actual history back restores camera, label mode, cohort pair and selection',()=>{
  const {element,change,click,run,history}=make();change('network-compare-left','sjd_strict');change('network-compare-drug','Herb 02');click('network3d-label-all');element('network-compare-left-scene').emit('keydown',{key:'ArrowRight'});
  const before=JSON.parse(run('JSON.stringify(captureViewState())'));run('resetDashboardView()');assert.equal(element('network-compare-left').value,'ra_strict');history.back();const after=JSON.parse(run('JSON.stringify(captureViewState())'));
  assert.deepEqual(after.network_comparison,before.network_comparison);assert.deepEqual(after.network_3d,before.network_3d);assert.deepEqual(after.network_view,before.network_view);assert.equal(element('network-compare-left').value,'sjd_strict');assert.equal(element('network-compare-drug').value,'Herb 02');
});

test('locating an isolated node preserves all-mode and keeps explicit neighborhood mode',()=>{
  const {run,change}=setup({transform:payload=>{twoCohorts(payload);payload.research.edges=payload.research.edges.filter(row=>row.item_1!=='Herb 71'&&row.item_2!=='Herb 71');return payload}});
  run('MingYiRxNetwork3D.locate("Herb 71")');assert.equal(run('MingYiRxNetwork.getSnapshot().mode'),'all');assert.ok(run('MingYiRxNetwork.getSnapshot().graph.nodes.length')>1);
  change('network-view-mode','neighborhood');run('MingYiRxNetwork3D.locate("Herb 71")');assert.equal(run('MingYiRxNetwork.getSnapshot().mode'),'neighborhood');assert.equal(run('MingYiRxNetwork.getSnapshot().graph.nodes.length'),1);assert.equal(run('MingYiRxNetwork.getSnapshot().graph.edges.length'),0);
});

test('comparison outside-cap selection is one history transaction and back restores both selectors',()=>{
  const {run,change,history,element}=make();const before=JSON.parse(run('JSON.stringify(captureViewState())'));
  change('network-compare-drug','Herb 70');assert.equal(element('network-compare-drug').value,'Herb 70');assert.equal(run('MingYiRxNetwork.getSnapshot().mode'),'all');history.back();
  const after=JSON.parse(run('JSON.stringify(captureViewState())'));assert.deepEqual(after.network_comparison,before.network_comparison);assert.equal(run('MingYiRxNetwork.getSnapshot().selected'),before.network_view.selected);assert.equal(after.sequence,before.sequence);
});

test('cohort subset swaps rebuild atomically when removing a focused node emits focusout',()=>{
  const {element,change}=setup({transform:twoCohorts,blurOnSceneReplace:true}),scene=element('network-compare-left-scene'),node=scene.svg.nodes.find(item=>item.getAttribute('data-compare-node')==='Herb 02');
  node.focus();scene.emit('focusin',{target:node});
  assert.doesNotThrow(()=>change('network-compare-left','sjd_strict'));
  assert.equal(element('network-compare-left-scene').svg.nodes.length,35);assert.equal(element('network-compare-right-scene').svg.nodes.length,60);
  const restored=element('network-compare-left-scene').svg.nodes.find(item=>item.getAttribute('data-compare-node')==='Herb 02');assert.equal(restored.focused,true);
  assert.doesNotThrow(()=>element('network-compare-left-scene').emit('keydown',{target:restored,key:'ArrowRight'}));
  assert.equal(element('network-compare-left-scene').getAttribute('data-camera'),element('network-compare-right-scene').getAttribute('data-camera'));
  change('network-compare-left','ra_strict');const absent=scene.svg.nodes.find(item=>item.getAttribute('data-compare-node')==='Herb 01');absent.focus();scene.emit('focusin',{target:absent});assert.doesNotThrow(()=>change('network-compare-left','sjd_strict'));assert.equal(scene.focused,true);
});
