"""Same-source fixed-frame comparison of disclosed strict cohort networks."""
from __future__ import annotations

from .dashboard import DashboardError


COMPARE_HTML = r"""
<section id="network-comparison" aria-labelledby="network-comparison-title">
  <div class="network-comparison-heading"><div><span class="network-eyebrow">FIXED-FRAME COMPARISON</span><h4 id="network-comparison-title">同一坐标，对照两个严格队列</h4><p id="network-comparison-source"></p></div><button type="button" class="filter-btn" id="network-compare-export">导出对照 JSON</button></div>
  <p class="network-comparison-caption">两侧共用药味坐标与视角。拖动任一画布同时旋转，点选药味同时查看两组原值；空间距离仅用于布局。首诊分析分母各自保留。</p>
  <div id="network-compare-unavailable" class="empty" hidden></div>
  <div id="network-compare-content">
    <div class="network-comparison-tools"><label>左侧严格队列<select id="network-compare-left"></select></label><label>右侧严格队列<select id="network-compare-right"></select></label><label>两侧定位药味<select id="network-compare-drug"></select></label><div><button class="filter-btn" type="button" id="network-compare-minus" aria-label="缩小两个对照网络">−</button><button class="filter-btn" type="button" id="network-compare-plus" aria-label="放大两个对照网络">＋</button><button class="filter-btn" type="button" id="network-compare-reset">重置共同视角</button></div></div>
    <div class="network-comparison-grid"><article><h5 id="network-compare-left-title"></h5><p id="network-compare-left-scope"></p><div class="network-compare-scene" id="network-compare-left-scene" tabindex="0" role="region" aria-label="左侧严格队列网络，方向键旋转共同视角"></div><p id="network-compare-left-value" class="network-compare-value" role="status"></p></article><article><h5 id="network-compare-right-title"></h5><p id="network-compare-right-scope"></p><div class="network-compare-scene" id="network-compare-right-scene" tabindex="0" role="region" aria-label="右侧严格队列网络，方向键旋转共同视角"></div><p id="network-compare-right-value" class="network-compare-value" role="status"></p></article></div>
    <div id="network-compare-detail" class="network-compare-detail" role="status" aria-live="polite"></div>
    <details class="network-data-details"><summary id="network-compare-table-title">药味原值与关联对照表</summary><div id="network-compare-nodes-table"></div><div id="network-compare-edges-table"></div></details>
  </div><p id="network-compare-export-status" role="status" aria-live="polite"></p>
</section>
"""

COMPARE_CSS = r"""
#network-comparison{margin-top:24px;padding:24px;border:1px solid #c8d8cd;border-radius:15px;background:#f5f8f2;color:#173f36;min-width:0;scroll-margin-top:100px}
.network-comparison-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}.network-comparison-heading h4{margin:6px 0;font-size:24px;font-weight:650;letter-spacing:-.4px}.network-comparison-heading p,.network-comparison-caption{font-size:12px;line-height:1.8;color:#567468;margin:6px 0 14px}.network-comparison-caption{max-width:85ch}
.network-comparison-tools{display:flex;align-items:end;gap:12px;flex-wrap:wrap;margin:18px 0}.network-comparison-tools label{display:grid;gap:6px;flex:1;min-width:150px;font-size:12px}.network-comparison-tools select{width:100%;min-height:44px;border:1px solid #b7cfc0;border-radius:7px;background:white;color:#173f36;padding:8px;max-width:100%}.network-comparison-tools>div{display:flex;gap:6px;flex-wrap:wrap}.network-comparison-tools button{min-height:44px}
.network-comparison-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.network-comparison-grid article{border:1px solid #c6d7cb;border-radius:11px;overflow:hidden;min-width:0;background:#edf3e9}.network-comparison-grid h5{font-size:16px;margin:16px 16px 5px;overflow-wrap:anywhere}.network-comparison-grid article>p{margin:0;padding:6px 16px 14px;font-size:11px;line-height:1.8;overflow-wrap:anywhere}.network-compare-scene{height:380px;background:#0c302a;touch-action:pan-y;cursor:grab;overflow:hidden;outline-offset:-4px}.network-compare-scene:focus-visible{outline:3px solid #d7b877}.network-compare-scene svg{display:block;width:100%;height:100%}.network-compare-scene [data-compare-node],.network-compare-scene [data-compare-edge]{cursor:pointer;outline:none}.network-compare-scene [data-compare-node]:focus-visible circle{stroke:white;stroke-width:4}.network-compare-scene [data-compare-edge]:focus-visible{stroke:#fff;stroke-opacity:.65}.network-compare-scene text{pointer-events:none;paint-order:stroke;stroke:#0c302a;stroke-width:3;stroke-linejoin:round}
.network-comparison-grid .network-compare-value{background:#e2ebdb;min-height:62px;padding-top:12px;font-size:12px}.network-compare-detail{font-size:12px;line-height:1.8;margin:14px 0;padding:14px 16px;border-left:3px solid #b28b43;background:#eaf0e4;overflow-wrap:anywhere}.network-compare-detail h5{font-size:16px;margin:0 0 5px}.network-compare-detail p{margin:5px 0}.network-comparison-grid [hidden],#network-comparison [hidden]{display:none!important}#network-compare-nodes-table,#network-compare-edges-table{max-width:100%;overflow:auto}#network-comparison .research-table{min-width:580px}#network-comparison button{overflow-wrap:anywhere}
@media(max-width:950px){.network-comparison-grid{grid-template-columns:1fr}.network-compare-scene{height:380px}}@media(max-width:600px){#network-comparison{padding:14px;border-radius:10px}.network-comparison-heading h4{font-size:21px}.network-comparison-tools{gap:10px}.network-comparison-tools label{flex-basis:100%;min-width:0}.network-compare-scene{height:320px}.network-comparison-heading button{min-height:44px}.network-comparison-grid h5{margin:13px 12px 4px}.network-comparison-grid article>p{padding-left:12px;padding-right:12px}}
"""

COMPARE_JS = r"""
const MingYiRxNetworkCompare = (()=>{
  'use strict';
  const byId=id=>document.getElementById(id),bridge=MingYiRxNetwork,space=MingYiRxNetwork3D,sides=['left','right'],W=640,H=480;
  const state={source:'',left:'',right:'',selected:'',panels:{},camera:space.getCamera(),available:false,pending:null,drag:null,focused:null,suppressClick:false,rebuilding:false};
  const sourceKey=()=>data.source_identity?.key||provenance.dataset_id||'';
  let resetRequested=false;
  const sourceTitle=()=>data.source_identity?.title||provenance.dataset_id||'来源未核实';
  const groupName=key=>groupLabel(researchRows('cohorts').find(row=>row.group===key)?.label||key);
  const metric=(value,type='number')=>escapeHtml(metricText(value,type));
  const pairKey=(a,b)=>JSON.stringify([a,b].sort());
  function availableGroups(){return researchRows('cohorts').filter(row=>researchRows('nodes').some(node=>node.group===row.group))}
  function panel(group){
    const sourceNodes=researchRows('nodes').filter(row=>row.group===group),nodes=usageOrder(sourceNodes.map(row=>row.item_name)).map(name=>sourceNodes.find(row=>row.item_name===name));
    const edges=researchRows('edges').filter(row=>row.group===group),snapshot=bridge.getSnapshot(),graph=bridge.project(nodes,edges,state.selected,'all',snapshot.edgeLimit);
    const cohort=researchRows('cohorts').find(row=>row.group===group),layout=space.layout(graph.nodes,researchRows('nodes'));
    return {group,cohort:cohort?{...cohort}:null,graph,layout};
  }
  function values(row){return row?`首诊使用 ${metric(row.exposed_patients)} / ${metric(row.patients)} 人 · 覆盖率 ${metric(row.prevalence,'percent')}`:'此药味在该队列未公开 / 不可用；不按零处理。'}
  function edgeValues(row){return row?`共现 ${metric(row.cooccurrence_patients)} 人 · 支持度 ${metric(row.support,'percent')} · 余弦 ${metric(row.cosine_similarity)} · Lift ${metric(row.lift)}`:'该关联未公开 / 不可用；不按零处理。'}
  function target(element){const node=element?.closest?.('[data-compare-node]');if(node)return {kind:'node',name:node.getAttribute('data-compare-node'),element:node};const edge=element?.closest?.('[data-compare-edge]');return edge?{kind:'edge',index:Number(edge.getAttribute('data-compare-edge')),element:edge}:null}
  function showDetail(side,item){
    if(!state.available||!item)return;
    if(item.kind==='node')byId('network-compare-detail').innerHTML=`<h5>${escapeHtml(item.name)}</h5>${sides.map(key=>`<p><strong>${escapeHtml(groupName(state[key]))}</strong> · ${values(state.panels[key].graph.scopeNodes.find(row=>row.item_name===item.name))}</p>`).join('')}`;
    else{const row=state.panels[side].graph.edges[item.index];if(!row)return;const key=pairKey(row.item_1,row.item_2);byId('network-compare-detail').innerHTML=`<h5>${escapeHtml(row.item_1)} · ${escapeHtml(row.item_2)}</h5>${sides.map(value=>`<p><strong>${escapeHtml(groupName(state[value]))}</strong> · ${edgeValues(state.panels[value].graph.scopeEdges.find(edge=>pairKey(edge.item_1,edge.item_2)===key))}</p>`).join('')}`}
  }
  function graphMarkup(side){
    const current=state.panels[side],graph=current.graph;
    const edges=graph.edges.map((row,index)=>`<line data-compare-edge="${index}" role="button" tabindex="${index===0?'0':'-1'}" aria-label="${escapeHtml(row.item_1+' 与 '+row.item_2+'，查看两组数值')}" stroke="#7db99e" stroke-width="${1+(Number(row.cosine_similarity)||0)*3}"/>`).join('');
    const nodes=graph.nodes.map(row=>`<g data-compare-node="${escapeHtml(row.item_name)}" role="button" tabindex="${row.item_name===state.selected?'0':'-1'}" aria-pressed="false" aria-label="${escapeHtml(row.item_name+'，选中并对照两组数值')}"><title>${escapeHtml(row.item_name)}</title><circle r="18" fill="#387d5e" stroke="#a4cdb0"/><text data-compare-label="true" text-anchor="middle" fill="#f4f6ea" font-size="12">${space.labelLines(row.item_name).map((line,index)=>`<tspan x="0" y="${index*15}">${escapeHtml(line)}</tspan>`).join('')}</text></g>`).join('');
    return `<svg viewBox="0 0 ${W} ${H}" role="group" aria-label="${escapeHtml(groupName(current.group)+'，'+graph.nodes.length+' 个药味')}" font-family="Microsoft YaHei, PingFang SC, sans-serif"><title>${escapeHtml(groupName(current.group))}固定坐标网络</title><defs><clipPath id="network-compare-${side}-clip"><rect width="${W}" height="${H}"/></clipPath></defs><rect width="${W}" height="${H}" fill="#0c302a"/><g clip-path="url(#network-compare-${side}-clip)"><g data-compare-links="true">${edges}</g><g data-compare-nodes="true">${nodes}</g></g></svg>`;
  }
  function paint(){
    if(!state.available||state.rebuilding)return;
    for(const side of sides){
      const current=state.panels[side];if(!current)continue;const scene=byId('network-compare-'+side+'-scene'),svg=scene.querySelector('svg');if(!svg)continue;
      const points=new Map(current.layout.map(point=>[point.name,space.project(point,state.camera,W,H)]));
      const labels=space.labelPositions(current.graph,points,state.selected,state.focused?.name,W,H,'focus');
      const nodes=[...svg.querySelectorAll('[data-compare-node]')];
      for(const node of nodes){const name=node.getAttribute('data-compare-node'),p=points.get(name),active=name===state.selected,label=labels.get(name);node.setAttribute('transform',`translate(${p.x.toFixed(3)} ${p.y.toFixed(3)}) scale(${p.scale.toFixed(3)})`);node.setAttribute('data-depth',p.z.toFixed(3));node.setAttribute('aria-pressed',String(active));node.setAttribute('tabindex',active?'0':'-1');node.querySelector('circle')?.setAttribute('fill',active?'#c5a25e':'#397d5e');const text=node.querySelector('[data-compare-label]');text?.setAttribute('visibility',label?'visible':'hidden');if(label)text?.setAttribute('transform',`translate(${(label.x+label.w/2-p.x)/p.scale} ${(label.y+12*label.scale-p.y)/p.scale}) scale(${label.scale/p.scale})`)}
      for(const line of svg.querySelectorAll('[data-compare-edge]')){const edge=current.graph.edges[Number(line.getAttribute('data-compare-edge'))],a=points.get(edge.item_1),b=points.get(edge.item_2);for(const [key,value]of Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y}))line.setAttribute(key,value.toFixed(3));const active=edge.item_1===state.selected||edge.item_2===state.selected;line.setAttribute('stroke',active?'#dbc183':'#7db99e');line.setAttribute('stroke-opacity',active?'.78':'.24')}
      const layer=svg.querySelector('[data-compare-nodes]');let next=null;for(const node of nodes.sort((a,b)=>Number(a.getAttribute('data-depth'))-Number(b.getAttribute('data-depth')))){if(node!==state.focused?.element&&node.nextSibling!==next)layer.insertBefore(node,next);next=node}
      scene.setAttribute('data-camera',JSON.stringify(state.camera));
      byId('network-compare-'+side+'-value').innerHTML=`<strong>${escapeHtml(state.selected)}</strong> · ${values(current.graph.scopeNodes.find(row=>row.item_name===state.selected))}`;
    }
  }
  function renderTables(){
    const panels=sides.map(side=>state.panels[side]),names=[...new Set(panels.flatMap(value=>value.graph.scopeNodes.map(row=>row.item_name)))].sort();
    byId('network-compare-table-title').textContent=`药味原值与关联对照表 · ${names.length} 个公开药味`;
    byId('network-compare-nodes-table').innerHTML=researchTable(['药味',...sides.map(side=>groupName(state[side])+' · 首诊原值')],names.map(name=>[escapeHtml(name),...panels.map(value=>values(value.graph.scopeNodes.find(row=>row.item_name===name)))]));
    const keys=[...new Set(panels.flatMap(value=>value.graph.scopeEdges.map(row=>pairKey(row.item_1,row.item_2))))].sort();
    byId('network-compare-edges-table').innerHTML=researchTable(['药味关联',...sides.map(side=>groupName(state[side])+' · 原值')],keys.map(key=>[JSON.parse(key).map(escapeHtml).join(' · '),...panels.map(value=>edgeValues(value.graph.scopeEdges.find(row=>pairKey(row.item_1,row.item_2)===key)))]));
  }
  function refresh(snapshot,reason='graph'){
    if(reason==='selection'){state.selected=snapshot.selected;buildPanels(false);return}
    if(resetRequested){state.left='';state.right='';state.selected='';state.source='';state.pending=null;resetRequested=false}
    const source=sourceKey(),changed=state.source!==source,groups=availableGroups(),ids=groups.map(row=>row.group);state.source=source;state.available=groups.length>=2;state.camera=space.getCamera();
    if(changed){state.left='';state.right='';state.selected=snapshot.selected;state.focused=null;state.drag=null;byId('network-compare-export-status').textContent=''}
    if(state.pending?.source===source){state.left=state.pending.left;state.right=state.pending.right;state.selected=state.pending.selected}
    if(!ids.includes(state.left))state.left=ids.includes(strictGroup)?strictGroup:ids[0]||'';
    if(!ids.includes(state.right)||state.right===state.left)state.right=ids.find(key=>key!==state.left)||'';
    byId('network-comparison-source').textContent=sourceTitle()+' · 独立严格队列首诊共现';
    byId('network-compare-unavailable').hidden=state.available;byId('network-compare-content').hidden=!state.available;byId('network-compare-export').disabled=!state.available;
    if(!state.available){state.panels={};byId('network-compare-detail').innerHTML='';byId('network-compare-unavailable').innerHTML=`此来源目前有 ${groups.length} 个已公开网络的严格队列，尚不能进行双队列对照。<a href="#network-lab">返回药味网络探索</a>`;return}
    for(const side of sides){const select=byId('network-compare-'+side);select.innerHTML=groups.map(row=>`<option value="${escapeHtml(row.group)}">${escapeHtml(groupName(row.group))}</option>`).join('');select.value=state[side]}
    buildPanels();
  }
  function buildPanels(tables=true){
    if(!state.available)return;const focused=state.focused;state.focused=null;
    // Removing focused SVG children emits focusout synchronously. Publish both
    // scenes before allowing those handlers to paint the new panel models.
    state.rebuilding=true;
    try{
    for(const side of sides)state.panels[side]=panel(state[side]);
    const names=[...new Set(sides.flatMap(side=>state.panels[side].graph.scopeNodes.map(row=>row.item_name)))].sort();
    if(!names.includes(state.selected)){state.selected=names[0]||'';for(const side of sides)state.panels[side]=panel(state[side])}
    const drug=byId('network-compare-drug');drug.innerHTML=names.map(name=>`<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join('');drug.value=state.selected;
    for(const side of sides){const current=state.panels[side],first=current.graph.scopeNodes[0];byId('network-compare-'+side+'-title').textContent=groupName(current.group);byId('network-compare-'+side+'-scope').textContent=`${sourceTitle()} · 首诊分析患者 ${metricText(current.cohort?current.cohort.patients:first?.patients)} 人；公开覆盖率阈值 ${metricText(first?.node_prevalence_threshold,'percent')}，余弦阈值 ${metricText(first?.edge_cosine_threshold)}。画布 ${current.graph.nodes.length}/${current.graph.scopeNodes.length} 个药味、${current.graph.edges.length}/${current.graph.scopeEdges.length} 条关联。`;byId('network-compare-'+side+'-scene').innerHTML=graphMarkup(side)}
    }finally{state.rebuilding=false}
    if(focused?.kind==='node'&&sides.includes(focused.side)){const scene=byId('network-compare-'+focused.side+'-scene'),node=[...scene.querySelector('svg').querySelectorAll('[data-compare-node]')].find(element=>element.getAttribute('data-compare-node')===focused.name);if(node){state.focused={kind:'node',name:focused.name,side:focused.side,element:node};node.focus({preventScroll:true})}else scene.focus({preventScroll:true})}
    paint();showDetail('left',{kind:'node',name:state.selected});if(tables)renderTables();
  }
  function select(name){
    if(!sides.some(side=>state.panels[side]?.graph.scopeNodes.some(row=>row.item_name===name)))return;
    changeView(()=>{state.selected=name;if(strictRows('nodes').some(row=>row.item_name===name)){if(bridge.getSnapshot().graph.nodes.some(row=>row.item_name===name))bridge.selectNode(name);else bridge.locateNode(name,false)}buildPanels(false)});
  }
  function camera(value){space.setCamera(value)}
  function exported(){return {schema_version:'mingyirx-fixed-frame-v1',source:{key:sourceKey(),title:sourceTitle()},selected:state.selected,camera:{...state.camera},coordinate_universe:space.layout(researchRows('nodes'),researchRows('nodes')),note:'Same-source disclosed coordinates only; absent rows are unavailable, not zero. Separate original metrics, no estimated differences.',panels:sides.map(side=>{const current=state.panels[side];return {side,group:current.group,cohort:current.cohort,displayed_nodes:current.graph.nodes,displayed_edges:current.graph.edges,disclosed_nodes:current.graph.scopeNodes,disclosed_edges:current.graph.scopeEdges,layout:current.layout}})}}
  for(const side of sides){
    byId('network-compare-'+side).addEventListener('change',event=>changeView(()=>{const next=event.target.value,other=side==='left'?'right':'left';if(!availableGroups().some(row=>row.group===next))return;if(state[other]===next)state[other]=state[side];state[side]=next;refresh(bridge.getSnapshot())}));
    const scene=byId('network-compare-'+side+'-scene');
    scene.addEventListener('pointerdown',event=>{if(event.button!==0||!state.available)return;const item=target(event.target);(item?.element||scene).focus({preventScroll:true});state.drag={side,id:event.pointerId,x:event.clientX,y:event.clientY,camera:{...state.camera},item,moved:false,touch:event.pointerType==='touch'};state.suppressClick=false;scene.setPointerCapture?.(event.pointerId);if(event.pointerType!=='touch')event.preventDefault()});
    scene.addEventListener('pointermove',event=>{if(!state.drag){if(event.pointerType!=='touch')showDetail(side,target(event.target));return}if(state.drag.side!==side||state.drag.id!==event.pointerId)return;const dx=event.clientX-state.drag.x,dy=event.clientY-state.drag.y;if(Math.hypot(dx,dy)>5)state.drag.moved=true;if(state.drag.moved)camera({...state.drag.camera,yaw:state.drag.camera.yaw+dx*.009,pitch:state.drag.camera.pitch+dy*.009})});
    function finish(event,cancelled=false){if(state.drag?.side!==side||state.drag.id!==event.pointerId)return;const drag=state.drag;state.drag=null;if(scene.hasPointerCapture?.(event.pointerId))scene.releasePointerCapture(event.pointerId);state.suppressClick=drag.moved||cancelled;if(!cancelled&&!drag.moved&&drag.item){if(drag.item.kind==='node')select(drag.item.name);else showDetail(side,drag.item)}}
    scene.addEventListener('pointerup',event=>finish(event));scene.addEventListener('pointercancel',event=>finish(event,true));scene.addEventListener('lostpointercapture',event=>finish(event,true));
    scene.addEventListener('click',event=>{if(state.suppressClick){state.suppressClick=false;return}const item=target(event.target);if(item?.kind==='node')select(item.name);else showDetail(side,item)});
    scene.addEventListener('focusin',event=>{if(state.rebuilding)return;const item=target(event.target);state.focused=item?{...item,side}:null;showDetail(side,item);paint()});scene.addEventListener('focusout',event=>{if(!state.rebuilding&&!scene.contains?.(event.relatedTarget)){state.focused=null;paint()}});
    scene.addEventListener('keydown',event=>{const key=event.key,item=target(event.target);if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(key)){event.preventDefault();camera({...state.camera,yaw:state.camera.yaw+(key==='ArrowRight'?.12:key==='ArrowLeft'?-.12:0),pitch:state.camera.pitch+(key==='ArrowDown'?.12:key==='ArrowUp'?-.12:0)})}else if((key==='Enter'||key===' ')&&item){event.preventDefault();if(item.kind==='node')select(item.name);else showDetail(side,item)}else if(['PageUp','PageDown'].includes(key)){event.preventDefault();const elements=[...scene.querySelector('svg').querySelectorAll(item?.kind==='edge'?'[data-compare-edge]':'[data-compare-node]')],index=elements.indexOf(item?.element);elements[(index+(key==='PageDown'?1:-1)+elements.length)%elements.length]?.focus({preventScroll:true})}else if(['+','=','-','Home'].includes(key)){event.preventDefault();camera(key==='Home'?{yaw:.38,pitch:-.18,zoom:1}:{...state.camera,zoom:state.camera.zoom*(key==='-'?1/1.2:1.2)})}else if(key==='Escape'){showDetail(side,{kind:'node',name:state.selected})}});
  }
  byId('network-compare-drug').addEventListener('change',event=>select(event.target.value));
  byId('network-compare-minus').addEventListener('click',()=>camera({...state.camera,zoom:state.camera.zoom/1.2}));byId('network-compare-plus').addEventListener('click',()=>camera({...state.camera,zoom:state.camera.zoom*1.2}));byId('network-compare-reset').addEventListener('click',()=>camera({yaw:.38,pitch:-.18,zoom:1}));
  byId('network-compare-export').addEventListener('click',()=>{if(state.available)downloadResearch('mingyirx-network-comparison.json',JSON.stringify(exported(),null,2),'application/json;charset=utf-8','network-compare-export-status')});
  const originalCapture=captureViewState,originalApply=applyViewState,originalReset=resetDashboardView;
  captureViewState=()=>({...originalCapture(),network_comparison:{source:sourceKey(),left:state.left,right:state.right,selected:state.selected}});
  applyViewState=view=>{state.pending=view?.network_comparison||null;try{originalApply(view)}finally{state.pending=null}};
  resetDashboardView=(...args)=>{if(!restoringView)resetRequested=true;return originalReset(...args)};
  space.subscribeCamera(value=>{state.camera=value;paint()});bridge.subscribe(refresh);refresh(bridge.getSnapshot());recordViewState(true);
  return Object.freeze({availableGroups,pairKey,exported});
})();
"""


def enhance_network_compare(page: str) -> str:
    """Append the comparison after 3D without rewriting data or prior scripts."""
    if 'id="network-comparison-script"' in page:
        return page
    if 'id="network-3d-script"' not in page:
        raise DashboardError("Network comparison requires the 3D adapter")
    marker = '<script id="supplement-data"' if '<script id="supplement-data"' in page else '<script id="dashboard-data"'
    if page.count(marker) != 1:
        raise DashboardError("Comparison payload anchor is missing or ambiguous")
    markup, scripts = page.split(marker, 1)
    anchor = '<section id="network-lab"'
    start = markup.find(anchor)
    end = markup.find('</section>', start)
    if markup.count(anchor) != 1 or end < 0 or markup.count('</style>') != 1 or scripts.count('</body>') != 1:
        raise DashboardError("Comparison presentation anchors are missing or ambiguous")
    end += len('</section>')
    markup = markup[:end] + COMPARE_HTML + markup[end:]
    markup = markup.replace('</style>', COMPARE_CSS + '</style>', 1)
    return (markup + marker + scripts).replace('</body>', '<script id="network-comparison-script">' + COMPARE_JS + '</script></body>', 1)
