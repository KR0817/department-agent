"""Build an isolated synthetic before/after layout preview, without clinical inputs."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from mingyirx.dashboard import HTML_TEMPLATE
from mingyirx.dashboard_layout import refine_local_layout
from mingyirx.dashboard_sources import build_source_dashboard
from test_original_interactions import fixture


HERBS = [
    "\u9ec4\u82aa", "\u767d\u828d", "\u832f\u82d3", "\u5f53\u5f52", "\u751f\u5730\u9ec4", "\u719f\u5730\u9ec4",
    "\u7518\u8349", "\u515a\u53c2", "\u767d\u672f", "\u9ea6\u51ac", "\u7384\u53c2", "\u91d1\u94f6\u82b1",
    "\u8fde\u7fd8", "\u4e39\u53c2", "\u5ddd\u828e", "\u9e21\u8840\u85e4", "\u725b\u819d", "\u675c\u4ef2",
]


def preview_payload(supplement: bool = False, dense: bool = True) -> dict:
    """Return deterministic fabricated aggregates with explicit test provenance."""
    payload = fixture(supplement)
    labels = {
        "ra": "\u7c7b\u98ce\u6e7f\u5173\u8282\u708e",
        "sjd": "\u5e72\u71e5\u75c5",
        "as": "\u5f3a\u76f4\u6027\u810a\u67f1\u708e",
        "ra__sjd": "\u7c7b\u98ce\u6e7f\u5173\u8282\u708e + \u5e72\u71e5\u75c5",
        "ra__as": "\u7c7b\u98ce\u6e7f\u5173\u8282\u708e + \u5f3a\u76f4\u6027\u810a\u67f1\u708e",
    }
    for group in payload["groups"]:
        group["label"] = labels[group["code"]]
    payload["provenance"] = {
        "dataset_id": "synthetic-ui-layout-only",
        "synthetic_mode": True,
        "cohort_version": "fabricated-layout-network-v2",
        "analysis_version": "not-a-clinical-analysis",
        "min_public_n": 10,
        "recorded_run_gate": "SYNTHETIC_UI_TEST",
        "artifact_check": "NOT_APPLICABLE",
    }
    payload["presentation"]["renderer_version"] = "synthetic-layout-preview"
    for row in payload["comparisons"]:
        row["item_name"] = HERBS[0]
        row["combination_label"] = labels[row["combination_group"]]
        row["single_label"] = labels[row["single_group"]]
    items = []
    for row in payload["items"]:
        denominator = int(row["group_patients"])
        for index, herb in enumerate(HERBS):
            count = max(1, denominator - index % 5)
            dose_count = max(1, count * 3 // 5)
            items.append({**row, "item_name": herb, "exposed_patients": str(count),
                          "prevalence": str(count / denominator),
                          "most_common_dose_values_g": str(5 + 5 * (index % 4)),
                          "most_common_dose_fraction": str(dose_count / count), "dose_patients": str(count),
                          "most_common_dose_patients": str(dose_count),
                          "most_common_dose_tied": "False", "use_count": str(count * 2)})
    payload["items"] = items
    for row in payload["changes"]:
        row["item_name"] = HERBS[0]
        row.update(most_common_dose_values_g="15", most_common_dose_fraction=".6",
                   dose_patients="10", most_common_dose_patients="6", most_common_dose_tied="False")
    payload["yearSummaries"] = [{**row, "year": str(year)} for row in payload["summaries"] for year in (2020, 2021, 2022)]
    payload["yearItems"] = [{**row, "year": str(year)} for row in items for year in (2020, 2022)]
    payload["yearChanges"] = [{**row, "year": str(year)} for row in payload["changes"] for year in (2020, 2022)]
    for row in payload["combinations"]:
        row["combination"] = " | ".join(HERBS[:2])
        row["support"] = str(int(row["support_patients"]) / int(row["patients"]))
    strict = payload["research"]["cohorts"][0]
    strict.update(group="as_strict" if supplement else "ra_strict",
                  label=labels["as" if supplement else "ra"], patients="20" if supplement else "30")
    denominator = int(strict["patients"])
    exposures = [denominator - 4 - index % (5 if supplement else 9) for index in range(len(HERBS))]
    # Generated integer sets make all displayed synthetic pairwise metrics coherent.
    members = [{(offset + index * 3) % denominator for offset in range(count)}
               for index, count in enumerate(exposures)]
    payload["research"]["nodes"] = [
        {"group": strict["group"], "item_name": herb, "patients": strict["patients"],
         "exposed_patients": str(exposures[index]), "prevalence": str(exposures[index] / denominator),
         "node_prevalence_threshold": ".1", "edge_cosine_threshold": ".2"}
        for index, herb in enumerate(HERBS)
    ]
    # The final disclosed node deliberately has no edges; no clinical inference is intended.
    pairs = [(0, index) for index in range(1, 17)]
    pairs += [(index, index + 1) for index in range(1, 16)]
    pairs += [(1, 6), (3, 9), (5, 12), (8, 16)]
    if dense:
        pairs += [(left, right) for left in range(17) for right in range(left + 1, 17)
                  if (left, right) not in pairs][:95]
    edges = []
    for index, (left, right) in enumerate(pairs):
        count = len(members[left] & members[right])
        edges.append({"group": strict["group"], "patients": strict["patients"],
                      "item_1": HERBS[left], "item_2": HERBS[right], "cooccurrence_patients": str(count),
                      "support": str(count / denominator),
                      "cosine_similarity": str(count / math.sqrt(exposures[left] * exposures[right])),
                      "lift": "" if index == 0 else str(count * denominator / (exposures[left] * exposures[right]))})
    payload["research"]["edges"] = edges
    return payload


NOTICE = '<aside class="policy-note" id="original-context"><b>SYNTHETIC UI TEST</b><p>Fabricated layout fixtures only. Drug names are display labels; all counts, doses and associations are invented for interface testing.</p><details class="fixture-evidence"><summary>Fixture scope and sources</summary><p>No original outpatient data or patient records were loaded. Each source has 18 disclosed network nodes and {edge_count} fabricated edges. The final node is deliberately isolated and one edge has a missing lift. Empty panels and missing annual observations are intentional test states.</p></details></aside>'

PROBE = r"""<script>
(() => {
  const params = new URLSearchParams(location.search);
  if (params.get('font') === '150') {
    const style = document.createElement('style');
    style.textContent = 'body{font-size:21px!important} p,td,th,label,summary,button,input,select,small,.research-panel p,.source-panel p,.section-head p{font-size:20px!important;line-height:1.65!important} h2{font-size:39px!important} h3,.section-head h3{font-size:39px!important} #network-lab .network-detail-card{font-size:18px!important} #network-lab .network-detail-card h5{font-size:25.5px!important} #network-lab .network-detail-card .network-detail-context{font-size:16.5px!important} #network-lab .network-detail-card .network-detail-note{font-size:15px!important}';
    document.head.append(style);
  }
  function report() {
    parent.postMessage({type:'synthetic-layout-report', width:innerWidth,
      documentWidth:document.documentElement.scrollWidth, height:innerHeight,
      scrollY, source:new URLSearchParams(location.search).get('source') || 'primary', href:location.pathname + location.search + location.hash,
      synthetic:true, font:params.get('font') || '100'}, location.origin);
  }
  addEventListener('load', report);
  addEventListener('resize', report);
  addEventListener('scroll', report, {passive:true});
  addEventListener('hashchange', report);
  addEventListener('change', () => setTimeout(report, 0));
  addEventListener('message', event => {if (event.origin === location.origin && event.data === 'report-synthetic-layout') report();});
  new ResizeObserver(report).observe(document.documentElement);
})();
</script>"""

HARNESS = r"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Synthetic UI refactor preview</title><style>
*{box-sizing:border-box}body{margin:0;background:#e6ece9;color:#17231f;font:14px system-ui,sans-serif}.toolbar{padding:12px 16px;display:flex;align-items:end;gap:12px;flex-wrap:wrap;background:#fff;border-bottom:1px solid #a9bbb0;position:sticky;top:0;z-index:5}.toolbar strong{align-self:center;color:#8a3327}.toolbar label{display:grid;gap:4px;font-size:12px}.toolbar select,.toolbar button{padding:8px;min-height:40px}.toolbar button{background:#1f5a46;color:white;border:0;border-radius:4px}#preview-report{padding:8px 16px;display:block;background:#edf4f1;min-height:36px}#frame-stage{padding:14px;overflow:auto}iframe{display:block;border:1px solid #80998b;background:white;height:1000px;max-width:none;margin:auto}
</style><div class="toolbar"><strong>SYNTHETIC UI TEST</strong><label>Version<select id="preview-version"><option value="refined">Refined</option><option value="baseline">Baseline</option></select></label><label>Viewport width<select id="preview-width"><option>1440</option><option>768</option><option>390</option></select></label><label>Text stress scale<select id="preview-font"><option value="100">100%</option><option value="150">150% CSS override</option></select></label><label>Section<select id="preview-section"><option value="">Entry</option><option value="item-research">Single drug</option><option value="annual-section">Annual</option><option value="comparison-section">Comorbidity</option><option value="strict-research">Network</option><option value="formula-evidence">Evidence</option></select></label><label>Source<select id="preview-source"><option value="primary">Primary</option><option value="supplement">Supplement</option></select></label><button id="preview-load" type="button">Load preview</button><button id="preview-measure" type="button">Measure</button><button id="preview-back" type="button">Frame back</button></div><output id="preview-report" aria-live="polite">Waiting for synthetic frame.</output><div id="frame-stage"><iframe id="preview-frame" title="Synthetic MingYiRx layout preview"></iframe></div><script>
const frame=document.getElementById('preview-frame');
function loadPreview(){
 const version=document.getElementById('preview-version').value,width=Number(document.getElementById('preview-width').value),font=document.getElementById('preview-font').value,section=document.getElementById('preview-section').value,source=document.getElementById('preview-source').value;
 frame.style.width=width+'px';frame.style.height=(width===390?844:1000)+'px';
 frame.src=version+'.html?source='+source+'&font='+font+(section?'#'+section:'');
}
document.getElementById('preview-load').addEventListener('click',loadPreview);
document.getElementById('preview-measure').addEventListener('click',()=>frame.contentWindow.postMessage('report-synthetic-layout',location.origin));
document.getElementById('preview-back').addEventListener('click',()=>frame.contentWindow.history.back());
addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==frame.contentWindow||event.data?.type!=='synthetic-layout-report')return;const d=event.data;document.getElementById('preview-report').textContent=`Synthetic only | iframe ${d.width} x ${d.height} | document width ${d.documentWidth} | horizontal overflow ${Math.max(0,d.documentWidth-d.width)}px | text ${d.font}% | ${d.href}`;});
loadPreview();
</script></html>"""


def build(output: Path, network_density: str = "dense") -> dict:
    """Create a new directory containing only generated synthetic fixtures."""
    from mingyirx.dashboard_network import enhance_network
    from mingyirx.dashboard_threeui import enhance_community_ui
    from mingyirx.dashboard_followup import enhance_followup
    from mingyirx.dashboard_network_3d import enhance_network_3d
    from mingyirx.dashboard_network_compare import enhance_network_compare
    from mingyirx.dashboard_group_matrix import enhance_group_matrix

    if output.exists():
        raise FileExistsError("Preview output must be a new directory")
    output.mkdir(parents=True)
    dense = network_density == "dense"
    edge_count = 130 if dense else 35
    for name, payload in (("primary", preview_payload(dense=dense)), ("supplement", preview_payload(True, dense=dense))):
        page = HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=True)).replace("__TITLE__", "Synthetic UI fixture")
        (output / (name + ".html")).write_text(page, encoding="utf-8")
    build_source_dashboard(output / "primary.html", output / "supplement.html", output / "baseline.html", refresh_template=True,
                           default_source="primary", source_metadata={key: {"title": "Synthetic " + key, "scope": "Fabricated interface test fixture."} for key in ("primary", "supplement")})
    baseline = (output / "baseline.html").read_text(encoding="utf-8")
    baseline = baseline.replace('<main class="main">', '<main class="main">' + NOTICE.format(edge_count=edge_count), 1)
    baseline = enhance_network(refine_local_layout(baseline))
    refined = enhance_network_3d(enhance_community_ui(enhance_followup(baseline)))
    refined = enhance_group_matrix(enhance_network_compare(refined))
    for name, page in (("baseline", baseline), ("refined", refined)):
        (output / (name + ".html")).write_text(page.replace("</body>", PROBE + "</body>", 1), encoding="utf-8")
    (output / "index.html").write_text(HARNESS, encoding="utf-8")
    manifest = {"purpose": "isolated-synthetic-ui-validation", "synthetic_mode": True, "original_aggregates_loaded": False,
                "fixture": "tests/test_original_interactions.py", "viewports": [1440, 768, 390], "font_stress_percent": [100, 150],
                "network_fixture": {"density": network_density, "nodes_per_source": 18, "edges_per_source": edge_count, "isolated_nodes_per_source": 1,
                                    "missing_lift_per_source": 1, "strict_groups": ["ra_strict", "as_strict"]},
                "note": "All clinical-looking numbers and associations are fabricated for layout testing; not clinical evaluation."}
    (output / "preview-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--network-density", choices=("dense", "sparse"), default="dense")
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output, arguments.network_density), indent=2))
