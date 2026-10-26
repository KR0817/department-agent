import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const html=fs.readFileSync(process.argv[2],'utf8');
const script=html.match(/<script id="community-ui-script">([\s\S]*?)<\/script>/)[1];
const nav=html.match(/<nav class="research-nav" id="community-dock"[^>]*>([\s\S]*?)<\/nav>/)[1];
function setup({width=1440,reduced=false,fine=true}={}){
  const elements=new Map(),events=new Map(),frames=new Map(),resizeObservers=[],mutations=[],variables={};let frameId=0,callbacks=0,documentY=2500;
  class Element{
    constructor(id='',attributes={}){this.id=id;this.attributes=attributes;this.dataset={};this.style={setProperty(name,value){variables[name]=value}};this.hidden=false;this.disabled=false;this.listeners=new Map();this.rect={left:0,top:0,width:100,height:48,right:100,bottom:48};this.clientWidth=100;this.scrollWidth=100;this.scrollLeft=0;this.children=[];this.parent=null;this.textContent=''}
    getAttribute(name){return this.attributes[name]??null}
    setAttribute(name,value){this.attributes[name]=String(value)}
    removeAttribute(name){delete this.attributes[name]}
    getBoundingClientRect(){return this.parent===root?{...this.rect,left:this.rect.left-root.scrollLeft,right:this.rect.right-root.scrollLeft}:this.rect}
    querySelector(selector){return selector==='.community-dock-content'?this.content:null}
    querySelectorAll(selector){return selector==='a[data-dock-item]'?this.children:[]}
    closest(selector){if(selector==='a[data-dock-item]')return this.attributes['data-dock-item']?this:null;if(selector==='[hidden]')return this.hidden?this:this.parent?.closest(selector)||null;return null}
    contains(element){return element===this||this.children.some(child=>child.contains(element))}
    addEventListener(type,listener){if(!this.listeners.has(type))this.listeners.set(type,[]);this.listeners.get(type).push(listener)}
    emit(type,event={}){for(const fn of this.listeners.get(type)||[])fn({target:this,...event})}
    focus(options={}){this.focusOptions=options;if(!options.preventScroll)documentY+=609;document.activeElement=this;this.focused=true;root.emit('focusin',{target:this})}
    scrollIntoView(options){this.scrolled=options;if(this.attributes['data-dock-item'])documentY+=609}
    click(modifiers={}){
      if(this.disabled)return;
      const event={target:this,button:0,defaultPrevented:false,...modifiers};event.preventDefault=()=>{event.defaultPrevented=true};
      this.emit('click',event);if(this.parent===root)root.emit('click',event);
      if(!event.defaultPrevented&&this.attributes.href&&event.button===0&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey){
        const url=new URL(location.href);url.hash=this.attributes.href;history.pushState(null,'',url);events.get('popstate')?.({state:null});events.get('hashchange')?.({});
      }
      return event;
    }
  }
  const element=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id)};
  const root=element('community-dock'),frame=element('community-dock-frame'),safety=element('safety');
  root.clientWidth=width<=600?330:900;root.scrollWidth=780;root.rect.width=root.clientWidth;root.rect.right=root.clientWidth;frame.rect.height=90;safety.rect.height=42;
  for(const [index,match] of [...nav.matchAll(/<a\b([^>]*)>([\s\S]*?)<\/a>/g)].entries()){
    const attrs=Object.fromEntries([...match[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(pair=>[pair[1],pair[2]]));
    const link=new Element(attrs.id||'link-'+index,attrs);link.content=new Element();link.parent=root;link.rect={left:index*110,top:48,width:106,height:48,right:index*110+106,bottom:96};root.children.push(link);
    if(attrs.id)elements.set(attrs.id,link);
    const target=element(attrs.href.slice(1));target.rect={left:0,top:300+index*500,width:900,height:450,right:900,bottom:750+index*500};
  }
  element('network-lab').parent=element('strict-research');element('strict-research').children.push(element('network-lab'));
  const exportButton=element('export-network-svg');exportButton.addEventListener('click',()=>callbacks++);
  const location=new URL('http://127.0.0.1:18879/fixture.html?source=primary');
  const clone=value=>JSON.parse(JSON.stringify(value)),initialState={mingyirx_view:{schema_version:1,source:'primary',groupFilter:'comorbidity',network_view:{edgeLimit:40,mode:'all'}},preserved_custom_field:{value:'kept'}};
  const entries=[{url:location.href,state:clone(initialState)}];let cursor=0;
  const view={groupFilter:'comorbidity',edgeLimit:40};
  const history={
    get state(){return entries[cursor].state},get length(){return entries.length},
    pushState(state,_title,url){entries.splice(++cursor);entries.push({url:String(url),state:clone(state)});location.href=String(url)},
    back(){if(cursor>0){cursor--;location.href=entries[cursor].url;events.get('popstate')?.({state:clone(entries[cursor].state)});events.get('hashchange')?.({})}},
    forward(){if(cursor+1<entries.length){cursor++;location.href=entries[cursor].url;events.get('popstate')?.({state:clone(entries[cursor].state)});events.get('hashchange')?.({})}}
  };
  // Mirrors the incumbent source handler's null-state fallback, which caused
  // native fragment navigation to reset the analysis in the actual browser.
  events.set('popstate',event=>{view.groupFilter=event.state?.mingyirx_view?.groupFilter||'all';view.edgeLimit=event.state?.mingyirx_view?.network_view?.edgeLimit||80});
  const document={getElementById:element,querySelector:selector=>selector==='.safety'?safety:null,body:element('body'),activeElement:null};
  const reducedQuery={matches:reduced,listeners:[],addEventListener(_type,fn){this.listeners.push(fn)}},fineQuery={matches:fine,listeners:[],addEventListener(_type,fn){this.listeners.push(fn)}};
  class Observer{constructor(fn){this.fn=fn;this.targets=[];resizeObservers.push(this)}observe(target){this.targets.push(target)}disconnect(){this.disconnected=true}}
  class MutationObserver{constructor(fn){this.fn=fn;mutations.push(this)}observe(){}disconnect(){this.disconnected=true}}
  const context=vm.createContext({document,location,history,URL,innerWidth:width,matchMedia:query=>query.includes('reduced-motion')?reducedQuery:fineQuery,ResizeObserver:Observer,MutationObserver,requestAnimationFrame:fn=>{frames.set(++frameId,fn);return frameId},cancelAnimationFrame:id=>frames.delete(id),addEventListener:(type,fn)=>events.set(type,fn)});
  vm.runInContext(script,context);
  const settle=()=>{let count=0;while(frames.size&&count<250){const [id,fn]=frames.entries().next().value;frames.delete(id);fn();count++}assert.ok(count<250,'Animation did not settle');return count};
  return {element,root,frame,safety,events,frames,variables,resizeObservers,mutations,reducedQuery,fineQuery,location,history,view,settle,callbacks:()=>callbacks,documentY:()=>documentY};
}

test('upstream spring and proximity animate only on demand without changing link slots',()=>{
  const {root,frames,settle}=setup();assert.equal(root.dataset.dockState,'idle');assert.equal(frames.size,0);
  root.emit('pointermove',{clientX:163});assert.equal(frames.size,1);assert.equal(root.dataset.dockState,'active');settle();
  assert.ok(Number(root.dataset.dockMax)>.8);assert.equal(frames.size,0);
  for(const link of root.children){assert.equal(link.style.width,undefined);assert.equal(link.style.height,undefined);assert.match(link.content.style.transform,/translateY/)}
  root.emit('pointerleave');settle();assert.equal(root.dataset.dockState,'idle');assert.equal(root.dataset.dockMax,'0.00');
});

test('keyboard keeps native Enter while arrow navigation focuses semantic links',()=>{
  const {root,location,element,settle}=setup(),first=root.children[0],network=root.children[1];let prevented=false;
  first.focus();settle();assert.equal(root.dataset.dockState,'focus');
  root.emit('keydown',{target:first,key:'ArrowRight',preventDefault(){prevented=true}});assert.equal(prevented,true);assert.equal(network.focused,true);assert.equal(network.focusOptions.preventScroll,true);assert.equal(network.scrolled,undefined);
  prevented=false;root.emit('keydown',{target:network,key:'Enter',preventDefault(){prevented=true}});assert.equal(prevented,false);
  network.click();assert.equal(location.hash,'#network-lab');assert.equal(element('network-lab').scrolled.block,'start');settle();
});

test('quality-to-strict keyboard focus changes only the horizontal dock position',()=>{
  for(const width of [1440,390]){
    const fixture=setup({width}),{root,element,events,location,settle}=fixture;
    for(const link of root.children){const target=element(link.attributes.href.slice(1));target.rect.top=-1800;target.rect.bottom=-1000}
    Object.assign(element('network-lab').rect,{top:-1162.25,bottom:-200});Object.assign(element('research-quality').rect,{top:100,bottom:800});
    location.hash='#research-quality';events.get('scroll')();settle();
    const quality=root.children.find(link=>link.attributes.href==='#research-quality'),strict=element('strict-nav-link');quality.focus({preventScroll:true});settle();
    const beforeY=fixture.documentY(),beforeTop=element('network-lab').getBoundingClientRect().top;
    root.emit('keydown',{target:quality,key:'ArrowLeft',preventDefault(){}});settle();
    assert.equal(strict.focused,true);assert.equal(strict.focusOptions.preventScroll,true);assert.equal(strict.scrolled,undefined);
    assert.equal(fixture.documentY(),beforeY);assert.equal(element('network-lab').getBoundingClientRect().top,beforeTop);assert.equal(location.hash,'#research-quality');
    assert.equal(quality.attributes['aria-current'],'location');assert.equal(strict.attributes['aria-current'],undefined);
    if(width===390){assert.ok(root.scrollLeft>0);const rect=strict.getBoundingClientRect();assert.ok(rect.left>=0&&rect.right<=root.clientWidth)}
  }
});

test('dock activation preserves the complete analysis history through fragments and back/forward',()=>{
  const {root,history,view,location,settle,element}=setup(),before=JSON.parse(JSON.stringify(history.state));
  const comparison=root.children.find(link=>link.attributes.href==='#comparison-section'),network=root.children.find(link=>link.attributes.href==='#network-lab');
  const click=comparison.click();settle();assert.equal(click.defaultPrevented,true);assert.equal(location.hash,'#comparison-section');assert.deepEqual(history.state,before);
  assert.deepEqual(view,{groupFilter:'comorbidity',edgeLimit:40});assert.equal(element('comparison-section').scrolled.block,'start');
  const length=history.length;comparison.click();settle();assert.equal(history.length,length);
  network.click({detail:0});settle();assert.equal(location.hash,'#network-lab');assert.deepEqual(history.state,before);assert.deepEqual(view,{groupFilter:'comorbidity',edgeLimit:40});
  history.back();settle();assert.equal(location.hash,'#comparison-section');assert.deepEqual(history.state,before);assert.deepEqual(view,{groupFilter:'comorbidity',edgeLimit:40});
  history.forward();settle();assert.equal(location.hash,'#network-lab');assert.deepEqual(history.state,before);assert.deepEqual(view,{groupFilter:'comorbidity',edgeLimit:40});
});

test('dock leaves modified middle prevented and hidden activations to existing browser behavior',()=>{
  const {root,history,location}=setup(),link=root.children[1],before=history.length;
  for(const modifiers of [{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{button:1},{defaultPrevented:true}]){
    const event=link.click(modifiers);assert.equal(event.defaultPrevented,Boolean(modifiers.defaultPrevented));assert.equal(history.length,before);assert.equal(location.hash,'');
  }
  link.hidden=true;let prevented=false;root.emit('click',{target:link,button:0,defaultPrevented:false,preventDefault(){prevented=true}});assert.equal(prevented,false);assert.equal(history.length,before);
});

test('phone coarse pointer and reduced-motion modes have no spring frames',()=>{
  for(const options of [{width:390},{fine:false},{reduced:true}]){
    const {root,frames,frame}=setup(options);assert.equal(root.dataset.dockState,'static');root.emit('pointermove',{clientX:60});root.children[0].focus();assert.equal(frames.size,0);
    for(const link of root.children)assert.equal(link.content.style.transform,'');if(options.width)assert.equal(frame.dataset.overflow,'true');
  }
  const {root,frames,reducedQuery}=setup();root.emit('pointermove',{clientX:60});assert.equal(frames.size,1);reducedQuery.matches=true;reducedQuery.listeners.forEach(fn=>fn());assert.equal(frames.size,0);assert.equal(root.dataset.dockState,'static');
});

test('nested network section wins scroll location and dynamic offsets track the banner',()=>{
  const {root,element,events,settle,variables,safety,frame,resizeObservers}=setup();
  for(const link of root.children){const target=element(link.attributes.href.slice(1));target.rect.top=1000;target.rect.bottom=1400}
  Object.assign(element('strict-research').rect,{top:20,bottom:950});Object.assign(element('network-lab').rect,{top:110,bottom:800});
  events.get('scroll')();settle();assert.equal(root.children.find(link=>link.attributes.href==='#network-lab').attributes['aria-current'],'location');
  element('network-lab').rect.bottom=130;events.get('scroll')();settle();assert.equal(element('strict-nav-link').attributes['aria-current'],'location');
  assert.equal(root.children.filter(link=>link.attributes['aria-current']).length,1);
  safety.rect.height=80;frame.rect.height=104;resizeObservers[0].fn();assert.equal(variables['--community-safety-height'],'80px');assert.equal(variables['--community-anchor-offset'],'202px');
});

test('source-driven hidden sections stay hidden and native disabled action remains effective',()=>{
  const {root,element,mutations,callbacks}=setup();const exportButton=element('export-network-svg');
  exportButton.disabled=true;exportButton.click();assert.equal(callbacks(),0);exportButton.disabled=false;exportButton.click();assert.equal(callbacks(),1);
  element('strict-research').hidden=true;element('annual-section').hidden=true;mutations[0].fn();
  assert.equal(element('strict-nav-link').hidden,true);assert.equal(root.children.find(link=>link.attributes.href==='#network-lab').hidden,true);assert.equal(root.children.find(link=>link.attributes.href==='#annual-section').hidden,true);
  element('strict-research').hidden=false;element('annual-section').hidden=false;element('analysis-source').emit('change');
  assert.equal(element('strict-nav-link').hidden,false);assert.equal(root.children.find(link=>link.attributes.href==='#network-lab').hidden,false);
  exportButton.click();assert.equal(callbacks(),2);
});

test('history-cache suspension and restoration preserve controls and malformed fragments are safe',()=>{
  const {root,events,frames,location,settle,resizeObservers}=setup();root.emit('pointermove',{clientX:50});assert.equal(frames.size,1);
  events.get('pagehide')({persisted:true});assert.equal(frames.size,0);assert.notEqual(resizeObservers[0].disconnected,true);
  events.get('pageshow')({persisted:true});settle();root.emit('pointermove',{clientX:50});assert.equal(frames.size,1);settle();
  location.hash='#%zz';assert.doesNotThrow(()=>events.get('hashchange')());
  events.get('pagehide')({persisted:false});assert.equal(frames.size,0);assert.equal(resizeObservers[0].disconnected,true);
});
