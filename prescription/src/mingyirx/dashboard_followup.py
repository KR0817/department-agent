"""Independent, offline view of disclosed adjacent-visit change aggregates."""
from __future__ import annotations

import re

from .dashboard import DashboardError


FOLLOWUP_CSS = r"""
#followup-lab{min-width:0;scroll-margin-top:var(--community-anchor-offset,142px);margin:34px 0;padding-top:8px}
#followup-lab [hidden]{display:none!important}
#followup-lab .followup-heading{display:flex;align-items:start;justify-content:space-between;gap:20px;margin-bottom:18px}
#followup-lab .followup-heading h3{font-size:30px;line-height:1.4;margin:5px 0 8px;color:#173c2e}
#followup-lab .followup-eyebrow{font:600 11px/1.5 system-ui,sans-serif;letter-spacing:.14em;color:#48765a}
#followup-lab p{line-height:1.75;max-width:none}
#followup-lab .followup-heading p,#followup-lab .followup-note{font-size:12px;color:#52695b;margin:6px 0}
#followup-lab .followup-stage-badge{flex:none;max-width:180px;background:#e5eecf;border:1px solid #b2c4a7;border-radius:6px;padding:8px 12px;color:#355438;font-size:12px;line-height:1.5}
#followup-lab .followup-timeline{display:grid;grid-template-columns:1fr 1.15fr 1fr;gap:1px;list-style:none;padding:0;margin:0;border:1px solid #adc3b1;border-radius:12px;overflow:hidden;background:#adc3b1}
#followup-lab .followup-timeline li{padding:18px;background:#f3f7ee;min-width:0}
#followup-lab .followup-timeline li:nth-child(2){background:#153d31;color:#f1f7e8}
#followup-lab .followup-timeline span{display:block;font-size:10px;font-weight:600;letter-spacing:.09em;color:#55725b;margin-bottom:7px}
#followup-lab .followup-timeline li:nth-child(2) span{color:#b5d3b5}
#followup-lab .followup-timeline strong{display:block;font-size:19px;line-height:1.5}
#followup-lab .followup-timeline p{margin:6px 0 0;font-size:12px;color:#526858}
#followup-lab .followup-timeline li:nth-child(2) p{color:#d0e0cb}
#followup-lab .followup-scope{margin:18px 0 10px;padding-left:12px;border-left:3px solid #7ca079;font-size:12px;color:#37513d;overflow-wrap:anywhere}
#followup-lab .followup-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;background:#c6d6bf;border:1px solid #c6d6bf;border-radius:9px;overflow:hidden;margin:0 0 12px}
#followup-lab .followup-summary>div{min-width:0;padding:15px 18px;background:#fcfdf7}
#followup-lab .followup-summary dt{font-size:11px;color:#5c6d54;line-height:1.6}
#followup-lab .followup-summary dd{margin:5px 0 0;font:600 23px/1.5 ui-monospace,monospace;color:#2b5538;overflow-wrap:anywhere}
#followup-lab .followup-availability{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0 22px;font-size:11px;color:#566650}
#followup-lab .followup-availability span{border:1px solid #cbd8c3;background:#f2f6eb;border-radius:5px;padding:6px 9px;line-height:1.5}
#followup-lab .followup-controls{display:grid;grid-template-columns:minmax(180px,1.3fr) minmax(140px,.8fr) minmax(130px,.8fr) minmax(150px,1fr);gap:12px;padding:16px;border:1px solid #bcccba;background:linear-gradient(#f5f8ef,#edf3e6);border-radius:10px}
#followup-lab .followup-controls label{display:grid;gap:6px;min-width:0;font-size:11px;font-weight:600;color:#4c624a}
#followup-lab select{min-width:0;width:100%;max-width:none;min-height:44px;border:1px solid #b5c7b0;border-radius:6px;background:#fffef9;padding:8px;font-size:13px;color:#203f2b}
#followup-lab button{cursor:pointer}
#followup-lab :is(button,select):focus-visible{outline:2px solid #16745b;outline-offset:3px}
#followup-lab .followup-actions{display:flex;flex-wrap:wrap;align-items:center;gap:10px;justify-content:space-between;margin:12px 0 16px}
#followup-lab .followup-button{min-height:44px;padding:10px 14px;border:1px solid #9fb89b;border-radius:7px;background:linear-gradient(#fffef8,#e8f0df);box-shadow:inset 0 1px #fff;color:#2e5134;font-size:12px;line-height:1.6;white-space:normal}
#followup-lab .followup-button:disabled{color:#73816b;background:#edf1e8;border-color:#c3cebc;cursor:not-allowed;box-shadow:none}
#followup-lab .followup-columns{display:grid;grid-template-columns:1fr 1fr;gap:16px}
#followup-lab .followup-columns[data-direction="addition"]{grid-template-columns:1fr}
#followup-lab .followup-columns[data-direction="removal"]{grid-template-columns:1fr}
#followup-lab .followup-column{min-width:0;border:1px solid #bdcfb7;border-radius:11px;background:#fbfdf6;overflow:hidden}
#followup-lab .followup-column>header{display:flex;align-items:baseline;justify-content:space-between;gap:10px;padding:16px 18px;border-bottom:1px solid #c8d9bf;background:#e6efdc}
#followup-lab .followup-column.removal{border-color:#cfbeae;background:#fdfbf6}
#followup-lab .followup-column.removal>header{background:#f0e8d9;border-color:#d9cdbb}
#followup-lab .followup-column h4{margin:0;font-size:19px;color:#2c4c31}
#followup-lab .followup-column.removal h4{color:#79553a}
#followup-lab .followup-column>header span{font-size:11px;color:#5e7155}
#followup-lab .followup-change{padding:14px 18px;border-bottom:1px solid #dce5d5}
#followup-lab .followup-change:last-child{border-bottom:0}
#followup-lab .followup-change[data-selected="true"]{background:#eef4e4;box-shadow:inset 3px 0 #72976b}
#followup-lab .followup-change>div{display:flex;gap:10px;align-items:baseline;justify-content:space-between}
#followup-lab .followup-drug{border:0;background:none;padding:8px 0;min-height:44px;max-width:70%;font-size:17px;line-height:1.5;font-weight:600;color:#274b30;text-align:left;overflow-wrap:anywhere}
#followup-lab .followup-change strong{font:600 18px/1.5 ui-monospace,monospace;color:#315636;text-align:right;overflow-wrap:anywhere}
#followup-lab .followup-change p{font-size:11px;color:#5d6e53;margin:4px 0;overflow-wrap:anywhere}
#followup-lab .followup-measure{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;font-size:11px;color:#586d51;margin:5px 0}
#followup-lab .followup-measure span:first-child{height:5px;border-radius:3px;overflow:hidden;background:#dce7d2}
#followup-lab .followup-measure i{height:100%;display:block;background:#7b9e69}
#followup-lab .removal .followup-measure i{background:#b38a58}
#followup-lab .followup-section-heading{display:flex;gap:16px;align-items:center;justify-content:space-between;margin:28px 0 10px}
#followup-lab .followup-section-heading h4{font-size:21px;margin:0;color:#29482f}
#followup-lab .followup-year-table td:first-child,#followup-lab .followup-year-table th:first-child{text-align:left}
#followup-lab .followup-year-table :is(th,td){text-align:right;font-variant-numeric:tabular-nums}
#followup-lab .followup-year-table tr[data-period-selected="true"] td{background:#eaf2dd}
#followup-lab .followup-year-table .followup-value-missing{color:#7b7769;font-size:11px}
#followup-lab .followup-readiness{margin-top:28px;padding:22px;border:1px solid #bccdb4;border-radius:12px;background:#f1f5e9}
#followup-lab .followup-readiness h4{margin:0 0 10px;font-size:22px;color:#294b31}
#followup-lab .followup-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}
#followup-lab .followup-tabs button[aria-selected="true"]{background:#254e36;color:#f8faef;border-color:#3f6c45;box-shadow:inset 0 1px #abc5964d}
#followup-lab .followup-requirements{display:grid;grid-template-columns:1fr 1fr;gap:10px 22px;list-style:none;padding:0;margin:14px 0}
#followup-lab .followup-requirements li{border-top:1px solid #c5d3bb;padding-top:10px;font-size:12px;line-height:1.8;color:#4f644b}
#followup-lab .followup-requirements b{display:block;color:#2f5135;font-size:13px}
#followup-lab .followup-benchmark{padding:14px 16px;border-left:3px solid #9f8252;background:#faf6ea;font-size:12px;color:#64543a;line-height:1.9}
#followup-lab .followup-legacy{margin-top:24px;border-top:1px solid #bdccba;padding-top:12px}
#followup-lab .followup-legacy>summary{min-height:44px;padding:12px 0;color:#536a50;font-size:12px;cursor:pointer}
@media(max-width:1100px){#followup-lab .followup-controls{grid-template-columns:1fr 1fr}}
@media(max-width:600px){#followup-lab .followup-heading{display:block}#followup-lab .followup-heading h3{font-size:27px}#followup-lab .followup-stage-badge{display:inline-block;max-width:none;margin-top:8px}#followup-lab .followup-timeline{grid-template-columns:1fr}#followup-lab .followup-timeline li{padding:14px 16px}#followup-lab .followup-timeline strong{font-size:17px}#followup-lab .followup-summary{grid-template-columns:1fr}#followup-lab .followup-summary>div{display:flex;align-items:baseline;gap:15px;justify-content:space-between;padding:10px 15px}#followup-lab .followup-summary dd{font-size:21px;margin:0;text-align:right}#followup-lab .followup-controls{padding:12px;gap:12px 8px}#followup-lab .followup-controls label:first-child{grid-column:1/-1}#followup-lab .followup-controls label:last-child{grid-column:1/-1}#followup-lab .followup-columns{grid-template-columns:1fr}#followup-lab .followup-section-heading{align-items:start;flex-wrap:wrap}#followup-lab .followup-readiness{padding:18px 14px}#followup-lab .followup-requirements{grid-template-columns:1fr}}
"""


FOLLOWUP_HTML = r"""
<section id="followup-lab" aria-labelledby="followup-heading">
  <div class="followup-heading"><div><span class="followup-eyebrow">FOLLOW-UP ADJUSTMENTS</span><h3 id="followup-heading">复诊时，处方为何调整？</h3><p>先看相邻两次合格就诊间发生了哪些加减，再关联本次开方前的症状与证候记录。</p></div><span class="followup-stage-badge">当前支持<br>处方变化描述</span></div>
  <ol class="followup-timeline" aria-label="相邻两次合格就诊的研究示意，不表示某位患者的实际记录"><li><span>01 · 同一患者</span><strong>上次合格就诊 · 处方 A</strong><p>保留上次用药集合，作为相邻处方比较的起点。</p></li><li><span>02 · 本次开方前</span><strong>症状与证候 · 待关联</strong><p>具有明确时间顺序的临床记录，用于分析记录变化与调方的关联。</p></li><li><span>03 · 本次合格就诊</span><strong>处方 B · 加减方向</strong><p>加药＝B 中新增；减药＝A 中移除；保留＝两次均有。</p></li></ol>
  <p class="followup-scope" id="followup-scope"></p>
  <dl class="followup-summary" id="followup-summary"></dl>
  <p class="followup-note">上方指标取当前组与分层的全观察期纵向汇总。患者等权中位 Jaccard：先取每名患者相邻转移的中位数，再取患者间中位数；描述处方连续性，不表示调整原因或预测效果。</p>
  <div class="followup-availability" id="followup-availability"></div>
  <div class="followup-controls"><label>疾病／共病组<select id="followup-group"></select></label><label>观察时期<select id="followup-period"></select></label><label>变化方向<select id="followup-direction"><option value="both">加药与减药</option><option value="addition">仅加药</option><option value="removal">仅减药</option></select></label><label>聚焦药味 · 查看年度<select id="followup-item"></select></label></div>
  <div class="followup-actions"><p class="followup-note" id="followup-status" role="status" aria-live="polite"></p><button type="button" class="followup-button" id="followup-export" disabled>导出当前加减 CSV</button></div>
  <div class="followup-columns" id="followup-columns" data-direction="both"><article class="followup-column addition" id="followup-addition-panel"><header><h4>＋ 复诊加药</h4><span>发生患者占比</span></header><div id="followup-additions"></div></article><article class="followup-column removal" id="followup-removal-panel"><header><h4>− 复诊减药</h4><span>发生患者占比</span></header><div id="followup-removals"></div></article></div>
  <p class="followup-note">“发生患者占比”按发生过该方向的复诊患者计算；“患者等权复诊频率”先在患者内计算转移比例，再对患者等权平均。事件克数是加药／减药事件中的原有剂量汇总，不是前后剂量差。</p>
  <div class="followup-section-heading"><h4 id="followup-annual-heading">聚焦药味 · 年度加减对照</h4><button type="button" class="followup-button" id="followup-export-annual" disabled>导出该药年度 CSV</button></div>
  <p class="followup-note" id="followup-annual-note"></p><div id="followup-annual"></div>
  <p class="research-status" id="followup-export-status" role="status" aria-live="polite"></p>
  <section class="followup-readiness" aria-labelledby="followup-readiness-heading"><h4 id="followup-readiness-heading">下一步：关联开方前临床记录</h4><p class="followup-note">当前汇总未提供可连接到相邻就诊的症状、证候与经核验医师标识。以下为研究准备要求，未生成临床原因、医师风格或疗效结论。</p><div class="followup-tabs" role="tablist" aria-label="复诊加减研究准备"><button class="followup-button" type="button" role="tab" id="followup-clinical-tab" aria-controls="followup-clinical-panel" aria-selected="true">临床记录关联</button><button class="followup-button" type="button" role="tab" id="followup-benchmark-tab" aria-controls="followup-benchmark-panel" aria-selected="false" tabindex="-1">连续性基线与评估</button></div>
    <div id="followup-clinical-panel" role="tabpanel" aria-labelledby="followup-clinical-tab"><ul class="followup-requirements"><li><b>开方前观察</b>将症状、体征与检验标注为本次处方前已知；后续疗效作为独立结局。</li><li><b>独立证候标签</b>证候参考由临床记录独立标注；本次处方不作为开方前证候推理的诊断输入。</li><li><b>医师与时间顺序</b>先核验医师标识、患者和相邻就诊关系；同日顺序不清时单独处理。</li><li><b>剂量与缺失</b>同药两次剂量均为单一正值、单位明确一致时才判定增减；冲突与缺失保留为未解决。</li></ul></div>
    <div id="followup-benchmark-panel" role="tabpanel" aria-labelledby="followup-benchmark-tab" hidden><div class="followup-benchmark"><b>先比较“沿用上次处方”的强基线。</b><br>处方高度连续时，原样沿用也可能有较高集合相似度；它对真正发生的新增与移除事件召回均为 0。总体 Jaccard 只作连续性背景，还需分别报告加药、减药、无变化相邻对、保留药味及可靠单位剂量变化。没有相关事件时，精确率或召回率保持未定义。</div><p class="followup-note">未来模型与该基线使用同一批固定相邻对；患者在开发与测试间分离，时间窗预先定义，区间估计保留患者聚类。已知患者的后期评估单独标注。当前页面没有训练模型，也未把历史连续性当作留出测试性能。</p></div>
    <button type="button" class="followup-button" id="followup-checklist">下载研究任务清单</button><p class="followup-note">下载内容为任务代码与待完成状态，不含病例、临床标注或人工验证结果。</p>
  </section>
  <details class="followup-legacy"><summary>展开原有处方轨迹与加减明细</summary>__FOLLOWUP_LEGACY__</details>
</section>
"""


FOLLOWUP_JS = r"""
(() => {
  'use strict';
  const byId=id=>document.getElementById(id),baseRender=render,baseCapture=captureViewState,baseApply=applyViewState,baseReset=resetDashboardView;
  let state={key:'',period:'all',direction:'both',item:''},pending=null,resetRequested=false;
  const enabled=()=>!data.privacy||data.privacy.longitudinal_enabled===true;
  const key=()=>JSON.stringify([data.source_identity?.key||provenance.dataset_id||'',selected,data.clinicalMode?stratumType:'overall',data.clinicalMode?stratum:'all']);
  const context=rows=>forContext(Array.isArray(rows)?rows:[]);
  const changeRows=annual=>enabled()?context(annual?data.yearChanges:data.changes).filter(row=>['addition','removal'].includes(row.change_type)):[];
  const searched=rows=>rows.filter(row=>!query||String(row.item_name||'').toLowerCase().includes(query.toLowerCase()));
  const validYear=value=>/^\d{4}$/.test(String(value));
  function years(){
    const values=[...new Set([...changeRows(true),...(enabled()?context(data.yearSummaries):[])].map(row=>String(row.year)).filter(validYear))].sort();
    if(values.length&&Number(values.at(-1))-Number(values[0])<=100)return Array.from({length:Number(values.at(-1))-Number(values[0])+1},(_,index)=>String(Number(values[0])+index));
    return values;
  }
  const rowsForPeriod=()=>state.period==='all'?changeRows(false):changeRows(true).filter(row=>String(row.year)===state.period);
  const ordered=rows=>[...rows].sort((a,b)=>(disclosed(b.patient_prevalence)?Number(b.patient_prevalence):-1)-(disclosed(a.patient_prevalence)?Number(a.patient_prevalence):-1)||String(a.item_name).localeCompare(String(b.item_name),'zh-CN'));
  const displayed=type=>state.direction!=='both'&&state.direction!==type?[]:ordered(searched(rowsForPeriod()).filter(row=>row.change_type===type)).slice(0,limit);
  const selectedAnnual=()=>changeRows(true).filter(row=>row.item_name===state.item);
  const absent=message=>`<p class="empty">${escapeHtml(message)}</p>`;
  const measure=(value,kind)=>escapeHtml(metricText(value,kind));
  function changeMarkup(row){
    const value=disclosed(row.patient_prevalence)?Math.min(100,Math.max(0,Number(row.patient_prevalence)*100)):null;
    return `<div class="followup-change" data-selected="${row.item_name===state.item}"><div><button type="button" class="followup-drug" data-followup-item="${escapeHtml(row.item_name)}" aria-pressed="${row.item_name===state.item}">${escapeHtml(row.item_name)}</button><strong>${measure(row.patient_prevalence,'percent')}</strong></div><p>${measure(row.patients_with_change)} / ${measure(row.repeat_patients)} 名复诊患者</p>${value===null?'':`<div class="followup-measure" aria-hidden="true"><span><i style="width:${value}%"></i></span></div>`}<p>患者等权复诊频率 <b>${measure(row.mean_patient_transition_fraction,'percent')}</b></p><p>事件剂量 · ${escapeHtml(doseDetail(row))}</p></div>`;
  }
  function renderAnnualRows(){
    byId('followup-annual-heading').textContent=state.item?`${state.item} · 年度加减对照`:'聚焦药味 · 年度加减对照';
    byId('followup-annual-note').textContent='按后一次就诊年份归属，沿用原有患者年分母与患者等权频率。缺失方向或年份标记未公开；此处为描述性对照，未检验时间稳定性。';
    const records=selectedAnnual(),available=years();
    byId('followup-export-annual').disabled=!records.length;
    if(!enabled()||!state.item||!available.length){byId('followup-annual').innerHTML=absent(!enabled()?'当前展示策略未开放纵向变化。':'当前药味或分层没有可公开的年度加减记录。');return}
    const cell=(row,field,kind)=>row?measure(row[field],kind):'<span class="followup-value-missing">未公开</span>';
    const count=row=>row?`${measure(row.patients_with_change)} / ${measure(row.repeat_patients)}`:'<span class="followup-value-missing">未公开</span>';
    const body=available.map(year=>{
      // A duplicate scope is ambiguous. Never choose a convenient denominator.
      const unique=type=>{const matches=records.filter(row=>String(row.year)===year&&row.change_type===type);return matches.length===1?matches[0]:null};
      const added=unique('addition'),removed=unique('removal');
      return `<tr data-period-selected="${year===state.period}"><td>${escapeHtml(year)}</td><td>${count(added)}</td><td>${cell(added,'patient_prevalence','percent')}</td><td>${cell(added,'mean_patient_transition_fraction','percent')}</td><td>${count(removed)}</td><td>${cell(removed,'patient_prevalence','percent')}</td><td>${cell(removed,'mean_patient_transition_fraction','percent')}</td></tr>`;
    }).join('');
    byId('followup-annual').innerHTML=`<p class="table-scroll-hint">左右滑动查看两种方向；人数为发生患者 / 复诊患者。</p><div class="research-table-wrap" tabindex="0" role="region" aria-label="聚焦药味的年度加减数值"><table class="research-table followup-year-table"><thead><tr><th scope="col">年份</th><th scope="col">加药人数</th><th scope="col">加药患者占比</th><th scope="col">加药等权频率</th><th scope="col">减药人数</th><th scope="col">减药患者占比</th><th scope="col">减药等权频率</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }
  function renderFollowup(){
    const currentKey=key();
    if(resetRequested||state.key!==currentKey){state={key:currentKey,period:'all',direction:'both',item:''};resetRequested=false}
    if(pending){if(pending.key===currentKey)state={key:currentKey,period:String(pending.period||'all'),direction:['both','addition','removal'].includes(pending.direction)?pending.direction:'both',item:String(pending.item||'')};else if(pending.reset)state={key:currentKey,period:'all',direction:'both',item:''}}
    const availableYears=years();if(state.period!=='all'&&!availableYears.includes(state.period))state.period='all';
    const names=[...new Set(searched([...changeRows(false),...changeRows(true)]).map(row=>String(row.item_name)))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
    if(!names.includes(state.item))state.item=names[0]||'';
    const source=data.source_identity?.title||provenance.dataset_id||'来源未标注',group=groupLabel(data.groups.find(row=>row.code===selected)?.label||selected||'无公开组'),stratumLabel=data.clinicalMode?(stratumType==='overall'?'全部患者':currentSummary().stratum_label||stratum):'原有分析组';
    byId('followup-scope').textContent=`${source} · ${group} · ${stratumLabel} · ${data.clinicalMode?'临床疾病标签与公开分层':'原有分析分组'}。来源独立统计；本模块不调用严格单病研究队列。`;
    const candidates=enabled()?context(data.longitudinal):[],longitudinal=candidates.length===1?candidates[0]:{};
    byId('followup-summary').innerHTML=[['全观察期复诊患者',longitudinal.repeat_patients],['全观察期相邻转移',longitudinal.transitions],['患者等权中位 Jaccard',longitudinal.median_patient_jaccard,'percent']].map(([label,value,kind])=>`<div><dt>${escapeHtml(label)}</dt><dd>${measure(value,kind)}</dd></div>`).join('');
    byId('followup-availability').innerHTML=`<span>${enabled()?'加药／减药 · 公开记录可查看':'纵向变化 · 当前策略未开放'}</span><span>保留药味汇总 · 未提供</span><span>同药剂量增减 · 未提供</span><span>开方前症状／证候 · 待关联</span>`;
    byId('followup-group').innerHTML=data.groups.map(group=>`<option value="${escapeHtml(group.code)}">${escapeHtml(groupLabel(group.label))}</option>`).join('');byId('followup-group').value=selected;byId('followup-group').disabled=!data.groups.length;
    byId('followup-period').innerHTML='<option value="all">全观察期</option>'+availableYears.map(year=>`<option value="${escapeHtml(year)}">${escapeHtml(year)} 年</option>`).join('');byId('followup-period').value=state.period;byId('followup-period').disabled=!enabled()||!availableYears.length;
    byId('followup-direction').value=state.direction;byId('followup-direction').disabled=!enabled();
    byId('followup-item').innerHTML=names.map(name=>`<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');byId('followup-item').value=state.item;byId('followup-item').disabled=!names.length;
    byId('followup-columns').dataset.direction=state.direction;
    const adds=displayed('addition'),removals=displayed('removal');
    for(const [direction,rows,target] of [['addition',adds,'followup-additions'],['removal',removals,'followup-removals']]){byId(`followup-${direction}-panel`).hidden=state.direction!=='both'&&state.direction!==direction;byId(target).innerHTML=rows.length?rows.map(changeMarkup).join(''):absent(!enabled()?'当前展示策略未开放纵向变化。':'当前时期、分层与搜索没有该方向的公开记录；未公开不等于零。')}
    const matching=searched(rowsForPeriod()).filter(row=>state.direction==='both'||row.change_type===state.direction);
    byId('followup-status').textContent=`${state.period==='all'?'全观察期':state.period+' 年'} · 展示 ${adds.length+removals.length} / ${matching.length} 条公开方向记录（每方向最多 ${limit} 条）${query?' · 沿用药味搜索：'+query:''}。点击药名查看年度对照。`;
    byId('followup-export').disabled=!adds.length&&!removals.length;byId('followup-export-status').textContent='';renderAnnualRows();
  }
  function exportRows(rows,kind){
    if(!enabled()||!rows.length)return;
    const columns=['group','stratum_type','stratum','year','item_name','change_type','repeat_patients','patients_with_change','patient_prevalence','mean_patient_transition_fraction','dose_patients','most_common_dose_values_g','most_common_dose_patients','most_common_dose_fraction','most_common_dose_tied'];
    const fields=['source_key','source_title','view_period','view_direction','view_query',...columns];
    const body=[fields,...rows.map(row=>[data.source_identity?.key||'',data.source_identity?.title||provenance.dataset_id||'',kind==='annual'?'all_disclosed_years':state.period,kind==='annual'?'both':state.direction,query,...columns.map(field=>row[field]??'')])].map(row=>row.map(safeCsvCell).join(',')).join('\r\n');
    downloadResearch(`mingyirx-followup-${kind}.csv`,'\uFEFF'+body,'text/csv;charset=utf-8','followup-export-status');
  }
  const switchLocal=(field,value)=>changeView(()=>{state[field]=value;renderFollowup()});
  // Search uses partial legacy renders. Run after its original input listener so
  // visible rows and export scope share the newly normalized global query.
  byId('search').addEventListener('input',renderFollowup);
  byId('followup-group').addEventListener('change',event=>selectDiseaseGroup(event.target.value));
  byId('followup-period').addEventListener('change',event=>switchLocal('period',event.target.value));
  byId('followup-direction').addEventListener('change',event=>switchLocal('direction',event.target.value));
  byId('followup-item').addEventListener('change',event=>switchLocal('item',event.target.value));
  byId('followup-columns').addEventListener('click',event=>{const button=event.target.closest?.('[data-followup-item]');if(button)switchLocal('item',button.getAttribute('data-followup-item'))});
  byId('followup-export').addEventListener('click',()=>exportRows([...displayed('addition'),...displayed('removal')],'view'));
  byId('followup-export-annual').addEventListener('click',()=>exportRows(selectedAnnual(),'annual'));
  byId('followup-checklist').addEventListener('click',()=>{
    const tasks=['VERIFY_ADJACENT_VISIT_ORDER','LINK_PRE_PRESCRIPTION_OBSERVATIONS','INDEPENDENT_SYNDROME_REFERENCE','VERIFY_PHYSICIAN_ID','PRESPECIFY_PATIENT_AND_TIME_SPLITS','ANNOTATE_ADDITION_REMOVAL_AND_DOSE','SEPARATE_LATER_OUTCOMES'];
    const result={schema_version:1,kind:'research_task_checklist',contract:'followup-adjustment-contract-v0.24.0',contains_case_data:false,contains_annotation_results:false,tasks:tasks.map(task_code=>({task_code,status:'not_started',evidence_status:'not_attached'}))};
    downloadResearch('mingyirx-followup-task-checklist.json',JSON.stringify(result,null,2),'application/json','followup-export-status');
  });
  const tabs=['clinical','benchmark'];
  function activateTab(name,focus=false){for(const item of tabs){const button=byId(`followup-${item}-tab`),active=item===name;button.setAttribute('aria-selected',String(active));button.setAttribute('tabindex',active?'0':'-1');byId(`followup-${item}-panel`).hidden=!active;if(active&&focus)button.focus({preventScroll:true})}}
  for(const name of tabs){const button=byId(`followup-${name}-tab`);button.addEventListener('click',()=>activateTab(name));button.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();activateTab(event.key==='Home'?'clinical':event.key==='End'?'benchmark':tabs.find(item=>item!==name),true)}})}
  render=(...args)=>{const result=baseRender(...args);renderFollowup();return result};
  captureViewState=()=>({...baseCapture(),followup_view:{...state}});
  applyViewState=view=>{pending=view?.followup_view||{reset:true};try{return baseApply(view)}finally{pending=null}};
  resetDashboardView=(...args)=>{resetRequested=true;const result=baseReset(...args);if(resetRequested&&!restoringView){state={key:'',period:'all',direction:'both',item:''};resetRequested=false}return result};
  renderFollowup();recordViewState(true);
})();
"""


def enhance_followup(page: str) -> str:
    """Insert an independent aggregate workbench while retaining all old flows."""
    if 'id="followup-ui-script"' in page:
        return page
    if 'id="network-interactive-script"' not in page or 'id="community-ui-script"' in page:
        raise DashboardError("Follow-up UI requires the network adapter before Community UI")
    marker = '<script id="supplement-data"' if '<script id="supplement-data"' in page else '<script id="dashboard-data"'
    if page.count(marker) != 1:
        raise DashboardError("Follow-up payload anchor is missing or ambiguous")
    markup, scripts = page.split(marker, 1)
    navs = list(re.finditer(r'<nav class="research-nav"[^>]*>.*?</nav>', markup, re.S))
    anchors = '<section class="section" id="annual-section"'
    if len(navs) != 1 or markup.count(anchors) != 1 or markup.count('</style>') != 1 or scripts.count('</body>') != 1:
        raise DashboardError("Follow-up presentation anchors are missing or ambiguous")
    legacy = []
    for title in ('\u5904\u65b9\u6f14\u53d8\u8f68\u8ff9', '\u590d\u8bca\u52a0\u51cf\u503e\u5411'):
        matches = list(re.finditer(r'<section class="section"><div class="section-head"><h3>' + title + r'</h3>.*?</section>', markup, re.S))
        if len(matches) != 1:
            raise DashboardError("Follow-up legacy section is missing or ambiguous")
        legacy.append(matches[0][0])
        markup = markup.replace(matches[0][0], '', 1)
    nav = navs[0][0].replace('>\u7eb5\u5411\u4e0e\u7f51\u7edc</a>', '>\u4e25\u683c\u961f\u5217\u7814\u7a76</a>', 1)
    markup = markup.replace(navs[0][0], nav.replace('</nav>', '<a href="#followup-lab">\u590d\u8bca\u52a0\u51cf</a></nav>', 1), 1)
    markup = markup.replace('<h3>\u7eb5\u5411\u7814\u7a76\u4e0e\u5171\u73b0\u7f51\u7edc</h3>', '<h3>\u72ec\u7acb\u4e25\u683c\u961f\u5217\u7814\u7a76</h3>', 1)
    markup = markup.replace(anchors, FOLLOWUP_HTML.replace('__FOLLOWUP_LEGACY__', ''.join(legacy)) + anchors, 1)
    markup = markup.replace('</style>', FOLLOWUP_CSS + '</style>', 1)
    return (markup + marker + scripts).replace('</body>', '<script id="followup-ui-script">' + FOLLOWUP_JS + '</script></body>', 1)
