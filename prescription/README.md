# MingYiRx prescription module

This source-only module retains the original prescription analytics, cohort and network calculations, source-separated dashboard, exact-prescription teaching renderer, reviewed case import, longitudinal comparisons, and append-only local collections. It is bundled with the integrated Department Agent under its upstream MIT license.

## Public demonstration

From the repository root, run:

```powershell
uv run python scripts/build_prescription_demo.py
```

The builder accepts only invented fixtures and writes all 14 application assets to `prescription/work/demo-site`. Intermediate generated files stay in the adjacent ignored `demo-site-build` directory. Existing output directories are refused. The parent launcher may reuse a previously verified demo site.

The aggregate dashboard, clinical shell, exact-prescription page and inheritance page use the original renderers. The report and report downloads contain clearly labeled fictional examples. They preserve navigation, disease switching, source details and downloads, but do not reproduce private historical reports, their appearance or medical claims. Fabricated display values are not calculated study estimates. No original clinical exports, generated private pages, real literature excerpts or case histories are distributed.

## Local workspace

The integrated launcher supplies the application site and a separate collection directory under this module's ignored `work/` directory. A real Git checkout is needed for the original `git check-ignore` privacy check. Do not remove that check or put collections in tracked source folders. Revisions preserve the original source hash, human review decisions and collection history; changing synthetic/real collection mode is refused.

TXT, CSV, JSON and DOCX parsing use the Python standard library. PDF text extraction requires `pypdf`; scanned PDFs must be exported as images. Image OCR uses Windows local OCR through `src/mingyirx/clinical_ocr.ps1` and is unavailable on other operating systems. The demo does not establish OCR performance or clinical accuracy.

## Configuration and tests

`configs/example.json` and `data/synthetic/` are public synthetic fixtures. `configs/local_gb18030.template.json` is a generic local-import column contract with no original input filenames or hashes. Supply authorized local inputs and their hashes in ignored configuration copies before using original-source processing. `configs/exact_rx_teaching_rules.json` contains explicitly fictional, unvalidated writing prompts.

Run the module tests from the repository root:

```powershell
$env:PYTHONPATH = "prescription/src"
uv run python -m unittest discover -s prescription/tests -p "test_*.py"
```

The JavaScript checks use Node.js when available. See `third_party/threeui/` for the preserved third-party license, source provenance and adaptation notices. Private source projects and their Git histories were not copied into this distribution.
