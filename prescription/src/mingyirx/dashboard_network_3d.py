"""Perspective SVG view of the existing, disclosed medication network."""
from __future__ import annotations

from .dashboard import DashboardError


NETWORK_3D_HTML = r"""
      <div class="network-dimension-bar"><div role="group" aria-label="网络维度"><button type="button" class="network-tool" id="network-dimension-3d" aria-pressed="true">3D 空间</button><button type="button" class="network-tool" id="network-dimension-2d" aria-pressed="false">2D 平面</button></div><span id="network3d-mode-note">拖动旋转 · 悬停查看数值</span></div>
      <div id="network3d-workspace">
        <div class="network3d-find"><label for="network3d-search">搜索当前严格队列药味<input id="network3d-search" type="search" placeholder="输入药名，定位已公开节点" autocomplete="off"></label><div role="group" aria-label="网络标签"><button type="button" class="network-tool" id="network3d-label-focus" aria-pressed="true">重点标签</button><button type="button" class="network-tool" id="network3d-label-all" aria-pressed="false">全部标签</button></div><span id="network3d-label-status" aria-live="polite"></span><div id="network3d-search-results" role="group" aria-label="药味搜索结果" hidden></div></div>
        <div class="network3d-toolbar"><div><button type="button" class="network-tool" id="network3d-zoom-out" aria-label="缩小 3D 网络">−</button><output id="network3d-zoom">100%</output><button type="button" class="network-tool" id="network3d-zoom-in" aria-label="放大 3D 网络">＋</button><button type="button" class="network-tool" id="network3d-reset">重置视角</button></div><div><button type="button" class="network-tool" id="network3d-motion" aria-pressed="false">自动旋转</button><span id="network3d-camera" aria-live="off"></span></div></div>
        <div class="network3d-scene-shell"><div id="network3d-scene" tabindex="0" role="region" aria-label="3D 药味共现网络，可用方向键旋转" aria-describedby="network3d-help"></div><div id="network3d-tooltip" class="network-detail-card" role="tooltip" hidden></div><div class="network3d-corner" aria-hidden="true"><span>Y</span><i></i><b>X</b><em>Z</em></div></div>
        <div id="network3d-detail" class="network-detail-card" role="status" aria-live="polite" hidden></div>
        <p class="network3d-note" id="network3d-help">拖动旋转，点按选中；悬停药味或连线查看原有数值。Tab 聚焦后，方向键旋转，＋ / − 缩放，Home 重置，Page Up / Down 浏览节点或连线。三维位置与景深仅用于布局。</p>
      </div>
"""


NETWORK_3D_CSS = r"""
#network-lab .network-dimension-bar{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 16px;background:#0d302c;border-bottom:1px solid #43695d;color:#c3d9d0;font-size:11px;flex-wrap:wrap}
#network-lab .network-dimension-bar>div{display:flex;gap:4px;padding:3px;border:1px solid #547b6c;border-radius:9px;background:#102b28}
#network-lab .network-dimension-bar button{border:0;background:transparent;font-weight:650;min-width:90px;min-height:38px}
#network-lab .network-dimension-bar button[aria-pressed="true"]{background:#d7e9dd;color:#103f35;box-shadow:0 1px 7px #041f2860}
#network-lab[data-network-dimension="3d"] .network-stage>.network-canvas-tools,#network-lab[data-network-dimension="3d"] .network-stage>.network-canvas-shell,#network-lab[data-network-dimension="3d"] #network-touch-details,#network-lab[data-network-dimension="3d"] .network-stage>.network-stage-note{display:none}
#network-lab[data-network-dimension="2d"] #network3d-workspace{display:none}
#network-lab .network3d-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:12px 16px;color:#c7dfd2;background:#123a32}
#network-lab .network3d-toolbar>div{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
#network-lab .network3d-find{display:flex;align-items:end;gap:12px;flex-wrap:wrap;padding:14px 16px;background:#123a32;border-bottom:1px solid #43695d;color:#d3e6d9}
#network-lab .network3d-find label{display:grid;gap:5px;flex:1;min-width:180px;font-size:11px}#network-lab .network3d-find input{width:100%;min-height:44px;padding:9px 12px;border:1px solid #547b6c;border-radius:7px;background:#0e302b;color:#f1f7ed;font:inherit;font-size:13px}#network-lab .network3d-find input::placeholder{color:#b2ccbc}
#network-lab .network3d-find [role="group"]{display:flex;gap:5px;flex-wrap:wrap}#network-lab .network3d-find button{min-height:44px}#network-lab .network3d-find button[aria-pressed="true"]{background:#d7e9dd;color:#103f35}#network-lab #network3d-label-status{flex-basis:100%;font-size:11px;min-height:17px;color:#b7d3c0}
#network-lab #network3d-search-results{flex-basis:100%;max-height:180px;overflow:auto}#network-lab #network3d-search-results[hidden]{display:none}#network-lab #network3d-search-results button{max-width:100%;overflow-wrap:anywhere;text-align:left}
#network-lab #network3d-zoom{min-width:44px;text-align:center;font:12px/1.4 ui-monospace,monospace}
#network-lab #network3d-camera{font:10px/1.5 ui-monospace,monospace;color:#aac9b9}
#network-lab .network3d-scene-shell{position:relative;min-width:0;background:#0b2c28}
#network-lab #network3d-scene{min-height:480px;height:560px;overflow:hidden;touch-action:none;cursor:grab;outline-offset:-4px}
#network-lab #network3d-scene:focus-visible{outline:3px solid #e7c58b}
#network-lab #network3d-scene.is-dragging{cursor:grabbing}
#network-lab #network3d-scene svg{display:block;width:100%;height:100%;overflow:hidden}
#network-lab #network3d-scene .empty{margin:24px;background:#143c32;color:#dceee3;border-color:#57856f}
#network-lab [data-network3d-node],#network-lab [data-network3d-edge-hit]{outline:none;cursor:pointer}
#network-lab [data-network3d-node]:focus-visible .network3d-orbit{stroke:#fff;stroke-width:4;opacity:1}
#network-lab [data-network3d-edge-hit]:focus-visible{stroke:#fff;stroke-opacity:.45}
#network-lab .network3d-label{paint-order:stroke;stroke:#0b2c28;stroke-width:3;stroke-linejoin:round;pointer-events:none;user-select:none}
#network-lab #network3d-tooltip{position:absolute;z-index:5;pointer-events:none;max-width:calc(100% - 24px);width:280px}
#network-lab #network3d-detail{border-radius:0;border-width:1px 0 0;box-shadow:none}
#network-lab .network3d-note{margin:0!important;padding:13px 16px;background:#10342e;border-top:1px solid #45695b;color:#c5dacc;font-size:11px!important;line-height:1.7}
#network-lab .network3d-corner{position:absolute;pointer-events:none;bottom:19px;left:24px;color:#9dbcaa;font:10px/1 ui-monospace,monospace;width:46px;height:44px;opacity:.8}
#network-lab .network3d-corner i{display:block;width:25px;height:24px;border-left:1px solid #9dbcaa;border-bottom:1px solid #9dbcaa;position:absolute;left:12px;top:6px}
#network-lab .network3d-corner span{position:absolute;left:10px;top:-3px}#network-lab .network3d-corner b{position:absolute;left:41px;top:26px;font-weight:400}#network-lab .network3d-corner em{position:absolute;left:0;top:37px;font-style:normal}
@media(max-width:600px){#network-lab #network3d-scene{height:440px;min-height:440px}#network-lab .network3d-toolbar{padding:10px;gap:9px}#network-lab .network3d-toolbar .network-tool,#network-lab .network-dimension-bar button{min-height:44px;min-width:44px}#network-lab .network-dimension-bar{padding:10px}#network-lab #network3d-camera{font-size:10px}#network-lab .network3d-note{padding:12px}}
"""


NETWORK_3D_JS = r"""
const MingYiRxNetwork3D = (() => {
  'use strict';
  const byId=id=>document.getElementById(id),bridge=MingYiRxNetwork;
  const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));
  const finite=value=>typeof value==='number'&&Number.isFinite(value);
  const reduced=typeof matchMedia==='function'?matchMedia('(prefers-reduced-motion: reduce)'):{matches:true};
  const stage=byId('network3d-scene'),lab=byId('network-lab');
  const defaultCamera=()=>({yaw:.38,pitch:-.18,zoom:1});
  const state={dimension:'3d',camera:defaultCamera(),snapshot:null,points:[],svg:null,width:960,height:640,auto:false,raf:0,lastFrame:0,hover:null,held:false,focused:false,focusedNode:null,drag:null,suppressClick:false,visible:true,pending:null,labels:'focus',source:'',lastPointer:null};
  const cameraListeners=new Set();let cameraSignature='',resetRequested=false;
  /** Equal-area sphere positions are presentation-only; no edge weights enter. */
  function layout(nodes,universe=nodes){
    const names=[...new Set(universe.map(row=>String(row.item_name)))].sort(),positions=new Map(names.map((name,index)=>{
      if(names.length===1)return [name,{name,x:0,y:0,z:0}];
      const y=1-2*(index+.5)/names.length,r=Math.sqrt(1-y*y),angle=index*2.399963229728653;
      return [name,{name,x:215*r*Math.cos(angle),y:215*y,z:215*r*Math.sin(angle)}];
    }));
    return [...new Set(nodes.map(row=>String(row.item_name)))].map(name=>positions.get(name)).filter(Boolean).map(point=>({...point}));
  }
  function labelLines(name){const letters=Array.from(name),lines=[];for(let index=0;index<letters.length;index+=7)lines.push(letters.slice(index,index+7).join(''));if(lines.length>3)lines[2]=lines[2].slice(0,6)+'…';return lines.slice(0,3)}
  /** Greedy screen-space placement is bounded by the existing 60-node cap. */
  function labelPositions(graph,points,selected,priority,width,height,mode='focus'){
    const neighbors=new Set();for(const edge of graph.edges)if([selected,priority].includes(edge.item_1)||[selected,priority].includes(edge.item_2)){neighbors.add(edge.item_1);neighbors.add(edge.item_2)}
    const rank=name=>name===priority?0:name===selected?1:neighbors.has(name)?2:3;
    const ordered=graph.nodes.map(row=>row.item_name).sort((a,b)=>rank(a)-rank(b)||(a<b?-1:a>b?1:0));
    const placed=new Map(),boxes=[];
    for(const name of ordered){
      if(mode!=='all'&&rank(name)>2)continue;const p=points.get(name);if(!p)continue;
      const lines=labelLines(name),scale=Math.min(1.35,Math.max(.8,p.scale)),w=Math.min(width-16,Math.max(...lines.map(line=>Array.from(line).reduce((n,ch)=>n+(/[\u0000-\u007f]/.test(ch)?7:12),0)))*scale+8),h=lines.length*15*scale+5,r=25*p.scale;
      const candidates=[[p.x-w/2,p.y+r+5],[p.x+r+6,p.y-h/2],[p.x-w-r-6,p.y-h/2],[p.x-w/2,p.y-r-h-5]];
      for(const [rawX,rawY] of candidates){const x=clamp(rawX,8,Math.max(8,width-w-8)),y=clamp(rawY,8,Math.max(8,height-h-8)),box={x,y,w,h};
        if(boxes.some(b=>x<b.x+b.w+5&&x+w+5>b.x&&y<b.y+b.h+4&&y+h+4>b.y))continue;
        boxes.push(box);placed.set(name,{...box,scale,lines});break;
      }
    }return placed;
  }
  /** Rotate both axes, then apply a positive perspective denominator. */
  function project(point,camera,width=960,height=640){
    const cy=Math.cos(camera.yaw),sy=Math.sin(camera.yaw),cp=Math.cos(camera.pitch),sp=Math.sin(camera.pitch);
    const x=point.x*cy+point.z*sy,z0=-point.x*sy+point.z*cy,y=point.y*cp-z0*sp,z=point.y*sp+z0*cp;
    const perspective=850/(850+z),fit=Math.min(width/580,height/580)*camera.zoom;
    return {name:point.name,x:width/2+x*perspective*fit,y:height/2+y*perspective*fit,z,scale:perspective*fit,depth:clamp((z+215)/430,0,1)};
  }
  function stop(){if(state.raf)cancelAnimationFrame(state.raf);state.raf=0;state.lastFrame=0}
  function canAnimate(){return state.dimension==='3d'&&state.auto&&!reduced.matches&&!document.hidden&&state.visible&&!state.hover&&!state.held&&!state.focused&&!state.drag&&!!state.points.length}
  function syncMotion(){
    const button=byId('network3d-motion');button.disabled=reduced.matches||!state.points.length;
    button.setAttribute('aria-pressed',String(state.auto));
    button.textContent=reduced.matches?'已减少动态':state.auto?'暂停旋转':'自动旋转';
    stage.setAttribute('data-motion-state',reduced.matches?'reduced':canAnimate()?'running':state.auto?'reading':'paused');
    if(!canAnimate()){stop();return}if(!state.raf)state.raf=requestAnimationFrame(tick);
  }
  function tick(time){
    state.raf=0;if(!canAnimate()){syncMotion();return}
    const dt=state.lastFrame?Math.min(40,Math.max(0,time-state.lastFrame)):16;state.lastFrame=time;
    state.camera.yaw+=dt*.000075;paint();state.raf=requestAnimationFrame(tick);
  }
  function cleanInteraction(){
    stop();if(state.drag&&stage.hasPointerCapture?.(state.drag.id))stage.releasePointerCapture(state.drag.id);
    state.drag=null;state.suppressClick=false;stage.classList.remove('is-dragging');clearDetail(false);state.focused=false;state.focusedNode=null;
  }
  function viewport(){
    const box=stage.getBoundingClientRect();state.width=Math.max(280,Math.round(box.width||960));state.height=Math.max(360,Math.round(box.height||560));
    state.svg?.setAttribute('viewBox',`0 0 ${state.width} ${state.height}`);
    for(const selector of ['[data-network3d-background]','[data-network3d-cliprect]']){const rect=state.svg?.querySelector(selector);rect?.setAttribute('width',state.width);rect?.setAttribute('height',state.height)}
    const orbit=state.svg?.querySelector('[data-network3d-equator]');if(orbit){orbit.setAttribute('cx',state.width/2);orbit.setAttribute('cy',state.height/2);orbit.setAttribute('rx',Math.min(state.width,state.height)*.4);orbit.setAttribute('ry',Math.min(state.width,state.height)*.16)}
  }
  function targetFor(element){
    const node=element?.closest?.('[data-network3d-node]');if(node)return {kind:'node',name:node.getAttribute('data-network3d-node'),element:node};
    const edge=element?.closest?.('[data-network3d-edge-hit]');return edge?{kind:'edge',index:Number(edge.getAttribute('data-network3d-edge-hit')),element:edge}:null;
  }
  function clearDetail(resume=true){
    state.hover?.element?.removeAttribute('aria-describedby');state.hover=null;state.held=false;state.lastPointer=null;
    for(const id of ['network3d-tooltip','network3d-detail']){byId(id).hidden=true;byId(id).innerHTML=''}
    paint();if(resume)syncMotion();
  }
  function showDetail(target,event,persistent=false){
    if(!target)return;state.hover?.element?.removeAttribute('aria-describedby');
    const content=bridge.detailMarkup(target);if(!content)return;
    state.hover=target;state.held=persistent;stop();
    const card=byId(persistent?'network3d-detail':'network3d-tooltip'),other=byId(persistent?'network3d-tooltip':'network3d-detail');
    other.hidden=true;card.innerHTML=content;card.hidden=false;target.element?.setAttribute('aria-describedby',card.id);
    if(!persistent){
      const rect=stage.getBoundingClientRect(),size=card.getBoundingClientRect();
      const x=event&&finite(event.clientX)?event.clientX-rect.left:rect.width/2,y=event&&finite(event.clientY)?event.clientY-rect.top:30;
      card.style.left=clamp(x+18,12,Math.max(12,rect.width-size.width-12))+'px';
      card.style.top=clamp(y+14,12,Math.max(12,rect.height-size.height-12))+'px';
    }
    paint();syncMotion();
  }
  const number=value=>Number(value).toFixed(3);
  function paint(){
    if(!state.svg)return;
    const projected=new Map(state.points.map(point=>{const p=project(point,state.camera,state.width,state.height);return [p.name,p]}));
    const selected=state.snapshot.selected,hover=state.hover,neighbors=new Set();
    const labels=labelPositions(state.snapshot.graph,projected,selected,hover?.kind==='node'?hover.name:state.focusedNode?.getAttribute('data-network3d-node'),state.width,state.height,state.labels);
    if(hover?.kind==='node'){neighbors.add(hover.name);for(const edge of state.snapshot.graph.edges)if(edge.item_1===hover.name||edge.item_2===hover.name){neighbors.add(edge.item_1);neighbors.add(edge.item_2)}}
    if(hover?.kind==='edge'){const edge=state.snapshot.graph.edges[hover.index];if(edge){neighbors.add(edge.item_1);neighbors.add(edge.item_2)}}
    const nodes=[...state.svg.querySelectorAll('[data-network3d-node]')];
    for(const node of nodes){
      const name=node.getAttribute('data-network3d-node'),p=projected.get(name),active=name===selected,highlight=neighbors.has(name);
      node.setAttribute('transform',`translate(${number(p.x)} ${number(p.y)}) scale(${number(p.scale)})`);
      node.setAttribute('data-depth',number(p.z));node.setAttribute('aria-pressed',String(active));node.setAttribute('tabindex',active?'0':'-1');
      node.setAttribute('opacity',hover&&!active&&!highlight?'.42':String(1-p.depth*.23));
      node.querySelector('.network3d-ball').setAttribute('fill',active?'url(#network3d-gold)':'url(#network3d-jade)');
      node.querySelector('.network3d-orbit').setAttribute('opacity',active||highlight?'1':'0');
      const label=labels.get(name),text=node.querySelector('.network3d-label');node.setAttribute('data-label-visible',String(!!label));
      if(text){text.setAttribute('visibility',label?'visible':'hidden');if(label){text.setAttribute('transform',`translate(${number((label.x+label.w/2-p.x)/p.scale)} ${number((label.y+12*label.scale-p.y)/p.scale)}) scale(${number(label.scale/p.scale)})`)}}
    }
    for(const line of state.svg.querySelectorAll('[data-network3d-edge], [data-network3d-edge-hit]')){
      const raw=line.getAttribute('data-network3d-edge'),index=Number(raw===null?line.getAttribute('data-network3d-edge-hit'):raw),edge=state.snapshot.graph.edges[index],a=projected.get(edge.item_1),b=projected.get(edge.item_2);
      for(const [key,value] of Object.entries({x1:a.x,y1:a.y,x2:b.x,y2:b.y}))line.setAttribute(key,number(value));
      if(raw!==null){const active=edge.item_1===selected||edge.item_2===selected,highlight=hover?.kind==='node'?(edge.item_1===hover.name||edge.item_2===hover.name):hover?.kind==='edge'&&hover.index===index;
        line.setAttribute('stroke',highlight?'#fff1cc':active?'#e7c58b':'#7fb99f');line.setAttribute('stroke-opacity',String(hover?highlight?.95:.08:active?.74:.18+(1-(a.depth+b.depth)/2)*.22));
      }
    }
    // Move only siblings around the focused node: preserve focus and depth order.
    const layer=state.svg.querySelector('[data-network3d-nodes]');let next=null;
    for(const node of nodes.sort((a,b)=>Number(a.getAttribute('data-depth'))-Number(b.getAttribute('data-depth')))){if(node!==state.focusedNode&&node.nextSibling!==next)layer.insertBefore(node,next);next=node}
    byId('network3d-zoom').textContent=Math.round(state.camera.zoom*100)+'%';
    byId('network3d-camera').textContent=`Y ${Math.round(state.camera.yaw*180/Math.PI)}° / X ${Math.round(state.camera.pitch*180/Math.PI)}°`;
    stage.setAttribute('data-camera',JSON.stringify(state.camera));
    byId('network3d-label-status').textContent=`显示 ${labels.size} / ${nodes.length} 个标签 · ${state.labels==='all'?'全部标签按空间避让':'优先选中药、焦点药及直接邻居'}；完整药名可在详情查看。`;
    const signature=JSON.stringify(state.camera);if(signature!==cameraSignature){cameraSignature=signature;for(const listener of cameraListeners)listener({...state.camera})}
  }
  function sceneMarkup(graph,interactive=true){
    const points=new Map(state.points.map(point=>{const p=project(point,state.camera,state.width,state.height);return [p.name,p]}));
    const placements=labelPositions(graph,points,state.snapshot.selected,null,state.width,state.height,state.labels);
    const links=graph.edges.map((edge,index)=>{
      const a=points.get(edge.item_1),b=points.get(edge.item_2),attributes=`x1="${number(a.x)}" y1="${number(a.y)}" x2="${number(b.x)}" y2="${number(b.y)}"`,score=edge.cosine_similarity;
      const width=score!==null&&score!==undefined&&score!==''&&Number.isFinite(Number(score))?1+Math.max(0,Number(score))*3:1;
      const active=edge.item_1===state.snapshot.selected||edge.item_2===state.snapshot.selected;
      return `<line data-network3d-edge="${index}" ${attributes} stroke="${active?'#e7c58b':'#7fb99f'}" stroke-opacity="${active?.74:.18+(1-(a.depth+b.depth)/2)*.22}" stroke-width="${width}"/>`;
    }).join('');
    const hits=interactive?graph.edges.map((edge,index)=>`<line data-network3d-edge-hit="${index}" tabindex="${index===0?'0':'-1'}" role="button" aria-label="${escapeHtml(edge.item_1+' 与 '+edge.item_2+'，按 Enter 查看关联数值')}" stroke="transparent" stroke-width="16" pointer-events="stroke"/>`).join(''):'';
    const nodes=graph.nodes.slice().sort((a,b)=>points.get(b.item_name).z-points.get(a.item_name).z).map(row=>{
      const name=row.item_name,p=points.get(name),active=name===state.snapshot.selected,labels=labelLines(name),label=placements.get(name);
      return `<g data-network3d-node="${escapeHtml(name)}" data-label-visible="${!!label}" transform="translate(${number(p.x)} ${number(p.y)}) scale(${number(p.scale)})" opacity="${1-p.depth*.23}" ${interactive?`role="button" tabindex="${active?'0':'-1'}" aria-pressed="${active}" aria-label="${escapeHtml(name+'，首诊覆盖率 '+metricText(row.prevalence,'percent')+'，按 Enter 选中')}"`:''}><title>${escapeHtml(name)}</title><circle class="network3d-orbit" r="28" fill="none" stroke="#e8ca8c" stroke-width="1.7" opacity="${active?'1':'0'}"/><circle class="network3d-ball" r="23" fill="url(#network3d-${active?'gold':'jade'})" stroke="#a0c8af" stroke-opacity=".7" stroke-width=".7"/><ellipse cx="-7" cy="-9" rx="6" ry="3" fill="#f2fff2" opacity=".28" pointer-events="none"/><text class="network3d-label" visibility="${label?'visible':'hidden'}" ${label?`transform="translate(${number((label.x+label.w/2-p.x)/p.scale)} ${number((label.y+12*label.scale-p.y)/p.scale)}) scale(${number(label.scale/p.scale)})"`:''} fill="#f2f8ed" text-anchor="middle" font-size="12" font-weight="600" paint-order="stroke" stroke="#0b2c28" stroke-width="3" stroke-linejoin="round">${labels.map((line,index)=>`<tspan x="0" y="${index*15}">${escapeHtml(line)}</tspan>`).join('')}</text></g>`;
    }).join('');
    return `<svg viewBox="0 0 ${state.width} ${state.height}" role="group" aria-label="三维药味共现网络，${graph.nodes.length} 个节点，${graph.edges.length} 条关联" font-family="Microsoft YaHei, PingFang SC, sans-serif"><title>三维药味共现网络</title><desc>确定性三维布局，双轴旋转及透视投影。空间位置、大小和景深没有临床含义。</desc><defs><clipPath id="network3d-clip"><rect data-network3d-cliprect="true" width="${state.width}" height="${state.height}"/></clipPath><radialGradient id="network3d-jade" cx="30%" cy="25%" r="75%"><stop offset="0" stop-color="#91c5a2"/><stop offset=".42" stop-color="#36785c"/><stop offset="1" stop-color="#123d34"/></radialGradient><radialGradient id="network3d-gold" cx="30%" cy="25%" r="75%"><stop offset="0" stop-color="#ffedb5"/><stop offset=".45" stop-color="#b98c42"/><stop offset="1" stop-color="#534529"/></radialGradient><radialGradient id="network3d-space"><stop stop-color="#204b3b"/><stop offset="1" stop-color="#0a2926"/></radialGradient></defs><g clip-path="url(#network3d-clip)"><rect data-network3d-background="true" width="${state.width}" height="${state.height}" fill="url(#network3d-space)"/><ellipse data-network3d-equator="true" cx="${state.width/2}" cy="${state.height/2}" rx="${Math.min(state.width,state.height)*.4}" ry="${Math.min(state.width,state.height)*.16}" fill="none" stroke="#66947b" stroke-opacity=".13" stroke-dasharray="3 7"/><g data-network3d-edges="true">${links}${hits}</g><g data-network3d-nodes="true">${nodes}</g></g></svg>`;
  }
  function validCamera(value){return value&&finite(value.yaw)&&finite(value.pitch)&&finite(value.zoom)?{yaw:value.yaw%(2*Math.PI),pitch:clamp(value.pitch,-1.45,1.45),zoom:clamp(value.zoom,.5,2.5)}:defaultCamera()}
  function refresh(snapshot,reason='graph'){
    if(reason==='selection'){state.snapshot=snapshot;paint();return}
    if(resetRequested){state.dimension='3d';state.camera=defaultCamera();state.pending=null;state.labels='focus';byId('network3d-search').value='';resetRequested=false}
    const source=data.source_identity?.key||provenance.dataset_id||'',changed=state.source!==source;cleanInteraction();state.auto=false;state.snapshot=snapshot;
    if(changed){state.camera=defaultCamera();state.labels='focus';byId('network3d-search').value=''}state.source=source;
    if(state.pending&&state.pending.key===snapshot.key){state.dimension=state.pending.dimension==='2d'?'2d':'3d';state.camera=validCamera(state.pending.camera);state.labels=state.pending.labels==='all'?'all':'focus'}
    state.points=layout(snapshot.graph?.nodes||[],researchRows('nodes'));viewport();
    stage.innerHTML=state.points.length?sceneMarkup(snapshot.graph):'<div class="empty">当前来源与严格队列没有公开的网络节点。切换来源或队列可查看已有汇总。</div>';
    state.svg=stage.querySelector('svg');
    for(const id of ['network3d-zoom-in','network3d-zoom-out','network3d-reset'])byId(id).disabled=!state.points.length;
    for(const mode of ['focus','all'])byId('network3d-label-'+mode).setAttribute('aria-pressed',String(state.labels===mode));
    renderSearch();setDimension(state.dimension,false);paint();syncMotion();
  }
  function setDimension(dimension,record=true){
    cleanInteraction();state.dimension=dimension==='2d'?'2d':'3d';state.auto=false;lab.setAttribute('data-network-dimension',state.dimension);
    bridge.suspend2d(state.dimension==='3d');
    for(const value of ['3d','2d'])byId('network-dimension-'+value).setAttribute('aria-pressed',String(state.dimension===value));
    byId('network3d-mode-note').textContent=state.dimension==='3d'?'拖动旋转 · 悬停查看数值':'拖动节点 · 平移与缩放';
    if(state.dimension==='3d'){viewport();paint()}syncMotion();if(record)recordViewState(true);
  }
  function cameraChange(change){stop();state.auto=false;clearDetail(false);change();paint();syncMotion();recordViewState(true)}
  function zoom(factor){cameraChange(()=>{state.camera.zoom=clamp(state.camera.zoom*factor,.5,2.5)})}
  function reset(){cameraChange(()=>{state.camera=defaultCamera()})}
  function renderSearch(){
    const query=byId('network3d-search').value.trim().toLocaleLowerCase(),box=byId('network3d-search-results');box.hidden=!query;
    const rows=strictRows('nodes').filter(row=>String(row.item_name).toLocaleLowerCase().includes(query));
    box.innerHTML=query?(rows.slice(0,16).map(row=>`<button type="button" class="network-tool" data-network3d-locate="${escapeHtml(row.item_name)}">${escapeHtml(row.item_name)}</button>`).join('')||'<span>当前严格队列无匹配的公开药味。</span>'):'';
    if(query&&rows.length>16)box.innerHTML+='<span>显示前 16 项，请继续输入缩小范围。</span>';
  }
  function locate(name){
    if(!bridge.locateNode(name))return false;
    const point=state.points.find(row=>row.name===name);if(point)cameraChange(()=>{state.camera={yaw:Math.atan2(point.x,-point.z),pitch:Math.atan2(-point.y,Math.hypot(point.x,point.z)),zoom:1}});
    const node=[...state.svg.querySelectorAll('[data-network3d-node]')].find(element=>element.getAttribute('data-network3d-node')===name);node?.focus({preventScroll:true});if(node)showDetail(targetFor(node),null,true);return true;
  }
  function selectTarget(target,event,persistent=true){if(!target)return;if(target.kind==='node')bridge.selectNode(target.name);showDetail(target,event,persistent)}
  stage.addEventListener('pointerdown',event=>{
    if(event.button!==0||!state.points.length)return;const target=targetFor(event.target);(target?.element||stage).focus({preventScroll:true});clearDetail(false);state.suppressClick=false;
    state.drag={id:event.pointerId,x:event.clientX,y:event.clientY,yaw:state.camera.yaw,pitch:state.camera.pitch,target,moved:false,touch:event.pointerType==='touch'};
    stop();stage.setPointerCapture?.(event.pointerId);stage.classList.add('is-dragging');event.preventDefault();
  });
  stage.addEventListener('pointermove',event=>{
    if(!state.drag){if(event.pointerType!=='touch'&&!state.held){if(state.lastPointer&&state.lastPointer.x===event.clientX&&state.lastPointer.y===event.clientY)return;const target=targetFor(event.target);if(target)showDetail(target,event);else if(state.hover)clearDetail();state.lastPointer={x:event.clientX,y:event.clientY}}return}
    if(state.drag.id!==event.pointerId)return;const dx=event.clientX-state.drag.x,dy=event.clientY-state.drag.y;
    if(Math.hypot(dx,dy)>5){state.drag.moved=true;state.auto=false}
    if(state.drag.moved){state.camera.yaw=state.drag.yaw+dx*.009;state.camera.pitch=clamp(state.drag.pitch+dy*.009,-1.45,1.45);paint()}
  });
  function finishPointer(event,cancelled=false){
    if(!state.drag||state.drag.id!==event.pointerId)return;const drag=state.drag;state.drag=null;
    if(stage.hasPointerCapture?.(event.pointerId))stage.releasePointerCapture(event.pointerId);stage.classList.remove('is-dragging');
    state.suppressClick=drag.moved||cancelled;
    if(!cancelled&&!drag.moved)selectTarget(drag.target,event,true);else if(drag.moved)recordViewState(true);
    syncMotion();
  }
  stage.addEventListener('pointerup',event=>finishPointer(event));stage.addEventListener('pointercancel',event=>finishPointer(event,true));
  stage.addEventListener('lostpointercapture',event=>finishPointer(event,true));
  stage.addEventListener('click',event=>{if(state.suppressClick){state.suppressClick=false;return}selectTarget(targetFor(event.target),event,true)});
  stage.addEventListener('pointerleave',()=>{if(!state.drag&&!state.held)clearDetail()});
  stage.addEventListener('focusin',event=>{state.focused=true;const target=targetFor(event.target);state.focusedNode=target?.kind==='node'?target.element:null;if(target)showDetail(target,null,true);syncMotion()});
  stage.addEventListener('focusout',event=>{if(stage.contains?.(event.relatedTarget))return;state.focused=false;state.focusedNode=null;if(!state.drag)clearDetail();syncMotion()});
  stage.addEventListener('wheel',event=>{if(!event.ctrlKey&&!event.metaKey)return;event.preventDefault();zoom(event.deltaY<0?1.12:1/1.12)},{passive:false});
  stage.addEventListener('keydown',event=>{
    const key=event.key,target=targetFor(event.target);
    if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(key)){event.preventDefault();cameraChange(()=>{state.camera.yaw+=(key==='ArrowRight'?1:key==='ArrowLeft'?-1:0)*.12;state.camera.pitch=clamp(state.camera.pitch+(key==='ArrowDown'?1:key==='ArrowUp'?-1:0)*.12,-1.45,1.45)});return}
    if(['+','=','-','Home','0','Escape'].includes(key)){event.preventDefault();if(key==='+'||key==='=')zoom(1.12);else if(key==='-')zoom(1/1.12);else if(key==='Escape')clearDetail();else reset();return}
    if((key==='Enter'||key===' ')&&target){event.preventDefault();selectTarget(target,null,true);return}
    if((key==='PageDown'||key==='PageUp')&&state.svg){event.preventDefault();const selector=target?.kind==='edge'?'[data-network3d-edge-hit]':'[data-network3d-node]',items=[...state.svg.querySelectorAll(selector)].sort((a,b)=>selector.includes('node')?state.points.findIndex(p=>p.name===a.getAttribute('data-network3d-node'))-state.points.findIndex(p=>p.name===b.getAttribute('data-network3d-node')):0);
      const index=items.indexOf(target?.element),next=items[(index+(key==='PageDown'?1:-1)+items.length)%items.length];next?.focus({preventScroll:true});if(next)showDetail(targetFor(next),null,true);
    }
  });
  byId('network-dimension-3d').addEventListener('click',()=>changeView(()=>setDimension('3d',false)));
  byId('network-dimension-2d').addEventListener('click',()=>changeView(()=>setDimension('2d',false)));
  byId('network3d-zoom-in').addEventListener('click',()=>zoom(1.2));byId('network3d-zoom-out').addEventListener('click',()=>zoom(1/1.2));
  byId('network3d-reset').addEventListener('click',reset);
  byId('network3d-motion').addEventListener('click',()=>{clearDetail(false);state.auto=!state.auto;syncMotion()});
  byId('network3d-search').addEventListener('input',renderSearch);
  byId('network3d-search').addEventListener('keydown',event=>{if(event.key==='Enter'){const button=byId('network3d-search-results').querySelector('[data-network3d-locate]');if(button){event.preventDefault();locate(button.getAttribute('data-network3d-locate'))}}});
  byId('network3d-search-results').addEventListener('click',event=>{const button=event.target.closest?.('[data-network3d-locate]');if(button)locate(button.getAttribute('data-network3d-locate'))});
  for(const mode of ['focus','all'])byId('network3d-label-'+mode).addEventListener('click',()=>changeView(()=>{state.labels=mode;for(const value of ['focus','all'])byId('network3d-label-'+value).setAttribute('aria-pressed',String(value===mode));paint()}));
  const originalCapture=captureViewState,originalApply=applyViewState,originalReset=resetDashboardView,originalExport=exportFigure;
  captureViewState=()=>({...originalCapture(),network_3d:{key:state.snapshot?.key,dimension:state.dimension,camera:{...state.camera},labels:state.labels}});
  applyViewState=view=>{state.pending=view?.network_3d||null;if(!state.pending){state.dimension='3d';state.camera=defaultCamera()}try{originalApply(view)}finally{state.pending=null}};
  resetDashboardView=(...args)=>{if(!restoringView)resetRequested=true;return originalReset(...args)};
  function export3d(){
    if(!state.points.length){byId('network-export-status').textContent='当前没有可导出的公开网络。';return}
    stop();state.auto=false;clearDetail(false);syncMotion();const graph=state.snapshot.graph;
    const context={kind:'network',title:'三维首诊药味共现网络',subtitle:byId('network-context').textContent,item:state.snapshot.center,group:strictGroup,stratum_type:'overall',stratum:'all',mode:state.snapshot.mode,dimension:'3d',selected:state.snapshot.selected,node_limit:60,edge_limit:state.snapshot.edgeLimit,displayed_nodes:graph.nodes,displayed_edges:graph.edges,available_nodes:graph.scopeNodes.length,available_edges:graph.scopeEdges.length,viewport:{width:state.width,height:state.height},camera:{...state.camera,focal_length:850},layout:state.points.map(point=>({...point})),projection:'yaw-pitch perspective; positive z recedes',denominator:byId('network-scope').textContent,note:'确定性三维坐标与透视景深仅用于布局，空间距离和大小没有临床含义。共现不表示配伍功效。'};
    // Build from the current camera and canonical rows, excluding interaction overlays.
    const svg=standaloneFigure(sceneMarkup(graph,false),context);if(!svg){byId('network-export-status').textContent='当前网络导出失败。';return}
    const token=value=>String(value).replace(/[^\p{L}\p{N}_.-]/gu,'_').slice(0,48);
    downloadResearch(`mingyirx-network-3d-${token(strictGroup)}-${state.snapshot.mode}.svg`,svg,'image/svg+xml;charset=utf-8','network-export-status');
  }
  exportFigure=kind=>kind==='network'&&state.dimension==='3d'?export3d():originalExport(kind);
  reduced.addEventListener?.('change',()=>{if(reduced.matches)state.auto=false;syncMotion()});
  document.addEventListener('visibilitychange',()=>syncMotion());
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&state.dimension==='3d'&&state.hover)clearDetail()});
  if(typeof addEventListener==='function'){addEventListener('pagehide',()=>{state.auto=false;cleanInteraction()});addEventListener('resize',()=>{if(state.dimension==='3d'){viewport();paint()}})}
  if(typeof ResizeObserver==='function')new ResizeObserver(()=>{if(state.dimension==='3d'){viewport();paint()}}).observe(stage);
  if(typeof IntersectionObserver==='function')new IntersectionObserver(entries=>{state.visible=entries.some(entry=>entry.isIntersecting);syncMotion()},{threshold:.05}).observe(stage);
  bridge.subscribe(refresh);refresh(bridge.getSnapshot());recordViewState(true);
  return Object.freeze({layout,project,labelPositions,labelLines,locate,getCamera:()=>({...state.camera}),setCamera:value=>cameraChange(()=>{state.camera=validCamera(value)}),subscribeCamera(listener){cameraListeners.add(listener);return ()=>cameraListeners.delete(listener)}});
})();
"""


def enhance_network_3d(page: str) -> str:
    """Append a 3D adapter, preserving payload bytes and all original controls."""
    if 'id="network-3d-script"' in page:
        return page
    if 'id="network-interactive-script"' not in page:
        raise DashboardError("3D network requires the interactive network adapter")
    marker = '<script id="supplement-data"' if '<script id="supplement-data"' in page else '<script id="dashboard-data"'
    if page.count(marker) != 1:
        raise DashboardError("3D network payload anchor is missing or ambiguous")
    markup, scripts = page.split(marker, 1)
    anchor = '<div class="network-stage">'
    if markup.count(anchor) != 1 or markup.count('</style>') != 1 or scripts.count('</body>') != 1:
        raise DashboardError("3D network presentation anchors are missing or ambiguous")
    markup = markup.replace(anchor, anchor + NETWORK_3D_HTML, 1)
    markup = markup.replace('id="network-lab"', 'id="network-lab" data-network-dimension="3d"', 1)
    markup = markup.replace('</style>', NETWORK_3D_CSS + '</style>', 1)
    script = '<script id="network-3d-script">' + NETWORK_3D_JS + '</script>'
    return (markup + marker + scripts).replace('</body>', script + '</body>', 1)
