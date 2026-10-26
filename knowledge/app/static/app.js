"use strict";

let catalog;
let labels;
let activeClaim;
let activeSource;
let packet;
let searchController;
let searchSequence = 0;
let checkSequence = 0;
let answerSequence = 0;
let preparedAnswer;
let fulltext;
let fulltextLoading = true;
let fulltextSequence = 0;
let searchBusy = false;
let literature;
let literatureLoading = true;
let literatureFailed = false;
let literaturePage = 1;
let literatureSequence = 0;
const LITERATURE_PAGE_SIZE = 20;
const EXTRACT_WAIT_MS = 480000;
const byId = (id) => document.getElementById(id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function sourceDisplayTitle(source) {
  if (typeof source.title_zh === "string" && /[\u3400-\u9fff]/.test(source.title_zh)) return source.title_zh;
  const registered = labels.sourceTitles[source.source_id || source.id];
  if (registered) return registered;
  const year = Number.isInteger(source.year) ? labels.literatureYear.replace("{year}", source.year) : "";
  const identifier = source.pmid ? `PMID ${source.pmid}` : source.pmcid || "";
  return [labels.diseases[source.disease] || labels.literatureUnknownDisease, studyTypeLabel(source.study_type), year, identifier].filter(Boolean).join(" / ");
}

function studyTypeLabel(type) {
  return labels.studyTypes[type] || labels.literatureStudyUnknown;
}

function originalEvidence(source, passage) {
  const details = element("details", "original-evidence");
  details.append(element("summary", "", labels.originalEvidence), element("h4", "registered-wording-label", labels.originalTitle), element("p", "context", source.title), element("h4", "registered-wording-label", labels.originalQuote), element("blockquote", "", passage.text), element("p", "locator", passage.locator), element("p", "context", passage.context_note));
  return details;
}

async function api(path, body, signal) {
  const response = await fetch(path, body === undefined ? {signal} : {
    signal,
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  });
  if (!response.ok) {
    const error = new Error("request_failed");
    const failure = await response.json().catch(() => ({}));
    if (["stale_fulltext_index", "fulltext_unavailable"].includes(failure.error)) error.code = failure.error;
    throw error;
  }
  return response.json();
}

function showView(view) {
  if (!["ask", "library", "lab", "review", "answer"].includes(view)) return;
  document.querySelectorAll(".view").forEach((node) => { node.hidden = node.id !== `view-${view}`; });
  document.querySelectorAll(".nav-button").forEach((node) => {
    node.classList.toggle("active", node.dataset.view === view);
    if (node.dataset.view === view) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
  byId(`view-${view}`).querySelector("h1").setAttribute("tabindex", "-1");
  byId(`view-${view}`).querySelector("h1").focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

function showSource(source) {
  const content = byId("source-content");
  content.replaceChildren();
  const title = element("h2", "source-dialog-title", sourceDisplayTitle(source));
  title.id = "source-title";
  content.append(title, currencyBadge(source), sourceStatusBadge(source));
  const definitions = element("dl", "source-definition");
  const values = [[labels.sourceId, source.id], ["PMID", source.pmid || "-"], ["DOI", source.doi || "-"], [labels.publicationYear, String(source.year)], [labels.readScope, labels.access[source.access] || source.access], [labels.retrievedAt, source.verified_at]];
  if (source.online_date) values.push([labels.onlineDate, source.online_date]);
  values.forEach(([name, value]) => definitions.append(element("dt", "", name), element("dd", "", value)));
  content.append(definitions, element("h3", "field-title", labels.sourceScope), element("p", "context", source.verification_scope));
  source.passages.forEach((passage) => {
    content.append(originalEvidence(source, passage));
    const details = element("details");
    details.append(element("summary", "", labels.snapshotDetails), element("p", "hash", passage.sha256), element("p", "context", labels.hashNote));
    content.append(details);
  });
  const link = element("a", "source-link", labels.openOriginal);
  const url = new URL(source.url);
  if (url.protocol === "https:") link.href = url.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  content.append(link);
  byId("source-dialog").showModal();
}

function sourceButton(source, text, className = "source-title") {
  const button = element("button", className, text);
  button.type = "button";
  button.addEventListener("click", () => showSource(source));
  return button;
}

function currencyBadge(source) {
  return element("span", `badge ${source.currency === "superseded" ? "fail" : "pending"}`, labels.currency[source.currency]);
}

function sourceStatusBadge(source) {
  return element("span", `badge ${source.status === "active" ? "" : "fail"}`, labels.sourceStatus[source.status]);
}

function reviewBadge(claim) {
  return element("span", `badge ${claim.review === "rejected" ? "fail" : "pending"}`, labels.review[claim.review]);
}

function appendReceipt(panel, result) {
  const details = element("details", "receipt");
  details.append(element("summary", "", labels.traceId + result.request_id));
  const link = element("a", "text-button", labels.receiptDownload);
  link.href = result.receipt_url;
  link.download = "";
  details.append(element("p", "context", labels.receiptNote), element("p", "hash", result.corpus_sha256), link);
  panel.append(details);
}

function renderLibrary(status) {
  byId("app-version").textContent = "v" + status.version;
  byId("scope-summary").textContent = labels.scopeSummary.replace("{count}", status.source_count);
  renderLiterature();
}

function publicSourceUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}

function literatureLocatorUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value, location.origin);
    if (url.origin !== location.origin || !["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || !/^\/api\/fulltext\/(page|section)\/[a-zA-Z0-9_-]+$/.test(url.pathname)) return null;
    return url.href;
  } catch {
    return null;
  }
}

function canAskLiterature(source) {
  return source.retrieval_eligible === true && typeof source.fulltext_source_id === "string" && source.fulltext_source_id.length > 0;
}

function validateLiterature(result) {
  if (!result || result.answer_language !== "zh-CN" || !Array.isArray(result.sources) || result.sources.length > 1000 || !result.counts || typeof result.version !== "string") throw new Error("invalid_literature");
  const ids = new Set();
  for (const source of result.sources) {
    if (!source || typeof source.id !== "string" || !source.id || ids.has(source.id) || typeof source.title !== "string" || !source.title || !Object.hasOwn(labels.diseases, source.disease) || source.disease === "all" || !Object.hasOwn(labels.literatureAccess, source.access) || source.review_status !== "pending" || typeof source.tcm_related !== "boolean" || typeof source.retrieval_eligible !== "boolean" || (source.retrieval_eligible && !canAskLiterature(source)) || !publicSourceUrl(source.source_url)) throw new Error("invalid_literature_source");
    ids.add(source.id);
  }
  const actual = {total: result.sources.length, fulltext: result.sources.filter((source) => source.access !== "abstract_only").length, indexed: result.sources.filter(canAskLiterature).length, clinical_approved: 0};
  if (Object.entries(actual).some(([key, value]) => result.counts[key] !== value)) throw new Error("invalid_literature_counts");
  return result;
}

function normalizedSearch(value) {
  return String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
}

function filteredLiterature() {
  const terms = normalizedSearch(byId("library-query").value).trim().split(/\s+/).filter(Boolean);
  const disease = byId("library-disease").value;
  const tcm = byId("library-tcm").value;
  return (literature?.sources || []).filter((source) => {
    if (disease !== "all" && source.disease !== disease) return false;
    if ((tcm === "yes" && !source.tcm_related) || (tcm === "no" && source.tcm_related)) return false;
    const text = normalizedSearch([source.title, source.title_zh, source.pmid, source.pmcid, source.doi, source.journal, source.year, labels.diseases[source.disease], studyTypeLabel(source.study_type), source.tcm_related ? labels.literatureTcm : ""].join(" "));
    return terms.every((term) => text.includes(term));
  });
}

function literatureAskButton(source) {
  const button = element("button", "text-button", labels.literatureAsk);
  button.type = "button";
  button.disabled = !canAskLiterature(source);
  if (button.disabled) button.title = labels.literatureNotIndexed;
  button.addEventListener("click", () => useLiterature(source));
  return button;
}

function showLiterature(source) {
  const content = byId("source-content");
  content.replaceChildren();
  const title = element("h2", "source-dialog-title", sourceDisplayTitle(source));
  title.id = "source-title";
  content.append(title);
  if (source.title_zh) content.append(element("p", "context", labels.literatureTranslatedTitle));
  if (source.review_note) content.append(element("p", "notice error", source.review_note));
  content.append(element("h3", "field-title", labels.originalTitle), element("p", "context", source.title));
  const definitions = element("dl", "source-definition");
  const values = [[labels.literatureDisease, labels.diseases[source.disease]], [labels.literatureStudyType, studyTypeLabel(source.study_type)], [labels.publicationYear, source.year || "—"], [labels.literatureJournal, source.journal || "—"], ["PMID", source.pmid || "—"], ["PMCID", source.pmcid || "—"], ["DOI", source.doi || "—"], [labels.readScope, labels.literatureAccess[source.access]], [labels.reviewStatus, labels.review.pending], [labels.literatureIndexLabel, canAskLiterature(source) ? labels.literatureIndexed : labels.literatureNotIndexed]];
  values.forEach(([name, value]) => definitions.append(element("dt", "", name), element("dd", "", String(value))));
  content.append(definitions, element("p", "context", labels.literatureReviewLimit));
  const url = publicSourceUrl(source.source_url);
  if (url) {
    const link = element("a", "source-link", labels.openOriginal);
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    content.append(link);
  }
  const locator = literatureLocatorUrl(source.locator_url);
  if (locator) {
    const link = element("a", "source-link", labels.literatureLocalText);
    link.href = locator;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    content.append(link);
  }
  content.append(literatureAskButton(source));
  byId("source-dialog").showModal();
}

function renderLiterature() {
  const list = byId("library-list");
  list.replaceChildren();
  const counts = literature?.counts;
  for (const [id, value] of [["source-count", counts?.total], ["fulltext-count", counts?.fulltext], ["indexed-count", counts?.indexed], ["pending-source-count", counts?.total], ["reviewed-count", counts?.clinical_approved]]) byId(id).textContent = value ?? "—";
  byId("library-reload").disabled = literatureLoading;
  byId("library-pagination").hidden = !literature;
  if (!literature) {
    const message = literatureLoading ? labels.literatureLoading : labels.literatureUnavailable;
    byId("library-status").textContent = message;
    list.append(element("div", literatureFailed ? "notice error" : "empty-state", message));
    return;
  }
  const matches = filteredLiterature();
  const pages = Math.max(1, Math.ceil(matches.length / LITERATURE_PAGE_SIZE));
  literaturePage = Math.max(1, Math.min(literaturePage, pages));
  const start = (literaturePage - 1) * LITERATURE_PAGE_SIZE;
  byId("library-status").textContent = labels.literatureCount.replace("{count}", matches.length).replace("{total}", literature.sources.length);
  byId("library-page").textContent = labels.literaturePage.replace("{page}", literaturePage).replace("{pages}", pages);
  byId("library-previous").disabled = literaturePage === 1;
  byId("library-next").disabled = literaturePage === pages;
  if (!matches.length) list.append(element("div", "empty-state", labels.literatureNoMatches));
  matches.slice(start, start + LITERATURE_PAGE_SIZE).forEach((source) => {
    const card = element("article", "library-card literature-card");
    const top = element("div", "card-top");
    top.append(element("span", "", labels.diseases[source.disease]), element("span", "badge", studyTypeLabel(source.study_type)));
    if (source.tcm_related) top.append(element("span", "badge", labels.literatureTcm));
    card.append(top, element("h2", "", sourceDisplayTitle(source)));
    if (source.title_zh) card.append(element("p", "context", labels.literatureTranslatedTitle));
    card.append(element("p", "source-meta", `${source.year || "—"} / PMID ${source.pmid || "—"} / PMCID ${source.pmcid || "—"}`));
    const original = element("details", "literature-original-title");
    original.append(element("summary", "", labels.literatureOriginalTitle), element("p", "context", source.title));
    card.append(original);
    const states = element("div", "review-states");
    states.append(element("span", "badge", labels.literatureAccess[source.access]), element("span", "badge", canAskLiterature(source) ? labels.literatureIndexed : labels.literatureNotIndexed), element("span", "badge pending", labels.review.pending));
    const details = element("button", "text-button", labels.literatureDetails);
    details.type = "button";
    details.addEventListener("click", () => showLiterature(source));
    const bottom = element("div", "card-bottom");
    bottom.append(details, literatureAskButton(source));
    card.append(states, bottom);
    list.append(card);
  });
}

async function refreshLiterature() {
  const sequence = ++literatureSequence;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  literatureLoading = true;
  literatureFailed = false;
  literature = null;
  renderLiterature();
  try {
    const result = await api("/api/literature", undefined, controller.signal);
    if (sequence !== literatureSequence) return;
    literature = validateLiterature(result);
    literaturePage = 1;
  } catch {
    if (sequence !== literatureSequence) return;
    literatureFailed = true;
  } finally {
    window.clearTimeout(timeout);
    if (sequence === literatureSequence) {
      literatureLoading = false;
      renderLiterature();
    }
  }
}

async function useLiterature(source) {
  if (!canAskLiterature(source)) return;
  if (byId("source-dialog").open) byId("source-dialog").close();
  showView("ask");
  byId("disease").value = source.disease;
  byId("mode").value = "extract";
  updateFulltextSources();
  invalidateSearch();
  const sequence = searchSequence;
  if (!fulltext?.sources.some((item) => item.id === source.fulltext_source_id)) await refreshFulltext();
  if (sequence !== searchSequence || byId("disease").value !== source.disease || byId("mode").value !== "extract") return;
  if (!fulltext?.sources.some((item) => item.id === source.fulltext_source_id && item.disease === source.disease)) {
    byId("results").replaceChildren(element("div", "notice error", labels.literatureSelectionUnavailable));
    return;
  }
  byId("fulltext-source").value = source.fulltext_source_id;
  invalidateSearch();
  byId("results").replaceChildren(element("div", "notice", labels.literatureReady.replace("{title}", sourceDisplayTitle(source))));
  byId("question").focus();
}

function renderReview() {
  const list = byId("review-list");
  list.replaceChildren();
  const disease = byId("review-disease").value;
  const items = packet.items.filter((item) => disease === "all" || item.claim.disease === disease);
  byId("review-count").textContent = `${items.length} ${labels.reviewCountSuffix}`;
  if (!items.length) list.append(element("div", "empty-state", labels.emptyReview));
  items.forEach((item) => {
    const source = packet.sources.find((s) => s.id === item.source_id);
    const card = element("article", "library-card review-card");
    const top = element("div", "card-top");
    top.append(element("span", "", `${labels.diseases[item.claim.disease]} / ${item.claim.id}`), reviewBadge(item.claim));
    card.append(top, element("h2", "", item.claim.text), sourceButton(source, sourceDisplayTitle(source)), originalEvidence(source, item.passage));
    const states = element("div", "review-states");
    states.append(sourceStatusBadge(source), currencyBadge(source));
    card.append(states);
    const details = element("details");
    details.append(element("summary", "", labels.reviewDimensions));
    const dimensions = element("ul", "review-dimensions");
    Object.keys(item.worksheet.dimensions).forEach((key) => {
      const row = element("li");
      row.append(element("span", "", labels.dimensions[key]), element("span", "badge pending", labels.unassessed));
      row.append(element("p", "context dimension-guide", labels.dimensionGuidance[key]));
      dimensions.append(row);
    });
    details.append(element("p", "context", labels.reviewStateGuide), dimensions, element("p", "hash", labels.bindingVersion + item.binding_sha256));
    card.append(details);
    list.append(card);
  });
}

function renderResults(result) {
  const results = byId("results");
  results.replaceChildren();
  const notice = element("div", "notice");
  notice.append(element("strong", "", labels.statuses[result.status]), element("div", "", labels.statusDetails[result.status]));
  results.append(notice);
  byId("result-count").textContent = `${result.references.length} ${labels.countSuffix}`;
  result.references.forEach((match) => {
    const card = element("article", "result-card");
    const top = element("div", "card-top");
    top.append(element("span", "", `${labels.diseases[match.claim.disease]} / ${labels.registeredParaphrase}`), reviewBadge(match.claim));
    const binding = element("div", "binding-line");
    const source = element("div");
    source.append(sourceButton(match.source, sourceDisplayTitle(match.source)), element("div", "source-meta", `PMID ${match.source.pmid || "—"} / DOI ${match.source.doi || "—"}`));
    binding.append(element("span", "binding-icon", "\u21b3"), source);
    const bottom = element("div", "card-bottom");
    bottom.append(element("span", "badge", labels.registeredLink), currencyBadge(match.source), sourceButton(match.source, labels.openSource, "text-button"));
    card.append(top, element("p", "claim-text", match.claim.text), binding, bottom);
    results.append(card);
  });
  appendReceipt(results, result);
}

function filteredFulltextSources() {
  const disease = byId("disease").value;
  return (fulltext?.sources || []).filter((source) => disease === "all" || source.disease === disease);
}

function updateFulltextSources() {
  const select = byId("fulltext-source");
  const previous = select.value;
  const all = element("option", "", labels.extractAllSources);
  all.value = "all";
  const sources = filteredFulltextSources();
  select.replaceChildren(all);
  sources.forEach((source) => {
    const option = element("option", "", sourceDisplayTitle(source));
    option.value = source.id;
    select.append(option);
  });
  if (sources.some((source) => source.id === previous)) select.value = previous;
  select.disabled = fulltextLoading || !fulltext?.enabled || !sources.length;
}

function updateSearchMode() {
  const extract = byId("mode").value === "extract";
  byId("fulltext-options").hidden = !extract;
  byId("extract-help").hidden = !extract;
  byId("results-heading").textContent = extract ? labels.extractHeading : labels.referenceHeading;
  byId("ask-button").disabled = searchBusy || (extract && (fulltextLoading || !fulltext?.enabled || !filteredFulltextSources().length));
  byId("ask-button").textContent = searchBusy ? (extract ? labels.extracting : labels.searching) : (extract ? labels.extractButton : labels.searchButton);
  byId("fulltext-reload").disabled = fulltextLoading || searchBusy;
  let scope = labels.extractUnavailable;
  if (fulltextLoading) scope = labels.extractLoading;
  else if (fulltext?.enabled) {
    scope = labels.extractScope.replace("{sources}", fulltext.sources.length).replace("{chunks}", fulltext.chunk_count);
    if (!filteredFulltextSources().length) scope += " " + labels.extractNoSources;
  }
  byId("fulltext-status").textContent = scope;
  byId("scope-summary").textContent = extract ? [scope, labels.extractQualityLimit].join(" ") : labels.scopeSummary.replace("{count}", catalog.sources.length);
  byId("runtime-status").textContent = fulltext?.enabled ? labels.extractRuntime.replace("{model}", typeof fulltext.model === "string" ? fulltext.model : labels.extractModelUnknown) : labels.runtime;
}

async function refreshFulltext() {
  const sequence = ++fulltextSequence;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  fulltextLoading = true;
  updateFulltextSources();
  updateSearchMode();
  try {
    const result = await api("/api/fulltext", undefined, controller.signal);
    if (sequence !== fulltextSequence) return;
    if (!Array.isArray(result.sources) || typeof result.enabled !== "boolean" || result.answer_language !== "zh-CN" || (result.enabled && !/^[a-f0-9]{64}$/.test(result.index_sha256))) throw new Error("invalid_fulltext_catalog");
    fulltext = result;
  } catch {
    if (sequence !== fulltextSequence) return;
    fulltext = null;
  } finally {
    window.clearTimeout(timeout);
    if (sequence === fulltextSequence) {
      fulltextLoading = false;
      updateFulltextSources();
      updateSearchMode();
    }
  }
}

function originalPageUrl(item) {
  if (typeof item.chunk_id !== "string" || !/^[a-zA-Z0-9_-]+$/.test(item.chunk_id) || typeof item.page_url !== "string") return null;
  const kind = item.evidence_kind || "pdf_page";
  if (!["pdf_page", "xml_section", "html_section"].includes(kind)) return null;
  const carrier = kind === "pdf_page" ? "page" : "section";
  try {
    const url = new URL(item.page_url, location.origin);
    if (url.origin !== location.origin || !["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== `/api/fulltext/${carrier}/${item.chunk_id}`) return null;
    return url.href;
  } catch {
    return null;
  }
}

function renderExtracts(result, expectedIndex) {
  if (result.index_sha256 !== expectedIndex) throw Object.assign(new Error("stale_response"), {code: "stale_fulltext_index"});
  if (result.answer_language !== "zh-CN" || !Object.hasOwn(labels.extractStatuses, result.status) || !Array.isArray(result.extracts)) throw new Error("invalid_extract_response");
  if (result.status === "extracts" && (!result.extracts.length || result.clinical_approval !== null || result.completeness !== "unassessed")) throw new Error("invalid_extract_response");
  if ((Object.hasOwn(result, "question_intent") && !["diagnostic_criteria", "classification_criteria", "tcm_syndrome", "mixed_criteria", "general"].includes(result.question_intent)) || (Object.hasOwn(result, "answer_scope") && !["classification_criteria", "tcm_syndrome", "source_excerpt", null].includes(result.answer_scope)) || (Object.hasOwn(result, "answerability_basis") && !["complete_source_bundle", "excerpt_only", "none"].includes(result.answerability_basis))) throw new Error("invalid_extract_response");
  const panel = byId("results");
  panel.replaceChildren();
  const notice = element("div", ["model_unavailable", "invalid_model_output", "source_unavailable"].includes(result.status) ? "notice error" : "notice");
  const reason = ["criteria_selection_incomplete", "criteria_bundle_budget_exceeded"].includes(result.reason) ? "complete_criteria_not_available" : result.reason;
  const detail = result.status === "insufficient" && Object.hasOwn(labels.extractReasonDetails, reason) ? labels.extractReasonDetails[reason] : labels.extractStatusDetails[result.status];
  notice.append(element("strong", "", labels.extractStatuses[result.status]), element("div", "", detail));
  panel.append(notice);
  const hasChineseAnswer = (item) => {
    const knownTranslation = ["source_chinese", "machine_translated"].includes(item.translation_status) || (item.translation_status === "versioned_translation" && item.translation_origin === "versioned_assistant_translation" && item.translation_review_status === "pending_clinician_review");
    return knownTranslation && typeof item.answer_zh === "string" && /[\u3400-\u9fff]/.test(item.answer_zh);
  };
  const chineseCount = result.extracts.filter(hasChineseAnswer).length;
  byId("result-count").textContent = result.status === "extracts" ? labels.extractCount.replace("{answers}", chineseCount).replace("{extracts}", result.extracts.length) : labels.extractStatuses[result.status];
  panel.append(element("p", "context", labels.extractRetrieval.replace("{count}", Number.isInteger(result.retrieved_count) ? result.retrieved_count : "—")), element("p", "source-meta", `${labels.extractModelLabel}: ${typeof result.model === "string" ? result.model : labels.extractModelUnknown}`));
  if (result.status !== "extracts") return;
  if (result.answer_scope === "classification_criteria") panel.append(element("div", "notice", labels.extractClassificationNotice));
  if (result.answerability_basis === "complete_source_bundle") panel.append(element("p", "context", labels.extractCriteriaCoverage));
  if (chineseCount !== result.extracts.length) panel.append(element("p", "notice error", chineseCount ? labels.extractTranslationPartial : labels.extractTranslationUnavailable));
  panel.append(element("p", "context", labels.extractApproval));
  result.extracts.forEach((item) => {
    const card = element("article", "result-card extract-card");
    const top = element("div", "card-top");
    const xml = item.evidence_kind === "xml_section";
    const html = item.evidence_kind === "html_section";
    const section = xml || html;
    const locator = html ? labels.extractHtmlSection : xml ? labels.extractSection : `${labels.extractPage} ${item.pdf_page ?? "—"}`;
    top.append(element("span", "", locator), element("span", "badge", html ? labels.extractHtmlAnchored : labels.extractAnchored));
    card.append(top);
    if (hasChineseAnswer(item)) {
      const translated = item.translation_status === "machine_translated";
      const versioned = item.translation_status === "versioned_translation";
      const answerLabel = versioned ? labels.extractVersionedTranslation : translated ? labels.extractMachineTranslation : labels.extractChineseOriginal;
      card.append(element("p", "extract-answer-label", answerLabel), element("p", "extract-answer", item.answer_zh));
      if (versioned) {
        top.append(element("span", "badge pending", labels.extractVersionedReview));
        card.append(element("p", "context extract-translation-note", labels.extractVersionedTranslationNote));
      } else if (translated) card.append(element("p", "context extract-translation-note", labels.extractTranslationNote));
    } else card.append(element("p", "notice error", labels.extractTranslationMissing));
    card.append(element("h3", "extract-source-title", sourceDisplayTitle(item)), element("p", "source-meta", `PMID ${item.pmid || "—"} / DOI ${item.doi || "—"}`), element("p", "context", html ? labels.extractHtmlQualityNote : xml ? labels.extractXmlQualityNote : labels.extractQualityNote));
    const details = element("details", "extract-context original-evidence");
    details.append(element("summary", "", labels.extractEvidence));
    if (section && typeof item.locator === "string") details.append(element("p", "locator", item.locator));
    details.append(element("h4", "registered-wording-label", labels.originalTitle), element("p", "context", item.title), element("h4", "registered-wording-label", html ? labels.extractHtmlOriginal : labels.originalQuote), element("blockquote", "extract-quote", item.quote), element("h4", "registered-wording-label", labels.extractContext), element("p", "context", item.context));
    card.append(details);
    const pageUrl = originalPageUrl(item);
    if (pageUrl) {
      const link = element("a", "source-link", section ? labels.extractOpenSection : labels.extractOpenPage);
      link.href = pageUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.append(link);
    } else card.append(element("p", "context", labels.extractPageUnavailable));
    const provenance = element("details");
    provenance.append(element("summary", "", labels.extractProvenance), element("p", "source-meta", `${item.source_id} / ${item.chunk_id}`), element("p", "hash", item.quote_sha256), element("p", "context", html ? labels.extractHtmlHashNote : labels.extractHashNote));
    card.append(provenance);
    panel.append(card);
  });
}

function resetSearchButton() {
  searchBusy = false;
  updateSearchMode();
  byId("results").setAttribute("aria-busy", "false");
}

function invalidateSearch() {
  searchSequence++;
  if (searchController) searchController.abort();
  resetSearchButton();
  byId("results").replaceChildren(element("div", "empty-state", labels.queryChanged));
  byId("result-count").textContent = labels.waitingQuestion;
}

async function ask(event) {
  if (event) event.preventDefault();
  const form = byId("question-form");
  if (!form.reportValidity()) return;
  const extract = byId("mode").value === "extract";
  if (extract && (fulltextLoading || !fulltext?.enabled || !filteredFulltextSources().length)) return;
  if (searchController) searchController.abort();
  searchController = new AbortController();
  const sequence = ++searchSequence;
  searchBusy = true;
  updateSearchMode();
  byId("results").setAttribute("aria-busy", "true");
  byId("results").replaceChildren(element("div", "notice", extract ? labels.extractWaiting : labels.searching));
  byId("result-count").textContent = extract ? labels.extracting : labels.searching;
  let timedOut = false;
  const controller = searchController;
  const timeout = extract ? window.setTimeout(() => { timedOut = true; controller.abort(); }, EXTRACT_WAIT_MS) : null;
  const expectedIndex = fulltext?.index_sha256;
  try {
    const body = extract ? {question: byId("question").value, disease: byId("disease").value, source_id: byId("fulltext-source").value, index_sha256: expectedIndex} : {question: byId("question").value, disease: byId("disease").value, mode: byId("mode").value};
    const result = await api(extract ? "/api/extract" : "/api/search", body, controller.signal);
    if (sequence !== searchSequence) return;
    if (extract) renderExtracts(result, expectedIndex);
    else renderResults(result);
  } catch (error) {
    if (sequence !== searchSequence) return;
    let message = timedOut ? labels.extractTimeout : labels.requestError;
    if (error.code === "stale_fulltext_index") message = labels.extractStale;
    if (error.code === "fulltext_unavailable") message = labels.extractUnavailable;
    byId("results").replaceChildren(element("div", "notice error", message));
    byId("result-count").textContent = "-";
    if (extract && ["stale_fulltext_index", "fulltext_unavailable"].includes(error.code)) refreshFulltext();
  } finally {
    if (timeout !== null) window.clearTimeout(timeout);
    if (sequence === searchSequence) resetSearchButton();
  }
}

function updateLabSource() {
  activeSource = catalog.sources.find((s) => s.id === byId("lab-source").value);
  byId("lab-passage").replaceChildren();
  if (!activeSource) return;
  activeSource.passages.forEach((passage) => {
    const option = element("option", "", passage.locator);
    option.value = passage.id;
    byId("lab-passage").append(option);
  });
  if (activeClaim && activeClaim.source_id === activeSource.id) byId("lab-passage").value = activeClaim.passage_id;
  updateLabPassage();
}

function invalidateCheck() {
  checkSequence++;
  byId("check-results").replaceChildren();
  byId("check-button").disabled = !activeClaim;
  byId("check-button").textContent = labels.checkButton;
}

function updateLabPassage() {
  const passage = activeSource.passages.find((p) => p.id === byId("lab-passage").value);
  byId("lab-quote").value = passage.text;
  invalidateCheck();
}

function resetLab() {
  activeClaim = catalog.claims.find((c) => c.id === byId("lab-claim").value);
  if (!activeClaim) {
    byId("check-results").replaceChildren(element("div", "empty-state", labels.emptyCatalog));
    byId("check-form").querySelectorAll("input, textarea, select, button").forEach((node) => { node.disabled = true; });
    return;
  }
  byId("lab-text").value = activeClaim.text;
  byId("lab-source").value = activeClaim.source_id;
  updateLabSource();
}

function renderChecks(result) {
  const panel = byId("check-results");
  panel.replaceChildren();
  panel.append(element("div", result.status === "blocked" ? "notice error" : "notice", labels.statuses[result.status]));
  const list = element("div", "check-list");
  result.checks.forEach((check) => {
    const row = element("div", "check-row");
    row.append(element("strong", "", labels.checkNames[check.name]), element("span", `badge ${check.state === "unknown" ? "pending" : check.state}`, labels.state[check.state]), element("p", "", labels.reasons[check.reason]));
    list.append(row);
  });
  panel.append(list, element("p", "check-footnote", labels.checkFootnote));
  appendReceipt(panel, result);
}

async function check(event) {
  event.preventDefault();
  if (!activeClaim || !activeSource) return;
  const sequence = ++checkSequence;
  const button = byId("check-button");
  button.disabled = true;
  button.textContent = labels.checking;
  try {
    const result = await api("/api/check", {claim_id: activeClaim.id, source_id: activeSource.id, passage_id: byId("lab-passage").value, claim_text: byId("lab-text").value, quote: byId("lab-quote").value, disease: activeClaim.disease});
    if (sequence !== checkSequence) return;
    renderChecks(result);
  } catch {
    if (sequence !== checkSequence) return;
    byId("check-results").replaceChildren(element("div", "notice error", labels.requestError));
  } finally {
    if (sequence === checkSequence) {
      button.disabled = false;
      button.textContent = labels.checkButton;
    }
  }
}

function invalidateAnswer(clearUnits = true) {
  answerSequence++;
  byId("answer-results").replaceChildren(element("p", "context", labels.answerChanged));
  byId("answer-results").setAttribute("aria-busy", "false");
  byId("segment-button").disabled = false;
  byId("segment-button").textContent = labels.answerPrepare;
  byId("audit-answer-button").disabled = false;
  byId("audit-answer-button").textContent = labels.answerAudit;
  if (clearUnits) {
    preparedAnswer = null;
    byId("answer-units").replaceChildren();
    byId("audit-answer-button").hidden = true;
  }
}

async function prepareAnswer(event, scenario) {
  if (event) event.preventDefault();
  if (!byId("answer-form").reportValidity()) return;
  invalidateAnswer();
  const sequence = ++answerSequence;
  const answer = byId("answer-text").value;
  const disease = byId("answer-disease").value;
  byId("segment-button").disabled = true;
  byId("segment-button").textContent = labels.answerPreparing;
  try {
    const result = await api("/api/segment-answer", {answer, disease});
    if (sequence !== answerSequence) return;
    if (result.corpus_sha256 !== catalog.corpus_sha256) throw new Error("stale_catalog");
    preparedAnswer = {answer, disease, corpus_sha256: result.corpus_sha256, units: result.units};
    byId("answer-results").replaceChildren();
    result.units.forEach((unit, index) => {
      const card = element("article", "library-card answer-unit");
      card.append(element("h2", "", `${labels.answerUnit} ${index + 1}`), element("p", "claim-text", unit.text));
      const help = element("p", "context", labels.answerSelectHelp);
      help.id = `answer-help-${unit.id}`;
      card.append(help);
      const choices = element("div", "citation-choices");
      choices.setAttribute("role", "group");
      choices.setAttribute("aria-label", `${labels.answerUnit} ${index + 1}`);
      choices.setAttribute("aria-describedby", help.id);
      catalog.claims.forEach((claim) => {
        const source = catalog.sources.find((s) => s.id === claim.source_id);
        const label = element("label", "citation-choice");
        const input = element("input");
        input.type = "checkbox";
        input.value = claim.id;
        input.dataset.unitId = unit.id;
        input.checked = unit.suggested_claim_ids.includes(claim.id);
        if (scenario === "swap" && index === 0) input.checked = claim.id === catalog.claims[1]?.id;
        if (scenario === "mixed" && index === 0) input.checked = catalog.claims.slice(0, 2).some((item) => item.id === claim.id);
        input.addEventListener("change", () => invalidateAnswer(false));
        const wording = element("span", "citation-choice-copy");
        wording.append(element("strong", "", claim.text), element("span", "citation-choice-source", `${source ? sourceDisplayTitle(source) : labels.answerUnknownSource} / ${claim.id}`));
        label.append(input, wording);
        choices.append(label);
      });
      if (!catalog.claims.length) choices.append(element("p", "context", labels.emptyCatalog));
      card.append(choices);
      byId("answer-units").append(card);
    });
    byId("audit-answer-button").hidden = false;
  } catch {
    if (sequence === answerSequence) byId("answer-results").replaceChildren(element("div", "notice error", labels.answerRequestError));
  } finally {
    if (sequence === answerSequence) {
      byId("segment-button").disabled = false;
      byId("segment-button").textContent = labels.answerPrepare;
    }
  }
}

function answerCheckItem(check) {
  const item = element("div");
  item.append(element("span", `badge ${check.state === "unknown" ? "pending" : check.state}`, `${labels.checkNames[check.name]} / ${labels.state[check.state]}`), element("p", "context", labels.reasons[check.reason]));
  return item;
}

function renderAnswerAudit(result) {
  const panel = byId("answer-results");
  panel.replaceChildren(element("div", result.status === "blocked" ? "notice error" : "notice", labels.answerStatuses[result.status]));
  const unitSummary = element("section", "audit-count-group");
  unitSummary.append(element("h2", "", labels.answerUnitSummary));
  const unitCounts = element("div", "coverage-summary");
  for (const [key, label] of [["total_units", "answerTotalUnits"], ["cited_units", "answerCited"], ["uncited_units", "answerUncited"], ["blocked_units", "answerBlocked"], ["review_required_units", "answerPending"]]) {
    unitCounts.append(element("span", "badge", `${labels[label]} ${result.coverage[key]}`));
  }
  unitSummary.append(unitCounts);
  const citationSummary = element("section", "audit-count-group");
  citationSummary.append(element("h2", "", labels.answerCitationSummary));
  const citationCounts = element("div", "coverage-summary");
  for (const [key, label, state] of [["total", "answerTotalCitations", ""], ["blocked", "answerBlockedCitations", "fail"], ["review_required", "answerPendingCitations", "pending"], ["eligible_reference", "answerEligibleCitations", ""]]) {
    citationCounts.append(element("span", `badge ${state}`, `${labels[label]} ${result.citation_summary[key]}`));
  }
  const bindingCounts = element("div", "coverage-summary binding-counts");
  for (const [key, label] of [["registered_binding_pass", "answerBindingPass"], ["registered_binding_fail", "answerBindingFail"], ["registered_binding_unknown", "answerBindingUnknown"]]) {
    bindingCounts.append(element("span", "badge", `${labels[label]} ${result.citation_summary[key]}`));
  }
  citationSummary.append(citationCounts, bindingCounts, element("p", "context", `${labels.answerDuplicates} ${result.coverage.duplicate_citations}\u3002${labels.answerCitationCountNote}`));
  const limits = element("div", "notice audit-limits");
  const evaluationStates = element("div", "coverage-summary");
  for (const [key, label] of [["joint_support", "answerJointSupport"], ["question_completeness", "answerQuestionCompleteness"]]) {
    evaluationStates.append(element("span", "badge pending", `${labels[label]}\uff1a${result[key] === "not_evaluated" ? labels.answerNotEvaluated : labels.answerNotReported}`));
  }
  limits.append(evaluationStates, element("p", "context", labels.answerLimit));
  panel.append(unitSummary, citationSummary, limits);
  result.units.forEach((unit, index) => {
    const card = element("article", "result-card");
    const heading = element("div", "card-top");
    heading.append(element("h2", "audit-unit-heading", `${labels.answerUnit} ${index + 1}`), element("span", unit.status === "blocked" ? "badge fail" : "badge pending", labels.answerUnitStatuses[unit.status]));
    card.append(heading, element("p", "claim-text", unit.text));
    if (!unit.citations.length) card.append(element("p", "context", labels.answerUnlinkedReason));
    unit.citations.forEach((citation, citationIndex) => {
      const source = catalog.sources.find((s) => s.id === citation.source_id);
      const claim = catalog.claims.find((c) => c.id === citation.claim_id);
      const passage = source?.passages.find((p) => p.id === citation.passage_id);
      const status = citation.checks.status;
      const diagnostic = element("section", `citation-diagnostic ${status === "blocked" ? "citation-blocked" : ""}`);
      const top = element("div", "card-top");
      top.append(element("h3", "", `${labels.answerCitation} ${citationIndex + 1}`), element("span", status === "blocked" ? "badge fail" : (status === "review_required" ? "badge pending" : "badge"), labels.answerCitationStatuses[status]));
      diagnostic.append(top);
      if (source) {
        diagnostic.append(element("p", "citation-source-name", sourceDisplayTitle(source)), element("p", "source-meta", `PMID ${source.pmid || "-"} / DOI ${source.doi || "-"} / ${labels.publicationYear} ${source.year}`), sourceButton(source, labels.openSource, "text-button citation-source-button"));
      } else {
        diagnostic.append(element("p", "context", labels.answerUnknownSource));
      }
      diagnostic.append(element("p", "source-meta", `${citation.claim_id || "-"} / ${citation.source_id || "-"} / ${citation.passage_id || "-"}`));
      diagnostic.append(element("h4", "registered-wording-label", labels.registeredParaphrase), element("p", "registered-wording", claim ? claim.text : labels.answerUnknownSource));
      const mainChecks = element("div", "citation-key-checks");
      citation.checks.checks.filter((check) => ["registered_binding", "clinical_support", "currency"].includes(check.name) || check.state === "fail").forEach((check) => mainChecks.append(answerCheckItem(check)));
      diagnostic.append(mainChecks);
      const details = element("details", "citation-details");
      details.append(element("summary", "", labels.answerCitationDetails));
      if (passage) {
        details.append(element("h4", "registered-wording-label", labels.answerSavedPassage), element("blockquote", "", passage.text), element("p", "locator", passage.locator), element("p", "context", passage.context_note));
      } else {
        details.append(element("p", "context", labels.answerPassageUnavailable));
      }
      const checks = element("div", "answer-checks");
      citation.checks.checks.forEach((check) => checks.append(answerCheckItem(check)));
      details.append(element("h4", "registered-wording-label", labels.answerAllChecks), checks);
      diagnostic.append(details);
      card.append(diagnostic);
    });
    panel.append(card);
  });
  appendReceipt(panel, result);
}

async function auditDraft() {
  if (!preparedAnswer) return;
  const sequence = ++answerSequence;
  const {answer, disease, corpus_sha256, units} = preparedAnswer;
  const selected = [...byId("answer-units").querySelectorAll('input[type="checkbox"]:checked')];
  const bindings = units.map((unit) => ({unit_id: unit.id, citations: selected.filter((input) => input.dataset.unitId === unit.id).map((input) => {
    const claim = catalog.claims.find((c) => c.id === input.value);
    return {claim_id: claim.id, source_id: claim.source_id, passage_id: claim.passage_id};
  })}));
  byId("audit-answer-button").disabled = true;
  byId("audit-answer-button").textContent = labels.checking;
  byId("answer-results").setAttribute("aria-busy", "true");
  try {
    const result = await api("/api/audit-answer", {answer, disease, corpus_sha256, bindings});
    if (sequence === answerSequence) {
      if (result.corpus_sha256 !== catalog.corpus_sha256) throw new Error("stale_catalog");
      renderAnswerAudit(result);
    }
  } catch {
    if (sequence === answerSequence) byId("answer-results").replaceChildren(element("div", "notice error", labels.answerRequestError));
  } finally {
    if (sequence === answerSequence) {
      byId("audit-answer-button").disabled = false;
      byId("audit-answer-button").textContent = labels.answerAudit;
      byId("answer-results").setAttribute("aria-busy", "false");
    }
  }
}

async function initialize() {
  try {
    const values = await Promise.all([api("/api/catalog"), api("/zh.json"), api("/api/status"), api("/api/review-packet")]);
    [catalog, labels] = values;
    packet = values[3];
    if (catalog.corpus_sha256 !== values[2].corpus_sha256 || catalog.corpus_sha256 !== packet.corpus_sha256) throw new Error("inconsistent_snapshot");
    renderLibrary(values[2]);
    refreshLiterature();
    renderReview();
    updateSearchMode();
    catalog.claims.forEach((claim) => {
      const option = element("option", "", `${labels.diseases[claim.disease]} / ${claim.id}`);
      option.value = claim.id;
      byId("lab-claim").append(option);
    });
    catalog.sources.forEach((source) => {
      const option = element("option", "", sourceDisplayTitle(source));
      option.value = source.id;
      byId("lab-source").append(option);
    });
    resetLab();
    byId("review-disease").addEventListener("change", renderReview);
    byId("question").addEventListener("input", invalidateSearch);
    byId("disease").addEventListener("change", () => { updateFulltextSources(); invalidateSearch(); });
    byId("mode").addEventListener("change", invalidateSearch);
    byId("fulltext-source").addEventListener("change", invalidateSearch);
    byId("fulltext-reload").addEventListener("click", () => { invalidateSearch(); refreshFulltext(); });
    byId("library-query").addEventListener("input", () => { literaturePage = 1; renderLiterature(); });
    ["library-disease", "library-tcm"].forEach((id) => byId(id).addEventListener("change", () => { literaturePage = 1; renderLiterature(); }));
    byId("library-reload").addEventListener("click", refreshLiterature);
    byId("library-previous").addEventListener("click", () => { literaturePage--; renderLiterature(); byId("library-status").scrollIntoView({block: "start"}); });
    byId("library-next").addEventListener("click", () => { literaturePage++; renderLiterature(); byId("library-status").scrollIntoView({block: "start"}); });
    document.querySelectorAll("[data-view]").forEach((node) => node.addEventListener("click", () => showView(node.dataset.view)));
    document.querySelectorAll("[data-example]").forEach((node) => node.addEventListener("click", () => {
      byId("question").value = (byId("mode").value === "extract" ? labels.extractExamples : labels.examples)[node.dataset.example];
      byId("disease").value = node.dataset.example;
      byId("fulltext-source").value = "all";
      updateFulltextSources();
      invalidateSearch();
      ask();
    }));
    document.querySelectorAll("[data-scenario]").forEach((node) => node.addEventListener("click", () => {
      resetLab();
      if (node.dataset.scenario === "swap") {
        const other = catalog.sources.find((s) => s.id !== activeClaim.source_id);
        if (other) {
          byId("lab-source").value = other.id;
          updateLabSource();
        }
      } else if (node.dataset.scenario === "rewrite") {
        byId("lab-text").value += labels.rewriteSuffix;
      }
    }));
    if (catalog.sources.length < 2) document.querySelector('[data-scenario="swap"]').disabled = true;
    byId("question-form").addEventListener("submit", ask);
    byId("check-form").addEventListener("submit", check);
    byId("lab-claim").addEventListener("change", resetLab);
    byId("lab-source").addEventListener("change", updateLabSource);
    byId("lab-passage").addEventListener("change", updateLabPassage);
    byId("lab-text").addEventListener("input", invalidateCheck);
    byId("lab-quote").addEventListener("input", invalidateCheck);
    byId("answer-form").addEventListener("submit", prepareAnswer);
    byId("answer-text").addEventListener("input", () => invalidateAnswer());
    byId("answer-disease").addEventListener("change", () => invalidateAnswer());
    byId("audit-answer-button").addEventListener("click", auditDraft);
    document.querySelectorAll("[data-answer-example]").forEach((button) => {
      button.disabled = !catalog.claims.length || (["swap", "mixed"].includes(button.dataset.answerExample) && catalog.claims.length < 2);
      button.addEventListener("click", () => {
        const claim = catalog.claims[0];
        byId("answer-text").value = claim.text + (button.dataset.answerExample === "missing" ? "\n" + labels.answerMissing : "");
        byId("answer-disease").value = button.dataset.answerExample === "mixed" ? "all" : claim.disease;
        prepareAnswer(null, button.dataset.answerExample);
      });
    });
    byId("close-source").addEventListener("click", () => byId("source-dialog").close());
    byId("source-dialog").addEventListener("click", (event) => {
      if (event.target === byId("source-dialog") && event.clientX < byId("source-dialog").getBoundingClientRect().left) byId("source-dialog").close();
    });
    refreshFulltext();
  } catch {
    byId("fatal").hidden = false;
    byId("fatal").textContent = labels ? labels.connectionError : "\u672c\u5730\u670d\u52a1\u672a\u8fde\u63a5\u3002\u8bf7\u542f\u52a8\u9879\u76ee\u540e\u5237\u65b0\u9875\u9762\u3002";
    byId("ask-button").disabled = true;
    byId("check-button").disabled = true;
    byId("segment-button").disabled = true;
  }
}

initialize();
