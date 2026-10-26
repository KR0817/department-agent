import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const html=fs.readFileSync(process.argv[2],'utf8');
const decode=value=>String(value).replaceAll('&quot;','"').replaceAll('&#39;',"'").replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');
function setup(reducedMotion=false,viewportWidth=1440,transformPayload=payload=>payload){
  const elements=new Map(),events=new Map(),downloads=[],stack=[],frames=new Map();let cursor=-1,frameId=0,cancelled=0;
  class Element{
    constructor(id='',attrs={}){this.id=id;this.attrs=attrs;this.listeners={};this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.checked=id==='fold-combos';this.dataset={};this.content='';this.style={};this.classList={add(){},remove(){}};this.captured=new Set()}
    set innerHTML(value){this.content=String(value);this.svg=null;if(this.id==='network-graph'&&this.content.includes('<svg'))this.svg=new Svg(this.content)}
    get innerHTML(){return this.content}
    get options(){return [...this.content.matchAll(/<option[^>]*value="([^"]*)"[^>]*>(.*?)<\/option>/g)].map(m=>({value:m[1],textContent:m[2]}))}
    addEventListener(type,fn,options={}){this.listeners[type]=fn;options.signal?.addEventListener('abort',()=>{delete this.listeners[type]},{once:true})}
    setAttribute(name,value){this.attrs[name]=String(value)}
    getAttribute(name){return this.attrs[name]??null}
    removeAttribute(name){delete this.attrs[name]}
    getBoundingClientRect(){const card=this.id==='network-hover-card',width=card?Number.parseFloat(this.style.width)||300:this.clientWidth||900,height=card?250:viewportWidth<=600?360:600;return {left:0,top:0,width,height,right:width,bottom:height}}
    querySelector(selector){if(selector==='svg')return this.svg;if(selector==='.network-node-shell')return this.circle;if(selector==='[data-network-hover-halo]')return this.halo;return null}
    querySelectorAll(){return []}
    closest(selector){if(selector==='[data-network-node]'&&this.attrs['data-network-node'])return this;if(selector==='[data-network-edge-hit]'&&this.attrs['data-network-edge-hit']!==undefined)return this;if(selector==='[data-network-select]'&&this.attrs['data-network-select'])return this;if(selector==='#'+this.id)return this;return null}
    focus(){this.focused=true}
    scrollIntoView(){this.scrolled=true}
    setPointerCapture(id){this.captured.add(id)}
    hasPointerCapture(id){return this.captured.has(id)}
    releasePointerCapture(id){this.captured.delete(id)}
  }
  class Svg extends Element{
    constructor(markup){super();this.plane=new Element();this.nodes=[...markup.matchAll(/<g class="network-node" data-network-node="([^"]+)"/g)].map(match=>{const node=new Element('',{'data-network-node':decode(match[1])});node.circle=new Element();node.halo=new Element();return node});this.edges=[...markup.matchAll(/<line data-network-edge="(\d+)"/g)].map(match=>new Element('',{'data-network-edge':match[1]}));this.hits=[...markup.matchAll(/<line data-network-edge-hit="(\d+)"/g)].map(match=>new Element('',{'data-network-edge-hit':match[1]}))}
    querySelector(selector){return selector==='[data-network-plane]'?this.plane:null}
    querySelectorAll(selector){return selector==='[data-network-node]'?this.nodes:selector==='[data-network-edge]'?this.edges:selector==='[data-network-edge-hit]'?this.hits:[]}
    createSVGPoint(){return {x:0,y:0,matrixTransform(){return {x:this.x,y:this.y}}}}
    getScreenCTM(){return {inverse(){return {}}}}
  }
  const element=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id)};
  for(const id of ['dashboard-data','supplement-data'])element(id).textContent=JSON.stringify(transformPayload(JSON.parse(html.match(new RegExp('<script id="'+id+'" type="application/json">(.*?)</script>','s'))[1])));
  element('network-graph').clientWidth=viewportWidth<=600?viewportWidth-48:900;
  element('analysis-source').innerHTML='<option value="primary">Primary</option><option value="supplement">Supplement</option>';
  const annual=['prevalence','addition','removal'].map(annual=>Object.assign(element('annual-'+annual),{dataset:{annual}}));
  const sizes=['all','2','3'].map(size=>Object.assign(element('size-'+size),{dataset:{size}}));
  const location={href:'http://127.0.0.1:18879/index.html',search:'',hash:''};
  const updateUrl=url=>{location.href=String(url);location.search=new URL(url).search;location.hash=new URL(url).hash};
  const clone=value=>JSON.parse(JSON.stringify(value));
  const history={replaceState(state,_title,url){if(cursor<0){cursor=0;stack.push(clone(state))}else stack[cursor]=clone(state);updateUrl(url)},pushState(state,_title,url){stack.splice(++cursor);stack.push(clone(state));updateUrl(url)},back(){if(cursor>0){cursor--;events.get('popstate')({state:stack[cursor]})}},get state(){return stack[cursor]}};
  class TestURL extends URL{static createObjectURL(blob){downloads.push({blob});return 'blob:fixture'}static revokeObjectURL(){}}
  const document={getElementById:element,title:'',body:{appendChild(){}},addEventListener(type,fn){events.set('document-'+type,fn)},createElement:()=>({click(){downloads.at(-1).name=this.download},remove(){}}),querySelectorAll:selector=>({'.annual-btn':annual,'.filter-btn[data-size]':sizes}[selector]||[])};
  const media={matches:reducedMotion,addEventListener(type,fn){events.set('media-'+type,fn)}};
  const pointerMedia={matches:viewportWidth>600,addEventListener(type,fn){events.set('pointer-media-'+type,fn)}};
  const context=vm.createContext({document,location,history,URL:TestURL,URLSearchParams,Blob,AbortController,innerWidth:viewportWidth,innerHeight:1000,matchMedia:query=>query.includes('reduced-motion')?media:pointerMedia,requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId},cancelAnimationFrame:id=>{cancelled++;frames.delete(id)},setTimeout:fn=>fn(),addEventListener:(type,fn)=>events.set(type,fn)});
  const run=code=>vm.runInContext(code,context);
  for(const block of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)){if(!block[1].includes('application/json'))run(block[2])}
  const click=id=>element(id).listeners.click({target:element(id)});
  const change=(id,value)=>element(id).listeners.change({target:{value}});
  const pointer=(type,target,x,y,pointerType='mouse')=>element('network-graph').svg.listeners[type]({type,target,button:0,pointerId:1,clientX:x,clientY:y,pointerType,preventDefault(){}});
  return {element,run,change,click,pointer,frames,media,pointerMedia,events,downloads,history,document,Element,cancelled:()=>cancelled};
}

test('projection caps existing rows, excludes unavailable endpoints and never mutates inputs',()=>{
  const {run}=setup();
  run('globalThis.before=JSON.stringify(data);globalThis.projected=MingYiRxNetwork.project(strictRows("nodes"),strictRows("edges"),networkItem,"all",120)');
  assert.equal(run('projected.nodes.length'),60);assert.equal(run('projected.edges.length'),120);
  assert.equal(run('projected.scopeNodes.length'),72);assert.equal(run('projected.scopeEdges.length'),278);
  assert.equal(run('JSON.stringify(data)===before'),true);
  assert.equal(run('projected.edges.every(row=>research.edges.includes(row))'),true);
  assert.equal(run('MingYiRxNetwork.project(strictRows("nodes"),[{item_1:"unpublished",item_2:networkItem}],networkItem).edges.length'),0);
  assert.equal(run('MingYiRxNetwork.project(strictRows("nodes"),[{item_1:"unpublished",item_2:networkItem}],networkItem).unresolvedEdges'),1);
  run('globalThis.neighborhood=MingYiRxNetwork.project(strictRows("nodes"),strictRows("edges"),"Herb 30","neighborhood",40)');
  assert.equal(run('neighborhood.edges.every(row=>row.item_1==="Herb 30"||row.item_2==="Herb 30")'),true);
  assert.equal(run('JSON.stringify(data)===before'),true);
});

test('whole network, exact edge table and inspector use distinct declared scopes',()=>{
  const {element,change,click}=setup();
  assert.equal(element('network-graph').svg.nodes.length,60);assert.equal(element('network-graph').svg.edges.length,80);
  assert.match(element('network-status').textContent,/60 \/ 72.*80 \/ 278/);
  assert.match(element('network-table-summary').textContent,/278/);
  assert.match(element('network-inspector').innerHTML,/Herb 00/);
  change('network-item','Herb 30');assert.equal(element('network-view-mode').value,'neighborhood');
  assert.equal(element('network-graph').svg.nodes.length,9);assert.equal(element('network-graph').svg.edges.length,8);
  assert.match(element('network-inspector').innerHTML,/Herb 30/);
  change('network-view-mode','all');change('network-edge-limit','120');assert.equal(element('network-graph').svg.edges.length,120);
  click('network-zoom-in');assert.notEqual(element('network-zoom-value').textContent,'100%');
});

test('pointer drag and background pan change presentation only; keyboard selects and moves',()=>{
  const {element,pointer,run,click}=setup();run('globalThis.before=JSON.stringify(data)');
  click('network-motion');const svg=element('network-graph').svg,node=svg.nodes[0],initial=node.attrs.transform;
  pointer('pointerdown',node,480,320);pointer('pointermove',node,560,360);pointer('pointerup',node,560,360);
  assert.notEqual(node.attrs.transform,initial);assert.equal(svg.captured.size,0);
  const pan=svg.plane.attrs.transform;pointer('pointerdown',svg,400,250);pointer('pointermove',svg,450,300);pointer('pointerup',svg,450,300);assert.notEqual(svg.plane.attrs.transform,pan);
  const beforeKey=node.attrs.transform;svg.listeners.keydown({target:node,key:'ArrowRight',preventDefault(){}});assert.notEqual(node.attrs.transform,beforeKey);
  svg.listeners.keydown({target:node,key:'PageDown',preventDefault(){}});assert.equal(svg.nodes[1].focused,true);assert.equal(svg.nodes[1].attrs['aria-pressed'],'true');
  assert.equal(run('JSON.stringify(data)===before'),true);
});

test('inspector actions are explicit and wheel zoom leaves ordinary scrolling alone',()=>{
  const {element,run,Element,click}=setup(),svg=element('network-graph').svg,node=svg.nodes[3];
  svg.listeners.click({target:node});assert.equal(run('networkItem'),'Herb 00');
  assert.match(element('network-inspector').innerHTML,/Herb 03/);
  element('network-inspector').listeners.click({target:new Element('network-center-selected')});
  assert.equal(run('networkItem'),'Herb 03');assert.equal(element('network-view-mode').value,'neighborhood');
  element('network-inspector').listeners.click({target:new Element('network-open-drug')});
  assert.equal(run('researchItem'),'Herb 03');assert.equal(element('item-research').focused,true);
  const current=element('network-graph').svg,prior=current.plane.attrs.transform;let prevented=false;
  current.listeners.wheel({ctrlKey:false,metaKey:false,deltaY:-1,preventDefault(){prevented=true}});
  assert.equal(prevented,false);assert.equal(current.plane.attrs.transform,prior);
  current.listeners.wheel({ctrlKey:true,metaKey:false,deltaY:-1,clientX:100,clientY:100,preventDefault(){prevented=true}});
  assert.equal(prevented,true);assert.notEqual(current.plane.attrs.transform,prior);
  click('network-fit');assert.match(element('network-status').textContent,/保留/);
});

test('motion is bounded, reduced-motion starts static, rerender cancels old frames and listeners',()=>{
  const fixture=setup(),{element,frames,change}=fixture;
  assert.equal(frames.size,1);assert.equal(element('network-graph').attrs['data-motion-state'],'running');
  let count=0;while(frames.size&&count<200){const [id,callback]=frames.entries().next().value;frames.delete(id);callback();count++}
  assert.equal(count,140);assert.equal(frames.size,0);assert.equal(element('network-graph').attrs['data-motion-state'],'settled');
  const finalSvg=element('network-graph').svg,[panX,panY,scale]=finalSvg.plane.attrs.transform.match(/[-\d.]+/g).map(Number);
  for(const node of finalSvg.nodes){const [x,y]=node.attrs.transform.match(/[-\d.]+/g).map(Number);assert.ok(panX+(x-33)*scale>=0&&panX+(x+33)*scale<=960);assert.ok(panY+(y-33)*scale>=0&&panY+(y+33)*scale<=640)}
  const positions=finalSvg.nodes.map(node=>node.attrs.transform.match(/[-\d.]+/g).map(Number));
  const minimumDistance=Math.min(...positions.flatMap((point,index)=>positions.slice(index+1).map(other=>Math.hypot(point[0]-other[0],point[1]-other[1]))));
  assert.ok(minimumDistance>=66,`Settled node circles overlap at distance ${minimumDistance}`);
  fixture.click('network-motion');const oldSvg=element('network-graph').svg;change('network-view-mode','neighborhood');
  assert.ok(fixture.cancelled()>0);assert.equal(Object.keys(oldSvg.listeners).length,0);
  const reduced=setup(true);assert.equal(reduced.frames.size,0);assert.equal(reduced.element('network-motion').disabled,true);assert.equal(reduced.element('network-graph').attrs['data-motion-state'],'reduced');
  const reducedPositions=reduced.element('network-graph').svg.nodes.map(node=>node.attrs.transform.match(/[-\d.]+/g).map(Number));
  const reducedDistance=Math.min(...reducedPositions.flatMap((point,index)=>reducedPositions.slice(index+1).map(other=>Math.hypot(point[0]-other[0],point[1]-other[1]))));
  assert.ok(reducedDistance>=66,`Static reduced-motion nodes overlap at distance ${reducedDistance}`);
  reduced.click('network-reset');assert.equal(reduced.frames.size,0);
});

test('fit recovers nodes dragged to both allowed extremes without a lower zoom jump',()=>{
  const {element,pointer,click}=setup(),svg=element('network-graph').svg;
  pointer('pointerdown',svg.nodes[0],0,0);pointer('pointermove',svg.nodes[0],-100000,-100000);pointer('pointerup',svg.nodes[0],-100000,-100000);
  pointer('pointerdown',svg.nodes[1],0,0);pointer('pointermove',svg.nodes[1],100000,100000);pointer('pointerup',svg.nodes[1],100000,100000);
  click('network-fit');const [panX,panY,scale]=svg.plane.attrs.transform.match(/[-\d.]+/g).map(Number);
  assert.ok(scale<.45);
  for(const node of svg.nodes){const [x,y]=node.attrs.transform.match(/[-\d.]+/g).map(Number);assert.ok(panX+(x-33)*scale>=0&&panX+(x+33)*scale<=960);assert.ok(panY+(y-33)*scale>=0&&panY+(y+33)*scale<=640)}
  click('network-zoom-out');const zoomAfter=Number(element('network-zoom-value').textContent.replace('%',''))/100;assert.ok(zoomAfter<scale);
});

test('phone canvas starts at readable native scale and exports its actual viewport',async()=>{
  const {element,click,downloads,frames}=setup(false,390);
  assert.match(element('network-graph').innerHTML,/viewBox="0 0 342 360"/);assert.equal(element('network-zoom-value').textContent,'100%');assert.equal(element('network-camera-label').textContent,'聚焦视野');
  assert.match(element('network-status').textContent,/手机默认放大至可读视野/);
  click('export-network-svg');const svg=await downloads[0].blob.text(),metadata=JSON.parse(decode(svg.match(/<metadata>(.*?)<\/metadata>/s)[1]));
  assert.equal(metadata.figure.viewport.width,342);assert.equal(metadata.figure.viewport.height,360);assert.equal(metadata.figure.viewport.zoom,1);assert.equal(metadata.figure.viewport.compact,true);
  click('network-fit');assert.equal(element('network-camera-label').textContent,'全图视野');assert.ok(Number(element('network-zoom-value').textContent.replace('%',''))<100);assert.equal(frames.size,0);
  click('network-reset');assert.equal(element('network-camera-label').textContent,'聚焦视野');assert.equal(element('network-zoom-value').textContent,'100%');
});

test('source, cohort, history and reset preserve aggregate state boundaries',()=>{
  const {element,change,run,history}=setup();
  change('network-view-mode','neighborhood');change('network-edge-limit','40');
  assert.equal(run('captureViewState().network_view.edgeLimit'),40);
  run('globalThis.saved=captureViewState()');
  change('analysis-source','supplement');assert.match(element('network-inspector').innerHTML,/Secondary 00/);assert.doesNotMatch(element('network-inspector').innerHTML,/Herb 00/);
  assert.equal(element('network-view-mode').value,'all');assert.equal(element('network-edge-limit').value,'80');
  run('applyViewState(saved)');assert.equal(element('network-view-mode').value,'neighborhood');assert.equal(element('network-edge-limit').value,'40');assert.match(element('network-inspector').innerHTML,/Herb 00/);
  change('network-item','Herb 30');change('network-view-mode','all');change('network-edge-limit','120');run('globalThis.fullSaved=captureViewState()');
  change('analysis-source','supplement');run('applyViewState(fullSaved)');
  assert.equal(run('networkItem'),'Herb 30');assert.equal(element('network-view-mode').value,'all');assert.equal(element('network-edge-limit').value,'120');
  change('strict-group','empty_strict');assert.equal(element('export-network-svg').disabled,true);assert.equal(element('network-motion').disabled,true);assert.equal(element('network-graph').svg,null);
  run('resetDashboardView()');assert.equal(element('network-view-mode').value,'all');assert.equal(element('network-edge-limit').value,'80');assert.equal(element('export-network-svg').disabled,false);
  assert.equal(history.state.mingyirx_view.network_view.mode,'all');
});

test('SVG download records actual visible edges, scope, layout, pan and zoom',async()=>{
  const {element,click,downloads,run}=setup();run('globalThis.before=JSON.stringify(data)');const initialScale=Number(element('network-graph').svg.plane.attrs.transform.match(/scale\(([^)]+)\)/)[1]);click('network-zoom-in');click('export-network-svg');
  assert.equal(downloads.length,1);assert.match(downloads[0].name,/network-.*-all-/);
  const svg=await downloads[0].blob.text(),metadata=JSON.parse(decode(svg.match(/<metadata>(.*?)<\/metadata>/s)[1]));
  assert.equal(metadata.figure.mode,'all');assert.equal(metadata.figure.displayed_nodes.length,60);assert.equal(metadata.figure.displayed_edges.length,80);assert.equal(metadata.figure.available_edges,278);
  assert.equal(metadata.figure.layout.length,60);assert.ok(Math.abs(metadata.figure.viewport.zoom-initialScale*1.2)<.0001);assert.match(svg,/network-plot-clip/);assert.match(svg,/共现不表示配伍功效/);
  assert.equal(run('JSON.stringify(data)===before'),true);
  run('strictGroup="empty_strict";renderStrictResearch()');click('export-network-svg');assert.equal(downloads.length,1);assert.match(element('network-export-status').textContent,/没有/);
});

const detailValues=element=>[...element.innerHTML.matchAll(/<dd>(.*?)<\/dd>/g)].map(match=>decode(match[1]));
const frameStep=frames=>{const [id,callback]=frames.entries().next().value;frames.delete(id);callback()};

test('node hover reads exact rows, holds remaining settling, and leaves selection/history/positions untouched',()=>{
  const {element,run,history,pointer,frames}=setup();
  for(let index=0;index<7;index++)frameStep(frames);
  const svg=element('network-graph').svg,node=svg.nodes[3],positions=svg.nodes.map(item=>item.attrs.transform),snapshot=JSON.stringify(history.state),selected=element('network-inspector').innerHTML;
  run('globalThis.before=JSON.stringify(data)');
  pointer('pointermove',node,320,250);
  assert.equal(element('network-hover-card').hidden,false);
  assert.deepEqual(detailValues(element('network-hover-card')),JSON.parse(run('JSON.stringify([metricText(research.nodes[3].exposed_patients),metricText(research.nodes[3].patients),metricText(research.nodes[3].prevalence,"percent"),String(strictRows("edges").filter(edge=>edge.item_1==="Herb 03"||edge.item_2==="Herb 03").length)])')));
  assert.ok(element('network-hover-card').innerHTML.includes(element('network-context').textContent));
  assert.equal(frames.size,0);assert.equal(element('network-graph').attrs['data-motion-state'],'reading');assert.equal(element('network-graph').attrs['data-hover-motion'],'running');
  assert.equal(node.attrs['data-network-hover'],'active');assert.equal(node.halo.attrs.opacity,'.7');
  assert.deepEqual(svg.nodes.map(item=>item.attrs.transform),positions);assert.equal(element('network-inspector').innerHTML,selected);assert.equal(JSON.stringify(history.state),snapshot);assert.equal(run('JSON.stringify(data)===before'),true);
  pointer('pointermove',node,325,252);assert.equal(frames.size,0);assert.deepEqual(svg.nodes.map(item=>item.attrs.transform),positions);
  pointer('pointerleave',svg,960,700);assert.equal(element('network-hover-card').hidden,true);assert.equal(node.attrs['data-network-hover'],'none');assert.equal(frames.size,1);
  let remaining=0;while(frames.size&&remaining<150){frameStep(frames);remaining++}assert.equal(remaining,133);
});

test('edge hit targets expose the same four metrics as the table and highlight only its endpoints',()=>{
  const {element,pointer,run}=setup(),svg=element('network-graph').svg;
  pointer('pointermove',svg.hits[4],350,250);
  const edge=JSON.parse(run('JSON.stringify(MingYiRxNetwork.project(usageOrder(strictRows("nodes").map(row=>row.item_name)).map(name=>strictRows("nodes").find(row=>row.item_name===name)),strictRows("edges"),networkItem).edges[4])'));
  assert.deepEqual(detailValues(element('network-hover-card')),JSON.parse(run(`JSON.stringify([metricText(${JSON.stringify(edge.cooccurrence_patients)}),metricText(${JSON.stringify(edge.support)},"percent"),metricText(${JSON.stringify(edge.cosine_similarity)}),metricText(${JSON.stringify(edge.lift)})])`)));
  const highlighted=svg.nodes.filter(node=>node.attrs['data-network-hover']==='neighbor').map(node=>node.attrs['data-network-node']).sort();assert.deepEqual(highlighted,[edge.item_1,edge.item_2].sort());
  assert.equal(svg.edges[4].attrs['stroke-opacity'],'1');assert.equal(svg.edges.filter(line=>line.attrs['stroke-opacity']==='1').length,1);
  assert.ok(element('network-graph').innerHTML.indexOf('data-network-edge-hit')<element('network-graph').innerHTML.indexOf('class="network-node"'));
});

test('hover preserves zero and unavailable values, escaping names and source text',()=>{
  const {element,pointer,run}=setup();
  run(`research.nodes[0].exposed_patients="0";research.nodes[0].prevalence="0";delete research.nodes[0].patients;renderResearchNetwork()`);
  let svg=element('network-graph').svg;
  pointer('pointermove',svg.nodes[0],200,200);assert.deepEqual(detailValues(element('network-hover-card')).slice(0,3),['0','未公开 / 未估计','0.0%']);
  run(`research.edges.forEach(row=>{row.cooccurrence_patients="0";row.support="0";row.cosine_similarity="0";delete row.lift});renderResearchNetwork()`);
  svg=element('network-graph').svg;pointer('pointermove',svg.hits[0],200,200);assert.deepEqual(detailValues(element('network-hover-card')),['0','0.0%','0','未公开 / 未估计']);
  const escaped=setup(false,1440,payload=>{const special='<药 & "name">',research=payload.research,old=research.nodes[0].item_name;research.nodes[0].item_name=special;research.usage[0].item_name=special;research.edges.forEach(row=>{if(row.item_1===old)row.item_1=special;if(row.item_2===old)row.item_2=special});return payload});
  escaped.element('network-context').textContent='<source & "cohort">';svg=escaped.element('network-graph').svg;escaped.pointer('pointermove',svg.nodes[0],200,200);
  const content=escaped.element('network-hover-card').innerHTML;assert.match(content,/&lt;药 &amp; &quot;name&quot;&gt;/);assert.match(content,/&lt;source &amp; &quot;cohort&quot;&gt;/);assert.doesNotMatch(content,/<药|<source/);
});

test('hover-to-drag, zoom, Escape, rerender and source changes remove all transient feedback',()=>{
  const {element,pointer,change,click,events}=setup();let svg=element('network-graph').svg,node=svg.nodes[2];
  pointer('pointermove',node,300,250);pointer('pointerdown',node,300,250);assert.equal(element('network-hover-card').hidden,true);assert.equal(node.attrs['data-network-hover'],'none');
  pointer('pointermove',node,360,270);assert.equal(element('network-hover-card').hidden,true);pointer('pointerup',node,360,270);
  pointer('pointermove',node,360,270);assert.equal(element('network-hover-card').hidden,false);click('network-zoom-in');assert.equal(element('network-hover-card').hidden,true);
  pointer('pointermove',node,360,270);svg.listeners.keydown({target:node,key:'Escape',preventDefault(){}});assert.equal(element('network-hover-card').hidden,true);
  pointer('pointermove',node,360,270);events.get('document-keydown')({target:element('network-fit'),key:'Escape'});assert.equal(element('network-hover-card').hidden,true);assert.equal(element('network-touch-details').hidden,true);
  pointer('pointermove',node,360,270);change('network-view-mode','neighborhood');assert.equal(element('network-hover-card').hidden,true);assert.equal(Object.keys(svg.listeners).length,0);
  svg=element('network-graph').svg;pointer('pointermove',svg.nodes[0],360,270);change('analysis-source','supplement');assert.equal(element('network-hover-card').hidden,true);assert.equal(element('network-hover-card').innerHTML,'');
  svg=element('network-graph').svg;pointer('pointermove',svg.nodes[0],360,270);assert.match(element('network-hover-card').innerHTML,/Secondary/);assert.doesNotMatch(element('network-hover-card').innerHTML,/Herb/);
});

test('paused and reduced motion retain data and static emphasis without restarting layout',()=>{
  const fixture=setup(),{element,pointer,click,frames,media,events}=fixture,svg=element('network-graph').svg;
  pointer('pointermove',svg.nodes[1],250,250);click('network-motion');assert.equal(element('network-hover-card').hidden,false);assert.equal(element('network-graph').attrs['data-hover-motion'],'static');
  pointer('pointerleave',svg,950,700);assert.equal(frames.size,0);assert.equal(element('network-motion').attrs['aria-pressed'],'true');
  click('network-motion');pointer('pointermove',svg.nodes[1],250,250);media.matches=true;events.get('media-change')();assert.equal(frames.size,0);assert.equal(element('network-hover-card').hidden,false);assert.equal(element('network-graph').attrs['data-hover-motion'],'static');
  const reduced=setup(true);reduced.pointer('pointermove',reduced.element('network-graph').svg.nodes[1],250,250);assert.equal(reduced.element('network-hover-card').hidden,false);assert.equal(reduced.frames.size,0);assert.equal(reduced.element('network-graph').attrs['data-hover-motion'],'static');
});

test('keyboard focus reveals node and edge data; coarse touch taps retain compact detail without hover',()=>{
  const desktop=setup(),svg=desktop.element('network-graph').svg;
  svg.listeners.focusin({target:svg.nodes[4]});assert.match(desktop.element('network-hover-card').innerHTML,/Herb 04/);assert.equal(svg.nodes[4].attrs['aria-describedby'],'network-hover-card');
  svg.listeners.focusout({target:svg.nodes[4]});assert.equal(desktop.element('network-hover-card').hidden,true);assert.equal(svg.nodes[4].attrs['aria-describedby'],undefined);
  svg.listeners.focusin({target:svg.hits[0]});assert.equal(detailValues(desktop.element('network-hover-card')).length,4);svg.listeners.keydown({target:svg.hits[0],key:'PageDown',preventDefault(){}});assert.equal(svg.hits[1].focused,true);assert.equal(svg.hits[1].attrs.tabindex,'0');
  const phone=setup(false,390),graph=phone.element('network-graph').svg,node=graph.nodes[2];
  phone.pointer('pointermove',node,150,180,'touch');assert.equal(phone.element('network-hover-card').hidden,true);
  phone.pointer('pointerdown',node,150,180,'touch');phone.pointer('pointerup',node,150,180,'touch');assert.equal(phone.element('network-touch-details').hidden,false);assert.match(phone.element('network-touch-details').innerHTML,/Herb 02/);assert.equal(node.attrs['aria-pressed'],'true');
  phone.pointer('pointerleave',graph,150,180,'touch');assert.equal(phone.element('network-touch-details').hidden,false);
  phone.pointer('pointerdown',graph.hits[0],150,180,'touch');phone.pointer('pointerup',graph.hits[0],150,180,'touch');assert.equal(detailValues(phone.element('network-touch-details')).length,4);assert.match(phone.element('network-touch-details').innerHTML,/Lift/);
  phone.pointer('pointerdown',node,150,180,'touch');phone.pointer('pointermove',node,200,220,'touch');phone.pointer('pointerup',node,200,220,'touch');graph.listeners.click({target:node,pointerType:'touch'});assert.equal(phone.element('network-touch-details').hidden,true);
});

test('tooltip stays inside canvas edges with no pointer interception and follows a stable target',()=>{
  const {element,pointer}=setup(),svg=element('network-graph').svg,card=element('network-hover-card');
  for(const [x,y] of [[10,10],[890,10],[10,590],[890,590]]){
    pointer('pointermove',svg.nodes[2],x,y);const rect=card.getBoundingClientRect(),left=Number.parseFloat(card.style.left),top=Number.parseFloat(card.style.top);
    assert.ok(left>=12&&left+rect.width<=888);assert.ok(top>=12&&top+rect.height<=588);
  }
  assert.match(html,/#network-lab #network-hover-card\{[^}]*pointer-events:none/);
  const narrow=setup(false,390);narrow.pointerMedia.matches=true;
  const narrowGraph=narrow.element('network-graph'),narrowCard=narrow.element('network-hover-card');
  narrowGraph.getBoundingClientRect=()=>({left:34.4,top:209.6,width:341.6,height:360,right:376,bottom:569.6});
  narrowCard.getBoundingClientRect=()=>({width:300,height:201.6});
  narrow.pointer('pointermove',narrowGraph.svg.nodes[0],159,455);
  const x=Number.parseFloat(narrowCard.style.left),y=Number.parseFloat(narrowCard.style.top),anchor={x:159-34.4,y:455-209.6};
  assert.ok(x>=12&&x+300<=329.6);assert.ok(y+201.6<anchor.y-12,'A horizontally clamped card must choose the available space above the target');
});

test('sticky dock is excluded and large-text cards use the inline panel when no clear space exists',()=>{
  const {element,pointer,document,events}=setup(),svg=element('network-graph').svg,card=element('network-hover-card');
  document.querySelector=selector=>selector==='#community-dock-frame'?{getBoundingClientRect:()=>({bottom:160})}:null;
  pointer('pointermove',svg.nodes[2],350,180);assert.equal(card.hidden,false);assert.ok(Number.parseFloat(card.style.top)>=172);
  card.getBoundingClientRect=()=>({width:300,height:500});events.get('scroll')();
  assert.equal(card.hidden,true);assert.equal(element('network-touch-details').hidden,false);assert.deepEqual(detailValues(element('network-touch-details')),['68','100','68.0%','6']);
  assert.equal(svg.nodes[2].attrs['aria-describedby'],'network-touch-details');
  svg.listeners.keydown({target:svg.nodes[2],key:'Escape',preventDefault(){}});assert.equal(element('network-touch-details').hidden,true);
});

test('hover export excludes transient hits and halos, restoring original selection and metadata',async()=>{
  const {element,pointer,click,downloads,run,history}=setup(),svg=element('network-graph').svg,node=svg.nodes[8],snapshot=JSON.stringify(history.state),positions=svg.nodes.map(item=>item.attrs.transform);
  const selected=run('networkItem');pointer('pointermove',node,400,300);click('export-network-svg');
  const exported=await downloads[0].blob.text(),metadata=JSON.parse(decode(exported.match(/<metadata>(.*?)<\/metadata>/s)[1]));
  assert.equal(element('network-hover-card').hidden,true);assert.equal(node.attrs['data-network-hover'],'none');assert.equal(node.halo.attrs.opacity,'0');assert.deepEqual(svg.nodes.map(item=>item.attrs.transform),positions);
  assert.equal(metadata.figure.selected,selected);assert.equal(metadata.figure.displayed_edges.length,80);assert.equal(JSON.stringify(history.state),snapshot);
  assert.doesNotMatch(exported,/data-network-transient|data-network-edge-hit|data-network-hover|network-hover-card/);assert.match(exported,/class="network-node-shell"/);assert.equal(metadata.figure.layout.length,60);
});
