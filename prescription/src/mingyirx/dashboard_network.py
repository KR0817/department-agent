"""Opt-in, dependency-free exploration of already disclosed network aggregates."""
from __future__ import annotations

import re

from .dashboard import DashboardError


NETWORK_CSS = r"""
#network-lab{scroll-margin-top:90px;min-width:0;margin:24px 0}
#network-lab .network-heading{display:flex;align-items:end;justify-content:space-between;gap:16px;margin-bottom:16px}
#network-lab .network-heading h4{font-size:28px;margin:3px 0 5px;color:var(--ink)}
#network-lab .network-eyebrow{font:600 11px/1.5 system-ui,sans-serif;letter-spacing:.15em;color:#137d71}
#network-lab #network-context{margin:0;font-size:13px;color:var(--muted)}
#network-lab .network-toolbar{display:grid;grid-template-columns:minmax(190px,1.5fr) minmax(150px,1fr) minmax(120px,.7fr) auto;gap:12px;align-items:end;padding:16px;border:1px solid #c7dad3;border-radius:10px;background:#f3f8f5}
#network-lab .network-toolbar label{display:grid;gap:6px;min-width:0;font-size:12px;font-weight:600}
#network-lab .network-toolbar select{width:100%;min-width:0;max-width:none;font-size:13px}
#network-lab .network-workspace{display:grid;grid-template-columns:minmax(0,1fr) 254px;gap:0;border:1px solid #c7dad3;border-radius:12px;overflow:hidden;margin-top:14px;background:#fff}
#network-lab .network-stage{position:relative;min-width:0;background:#123c36}
#network-lab #network-graph{margin:0;border:0;border-radius:0;min-width:0;min-height:420px;overflow:hidden;background:#123c36;touch-action:none}
#network-lab #network-graph svg{display:block;width:100%;height:100%;min-width:0;min-height:420px;aspect-ratio:3/2;overflow:hidden;touch-action:none;cursor:grab}
#network-lab #network-graph svg.is-dragging{cursor:grabbing}
#network-lab #network-graph .empty{margin:32px;padding:32px;color:#dcece6;background:#184c42;border-color:#477e70}
#network-lab .network-node{cursor:grab;outline:none}
#network-lab .network-node:focus-visible .network-node-shell{stroke:#fff;stroke-width:4}
#network-lab .network-node text{pointer-events:none;user-select:none}
#network-lab .network-canvas-shell{position:relative;min-width:0}
#network-lab .network-node-visual{pointer-events:none}
#network-lab [data-network-edge-hit]{cursor:help;outline:none}
#network-lab [data-network-hover="active"] .network-node-visual{transform:translateY(-2px) scale(1.045)}
#network-lab #network-graph[data-hover-motion="running"] [data-network-hover="active"] .network-node-visual{animation:network-hover-float 1.8s ease-in-out infinite}
@keyframes network-hover-float{0%,100%{transform:translateY(-1px) scale(1.045)}50%{transform:translateY(-4px) scale(1.065)}}
#network-lab .network-detail-card{box-sizing:border-box;color:#f2faf5;background:#102f2a;border:1px solid #86b6a2;border-radius:10px;box-shadow:0 12px 30px #061f2840;padding:14px;font-size:12px;line-height:1.5;overflow-wrap:anywhere}
#network-lab #network-hover-card{position:absolute;z-index:4;pointer-events:none;max-width:calc(100% - 24px)}
#network-lab .network-detail-card[hidden]{display:none}
#network-lab .network-detail-card h5{margin:0 0 5px;color:#fff;font-size:17px;line-height:1.5}
#network-lab .network-detail-context{margin:0 0 11px!important;color:#bad5c8;font-size:11px!important;line-height:1.5}
#network-lab .network-detail-card dl{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:5px 14px;margin:0}
#network-lab .network-detail-card dt{color:#c0d9cd}
#network-lab .network-detail-card dd{margin:0;color:#ffe1a6;text-align:right;font-variant-numeric:tabular-nums}
#network-lab .network-detail-note{color:#bad5c8;font-size:10px!important;margin:10px 0 0!important}
#network-lab #network-touch-details{border-radius:0;border-width:1px 0 0;box-shadow:none;padding:14px 18px}
#network-lab .network-canvas-tools{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;background:#10342f;border-bottom:1px solid #345c51;color:#dcece6;flex-wrap:wrap}
#network-lab .network-canvas-tools>div{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
#network-lab .network-tool{min-height:38px;min-width:38px;padding:6px 11px;background:#1b4c43;border:1px solid #567d70;border-radius:6px;color:#f4fbf7;font:500 12px/1.4 "Microsoft YaHei",sans-serif;cursor:pointer}
#network-lab .network-tool:hover{background:#2b6355;border-color:#99c4b3}
#network-lab .network-tool:disabled{opacity:.55;color:#dcece6;background:#1b4c43;cursor:not-allowed}
#network-lab .network-tool:focus-visible{outline:3px solid #e8c385;outline-offset:2px}
#network-lab #network-zoom-value{min-width:42px;text-align:center;font:12px/1.5 ui-monospace,monospace;color:#dcece6}
#network-lab #network-camera-label{font-size:11px;color:#c4d9cf;padding-left:4px}
#network-lab .network-stage-note{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;padding:10px 16px;margin:0!important;color:#dcece6;font-size:11px!important;border-top:1px solid #345c51;background:#10342f}
#network-lab .network-stage-note i{display:inline-block;width:7px;height:7px;background:#e0b76b;border-radius:50%;margin-right:6px}
#network-lab #network-inspector{min-width:0;padding:20px 18px;background:#fcfdfb;border-left:1px solid #c7dad3;overflow-wrap:anywhere}
#network-lab #network-inspector h5{font-size:24px;line-height:1.4;margin:4px 0 12px;color:#16342f;font-family:STFangsong,FangSong,serif}
#network-lab .network-inspector-label{color:#137d71;font-size:11px;font-weight:700;letter-spacing:.08em}
#network-lab .network-node-metrics{margin:12px 0;display:grid;grid-template-columns:1fr 1fr;gap:12px}
#network-lab .network-node-metrics div{min-width:0}
#network-lab .network-node-metrics dt{font-size:11px;color:#526b60;margin-bottom:4px}
#network-lab .network-node-metrics dd{margin:0;font:600 18px/1.5 ui-monospace,monospace;color:#16342f}
#network-lab .network-inspector-actions{display:grid;gap:8px;margin:18px 0}
#network-lab .network-inspector-actions button{width:100%;font-size:12px;text-align:center}
#network-lab #network-center-selected{background:#137d71;color:#fff;border-color:#137d71}
#network-lab .network-neighbors{padding:0;margin:12px 0 0;list-style:none}
#network-lab .network-neighbors li{border-top:1px solid #dce8e1;padding:9px 0}
#network-lab .network-neighbors button{border:0;padding:0;background:none;color:#16342f;font-size:12px;text-align:left;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
#network-lab .network-neighbors small{display:block;color:#526b60;font-size:11px;margin-top:4px}
#network-lab .network-inspector-note{font-size:11px!important;color:#526b60;margin:10px 0!important}
#network-lab #network-status{font-size:12px;margin:10px 0 8px;color:#526b60;min-height:20px}
#network-lab .network-data-details{margin-top:14px;border-top:1px solid #c7dad3;padding-top:14px}
#network-lab .network-data-details>summary{font-size:13px;font-weight:600;color:#16342f;cursor:pointer}
#network-lab #network-scope{font-size:12px;line-height:1.7;max-width:none}
#network-lab #network-edges .research-table :is(th,td):nth-child(-n+2){text-align:left}
@media(max-width:1200px){#network-lab .network-workspace{grid-template-columns:minmax(0,1fr)}#network-lab #network-inspector{border-left:0;border-top:1px solid #c7dad3;display:grid;grid-template-columns:1fr 1fr;gap:4px 24px}#network-lab .network-inspector-summary{min-width:0}#network-lab .network-inspector-connections{min-width:0}#network-lab .network-toolbar{grid-template-columns:minmax(0,1fr) minmax(140px,1fr) minmax(110px,.7fr)}#network-lab #export-network-svg{grid-column:1/-1;justify-self:end}}
@media(max-width:600px){#network-lab .network-heading h4{font-size:26px}#network-lab .network-toolbar{grid-template-columns:minmax(0,1fr) minmax(0,1fr);padding:12px;gap:10px}#network-lab .network-toolbar>label:first-child{grid-column:1/-1}#network-lab #export-network-svg{justify-self:stretch}#network-lab #network-inspector{display:block;padding:18px}#network-lab #network-graph,#network-lab #network-graph svg{min-height:360px}#network-lab .network-canvas-tools{padding:10px;gap:8px}#network-lab .network-stage-note{font-size:11px!important;padding:10px}#network-lab .network-node-metrics{grid-template-columns:repeat(3,minmax(0,1fr))}#network-lab .network-node-metrics dd{font-size:17px}}
@media(prefers-reduced-motion:reduce){#network-lab *{scroll-behavior:auto!important}}
"""


NETWORK_HTML = r"""
<section id="network-lab" aria-labelledby="network-heading">
  <div class="network-heading"><div><span class="network-eyebrow">MEDICATION NETWORK</span><h4 id="network-heading">药味共现网络</h4><p id="network-context">独立严格单病队列 · 首诊共现</p></div></div>
  <div class="network-toolbar">
    <label>定位药味（按原有总用次数）<select id="network-item"></select></label>
    <label>探索范围<select id="network-view-mode"><option value="all">全队列网络</option><option value="neighborhood">中心药味邻域</option></select></label>
    <label>画布连线上限<select id="network-edge-limit"><option value="40">40 条</option><option value="80" selected>80 条</option><option value="120">120 条</option></select></label>
    <button class="filter-btn" type="button" id="export-network-svg" disabled>导出当前网络 SVG</button>
  </div>
  <div class="network-workspace">
    <div class="network-stage">
      <div class="network-canvas-tools"><div><button class="network-tool" type="button" id="network-zoom-out" aria-label="缩小网络">−</button><span id="network-zoom-value" aria-live="off">100%</span><button class="network-tool" type="button" id="network-zoom-in" aria-label="放大网络">＋</button><button class="network-tool" type="button" id="network-fit">适配画布</button><span id="network-camera-label">全图视野</span></div><div><button class="network-tool" type="button" id="network-motion" aria-pressed="false">暂停布局</button><button class="network-tool" type="button" id="network-reset">重置布局</button></div></div>
      <div class="network-canvas-shell"><div id="network-graph" class="network-view" tabindex="0" role="region" aria-label="交互式药味共现网络" aria-describedby="network-keyboard-help"></div><div id="network-hover-card" class="network-detail-card" role="tooltip" hidden></div></div>
      <div id="network-touch-details" class="network-detail-card" role="status" aria-live="polite" hidden></div>
      <p class="network-stage-note"><span><i></i>金色为选中药味</span><span>线宽为原有余弦相似度</span><span>位置与大小仅用于布局</span></p>
    </div>
    <aside id="network-inspector" aria-label="选中药味与公开关联"></aside>
  </div>
  <p id="network-status" role="status" aria-live="polite"></p>
  <details class="network-data-details"><summary>操作说明与网络口径</summary><p id="network-keyboard-help">悬停药味或连线查看公开数值；触屏点按后在画布下方显示详情。拖动药味调整位置，拖动画布平移；Ctrl + 滚轮或缩放按钮改变视野。Tab 进入节点或连线，Page Up / Page Down 切换同类对象，Enter 选中药味或查看连线，Escape 关闭详情。方向键移动节点，背景获焦后平移，＋ / − 缩放，0 适配。</p><p id="network-scope"></p></details>
  <p class="research-status" id="network-export-status" role="status" aria-live="polite"></p>
  <details class="network-data-details"><summary id="network-table-summary">全部公开关联数值</summary><div id="network-edges"></div></details>
</section>
"""


NETWORK_JS = r"""
const MingYiRxNetwork = (() => {
  'use strict';
  const WIDTH=960, HEIGHT=640, MAX_NODES=60;
  const numeric=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
  const score=row=>numeric(row.cosine_similarity)?Number(row.cosine_similarity):-Infinity;
  const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));
  /** Select existing rows only. Positions and visual limits never alter the inputs. */
  function project(nodes,edges,center,mode='all',edgeLimit=80){
    const ordered=[...new Map(nodes.map(row=>[row.item_name,row])).values()];
    const names=new Set(ordered.map(row=>row.item_name));
    const valid=edges.filter(row=>names.has(row.item_1)&&names.has(row.item_2)&&row.item_1!==row.item_2);
    const scopeEdges=valid.filter(row=>mode==='all'||row.item_1===center||row.item_2===center).slice().sort((a,b)=>score(b)-score(a));
    const scopeNames=mode==='all'?names:new Set([center,...scopeEdges.flatMap(row=>[row.item_1,row.item_2])]);
    const scopeNodes=ordered.filter(row=>scopeNames.has(row.item_name));
    const ranked=mode==='all'?scopeNodes:[...scopeNodes.filter(row=>row.item_name===center),...scopeEdges.flatMap(row=>[row.item_1,row.item_2]).filter(name=>name!==center).map(name=>scopeNodes.find(row=>row.item_name===name)).filter(Boolean)];
    const visibleNodes=[...new Map(ranked.map(row=>[row.item_name,row])).values()].slice(0,MAX_NODES);
    if(mode==='all'&&names.has(center)&&!visibleNodes.some(row=>row.item_name===center)){visibleNodes[visibleNodes.length-1]=ordered.find(row=>row.item_name===center)}
    const shown=new Set(visibleNodes.map(row=>row.item_name));
    const cap=[40,80,120].includes(Number(edgeLimit))?Number(edgeLimit):80;
    const visibleEdges=scopeEdges.filter(row=>shown.has(row.item_1)&&shown.has(row.item_2)).slice(0,cap);
    return {nodes:visibleNodes,edges:visibleEdges,scopeNodes,scopeEdges,mode,edgeLimit:cap,unresolvedEdges:edges.length-valid.length};
  }
  function initialPositions(nodes){
    const total=nodes.length;
    return new Map(nodes.map((row,index)=>{
      const radius=total===1?0:44*Math.sqrt(index+.5),angle=index*2.399963229728653;
      return [row.item_name,{name:row.item_name,x:WIDTH/2+Math.cos(angle)*radius*1.35,y:HEIGHT/2+Math.sin(angle)*radius,vx:0,vy:0}];
    }));
  }
  const state={key:'',mode:'all',edgeLimit:80,selected:'',center:'',graph:null,points:new Map(),pan:{x:0,y:0},zoom:1,framing:'overview',viewport:{width:WIDTH,height:HEIGHT,compact:false},paused:false,remaining:0,raf:0,svg:null,drag:null,dispose:null,pending:null,hover:null,hoverHeld:false,lastPointer:'',suppressClick:false};
  const subscribers=new Set();let suspended2d=false;
  // Presentation adapters receive copies; the disclosed rows stay authoritative.
  function getSnapshot(){return {key:state.key,mode:state.mode,edgeLimit:state.edgeLimit,selected:state.selected,center:state.center,graph:state.graph?{...state.graph,...Object.fromEntries(['nodes','edges','scopeNodes','scopeEdges'].map(key=>[key,state.graph[key].map(row=>({...row}))]))}:null}}
  function notify(reason){for(const listener of subscribers)listener(getSnapshot(),reason)}
  const reduced=typeof matchMedia==='function'?matchMedia('(prefers-reduced-motion: reduce)'):{matches:true};
  const finePointer=typeof matchMedia==='function'?matchMedia('(hover: hover) and (pointer: fine)'):{matches:false};
  const byId=id=>document.getElementById(id);
  const contextKey=()=>`${data.source_identity?.key||provenance.dataset_id||''}|${strictGroup}`;
  const originalRender=renderResearchNetwork, originalExport=exportFigure;
  function announce(message){byId('network-status').textContent=message}
  function stop(){if(state.raf&&typeof cancelAnimationFrame==='function')cancelAnimationFrame(state.raf);state.raf=0}
  function cleanup(){clearHover(false);stop();state.dispose?.();state.dispose=null;state.svg=null;state.drag=null;state.lastPointer='';state.suppressClick=false}
  function readViewport(){
    const compact=typeof innerWidth==='number'&&innerWidth<=600;
    return {width:compact?Math.max(240,Math.round(byId('network-graph').clientWidth||innerWidth-32)):WIDTH,height:compact?360:HEIGHT,compact};
  }
  function frameLayout(){
    if(!state.viewport.compact){fit();return}
    const point=state.points.get(state.selected)||{x:WIDTH/2,y:HEIGHT/2};state.zoom=1;state.framing='focus';
    state.pan={x:state.viewport.width/2-point.x,y:state.viewport.height/2-point.y};positionView();
  }
  function positionView(){
    state.svg?.querySelector('[data-network-plane]')?.setAttribute('transform',`translate(${state.pan.x.toFixed(2)} ${state.pan.y.toFixed(2)}) scale(${state.zoom.toFixed(4)})`);
    byId('network-zoom-value').textContent=Math.round(state.zoom*100)+'%';
    byId('network-camera-label').textContent={overview:'全图视野',focus:'聚焦视野',custom:'自定义视野'}[state.framing];
  }
  function hoverTarget(target){
    const node=target?.closest?.('[data-network-node]');
    if(node)return {kind:'node',name:node.getAttribute('data-network-node'),element:node};
    const edge=target?.closest?.('[data-network-edge-hit]');
    return edge?{kind:'edge',index:Number(edge.getAttribute('data-network-edge-hit')),element:edge}:null;
  }
  function sameHover(first,second){return !!first&&!!second&&first.kind===second.kind&&first.name===second.name&&first.index===second.index}
  /** All values retain the disclosed row's original denominator and formatting. */
  function detailMarkup(target){
    const row=target.kind==='node'?state.graph.nodes.find(item=>item.item_name===target.name):state.graph.edges[target.index];
    if(!row)return '';
    const metrics=target.kind==='node'?[
      ['首诊使用人数',metricText(row.exposed_patients)],['首诊分析患者',metricText(row.patients)],['首诊覆盖率',metricText(row.prevalence,'percent')],
      ['当前范围公开关联',String(state.graph.scopeEdges.filter(edge=>edge.item_1===target.name||edge.item_2===target.name).length)]
    ]:[['共现患者',metricText(row.cooccurrence_patients)],['首诊支持度',metricText(row.support,'percent')],['余弦相似度',metricText(row.cosine_similarity)],['Lift',metricText(row.lift)]];
    const title=target.kind==='node'?row.item_name:`${row.item_1} · ${row.item_2}`;
    return `<h5>${escapeHtml(title)}</h5><p class="network-detail-context">${escapeHtml(byId('network-context').textContent)}</p><dl>${metrics.map(([label,value])=>`<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join('')}</dl><p class="network-detail-note">${target.kind==='node'?'关联数含当前范围未绘出的公开边。':'仅为首诊共现关联，不表示配伍功效。'}</p>`;
  }
  function placeTooltip(event){
    if(!state.hover||state.hover.touch)return;
    const card=byId('network-hover-card'),rect=byId('network-graph').getBoundingClientRect();
    const viewWidth=typeof innerWidth==='number'?innerWidth:rect.right,viewHeight=typeof innerHeight==='number'?innerHeight:rect.bottom;
    const coverBottom=Math.max(0,...['#community-dock-frame','.safety'].map(selector=>document.querySelector?.(selector)?.getBoundingClientRect().bottom||0));
    const left=Math.max(12,12-rect.left),right=Math.min(rect.width-12,viewWidth-rect.left-12),top=Math.max(12,coverBottom+12-rect.top),bottom=Math.min(rect.height-12,viewHeight-rect.top-12);
    card.hidden=false;
    card.style.width=Math.max(120,Math.min(300,right-left))+'px';
    let anchor=state.hover.anchor;
    if(event&&Number.isFinite(event.clientX)&&Number.isFinite(event.clientY))anchor={x:event.clientX-rect.left,y:event.clientY-rect.top};
    if(!anchor){
      const points=state.hover.kind==='node'?[state.points.get(state.hover.name)]:[state.points.get(state.graph.edges[state.hover.index].item_1),state.points.get(state.graph.edges[state.hover.index].item_2)];
      const x=points.reduce((sum,point)=>sum+point.x,0)/points.length,y=points.reduce((sum,point)=>sum+point.y,0)/points.length;
      anchor={x:(state.pan.x+x*state.zoom)*rect.width/state.viewport.width,y:(state.pan.y+y*state.zoom)*rect.height/state.viewport.height};
    }
    state.hover.anchor=anchor;
    const size=card.getBoundingClientRect(),width=size.width,height=size.height;
    const candidates=[{x:anchor.x+24,y:anchor.y-height/2},{x:anchor.x-width-24,y:anchor.y-height/2},{x:anchor.x-width/2,y:anchor.y+28},{x:anchor.x-width/2,y:anchor.y-height-28}].map(point=>({...point,x:clamp(point.x,left,Math.max(left,right-width))}));
    const avoidsTarget=point=>point.x>anchor.x+12||point.x+width<anchor.x-12||point.y>anchor.y+12||point.y+height<anchor.y-12;
    const fitting=candidates.find(point=>point.y>=top&&point.y+height<=bottom&&avoidsTarget(point));
    const panel=byId('network-touch-details');
    if(!fitting){card.hidden=true;panel.innerHTML=card.innerHTML;panel.hidden=false;state.hover.element.setAttribute('aria-describedby',panel.id);return}
    panel.hidden=true;panel.innerHTML='';state.hover.element.setAttribute('aria-describedby',card.id);
    card.style.left=clamp(fitting.x,left,Math.max(left,right-width))+'px';card.style.top=clamp(fitting.y,top,Math.max(top,bottom-height))+'px';
  }
  function hoverMotion(){
    byId('network-graph').setAttribute('data-hover-motion',state.hover&&!state.hover.touch&&!state.paused&&!reduced.matches?'running':'static');
  }
  /** Hold settling while reading; resume only its remaining frames on leave. */
  function showHover(target,event,touch=false){
    if(!target||state.drag||!detailMarkup(target))return;
    if(sameHover(state.hover,target)&&state.hover.touch===touch){placeTooltip(event);return}
    const held=state.hoverHeld||!!state.raf;clearHover(false);state.hoverHeld=held;stop();
    state.hover={...target,touch,anchor:null};
    const card=byId(touch?'network-touch-details':'network-hover-card');card.innerHTML=detailMarkup(target);card.hidden=false;
    target.element.setAttribute('aria-describedby',card.id);paint();motionLabel();placeTooltip(event);
  }
  function clearHover(resume=true){
    const held=state.hoverHeld;state.hoverHeld=false;
    state.hover?.element.removeAttribute('aria-describedby');state.hover=null;
    for(const id of ['network-hover-card','network-touch-details']){const card=byId(id);card.hidden=true;card.innerHTML=''}
    if(state.svg)paint();hoverMotion();
    if(resume&&held&&!suspended2d&&!state.paused&&!reduced.matches&&state.svg&&state.remaining>0)state.raf=requestAnimationFrame(tick);
    motionLabel();
  }
  function paint(){
    if(!state.svg)return;
    const hovered=state.hover,neighbors=new Set();
    if(hovered?.kind==='node'){
      neighbors.add(hovered.name);
      for(const row of state.graph.edges)if(row.item_1===hovered.name||row.item_2===hovered.name){neighbors.add(row.item_1);neighbors.add(row.item_2)}
    }else if(hovered?.kind==='edge'){const edge=state.graph.edges[hovered.index];if(edge){neighbors.add(edge.item_1);neighbors.add(edge.item_2)}}
    for(const element of state.svg.querySelectorAll('[data-network-node]')){
      const name=element.getAttribute('data-network-node'),point=state.points.get(name),active=name===state.selected;
      if(!point)continue;
      element.setAttribute('transform',`translate(${point.x.toFixed(2)} ${point.y.toFixed(2)})`);
      element.setAttribute('tabindex',active?'0':'-1');element.setAttribute('aria-pressed',String(active));
      const circle=element.querySelector('.network-node-shell');circle.setAttribute('fill',active?'#765722':'#1b554b');circle.setAttribute('stroke',active?'#e8c385':'#91c2ad');circle.setAttribute('stroke-width',active?'3':'1.5');
      const highlighted=neighbors.has(name),primary=hovered?.kind==='node'&&hovered.name===name;
      element.setAttribute('data-network-hover',primary?'active':highlighted?'neighbor':'none');
      const halo=element.querySelector('[data-network-hover-halo]');halo.setAttribute('opacity',highlighted?primary?'.7':'.3':'0');
      if(highlighted){circle.setAttribute('stroke','#f3deb3');circle.setAttribute('stroke-width',primary?'3.5':'2.5')}
    }
    const linked=new Set(state.graph.edges.filter(row=>row.item_1===state.selected||row.item_2===state.selected));
    for(const element of state.svg.querySelectorAll('[data-network-edge]')){
      const edge=state.graph.edges[Number(element.getAttribute('data-network-edge'))],first=state.points.get(edge.item_1),second=state.points.get(edge.item_2);
      element.setAttribute('x1',first.x.toFixed(2));element.setAttribute('y1',first.y.toFixed(2));element.setAttribute('x2',second.x.toFixed(2));element.setAttribute('y2',second.y.toFixed(2));
      const hoverLinked=hovered?.kind==='node'?(edge.item_1===hovered.name||edge.item_2===hovered.name):hovered?.kind==='edge'&&state.graph.edges[hovered.index]===edge;
      element.setAttribute('stroke',hoverLinked?'#ffe1a6':linked.has(edge)?'#e2c48a':'#76b49f');element.setAttribute('stroke-opacity',hovered?hoverLinked?'1':'.13':linked.has(edge)?'.85':'.36');
    }
    for(const element of state.svg.querySelectorAll('[data-network-edge-hit]')){
      const edge=state.graph.edges[Number(element.getAttribute('data-network-edge-hit'))],first=state.points.get(edge.item_1),second=state.points.get(edge.item_2);
      for(const [key,value] of Object.entries({x1:first.x,y1:first.y,x2:second.x,y2:second.y}))element.setAttribute(key,value.toFixed(2));
    }
    positionView();hoverMotion();
  }
  function motionLabel(){
    const button=byId('network-motion');button.disabled=reduced.matches||!state.graph?.nodes.length;
    button.textContent=reduced.matches?'已减少动态':state.raf||state.hoverHeld?'暂停布局':state.paused?'继续布局':'重新布局';
    button.setAttribute('aria-pressed',String(state.paused||reduced.matches));
    byId('network-graph').setAttribute('data-motion-state',reduced.matches?'reduced':state.hoverHeld?'reading':state.raf?'running':state.paused?'paused':'settled');
    byId('network-graph').setAttribute('data-reduced-motion',String(reduced.matches));
    hoverMotion();
  }
  /** A short deterministic settling motion; no stochastic layout or inferred weight. */
  function tick(){
    state.raf=0;
    if(suspended2d||state.paused||reduced.matches||!state.svg||state.remaining<=0){motionLabel();return}
    const points=[...state.points.values()],alpha=Math.min(1,state.remaining/75);
    for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++){
      const a=points[i],b=points[j],dx=b.x-a.x,dy=b.y-a.y,distance=Math.max(1,Math.hypot(dx,dy)),force=(Math.min(4,1900/(distance*distance))+Math.max(0,76-distance)*.15)*alpha;
      a.vx-=dx/distance*force;a.vy-=dy/distance*force;b.vx+=dx/distance*force;b.vy+=dy/distance*force;
    }
    for(const row of state.graph.edges){
      const a=state.points.get(row.item_1),b=state.points.get(row.item_2),dx=b.x-a.x,dy=b.y-a.y,distance=Math.max(1,Math.hypot(dx,dy)),force=(distance-155)*.0015*alpha;
      a.vx+=dx/distance*force;a.vy+=dy/distance*force;b.vx-=dx/distance*force;b.vy-=dy/distance*force;
    }
    for(const point of points){point.vx=(point.vx+(WIDTH/2-point.x)*.0008*alpha)*.78;point.vy=(point.vy+(HEIGHT/2-point.y)*.0008*alpha)*.78;point.x=clamp(point.x+point.vx,65,WIDTH-65);point.y=clamp(point.y+point.vy,65,HEIGHT-65)}
    state.remaining--;paint();
    if(state.remaining>0)state.raf=requestAnimationFrame(tick);else frameLayout();
    motionLabel();
  }
  function start(){stop();if(!suspended2d&&!reduced.matches&&!state.paused&&state.graph?.nodes.length&&typeof requestAnimationFrame==='function'){state.remaining=140;state.raf=requestAnimationFrame(tick)}motionLabel()}
  function fit(user=false){
    if(!state.points.size)return;
    if(user){clearHover(false);stop();state.paused=true;motionLabel()}
    state.framing='overview';
    const points=[...state.points.values()],minX=Math.min(...points.map(p=>p.x))-75,maxX=Math.max(...points.map(p=>p.x))+75,minY=Math.min(...points.map(p=>p.y))-65,maxY=Math.max(...points.map(p=>p.y))+65;
    state.zoom=clamp(Math.min((state.viewport.width-60)/(maxX-minX),(state.viewport.height-60)/(maxY-minY)),.01,1.5);
    state.pan={x:state.viewport.width/2-(minX+maxX)/2*state.zoom,y:state.viewport.height/2-(minY+maxY)/2*state.zoom};positionView();
  }
  function zoom(factor,anchor={x:state.viewport.width/2,y:state.viewport.height/2}){
    clearHover(false);stop();state.paused=true;motionLabel();
    state.framing='custom';
    const next=clamp(state.zoom*factor,.01,3),ratio=next/state.zoom;
    state.pan={x:anchor.x-(anchor.x-state.pan.x)*ratio,y:anchor.y-(anchor.y-state.pan.y)*ratio};state.zoom=next;positionView();
  }
  function inspect(){
    const row=state.graph?.scopeNodes.find(item=>item.item_name===state.selected);
    if(!row){byId('network-inspector').innerHTML='<p class="network-inspector-note">当前来源没有可展示的公开网络节点。</p>';return}
    const linked=state.graph.scopeEdges.filter(edge=>edge.item_1===state.selected||edge.item_2===state.selected);
    const neighbors=linked.slice(0,5).map(edge=>{
      const name=edge.item_1===state.selected?edge.item_2:edge.item_1,visible=state.points.has(name);
      return `<li>${visible?`<button type="button" data-network-select="${escapeHtml(name)}">${escapeHtml(name)}</button>`:`<span>${escapeHtml(name)}</span>`}<small>共现 ${escapeHtml(metricText(edge.cooccurrence_patients))} 人 · 余弦 ${escapeHtml(metricText(edge.cosine_similarity))}</small></li>`;
    }).join('');
    byId('network-inspector').innerHTML=`<div class="network-inspector-summary"><span class="network-inspector-label">SELECTED MEDICATION</span><h5>${escapeHtml(row.item_name)}</h5><dl class="network-node-metrics"><div><dt>首诊覆盖率</dt><dd>${escapeHtml(metricText(row.prevalence,'percent'))}</dd></div><div><dt>首诊使用人数</dt><dd>${escapeHtml(metricText(row.exposed_patients))}</dd></div><div><dt>当前范围公开关联</dt><dd>${linked.length}</dd></div></dl><div class="network-inspector-actions"><button type="button" class="filter-btn" id="network-center-selected">以此药味展开邻域</button><button type="button" class="filter-btn" id="network-open-drug">查看单药分析</button></div></div><div class="network-inspector-connections"><span class="network-inspector-label">公开关联 · 按余弦排序</span><ul class="network-neighbors">${neighbors||'<li>当前范围没有已公开关联。</li>'}</ul><p class="network-inspector-note">展示前 ${Math.min(5,linked.length)} / ${linked.length} 条；完整数值见下方关联表。共现不代表配伍功效。</p></div>`;
  }
  function select(name,focus=false){
    if(!state.points.has(name))return;state.selected=name;paint();inspect();
    if(focus)for(const element of state.svg.querySelectorAll('[data-network-node]'))if(element.getAttribute('data-network-node')===name)element.focus();
    announce(`已选中 ${name}；拖动或方向键可移动，右侧可展开邻域或查看单药分析。`);
    notify('selection');
  }
  function canvasPoint(event){
    const point=state.svg.createSVGPoint();point.x=event.clientX;point.y=event.clientY;
    const matrix=state.svg.getScreenCTM();return matrix?point.matrixTransform(matrix.inverse()):{x:WIDTH/2,y:HEIGHT/2};
  }
  function attachCanvas(){
    const svg=state.svg,controller=new AbortController(),options={signal:controller.signal};
    state.dispose=()=>{if(state.drag&&svg.hasPointerCapture?.(state.drag.id))svg.releasePointerCapture(state.drag.id);controller.abort()};
    svg.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;
      state.lastPointer=event.pointerType||'mouse';state.suppressClick=false;clearHover(false);
      const node=event.target.closest?.('[data-network-node]'),point=canvasPoint(event),name=node?.getAttribute('data-network-node');
      stop();state.paused=true;motionLabel();
      const original=name?state.points.get(name):state.pan;
      state.drag={id:event.pointerId,name,start:point,x:original.x,y:original.y,touch:state.lastPointer==='touch',target:hoverTarget(event.target),moved:false};
      if(name){select(name);node.focus?.({preventScroll:true})}
      svg.setPointerCapture(event.pointerId);svg.classList.add('is-dragging');event.preventDefault();
    },options);
    svg.addEventListener('pointermove',event=>{
      if(!state.drag){if(event.pointerType!=='touch'&&finePointer.matches){const target=hoverTarget(event.target);if(target)showHover(target,event);else if(state.hover)clearHover()}return}
      if(state.drag.id!==event.pointerId)return;
      state.framing='custom';
      const point=canvasPoint(event),dx=point.x-state.drag.start.x,dy=point.y-state.drag.start.y;
      if(Math.hypot(dx,dy)>4)state.drag.moved=true;
      if(state.drag.name){const node=state.points.get(state.drag.name);node.x=clamp(state.drag.x+dx/state.zoom,-WIDTH,WIDTH*2);node.y=clamp(state.drag.y+dy/state.zoom,-HEIGHT,HEIGHT*2);node.vx=0;node.vy=0;paint()}
      else{state.pan={x:state.drag.x+dx,y:state.drag.y+dy};positionView()}
    },options);
    const finish=event=>{
      if(state.drag?.id!==event.pointerId)return;
      const drag=state.drag;state.drag=null;state.suppressClick=drag.moved;
      if(svg.hasPointerCapture?.(event.pointerId))svg.releasePointerCapture(event.pointerId);svg.classList.remove('is-dragging');
      if(event.type==='pointerup'&&drag.touch&&!drag.moved)showHover(drag.target,null,true);
    };
    svg.addEventListener('pointerup',finish,options);svg.addEventListener('pointercancel',finish,options);svg.addEventListener('lostpointercapture',finish,options);
    svg.addEventListener('pointerleave',event=>{if(event.pointerType!=='touch')clearHover()},options);
    svg.addEventListener('pointerout',event=>{if(!state.drag&&event.pointerType!=='touch'&&!sameHover(hoverTarget(event.target),hoverTarget(event.relatedTarget)))clearHover()},options);
    svg.addEventListener('focusin',event=>{if(!state.drag)showHover(hoverTarget(event.target))},options);
    svg.addEventListener('focusout',()=>clearHover(),options);
    svg.addEventListener('click',event=>{
      if(state.suppressClick){state.suppressClick=false;return}
      const target=hoverTarget(event.target);if(target?.kind==='node')select(target.name);
      if(target&&(event.pointerType==='touch'||state.lastPointer==='touch'))showHover(target,null,true);
    },options);
    svg.addEventListener('wheel',event=>{if(!event.ctrlKey&&!event.metaKey)return;event.preventDefault();zoom(event.deltaY<0?1.12:1/1.12,canvasPoint(event))},{...options,passive:false});
    svg.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();clearHover();return}
      const node=event.target.closest?.('[data-network-node]'),name=node?.getAttribute('data-network-node'),keys={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
      const target=hoverTarget(event.target);
      if(target?.kind==='edge'&&['Enter',' '].includes(event.key)){event.preventDefault();showHover(target);return}
      if(target?.kind==='edge'&&['PageUp','PageDown'].includes(event.key)){
        event.preventDefault();const edges=[...svg.querySelectorAll('[data-network-edge-hit]')],index=(target.index+(event.key==='PageUp'?-1:1)+edges.length)%edges.length;
        edges.forEach((edge,number)=>edge.setAttribute('tabindex',number===index?'0':'-1'));edges[index].focus({preventScroll:true});return;
      }
      if(name&&['Enter',' '].includes(event.key)){event.preventDefault();select(name);return}
      if(name&&['PageUp','PageDown'].includes(event.key)){event.preventDefault();const names=[...state.points.keys()],index=names.indexOf(name);select(names[(index+(event.key==='PageUp'?-1:1)+names.length)%names.length],true);return}
      if(keys[event.key]){event.preventDefault();clearHover(false);stop();state.paused=true;state.framing='custom';motionLabel();const [x,y]=keys[event.key],step=event.shiftKey?30:10;if(name){const point=state.points.get(name);point.x=clamp(point.x+x*step,-WIDTH,WIDTH*2);point.y=clamp(point.y+y*step,-HEIGHT,HEIGHT*2);select(name)}else{state.pan.x+=x*step;state.pan.y+=y*step;positionView()}return}
      if(['+','=','-','0'].includes(event.key)){event.preventDefault();if(event.key==='0')fit(true);else zoom(event.key==='-'?1/1.2:1.2)}
    },options);
  }
  function svgMarkup(graph){
    const links=graph.edges.map((row,index)=>`<line data-network-edge="${index}" stroke="#76b49f" stroke-opacity=".36" stroke-width="${numeric(row.cosine_similarity)?(1+clamp(Number(row.cosine_similarity),0,1)*3).toFixed(2):1}"/>`).join('');
    const hits=graph.edges.map((row,index)=>`<line data-network-edge-hit="${index}" data-network-transient="true" stroke="transparent" stroke-width="14" vector-effect="non-scaling-stroke" pointer-events="stroke" role="button" tabindex="${index===0?'0':'-1'}" aria-label="${escapeHtml(row.item_1)} 与 ${escapeHtml(row.item_2)}，查看共现关联数值"/>`).join('');
    const nodes=graph.nodes.map(row=>{
      const name=String(row.item_name),characters=[...name],lines=characters.length<=6?[name]:[characters.slice(0,Math.ceil(characters.length/2)).join(''),characters.slice(Math.ceil(characters.length/2)).join('')];
      const fontSize=characters.length>12?10:characters.length>8?11:13;
      return `<g class="network-node" data-network-node="${escapeHtml(name)}" role="button" tabindex="-1" aria-pressed="false" aria-label="${escapeHtml(name)}，首诊覆盖率 ${escapeHtml(metricText(row.prevalence,'percent'))}，按 Enter 选中"><circle data-network-transient="true" r="39" fill="transparent" pointer-events="all"/><g class="network-node-visual" pointer-events="none"><circle data-network-hover-halo="true" data-network-transient="true" r="41" fill="none" stroke="#efd69a" stroke-width="5" opacity="0"/><circle class="network-node-shell" r="33" fill="#1b554b" stroke="#91c2ad" stroke-width="1.5"/><text text-anchor="middle" fill="#ffffff" font-size="${fontSize}" font-weight="600">${lines.map((line,index)=>`<tspan x="0" y="${lines.length===1?5:index===0?-3:14}">${escapeHtml(line)}</tspan>`).join('')}</text></g></g>`;
    }).join('');
    return `<svg viewBox="0 0 ${state.viewport.width} ${state.viewport.height}" role="group" aria-label="可移动的药味共现网络，${graph.nodes.length} 个节点，${graph.edges.length} 条关联" font-family="Microsoft YaHei, PingFang SC, sans-serif" tabindex="0"><title>药味共现网络</title><desc>节点可拖动，背景可平移。连线只来自已公开共现记录；节点位置和大小仅用于布局。按 Page Up 或 Page Down 切换节点或连线，方向键移动节点。</desc><defs><clipPath id="network-plot-clip"><rect data-network-clip="true" width="${state.viewport.width}" height="${state.viewport.height}"/></clipPath></defs><rect data-network-background="true" width="${state.viewport.width}" height="${state.viewport.height}" fill="#123c36"/><g clip-path="url(#network-plot-clip)"><g data-network-plane="true">${links}${hits}${nodes}</g></g></svg>`;
  }
  function render(){
    cleanup();originalRender();
    const key=contextKey(),changed=key!==state.key;
    if(changed){state.key=key;state.mode='all';state.edgeLimit=80;state.selected='';state.paused=false;state.center=''}
    if(state.pending){const pending=state.pending;if(pending.key===key){state.mode=pending.mode==='neighborhood'?'neighborhood':'all';state.edgeLimit=[40,80,120].includes(Number(pending.edgeLimit))?Number(pending.edgeLimit):80}}
    else if(!changed&&state.center&&state.center!==networkItem)state.mode='neighborhood';
    if(state.center!==networkItem)state.selected=networkItem;
    state.center=networkItem;
    const sourceNodes=strictRows('nodes'),nodes=usageOrder(sourceNodes.map(row=>row.item_name)).map(name=>sourceNodes.find(row=>row.item_name===name));
    state.graph=project(nodes,strictRows('edges'),networkItem,state.mode,state.edgeLimit);
    if(!state.graph.nodes.some(row=>row.item_name===state.selected))state.selected=state.graph.nodes.some(row=>row.item_name===networkItem)?networkItem:state.graph.nodes[0]?.item_name||'';
    if(state.pending?.key===key&&state.graph.nodes.some(row=>row.item_name===state.pending.selected))state.selected=state.pending.selected;
    state.points=initialPositions(state.graph.nodes);state.pan={x:0,y:0};state.zoom=1;state.viewport=readViewport();
    byId('network-view-mode').value=state.mode;byId('network-edge-limit').value=String(state.edgeLimit);
    const cohort=researchRows('cohorts').find(row=>row.group===strictGroup),center=nodes.find(row=>row.item_name===networkItem),source=data.source_identity?.title||provenance.dataset_id||'来源未核实';
    byId('network-context').textContent=`${source} · ${groupLabel(cohort?.label||strictGroup||'无公开队列')} · 独立严格单病队列`;
    byId('network-scope').textContent=`首诊分析患者 ${metricText(cohort?.patients??center?.patients)} 人；覆盖率阈值 ${metricText(center?.node_prevalence_threshold,'percent')}，余弦阈值 ${metricText(center?.edge_cosine_threshold)}。画布最多 60 个节点及 ${state.edgeLimit} 条关联，按原有总用次数选择节点、余弦相似度选择连线；邻域只取与中心药味直接相连的原有边。下表保留当前范围的全部 ${state.graph.scopeEdges.length} 条有效公开关联。${state.graph.unresolvedEdges?`另有 ${state.graph.unresolvedEdges} 条边缺少完整公开端点或为自身连接，未绘制。`:''}选项总用次数来自全分析人群合格就诊；当前网络为独立严格队列首诊。布局、颜色与动画没有疗效含义。`;
    byId('network-table-summary').textContent=`全部公开关联数值 · ${state.graph.scopeEdges.length} 条（${state.mode==='all'?'全队列':'中心药味邻域'}）`;
    byId('network-edges').innerHTML=researchTable(['药味一','药味二','共现患者','首诊支持度','余弦相似度','Lift'],state.graph.scopeEdges.map(row=>[escapeHtml(row.item_1),escapeHtml(row.item_2),valueCell(row.cooccurrence_patients),valueCell(row.support,'percent'),valueCell(row.cosine_similarity),valueCell(row.lift)]),state.graph.scopeEdges.map((_,index)=>`network-edge-${index}`));
    byId('network-graph').innerHTML=state.graph.nodes.length?svgMarkup(state.graph):'<div class="empty">当前来源与严格队列没有公开的网络节点。切换来源或队列可查看已有汇总。</div>';
    byId('network-graph').setAttribute('tabindex',state.graph.nodes.length?'-1':'0');
    state.svg=byId('network-graph').querySelector('svg');
    byId('export-network-svg').disabled=!state.graph.nodes.length;
    for(const id of ['network-zoom-in','network-zoom-out','network-fit','network-reset','network-view-mode','network-edge-limit'])byId(id).disabled=!state.graph.nodes.length;
    if(state.svg){paint();frameLayout();attachCanvas();start()}else motionLabel();
    inspect();announce(`${state.mode==='all'?'全队列网络':'中心药味邻域'} · 画布载入 ${state.graph.nodes.length} / ${state.graph.scopeNodes.length} 个节点、${state.graph.edges.length} / ${state.graph.scopeEdges.length} 条公开关联${state.graph.nodes.length&&!state.graph.edges.length?'；当前范围没有可绘制关联':''}。${state.viewport.compact&&state.graph.nodes.length?'手机默认放大至可读视野；拖动画布探索，点「适配画布」查看全图。':''}`);
    notify('graph');
  }
  function exportNetwork(){
    if(!state.svg||!state.graph?.nodes.length){byId('network-export-status').textContent='当前没有可导出的公开网络。';return}
    clearHover(false);stop();motionLabel();
    const center=strictRows('nodes').find(row=>row.item_name===networkItem),cohort=researchRows('cohorts').find(row=>row.group===strictGroup);
    const context={kind:'network',title:state.mode==='all'?'首诊药味共现网络':`${networkItem} · 首诊共现邻域`,item:networkItem,group:strictGroup,subtitle:`${groupLabel(cohort?.label||strictGroup)} · 独立严格单病队列`,stratum_type:'overall',stratum:'all',mode:state.mode,selected:state.selected,node_limit:MAX_NODES,edge_limit:state.edgeLimit,displayed_nodes:state.graph.nodes,displayed_edges:state.graph.edges,available_nodes:state.graph.scopeNodes.length,available_edges:state.graph.scopeEdges.length,viewport:{width:state.viewport.width,height:state.viewport.height,compact:state.viewport.compact,zoom:state.zoom,pan:{...state.pan}},layout:[...state.points.values()].map(({name,x,y})=>({name,x,y})),denominator:`首诊分析患者 ${metricText(cohort?.patients??center?.patients)} 人；覆盖率阈值 ${metricText(center?.node_prevalence_threshold,'percent')}，余弦阈值 ${metricText(center?.edge_cosine_threshold)}。`,note:`当前${state.mode==='all'?'全队列':'邻域'}画布载入 ${state.graph.nodes.length}/${state.graph.scopeNodes.length} 个节点、${state.graph.edges.length}/${state.graph.scopeEdges.length} 条关联。保留当前平移缩放与节点位置，超出画布的部分按当前视野裁切。节点最多 60 个，连线最多 ${state.edgeLimit} 条；共现不表示配伍功效。`};
    const clean=byId('network-graph').innerHTML.replace(/<(line|circle)\b[^>]*data-network-transient="true"[^>]*(?:\/>|>[\s\S]*?<\/\1>)/g,'').replace(/\sdata-network-hover="[^"]*"/g,'');
    const svg=standaloneFigure(clean,context);
    if(!svg){byId('network-export-status').textContent='当前网络导出失败。';return}
    const token=value=>String(value).replace(/[^\p{L}\p{N}_.-]/gu,'_').slice(0,48);
    downloadResearch(`mingyirx-network-${token(strictGroup)}-${state.mode}-${token(networkItem)}.svg`,svg,'image/svg+xml;charset=utf-8','network-export-status');
  }
  renderResearchNetwork=render;
  exportFigure=kind=>kind==='network'?exportNetwork():originalExport(kind);
  const originalCapture=captureViewState,originalApply=applyViewState,originalReset=resetDashboardView;
  captureViewState=()=>({...originalCapture(),network_view:{key:contextKey(),mode:state.mode,edgeLimit:state.edgeLimit,selected:state.selected}});
  applyViewState=view=>{state.pending=view?.network_view||null;try{originalApply(view)}finally{state.pending=null}};
  resetDashboardView=(...args)=>{state.key='';if(!restoringView)state.pending=null;return originalReset(...args)};
  byId('network-view-mode').addEventListener('change',event=>changeView(()=>{state.mode=event.target.value==='neighborhood'?'neighborhood':'all';render()}));
  byId('network-edge-limit').addEventListener('change',event=>changeView(()=>{state.edgeLimit=Number(event.target.value);render()}));
  byId('network-zoom-in').addEventListener('click',()=>zoom(1.2));byId('network-zoom-out').addEventListener('click',()=>zoom(1/1.2));
  byId('network-fit').addEventListener('click',()=>{fit(true);announce('已适配当前节点位置；拖动布局保留。')});
  byId('network-reset').addEventListener('click',()=>{clearHover(false);state.points=initialPositions(state.graph.nodes);paint();frameLayout();state.paused=false;start();announce('已重置节点位置与视野。')});
  byId('network-motion').addEventListener('click',()=>{if(state.raf||state.hoverHeld){stop();state.hoverHeld=false;state.paused=true}else{clearHover(false);state.paused=false;start()}motionLabel()});
  byId('network-inspector').addEventListener('click',event=>{
    const selectButton=event.target.closest?.('[data-network-select]');if(selectButton){select(selectButton.getAttribute('data-network-select'),true);return}
    if(event.target.closest?.('#network-center-selected'))changeView(()=>{networkItem=state.selected;state.mode='neighborhood';render()});
    if(event.target.closest?.('#network-open-drug'))focusDrug(state.selected);
  });
  reduced.addEventListener?.('change',()=>{if(reduced.matches){stop();state.hoverHeld=false;state.paused=true}motionLabel()});
  finePointer.addEventListener?.('change',()=>clearHover());
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&state.hover)clearHover()});
  if(typeof addEventListener==='function')addEventListener('scroll',()=>{if(state.hover&&!state.drag)placeTooltip()},{passive:true});
  function resizeCanvas(){
    if(!state.svg)return;
    const viewport=readViewport();if(viewport.width===state.viewport.width&&viewport.height===state.viewport.height)return;
    clearHover();state.viewport=viewport;state.svg.setAttribute('viewBox',`0 0 ${viewport.width} ${viewport.height}`);
    for(const selector of ['[data-network-clip]','[data-network-background]']){const rect=state.svg.querySelector(selector);rect?.setAttribute('width',viewport.width);rect?.setAttribute('height',viewport.height)}
    frameLayout();
  }
  if(typeof ResizeObserver==='function')new ResizeObserver(resizeCanvas).observe(byId('network-graph'));
  else if(typeof addEventListener==='function')addEventListener('resize',resizeCanvas);
  render();recordViewState(true);
  function locateNode(name,record=true){
    if(!strictRows('nodes').some(row=>row.item_name===name))return false;
    const locate=()=>{networkItem=name;state.center=name;state.selected=name;render();select(name)};
    if(record)changeView(locate);else locate();return true;
  }
  return Object.freeze({project,initialPositions,getSnapshot,detailMarkup,locateNode,selectNode:name=>select(name),subscribe(listener){subscribers.add(listener);return ()=>subscribers.delete(listener)},suspend2d(value){suspended2d=!!value;if(suspended2d){clearHover(false);stop();if(state.drag&&state.svg?.hasPointerCapture?.(state.drag.id))state.svg.releasePointerCapture(state.drag.id);state.drag=null;state.svg?.classList.remove('is-dragging')}else start();motionLabel()}});
})();
"""


def enhance_network(page: str) -> str:
    """Add an opt-in view without changing prior script bodies or payload bytes."""
    if 'id="network-interactive-script"' in page:
        return page
    marker = '<script id="supplement-data"'
    if marker not in page:
        marker = '<script id="dashboard-data"'
    if marker not in page:
        raise DashboardError("Network payload anchor is missing")
    markup, scripts = page.split(marker, 1)
    expression = r'<h4>\u9996\u8bca\u836f\u5473\u5171\u73b0\u90bb\u57df</h4>.*?<div id="network-edges"></div>'
    matches = list(re.finditer(expression, markup, re.S))
    if len(matches) != 1 or markup.count('</style>') != 1 or scripts.count('</body>') != 1:
        raise DashboardError("Network presentation anchor is missing or ambiguous")
    markup = markup[:matches[0].start()] + NETWORK_HTML + markup[matches[0].end():]
    markup = markup.replace('</style>', NETWORK_CSS + '</style>', 1)
    nav = '<nav class="research-nav"'
    nav_match = re.search(re.escape(nav) + r'[^>]*>', markup)
    if nav_match:
        entry = '<a class="network-entry" href="#network-lab"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M5 6 19 8 11 19 5 6M5 6 11 19" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="5" cy="6" r="3" fill="currentColor"/><circle cx="19" cy="8" r="3" fill="currentColor"/><circle cx="11" cy="19" r="3" fill="currentColor"/></svg>\u836f\u5473\u7f51\u7edc</a>'
        markup = markup[:nav_match.end()] + entry + markup[nav_match.end():]
    script = '<script id="network-interactive-script">' + NETWORK_JS + '</script>'
    return (markup + marker + scripts).replace('</body>', script + '</body>', 1)
