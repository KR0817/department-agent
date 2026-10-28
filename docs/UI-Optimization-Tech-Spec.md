# Workbench UI optimization

Date: 2026-10-29

## Scope and visual source

Implement the approved Verda-inspired concept using the existing FastAPI host and vanilla frontend. The independently authored concept approved for implementation on 2026-10-29 is the sole visual reference. Its reference tokens derive from [VerdaAI-Investigator at c6d6bfbe4da75bb506fa1de7f742d9db5e92dc56](https://github.com/kangjiayao14/VerdaAI-Investigator/tree/c6d6bfbe4da75bb506fa1de7f742d9db5e92dc56). No upstream component code or branding is transplanted.

Background #FAFBF9, white surfaces, tint #EAF1EA, border #E3E8E3, ink #3A413C, secondary #6B746C, 16px cards, 12px buttons, 15px body / 1.7 line height, and a 220px desktop navigation rail. Retain #176B5A primary actions and existing clinical semantic colors for contrast. Retain local fonts.

## Contract and invariants

No API, data model, authentication, extraction, review or archival contract changes. Existing route IDs, source provenance, error handling and session boundaries remain authoritative. Candidate fields remain accepted by default; explicit archival confirmation and the unsaved-change gate remain. Partial archival resumes its frozen plan. Follow-up messages remain queued only.

All four main modules and patient/record subroutes remain reachable. Preserve the full MingYiRx iframe, its nine report/download links, standalone view and quick-analysis route. Navigation must retain the iframe instance and its state; logout must clear it. Imported collection saves do not regenerate all aggregate charts. Knowledge queries remain separate from patient records and expose original/translation provenance.

## Implementation

1. Shared shell: persistent desktop navigation, compact/mobile menu, responsive content area, reusable tokens, accessible focus and route context. Preserve overview charts, filters and all secondary tabs.
2. Clinical evidence: make the existing source comparison viewer easier to discover and read. Retain image/text pagination, field switching, missing-coordinate fallback, keyboard focus return and source attribution. Reuse current helpers rather than replacing review logic.
3. Knowledge: distinct answer, citations and provenance sections; readable source cards and existing source reader. Complete prescription workspace: larger usable canvas, expand/restore with state intact, all original entry points retained.
4. Verify integration, source semantics and responsive layouts before considering deployment. Keep the preview isolated and synthetic.

## Acceptance and validation

- Desktop 1440 and 1280, tablet 768, mobile 390: no unintended outer horizontal overflow or overlapping controls; dense tables scroll within their own containers. Primary actions remain reachable.
- Keyboard navigation, Escape and focus return; reduced motion; source drawer and menu responsive transitions.
- Overview, clinical workbench, patient/record routes, knowledge answer/source and complete/quick prescription routes function.
- Synthetic clinical upload, field source reading, review changes and archive confirmation remain functional. Verify relevant source/review regression suites.
- Full prescription assets and entries remain accessible; frame survives module switches and is removed on logout; save/restart persistence covered by existing smoke tests.
- Run existing portable suites and synthetic integration smoke. Browser checks must report errors honestly; neither software tests nor synthetic examples establish clinical accuracy.
- No external patient data transfer, new package dependencies or edits to private services/backups. Maintain an exact baseline static-file archive for rollback and record before/after checksums locally.

## Release boundary

Deliver a local branch and isolated loopback preview first. Existing private live services and backup launchers remain independent. A published modified service requires a matching source offer and the existing release checks. The user subsequently authorized the GitHub source update; version 0.1.1 includes the verified UI and its matching source tag.
