"""Synthetic checks for the unified shell and real intake controller paths."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from mingyirx.case_import import prepare_import, recognize_text
from mingyirx.dashboard_clinical import CSS, JS, render_clinical_workspace


def teaching_sidecar():
    anchors = []
    for index, (source, group, support_patients, patients, support) in enumerate([
        ("primary", "ra_strict", "10", "40", "0.2500"),
        ("primary", "sjd_strict", "0", "40", "0"),
        ("primary", "as_strict", "12", "48", "0.25"),
        ("primary", "ra_strict__sjd_strict", "14", "56", "0.250000"),
        ("supplement", "as_strict", "16", "64", "0.25"),
    ]):
        anchors.append({
            "case_id": f"SIM_CASE_{index}", "source": source, "group": group,
            "table": "combinations", "row_index": index, "row_sha256": "b" * 64,
            "source_payload_sha256": "a" * 64,
            "retained_original_fields": "Entire aggregate row and exact medicine labels",
            "simulated_fields": ["visits"],
            "row": {"combination": "Synthetic Herb A | Synthetic Herb B | Synthetic Herb C",
                    "combination_size": "3", "group": group,
                    "support_patients": support_patients, "patients": patients,
                    "support": support, "stratum": "all", "stratum_type": "overall"},
        })
    return {"schema_version": "mingyirx-aggregate-teaching-v1", "synthetic": True,
            "case_count": 5, "anchors": anchors, "source_payload_sha256": {"primary": "a" * 64},
            "individual_prescriptions_reconstructed": False, "clinical_validation": False}


def candidates():
    text = """subject_code: SYN-P1
episode_code: SYN-E1
physician_code: SYN-D1
visit_code: SYN-V1
date: 2026-01-01
sequence: 1
condition: Synthetic fatigue
symptoms: No dry mouth
tongue: Pale
pulse: Weak
syndrome: Synthetic syndrome
principle: Synthetic principle
prescription: HerbA 10 g; HerbB 12 g

subject_code: SYN-P1
episode_code: SYN-E1
physician_code: SYN-D1
visit_code: SYN-V2
date: 2026-01-08
sequence: 2
condition: Synthetic fatigue
symptoms: No dry mouth
tongue: Pale
pulse: Weak
syndrome: Synthetic syndrome
principle: Synthetic principle
prescription: HerbA 15 g; HerbC 9 g
"""
    return recognize_text(text, "a" * 64, "txt")


NODE_CHECKS = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
const html=fs.readFileSync(process.argv[2],'utf8'),fixture=JSON.parse(fs.readFileSync(process.argv[3],'utf8')),output=process.argv[4];
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup({protocol='http:',hostname='127.0.0.1',stateRecords=[],revision=0,synthetic=null,responder}={}){
 const elements=new Map(),requests=[],writes=[];
 class Node{
  constructor(id){this.id=id;this.textContent='';this.html='';this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.attributes={};this.listeners={};this.files=[];}
  set innerHTML(value){this.html=value;for(const match of value.matchAll(/<(?:input|textarea|span|select)[^>]*id="([^"]+)"[^>]*>/g)){const item=el(match[1]);item.disabled=/\bdisabled\b/.test(match[0]);}}
  get innerHTML(){return this.html;}
  addEventListener(type,fn){this.listeners[type]=fn;}
  setAttribute(key,value){if(key==='src')writes.push([this.id,value]);this.attributes[key]=String(value);}
  getAttribute(key){return this.attributes[key]??null;}
  focus(){this.focused=true;}
 }
 const el=id=>{if(!elements.has(id))elements.set(id,new Node(id));return elements.get(id);};
 for(const match of html.matchAll(/<[^>]+\bid="([^"]+)"[^>]*>/g)){const node=el(match[1]);node.disabled=/\bdisabled\b/.test(match[0]);node.hidden=/\bhidden\b/.test(match[0]);node.checked=/\bchecked\b/.test(match[0]);const src=match[0].match(/\bsrc="([^"]+)"/);if(src)node.attributes.src=src[1];}
 el('clinical-workspace-data').textContent=html.match(/<script id="clinical-workspace-data" type="application\/json">(.*?)<\/script>/s)[1];
 const fetch=async(url,options)=>{const body=options.body?JSON.parse(options.body):undefined;requests.push({url,options,body});let result=url==='/api/state'?{online:true,nonce:'synthetic-session-nonce',formats:['txt','csv'],records:stateRecords,revision,synthetic}:undefined;if(responder){const response=await responder(url,body,requests);if(response!==undefined)result=response;}if(result instanceof Error)throw result;if(result===undefined)throw new Error('Unexpected route');if(result.status)return {ok:false,json:async()=>result.body};return {ok:true,json:async()=>JSON.parse(JSON.stringify(result))};};
 const context=vm.createContext({document:{getElementById:el},location:{protocol,hostname},fetch,btoa:value=>Buffer.from(value,'binary').toString('base64'),Uint8Array});
 vm.runInContext(html.match(/<script id="clinical-workspace-controller">(.*?)<\/script>/s)[1],context);
 const fire=async(id,type,event={})=>{assert.ok(el(id).listeners[type],`${id}.${type}`);await el(id).listeners[type]({target:el(id),preventDefault(){},...event});await tick();};
 const click=id=>fire(id,'click');
 const edit=async(field,value)=>{el('record-'+field).value=value;await fire('record-'+field,'input');};
 const check=async(id,value=true)=>{el(id).checked=value;await fire(id,'change');};
 const file=(name,text,size)=>({name,size:size??Buffer.byteLength(text),arrayBuffer:async()=>{const bytes=Buffer.from(text);return bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.length);}});
 return {el,requests,writes,fire,click,edit,check,file};
}
const preview=()=>JSON.parse(JSON.stringify(fixture.preview));
const recognized=records=>({schema_version:'mingyirx-case-import-v1',records,warnings:[],extractor:{name:'synthetic-test'}});

test('static file mode makes no requests and persistent frames survive keyboard module switching',async()=>{
 const f=setup({protocol:'file:'});await tick();assert.equal(f.requests.length,0);assert.equal(f.el('service-note').hidden,false);assert.equal(f.el('intake-recognize').disabled,true);assert.equal(f.el('workspace-panel-aggregate').hidden,false);
 await f.click('workspace-tab-intake');await f.click('workspace-tab-cases');await f.click('workspace-tab-aggregate');assert.deepEqual(f.writes,[]);assert.equal(f.el('aggregate-frame').getAttribute('src'),'aggregate.html');assert.equal(f.el('cases-frame').getAttribute('src'),'inheritance.html');
 await f.fire('workspace-tab-aggregate','keydown',{key:'End'});assert.equal(f.el('workspace-tab-cases').focused,true);assert.equal(f.el('workspace-tab-cases').attributes['aria-selected'],'true');assert.equal(f.el('workspace-tab-aggregate').attributes.tabindex,'-1');
 await f.click('intake-recognize');await f.click('intake-preview');await f.click('intake-commit');assert.equal(f.requests.length,0);
 const remote=setup({hostname:'example.test'});await tick();assert.equal(remote.requests.length,0);assert.equal(remote.el('intake-file').disabled,true);
});

test('state loads current collection and sequential multi-file append sends nonce and whole collection',async()=>{
 let call=0;const f=setup({stateRecords:[fixture.records[0]],responder:(url)=>url==='/api/recognize'?recognized([{...fixture.records[1],record_id:'SYN-ADDED-'+(++call),visit_code:'SYN-V'+(call+1)}]):url==='/api/preview'?preview():undefined});await tick();assert.match(f.el('session-summary').textContent,/1 条/);assert.equal(f.el('intake-synthetic').checked,false);
 f.el('intake-file').files=[f.file('first.txt','first synthetic file'),f.file('second.txt','second synthetic file')];await f.click('intake-recognize');assert.match(f.el('session-summary').textContent,/3 条/);assert.equal(f.requests.filter(r=>r.url==='/api/recognize').length,2);assert.equal(Buffer.from(f.requests[1].body.data_base64,'base64').toString(),'first synthetic file');assert.equal(f.requests[1].options.headers['X-MingYiRx-Nonce'],'synthetic-session-nonce');assert.equal(f.requests[1].options.credentials,'same-origin');
 await f.click('intake-preview');const sent=f.requests.at(-1).body;assert.equal(sent.records.length,3);assert.equal(sent.synthetic,false);assert.deepEqual(sent.records[0],fixture.records[0]);
});

test('editing preserves missing and negated content, records human evidence, previews changes and commits',async()=>{
 const f=setup({stateRecords:fixture.records,responder:url=>url==='/api/preview'?preview():url==='/api/commit'?{gate:'PASS_WITH_WARNINGS',revision:1,counts:{cases:1},case_url:'/imported.html?revision=1'}:undefined});await tick();assert.equal(f.el('record-symptoms').value,'No dry mouth');assert.match(f.el('evidence-symptoms').textContent,/来源行/);
 await f.edit('symptoms','No dry mouth; synthetic fatigue recorded');await f.edit('pulse','');assert.match(f.el('evidence-symptoms').textContent,/人工已修改/);await f.check('intake-synthetic');await f.click('intake-preview');assert.match(f.el('preview-results').innerHTML,/HerbA|HerbB|HerbC/);assert.match(f.el('preview-results').innerHTML,/新增/);assert.match(f.el('preview-results').innerHTML,/去除/);assert.match(f.el('preview-results').innerHTML,/保留/);
 await f.click('intake-commit');assert.equal(f.requests.filter(r=>r.url==='/api/commit').length,0);await f.check('intake-deidentified');await f.check('intake-confirmed');assert.equal(f.el('intake-commit').disabled,false);await f.click('intake-commit');const body=f.requests.find(r=>r.url==='/api/commit').body;assert.equal(body.revision,0);assert.equal(body.synthetic,true);assert.equal(body.confirmed,true);assert.equal(body.deidentified,true);assert.equal(body.records[0].evidence.symptoms,'user-reviewed');assert.equal(body.records[0].pulse,'');assert.equal(f.el('cases-frame').getAttribute('src'),'/imported.html?revision=1');assert.equal(f.el('workspace-panel-cases').hidden,false);assert.equal(f.el('aggregate-frame').getAttribute('src'),'aggregate.html');fs.writeFileSync(output,JSON.stringify(body));
 await f.click('show-teaching');assert.equal(f.el('cases-frame').getAttribute('src'),'inheritance.html');await f.click('show-imported');assert.equal(f.el('cases-frame').getAttribute('src'),'/imported.html?revision=1');
});

test('any edit invalidates the preview and confirmation before a direct commit handler can run',async()=>{
 const f=setup({stateRecords:fixture.records,responder:url=>url==='/api/preview'?preview():undefined});await tick();await f.click('intake-preview');await f.check('intake-deidentified');await f.check('intake-confirmed');await f.edit('condition','Edited synthetic condition');assert.equal(f.el('intake-confirmed').checked,false);assert.equal(f.el('intake-commit').disabled,true);await f.check('intake-confirmed');await f.click('intake-commit');assert.equal(f.requests.filter(r=>r.url==='/api/commit').length,0);
});

test('revision conflict and recognition errors preserve existing edits and prior successful files',async()=>{
 let call=0;const f=setup({stateRecords:[fixture.records[0]],responder:url=>url==='/api/recognize'?(++call===1?recognized([fixture.records[1]]):{status:400,body:{error:'OCR_REQUIRED'}}):url==='/api/preview'?preview():url==='/api/commit'?{status:409,body:{error:'REVISION_CONFLICT'}}:undefined});await tick();await f.edit('symptoms','Preserved synthetic edit');f.el('intake-file').files=[f.file('good.txt','x'),f.file('scan.pdf','x')];await f.click('intake-recognize');assert.match(f.el('session-summary').textContent,/2 条/);assert.match(f.el('intake-status').textContent,/前序文件已追加/);assert.match(f.el('intake-status').textContent,/文本层/);await f.click('intake-preview');await f.check('intake-deidentified');await f.check('intake-confirmed');await f.click('intake-commit');assert.match(f.el('commit-status').textContent,/版本已变化/);f.el('record-select').value='0';await f.fire('record-select','change');assert.equal(f.el('record-symptoms').value,'Preserved synthetic edit');assert.equal(f.el('cases-frame').getAttribute('src'),'inheritance.html');
});

test('malicious preview text is escaped and server cannot redirect a frame externally',async()=>{
 const result=preview();result.pairs[0].case_id='<img src=x onerror=bad()>';result.medicine_labels=Object.fromEntries(Object.keys(result.medicine_labels).map(key=>[key,'<script>bad()</script>']));const f=setup({stateRecords:fixture.records,responder:url=>url==='/api/preview'?result:url==='/api/commit'?{gate:'PASS',revision:1,case_url:'https://example.test/steal'}:undefined});await tick();await f.click('intake-preview');assert.match(f.el('preview-results').innerHTML,/&lt;img/);assert.match(f.el('preview-results').innerHTML,/&lt;script/);assert.doesNotMatch(f.el('preview-results').innerHTML,/<img|<script/);await f.check('intake-deidentified');await f.check('intake-confirmed');await f.click('intake-commit');assert.match(f.el('commit-status').textContent,/地址不符合/);assert.equal(f.el('cases-frame').getAttribute('src'),'inheritance.html');
});

test('blocked preview, oversized files and unavailable service cannot enable commit',async()=>{
 const f=setup({stateRecords:fixture.records,responder:url=>url==='/api/preview'?{gate:'BLOCK',pairs:[],errors:[{code:'VISIT_CONFLICT',record:1,field:'visit_code'}],warnings:[],counts:{}}:undefined});await tick();await f.click('intake-preview');assert.match(f.el('preview-results').innerHTML,/冲突/);await f.check('intake-deidentified');await f.check('intake-confirmed');await f.click('intake-commit');assert.equal(f.requests.filter(r=>r.url==='/api/commit').length,0);f.el('intake-file').files=[f.file('large.txt','x',8*1024*1024+1)];await f.click('intake-recognize');assert.match(f.el('intake-status').textContent,/8 MiB/);assert.equal(f.requests.filter(r=>r.url==='/api/recognize').length,0);
 const offline=setup({responder:()=>new Error('offline')});await tick();assert.equal(offline.el('service-note').hidden,false);assert.equal(offline.el('intake-file').disabled,true);assert.equal(offline.el('service-state').textContent,'本地服务未连接');
});

test('reloading an existing session offers the current committed page without changing aggregate',async()=>{
 const f=setup({stateRecords:fixture.records,revision:3});await tick();assert.equal(f.el('cases-frame').getAttribute('src'),'/imported.html?revision=3');assert.equal(f.el('show-imported').disabled,false);assert.equal(f.el('workspace-panel-aggregate').hidden,false);assert.equal(f.el('aggregate-frame').getAttribute('src'),'aggregate.html');
});

test('saved collection mode is restored and retained through preview and commit',async()=>{
 for(const synthetic of [true,false]){
  const f=setup({stateRecords:fixture.records,revision:3,synthetic,responder:url=>url==='/api/preview'?preview():url==='/api/commit'?{gate:'PASS_WITH_WARNINGS',revision:4,case_url:'/imported.html?revision=4'}:undefined});await tick();assert.equal(f.el('intake-synthetic').checked,synthetic);assert.equal(f.el('intake-synthetic').disabled,true);assert.match(f.el('intake-mode-note').textContent,synthetic?/已保存为合成示例/:/已保存为真实脱敏材料/);
  await f.check('intake-synthetic',!synthetic);assert.equal(f.el('intake-synthetic').checked,synthetic);await f.click('intake-preview');assert.equal(f.requests.at(-1).body.synthetic,synthetic);await f.check('intake-deidentified');await f.check('intake-confirmed');await f.click('intake-commit');const body=f.requests.find(r=>r.url==='/api/commit').body;assert.equal(body.synthetic,synthetic);assert.equal(body.revision,3);assert.equal(f.el('cases-frame').getAttribute('src'),'/imported.html?revision=4');assert.equal(f.el('intake-synthetic').disabled,true);
 }
 const empty=setup();await tick();assert.equal(empty.el('intake-synthetic').checked,false);assert.equal(empty.el('intake-synthetic').disabled,false);
});

test('preview warnings use readable language, global positions are omitted and unknown codes are folded',async()=>{
 const result=preview();result.warnings=[{code:'DOSE_BASIS_AND_PREPARATION_UNKNOWN',record:1,field:'prescription'},{code:'SOURCE_HASHES_DECLARED_ONLY',record:0},{code:'SYNTHETIC_WORKFLOW_ONLY',record:0},{code:'UNCONFIRMED_ATTRIBUTION',record:0},{code:'FUTURE_DIAGNOSTIC',record:0}];const f=setup({stateRecords:fixture.records,responder:url=>url==='/api/preview'?result:undefined});await tick();await f.click('intake-preview');const markup=f.el('preview-results').innerHTML;assert.match(markup,/剂量基准和制备方式未提供/);assert.match(markup,/原文件尚待独立核验/);assert.match(markup,/来源或医师归属待人工审阅/);assert.match(markup,/记录 1/);assert.doesNotMatch(markup,/ · 记录 0|SOURCE_HASHES_DECLARED_ONLY|DOSE_BASIS_AND_PREPARATION_UNKNOWN/);assert.match(markup,/需要核对<details><summary>技术详情<\/summary><code>FUTURE_DIAGNOSTIC/);assert.match(markup,/输入记录/);assert.match(markup,/完全重复记录/);assert.doesNotMatch(markup,/input_records|duplicates/);
});

test('teaching anchors show five exact aggregate rows directly and retain the full hash sidecar',async()=>{
 const f=setup({protocol:'file:'});await tick();await f.click('workspace-tab-cases');const markup=f.el('teaching-anchor-table').innerHTML;assert.equal(f.el('teaching-provenance-panel').hidden,false);assert.equal((markup.match(/<tr>/g)||[]).length,6);assert.match(markup,/SIM_CASE_0/);assert.match(markup,/primary \/ ra_strict/);assert.match(markup,/supplement \/ as_strict/);assert.match(markup,/Synthetic Herb A \| Synthetic Herb B \| Synthetic Herb C/);assert.match(markup,/<td>10<\/td><td>40<\/td><td>0.2500<\/td>/);assert.match(markup,/<td>0<\/td><td>40<\/td><td>0<\/td>/);assert.match(markup,/<td>14<\/td><td>56<\/td><td>0.250000<\/td>/);assert.equal(JSON.parse(f.el('teaching-provenance').textContent).anchors[0].row_sha256,'b'.repeat(64));assert.match(html,/三味组合不是完整方/);assert.match(html,/<details><summary>完整溯源与哈希 JSON/);assert.deepEqual(f.writes,[]);
});
"""


class ClinicalDashboardTests(unittest.TestCase):
    def test_persistent_document_routes_and_offline_command(self):
        page = render_clinical_workspace(synthetic_preview=True)
        self.assertEqual(page.count('id="aggregate-frame"'), 1)
        self.assertEqual(page.count('id="cases-frame"'), 1)
        self.assertIn('src="aggregate.html"', page)
        self.assertIn('src="inheritance.html"', page)
        self.assertIn("python scripts/serve_clinical_workspace.py --site outputs/clinical_workspace_20261024_v1/site --state-dir work/clinical_sessions/session-001", page)
        self.assertNotRegex(JS, r"localStorage|sessionStorage|XMLHttpRequest|\beval\s*\(|new Function\s*\(")
        self.assertNotRegex(CSS, r"@import|url\(")
        self.assertNotRegex(page, r'<(?:script|iframe)[^>]+src="https?://')
        self.assertIn("max-width:600px", CSS)

    def test_provenance_is_canonical_escaped_data_and_never_a_script(self):
        provenance = {"description": "</script><img src=x> __JS__ &", "source": {"b": 2, "a": 1}}
        page = render_clinical_workspace(teaching_provenance=provenance)
        text = re.search(r'<script id="clinical-workspace-data" type="application/json">(.*?)</script>', page, re.S)[1]
        self.assertEqual(json.loads(text)["teaching_provenance"], provenance)
        self.assertNotIn("</script>", text)
        self.assertIn(r"\u003c", text)
        self.assertEqual(page, render_clinical_workspace(teaching_provenance={"source": {"a": 1, "b": 2}, "description": provenance["description"]}))
        self.assertNotIn("teaching-provenance.json", JS)

    def test_renderer_rejects_wrong_option_types(self):
        with self.assertRaises(ValueError):
            render_clinical_workspace(synthetic_preview="false")
        with self.assertRaises(ValueError):
            render_clinical_workspace(teaching_provenance=[])

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable")
    def test_actual_async_controller_and_core_roundtrip(self):
        recognized = candidates()
        self.assertEqual(len(recognized["records"]), 2)
        prepared = prepare_import(recognized["records"], synthetic=True)
        self.assertNotEqual(prepared["gate"], "BLOCK", prepared["errors"])
        preview = {key: value for key, value in prepared.items() if key != "bundle"}
        preview["medicine_labels"] = {row["code"]: row["label"] for row in prepared["bundle"]["vocabulary"]["medicines"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workspace.html").write_text(render_clinical_workspace(synthetic_preview=True, teaching_provenance=teaching_sidecar()), encoding="utf-8")
            (root / "fixture.json").write_text(json.dumps({"records": recognized["records"], "preview": preview}), encoding="utf-8")
            (root / "controller-checks.mjs").write_text(NODE_CHECKS, encoding="utf-8")
            result = subprocess.run(["node", str(root / "controller-checks.mjs"), str(root / "workspace.html"), str(root / "fixture.json"), str(root / "committed.json")], capture_output=True, text=True, encoding="utf-8", timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            committed = json.loads((root / "committed.json").read_text(encoding="utf-8"))
            validated = prepare_import(committed["records"], synthetic=committed["synthetic"])
            self.assertNotEqual(validated["gate"], "BLOCK", validated["errors"])
            self.assertEqual(committed["records"][0]["evidence"]["symptoms"], "user-reviewed")


if __name__ == "__main__":
    unittest.main()
