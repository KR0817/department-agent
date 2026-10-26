import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function setup(path) {
  const html = fs.readFileSync(path, 'utf8');
  const elements = new Map(), downloads = [], events = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { innerHTML:'', textContent:'', hidden:false, disabled:false, value:'', dataset:{}, attributes:{}, listeners:{},
      get options() { return [...this.innerHTML.matchAll(/<option[^>]*value="([^"]*)"[^>]*>(.*?)<\/option>/g)].map(match=>({value:match[1], textContent:match[2]})); },
      addEventListener(type, fn) { this.listeners[type] = fn; },
      setAttribute(key, value) { this.attributes[key]=value; }, focus() {}, scrollIntoView() {} });
    return elements.get(id);
  };
  for (const id of ['dashboard-data', 'supplement-data']) element(id).textContent=html.match(new RegExp('<script id="'+id+'" type="application/json">(.*?)</script>', 's'))[1];
  element('analysis-source').innerHTML='<option value="primary">Primary</option><option value="supplement">Supplement</option>';
  const annual=['prevalence','addition','removal'].map(value=>Object.assign(element('annual-'+value),{dataset:{annual:value}}));
  const sizes=['all','2','3'].map(value=>Object.assign(element('size-'+value),{dataset:{size:value}}));
  const location={href:'http://127.0.0.1:18785/index.html',search:''};
  const history={pushState(_state,_title,url){location.href=String(url);location.search=url.search;}};
  class TestURL extends URL { static createObjectURL(blob) { downloads.push({blob});return 'blob:synthetic'; } static revokeObjectURL() {} }
  const document={getElementById:element,title:'',body:{appendChild(){}},
    createElement:()=>({click(){downloads.at(-1).name=this.download;},remove(){}}),
    querySelectorAll:selector=>({'.annual-btn':annual,'.filter-btn[data-size]':sizes}[selector]||[])};
  const context=vm.createContext({document,location,history,URL:TestURL,URLSearchParams,Blob,setTimeout:fn=>fn(),addEventListener:(name,fn)=>events.set(name,fn)});
  const source=html.split('<script>')[1].split('</script>')[0];
  vm.runInContext(source,context);
  return {element,downloads,events,location,document,run:code=>vm.runInContext(code,context)};
}

const ui=setup(process.argv[2]);
assert.equal(ui.run('activeSource'),'supplement');
assert.match(ui.element('stats').innerHTML,/>20</);
assert.match(ui.element('annual-chart').innerHTML,/2026/);
ui.run("query='old';researchItem='old';annualItem='old';networkItem='old';stratumType='sex';stratum='female';comboSize='3';groupFilter='comorbidity'");
ui.element('comparison-export-status').textContent='old comparison export';
ui.element('reference-age').value='52';ui.element('reference-sex').value='female';ui.element('export-status').textContent='old success';
ui.element('analysis-source').listeners.change({target:{value:'primary'}});
assert.equal(ui.run('activeSource'),'primary');
assert.match(ui.element('stats').innerHTML,/>40</);
assert.match(ui.element('annual-chart').innerHTML,/2020/);
assert.doesNotMatch(ui.element('annual-chart').innerHTML,/2026/);
assert.equal(ui.run('data===sourceData.primary && research===data.research && provenance===data.provenance'),true);
assert.equal(ui.element('reference-age').value,'');assert.equal(ui.element('reference-sex').value,'');
assert.equal(ui.element('export-status').textContent,'');assert.equal(ui.run('query'),'');
assert.equal(ui.element('comparison-export-status').textContent,'');assert.equal(ui.run('groupFilter'),'all');
assert.equal(ui.element('reference-section').hidden,true);
for(const id of ['strict-research','strict-nav-link','combination-panel','demographics','quality-dose-panel'])assert.equal(ui.element(id).hidden,true,id);
assert.equal(ui.element('structure-grid').className,'content-grid protected');
assert.match(ui.element('presentation-policy').innerHTML,/<details>/);
assert.match(ui.run("doseDetail({dose_patients:'20',most_common_dose_values_g:'10;15',most_common_dose_patients:'10',most_common_dose_fraction:'.5',most_common_dose_tied:'True'})"),/10\/20/);
ui.element('export-item').listeners.click();
assert.match(await ui.downloads[0].blob.text(),/primary/);
assert.match(await ui.downloads[0].blob.text(),/conservative-v1/);
ui.element('export-provenance').listeners.click();
const provenance=JSON.parse(await ui.downloads[1].blob.text());
assert.equal(provenance.source_identity.key,'primary');assert.equal(provenance.privacy.profile,'conservative-v1');
ui.element('export-annual-svg').listeners.click();
const svg=await ui.downloads[2].blob.text();
assert.match(svg,/source_identity/);assert.match(svg,/conservative-v1/);assert.doesNotMatch(svg,/2026/);
ui.location.search='?source=supplement';ui.events.get('popstate')();assert.equal(ui.run('activeSource'),'supplement');
const empty=setup(process.argv[3]);
assert.equal(empty.element('dashboard-empty').hidden,false);
assert.equal(empty.element('export-item').disabled,true);assert.equal(empty.element('export-annual-svg').disabled,true);
empty.element('analysis-source').listeners.change({target:{value:'primary'}});
assert.equal(empty.element('dashboard-empty').hidden,true);
assert.match(empty.element('stats').innerHTML,/>40</);
console.log('Source state, projected exports, empty source and browser history checks passed.');
