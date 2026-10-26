import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const html=fs.readFileSync(process.argv[2],'utf8');
const decode=value=>String(value).replaceAll('&quot;','"').replaceAll('&#39;',"'").replaceAll('&lt;','<').replaceAll('&gt;','>').replaceAll('&amp;','&');

// DOM event stubs exercise the actual composed scripts. Browser rendering is separate.
export function setup({reducedMotion=false,width=1440,transform=payload=>payload,blurOnSceneReplace=false}={}){
  const elements=new Map(),events=new Map(),frames=new Map(),downloads=[],stack=[];let cursor=-1,frameId=0;
  class Element{
    constructor(id='',attrs={}){this.id=id;this.attrs=attrs;this.listeners={};this.value='';this.textContent='';this.hidden=false;this.disabled=false;this.checked=id==='fold-combos';this.dataset={};this.content='';this.style={};this.captured=new Set();this.classList={add(){},remove(){}}}
    set innerHTML(value){const previous=this.svg;this.content=String(value);this.svg=null;if((['network-graph','network3d-scene'].includes(this.id)||this.id.startsWith('network-compare-')&&this.id.endsWith('-scene'))&&this.content.includes('<svg'))this.svg=new Svg(this.content,this.id==='network3d-scene',this.id.startsWith('network-compare-'));if(blurOnSceneReplace&&previous?.nodes.some(node=>node.focused))this.emit('focusout',{relatedTarget:null})}
    get innerHTML(){return this.content}
    get options(){return [...this.content.matchAll(/<option[^>]*value="([^"]*)"[^>]*>(.*?)<\/option>/g)].map(m=>({value:m[1],textContent:m[2]}))}
    addEventListener(type,fn,options={}){(this.listeners[type]??=[]).push(fn);options.signal?.addEventListener('abort',()=>{this.listeners[type]=this.listeners[type].filter(value=>value!==fn)},{once:true})}
    emit(type,event={}){for(const listener of this.listeners[type]||[])listener({target:this,preventDefault(){},...event})}
    setAttribute(name,value){this.attrs[name]=String(value)}getAttribute(name){return this.attrs[name]??null}removeAttribute(name){delete this.attrs[name]}
    getBoundingClientRect(){const card=this.id.includes('tooltip')||this.id==='network-hover-card',viewWidth=width<=600?width-32:900;return {left:0,top:0,width:card?Math.min(280,viewWidth-24):viewWidth,height:card?240:width<=600?440:560,right:viewWidth,bottom:560}}
    querySelector(selector){if(selector==='svg')return this.svg;if(selector==='.network-node-shell'||selector==='.network3d-ball'||selector==='circle')return this.circle;if(selector==='[data-network-hover-halo]'||selector==='.network3d-orbit')return this.halo;if(selector==='.network3d-label'||selector==='[data-compare-label]')return this.label;return null}
    querySelectorAll(){return []}
    closest(selector){if(selector.startsWith('[')){const key=selector.slice(1,-1);return this.attrs[key]!==undefined?this:null}return selector==='#'+this.id?this:null}
    focus(){this.focused=true}scrollIntoView(){this.scrolled=true}appendChild(){}contains(element){return element===this||this.svg?.nodes.includes(element)||this.svg?.hits.includes(element)}
    insertBefore(node,next){this.children??=[];const index=this.children.indexOf(node);if(index>=0)this.children.splice(index,1);this.children.splice(next===null?this.children.length:this.children.indexOf(next),0,node);for(let i=0;i<this.children.length;i++)this.children[i].nextSibling=this.children[i+1]||null;node.moves=(node.moves||0)+1}
    setPointerCapture(id){this.captured.add(id)}hasPointerCapture(id){return this.captured.has(id)}releasePointerCapture(id){this.captured.delete(id)}
  }
  class Svg extends Element{
    constructor(markup,is3d,compare=false){super();this.is3d=is3d;this.plane=new Element();this.layer=new Element();const prefix=compare?'compare':is3d?'network3d':'network';
      this.nodes=[...markup.matchAll(new RegExp('<g[^>]*data-'+prefix+'-node="([^\"]+)"','g'))].map(match=>{const node=new Element('',{['data-'+prefix+'-node']:decode(match[1])});node.circle=new Element();node.halo=new Element();node.label=new Element();return node});
      this.edges=[...markup.matchAll(new RegExp('<line data-'+prefix+'-edge="(\\d+)"','g'))].map(match=>new Element('',{['data-'+prefix+'-edge']:match[1]}));
      this.hits=[...markup.matchAll(new RegExp('<line data-'+prefix+'-edge-hit="(\\d+)"','g'))].map(match=>new Element('',{['data-'+prefix+'-edge-hit']:match[1]}));
      this.layer.children=[...this.nodes];for(let i=0;i<this.nodes.length;i++)this.nodes[i].nextSibling=this.nodes[i+1]||null;
    }
    querySelector(selector){return selector==='[data-network-plane]'?this.plane:['[data-network3d-nodes]','[data-compare-nodes]'].includes(selector)?this.layer:null}
    querySelectorAll(selector){if(selector.includes(', '))return [...this.edges,...this.hits];if(selector.endsWith('-node]'))return this.nodes;if(selector.endsWith('-edge]'))return this.edges;if(selector.endsWith('-edge-hit]'))return this.hits;return []}
    createSVGPoint(){return {x:0,y:0,matrixTransform(){return {x:this.x,y:this.y}}}}getScreenCTM(){return {inverse(){return {}}}}
  }
  const element=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id)};
  const emit=(key,event={})=>{for(const fn of events.get(key)||[])fn(event)};
  const listen=(key,fn)=>events.set(key,[...(events.get(key)||[]),fn]);
  for(const id of ['dashboard-data','supplement-data'])element(id).textContent=JSON.stringify(transform(JSON.parse(html.match(new RegExp('<script id="'+id+'" type="application/json">(.*?)</script>','s'))[1])));
  element('network-graph').clientWidth=width<=600?width-48:900;
  element('analysis-source').innerHTML='<option value="primary">Primary</option><option value="supplement">Supplement</option>';
  const annual=['prevalence','addition','removal'].map(annual=>Object.assign(element('annual-'+annual),{dataset:{annual}})),sizes=['all','2','3'].map(size=>Object.assign(element('size-'+size),{dataset:{size}}));
  const location={href:'http://127.0.0.1:18879/index.html',search:'',hash:''},clone=value=>JSON.parse(JSON.stringify(value));
  const updateUrl=url=>{location.href=String(url);location.search=new URL(url).search;location.hash=new URL(url).hash};
  const history={replaceState(state,_title,url){if(cursor<0){cursor=0;stack.push(clone(state))}else stack[cursor]=clone(state);updateUrl(url)},pushState(state,_title,url){stack.splice(++cursor);stack.push(clone(state));updateUrl(url)},back(){if(cursor>0){cursor--;emit('popstate',{state:stack[cursor]})}},get state(){return stack[cursor]}};
  class TestURL extends URL{static createObjectURL(blob){downloads.push({blob});return 'blob:fixture'}static revokeObjectURL(){}}
  const document={hidden:false,getElementById:element,title:'',body:{appendChild(){}},addEventListener:(type,fn)=>listen('document-'+type,fn),createElement:()=>({click(){downloads.at(-1).name=this.download},remove(){}}),querySelectorAll:selector=>({'.annual-btn':annual,'.filter-btn[data-size]':sizes}[selector]||[])};
  const media={matches:reducedMotion,addEventListener:(type,fn)=>listen('media-'+type,fn)};
  const context=vm.createContext({document,location,history,URL:TestURL,URLSearchParams,Blob,AbortController,innerWidth:width,innerHeight:1000,matchMedia:query=>query.includes('reduced-motion')?media:{matches:width>600,addEventListener(){}},requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId},cancelAnimationFrame:id=>frames.delete(id),setTimeout:fn=>fn(),addEventListener:(type,fn)=>listen(type,fn)});
  const run=code=>vm.runInContext(code,context);
  for(const block of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g))if(!block[1].includes('application/json'))run(block[2]);
  const click=id=>element(id).emit('click'),change=(id,value)=>element(id).emit('change',{target:{value}});
  const pointer=(type,target,x,y,pointerType='mouse')=>element('network3d-scene').emit(type,{type,target,button:0,pointerId:1,clientX:x,clientY:y,pointerType});
  return {element,run,change,click,pointer,frames,media,emit,downloads,history,document,Element};
}

const camera=fixture=>JSON.parse(fixture.element('network3d-scene').getAttribute('data-camera'));
const node=fixture=>fixture.element('network3d-scene').svg.nodes;
const detailValues=element=>[...element.innerHTML.matchAll(/<dd>(.*?)<\/dd>/g)].map(match=>decode(match[1]));

test('true 3D coordinates are deterministic, rotations affect depth and perspective without data changes',()=>{
  const fixture=setup(),{run,element,frames}=fixture;run('globalThis.before3d=JSON.stringify(data);globalThis.points3d=MingYiRxNetwork3D.layout(strictRows("nodes"))');
  assert.equal(run('points3d.length'),72);assert.ok(run('new Set(points3d.map(p=>p.z)).size')>20);
  assert.equal(run('JSON.stringify(points3d)===JSON.stringify(MingYiRxNetwork3D.layout(strictRows("nodes")))'),true);
  assert.equal(run('points3d.every(p=>[p.x,p.y,p.z].every(Number.isFinite))'),true);
  assert.equal(run('(()=>{const p=points3d[5],a=MingYiRxNetwork3D.project(p,{yaw:0,pitch:0,zoom:1}),b=MingYiRxNetwork3D.project(p,{yaw:.5,pitch:.3,zoom:1});return a.x!==b.x&&a.y!==b.y&&a.z!==b.z})()'),true);
  assert.equal(run('MingYiRxNetwork3D.project({x:20,y:0,z:-200},{yaw:0,pitch:0,zoom:1}).scale>MingYiRxNetwork3D.project({x:20,y:0,z:200},{yaw:0,pitch:0,zoom:1}).scale'),true);
  assert.equal(node(fixture).length,60);assert.equal(element('network3d-scene').svg.edges.length,80);assert.equal(element('network-lab').getAttribute('data-network-dimension'),'3d');assert.equal(frames.size,0);
  assert.equal(run('JSON.stringify(data)===before3d'),true);
});

test('drag rotates both axes, preserves selection, cancels capture and does not edit disclosed values',()=>{
  const fixture=setup(),{element,pointer,run}=fixture,scene=element('network3d-scene'),target=node(fixture)[3];
  run('globalThis.before3d=JSON.stringify(data);globalThis.selected3d=MingYiRxNetwork.getSnapshot().selected');const before=camera(fixture);
  pointer('pointerdown',target,100,100);pointer('pointermove',target,160,125);pointer('pointerup',target,160,125);scene.emit('click',{target});
  assert.notEqual(camera(fixture).yaw,before.yaw);assert.notEqual(camera(fixture).pitch,before.pitch);assert.equal(scene.captured.size,0);
  assert.equal(run('MingYiRxNetwork.getSnapshot().selected===selected3d'),true);assert.equal(run('JSON.stringify(data)===before3d'),true);
  pointer('pointerdown',scene,100,100);pointer('pointercancel',scene,100,100);assert.equal(scene.captured.size,0);
});

test('node and edge hover reuse exact zero/missing metrics; touch selection updates original inspector',()=>{
  const fixture=setup({transform:payload=>{payload.research.nodes[0].prevalence='0';payload.research.nodes[0].exposed_patients='0';for(const edge of payload.research.edges){edge.support='';edge.lift='0'}return payload}});
  const {element,pointer,run}=fixture,scene=element('network3d-scene'),target=node(fixture).find(item=>item.getAttribute('data-network3d-node')==='Herb 00');
  pointer('pointermove',target,80,100);assert.equal(element('network3d-tooltip').hidden,false);assert.deepEqual(detailValues(element('network3d-tooltip')).slice(0,3),['0','100','0.0%']);
  pointer('pointermove',scene.svg.hits[0],90,110);const values=detailValues(element('network3d-tooltip'));assert.equal(values[1],'\u672a\u516c\u5f00 / \u672a\u4f30\u8ba1');assert.equal(values[3],'0');
  const other=node(fixture).find(item=>item.getAttribute('data-network3d-node')==='Herb 03');pointer('pointerdown',other,80,100,'touch');pointer('pointerup',other,80,100,'touch');
  assert.match(element('network-inspector').innerHTML,/Herb 03/);assert.match(element('network3d-detail').innerHTML,/Herb 03/);assert.equal(run('networkItem'),'Herb 00');
  fixture.emit('document-keydown',{key:'Escape'});assert.equal(element('network3d-detail').hidden,true);
});

test('keyboard rotates and focuses values; ordinary wheel remains page scroll',()=>{
  const fixture=setup(),{element,click}=fixture,scene=element('network3d-scene'),target=node(fixture)[0],before=camera(fixture);
  scene.emit('keydown',{target:scene,key:'ArrowRight'});scene.emit('keydown',{target:scene,key:'ArrowDown'});assert.notEqual(camera(fixture).yaw,before.yaw);assert.notEqual(camera(fixture).pitch,before.pitch);
  scene.emit('keydown',{target,key:'PageDown'});assert.ok(node(fixture).some(item=>item.focused));assert.equal(element('network3d-detail').hidden,false);
  let prevented=false;scene.emit('wheel',{ctrlKey:false,metaKey:false,deltaY:-1,preventDefault(){prevented=true}});assert.equal(prevented,false);
  scene.emit('wheel',{ctrlKey:true,deltaY:-1,preventDefault(){prevented=true}});assert.equal(prevented,true);assert.ok(camera(fixture).zoom>1);
  click('network3d-reset');assert.deepEqual(camera(fixture),before);
});

test('source, local controls, history and dimension changes use one disclosed graph',()=>{
  const fixture=setup(),{element,change,click,run,history}=fixture;change('network-view-mode','neighborhood');change('network-edge-limit','40');
  assert.equal(element('network3d-scene').svg.edges.length,4);assert.equal(run('MingYiRxNetwork.getSnapshot().mode'),'neighborhood');
  click('network-dimension-2d');assert.equal(element('network-lab').getAttribute('data-network-dimension'),'2d');run('globalThis.saved3d=captureViewState()');
  change('analysis-source','supplement');assert.ok(node(fixture).every(item=>item.getAttribute('data-network3d-node').startsWith('Secondary')));assert.doesNotMatch(element('network3d-detail').innerHTML,/Herb/);
  run('applyViewState(saved3d)');assert.equal(element('network-lab').getAttribute('data-network-dimension'),'2d');assert.equal(element('network3d-scene').svg.edges.length,4);
  click('network-dimension-3d');assert.equal(element('network-lab').getAttribute('data-network-dimension'),'3d');history.back();assert.equal(element('network-lab').getAttribute('data-network-dimension'),'2d');
  run('resetDashboardView()');assert.equal(element('network-lab').getAttribute('data-network-dimension'),'3d');assert.equal(node(fixture).length,60);
});

test('optional auto rotation pauses on hover, drag, visibility, reduced motion, mode and source',()=>{
  const fixture=setup(),{element,click,frames,pointer,document,emit,media,change}=fixture;
  click('network3d-motion');assert.equal(frames.size,1);const initial=camera(fixture).yaw;const [id,frame]=frames.entries().next().value;frames.delete(id);frame(16);assert.notEqual(camera(fixture).yaw,initial);
  pointer('pointermove',node(fixture)[0],80,100);assert.equal(frames.size,0);element('network3d-scene').emit('pointerleave');assert.equal(frames.size,1);
  document.hidden=true;emit('document-visibilitychange');assert.equal(frames.size,0);document.hidden=false;emit('document-visibilitychange');assert.equal(frames.size,1);
  media.matches=true;emit('media-change');assert.equal(frames.size,0);assert.equal(element('network3d-motion').disabled,true);
  media.matches=false;emit('media-change');click('network3d-motion');change('analysis-source','supplement');assert.equal(frames.size,0);
  click('network3d-motion');click('network-dimension-2d');assert.equal(element('network3d-motion').getAttribute('aria-pressed'),'false');
  const reduced=setup({reducedMotion:true});assert.equal(reduced.frames.size,0);assert.equal(reduced.element('network3d-motion').disabled,true);
});

test('SVG export captures camera, genuine x/y/z and only original visible rows without hit overlays',async()=>{
  const fixture=setup(),{element,click,downloads,run}=fixture;run('globalThis.before3d=JSON.stringify(data)');
  element('network3d-scene').emit('keydown',{key:'ArrowRight'});click('network3d-zoom-in');click('export-network-svg');
  const content=await downloads[0].blob.text(),metadata=JSON.parse(decode(content.match(/<metadata>(.*?)<\/metadata>/s)[1]));
  assert.match(downloads[0].name,/network-3d/);assert.equal(metadata.figure.dimension,'3d');assert.equal(metadata.figure.displayed_nodes.length,60);assert.equal(metadata.figure.displayed_edges.length,80);assert.equal(metadata.figure.layout.length,60);
  assert.ok(metadata.figure.layout.some(point=>point.z!==0));assert.deepEqual({yaw:metadata.figure.camera.yaw,pitch:metadata.figure.camera.pitch,zoom:metadata.figure.camera.zoom},camera(fixture));
  assert.doesNotMatch(content,/data-network3d-edge-hit|role="tooltip"|network3d-tooltip/);assert.match(content,/network3d-jade/);assert.equal(run('JSON.stringify(data)===before3d'),true);
  for(let i=0;i<8;i++)click('network3d-zoom-in');click('export-network-svg');const magnified=await downloads[1].blob.text();
  assert.match(magnified,/<clipPath id="network3d-clip"><rect data-network3d-cliprect="true" width="900" height="560"/);assert.match(magnified,/<g clip-path="url\(#network3d-clip\)">/);assert.doesNotMatch(magnified,/rect width="100%"/);
  click('network-dimension-2d');click('export-network-svg');assert.doesNotMatch(downloads[2].name,/network-3d/);
});

test('empty data disables 3D controls and export; hostile labels remain escaped',async()=>{
  const empty=setup(),{element,change,click,downloads}=empty;change('strict-group','empty_strict');assert.equal(element('network3d-scene').svg,null);assert.equal(element('network3d-zoom-in').disabled,true);assert.equal(element('export-network-svg').disabled,true);click('export-network-svg');assert.equal(downloads.length,0);
  const hostile=setup({transform:payload=>{const old=payload.research.nodes[0].item_name;payload.research.nodes[0].item_name='<img src=x onerror="attack">';payload.research.usage[0].item_name=payload.research.nodes[0].item_name;for(const edge of payload.research.edges){if(edge.item_1===old)edge.item_1=payload.research.nodes[0].item_name;if(edge.item_2===old)edge.item_2=payload.research.nodes[0].item_name}return payload}});
  assert.doesNotMatch(hostile.element('network3d-scene').innerHTML,/<img /);assert.match(hostile.element('network3d-scene').innerHTML,/&lt;img/);
  hostile.click('export-network-svg');assert.doesNotMatch(await hostile.downloads[0].blob.text(),/<img /);
});

test('bridge snapshots cannot mutate original rows and inspector selection remains shared',()=>{
  const fixture=setup(),{run,element,Element}=fixture;assert.equal(run('(()=>{const snapshot=MingYiRxNetwork.getSnapshot(),before=research.nodes[0].patients;snapshot.graph.nodes[0].patients="changed";return research.nodes[0].patients===before})()'),true);
  element('network-inspector').emit('click',{target:new Element('',{'data-network-select':'Herb 03'})});
  const target=node(fixture).find(item=>item.getAttribute('data-network3d-node')==='Herb 03');assert.equal(target.getAttribute('aria-pressed'),'true');
  element('network-inspector').emit('click',{target:new Element('network-center-selected')});assert.equal(run('networkItem'),'Herb 03');assert.equal(element('network3d-scene').svg.edges.length,7);
});

test('phone projection bounds and long labels retain full accessible names',()=>{
  const fixture=setup({width:390}),{run,element}=fixture;assert.match(element('network3d-scene').innerHTML,/viewBox="0 0 358 440"/);
  assert.equal(run('MingYiRxNetwork3D.layout(strictRows("nodes").slice(0,60)).every(p=>{const q=MingYiRxNetwork3D.project(p,{yaw:.38,pitch:-.18,zoom:1},358,440);return q.x>=0&&q.x<=358&&q.y>=0&&q.y<=440})'),true);
  const longName='Synthetic very long medication name with multiple words and detail';
  const long=setup({width:390,transform:payload=>{payload.research.nodes[0].item_name=longName;payload.research.usage[0].item_name=longName;return payload}});
  assert.ok(long.element('network3d-scene').innerHTML.includes('<title>'+longName+'</title>'));
});

test('rotation preserves focused node while reordering all spheres by depth',()=>{
  const fixture=setup(),scene=fixture.element('network3d-scene'),target=node(fixture)[20];
  scene.emit('focusin',{target});target.focus();const moves=target.moves||0;
  for(let i=0;i<18;i++)scene.emit('keydown',{target,key:'ArrowRight'});
  const depths=scene.svg.layer.children.map(item=>Number(item.getAttribute('data-depth')));
  assert.ok(depths.every((value,index)=>index===0||depths[index-1]>=value));assert.equal(target.moves||0,moves);assert.equal(target.focused,true);
});
