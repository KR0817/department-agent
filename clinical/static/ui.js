// Presentation-only helpers. They never call the API or change application state;
// app.js remains the single owner of routing, data and rendering.

const narrow = window.matchMedia('(max-width: 800px)');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

// The skip link must not change location.hash, because the hash drives routing.
document.addEventListener('click', event => {
  const link = event.target.closest('.skip-link');
  if (!link) return;
  event.preventDefault();
  const candidates = [link.dataset.skipTarget, 'auth_title'];
  for (const id of candidates) {
    const target = id && document.getElementById(id);
    if (!target || target.closest('[hidden]')) continue;
    if (!target.hasAttribute('tabindex')) target.tabIndex = -1;
    target.focus();
    target.scrollIntoView({block: 'start', behavior: reducedMotion.matches ? 'auto' : 'smooth'});
    return;
  }
});

// On a single-column layout the review panel sits below the upload sidebar.
// After a queued document is chosen, bring its review into view once app.js has rendered it
// (the page is too short to scroll there before the review content arrives).
let revealUntil = 0;
const revealReview = () => {
  const tabs = document.getElementById('workbench_tabs');
  if (!tabs || tabs.hidden) return;
  tabs.scrollIntoView({block: 'start', behavior: reducedMotion.matches ? 'auto' : 'smooth'});
};
document.addEventListener('click', event => {
  if (!narrow.matches || !event.target.closest('#jobs .job, #upload_results .upload-result button')) return;
  revealUntil = Date.now() + 2500;
  requestAnimationFrame(revealReview);
});
const content = document.getElementById('content');
if (content) {
  new MutationObserver(() => {
    if (Date.now() > revealUntil) return;
    requestAnimationFrame(() => {
      revealReview();
      const tabs = document.getElementById('workbench_tabs');
      // Stop as soon as the review has actually reached the top of the screen.
      if (tabs && Math.abs(tabs.getBoundingClientRect().top) < 8) revealUntil = 0;
    });
  }).observe(content, {childList: true});
}

// On phones the secondary tabs scroll sideways; keep the chosen tab fully visible.
document.addEventListener('click', event => {
  const tab = event.target.closest('#workbench_tabs [role=tab]');
  if (!tab || !narrow.matches) return;
  tab.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: reducedMotion.matches ? 'auto' : 'smooth'});
});

// Upload drop zone: name the chosen files, mirror the locked first step and highlight a drag.
const fileInput = document.getElementById('file');
const fileDrop = document.getElementById('file_drop');
const fileSummary = document.getElementById('file_summary');
const describeFiles = () => {
  if (!fileInput || !fileDrop || !fileSummary) return;
  const files = [...(fileInput.files || [])];
  if (files.length) {
    const names = files.slice(0, 2).map(file => file.name).join('、');
    fileSummary.textContent = '已选择 ' + files.length + ' 份：' + names + (files.length > 2 ? ' 等' : '');
    fileDrop.dataset.files = String(files.length);
  } else {
    fileSummary.textContent = fileInput.disabled ? '请先完成第 1 步：选择或新建患者' : '尚未选择文件';
    delete fileDrop.dataset.files;
  }
};
if (fileInput && fileDrop) {
  fileInput.addEventListener('change', describeFiles);
  new MutationObserver(describeFiles).observe(fileInput, {attributes: true, attributeFilter: ['disabled']});
  for (const type of ['dragenter', 'dragover']) {
    fileDrop.addEventListener(type, () => { if (!fileInput.disabled) fileDrop.classList.add('is-dragover'); });
  }
  for (const type of ['dragleave', 'dragend', 'drop']) {
    fileDrop.addEventListener(type, () => fileDrop.classList.remove('is-dragover'));
  }
  describeFiles();
}

// A file dropped anywhere except an enabled file input would make the browser open it
// and leave the workbench, discarding unsaved review decisions.
const carriesFiles = event => [...(event.dataTransfer?.types || [])].includes('Files');
const acceptsFiles = target => target instanceof Element && Boolean(target.closest('input[type=file]:not(:disabled)'));
for (const type of ['dragover', 'drop']) {
  window.addEventListener(type, event => {
    if (!carriesFiles(event) || acceptsFiles(event.target)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
  });
}

// Arrow, Home and End keys move between tabs in a tab list.
document.addEventListener('keydown', event => {
  const tab = event.target instanceof Element ? event.target.closest('[role=tablist] [role=tab]') : null;
  if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const tabs = [...tab.closest('[role=tablist]').querySelectorAll('[role=tab]')].filter(item => !item.hidden && !item.disabled);
  const index = tabs.indexOf(tab);
  if (index < 0 || !tabs.length) return;
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
    : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  event.preventDefault();
  tabs[next].focus();
  tabs[next].click();
});

// Content that arrives after a navigation rises into place once; background refreshes stay still.
const views = ['content', 'department_full_analysis'].map(id => document.getElementById(id)).filter(Boolean);
let revealUntilLoaded = 0;
let revealTimer = 0;
const playReveal = () => {
  if (reducedMotion.matches) return;
  clearTimeout(revealTimer);
  for (const view of views) {
    if (view.hidden) continue;
    view.classList.remove('view-enter');
    void view.offsetWidth;
    view.classList.add('view-enter');
  }
  revealTimer = setTimeout(() => { for (const view of views) view.classList.remove('view-enter'); }, 900);
};
const markNavigation = () => {
  revealUntilLoaded = Date.now() + 20000;
  requestAnimationFrame(playReveal);
};
document.addEventListener('click', event => {
  if (event.target instanceof Element
      && event.target.closest('.primary-nav button, #workbench_tabs [role=tab], [data-patient-source], .patient-back, #jobs .job')) {
    markNavigation();
  }
});
window.addEventListener('hashchange', markNavigation);
for (const view of views) {
  new MutationObserver(() => {
    if (!revealUntilLoaded || Date.now() > revealUntilLoaded || view.hidden || view.querySelector('.skeleton')) return;
    revealUntilLoaded = 0;
    requestAnimationFrame(playReveal);
  }).observe(view, {childList: true});
}
