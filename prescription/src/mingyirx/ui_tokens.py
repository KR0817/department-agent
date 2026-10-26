"""Shared visual tokens for the workspace shell and the pages it frames.

One palette, one type stack and one motion curve, so the shell header and the
iframed pages render the same background, surface and line colours.
No external fonts or URLs: every page keeps ``default-src 'none'``.
"""

TOKENS = r""":root{--ground:#eef1ec;--paper:#fbfbf8;--tint:#e9eee7;--tint-strong:#dde6db;--line:#d3dbd1;--line-strong:#a6b5a5;--ink:#1e352d;--muted:#55675d;--pine:#173d35;--pine-hover:#21503f;--pine-soft:#c9d8cd;--gold:#9c7429;--gold-ink:#806020;--hl:#f6eac4;--hl-soft:#faf3e0;--sim:#f8efda;--sim-line:#e3d0a2;--sim-ink:#6b521f;--add:#2c6a4d;--add-bg:#e1eee4;--add-line:#9cc1aa;--remove:#8a4a34;--remove-bg:#f5e7df;--remove-line:#d5b3a4;--red:#8b3e33;--ease:cubic-bezier(.32,.72,0,1);--shadow:0 1px 2px rgba(23,61,53,.06),0 10px 24px -18px rgba(23,61,53,.45);--sans:"Segoe UI Variable Text","Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei UI","Microsoft YaHei","Noto Sans CJK SC","Source Han Sans SC",system-ui,sans-serif;--mono:"Cascadia Mono",Consolas,"SFMono-Regular",ui-monospace,monospace}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%;text-size-adjust:100%}h1,h2,h3{text-wrap:balance}p{text-wrap:pretty}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition-duration:0s!important;animation-duration:0s!important;scroll-behavior:auto!important}}
"""
