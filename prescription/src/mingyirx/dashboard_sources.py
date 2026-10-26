"""Switch complete outpatient dashboards without merging their denominators."""
import json
from pathlib import Path
import re

from .dashboard import DashboardError, HTML_TEMPLATE
from .dashboard_privacy import PROFILE, SHOWCASE_PROFILE, protect_payload


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("&", "\\u0026")


def build_source_dashboard(primary: Path, supplement: Path, output: Path, *,
                           privacy_policy: str | None = None, min_public_n: int = 10,
                           source_metadata: dict | None = None,
                           default_source: str = "supplement",
                           refresh_template: bool = False) -> dict:
    """Build one local source selector; protected multisource demos are synthetic."""
    if privacy_policy not in (None, PROFILE, SHOWCASE_PROFILE):
        raise DashboardError("Unsupported presentation privacy policy")
    if default_source not in ("primary", "supplement"):
        raise DashboardError("Unknown default source")
    pages = [path.read_text(encoding="utf-8") for path in (primary, supplement)]
    pattern = r'<script id="dashboard-data" type="application/json">(.*?)</script>'
    payloads = []
    for key, page in zip(("primary", "supplement"), pages):
        match = re.search(pattern, page, re.S)
        if not match or 'id="analysis-source"' in page:
            raise DashboardError("Input must be a single-source MingYiRx dashboard")
        try:
            payload = json.loads(match[1])
        except ValueError as error:
            raise DashboardError("Invalid source dashboard payload") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("groups"), list):
            raise DashboardError("Source groups must be a list")
        if privacy_policy is not None:
            if payload.get("provenance", {}).get("synthetic_mode") is not True:
                raise DashboardError("Protected multisource dashboards require explicitly synthetic sources")
            payload = protect_payload(payload, min_public_n, profile=privacy_policy)
        metadata = (source_metadata or {}).get(key, {})
        if not isinstance(metadata, dict) or any(not isinstance(metadata.get(field, ""), str) for field in ("title", "scope")):
            raise DashboardError("Source title and scope must be strings")
        payload["source_identity"] = {"key": key, "title": metadata.get("title") or ("主要门诊导出" if key == "primary" else "补充门诊导出"), "scope": metadata.get("scope", "来源内独立描述；跨来源患者归并未建立。")}
        payloads.append(payload)
    # Protected output never inherits unfiltered legacy HTML tables or JSON.
    page = HTML_TEMPLATE.replace("__TITLE__", "MingYiRx · 门诊来源工作台") if privacy_policy or refresh_template else pages[0]
    anchor = "const data=JSON.parse(document.getElementById('dashboard-data').textContent);"
    if anchor not in page:
        raise DashboardError("Unsupported dashboard template")
    if privacy_policy or refresh_template:
        page = page.replace("__PAYLOAD__", _json(payloads[0]))
    else:
        page = re.sub(pattern, lambda _: '<script id="dashboard-data" type="application/json">'+_json(payloads[0])+'</script>', page, count=1, flags=re.S)
    page = page.replace('<script id="dashboard-data"', '<script id="supplement-data" type="application/json">'+_json(payloads[1])+'</script><script id="dashboard-data"', 1)
    page = page.replace(anchor, "const sourceData={primary:JSON.parse(document.getElementById('dashboard-data').textContent),supplement:JSON.parse(document.getElementById('supplement-data').textContent)};const defaultSource="+_json(default_source)+";let activeSource=new URLSearchParams(location.search).get('source');if(!Object.hasOwn(sourceData,activeSource))activeSource=defaultSource;let data=sourceData[activeSource];")
    page = page.replace("const research = data.research || {};", "let research = data.research || {};").replace("const provenance = data.provenance || {};", "let provenance = data.provenance || {};")
    control = '<section class="source-panel"><h2 id="source-title"></h2><label for="analysis-source">门诊数据来源</label><select id="analysis-source"><option value="primary">主要门诊导出</option><option value="supplement">补充门诊导出</option></select><p id="active-source-note" role="status" aria-live="polite"></p><p>来源内编号、年度、药味、加减和导出随来源切换；不同来源不相加，切换不代表完成患者去重。</p></section>'
    page = page.replace('<main class="main">', '<main class="main">'+control, 1)
    script = r'''
function updateSourceNote(){
  const identity=data.source_identity;document.getElementById('analysis-source').value=activeSource;
  for(const option of document.getElementById('analysis-source').options)option.textContent=sourceData[option.value].source_identity.title;
  document.getElementById('source-title').textContent=identity.title;document.title=identity.title+' · MingYiRx';
  const groups=data.clinicalMode?`${data.groups.filter(row=>number(row.disease_count)===1).length} 个单病组 / ${data.groups.filter(row=>number(row.disease_count)>1).length} 个共病组；各组人数见下方概览`:data.groups.map(row=>`${groupLabel(row.label)} ${publicValue(row.patients)} 人`).join('；');
  const years=[...new Set((data.yearSummaries||[]).map(row=>String(row.year)))].sort();
  document.getElementById('active-source-note').textContent=`${identity.scope} 来源内公开分母：${groups||'无公开分析组'}。公开年度：${years.length?years[0]+'—'+years.at(-1):'无公开年度'}。`;
}
function switchAnalysisSource(key,push=true){
  if(!Object.hasOwn(sourceData,key))return;
  if(push&&typeof recordViewState==='function')recordViewState(true);
  activeSource=key;data=sourceData[key];research=data.research||{};provenance=data.provenance||{};
  selected=data.groups.some(row=>row.code===selected)?selected:(data.groups[0]?.code||'');
  if(typeof resetDashboardView==='function')resetDashboardView(false,false);
  else{
    stratumType='overall';stratum='all';comparisonKey='';annualItem='';annualMetric='prevalence';researchItem='';strictGroup=selected;networkItem='';query='';comboSize='all';limit=12;
    if(typeof groupFilter!=='undefined'){groupFilter='all';document.getElementById('group-filter').value='all'}
    document.getElementById('search').value='';document.getElementById('limit').value='12';
    document.querySelectorAll('.filter-btn[data-size]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.size==='all')));
    const fold=document.getElementById('fold-combos');if(fold)fold.checked=true;
  }
  document.getElementById('reference-diagnosis').innerHTML=data.groups.map(group=>`<option value="${escapeHtml(group.code)}">${escapeHtml(groupLabel(group.label))}</option>`).join('');
  document.getElementById('reference-age').value='';document.getElementById('reference-sex').value='';populateReferenceSex();renderReferenceResult();
  for(const id of ['export-status','annual-export-status','network-export-status','comparison-export-status'])document.getElementById(id).textContent='';
  render();renderStrictResearch();renderResearchQuality();updateSourceNote();
  if(push){if(typeof recordViewState==='function')recordViewState();else{const url=new URL(location.href);url.searchParams.set('source',key);history.pushState({source:key},'',url)}}
}
document.getElementById('analysis-source').addEventListener('change',event=>switchAnalysisSource(event.target.value));
if(typeof applyViewState!=='function')addEventListener('popstate',()=>switchAnalysisSource(new URLSearchParams(location.search).get('source')||defaultSource,false));
updateSourceNote();
if(typeof recordViewState==='function')recordViewState(true);
'''
    initialization = "initializeResearch();initializeReference();render();"
    if initialization not in page:
        raise DashboardError("Source-switch initialization is unavailable")
    page = page.replace(initialization, initialization+script, 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return {"gate": "PASS", "sources": 2, "default_source": default_source,
            "privacy_profile": privacy_policy, "patient_identity_merge": False,
            "patient_level_data_added": False}
