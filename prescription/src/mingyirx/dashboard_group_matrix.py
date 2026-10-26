"""Accessible matrix of already disclosed, exact clinical label groups."""
from __future__ import annotations

from .dashboard import DashboardError


GROUP_MATRIX_CSS = r"""
#group-matrix-lab{min-width:0;margin:16px 0 22px;scroll-margin-top:var(--community-anchor-offset,142px)}
#group-matrix-lab [hidden]{display:none!important}
#group-matrix-lab .group-matrix-heading{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:8px}
#group-matrix-lab h4{font-size:21px;line-height:1.5;color:#244d3c;margin:0}
#group-matrix-lab p{font-size:12px;color:#546a5b;line-height:1.75;max-width:none;overflow-wrap:anywhere;margin:8px 0}
#group-matrix-lab .group-matrix-badge{flex:none;color:#70613f;background:#f1ecdc;border:1px solid #d2c5a2;border-radius:5px;padding:5px 9px;font-size:10px}
#group-matrix-lab .group-matrix-scroll{max-width:100%;overflow-x:auto;overscroll-behavior-x:contain;border:1px solid #b9cdbd;border-radius:10px;background:#fcfdf8;scrollbar-color:#819f86 #edf2e8;scrollbar-width:thin}
#group-matrix-lab .group-matrix-chart{table-layout:fixed;border-collapse:separate;border-spacing:0;margin:0;width:100%;color:#294d3b}
#group-matrix-lab .group-matrix-chart :is(th,td){box-sizing:border-box;text-align:center;border:0;border-right:1px solid #dce5d7;padding:0;vertical-align:middle;background:transparent}
#group-matrix-lab .group-matrix-chart tr:last-child td{padding-bottom:12px}
#group-matrix-lab .group-matrix-chart th:first-child{position:sticky;left:0;z-index:2;text-align:left;width:156px;background:#f0f5e9;border-right:1px solid #b9cdbd;padding:10px 14px;font-size:12px;font-weight:500;line-height:1.6;overflow-wrap:anywhere}
#group-matrix-lab .group-matrix-chart thead th:first-child{vertical-align:bottom;padding-bottom:18px;font-size:11px}
#group-matrix-lab .group-matrix-chart td{height:46px;cursor:pointer}
#group-matrix-lab .group-matrix-chart [data-active="true"]{background:#e8f1df}
#group-matrix-lab .group-matrix-column{width:100%;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;min-height:205px;padding:14px 8px 10px;border:0;border-bottom:1px solid #cbd9c4;background:transparent;color:#365a42;cursor:pointer;font:inherit}
#group-matrix-lab .group-matrix-column:hover{background:#eaf2e1}
#group-matrix-lab .group-matrix-column strong{font:600 20px/1.5 ui-monospace,monospace;color:#224d38;margin-bottom:3px}
#group-matrix-lab .group-matrix-bar-space{height:96px;display:flex;align-items:flex-end;width:42px;margin:0 auto 10px;border-bottom:1px solid #a9bda7}
#group-matrix-lab .group-matrix-bar{display:block;width:100%;border-radius:5px 5px 0 0;background:linear-gradient(#729f7d,#315d46);box-shadow:inset 0 1px #a1bc9d}
#group-matrix-lab [aria-pressed="true"] .group-matrix-bar{background:linear-gradient(#c1a468,#96763b)}
#group-matrix-lab .group-matrix-column-label{font-size:11px;line-height:1.65;overflow-wrap:anywhere;white-space:normal;min-height:38px;width:100%}
#group-matrix-lab .group-matrix-cell{display:flex;justify-content:center;align-items:center;position:relative;min-height:46px}
#group-matrix-lab .group-matrix-line{position:absolute;left:50%;top:0;bottom:0;width:2px;background:#728f6f;transform:translateX(-50%)}
#group-matrix-lab .group-matrix-dot{position:relative;z-index:1;display:block;width:12px;height:12px;border-radius:50%;background:#d8e1d2;border:1px solid #c0cebb}
#group-matrix-lab .group-matrix-dot[data-member="yes"]{background:#2d5e42;border:2px solid #fcfdf8;box-shadow:0 0 0 1px #2d5e42}
#group-matrix-lab .group-matrix-dot[data-member="unknown"]{width:auto;height:auto;background:none;border:0;font:600 14px/1 monospace;color:#87734b}
#group-matrix-lab [data-active="true"] .group-matrix-dot[data-member="yes"]{background:#947239;box-shadow:0 0 0 1px #947239}
#group-matrix-lab .group-matrix-scope{border-left:3px solid #74936d;padding-left:10px;color:#36583d}
#group-matrix-lab details{margin-top:12px;border-top:1px solid #cbd8c3}
#group-matrix-lab summary{min-height:44px;padding:12px 2px;cursor:pointer;color:#435f48;font-size:12px;line-height:1.6}
#group-matrix-lab .group-matrix-values{width:100%;min-width:600px;border-collapse:collapse;font-size:12px}
#group-matrix-lab .group-matrix-values :is(th,td){padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid #d4dfcd;line-height:1.6;overflow-wrap:anywhere}
#group-matrix-lab .group-matrix-values th{background:#eef4e6;font-weight:500}
#group-matrix-lab .group-matrix-values button{min-height:44px;border:0;background:transparent;color:#24523b;padding:8px 0;font:inherit;text-align:left;cursor:pointer;overflow-wrap:anywhere}
#group-matrix-lab .group-matrix-values tr[data-active="true"]{background:#e8f1df}
#group-matrix-lab :is(button,summary,[tabindex]):focus-visible{outline:2px solid #9b7b3e;outline-offset:-3px}
.group-matrix-legacy>summary{font-size:12px;color:#526b56;cursor:pointer;min-height:44px;padding:12px 0}
@media(max-width:600px){#group-matrix-lab .group-matrix-heading{flex-wrap:wrap;gap:7px}#group-matrix-lab h4{font-size:19px}#group-matrix-lab .group-matrix-chart th:first-child{width:130px;padding:8px 10px;font-size:11px}}
"""


GROUP_MATRIX_HTML = r"""
<section id="group-matrix-lab" aria-labelledby="group-matrix-title">
  <div class="group-matrix-heading"><h4 id="group-matrix-title">疾病标签组合矩阵</h4><span class="group-matrix-badge">已公开的精确分组</span></div>
  <p id="group-matrix-description">每列对应一个已公开的疾病标签组合，圆点表示该组记录中包含的标签；上方柱高表示该组患者数。点击一列，联动药味与复诊加减。左右方向键可移动列焦点。</p>
  <p id="group-matrix-scope" class="group-matrix-scope" role="status" aria-live="polite"></p>
  <div id="group-matrix-scroll" class="group-matrix-scroll" tabindex="0" role="region" aria-label="疾病标签组合矩阵，可左右滚动" aria-describedby="group-matrix-description"><div id="group-matrix-chart"></div></div>
  <p id="group-matrix-empty" class="empty" hidden></p>
  <p id="group-matrix-caption">实心圆表示包含，浅色圆表示该精确组合未包含；问号表示成员定义未提供。分组基于观察期内记录标签，不表示每次就诊均经临床确诊。仅展示已公开组合。</p>
  <details id="group-matrix-table-details"><summary>展开分组数值表与就诊分母</summary><div class="group-matrix-scroll" tabindex="0" role="region" aria-label="疾病分组数值表，可左右滚动"><div id="group-matrix-table"></div></div></details>
</section>
"""


GROUP_MATRIX_JS = r"""
(() => {
  'use strict';
  const byId=id=>document.getElementById(id),baseRender=render;
  const count=value=>((typeof value==='string'&&/^\d+$/.test(value.trim()))||typeof value==='number')&&Number.isSafeInteger(Number(value))&&Number(value)>=0?Number(value):null;
  const shown=value=>count(value)===null?'未公开':String(value);
  function records(){
    const groups=Array.isArray(data.groups)?data.groups:[],summaries=Array.isArray(data.summaries)?data.summaries:[];
    const labels=new Map(),codes=new Map();
    for(const group of groups)codes.set(group.code,(codes.get(group.code)||0)+1);
    const rows=groups.map(group=>{
      const parts=String(group.code||'').split('__'),names=String(group.label||'').split(' + '),size=count(group.disease_count);
      const valid=Boolean(group.code)&&codes.get(group.code)===1&&size!==null&&size>0&&parts.length===size&&names.length===size&&new Set(parts).size===size&&parts.every(Boolean)&&names.every(name=>name.trim());
      if(valid)parts.forEach((code,index)=>{if(!labels.has(code))labels.set(code,new Set());labels.get(code).add(names[index])});
      const matches=summaries.filter(row=>row.group===group.code&&row.stratum_type==='overall'&&row.stratum==='all');
      // Never fall back from an explicitly suppressed field to another row.
      const visits=Object.hasOwn(group,'visits')?group.visits:matches.length===1?matches[0].visits:undefined;
      return {group,parts,names,valid,patients:count(group.patients),visits};
    });
    const members=[...labels].filter(([,values])=>values.size===1).map(([code,values])=>({code,label:[...values][0]}));
    for(const row of rows)row.valid=row.valid&&row.parts.every(code=>labels.get(code)?.size===1);
    return {rows,members};
  }
  function choose(code,origin){
    if(!data.groups.some(group=>group.code===code))return;
    // The original handler owns navigation, history and downstream follow-up.
    // Its overview flag clears a hiding sidebar filter, but not strictGroup.
    const x=globalThis.scrollX||0,y=globalThis.scrollY||0;
    selectDiseaseGroup(code,true);
    if(typeof scrollTo==='function')scrollTo({left:x,top:y,behavior:'instant'});
    const target=byId(origin==='table'?'group-matrix-table':'group-matrix-chart');
    [...target.querySelectorAll('[data-group-choice]')].find(button=>button.dataset.groupChoice===code)?.focus({preventScroll:true});
  }
  function renderMatrix(){
    const section=byId('group-matrix-lab');section.hidden=!data.clinicalMode;
    if(section.hidden)return;
    const {rows,members}=records(),available=rows.length>0;
    byId('group-matrix-scroll').hidden=!available;byId('group-matrix-table-details').hidden=!available;byId('group-matrix-empty').hidden=available;
    byId('group-matrix-empty').textContent='当前来源没有已公开的精确疾病分组。可切换来源查看已有汇总。';
    const active=rows.find(row=>row.group.code===selected);
    byId('group-matrix-scope').textContent=`${data.source_identity?.title||provenance.dataset_id||'当前来源'} · ${rows.length} 个已公开组合 · 当前选择：${active?groupLabel(active.group.label):'未选择'}。矩阵显示各组全部患者；当前工作区分层与严格研究队列独立保留。`;
    if(!available){byId('group-matrix-chart').innerHTML='';byId('group-matrix-table').innerHTML='';return}
    const max=Math.max(1,...rows.map(row=>row.patients??0)),width=156+rows.length*124;
    const button=(row,index)=>`<button type="button" class="group-matrix-column" data-group-choice="${escapeHtml(row.group.code)}" aria-pressed="${row.group.code===selected}" aria-label="选择 ${escapeHtml(groupLabel(row.group.label))}，${escapeHtml(shown(row.group.patients))}名患者"><strong>${escapeHtml(shown(row.group.patients))}</strong><span class="group-matrix-bar-space" aria-hidden="true">${row.patients===null?'':`<i class="group-matrix-bar" style="height:${row.patients/max*100}%"></i>`}</span><span class="group-matrix-column-label">${escapeHtml(groupLabel(row.group.label)||`分组 ${index+1}`)}</span></button>`;
    const header='<thead><tr><th scope="col">患者数<br>记录疾病标签 ↓</th>'+rows.map((row,index)=>`<th scope="col" data-active="${row.group.code===selected}">${button(row,index)}</th>`).join('')+'</tr></thead>';
    const body=members.map((member,index)=>'<tr><th scope="row">'+escapeHtml(groupLabel(member.label))+'</th>'+rows.map(row=>{
      const included=row.valid&&row.parts.includes(member.code),status=!row.valid?'unknown':included?'yes':'no';
      const indices=row.valid?members.map((value,i)=>row.parts.includes(value.code)?i:-1).filter(i=>i>=0):[];
      const line=indices.length>1&&index>=Math.min(...indices)&&index<=Math.max(...indices)?`<i class="group-matrix-line" aria-hidden="true" style="${index===Math.min(...indices)?'top:50%;':''}${index===Math.max(...indices)?'bottom:50%;':''}"></i>`:'';
      return `<td data-group-column="${escapeHtml(row.group.code)}" data-active="${row.group.code===selected}" aria-label="${!row.valid?'成员定义未提供':included?'包含':'该组合未包含'}"><span class="group-matrix-cell" aria-hidden="true">${line}<i class="group-matrix-dot" data-member="${status}">${status==='unknown'?'?':''}</i></span></td>`;
    }).join('')+'</tr>').join('');
    byId('group-matrix-chart').innerHTML=`<table class="group-matrix-chart" style="min-width:${width}px" aria-label="已公开的精确疾病组合与原始患者数">${header}<tbody>${body||'<tr><th scope="row">成员定义</th>'+rows.map(()=>'<td>未提供</td>').join('')+'</tr>'}</tbody></table>`;
    byId('group-matrix-table').innerHTML='<table class="group-matrix-values"><thead><tr><th scope="col">精确疾病组</th><th scope="col">记录标签成员</th><th scope="col">患者数</th><th scope="col">合格就诊数</th></tr></thead><tbody>'+rows.map(row=>`<tr data-active="${row.group.code===selected}"><th scope="row"><button type="button" data-group-choice="${escapeHtml(row.group.code)}" aria-pressed="${row.group.code===selected}">${escapeHtml(groupLabel(row.group.label)||row.group.code)}</button></th><td>${row.valid?row.names.map(name=>escapeHtml(groupLabel(name))).join('；'):'成员定义未提供'}</td><td>${escapeHtml(shown(row.group.patients))}</td><td>${escapeHtml(shown(row.visits))}</td></tr>`).join('')+'</tbody></table>';
  }
  for(const [id,origin] of [['group-matrix-chart','chart'],['group-matrix-table','table']]){
    const target=byId(id);
    target.addEventListener('click',event=>{const button=event.target.closest?.('[data-group-choice],[data-group-column]');if(button&&target.contains(button))choose(button.dataset.groupChoice||button.dataset.groupColumn,origin)});
    target.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      const button=event.target.closest?.('[data-group-choice]'),buttons=[...target.querySelectorAll('[data-group-choice]')],index=buttons.indexOf(button);if(index<0)return;
      event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;
      buttons[next].focus({preventScroll:true});buttons[next].scrollIntoView?.({block:'nearest',inline:'nearest'});
    });
  }
  render=(...args)=>{const result=baseRender(...args);renderMatrix();return result};
  renderMatrix();
})();
"""


def enhance_group_matrix(page: str) -> str:
    """Add the exact-group matrix without rewriting source rows or handlers."""
    if 'id="group-matrix-script"' in page:
        return page
    marker = '<script id="supplement-data"' if '<script id="supplement-data"' in page else '<script id="dashboard-data"'
    if page.count(marker) != 1:
        raise DashboardError("Group matrix payload anchor is missing or ambiguous")
    markup, scripts = page.split(marker, 1)
    anchor = '<div class="overview-groups" id="overview-groups"></div>'
    if markup.count(anchor) != 1 or markup.count('</style>') != 1 or scripts.count('</body>') != 1:
        raise DashboardError("Group matrix presentation anchors are missing or ambiguous")
    markup = markup.replace(anchor, GROUP_MATRIX_HTML + '<details class="group-matrix-legacy"><summary>展开原有分组卡片</summary>' + anchor + '</details>', 1)
    markup = markup.replace('</style>', GROUP_MATRIX_CSS + '</style>', 1)
    script = '<script id="group-matrix-script">' + GROUP_MATRIX_JS + '</script>'
    return (markup + marker + scripts).replace('</body>', script + '</body>', 1)
