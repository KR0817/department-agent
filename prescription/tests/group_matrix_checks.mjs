import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const html=fs.readFileSync(process.argv[2],'utf8');
function setup(){
  const elements=new Map(),events=new Map(),stack=[];let cursor=-1,focused=null;
  const unescape=value=>value.replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&amp;/g,'&');
  const element=id=>{
    if(!elements.has(id)){
      let markup='',buttons=[];
      elements.set(id,{id,textContent:'',hidden:false,disabled:false,value:'',checked:id==='fold-combos',dataset:{},listeners:{},attributes:{},
        get innerHTML(){return markup},set innerHTML(value){markup=value;buttons=[...value.matchAll(/<button\b[^>]*data-group-choice="([^"]*)"[^>]*>/g)].map(match=>({dataset:{groupChoice:unescape(match[1])},focus(options){focused=this;this.focusOptions=options},scrollIntoView(options){this.scrollOptions=options},closest(){return this}}))},
        querySelectorAll(selector){return selector==='[data-group-choice]'?buttons:[]},contains(button){return buttons.includes(button)},
        get options(){return [...this.innerHTML.matchAll(/<option[^>]*value="([^"]*)"[^>]*>(.*?)<\/option>/g)].map(match=>({value:match[1],textContent:match[2]}))},
        addEventListener(type,fn){const previous=this.listeners[type];this.listeners[type]=event=>{previous?.(event);fn(event)}},setAttribute(name,value){this.attributes[name]=String(value)},getAttribute(name){return this.attributes[name]??null},focus(options){focused=this;this.focusOptions=options},scrollIntoView(options){this.scrollOptions=options}});
    }
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
  const document={getElementById:element,title:'',body:{appendChild(){}},addEventListener(type,fn){events.set('document-'+type,fn)},createElement:()=>({click(){},remove(){}}),querySelectorAll:selector=>({'.annual-btn':annual,'.filter-btn[data-size]':sizes}[selector]||[])};
  const context=vm.createContext({document,location,history,URL,URLSearchParams,Blob,setTimeout:fn=>fn(),scrollTo(){},addEventListener:(type,fn)=>events.set(type,fn)});
  vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
  for(const id of ['followup-ui-script','group-matrix-script'])vm.runInContext(html.match(new RegExp('<script id="'+id+'">([\\s\\S]*?)</script>'))[1],context);
  const click=(code,id='group-matrix-chart')=>{const target=element(id),button=target.querySelectorAll('[data-group-choice]').find(button=>button.dataset.groupChoice===code);assert.ok(button);target.listeners.click({target:button})};
  return {element,events,history,click,focused:()=>focused,run:code=>vm.runInContext(code,context)};
}

test('matrix uses only disclosed exact rows and keeps patient and visit denominators unchanged',()=>{
  const f=setup();f.run('globalThis.originalData=JSON.stringify(data);render()');
  const chart=f.element('group-matrix-chart').innerHTML,table=f.element('group-matrix-table').innerHTML;
  assert.deepEqual(f.element('group-matrix-chart').querySelectorAll('[data-group-choice]').map(button=>button.dataset.groupChoice),['ra','sjd','ra__sjd','ra__as']);
  assert.equal((chart.match(/data-member="yes"/g)||[]).length,6);assert.equal((chart.match(/data-member="no"/g)||[]).length,6);
  assert.match(chart,/>40<\/strong>/);assert.match(chart,/>20<\/strong>/);assert.match(table,/<td>40<\/td><td>100<\/td>/);
  assert.doesNotMatch(chart,/sjd__as|ra__sjd__as/);assert.doesNotMatch(table,/合计|总计/);assert.equal(f.run('JSON.stringify(data)===originalData'),true);
});

test('column and table activation use original group history and preserve the strict cohort',()=>{
  const f=setup();f.run("strictGroup='ra_strict';groupFilter='single';document.getElementById('group-filter').value='single';render()");
  f.click('ra__sjd');assert.equal(f.run('selected'),'ra__sjd');assert.equal(f.run('groupFilter'),'all');assert.equal(f.run('strictGroup'),'ra_strict');
  assert.equal(f.element('followup-group').value,'ra__sjd');assert.match(f.element('followup-scope').textContent,/类风湿.*干燥/);
  assert.equal(f.focused().dataset.groupChoice,'ra__sjd');assert.equal(f.focused().focusOptions.preventScroll,true);
  f.click('sjd','group-matrix-table');assert.equal(f.run('selected'),'sjd');assert.match(f.element('group-matrix-scope').textContent,/当前选择：干燥/);
  f.history.back();assert.equal(f.run('selected'),'ra__sjd');assert.equal(f.element('followup-group').value,'ra__sjd');
  f.history.forward();assert.equal(f.run('selected'),'sjd');assert.equal(f.run('strictGroup'),'ra_strict');
});

test('source one-group reset and browser history never mix released rows',()=>{
  const f=setup();f.click('ra__as');f.run("switchAnalysisSource('supplement')");
  assert.equal(f.element('group-matrix-chart').querySelectorAll('[data-group-choice]').length,1);assert.match(f.element('group-matrix-chart').innerHTML,/data-group-choice="as"/);
  assert.doesNotMatch(f.element('group-matrix-chart').innerHTML,/data-group-choice="ra/);assert.match(f.element('group-matrix-scope').textContent,/补充门诊导出/);
  f.history.back();assert.equal(f.run('selected'),'ra__as');assert.equal(f.element('group-matrix-chart').querySelectorAll('[data-group-choice]').length,4);
  f.run('resetDashboardView()');assert.equal(f.run('selected'),'ra');assert.match(f.element('group-matrix-scope').textContent,/当前选择：类风湿关节炎/);
  f.history.back();assert.equal(f.run('selected'),'ra__as');
});

test('zero suppressed missing and conflicting membership retain distinct visible states',()=>{
  const f=setup();f.run("data.groups[0].patients='0';data.groups[0].visits='';data.groups[1].patients='';data.groups[2].disease_count='3';data.summaries.push({...data.summaries[3],visits:'999'});render()");
  const chart=f.element('group-matrix-chart').innerHTML,table=f.element('group-matrix-table').innerHTML;
  assert.match(chart,/>0<\/strong>/);assert.match(chart,/height:0%/);assert.match(chart,/>未公开<\/strong>/);assert.match(chart,/data-member="unknown"/);
  assert.match(table,/<td>0<\/td><td>未公开<\/td>/);assert.doesNotMatch(table,/>999</);assert.match(table,/成员定义未提供/);
  f.run("data.groups[3].label='Conflicting RA + Ankylosing spondylitis';render()");
  assert.match(f.element('group-matrix-chart').innerHTML,/data-member="unknown"/);
});

test('unknown group definitions do not manufacture membership or a numeric count',()=>{
  const f=setup();f.run("data.groups=[{code:'unknown',label:'Undefined exact group',patients:'<10'},{code:'blank',label:'',patients:null,disease_count:'1'}];data.summaries=[];selected='unknown';render()");
  const chart=f.element('group-matrix-chart').innerHTML,table=f.element('group-matrix-table').innerHTML;
  assert.equal(f.element('group-matrix-chart').querySelectorAll('[data-group-choice]').length,2);
  assert.doesNotMatch(chart,/data-member="yes"|class="group-matrix-bar"/);assert.match(chart,/成员定义/);assert.match(chart,/未提供/);
  assert.doesNotMatch(table,/<td>0<\/td>/);assert.match(table,/未公开/);
});

test('malicious and long labels are escaped without treating their text as a selector',()=>{
  const f=setup();f.run(`data.groups=[{code:'x"><img src=x>',label:'Long <unsafe&"> '+ 'word '.repeat(20),patients:'10',disease_count:'1'}];data.summaries=[];selected=data.groups[0].code;render()`);
  const chart=f.element('group-matrix-chart').innerHTML,table=f.element('group-matrix-table').innerHTML;
  assert.match(chart,/&lt;unsafe&amp;&quot;&gt;/);assert.match(chart,/data-group-choice="x&quot;&gt;&lt;img src=x&gt;"/);
  assert.doesNotMatch(chart,/<img|<unsafe/);assert.doesNotMatch(table,/<img|<unsafe/);
  f.click('x"><img src=x>');assert.equal(f.run('selected'),'x"><img src=x>');assert.equal(f.focused().dataset.groupChoice,'x"><img src=x>');
});

test('keyboard moves focus without changing the selected group until native activation',()=>{
  const f=setup(),chart=f.element('group-matrix-chart'),buttons=chart.querySelectorAll('[data-group-choice]');let prevented=false;
  chart.listeners.keydown({key:'ArrowRight',target:buttons[0],preventDefault(){prevented=true}});assert.equal(prevented,true);assert.equal(f.focused(),buttons[1]);assert.equal(f.run('selected'),'ra');
  chart.listeners.keydown({key:'End',target:buttons[1],preventDefault(){}});assert.equal(f.focused(),buttons.at(-1));
  chart.listeners.keydown({key:'Home',target:buttons.at(-1),preventDefault(){}});assert.equal(f.focused(),buttons[0]);
  f.click('ra__sjd');assert.equal(f.run('selected'),'ra__sjd');
});

test('empty and nonclinical sources do not retain a previous source matrix',()=>{
  const f=setup();f.run('data.groups=[];selected="";render()');
  assert.equal(f.element('group-matrix-scroll').hidden,true);assert.equal(f.element('group-matrix-table-details').hidden,true);assert.equal(f.element('group-matrix-empty').hidden,false);assert.equal(f.element('group-matrix-chart').innerHTML,'');assert.equal(f.element('group-matrix-table').innerHTML,'');
  f.run('data.clinicalMode=false;render()');assert.equal(f.element('group-matrix-lab').hidden,true);
});
