# Third-party notices and source boundaries

Department Agent is distributed under **AGPL-3.0-only**; see [LICENSE](LICENSE).
Repository-authored integration, release tooling and the original knowledge-module
source are offered under that license in this release. The notices below preserve
the separate licenses and attribution of incorporated components. A top-level
license does not replace those notices or grant rights to separately supplied data.

## ClinData Relay OCR

- Upstream project: [KR0817/clin-data-relay](https://github.com/KR0817/clin-data-relay).
- Incorporated source: upstream `app/ocr.py`, retained as
  `clinical/vendor/relay_ocr.py`.
- License: **AGPL-3.0-only**, explicitly identified in the upstream project README.
- License text: [ClinData Relay AGPL v3](licenses/ClinData-Relay-AGPL-3.0.txt).
- The imported OCR source was byte-identical to the locally verified upstream
  source at intake: SHA-256
  `3e4dcd697eaafcf218904ecf0b1cc6e3f6df879626d9682260850d16e57c0597`.

The clinical `fhir_http.py` helper originated in the author's synthetic FHIR
workflow verifier. Its recorded source was the author's `verify-workflow.py`;
it is not attributed here as a verified upstream ClinData Relay file.

For a modified version served to remote users, retain an accessible offer of its
corresponding source as required by AGPL section 13. The [GNU license
text](https://www.gnu.org/licenses/agpl-3.0.html) describes the applicable terms.
The repository's application source, build scripts and documented installation
steps form its source distribution; a source link must correspond to the actual
version being served.

## MingYiRx

- Source component: the author's MingYiRx prescription-analysis software.
- Copyright: **2026 Xinbo Yu**.
- Original component license: **MIT**.
- License text: [MingYiRx MIT](licenses/MingYiRx-MIT.txt).

The original MIT copyright and permission notice remain applicable to the
incorporated MingYiRx source. The integrated distribution is offered under the
top-level AGPL terms with this notice preserved. The original MingYiRx license
covered software; it did not license clinical records, third-party articles or
private study outputs.

## ThreeUI Community adaptations

- Upstream: [MengTo/threeui](https://github.com/MengTo/threeui).
- Recorded source revision: `68802d5428071ada5c20db8094b1649e6bb770ed`.
- Recorded package version: `1.2.0`.
- Copyright: **2026 Meng To**.
- License: **MIT**; see [ThreeUI MIT](licenses/ThreeUI-MIT.txt).
- Upstream asset policy: [ThreeUI asset licenses](licenses/ThreeUI-ASSET-LICENSES.md).

The prescription interface uses native HTML/CSS adaptations of Community controls,
including AnimatedTopDock, SpinningBorderButton and selected RectangleButtons
surfaces. The adapter retains the upstream MIT notice in generated HTML. Selected
upstream source references may be retained for provenance; they are not the
executed React/Three.js runtime of this application.

The upstream asset-policy document describes the upstream repository, not a claim
that all of its assets are bundled here. No rights to ThreeUI-hosted catalog
thumbnails, preview videos, Pro/Beta components or unrelated remote assets are
granted by this project's license. Such media are outside this distribution.

## Geist font

- Font copyright: **2023 Vercel, in collaboration with basement.studio**.
- License: **SIL Open Font License 1.1**.
- License text: [Geist OFL](licenses/Geist-OFL-1.1.txt); the notice is also retained
  beside the clinical font files.

The font retains its own OFL terms and is not relicensed as AGPL. Bundling the font
with the application does not change the font's license. See the [official OFL
text](https://openfontlicense.org/open-font-license-official-text/) for its terms.

## Knowledge sources and optional dependencies

The knowledge-module software license covers its original source code and the
repository's explicitly synthetic examples. It does not cover external papers,
guideline PDFs, XML full text, translations, source images or derived indexes.
The author's existing literature collection is not included. Anyone supplying a
local corpus must have the relevant rights and retain source-specific provenance
and terms; public web access alone does not establish redistribution permission.

Dependencies installed separately through Python package management, optional OCR
executables, model-serving software and model weights retain their respective
upstream licenses. They are not relicensed by this repository. Third-party runtime
binaries and model weights are not bundled in this source distribution.

Clinical exports, private reports, account records, credentials and deployment
state are outside this public repository and outside its software-license grant.
