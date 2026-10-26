import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const script=fs.readFileSync(process.argv[2],'utf8');

function setup({observerAvailable=true,missingMode=false}={}){
  const elements=new Map(),events=new Map(),observers=[],pending=new Set(),changes=[];
  let writes=0,focused=null;
  class Element{
    constructor(tagName,id=''){this.tagName=tagName.toUpperCase();this.id=id;this.parentElement=null;this.children=[];this.attributes={};this.dataset={};this.listeners=new Map();this.hidden=false;this.disabled=false;this.textContent='';this.value=''}
    append(...children){for(const child of children){this.children.push(child);child.parentElement=this}}
    insertAdjacentElement(position,element){assert.equal(position,'afterend');const index=this.parentElement.children.indexOf(this);this.parentElement.children.splice(index+1,0,element);element.parentElement=this.parentElement}
    closest(selector){if(selector==='label')return this.tagName==='LABEL'?this:this.parentElement?.closest(selector);return null}
    setAttribute(name,value){writes++;this.attributes[name]=String(value);mutate(this,'attributes',name)}
    getAttribute(name){return this.attributes[name]??null}
    addEventListener(type,listener){if(!this.listeners.has(type))this.listeners.set(type,[]);this.listeners.get(type).push(listener)}
    dispatchEvent(event){event.target=this;for(const listener of this.listeners.get(event.type)||[])listener(event);if(event.bubbles)this.parentElement?.bubble(event);return !event.defaultPrevented}
    bubble(event){for(const listener of this.listeners.get(event.type)||[])listener(event);if(event.bubbles)this.parentElement?.bubble(event)}
    click(){if(!this.disabled)this.dispatchEvent(new Event('click',{bubbles:true}))}
    focus(options){focused=this;this.focusOptions=options}
  }
  class Event{
    constructor(type,options={}){this.type=type;Object.assign(this,options);this.defaultPrevented=false}
    preventDefault(){this.defaultPrevented=true}
  }
  class Observer{
    constructor(callback){this.callback=callback;this.targets=[];observers.push(this)}
    observe(target,options){this.targets.push({target,options})}
    disconnect(){this.disconnected=true}
  }
  function mutate(target,type,name){for(const observer of observers){if(observer.disconnected)continue;if(observer.targets.some(entry=>entry.target===target&&entry.options[type]&&(!entry.options.attributeFilter||entry.options.attributeFilter.includes(name))))pending.add(observer)}}
  const flush=()=>{let passes=0;while(pending.size){assert.ok(++passes<5,'Observer feedback loop');const batch=[...pending];pending.clear();batch.forEach(observer=>observer.callback())}return passes};
  const inspector=new Element('aside','network-inspector');elements.set(inspector.id,inspector);
  const toolbar=new Element('div'),makeSelect=(id,options,selected)=>{
    const label=new Element('label'),select=new Element('select',id);select.options=options.map(([value,text])=>({value,textContent:text,disabled:false}));select.value=selected;
    label.append(select);toolbar.append(label);elements.set(id,select);
    // Existing state handlers own the render, history, and filtering. The new
    // controls may only invoke this same change path with the original select.
    select.addEventListener('change',event=>{changes.push({id:select.id,value:select.value,target:event.target,bubbles:event.bubbles});mutate(inspector,'childList')});
    return select;
  };
  const mode=makeSelect('network-view-mode',[['all','Full cohort'],['neighborhood','Center neighborhood']],'all');
  const density=makeSelect('network-edge-limit',[['40','40 edges'],['80','80 edges'],['120','120 edges']],'80');
  if(missingMode)elements.delete(mode.id);
  const document={getElementById:id=>elements.get(id)||null,createElement:tag=>new Element(tag)};
  vm.runInNewContext(script,{document,Event,MutationObserver:observerAvailable?Observer:undefined,addEventListener:(name,callback)=>events.set(name,callback)});
  const groupFor=id=>toolbar.children.find(element=>element.dataset.communityControl===id)?.children[1];
  const button=(id,value)=>groupFor(id)?.children.find(element=>element.dataset.value===value);
  const state=(modeValue,densityValue,disabled=false)=>{mode.value=modeValue;density.value=densityValue;mode.disabled=disabled;density.disabled=disabled;mutate(inspector,'childList');mutate(mode,'attributes','disabled');mutate(density,'attributes','disabled');flush()};
  const key=(button,key)=>{const event=new Event('keydown',{bubbles:true,key});button.dispatchEvent(event);return event};
  return {mode,density,inspector,toolbar,events,observers,changes,flush,button,groupFor,state,key,mutate,writes:()=>writes,focused:()=>focused};
}

test('native options remain authoritative and one activation sends one original change event',()=>{
  const f=setup(),mode='network-view-mode',density='network-edge-limit';
  assert.equal(f.mode.parentElement.hidden,true);assert.equal(f.density.parentElement.hidden,true);
  assert.equal(f.button(mode,'all').getAttribute('aria-pressed'),'true');assert.equal(f.button(density,'80').getAttribute('aria-pressed'),'true');
  assert.equal(f.button(mode,'neighborhood').getAttribute('aria-label'),'Center neighborhood');
  f.button(mode,'neighborhood').click();f.flush();assert.equal(f.mode.value,'neighborhood');assert.equal(f.changes.length,1);
  assert.equal(f.changes[0].target,f.mode);assert.equal(f.changes[0].bubbles,true);assert.equal(f.button(mode,'neighborhood').getAttribute('aria-pressed'),'true');
  f.button(mode,'neighborhood').click();f.flush();assert.equal(f.changes.length,1);
  f.button(density,'120').click();f.flush();assert.equal(f.density.value,'120');assert.equal(f.changes.length,2);
});

test('source cohort inspector and history renders synchronize without creating change events',()=>{
  const f=setup();
  for(const [mode,density] of [['neighborhood','40'],['all','80'],['neighborhood','120'],['all','40']]){
    f.state(mode,density);
    for(const button of f.groupFor('network-view-mode').children)assert.equal(button.getAttribute('aria-pressed'),String(button.dataset.value===mode));
    for(const button of f.groupFor('network-edge-limit').children)assert.equal(button.getAttribute('aria-pressed'),String(button.dataset.value===density));
  }
  assert.equal(f.changes.length,0);
  const writes=f.writes();f.mutate(f.inspector,'childList');assert.equal(f.flush(),1);assert.equal(f.writes(),writes);
  assert.equal(f.observers[0].targets.length,3);assert.ok(f.observers[0].targets.every(entry=>entry.target===f.inspector||entry.target===f.mode||entry.target===f.density));
});

test('empty state disables choices and restores them through the same source render',()=>{
  const f=setup();f.state('all','80',true);
  for(const id of ['network-view-mode','network-edge-limit'])for(const button of f.groupFor(id).children){assert.equal(button.disabled,true);button.click()}
  assert.equal(f.changes.length,0);assert.equal(f.mode.value,'all');assert.equal(f.density.value,'80');
  f.state('all','80',false);assert.equal(f.button('network-view-mode','neighborhood').disabled,false);f.button('network-view-mode','neighborhood').click();assert.equal(f.mode.value,'neighborhood');
});

test('arrows Home End focus and activate native buttons while Enter Space remain native',()=>{
  const f=setup(),id='network-edge-limit',middle=f.button(id,'80');
  assert.equal(f.key(middle,'ArrowRight').defaultPrevented,true);assert.equal(f.density.value,'120');assert.equal(f.focused(),f.button(id,'120'));assert.equal(f.focused().focusOptions.preventScroll,true);
  f.key(f.focused(),'Home');assert.equal(f.density.value,'40');f.key(f.focused(),'End');assert.equal(f.density.value,'120');
  f.key(f.focused(),'ArrowRight');assert.equal(f.density.value,'40');
  const count=f.changes.length;assert.equal(f.key(f.focused(),'Enter').defaultPrevented,false);assert.equal(f.key(f.focused(),' ').defaultPrevented,false);assert.equal(f.changes.length,count);
  f.density.options[1].disabled=true;f.state('all','40');f.key(f.button(id,'40'),'ArrowRight');assert.equal(f.density.value,'120');
});

test('unavailable observer keeps native fallback visible and missing select does not hide its label',()=>{
  const unavailable=setup({observerAvailable:false});assert.equal(unavailable.mode.parentElement.hidden,false);assert.equal(unavailable.density.parentElement.hidden,false);assert.equal(unavailable.toolbar.children.length,2);
  const partial=setup({missingMode:true});assert.equal(partial.mode.parentElement.hidden,false);assert.equal(partial.groupFor('network-view-mode'),undefined);assert.ok(partial.groupFor('network-edge-limit'));
});

test('back-forward cache retains observation and pageshow resynchronizes stored selection',()=>{
  const f=setup();f.events.get('pagehide')({persisted:true});assert.notEqual(f.observers[0].disconnected,true);
  f.mode.value='neighborhood';f.density.value='40';f.events.get('pageshow')();assert.equal(f.button('network-view-mode','neighborhood').getAttribute('aria-pressed'),'true');assert.equal(f.button('network-edge-limit','40').getAttribute('aria-pressed'),'true');
  f.events.get('pagehide')({persisted:false});assert.equal(f.observers[0].disconnected,true);
});
