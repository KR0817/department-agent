"""Public research projections and embedded workbench assets.

The restricted manifest is a verification input, never a serialization source.
Optional tables retain their original strict-cohort scope and suppression blanks.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


RESEARCH_TABLES = {
    "usage": ("item_usage_totals.csv", {"item_name", "total_usage_visits"}),
    "matched": ("matched_reference_summary.csv", set("group patients matched_transitions observed_patient_median_jaccard observed_bootstrap_ci95_low observed_bootstrap_ci95_high matched_between_patient_median_jaccard matched_between_bootstrap_ci95_low matched_between_bootstrap_ci95_high within_minus_between_median within_minus_between_bootstrap_ci95_low within_minus_between_bootstrap_ci95_high empirical_one_sided_bh_fdr".split())),
    "sensitivity": ("matched_reference_sensitivity.csv", set("analysis group patients transitions observed_patient_median_jaccard matched_between_patient_median_jaccard within_minus_between_median within_minus_between_bootstrap_ci95_low within_minus_between_bootstrap_ci95_high".split())),
    "modes": ("transition_mode_summary.csv", set("group mode dose_resolved_patients dose_resolved_transitions mean_patient_proportion".split())),
    "normalization": ("item_normalization_audit.csv", set("dictionary_version dictionary_entries dictionary_sha256".split())),
    "doseAudit": ("dose_conflict_audit.csv", set("group patients visits patients_with_conflict visits_with_conflict visit_item_conflicts patients_with_conflict_pct visits_with_conflict_pct".split())),
    "nodes": ("network_nodes.csv", set("group group_label patients node_prevalence_threshold edge_cosine_threshold item_name exposed_patients prevalence bootstrap_core_selection_probability degree".split())),
    "edges": ("network_edges.csv", set("group patients node_prevalence_threshold edge_cosine_threshold item_1 item_2 cooccurrence_patients support cosine_similarity lift".split())),
    "thresholds": ("network_threshold_sensitivity.csv", set("group node_prevalence_threshold edge_cosine_threshold stable_nodes edges density connected_components largest_component_fraction node_retention_vs_primary edge_retention_vs_primary primary_setting".split())),
}


def public_provenance(input_dir: Path, source_tables: list[str]) -> dict[str, object]:
    """Verify exact source bytes and return a fixed, path-free public contract."""
    hashes = {name: hashlib.sha256((input_dir / name).read_bytes()).hexdigest()
              for name in sorted(set(source_tables))}
    result = {"project_id": None, "dataset_id": None, "cohort_version": None,
              "analysis_version": None, "min_public_n": None, "synthetic_mode": None,
              "recorded_run_gate": None, "config_sha256": None,
              "artifact_check": "NOT_ASSESSED", "source_sha256": hashes}
    path = input_dir / "run_manifest.json"
    if not path.is_file():
        return result
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError
        artifacts = manifest.get("artifacts", {})
        config = manifest.get("configuration", {})
        if not isinstance(artifacts, dict) or not isinstance(config, dict):
            raise ValueError
    except (ValueError, OSError) as error:
        raise ValueError("Invalid research manifest; no manifest content disclosed") from error
    checked = 0
    for name, digest in hashes.items():
        expected = artifacts.get(name)
        if expected is not None:
            if expected != digest:
                raise ValueError(f"Aggregate hash mismatch: {name}")
            checked += 1
    result["artifact_check"] = "PASS" if checked == len(hashes) else "PARTIAL" if checked else "NOT_ASSESSED"
    for target, key in [("project_id", "project_id"), ("dataset_id", "dataset_id"),
                        ("cohort_version", "cohort_version"), ("analysis_version", "mingyirx_version")]:
        value = manifest.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
            result[target] = value
    if manifest.get("gate") == "BLOCK":
        raise ValueError("Research manifest records BLOCK; dashboard generation refused")
    if manifest.get("gate") in ("PASS", "PASS_WITH_WARNINGS"):
        result["recorded_run_gate"] = manifest["gate"]
    threshold = config.get("min_public_n")
    if type(threshold) is int and threshold > 0:
        result["min_public_n"] = threshold
    if type(config.get("synthetic_mode")) is bool:
        result["synthetic_mode"] = config["synthetic_mode"]
    if type(threshold) is int and threshold < 10 and config.get("synthetic_mode") is not True:
        raise ValueError("Public threshold below 10 requires an explicit synthetic run")
    digest = config.get("sha256")
    if isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest):
        result["config_sha256"] = digest
    return result


RESEARCH_CSS = """
.research-nav{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0}.research-nav a{color:var(--pine);padding:7px 11px;border:1px solid var(--rule);text-decoration:none;font-size:12px;background:var(--paper)}
.research-panel{scroll-margin-top:60px}.research-panel p{font-size:12px;line-height:1.8;color:var(--muted)}.research-panel label{display:grid;gap:6px;font-size:12px;min-width:0}.research-panel select{max-width:100%}
.research-table-wrap{max-width:100%;overflow:auto;margin:14px 0;border:1px solid var(--rule)}.research-table{width:100%;border-collapse:collapse;font-size:12px;background:var(--paper)}.research-table th,.research-table td{padding:12px;text-align:left;border-bottom:1px solid var(--rule);vertical-align:top;min-width:95px}.research-table th{white-space:nowrap;background:var(--pine-soft)}.research-table td small{display:block;margin-top:5px;color:var(--muted);line-height:1.6}.research-table tr:target{background:var(--blue-soft);scroll-margin-top:60px}
.identity-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.identity-card{padding:12px;border:1px solid var(--rule);background:var(--paper);overflow-wrap:anywhere}.identity-card span{display:block;font-size:11px;color:var(--muted);margin-bottom:6px}.identity-card b{font-size:12px}.table-scroll-hint{display:none}#item-comparison table{min-width:650px}.research-panel h4{margin:24px 0 10px;font-size:15px}.research-panel details{margin-top:18px}.research-panel summary{cursor:pointer;font-size:13px}.research-panel .empty{padding:18px}
.research-meter{height:5px;background:var(--rule);min-width:100px;margin-top:6px}.research-meter i{display:block;height:100%;background:var(--pine)}.network-view{overflow:auto;background:var(--paper);border:1px solid var(--rule)}.network-view svg{display:block;min-width:620px;width:100%;height:auto}.network-view{border-radius:20px;margin:16px 0;background:#edf4f3}.network-associate:hover rect,.network-associate:focus rect{stroke:#28695f;stroke-width:2;fill:#f5faf8}.network-associate:focus{outline:none}.network-view a:focus circle{stroke:var(--blue);stroke-width:4}.research-status{min-height:20px;font-size:12px;color:var(--pine)}
.drug-focus{font:inherit;font-weight:600;color:var(--pine);background:transparent;border:0;border-bottom:1px dotted currentColor;padding:3px 1px;text-align:left;cursor:pointer;overflow-wrap:anywhere}.drug-focus:hover{background:var(--pine-soft)}.drug-focus:focus-visible,.filter-btn:focus-visible,.overview-group:focus-visible{outline:3px solid rgba(45,95,136,.4);outline-offset:3px}.view-controls{margin:10px 0 18px}.view-controls .search-status{flex:1;min-width:210px;margin:0}.focus-state{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:12px;background:var(--pine-soft);border:1px solid var(--rule)}.focus-state p{flex:1;margin:0;min-width:160px}.focus-links{display:flex;flex-wrap:wrap;gap:10px}.focus-links button{max-width:100%;white-space:normal;text-align:left}.research-table .group-focus{font:inherit;background:none;border:0;color:var(--pine);padding:0;text-decoration:underline;cursor:pointer}#item-research{scroll-margin-top:80px}#item-research:focus{outline:0}.comparison-count{font-size:12px;color:var(--muted)}
@media(max-width:600px){.research-panel .table-scroll-hint{display:block;margin:8px 0 0;font-size:11px}.identity-grid{grid-template-columns:1fr}.research-panel .controls{align-items:stretch}.research-panel .controls label{width:100%}.research-panel .section-head{display:block}}
"""

RESEARCH_HTML = """
<nav class="research-nav" aria-label="研究工作区导航"><a href="#item-research">单药研究</a><a id="strict-nav-link" href="#strict-research">纵向与网络</a><a href="#research-quality">质量与版本</a></nav>
<section class="section research-panel" id="item-research" tabindex="-1">
  <div class="section-head"><div><h3>单药研究</h3><p id="item-scope"></p></div><div class="controls">
    <p id="research-order-note">药味选项按全分析人群的总用次数降序排列：同一规范药味每次合格就诊计 1 次，包含首诊和复诊；未公开次数的药味排在末尾。</p><label>研究药味<select id="research-item"></select></label>
    <button class="filter-btn" type="button" id="export-item">导出当前药味 CSV</button>
    <button class="filter-btn" type="button" id="export-provenance">导出复现记录 JSON</button>
  </div></div>
  <div class="focus-state"><p id="focused-drug-status" role="status" aria-live="polite"></p><button class="filter-btn" type="button" id="clear-drug-focus">清除药味聚焦</button></div><p id="item-availability"></p>
  <p>首诊覆盖以首诊患者为分母；加减发生率以复诊患者为分母。各疾病并列展示采用同一 0–100% 刻度，仅作描述性比较。未公开不等于零；克数仅为历史记录。</p>
  <div id="item-comparison"></div><p class="research-status" id="export-status" role="status" aria-live="polite"></p>
  <div class="focus-links"><button class="filter-btn" type="button" id="item-to-annual">在当前组年度趋势中查看此药</button><button class="filter-btn" type="button" id="item-to-network">在严格单病网络中查看此药</button></div>
</section>
<section class="section research-panel" id="strict-research">
  <div class="section-head"><div><h3>纵向研究与共现网络</h3><p>独立严格单病队列；不随上方临床表型、性别或年龄分层改变。汇总来自既有分析，未重新估计。</p></div><label>严格研究队列<select id="strict-group"></select></label></div>
  <p id="strict-scope"></p><h4>患者内连续性与匹配患者间参照</h4><div id="matched-results"></div>
  <p>Jaccard 表示药味集合相似度；差值采用原分析的患者级估计。95% CI 为原分析 bootstrap 区间，FDR 为原分析单侧经验检验的 BH 校正结果。关联性结果不表示疗效。</p>
  <details><summary>匹配敏感性分析与调整方式</summary><div id="matched-sensitivity"></div><div id="transition-modes"></div></details>
  <h4>首诊药味共现邻域</h4><div class="controls"><label>网络中心药味（按总用次数）<select id="network-item"></select></label><button class="filter-btn" type="button" id="export-network-svg" disabled>导出网络图 SVG</button></div><p class="research-status" id="network-export-status" role="status" aria-live="polite"></p><p id="network-scope"></p><p class="table-scroll-hint">窄屏可横向滑动网络图；点击关联药味定位下方明细。</p><div id="network-graph" class="network-view" tabindex="0" role="region" aria-label="可横向滚动的共现网络"></div><div id="network-edges"></div>
  <details><summary>阈值敏感性汇总</summary><p>这里只展示已计算的网络规模与保留率。未保存其他阈值的边集合，因此图形始终采用主分析阈值。</p><div id="network-thresholds"></div></details>
</section>
<section class="section research-panel" id="research-quality">
  <div class="section-head"><div><h3>数据质量与版本</h3><p>历史运行状态与本次文件校验分别报告。结构校验与哈希一致不代表诊断真实性或临床有效性得到验证。</p></div></div>
  <div class="identity-grid" id="research-identity"></div><h4>数据口径</h4><p id="quality-scope-note">疾病组来自记录中的诊断标签。临床视图包含精确合并病表型与单维分层；严格研究视图限于单病主分析。页面不公开完整排除流程计数，避免由差值恢复小样本信息。</p>
  <div id="quality-summary"></div><details id="quality-dose-panel"><summary>严格研究队列剂量冲突审计</summary><div id="quality-dose"></div></details>
</section>
"""

RESEARCH_JS = r"""
const research = data.research || {};
const provenance = data.provenance || {};
let researchItem = '', strictGroup = '', networkItem = '', focusCleared = data.presentation?.local_aggregate_only === true;
let viewSequence = 0, restoringView = false;
const disclosed = value => value !== undefined && value !== null && value !== '' && Number.isFinite(Number(value));
const metricText = (value, kind = 'number') => !disclosed(value) ? '未公开 / 未估计' : kind === 'percent' ? percent(value) : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 6 });
const researchRows = key => research[key] || [];
function usageCount(name) {
  const value = researchRows('usage').find(row => row.item_name === name)?.total_usage_visits;
  return disclosed(value) && Number.isInteger(Number(value)) && Number(value) > 0 ? Number(value) : null;
}
function usageOrder(names) {
  return [...new Set(names)].sort((a, b) => (usageCount(b) ?? -1) - (usageCount(a) ?? -1) || a.localeCompare(b, 'zh-CN'));
}
function usageLabel(name) {
  const count = usageCount(name);
  return `${name} · ${count === null ? '总次数未公开' : count.toLocaleString('zh-CN') + ' 次'}`;
}
const strictRows = key => researchRows(key).filter(row => row.group === strictGroup);
const researchTable = (headers, rows, rowIds = []) => rows.length ? `<p class="table-scroll-hint">表格可横向滑动，查看其余列。</p><div class="research-table-wrap" tabindex="0" role="region" aria-label="${escapeHtml(headers.join('、'))}"><table class="research-table"><thead><tr>${headers.map(x => `<th scope="col">${escapeHtml(x)}</th>`).join('')}</tr></thead><tbody>${rows.map((row, index) => `<tr${rowIds[index] ? ` id="${escapeHtml(rowIds[index])}"` : ''}>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : empty('没有可用的公开汇总记录；不表示零或通过。');
const valueCell = (value, kind) => escapeHtml(metricText(value, kind));
const estimateCell = (row, value, low, high) => `${valueCell(row[value])}<small>95% CI ${valueCell(row[low])} – ${valueCell(row[high])}</small>`;

/** Use exactly one shared clinical stratum; never pool or infer a missing group. */
function itemResearchRows() {
  return data.groups.map(group => {
    const find = (rows, type) => forContext(rows, group.code).find(row => row.item_name === researchItem && (!type || row.change_type === type));
    return { group, first: find(data.items), addition: find(data.changes, 'addition'), removal: find(data.changes, 'removal') };
  });
}
function researchRateCell(row, change = false) {
  if (!row) return '未公开 / 未估计';
  const value = row[change ? 'patient_prevalence' : 'prevalence'];
  return `${valueCell(value, 'percent')}${disclosed(value) ? `<div class="research-meter"><i style="width:${Math.max(0, Math.min(100, Number(value) * 100))}%"></i></div>` : ''}<small>${valueCell(row[change ? 'patients_with_change' : 'exposed_patients'])} / ${valueCell(row[change ? 'repeat_patients' : 'group_patients'])} 名${change ? '复诊' : '首诊'}患者</small>${change ? `<small>患者等权复诊频率 ${valueCell(row.mean_patient_transition_fraction, 'percent')}</small>` : ''}<small>${escapeHtml(doseDetail(row))}</small>`;
}
function renderItemResearch() {
  const names = usageOrder([...data.items, ...data.changes].filter(inStratum).map(row => row.item_name));
  if (!researchItem && !focusCleared) researchItem = names[0] || '';
  const options = usageOrder(researchItem ? [...names, researchItem] : names);
  document.getElementById('research-item').innerHTML = `<option value="" ${researchItem ? '' : 'selected'}>选择药味或点击页面中的药名</option>` + options.map(name => `<option ${name === researchItem ? 'selected' : ''} value="${escapeHtml(name)}">${escapeHtml(usageLabel(name))}</option>`).join('');
  document.getElementById('research-item').disabled = !options.length;
  document.getElementById('item-scope').textContent = `跨疾病并列 · ${data.clinicalMode ? (stratumType === 'overall' ? '全部患者' : currentSummary().stratum_label || stratum) : '严格单病队列'}；沿用上方分层，独立于药味搜索与显示数量。`;
  document.getElementById('focused-drug-status').textContent = researchItem ? `已聚焦：${researchItem}。下表使用各疾病组各自的分母；列表搜索保持独立。` : '尚未聚焦药味。点击任一药名，联动查看跨疾病首诊、克数与复诊加减记录。';
  document.getElementById('clear-drug-focus').disabled = !researchItem;
  document.getElementById('item-comparison').innerHTML = researchItem ? researchTable(['疾病组', '首诊覆盖', '复诊加药', '复诊减药'], itemResearchRows().map(row => [`<button type="button" class="group-focus" data-focus-group="${escapeHtml(row.group.code)}">${escapeHtml(groupLabel(row.group.label))}</button>`, researchRateCell(row.first), researchRateCell(row.addition, true), researchRateCell(row.removal, true)])) : empty('选择药味后，按当前分层并列展示各疾病组已公开的结果。');
  document.getElementById('export-item').disabled = !researchItem;
  const annualAvailable = researchItem && data.clinicalMode && [...forContext(data.yearItems), ...forContext(data.yearChanges)].some(row => row.item_name === researchItem);
  const networkGroup = focusedNetworkGroup();
  document.getElementById('item-to-annual').disabled = !annualAvailable;
  document.getElementById('item-to-network').disabled = !networkGroup;
  const networkLabel = groupLabel(researchRows('cohorts').find(row => row.group === networkGroup)?.label || networkGroup);
  document.getElementById('item-to-network').textContent = networkGroup ? `查看${networkLabel}严格队列中的此药网络` : '此药暂无可用严格单病网络';
  document.getElementById('item-availability').textContent = researchItem ? `当前组年度记录：${annualAvailable ? '可查看' : '未公开 / 未估计'}；严格单病网络：${networkGroup ? networkLabel + '可查看（独立队列）' : '未公开 / 未估计'}。缺失单元格保持不可用，不补零。` : '';
}
function focusedNetworkGroup(){
  if(!researchItem || data.privacy)return '';
  const groups=researchRows('cohorts').map(row=>row.group).filter(group=>researchRows('nodes').some(row=>row.group===group&&row.item_name===researchItem));
  return [selected,`${selected}_strict`,strictGroup,...groups].find(group=>groups.includes(group))||'';
}
function drugButton(name){return `<button type="button" class="drug-focus" data-focus-drug="${escapeHtml(name)}" aria-label="聚焦药味 ${escapeHtml(name)}，查看跨疾病与年度记录">${escapeHtml(name)}</button>`}
function focusDrug(name,scroll=true){
  recordViewState(true);researchItem=String(name||'');focusCleared=!researchItem;renderItemResearch();renderViewState();recordViewState();
  if(scroll){const section=document.getElementById('item-research');section.scrollIntoView?.({behavior:'smooth',block:'start'});section.focus?.({preventScroll:true})}
}
function renderStrictResearch() {
  const cohorts = researchRows('cohorts');
  if (!cohorts.some(row => row.group === strictGroup)) strictGroup = cohorts[0]?.group || '';
  document.getElementById('strict-group').innerHTML = cohorts.map(row => `<option value="${escapeHtml(row.group)}" ${strictGroup === row.group ? 'selected' : ''}>${escapeHtml(groupLabel(row.label || row.group))}</option>`).join('');
  document.getElementById('strict-group').disabled = !cohorts.length;
  const cohort = cohorts.find(row => row.group === strictGroup);
  document.getElementById('strict-scope').textContent = cohort ? `${groupLabel(cohort.label || cohort.group)} · 主分析可用患者 ${metricText(cohort.patients)} 人；各分析有效样本量见表。分母不同，不可用上方临床人数替代。` : '未载入严格队列。';
  document.getElementById('matched-results').innerHTML = researchTable(['有效患者 / 转换', '患者内 Jaccard', '匹配患者间 Jaccard', '患者内减患者间', 'BH FDR'], strictRows('matched').map(row => [
    `${valueCell(row.patients)} / ${valueCell(row.matched_transitions)}`,
    estimateCell(row, 'observed_patient_median_jaccard', 'observed_bootstrap_ci95_low', 'observed_bootstrap_ci95_high'),
    estimateCell(row, 'matched_between_patient_median_jaccard', 'matched_between_bootstrap_ci95_low', 'matched_between_bootstrap_ci95_high'),
    estimateCell(row, 'within_minus_between_median', 'within_minus_between_bootstrap_ci95_low', 'within_minus_between_bootstrap_ci95_high'), valueCell(row.empirical_one_sided_bh_fdr)]));
  document.getElementById('matched-sensitivity').innerHTML = researchTable(['敏感性设定', '患者', '转换', '患者内 Jaccard', '患者间 Jaccard', '差值及 95% CI'], strictRows('sensitivity').map(row => [escapeHtml(row.analysis), valueCell(row.patients), valueCell(row.transitions), valueCell(row.observed_patient_median_jaccard), valueCell(row.matched_between_patient_median_jaccard), estimateCell(row, 'within_minus_between_median', 'within_minus_between_bootstrap_ci95_low', 'within_minus_between_bootstrap_ci95_high')]));
  const modes = { exact_repeat: '完全重复', dose_only: '仅剂量变化', composition_only: '仅药味变化', composition_and_dose: '药味与剂量均变化' };
  document.getElementById('transition-modes').innerHTML = researchTable(['调整方式', '剂量可解析患者', '剂量可解析转换', '患者等权平均比例'], strictRows('modes').map(row => [escapeHtml(modes[row.mode] || row.mode), valueCell(row.dose_resolved_patients), valueCell(row.dose_resolved_transitions), valueCell(row.mean_patient_proportion, 'percent')]));
  renderResearchNetwork();
}
/** Fixed, non-overlapping positions; edges and values are unchanged source aggregates. */
function neighborhoodSvg(center, visible) {
  const points = visible.map((row, index) => {
    const side = index % 2, slot = Math.floor(index / 2), count = Math.ceil((visible.length - side) / 2);
    return {row, index, side, x: side ? 550 : 30, y: 318 + (slot - (count - 1) / 2) * 88,
      name: row.item_1 === networkItem ? row.item_2 : row.item_1};
  });
  const links = points.map(p => {
    const target = p.side ? p.x : p.x + 180, anchor = p.side ? 440 : 320;
    return `<path d="M ${anchor} 318 C ${(anchor + target) / 2} 318 ${(anchor + target) / 2} ${p.y} ${target} ${p.y}" fill="none" stroke="#8cb6ae" stroke-opacity=".65" stroke-width="${1 + number(p.row.cosine_similarity) * 3}"/>`;
  }).join('');
  const cards = points.map(p => `<a class="network-associate" href="#network-edge-${p.index}" aria-label="${escapeHtml(p.name)}，共现 ${escapeHtml(p.row.cooccurrence_patients)} 人，查看完整数值"><title>${escapeHtml(p.name)}；共现 ${escapeHtml(p.row.cooccurrence_patients)} 人；余弦 ${metricText(p.row.cosine_similarity)}</title><rect x="${p.x}" y="${p.y - 32}" width="180" height="64" rx="12" fill="#ffffff" stroke="#d4e3e0"/><circle cx="${p.x + 16}" cy="${p.y - 7}" r="4" fill="#28695f"/><text x="${p.x + 29}" y="${p.y - 2}" font-size="16" font-weight="600" fill="#183c43">${escapeHtml(p.name)}</text><text x="${p.x + 16}" y="${p.y + 19}" font-size="11" fill="#577986">${escapeHtml(p.row.cooccurrence_patients)} 人共现 · 余弦 ${number(p.row.cosine_similarity).toFixed(3)}</text></a>`).join('');
  return `<svg viewBox="0 0 760 636" role="img" aria-label="${escapeHtml(networkItem)}首诊共现邻域，前 ${visible.length} 条关联；完整数值见下表" font-family="Microsoft YaHei, sans-serif"><title>${escapeHtml(networkItem)}首诊共现邻域</title><desc>中心节点用于定位所选药味。连线越粗表示余弦相似度越高；位置与节点大小不代表效应。点击关联药味查看表格。</desc><rect width="760" height="636" rx="20" fill="#edf4f3"/><circle cx="380" cy="318" r="138" fill="none" stroke="#dce9e6"/><circle cx="380" cy="318" r="108" fill="none" stroke="#d4e3e0" stroke-dasharray="3 7"/><text x="30" y="37" font-size="12" letter-spacing="2" fill="#577986">首诊共现 / ${visible.length} 条关联</text><text x="730" y="37" text-anchor="end" font-size="11" fill="#577986">线宽 = 余弦相似度</text>${links}<circle cx="380" cy="318" r="77" fill="#dce9e6"/><circle cx="380" cy="318" r="67" fill="#183c43"/><text x="380" y="300" text-anchor="middle" font-size="${networkItem.length > 5 ? 16 : 22}" font-weight="600" fill="#ffffff">${escapeHtml(networkItem)}</text><text x="380" y="325" text-anchor="middle" font-size="12" fill="#d4e3e0">首诊使用</text><text x="380" y="350" text-anchor="middle" font-size="21" font-family="Georgia, serif" fill="#ffffff">${escapeHtml(metricText(center.exposed_patients))} 人</text>${cards}<text x="380" y="610" text-anchor="middle" font-size="12" fill="#577986">点击关联药味查看明细 · 共现不代表配伍功效</text></svg>`;
}
function renderResearchNetwork() {
  document.getElementById('network-export-status').textContent = '';
  const sourceNodes = strictRows('nodes');
  const nodes = usageOrder(sourceNodes.map(row => row.item_name)).map(name => sourceNodes.find(row => row.item_name === name));
  if (!nodes.some(row => row.item_name === networkItem)) networkItem = nodes[0]?.item_name || '';
  document.getElementById('network-item').innerHTML = nodes.map(row => `<option value="${escapeHtml(row.item_name)}" ${row.item_name === networkItem ? 'selected' : ''}>${escapeHtml(usageLabel(row.item_name))}</option>`).join('');
  document.getElementById('network-item').disabled = !nodes.length;
  const center = nodes.find(row => row.item_name === networkItem);
  const edges = strictRows('edges').filter(row => row.item_1 === networkItem || row.item_2 === networkItem).sort((a, b) => number(b.cosine_similarity) - number(a.cosine_similarity));
  document.getElementById('network-scope').textContent = center ? `选项次数为全分析人群的全部合格就诊；图中人数为当前严格队列首诊。主分析阈值：首诊覆盖率 ≥ ${metricText(center.node_prevalence_threshold, 'percent')}，余弦相似度 ≥ ${metricText(center.edge_cosine_threshold)}；分析患者 ${metricText(center.patients)} 人。图显示相似度最高的前 12 条关联，表格包含全部 ${edges.length} 条。连线表示共现，不能解释为配伍功效。` : '没有公开的主分析网络节点。';
  document.getElementById('export-network-svg').disabled = !center || !edges.length;
  const neighborName = row => row.item_1 === networkItem ? row.item_2 : row.item_1;
  const visible = edges.slice(0, 12);
  document.getElementById('network-graph').innerHTML = !center || !edges.length ? empty(center ? '该节点没有达到主分析阈值的公开关联。' : '未载入可绘制的网络。') : neighborhoodSvg(center, visible);
  document.getElementById('network-edges').innerHTML = researchTable(['关联药味', '共现患者', '首诊支持度', '余弦相似度', 'Lift'], edges.map(row => [escapeHtml(neighborName(row)), valueCell(row.cooccurrence_patients), valueCell(row.support, 'percent'), valueCell(row.cosine_similarity), valueCell(row.lift)]), edges.map((_, index) => `network-edge-${index}`));
  document.getElementById('network-thresholds').innerHTML = researchTable(['主分析', '覆盖率阈值', '余弦阈值', '节点', '边', '节点保留率', '边保留率'], strictRows('thresholds').map(row => [row.primary_setting === 'True' ? '是' : '否', valueCell(row.node_prevalence_threshold, 'percent'), valueCell(row.edge_cosine_threshold), valueCell(row.stable_nodes), valueCell(row.edges), valueCell(row.node_retention_vs_primary, 'percent'), valueCell(row.edge_retention_vs_primary, 'percent')]));
}
function renderResearchQuality() {
  document.getElementById('source-kind').textContent = provenance.synthetic_mode === true ? '模拟数据演示：所有病例与统计均为合成示例，不是真实患者结果。' : provenance.synthetic_mode === false ? data.presentation?.local_aggregate_only === true ? '已核对的门诊汇总 · 来源内独立解读。' : '非模拟来源的群体汇总；具体诊疗场景需按数据来源核实，不替代临床判断。' : '数据来源真实性未核实，不用于临床判断。';
  const cards = [['数据集', provenance.dataset_id], ['队列版本', provenance.cohort_version], ['分析版本 / 看板版本', `${provenance.analysis_version || '未核实'} / ${data.version || '未核实'}`], ['当前最小公开患者数', data.privacy?.min_public_n ?? provenance.min_public_n], ['原运行状态', provenance.recorded_run_gate], ['本次源文件哈希核验', provenance.artifact_check], ['数据来源类型', provenance.synthetic_mode === true ? '模拟数据' : provenance.synthetic_mode === false ? '真实数据汇总' : '未核实'], ['配置 SHA-256', provenance.config_sha256]];
  document.getElementById('research-identity').innerHTML = cards.map(([label, value]) => `<div class="identity-card"><span>${escapeHtml(label)}</span><b>${escapeHtml(value ?? '未核实')}</b></div>`).join('');
  const normalization = researchRows('normalization')[0];
  document.getElementById('quality-summary').innerHTML = researchTable(['核验对象', '状态与边界'], [
    ['已载入汇总表结构', '已在构建时检查必需字段、重复表头、行宽与禁用标识字段；未知列已排除'],
    ['源文件完整性', escapeHtml(provenance.artifact_check === 'PASS' ? '所有载入表与运行清单哈希一致' : provenance.artifact_check === 'PARTIAL' ? '仅部分载入表有可核对的清单哈希' : '未评估：缺少可核对的运行清单哈希')],
    ['药名归一化', normalization ? `${escapeHtml(normalization.dictionary_version)}；字典条目 ${valueCell(normalization.dictionary_entries)}。${Number(normalization.dictionary_entries) === 0 ? '当前未应用药名映射字典，同义名称可能仍分开统计。' : '仅使用原分析已固定映射。'}` : '未评估：缺少字典审计表'],
    ['诊断真实性、疗效与安全性', '未评估；本平台展示记录标签与处方结构，不输出治疗建议']
  ]);
  document.getElementById('quality-dose').innerHTML = researchTable(['队列', '患者', '就诊', '冲突患者', '冲突就诊', '冲突条目', '冲突患者百分比'], researchRows('doseAudit').map(row => [escapeHtml(groupLabel(researchRows('cohorts').find(c => c.group === row.group)?.label || row.group)), valueCell(row.patients), valueCell(row.visits), valueCell(row.patients_with_conflict), valueCell(row.visits_with_conflict), valueCell(row.visit_item_conflicts), disclosed(row.patients_with_conflict_pct) ? `${valueCell(row.patients_with_conflict_pct)}%` : '未公开 / 未估计']));
}
/** Prefix spreadsheet formulas, then RFC 4180 quote every text cell. */
function safeCsvCell(value) {
  let text = String(value ?? '');
  if (!(typeof value === 'number' && Number.isFinite(value)) && /^[\s\uFEFF]*[=+@-]/u.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
function itemExportRows() {
  return itemResearchRows().flatMap(entry => ['first', 'addition', 'removal'].map(metric => {
    const row = entry[metric];
    return { group: entry.group.code, item_name: researchItem, stratum_type: data.clinicalMode ? stratumType : 'overall', stratum: data.clinicalMode ? stratum : 'all', metric,
      numerator: row?.[metric === 'first' ? 'exposed_patients' : 'patients_with_change'] ?? '', denominator: row?.[metric === 'first' ? 'group_patients' : 'repeat_patients'] ?? '',
      prevalence: row?.[metric === 'first' ? 'prevalence' : 'patient_prevalence'] ?? '',
      mean_patient_transition_fraction: row?.mean_patient_transition_fraction ?? '', dose_fraction: row?.most_common_dose_fraction ?? '', dose_fraction_semantics: 'per_modal_value', dose_values_g: row?.most_common_dose_values_g ?? '', dose_patients: row?.dose_patients ?? '', most_common_dose_patients: row?.most_common_dose_patients ?? '', dose_tied: row?.most_common_dose_tied ?? '',
      availability: row ? 'disclosed_row_cells_may_be_suppressed' : 'not_disclosed_or_not_estimated', dataset_id: provenance.dataset_id ?? '', cohort_version: provenance.cohort_version ?? '', analysis_version: provenance.analysis_version ?? '', dashboard_version: data.presentation?.renderer_version ?? data.version ?? '', source_id: data.source_identity?.key ?? '', source_title: data.source_identity?.title ?? '', privacy_profile: data.privacy?.profile ?? 'legacy', min_public_n: data.privacy?.min_public_n ?? provenance.min_public_n ?? '' };
  }));
}
/** Export precisely the comparison rows rendered after search and display limits. */
function comparisonExportRows() {
  const numericFields = ['combination_repeat_patients','single_repeat_patients','combination_patients_with_change','single_patients_with_change','combination_prevalence','single_prevalence','combination_mean_transition_fraction','single_mean_transition_fraction','mean_transition_fraction_difference'];
  return comparisonDisplayRows().map(row => ({ ...row,
    ...Object.fromEntries(numericFields.map(key => [key, disclosed(row[key]) ? Number(row[key]) : ''])),
    combination_label: groupLabel(row.combination_label), single_label: groupLabel(row.single_label),
    dataset_id: provenance.dataset_id ?? '', cohort_version: provenance.cohort_version ?? '',
    analysis_version: provenance.analysis_version ?? '', dashboard_version: data.presentation?.renderer_version ?? data.version ?? '',
    source_id: data.source_identity?.key ?? '', source_title: data.source_identity?.title ?? '',
    synthetic_mode: provenance.synthetic_mode === true, privacy_profile: data.privacy?.profile ?? 'legacy',
    min_public_n: data.privacy?.min_public_n ?? provenance.min_public_n ?? '',
    difference_definition: 'combination_minus_single_patient_equal_transition_fraction',
    dose_fraction_semantics: 'per_modal_value', search: query, change_direction_filter: comparisonDirection, display_limit_per_direction: limit }));
}
function downloadResearch(name, body, type, statusId = 'export-status') {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const link = document.createElement('a'); link.href = url; link.download = name;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  document.getElementById(statusId).textContent = `已生成 ${name}；仅含公开汇总与当前视图口径。`;
}
const figureCss = __FIGURE_CSS__;
/** Wrap by approximate full-width glyphs to keep long source labels inside SVG. */
function figureLines(value, columns) {
  const lines = []; let line = '', width = 0;
  for (const char of String(value)) {
    const size = char.codePointAt(0) > 255 ? 2 : 1;
    if (width + size > columns) { lines.push(line); line = ''; width = 0; }
    line += char; width += size;
  }
  if (line) lines.push(line);
  return lines;
}
function figureContext(kind) {
  if (kind === 'annual') {
    const group = data.groups.find(row => row.code === selected);
    const metric = { prevalence: '年度覆盖率', addition: '年度加药频率', removal: '年度减药频率' }[annualMetric];
    return { kind, title: `${annualItem} · ${metric}`, item: annualItem, group: selected,
      subtitle: `${groupLabel(group?.label)} · ${stratumType === 'overall' ? '全部患者' : currentSummary().stratum_label || stratum}`,
      stratum_type: stratumType, stratum, metric: annualMetric,
      denominator: annualMetric === 'prevalence' ? '每名患者每年首张合格处方；各年分母见图。' : '各复诊患者年内加/减药转换比例，再对患者等权平均；各年发生人数/复诊人数见图。',
      note: '缺失年份断线，不补零；克数为历史记录。记录标签队列，不能据此判断疗效。',
      rows: annualSourceRows().filter(row => row.item_name === annualItem) };
  }
  const center = strictRows('nodes').find(row => row.item_name === networkItem);
  const cohort = researchRows('cohorts').find(row => row.group === strictGroup);
  const edges = strictRows('edges').filter(row => row.item_1 === networkItem || row.item_2 === networkItem).sort((a, b) => number(b.cosine_similarity) - number(a.cosine_similarity));
  return { kind, title: `${networkItem} · 首诊共现邻域`, item: networkItem, group: strictGroup,
    subtitle: `${groupLabel(cohort?.label || strictGroup)} · 独立严格单病队列`,
    stratum_type: 'overall', stratum: 'all',
    denominator: `首诊分析患者 ${metricText(center?.patients)} 人；覆盖率阈值 ${metricText(center?.node_prevalence_threshold, 'percent')}，余弦阈值 ${metricText(center?.edge_cosine_threshold)}。`,
    note: `图中显示 ${Math.min(12, edges.length)} / ${edges.length} 条公开关联，按余弦相似度选取前 12 条。连线表示共现，不表示配伍功效。`,
    center, displayed_edges: edges.slice(0, 12) };
}
/** Serialize existing, escaped chart markup; metadata contains public projections only. */
function standaloneFigure(source, context) {
  const match = source.match(/<svg\b[^>]*viewBox="0 0 ([\d.]+) ([\d.]+)"[^>]*>([\s\S]*?)<\/svg>/);
  if (!match) return null;
  const plotWidth = Number(match[1]), plotHeight = Number(match[2]), width = plotWidth + 48;
  if (!(plotWidth > 0 && plotHeight > 0)) return null;
  const title = figureLines(context.title, Math.floor(plotWidth / 11));
  const subtitle = figureLines(context.subtitle, Math.floor(plotWidth / 8));
  const top = 34 + title.length * 26 + subtitle.length * 20;
  const footer = [context.denominator, context.note, `来源 ${data.source_identity?.title ?? provenance.dataset_id ?? '未核实'}；展示策略 ${data.privacy?.profile ?? '历史汇总'}`,
    `数据集 ${provenance.dataset_id ?? '未核实'}；队列 ${provenance.cohort_version ?? '未核实'}`,
    `分析 ${provenance.analysis_version ?? '未核实'}；看板 ${data.version}；最小公开人数 ${data.privacy?.min_public_n ?? provenance.min_public_n ?? '未核实'}；源文件校验 ${provenance.artifact_check ?? 'NOT_ASSESSED'}`,
    '源表 SHA-256、筛选条件及原始汇总值见 SVG 内嵌 metadata。'
  ].flatMap(line => figureLines(line, Math.floor(plotWidth / 7)));
  const height = top + plotHeight + 36 + footer.length * 20;
  const metadata = { schema_version: 1, provenance, source_identity: data.source_identity ?? null, privacy: data.privacy ?? null, dashboard_version: data.presentation?.renderer_version ?? data.version, figure: context };
  const textLines = (lines, y, size, weight = 400) => lines.map((line, index) => `<text x="24" y="${y + index * (size + 6)}" font-size="${size}" font-weight="${weight}">${escapeHtml(line)}</text>`).join('');
  // Fragment links point into the dashboard table and have no standalone meaning.
  const geometry = match[3].replace(/<a\b[^>]*>/g, '').replace(/<\/a>/g, '');
  return `<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="figure-title figure-desc"><title id="figure-title">${escapeHtml(context.title)}</title><desc id="figure-desc">${escapeHtml(context.subtitle + '。' + context.denominator + context.note)}</desc><metadata>${escapeHtml(JSON.stringify(metadata))}</metadata><style>${figureCss}</style><rect width="${width}" height="${height}" fill="#fbfcf9"/>${textLines(title, 32, 20, 600)}${textLines(subtitle, 32 + title.length * 26, 14)}<g transform="translate(24 ${top})">${geometry}</g>${textLines(footer, top + plotHeight + 24, 14)}</svg>`;
}
function exportFigure(kind) {
  const sourceId = kind === 'annual' ? 'annual-chart' : 'network-graph';
  const statusId = `${kind}-export-status`;
  const context = figureContext(kind);
  const svg = standaloneFigure(document.getElementById(sourceId).innerHTML, context);
  if (!svg) { document.getElementById(statusId).textContent = '当前没有可导出的公开图形。'; return; }
  const token = value => String(value).replace(/[^\p{L}\p{N}_.-]/gu, '_').slice(0, 48);
  downloadResearch(`mingyirx-${kind}-${token(context.group)}-${token(context.item)}.svg`, svg, 'image/svg+xml;charset=utf-8', statusId);
}
/** History contains aggregate navigation only; patient reference fields are excluded. */
function captureViewState(){
  return {schema_version:1,source:data.source_identity?.key||'',selected,stratumType,stratum,query,groupFilter,researchItem,focusCleared,annualItem,annualMetric,comparisonKey,comparisonDirection,comboSize,limit,foldCombos:document.getElementById('fold-combos').checked,strictGroup,networkItem,sequence:viewSequence};
}
function renderViewState(){
  document.getElementById('view-back').disabled=viewSequence<1;
  document.getElementById('view-state').textContent=`当前：${groupLabel(data.groups.find(group=>group.code===selected)?.label||'无公开组')} · ${stratumType==='overall'?'全部公开分层':currentSummary().stratum_label||stratum}${researchItem?' · 聚焦 '+researchItem:''}${query?' · 列表搜索 '+query:''}`;
}
function recordViewState(replace=false){
  if(restoringView||typeof history==='undefined'||typeof location==='undefined'||typeof URL!=='function')return;
  if(!replace)viewSequence+=1;
  const state={mingyirx_view:captureViewState()},url=new URL(location.href);
  if(state.mingyirx_view.source)url.searchParams.set('source',state.mingyirx_view.source);
  if(replace)history.replaceState?.(state,'',url);else history.pushState(state,'',url);
  renderViewState();
}
function syncViewControls(){
  document.getElementById('group-filter').value=groupFilter;document.getElementById('search').value=query;
  document.getElementById('limit').value=String(limit);document.getElementById('comparison-direction').value=comparisonDirection;
  document.querySelectorAll('.filter-btn[data-size]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.size===comboSize)));
}
function clearExportMessages(){for(const id of ['export-status','annual-export-status','network-export-status','comparison-export-status'])document.getElementById(id).textContent=''}
function resetDashboardView(push=true,resetGroup=true){
  if(push)recordViewState(true);
  if(resetGroup)selected=data.groups[0]?.code||'';
  stratumType='overall';stratum='all';comparisonKey='';comparisonDirection='all';annualItem='';annualMetric='prevalence';researchItem='';focusCleared=data.presentation?.local_aggregate_only===true;strictGroup=selected;networkItem='';query='';comboSize='all';limit=12;groupFilter='all';
  document.getElementById('fold-combos').checked=true;document.getElementById('reference-age').value='';document.getElementById('reference-sex').value='';
  syncViewControls();clearExportMessages();
  if(push){render();renderStrictResearch();renderResearchQuality();renderReferenceResult();recordViewState()}
}
function applyViewState(state){
  if(!state||state.schema_version!==1)return;
  restoringView=true;
  try{
    if(state.source&&state.source!==data.source_identity?.key&&typeof switchAnalysisSource==='function')switchAnalysisSource(state.source,false);
    selected=data.groups.some(group=>group.code===state.selected)?state.selected:(data.groups[0]?.code||'');
    stratumType=String(state.stratumType||'overall');stratum=String(state.stratum||'all');ensureStratum();
    query=String(state.query||'');groupFilter=['all','single','comorbidity'].includes(state.groupFilter)?state.groupFilter:'all';
    researchItem=String(state.researchItem||'');focusCleared=Boolean(state.focusCleared);annualItem=String(state.annualItem||'');
    annualMetric=['prevalence','addition','removal'].includes(state.annualMetric)?state.annualMetric:'prevalence';
    comparisonKey=String(state.comparisonKey||'');comparisonDirection=['all','addition','removal'].includes(state.comparisonDirection)?state.comparisonDirection:'all';
    comboSize=['all','2','3'].includes(state.comboSize)?state.comboSize:'all';limit=[8,12,20].includes(state.limit)?state.limit:12;
    strictGroup=String(state.strictGroup||'');networkItem=String(state.networkItem||'');viewSequence=Number.isSafeInteger(state.sequence)?Math.max(0,state.sequence):0;
    document.getElementById('fold-combos').checked=state.foldCombos!==false;syncViewControls();clearExportMessages();
    render();renderStrictResearch();renderResearchQuality();
  }finally{restoringView=false}
}
function changeView(action){recordViewState(true);action();renderViewState();recordViewState()}
function initializeResearch() {
  document.getElementById('view-back').addEventListener('click',()=>{if(typeof history!=='undefined'&&viewSequence>0)history.back()});
  document.getElementById('reset-view').addEventListener('click',()=>resetDashboardView());
  document.getElementById('clear-drug-focus').addEventListener('click',()=>focusDrug('',false));
  document.addEventListener?.('click',event=>{
    const drug=event.target.closest?.('button[data-focus-drug]');if(drug){focusDrug(drug.dataset.focusDrug);return}
    const group=event.target.closest?.('button[data-focus-group]');if(group)selectDiseaseGroup(group.dataset.focusGroup);
  });
  if(typeof addEventListener==='function')addEventListener('popstate',event=>{
    const state=event?.state?.mingyirx_view;
    if(state){applyViewState(state);return}
    if(typeof switchAnalysisSource==='function')switchAnalysisSource(new URLSearchParams(location.search).get('source')||defaultSource,false);
  });
  document.getElementById('export-comparison').addEventListener('click', () => {
    const rows = comparisonExportRows(); if (!rows.length) return;
    const keys = Object.keys(rows[0]);
    const csv = [keys, ...rows.map(row => keys.map(key => row[key]))].map(row => row.map(safeCsvCell).join(',')).join('\r\n');
    downloadResearch('mingyirx-comorbidity-comparison.csv', '\uFEFF' + csv, 'text/csv;charset=utf-8', 'comparison-export-status');
  });
  document.getElementById('export-annual-svg').addEventListener('click', () => exportFigure('annual'));
  document.getElementById('export-network-svg').addEventListener('click', () => exportFigure('network'));
  document.getElementById('research-item').addEventListener('change', event => focusDrug(event.target.value,false));
  document.getElementById('strict-group').addEventListener('change', event => changeView(()=>{strictGroup=event.target.value;networkItem='';renderStrictResearch();renderItemResearch()}));
  document.getElementById('network-item').addEventListener('change', event => changeView(()=>{networkItem=event.target.value;renderResearchNetwork()}));
  document.getElementById('item-to-annual').addEventListener('click', () => changeView(()=>{annualItem=researchItem;renderAnnual();document.getElementById('annual-section').scrollIntoView({behavior:'smooth'})}));
  document.getElementById('item-to-network').addEventListener('click',()=>{const group=focusedNetworkGroup();if(!group)return;changeView(()=>{strictGroup=group;networkItem=researchItem;renderStrictResearch();document.getElementById('strict-research').scrollIntoView({behavior:'smooth'})})});
  document.getElementById('export-item').addEventListener('click', () => {
    const rows = itemExportRows(); if (!rows.length) return;
    const keys = Object.keys(rows[0]);
    const csv = [keys, ...rows.map(row => keys.map(key => row[key]))].map(row => row.map(safeCsvCell).join(',')).join('\r\n');
    downloadResearch('mingyirx-item-view.csv', '\uFEFF' + csv, 'text/csv;charset=utf-8');
  });
  document.getElementById('export-provenance').addEventListener('click', () => downloadResearch('mingyirx-view-provenance.json', JSON.stringify({ schema_version: 1, provenance, source_identity: data.source_identity ?? null, privacy: data.privacy ?? null, dashboard_version: data.presentation?.renderer_version ?? data.version,
    view: { item: researchItem, stratum_type: stratumType, stratum, clinical_mode: data.clinicalMode, strict_group: strictGroup, network_item: networkItem },
    denominators: { first: 'first-prescription patients', addition: 'repeat patients', removal: 'repeat patients' }, rows: itemExportRows() }, null, 2), 'application/json'));
  renderStrictResearch(); renderResearchQuality();recordViewState(true);
}
"""
