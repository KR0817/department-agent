"""Native, offline adaptations of MIT-licensed ThreeUI Community controls."""
from __future__ import annotations

import re

from .dashboard import DashboardError


UPSTREAM_URL = "https://github.com/MengTo/threeui/tree/68802d5428071ada5c20db8094b1649e6bb770ed"
UPSTREAM_LICENSE = """MIT License

Copyright (c) 2026 Meng To

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


# Adapted from community.css (AnimatedTopDock sable) and the layered native
# button in spinning-border-button.html. Slots remain fixed; only content moves.
COMMUNITY_CSS = r"""
.local-original-view{--community-safety-height:36px;--community-anchor-offset:142px}
.local-original-view :is(#disease-overview,#item-research,#annual-section,#comparison-section,#strict-research,#network-lab,#research-quality,#formula-evidence,#main-workbench){scroll-margin-top:var(--community-anchor-offset)!important}
.local-original-view #community-dock-frame{position:sticky;top:var(--community-safety-height);z-index:19;isolation:isolate;min-width:0;margin:-8px 0 24px;padding:10px 0 0;background:var(--canvas)}
.local-original-view .community-dock-shell{display:flex;align-items:center;gap:10px;min-width:0;padding:5px 8px;border:1px solid #3d5d50;border-radius:13px;background:linear-gradient(180deg,#183c33,#102a25);box-shadow:0 8px 24px #102a2524,inset 0 1px #ffffff12;isolation:isolate}
.local-original-view .community-dock-brand{flex:none;padding:0 12px 0 8px;color:#f3f5e8;font:600 14px/1.3 Georgia,serif;letter-spacing:-.02em;border-right:1px solid #65807366}
.local-original-view .community-dock-brand small{display:block;color:#b5c8bb;font:10px/1.4 "Microsoft YaHei",sans-serif;letter-spacing:.08em;margin-top:3px}
.local-original-view #community-dock{display:flex;flex:1;flex-wrap:nowrap;align-items:center;gap:3px;min-width:0;overflow-x:auto;overflow-y:hidden;scrollbar-width:thin;scrollbar-color:#668576 #17382e;margin:0;padding:4px 2px;scroll-behavior:auto;overscroll-behavior-x:contain}
.local-original-view #community-dock a{position:relative;display:inline-flex;flex:0 0 106px;align-items:center;justify-content:center;min-width:0;height:48px;min-height:48px;padding:0 8px;border:1px solid transparent;border-radius:8px;outline:none;color:#d4e2d7;background:#18392f;font:500 13px/1.4 "Microsoft YaHei","PingFang SC",sans-serif;white-space:nowrap;text-decoration:none;box-shadow:inset 0 1px #ffffff08;transition:color .15s,border-color .18s,background .18s,box-shadow .18s;isolation:isolate}
.local-original-view #community-dock a[hidden]{display:none!important}
.local-original-view #community-dock a[data-dock-near="true"],.local-original-view #community-dock a:hover{color:#fff;border-color:#6d8a76;background:#234839;box-shadow:0 5px 12px #061f1a38,inset 0 1px #ffffff12}
.local-original-view #community-dock a[aria-current="location"]{color:#14392d;border-color:#c6d8b9;background:#e2e9d1;box-shadow:0 4px 10px #071d1738,inset 0 1px #fff9}
.local-original-view #community-dock a[aria-current="location"] .community-dock-content{font-weight:700}
.local-original-view #community-dock a:focus-visible{outline:2px solid #f1d59a;outline-offset:-3px;border-color:#f1d59a;color:#fff;background:#244d3e}
.local-original-view #community-dock .community-dock-content{display:flex;gap:7px;align-items:center;justify-content:center;width:100%;transform-origin:50% 50%;pointer-events:none;will-change:transform}
.local-original-view #community-dock .community-dock-content svg{width:17px;height:17px;flex:none}
.local-original-view #community-dock .network-entry{flex-basis:122px;gap:0;color:#f3f5e8;border-color:#82977c;background:transparent;padding:1px;box-shadow:none}
.local-original-view #community-dock .network-entry[aria-current="location"]{color:#fff;border-color:#e0bd79}
.local-original-view .community-dock-hint{display:flex;justify-content:flex-end;margin:0;padding:4px 6px 0;color:#54695b;font-size:10px;line-height:1.4;letter-spacing:.02em;min-height:18px}
.local-original-view #community-dock-frame[data-overflow="false"] .community-dock-hint{visibility:hidden}
.local-original-view .community-beam{position:relative;isolation:isolate;overflow:hidden;border:1px solid #71866e;background:transparent;box-shadow:0 3px 8px #12362b18,inset 0 1px #ffffff14}
.local-original-view .community-beam::before{content:"";position:absolute;z-index:-2;inset:-150%;background:conic-gradient(from 90deg at 50% 50%,transparent 0%,transparent 75%,#f0d69c 100%);opacity:0;pointer-events:none}
.local-original-view .community-beam::after{content:"";position:absolute;z-index:-1;inset:1px;border-radius:inherit;background:linear-gradient(180deg,#315443,#102c24);box-shadow:inset 0 1px #ffffff38;pointer-events:none}
.local-original-view .community-beam:is(:hover,:focus-visible):not(:disabled)::before{opacity:1;animation:community-border-spin 3s linear infinite}
.local-original-view #network-lab #export-network-svg.community-beam{padding:11px 18px;border-radius:9px;color:#f5f7ec;font-size:13px;font-weight:600;min-height:46px;transition:box-shadow .2s,color .2s}
.local-original-view #network-lab #export-network-svg.community-beam:is(:hover,:focus-visible):not(:disabled){box-shadow:0 4px 14px #194b3b30;color:#fff;outline-color:#b88737}
.local-original-view #network-lab #export-network-svg.community-beam:disabled{color:#718176;background:#edf1eb;border-color:#b9c5bc;box-shadow:none;cursor:not-allowed}
.local-original-view #network-lab #export-network-svg.community-beam:disabled::before,.local-original-view #network-lab #export-network-svg.community-beam:disabled::after{display:none}
.local-original-view :is(input,select):focus-visible{outline:2px solid #177e63;outline-offset:2px;box-shadow:0 0 0 4px #137d7112}
.local-original-view .research-table-wrap{border-color:#c1d0c3;box-shadow:inset 0 1px #fff}
.local-original-view .research-table th{background:linear-gradient(180deg,#e9f0e4,#dfe8d9);border-bottom-color:#a6bea9;color:#244631}
@keyframes community-border-spin{to{transform:rotate(360deg)}}
@media(max-width:1100px){.local-original-view .community-dock-brand{display:none}.local-original-view #community-dock a{flex-basis:100px}.local-original-view #community-dock .network-entry{flex-basis:116px}}
@media(max-width:600px){.local-original-view #community-dock-frame{margin:-4px 0 18px;padding-top:6px}.local-original-view .community-dock-shell{padding:3px 4px;border-radius:10px}.local-original-view #community-dock{padding:3px 1px;gap:3px}.local-original-view #community-dock a{height:44px;min-height:44px;flex-basis:91px;font-size:12px}.local-original-view #community-dock .network-entry{flex-basis:111px}.local-original-view .community-dock-hint{font-size:10px;min-height:17px}.local-original-view #community-dock .community-dock-content{transform:none!important;will-change:auto}}
@media(prefers-reduced-motion:reduce),(hover:none),(pointer:coarse){.local-original-view #community-dock .community-dock-content{transform:none!important;will-change:auto}.local-original-view #community-dock a,.local-original-view .community-beam{transition:none}.local-original-view .community-beam::before{animation:none!important;opacity:0!important}}
"""


# The spring, smoothstep proximity, neighboring keyboard-focus field and motion
# gates below are adapted from the pinned createTopDockController. Unlike the
# catalogue controller, frames stop at rest and never change link dimensions.
COMMUNITY_JS = r"""
(() => {
  'use strict';
  const root=document.getElementById('community-dock'),frame=document.getElementById('community-dock-frame');
  const safety=document.querySelector('.safety');
  if(!root||!frame)return;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),precision=matchMedia('(hover:hover) and (pointer:fine)');
  const items=Array.from(root.querySelectorAll('a[data-dock-item]')).map(element=>({element,content:element.querySelector('.community-dock-content'),target:0,value:0,velocity:0}));
  const targets=items.map(item=>({item,target:document.getElementById(item.element.getAttribute('href').slice(1))}));
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  let enabled=false,springFrame=0,viewFrame=0,anchorOffset=142,released=false;
  const visibleItems=()=>items.filter(item=>!item.element.hidden);
  function paint(){
    let maximum=0;
    for(const item of items){const value=clamp(item.value,0,1.08);maximum=Math.max(maximum,value);item.content.style.transform=enabled?`translateY(${(value*1.8).toFixed(2)}px) scale(${(1+value*.035).toFixed(4)})`:''}
    root.dataset.dockMax=maximum.toFixed(2);
  }
  function draw(){
    springFrame=0;if(!enabled||released)return;
    let moving=false;
    for(const item of items){
      item.velocity+=(item.target-item.value)*.19;item.velocity*=.7;item.value+=item.velocity;
      if(Math.abs(item.target-item.value)<.001&&Math.abs(item.velocity)<.001){item.value=item.target;item.velocity=0}else moving=true;
    }
    paint();
    if(moving)springFrame=requestAnimationFrame(draw);else if(items.every(item=>item.target===0))root.dataset.dockState='idle';
  }
  function requestSpring(){if(enabled&&!springFrame&&!released)springFrame=requestAnimationFrame(draw)}
  function reset(){for(const item of items){item.target=0;item.element.dataset.dockNear='false'}requestSpring()}
  function measure(){
    if(released)return;
    if(springFrame)cancelAnimationFrame(springFrame);springFrame=0;
    enabled=!reduced.matches&&precision.matches&&innerWidth>600&&root.clientWidth>0;
    for(const item of items){item.target=0;item.value=0;item.velocity=0;item.element.dataset.dockNear='false'}
    root.dataset.dockState=enabled?'idle':'static';paint();
    const safetyHeight=safety?.getBoundingClientRect().height||0,dockHeight=frame.getBoundingClientRect().height;
    anchorOffset=Math.ceil(safetyHeight+dockHeight+18);
    document.body.style.setProperty('--community-safety-height',`${Math.ceil(safetyHeight)}px`);
    document.body.style.setProperty('--community-anchor-offset',`${anchorOffset}px`);
    frame.dataset.overflow=String(root.scrollWidth>root.clientWidth+2);updateActive();
  }
  function syncVisibility(){
    for(const {item,target} of targets)item.element.hidden=!target||Boolean(target.closest('[hidden]'));
    measure();
  }
  function updateActive(){
    viewFrame=0;
    const available=targets.filter(({item,target})=>!item.element.hidden&&target).map(entry=>({...entry,rect:entry.target.getBoundingClientRect()}));
    if(!available.length)return;
    const y=anchorOffset+1,inside=available.filter(entry=>entry.rect.top<=y&&entry.rect.bottom>y);
    // A child such as network-lab takes precedence over its strict-research parent.
    let active=inside.sort((a,b)=>b.rect.top-a.rect.top||Number(a.target.contains(b.target))-Number(b.target.contains(a.target)))[0];
    if(!active)active=available.filter(entry=>entry.rect.top<=y).sort((a,b)=>b.rect.top-a.rect.top)[0]||available[0];
    for(const {item} of targets){if(item===active.item)item.element.setAttribute('aria-current','location');else item.element.removeAttribute('aria-current')}
  }
  function requestView(){if(!viewFrame&&!released)viewFrame=requestAnimationFrame(updateActive)}
  function pointerMove(event){
    if(!enabled)return;
    for(const item of items){
      const rect=item.element.getBoundingClientRect(),proximity=item.element.hidden?0:clamp(1-Math.abs(event.clientX-(rect.left+rect.width*.5))/122,0,1);
      item.target=proximity*proximity*(3-2*proximity);item.element.dataset.dockNear=String(item.target>.08);
    }
    root.dataset.dockState='active';requestSpring();
  }
  function focusIn(event){
    const link=event.target.closest?.('a[data-dock-item]');if(!link)return;
    // A sticky link must reveal only its horizontal track, never the document.
    const bounds=root.getBoundingClientRect(),rect=link.getBoundingClientRect();
    const delta=rect.left<bounds.left+6?rect.left-bounds.left-6:rect.right>bounds.right-6?rect.right-bounds.right+6:0;
    if(delta)root.scrollLeft=clamp(root.scrollLeft+delta,0,Math.max(0,root.scrollWidth-root.clientWidth));
    if(!enabled)return;
    const visible=visibleItems(),index=visible.findIndex(item=>item.element===link);
    for(const item of items){const position=visible.indexOf(item);item.target=position<0?0:position===index?1:Math.abs(position-index)===1?.24:0;item.element.dataset.dockNear=String(item.target>.08)}
    root.dataset.dockState='focus';requestSpring();
  }
  function keyDown(event){
    const link=event.target.closest?.('a[data-dock-item]');if(!link)return;
    const visible=visibleItems(),index=visible.findIndex(item=>item.element===link);
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)||index<0)return;
    event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?visible.length-1:(index+(event.key==='ArrowLeft'?-1:1)+visible.length)%visible.length;
    visible[next].element.focus({preventScroll:true});
  }
  function syncHash(){
    let id;try{id=decodeURIComponent(location.hash.slice(1))}catch{return}
    const target=targets.find(entry=>entry.target?.id===id&&!entry.item.element.hidden)?.target;
    if(target)target.scrollIntoView({block:'start',behavior:'auto'});requestView();
  }
  function navigate(event){
    const link=event.target.closest?.('a[data-dock-item]');
    if(!link||!root.contains(link)||link.closest('[hidden]')||event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
    const href=link.getAttribute('href'),target=link.getAttribute('target');
    if(!href?.startsWith('#')||(target&&target!=='_self')||link.getAttribute('download')!==null)return;
    // Native fragment entries can have null state; the incumbent popstate
    // fallback then resets the source. Carry its entire current state forward.
    event.preventDefault();reset();const url=new URL(location.href);url.hash=href;
    if(url.hash!==location.hash)history.pushState(history.state,'',url);
    syncHash();
  }
  root.addEventListener('pointermove',pointerMove);root.addEventListener('pointerleave',reset);
  root.addEventListener('focusin',focusIn);root.addEventListener('focusout',event=>{if(!root.contains(event.relatedTarget))reset()});root.addEventListener('keydown',keyDown);
  root.addEventListener('click',navigate);
  addEventListener('scroll',requestView,{passive:true});addEventListener('hashchange',syncHash);addEventListener('resize',measure);
  reduced.addEventListener('change',measure);precision.addEventListener('change',measure);
  const observer=typeof ResizeObserver==='function'?new ResizeObserver(measure):null;
  if(safety)observer?.observe(safety);observer?.observe(frame);
  const visibility=typeof MutationObserver==='function'?new MutationObserver(syncVisibility):null;
  for(const {target} of targets)if(target)visibility?.observe(target,{attributes:true,attributeFilter:['hidden']});
  document.getElementById('analysis-source')?.addEventListener('change',syncVisibility);
  document.fonts?.ready.then(()=>{if(!released){measure();syncHash()}});
  syncVisibility();
  addEventListener('load',()=>{measure();syncHash()},{once:true});
  addEventListener('pagehide',event=>{if(springFrame)cancelAnimationFrame(springFrame);if(viewFrame)cancelAnimationFrame(viewFrame);springFrame=0;viewFrame=0;if(event.persisted)return;released=true;observer?.disconnect();visibility?.disconnect()});
  addEventListener('pageshow',event=>{if(event.persisted){measure();requestView()}});
})();
"""


# Local RectangleButtons.tsx, Aster (337-383, 557-576) and Meridian (283-327):
# retain the edge, top sheen and pressed surface without catalogue blur/assets.
# Segmented selection semantics below are local, not an upstream component API.
WORKBENCH_CSS = r"""
.local-original-view #network-lab .network-heading{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:8px 18px;margin-bottom:18px}
.local-original-view #network-lab .network-heading>div{min-width:0}
.local-original-view #network-lab .network-heading h4{margin:5px 0 0;letter-spacing:.02em}
.local-original-view #network-lab #network-context{grid-column:1/-1;padding-top:8px;border-top:1px solid #d6e0d4;font-size:12px;line-height:1.7;overflow-wrap:anywhere}
.local-original-view #network-lab .network-heading #export-network-svg{grid-column:auto;justify-self:end;align-self:center;min-height:44px;padding:10px 14px;white-space:normal;max-width:150px;font-size:12px;line-height:1.5}
.local-original-view #network-lab .network-toolbar{grid-template-columns:minmax(220px,1.25fr) minmax(230px,1fr) minmax(180px,.8fr);gap:16px;padding:18px;background:linear-gradient(180deg,#f6f9f1,#edf3e9);border:1px solid #becfbc;border-radius:12px;box-shadow:inset 0 1px #fff,0 3px 10px #1c463008}
.local-original-view #network-lab .network-toolbar label,.local-original-view #network-lab .community-choice-label{color:#49604e;font-size:11px;font-weight:600;line-height:1.5}
.local-original-view #network-lab .network-toolbar label[data-community-native][hidden]{display:none!important}
.local-original-view #network-lab #network-item{min-height:46px;border-color:#b4c6b2;background:#fcfdf9;box-shadow:inset 0 1px 2px #214c3010;border-radius:7px;color:#1c3d2b}
.local-original-view #network-lab .community-choice{display:grid;gap:6px;min-width:0}
.local-original-view #network-lab .community-segments{display:flex;gap:3px;padding:3px;min-width:0;border:1px solid #b8cbb5;border-radius:9px;background:#e4ecdf;box-shadow:inset 0 1px 3px #25482e0d}
.local-original-view #network-lab .community-segment{position:relative;isolation:isolate;display:flex;align-items:center;justify-content:center;flex:1;min-width:0;min-height:44px;padding:8px 10px;border:1px solid transparent;border-radius:6px;background:transparent;color:#4b6250;font:600 12px/1.5 "Microsoft YaHei","PingFang SC",sans-serif;text-align:center;overflow-wrap:anywhere;cursor:pointer;transition:background .16s,color .16s,box-shadow .16s}
.local-original-view #network-lab .community-segment::after{content:"";position:absolute;inset:0;z-index:-1;border-radius:inherit;background:linear-gradient(180deg,#ffffff5c,transparent 55%);pointer-events:none;opacity:0}
.local-original-view #network-lab .community-segment:hover:not(:disabled){color:#153e2a;background:#f3f7ed;border-color:#c1cfb9}
.local-original-view #network-lab .community-segment[aria-pressed="true"]{color:#183b28;background:#fbfcf7;border-color:#a3b89c;box-shadow:0 2px 4px #26472e14,inset 0 1px #fff}
.local-original-view #network-lab .community-segment[aria-pressed="true"]::after{opacity:1}
.local-original-view #network-lab .community-segment:active:not(:disabled){box-shadow:inset 0 2px 3px #244a301a;background:#e3ecdc}
.local-original-view #network-lab .community-segment:focus-visible{outline:2px solid #16745b;outline-offset:2px;z-index:1}
.local-original-view #network-lab .community-segment:disabled{cursor:not-allowed;color:#6c7d69;background:#e8ede4;border-color:transparent;box-shadow:none}
.local-original-view #network-lab [data-community-control="network-edge-limit"] .community-segments{flex-wrap:wrap}
.local-original-view #network-lab [data-community-control="network-edge-limit"] .community-segment{flex:1 0 calc(3ch + 10px);overflow-wrap:normal;word-break:normal}
.local-original-view #network-lab .network-workspace{grid-template-columns:minmax(0,1fr) 280px;border-color:#adbfaf;border-radius:12px;box-shadow:0 8px 26px #214d2e0c}
.local-original-view #network-lab .network-tool{min-height:44px;min-width:44px}
.local-original-view #network-lab #network-inspector{padding:22px 20px;background:linear-gradient(145deg,#fcfdf8,#f0f5e9);border-color:#c0cfbc}
.local-original-view #network-lab #network-inspector h5{font-size:30px;line-height:1.35;letter-spacing:.03em;margin:8px 0 16px;color:#1b3b28}
.local-original-view #network-lab .network-inspector-label{font-size:10px;line-height:1.6;color:#52735c;letter-spacing:.09em}
.local-original-view #network-lab .network-node-metrics{grid-template-columns:1fr 1fr;gap:10px 12px;margin:0;padding:14px 0;border-top:1px solid #cbd8c5;border-bottom:1px solid #cbd8c5}
.local-original-view #network-lab .network-node-metrics>div:first-child{grid-column:1/-1;display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:3px}
.local-original-view #network-lab .network-node-metrics dt{font-size:11px;line-height:1.5;color:#5a6c55;margin:0 0 3px}
.local-original-view #network-lab .network-node-metrics dd{font-size:20px;line-height:1.5;font-variant-numeric:tabular-nums;color:#254a2f;overflow-wrap:anywhere}
.local-original-view #network-lab .network-node-metrics>div:first-child dd{font-size:29px;letter-spacing:-.04em;text-align:right;color:#286944}
.local-original-view #network-lab .network-inspector-actions{gap:8px;margin:16px 0 22px}
.local-original-view #network-lab .network-inspector-actions button{min-height:44px;padding:10px 12px;border-radius:7px;border:1px solid #adbfaa;background:linear-gradient(180deg,#fefef9,#e7efdf);box-shadow:inset 0 1px #fff,0 2px 3px #2d4a2110;color:#355136;font-size:12px;line-height:1.5;white-space:normal;overflow-wrap:anywhere}
.local-original-view #network-lab #network-center-selected{color:#f2f8ea;background:linear-gradient(180deg,#356447,#244b34);border-color:#527b52;box-shadow:inset 0 1px #9cb48c60,0 2px 4px #19391b20}
.local-original-view #network-lab .network-inspector-actions button:focus-visible{outline:2px solid #16745b;outline-offset:3px}
.local-original-view #network-lab .network-inspector-actions button:active:not(:disabled){box-shadow:inset 0 2px 3px #17342033}
.local-original-view #network-lab .network-neighbors{margin:9px 0 0}
.local-original-view #network-lab .network-neighbors li{padding:9px 10px;border:1px solid #d3dfcb;border-radius:7px;margin:6px 0;background:#ffffff87;box-shadow:inset 0 1px #fff}
.local-original-view #network-lab .network-neighbors li:focus-within{border-color:#719e7a;background:#f4f9ec}
.local-original-view #network-lab .network-neighbors button{display:block;min-height:44px;width:100%;padding:5px 0;font-size:14px;font-weight:600;line-height:1.5;overflow-wrap:anywhere;text-decoration:none;color:#254b31}
.local-original-view #network-lab .network-neighbors button:hover{text-decoration:underline;text-underline-offset:4px}
.local-original-view #network-lab .network-neighbors button:focus-visible{outline:2px solid #16745b;outline-offset:2px;border-radius:3px}
.local-original-view #network-lab .network-neighbors small{margin:0;font-size:11px;line-height:1.7;font-variant-numeric:tabular-nums;color:#52664d}
.local-original-view #network-lab .network-data-details>summary{min-height:44px;padding:11px 0;line-height:1.6}
.local-original-view #network-lab .research-table{font-variant-numeric:tabular-nums}
.local-original-view #network-lab .research-table tbody tr:hover td{background:#f0f6e8}
.local-original-view #network-lab .research-table tr:focus-visible{outline:2px solid #16745b;outline-offset:-2px}
.local-original-view #network-lab .research-table tr:focus-visible td{background:#e9f3df}
.local-original-view #network-lab .research-table :is(th,td):nth-child(n+3){text-align:right}
@media(max-width:1200px){.local-original-view #network-lab .network-workspace{grid-template-columns:minmax(0,1fr)}.local-original-view #network-lab #network-inspector{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px 28px}.local-original-view #network-lab .network-inspector-actions{grid-template-columns:1fr 1fr;margin-bottom:0}}
@media(max-width:1000px){.local-original-view #network-lab .network-toolbar{grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:12px}.local-original-view #network-lab .network-toolbar>label:first-child{grid-column:1/-1}}
@media(max-width:600px){.local-original-view #network-lab .network-heading{gap:10px 12px;margin-bottom:14px}.local-original-view #network-lab .network-heading h4{font-size:24px}.local-original-view #network-lab .network-heading #export-network-svg{max-width:108px;padding:9px 11px}.local-original-view #network-lab #network-context{font-size:11px}.local-original-view #network-lab .network-toolbar{padding:12px;gap:11px 8px}.local-original-view #network-lab .community-segments{gap:2px;padding:2px}.local-original-view #network-lab .community-segment{padding:8px 4px;font-size:11px}.local-original-view #network-lab #network-inspector{padding:20px 16px}.local-original-view #network-lab .network-inspector-actions{display:grid;grid-template-columns:1fr 1fr;margin-bottom:22px}.local-original-view #network-lab .network-neighbors li{display:grid;grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr);gap:8px;align-items:center;padding:6px 10px}.local-original-view #network-lab .network-neighbors small{text-align:right}.local-original-view #network-lab .network-node-metrics{grid-template-columns:1fr 1fr}.local-original-view #network-lab .network-node-metrics>div:first-child dd{font-size:29px}}
@media(prefers-reduced-motion:reduce){.local-original-view #network-lab .community-segment{transition:none}}
"""


WORKBENCH_JS = r"""
(() => {
  'use strict';
  const inspector=document.getElementById('network-inspector'),controls=[];
  if(!inspector||typeof MutationObserver!=='function')return;
  const definitions=[
    {id:'network-view-mode',label:'\u63a2\u7d22\u8303\u56f4',labels:{all:'\u5168\u961f\u5217',neighborhood:'\u4e2d\u5fc3\u90bb\u57df'}},
    {id:'network-edge-limit',label:'\u753b\u5e03\u8fde\u7ebf\u4e0a\u9650'}
  ];
  for(const definition of definitions){
    const select=document.getElementById(definition.id),label=select?.closest?.('label');
    if(select?.tagName!=='SELECT'||!label||!select.options.length)continue;
    const shell=document.createElement('div'),caption=document.createElement('span'),group=document.createElement('div');
    shell.className='community-choice';shell.dataset.communityControl=definition.id;
    caption.className='community-choice-label';caption.id=`${definition.id}-caption`;caption.textContent=definition.label;
    group.className='community-segments';group.setAttribute('role','group');group.setAttribute('aria-labelledby',caption.id);
    const choices=Array.from(select.options).map(option=>{
      const button=document.createElement('button');button.type='button';button.className='community-segment';button.dataset.value=option.value;
      button.textContent=definition.labels?.[option.value]||option.textContent;button.setAttribute('aria-label',option.textContent);
      button.addEventListener('click',()=>{
        if(select.disabled||option.disabled)return;
        if(select.value!==option.value){select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}))}
        sync();
      });
      group.append(button);return {button,option};
    });
    function sync(){
      for(const {button,option} of choices){
        const pressed=String(select.value===option.value),disabled=select.disabled||option.disabled;
        if(button.getAttribute('aria-pressed')!==pressed)button.setAttribute('aria-pressed',pressed);
        if(button.disabled!==disabled)button.disabled=disabled;
      }
    }
    group.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      const available=choices.filter(({button})=>!button.disabled),index=available.findIndex(({button})=>button===event.target);
      if(index<0)return;
      event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?available.length-1:(index+(event.key==='ArrowLeft'?-1:1)+available.length)%available.length;
      available[next].button.focus({preventScroll:true});available[next].button.click();
    });
    shell.append(caption,group);sync();label.insertAdjacentElement('afterend',shell);
    // The select and its listeners remain authoritative. Hide only after every
    // replacement control is mounted and synchronized; unsupported DOM keeps it.
    label.dataset.communityNative='true';label.hidden=true;
    select.addEventListener('change',sync);controls.push({select,sync});
  }
  if(!controls.length)return;
  const syncAll=()=>controls.forEach(control=>control.sync());
  const observer=new MutationObserver(syncAll);
  observer.observe(inspector,{childList:true});
  for(const {select} of controls)observer.observe(select,{attributes:true,attributeFilter:['disabled']});
  addEventListener('pageshow',syncAll);
  addEventListener('pagehide',event=>{if(!event.persisted)observer.disconnect()});
})();
"""


def enhance_community_ui(page: str) -> str:
    """Adapt pinned Community controls without replacing any existing handler."""
    if 'id="community-ui-script"' in page:
        return page
    if 'id="network-interactive-script"' not in page:
        raise DashboardError("Community UI requires the interactive network adapter")
    marker = '<script id="supplement-data"' if '<script id="supplement-data"' in page else '<script id="dashboard-data"'
    if page.count(marker) != 1:
        raise DashboardError("Community UI payload anchor is missing or ambiguous")
    markup, scripts = page.split(marker, 1)
    navs = list(re.finditer(r'<nav class="research-nav"[^>]*>.*?</nav>', markup, re.S))
    mains = list(re.finditer(r'<main class="main"[^>]*>', markup))
    exports = list(re.finditer(r'<button class="([^"]*)"([^>]*\bid="export-network-svg"[^>]*)>', markup))
    if len(navs) != 1 or len(mains) != 1 or len(exports) != 1 or markup.count('</style>') != 1 or scripts.count('</body>') != 1:
        raise DashboardError("Community UI presentation anchors are missing or ambiguous")
    nav = navs[0][0]
    required = ['#network-lab', '#item-research', '#strict-research', '#research-quality']
    if any(nav.count('href="' + anchor + '"') != 1 for anchor in required) or nav.count('id="strict-nav-link"') != 1:
        raise DashboardError("Community UI navigation contract is incomplete")
    entries = re.findall(r'<a\b[^>]*>.*?</a>', nav, re.S)
    entries.insert(0, '<a href="#disease-overview">\u75be\u75c5\u6982\u89c8</a>')
    entries.insert(3, '<a href="#annual-section">\u5e74\u5ea6\u8d8b\u52bf</a>')
    entries.insert(4, '<a href="#comparison-section">\u5171\u75c5\u6bd4\u8f83</a>')
    followup_entry = next((entry for entry in entries if 'href="#followup-lab"' in entry), None)
    if followup_entry is not None:
        entries.remove(followup_entry)
        network_index = next((index for index, entry in enumerate(entries) if 'href="#network-lab"' in entry), 0)
        entries.insert(network_index + 1, followup_entry)
    # Reuse Community glyphs from AnimatedTopDock, mapped to the local anchors.
    icons = {
        '#followup-lab': '<path d="M3 3h8l-2-2M13 13H5l2 2M13 4v4M3 12V8"/><circle cx="3" cy="5" r="1.5"/><circle cx="13" cy="11" r="1.5"/>',
        '#disease-overview': '<rect x="2.25" y="2.25" width="4.5" height="4.5" rx=".8"/><rect x="9.25" y="2.25" width="4.5" height="4.5" rx=".8"/><rect x="2.25" y="9.25" width="4.5" height="4.5" rx=".8"/><rect x="9.25" y="9.25" width="4.5" height="4.5" rx=".8"/>',
        '#item-research': '<path d="M3.4 2.4h5.4l3.8 3.8v7.4H3.4z"/><path d="M8.8 2.4v3.8h3.8M5.9 9h4.2M5.9 11.2h3"/>',
        '#annual-section': '<circle cx="8" cy="8" r="5.9"/><path d="M8 4.6V8l2.4 1.5"/>',
        '#comparison-section': '<path d="M8 1.9 14.4 5.6 8 9.3 1.6 5.6z"/><path d="m2.6 8 5.4 3.1L13.4 8M2.6 10.7 8 13.8l5.4-3.1"/>',
        '#strict-research': '<circle cx="3" cy="8" r="1.5"/><circle cx="12.5" cy="3.5" r="1.5"/><circle cx="12.5" cy="12.5" r="1.5"/><path d="M4.5 7.3 11 4.2M4.5 8.7l6.5 3.1"/>',
        '#research-quality': '<path d="M4 2.25h5.4L12 4.85v8.9H4z"/><path d="M9.25 2.25V5h2.7M6 8h4M6 10.5h4"/>',
    }
    enhanced = []
    for entry in entries:
        entry = re.sub(r'<a\b', '<a data-dock-item="true"', entry, count=1)
        if 'class="network-entry"' in entry:
            entry = entry.replace('class="network-entry"', 'class="network-entry community-beam"', 1)
        href = re.search(r'href="([^"]+)"', entry)[1]
        if href in icons:
            icon = '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">' + icons[href] + '</svg>'
            entry = re.sub(r'(<a\b[^>]*>)', lambda match: match[0] + icon, entry, count=1)
        entry = re.sub(r'(<a\b[^>]*>)(.*?)(</a>)', r'\1<span class="community-dock-content">\2</span>\3', entry, count=1, flags=re.S)
        enhanced.append(entry)
    dock = '<div id="community-dock-frame" data-threeui-adaptation="AnimatedTopDock" data-overflow="false"><div class="community-dock-shell"><div class="community-dock-brand" aria-hidden="true">MingYiRx<small>\u5206\u6790\u5de5\u4f5c\u533a</small></div><nav class="research-nav" id="community-dock" aria-label="\u7814\u7a76\u5de5\u4f5c\u533a\u5bfc\u822a" data-dock-state="idle" data-dock-max="0.00">' + ''.join(enhanced) + '</nav></div><p class="community-dock-hint">\u5de6\u53f3\u6ed1\u52a8\u5207\u6362\u5de5\u4f5c\u533a\u5165\u53e3 \u2194</p></div>'
    markup = markup.replace(navs[0][0], '', 1)
    markup = re.sub(r'(<main class="main"[^>]*>)', lambda match: match[0] + dock, markup, count=1)
    markup = re.sub(r'<button class="([^"]*)"([^>]*\bid="export-network-svg"[^>]*)>', r'<button class="\1 community-beam"\2 data-threeui-adaptation="SpinningBorderButton">', markup, count=1)
    export = re.search(r'<button\b[^>]*\bid="export-network-svg"[^>]*>.*?</button>', markup, re.S)
    heading = re.search(r'<div class="network-heading"><div>(.*?)<p id="network-context">(.*?)</p></div></div>', markup, re.S)
    if not export or not heading:
        raise DashboardError("Community workbench anchors are missing or ambiguous")
    export_markup = re.sub(r'>.*?</button>', '>\u5bfc\u51fa SVG</button>', export[0], flags=re.S)
    export_markup = export_markup.replace('id="export-network-svg"', 'id="export-network-svg" aria-label="\u5bfc\u51fa\u5f53\u524d\u7f51\u7edc SVG"', 1)
    markup = markup.replace(export[0], '', 1)
    markup = markup.replace(heading[0], '<div class="network-heading"><div>' + heading[1] + '</div>' + export_markup + '<p id="network-context">' + heading[2] + '</p></div>', 1)
    markup = markup.replace('</style>', COMMUNITY_CSS + WORKBENCH_CSS + '</style>', 1)
    notice = '<!-- ThreeUI Community adaptations: AnimatedTopDock, SpinningBorderButton, RectangleButtons Aster and Meridian surfaces.\nSegmented control semantics are authored locally.\nUpstream: ' + UPSTREAM_URL + '\n' + UPSTREAM_LICENSE + '-->\n'
    script = '<script id="community-ui-script">' + COMMUNITY_JS + WORKBENCH_JS + '</script>'
    return notice + (markup + marker + scripts).replace('</body>', script + '</body>', 1)
