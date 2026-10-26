"""Opt-in layout refinement for the existing local aggregate workbench."""
from __future__ import annotations

import re

from .dashboard import DashboardError


LAYOUT_CSS = r"""
.local-original-view{--canvas:#edf4f2;--paper:#fff;--ink:#16342f;--muted:#526b63;--rule:#d2e1da;--pine:#0f7468;--pine-soft:#e1f1ea;--navy:#123c36;--gold:#b88737;background:radial-gradient(ellipse at 95% 0%,#dcece6,transparent 48%),var(--canvas);font-size:14px;line-height:1.6}
.local-original-view .shell{grid-template-columns:236px minmax(0,1fr)}
.local-original-view .main{min-width:0;width:min(1440px,100%);padding:28px 32px 56px}
.local-original-view .rail{padding:28px 18px;background:linear-gradient(155deg,#123c36,#0c302c);color:#eff8f4;border-right:0;backdrop-filter:none}
.local-original-view .brand{padding-bottom:22px;border-bottom:1px solid #365b51}
.local-original-view .brand h1{font-size:28px;letter-spacing:.04em}.local-original-view .brand p{font-size:12px;color:#bad4c9;line-height:1.9}
.local-original-view .brand .eyebrow{color:#8cd5bd;letter-spacing:.14em}
.local-original-view .rail :is(.group-filter-label,.group-btn small,.rail-note){color:#c0d6cc}
.local-original-view .rail .rail-note{border-color:#365b51}
.local-original-view .rail select{background:#1a483f;color:#f1faf5;border-color:#567b6e}
.local-original-view .rail .group-btn{color:#e2f2e9}
.local-original-view .rail .group-btn:hover{background:#1e5247}
.local-original-view .rail .group-btn[aria-pressed="true"]{background:#dff3e8;border-color:#8dcbb3;color:#163c30;box-shadow:0 5px 18px #061d1a33}
.local-original-view .rail .group-btn[aria-pressed="true"] small{color:#325c4c}
.local-original-view .rail .group-btn::before{background:#608f7c}
.local-original-view .rail .group-btn[aria-pressed="true"]::before{background:#137d71}
.local-original-view :is(.group-filter-label,.group-btn small,.group-kind,.rail-note){font-size:12px}
.local-original-view .group-kind{padding:1px 5px;font-weight:500}
.local-original-view .group-btn{min-height:48px;padding:10px 8px;border-radius:6px}
.local-original-view #original-context{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;margin:0 0 16px;padding:0 0 12px;background:transparent;border:0;border-bottom:1px solid var(--rule);font-size:12px}
.local-original-view #original-context>details{margin:0}.local-original-view #original-context summary{color:var(--pine);cursor:pointer}
.local-original-view #original-context p{max-width:80ch;margin:8px 0}
.local-original-view #original-context a{color:var(--pine);text-underline-offset:3px}
.local-original-view .source-panel{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,.7fr);gap:8px 24px;align-items:center;padding:20px 24px;margin-bottom:24px;background:var(--paper);border:1px solid #dce7e2;border-radius:14px;box-shadow:0 6px 24px #123c3606}
.local-original-view .source-panel h2{margin:0;font-size:20px;line-height:1.4}
.local-original-view .source-panel .control-field{grid-column:2;grid-row:1/3}
.local-original-view .source-panel details{grid-column:1;grid-row:2;font-size:12px}
.local-original-view .source-panel details[open]{grid-column:1/-1;grid-row:3}
.local-original-view .source-panel summary{color:var(--muted);cursor:pointer}
.local-original-view .source-panel p{margin:8px 0;font-size:13px}
.local-original-view .control-field{display:grid;gap:6px;min-width:0;font-size:13px;font-weight:600;color:var(--ink)}
.local-original-view .control-field select{width:100%}
.local-original-view #disease-overview{padding:0 0 24px;margin-bottom:24px}
.local-original-view #disease-overview .section-head{margin:0 0 12px}
.local-original-view #disease-overview .section-head h3{font-size:22px;margin:0}
.local-original-view .overview-groups{grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:8px}
.local-original-view .overview-group{padding:16px 14px;gap:7px;border:1px solid #dce7e2;border-radius:12px;box-shadow:0 4px 14px #123c3604;transition:transform .16s ease,box-shadow .16s ease}
.local-original-view .overview-group:hover{transform:translateY(-2px);box-shadow:0 8px 22px #123c3612}
.local-original-view .overview-group[aria-pressed="true"]{background:linear-gradient(135deg,#1b6654,#154f45);border-color:#1c6656;color:#fff}
.local-original-view .overview-group[aria-pressed="true"] :is(span,b){color:#e0f4e7}
.local-original-view .overview-group strong{font-size:13px;line-height:1.55}
.local-original-view .overview-group span{font-size:12px}.local-original-view .overview-group b{font-size:22px;font-variant-numeric:tabular-nums}
.local-original-view .overview-method{margin-top:10px;color:var(--muted);font-size:12px}
.local-original-view .overview-method summary{cursor:pointer;width:fit-content}
.local-original-view .overview-method p{font-size:13px;max-width:85ch}
.local-original-view .mast{gap:20px;padding-bottom:16px;align-items:center}
.local-original-view .mast h2{font-size:40px;line-height:1.25}
.local-original-view .mast-copy{font-size:13px;max-width:46ch}
.local-original-view .research-nav{margin:16px 0 12px;gap:8px}
.local-original-view .research-nav a{border-radius:8px;font-size:13px;min-height:44px;display:flex;align-items:center;padding:10px 16px;border-color:#c5d9ce}
.local-original-view .research-nav .network-entry{color:#fff;background:var(--navy);border-color:var(--navy);gap:10px;box-shadow:0 6px 18px #123c3618}
.local-original-view .network-entry svg{width:18px;height:18px;flex:none}
.local-original-view .view-controls{gap:8px;padding-bottom:12px}
.local-original-view .view-controls p{flex-basis:100%;margin:0;font-size:12px}
.local-original-view .stratum-btn{font-size:13px;padding:8px 12px;min-height:40px}
.local-original-view .strata-label{font-size:12px}
.local-original-view .stats{margin-top:12px;gap:1px;border:1px solid var(--rule);border-radius:12px;overflow:hidden;background:var(--rule)}
.local-original-view .stat{padding:20px;background:var(--paper);border:0}.local-original-view .stat span{font-size:12px}
.local-original-view .stat strong{font-size:28px;letter-spacing:-.03em;color:var(--navy)}.local-original-view .stat:first-child{padding-left:20px}
.local-original-view :is(.demo-block h4,.demo-row,.age-median small){font-size:12px}
.local-original-view .section{padding:28px 0}
.local-original-view :is(.annual-controls,.comparison-control){display:grid;grid-template-columns:minmax(200px,1fr) auto auto;align-items:end;width:100%;gap:12px;padding:16px;background:#f1f5f2;border:1px solid var(--rule);border-radius:7px}
.local-original-view :is(#annual-section,#comparison-section)>.section-head{display:block}
.local-original-view :is(.annual-controls,.comparison-control){margin-top:16px}
.local-original-view .annual-controls{grid-template-columns:repeat(3,auto) minmax(180px,1fr) auto}
.local-original-view .annual-controls .control-field{grid-column:4;grid-row:1}
.local-original-view .annual-controls select{max-width:none;min-width:0}
.local-original-view .comparison-control select{min-width:0}
.local-original-view .section-head:has(#search){display:block}
.local-original-view .section-head:has(#search) .controls{margin-top:16px;padding:16px;background:#f1f5f2;border:1px solid var(--rule);border-radius:7px;align-items:end}
.local-original-view .section-head:has(#search) label:has(#search){display:grid;gap:6px;flex:1;min-width:220px}
.local-original-view .section-head:has(#search) .eyebrow{font:600 13px/1.6 "Microsoft YaHei",sans-serif;letter-spacing:0;color:var(--ink)}
.local-original-view .search{font-size:14px;width:100%}
.local-original-view :is(.comparison-sub,.change-sub,.drug small,.combo-meta,.combo-summary,.combo-children p,.track-title small,.track-label em,.mini-drug small,.annual-caption,.footer){font-size:12px;line-height:1.65}
.local-original-view :is(.direction,.combo-size){font-size:11px}
.local-original-view :is(.track,.annual-frame,.reference-shell){box-shadow:none}
.local-original-view .track{padding:16px;background:var(--paper)}
.local-original-view .track.core{transform:none;box-shadow:none;background:var(--paper)}
.local-original-view .mini-drug small{white-space:normal;overflow:visible}
.local-original-view .comparison-main{grid-template-columns:auto minmax(0,1fr) auto}
.local-original-view .comparison-main button{min-width:0}
.local-original-view #network-edges .research-table :is(td,th):not(:first-child){text-align:right}
.local-original-view .main{animation:none}
.local-original-view :is(button,input,select,summary,a):focus-visible{outline:3px solid var(--blue);outline-offset:3px}
.local-original-view :is(input,select){color:var(--ink);background:#fff;min-height:44px;max-width:100%;border:1px solid #a5b5ac;border-radius:5px}
.local-original-view :is(.filter-btn,.annual-btn){min-height:44px;font-size:13px;border-radius:8px;background:#fff;transition:background .15s ease,border-color .15s ease}
.local-original-view :is(.filter-btn,.annual-btn):hover:not(:disabled){background:var(--pine-soft);border-color:#8db6a5}
.local-original-view .safety{background:#0b2925;color:#e6f1eb;font-size:12px}
.local-original-view .section-head h3{color:var(--navy)}
.local-original-view :is(.ledger,.combo,.change-panel,.comparison-panel){border-radius:10px;overflow:hidden;border-color:#d2e1da}
.local-original-view :is(.ledger-title,.research-table th){background:#e7f1ec}
.local-original-view .demographics{border-radius:10px;overflow:hidden;background:#d2e1da}
.local-original-view .demo-block{background:#f8fbf9}
.local-original-view :is(.track,.annual-frame){border-radius:12px;overflow:hidden}
.local-original-view .research-table-wrap{box-shadow:0 4px 18px #123c3604}
.local-original-view .research-panel .identity-card{border-radius:10px;padding:16px}
.local-original-view .longitudinal-details{margin:24px 0 0;padding:18px 20px;border:1px solid var(--rule);border-radius:12px;background:var(--paper)}
.local-original-view .longitudinal-details>summary{color:var(--navy);font-weight:600;font-size:15px}
.local-original-view button:disabled{cursor:not-allowed;color:var(--muted);background:#edf1ee}
.local-original-view .section-head{gap:16px;align-items:start}
.local-original-view .section-head h3{font-size:26px;line-height:1.3;margin-bottom:8px}
.local-original-view .section-head p{font-size:13px;line-height:1.7}
.local-original-view #item-research .section-head{display:block;margin-bottom:12px}
.local-original-view #item-research .controls{display:grid;grid-template-columns:minmax(220px,1fr) auto auto;align-items:end;gap:12px;padding:16px;margin-top:16px;background:#f1f5f2;border:1px solid var(--rule);border-radius:7px}
.local-original-view #item-research .controls label{font-size:13px;font-weight:600;gap:7px}
.local-original-view #item-research .controls select{width:100%;font-size:14px}
.local-original-view .sort-help{margin:10px 0 0!important;color:var(--muted)}
.local-original-view .sort-help summary{font-size:12px;cursor:pointer;width:fit-content}
.local-original-view .measure-help{margin-top:8px!important;font-size:13px;color:var(--muted)}
.local-original-view .measure-help summary{cursor:pointer;width:fit-content}
.local-original-view .measure-help p{max-width:85ch;margin:8px 0}
.local-original-view #research-order-note{max-width:76ch;margin:8px 0;font-size:13px}
.local-original-view .research-panel p{font-size:13px;line-height:1.7}
.local-original-view .focus-state{padding:8px 0;gap:10px}
.local-original-view .focus-state p{margin:0}
.local-original-view .focus-links{gap:10px;margin-top:14px}
.local-original-view .research-table-wrap{border-radius:6px;background:var(--paper);max-height:640px;scrollbar-color:#80998b #edf1ee;scrollbar-width:auto}
.local-original-view .research-table{font-size:13px;font-variant-numeric:tabular-nums;line-height:1.55}
.local-original-view .research-table :is(th,td){padding:14px 16px}
.local-original-view .research-table th{position:sticky;top:0;z-index:2;font-weight:600;background:#e6eee8;border-bottom:2px solid #9db4a6;white-space:normal}
.local-original-view .research-table td{background:var(--paper)}
.local-original-view .research-table tbody tr:nth-child(even) td{background:#f1f5f1}
.local-original-view .research-table tbody tr:hover td{background:#eaf1ec}
.local-original-view .research-table td small{font-size:12px;line-height:1.6;margin-top:6px}
.local-original-view #item-comparison .research-table :is(th,td):first-child{position:sticky;left:0;z-index:1;min-width:135px;width:19%;box-shadow:1px 0 #cbd3cf}
.local-original-view #item-comparison .research-table th:first-child{z-index:3}
.local-original-view #item-comparison .research-table td:not(:first-child){text-align:right;min-width:170px}
.local-original-view #item-comparison .research-table th:not(:first-child){text-align:right}
.local-original-view .research-meter{margin-left:auto;max-width:150px}
.local-original-view .table-scroll-hint{display:block;font-size:12px;margin:10px 0 6px}
.local-original-view .skip-workbench{position:absolute;left:16px;top:-100px;z-index:50;padding:10px 16px;background:var(--paper);color:var(--pine)}
.local-original-view .skip-workbench:focus{top:10px}
.local-original-view #formula-evidence{scroll-margin-top:90px}
@media(prefers-reduced-motion:reduce){.local-original-view .overview-group,.local-original-view .filter-btn,.local-original-view .annual-btn{transition:none}.local-original-view .overview-group:hover{transform:none}}
@media(max-width:520px){.local-original-view .focus-state p{flex:1 1 100%}}
@media(max-width:1200px){.local-original-view #item-research .controls{grid-template-columns:1fr 1fr}.local-original-view #item-research .controls label{grid-column:1/-1}.local-original-view .annual-controls{grid-template-columns:repeat(3,minmax(0,1fr))}.local-original-view .annual-controls .control-field{grid-column:1/3;grid-row:2}.local-original-view .comparison-control{grid-template-columns:minmax(0,1fr) minmax(120px,.5fr)}.local-original-view #export-comparison{grid-column:1/-1;justify-self:end}}
@media(max-width:900px){.local-original-view .shell{grid-template-columns:minmax(0,1fr)}.local-original-view .main{padding:20px 24px 40px}.local-original-view .rail{padding:16px 24px}.local-original-view .brand{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;align-items:center}.local-original-view .brand .eyebrow{grid-column:1/-1}.local-original-view .brand h1{margin:4px 0;font-size:24px}.local-original-view .group-filter-label{max-width:none;display:flex;align-items:center;gap:12px;margin-top:12px}.local-original-view .group-filter-label select{max-width:230px}.local-original-view .rail-note{font-size:12px}.local-original-view .mast{gap:12px;align-items:flex-start}.local-original-view .mast-copy{max-width:none}.local-original-view .demographics{grid-template-columns:repeat(3,minmax(0,1fr))}.local-original-view .demo-row{grid-template-columns:minmax(42px,auto) 1fr auto}.local-original-view .stats{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:520px){.local-original-view .main{padding:16px 16px 32px}.local-original-view .rail{padding:16px}.local-original-view .brand{display:block}.local-original-view .brand p{margin-top:8px}.local-original-view .source-panel{grid-template-columns:minmax(0,1fr);padding:14px;gap:12px}.local-original-view .source-panel .control-field{grid-column:1;grid-row:2}.local-original-view .source-panel details,.local-original-view .source-panel details[open]{grid-column:1;grid-row:3}.local-original-view .source-panel h2{font-size:19px}.local-original-view .overview-groups{grid-template-columns:repeat(2,minmax(0,1fr))}.local-original-view .mast h2{font-size:30px}.local-original-view .stats{grid-template-columns:repeat(2,minmax(0,1fr))}.local-original-view .stat{padding:14px 10px;border-bottom:1px solid var(--rule)}.local-original-view .stat:nth-child(odd){padding-left:0;border-right:1px solid var(--rule)}.local-original-view .demographics{grid-template-columns:minmax(0,1fr)}.local-original-view .annual-controls,.local-original-view .comparison-control{padding:12px;gap:10px}.local-original-view .comparison-control{grid-template-columns:minmax(0,1fr)}.local-original-view #export-comparison{justify-self:stretch}.local-original-view .annual-controls .control-field{grid-column:1/-1;grid-row:1}.local-original-view #export-annual-svg{grid-column:1/-1}.local-original-view #item-research .controls{padding:12px;gap:10px}.local-original-view #item-research .controls button{font-size:12px;padding:8px}.local-original-view #item-comparison .research-table :is(th,td):first-child{min-width:112px;width:112px;max-width:112px}.local-original-view .research-table :is(th,td){padding:12px}.local-original-view .focus-links{display:grid;grid-template-columns:minmax(0,1fr)}.local-original-view .section-head h3{font-size:25px}.local-original-view #item-research .focus-state{flex-wrap:wrap;padding:10px}.local-original-view #clear-drug-focus{margin-left:auto}.local-original-view .section-head:has(#search) label:has(#search){flex-basis:100%;min-width:0}.local-original-view .section-head:has(#search) .controls{gap:8px;padding:12px}.local-original-view .section-head:has(#search) .control-field{flex-basis:100%}}
"""


ANCHOR_JS = """<script>
(() => {
  function revealEvidence() {
    if (location.hash !== '#formula-evidence') return;
    const section = document.getElementById('formula-evidence');
    if (!section) return;
    section.open = true;
    section.scrollIntoView({block: 'start'});
  }
  addEventListener('hashchange', revealEvidence);
  revealEvidence();
})();
</script>"""


def refine_local_layout(page: str) -> str:
    """Preserve JSON and existing scripts while grouping presentation controls."""
    if '<body class="local-original-view">' in page:
        return page
    marker = '<script id="supplement-data"'
    if marker not in page:
        marker = '<script id="dashboard-data"'
    if marker not in page or '<body>' not in page:
        raise DashboardError("Unsupported local layout template")
    markup, scripts = page.split(marker, 1)
    for required in ('<body>', '<main class="main">', '</style>', '<details class="evidence">'):
        if markup.count(required) != 1:
            raise DashboardError("Required local layout anchor is missing or ambiguous")
    note = re.search(r'<p id="research-order-note">.*?</p>', markup, re.S)
    if note is None:
        raise DashboardError("Research toolbar description is missing")
    markup = markup.replace(note[0], '', 1)
    anchor = '  <div class="focus-state">'
    if anchor not in markup:
        raise DashboardError("Research toolbar anchor is missing")
    markup = markup.replace(anchor, '<details class="sort-help"><summary>\u836f\u5473\u6392\u5e8f\u8bf4\u660e</summary>' + note[0] + '</details>' + anchor, 1)
    # Keep explanations accessible without competing with the active selectors.
    markup = re.sub(r'(<p>\u9996\u8bca\u8986\u76d6.*?</p>)', lambda m: '<details class="measure-help"><summary>\u7edf\u8ba1\u53e3\u5f84\u4e0e\u7f3a\u5931\u503c\u8bf4\u660e</summary>' + m[1] + '</details>', markup, count=1, flags=re.S)
    markup = re.sub(r'(<aside[^>]*id="original-context"[^>]*><b>.*?</b>)(.*?)(</aside>)', lambda m: m[1] + '<details><summary>\u6570\u636e\u8bf4\u660e\u4e0e\u539f\u62a5\u544a</summary>' + m[2] + '</details>' + m[3], markup, count=1, flags=re.S)
    markup = re.sub(r'(<section class="source-panel"><h2[^>]*>.*?</h2>)(<label[^>]*>.*?</label>)(<select.*?</select>)(.*?)(</section>)', lambda m: m[1] + '<div class="control-field">' + m[2] + m[3] + '</div><details><summary>\u6765\u6e90\u8303\u56f4\u4e0e\u5207\u6362\u8bf4\u660e</summary>' + m[4] + '</details>' + m[5], markup, count=1, flags=re.S)
    overview = re.search(r'(<section[^>]*id="disease-overview"[^>]*>)(.*?)(</section>)', markup, re.S)
    if overview:
        content = overview[2]
        descriptions = re.findall(r'<p\b[^>]*>.*?</p>', content, re.S)
        for description in descriptions:
            content = content.replace(description, '', 1)
        content += '<details class="overview-method"><summary>\u75be\u75c5\u6807\u7b7e\u4e0e\u7edf\u8ba1\u53e3\u5f84</summary>' + ''.join(descriptions) + '</details>'
        markup = markup.replace(overview[0], overview[1] + content + overview[3], 1)
    for field in ('comparison-target', 'comparison-direction'):
        markup = re.sub(r'(<label for="' + field + r'"[^>]*>.*?</label>)(<select id="' + field + r'"[^>]*>.*?</select>)', r'<div class="control-field">\1\2</div>', markup, count=1, flags=re.S)
    for field, label in (('annual-item', '\u5e74\u5ea6\u8d8b\u52bf\u836f\u5473'), ('limit', '\u663e\u793a\u6570\u91cf')):
        markup = re.sub(r'(<select id="' + field + r'"[^>]*>.*?</select>)', '<label class="control-field">' + label + r'\1</label>', markup, count=1, flags=re.S)
    # The graph is the primary task; preserve the independent longitudinal tables
    # in a disclosure instead of placing them ahead of the graph's controls.
    strict = re.search(r'(<section class="section research-panel" id="strict-research">)(.*?)(</section>)', markup, re.S)
    if strict:
        head, rest = strict[2].split('<h4>', 1)
        split = rest.find('<h4>\u9996\u8bca\u836f\u5473\u5171\u73b0\u90bb\u57df</h4>')
        if split < 0:
            raise DashboardError("Network section anchor is missing")
        longitudinal = '<h4>' + rest[:split]
        network = rest[split:]
        content = head + network + '<details class="longitudinal-details"><summary>\u60a3\u8005\u5185\u8fde\u7eed\u6027\u4e0e\u5339\u914d\u53c2\u7167</summary>' + longitudinal + '</details>'
        markup = markup.replace(strict[0], strict[1] + content + strict[3], 1)
    markup = markup.replace('<body>', '<body class="local-original-view"><a class="skip-workbench" href="#main-workbench">\u8df3\u5230\u5206\u6790\u5de5\u4f5c\u533a</a>', 1)
    markup = markup.replace('<main class="main">', '<main class="main" id="main-workbench" tabindex="-1">', 1)
    markup = markup.replace('<details class="evidence">', '<details class="evidence" id="formula-evidence">', 1)
    markup = markup.replace('</style>', LAYOUT_CSS + '</style>', 1)
    return (markup + marker + scripts).replace('</body>', ANCHOR_JS + '</body>', 1)
