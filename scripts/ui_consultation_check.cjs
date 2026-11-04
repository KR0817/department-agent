/* Browser regression against a dedicated, synthetic loopback run only. */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '../frontend/node_modules/playwright');
const base = process.env.UI_CHECK_BASE || 'http://127.0.0.1:18950';
const output = path.resolve(process.env.UI_CHECK_OUTPUT || 'work/react-langgraph/browser');
const checks = [], errors = [], external = [];
function check(name, passed) { checks.push({ name, passed: Boolean(passed) }); if (!passed) throw new Error(name); }
async function ready(page) { await page.locator('.consultation-controls:not([disabled])').waitFor(); }
async function action(page, id, endpoint) {
  const waiting = page.waitForResponse(response => response.url().includes('/api/department/' + endpoint) && response.request().method() === 'POST');
  await page.locator(id).click(); const response = await waiting;
  check('response-' + id, response.ok()); await ready(page); return response.json();
}
async function navigate(page, name) {
  const nav = page.locator('#nav_' + name);
  if (!await nav.isVisible()) await page.locator('#navigation_toggle').click();
  await nav.click();
  await page.waitForFunction(id => document.getElementById(id)?.getAttribute('aria-current') === 'page', 'nav_' + name);
  if (name === 'consultation') await ready(page);
}
async function capture(page, name) {
  check(name + '-no-overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true });
}
(async () => {
  if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw new Error('Use a synthetic loopback service');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.UI_CHECK_CHANNEL || 'msedge', headless: true });
  try {
    for (const width of [1440, 768, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      page.on('request', request => { if (!request.url().startsWith(base + '/') && !request.url().startsWith('data:')) external.push(request.url().split('/').slice(0, 3).join('/')); });
      await page.goto(base + '/#consultation'); await ready(page);
      check('synthetic-mode-' + width, (await (await page.request.get(base + '/api/status')).json()).mode === 'synthetic-demo');
      const title = 'Synthetic React ' + width + ' ' + Date.now();
      await page.locator('#consultation_instruction').fill(title);
      await page.locator('#consultation_example').click();
      await page.waitForFunction(() => document.getElementById('consultation_text').value.length > 20); await ready(page);
      let flow = await action(page, '#consultation_run', 'assistant/consultation');
      check('real-graph-' + width, flow.engine === 'langgraph' && flow.stage === 'question');
      await page.locator('#consultation_origin').selectOption('clinician');
      await page.locator('#consultation_answer').fill('Synthetic observed finding');
      await capture(page, width + '-question');
      if (width === 1440) {
        let release, finished;
        const waiting = new Promise(resolve => { release = resolve; });
        const handled = new Promise(resolve => { finished = resolve; });
        const pattern = '**/api/department/assistant/consultation';
        await page.route(pattern, async route => {
          const response = await route.fetch(); await waiting;
          await route.fulfill({ response }).catch(() => {}); finished();
        });
        await page.locator('#consultation_run').click();
        await page.locator('.consultation-activity button').click();
        release(); await handled; await page.unroute(pattern); await ready(page);
        check('cancel-keeps-answer-and-discards-late-turn', await page.locator('#consultation_answer').inputValue() === 'Synthetic observed finding');
      }
      const saved = await action(page, '#consultation_save', 'assistant/drafts/');
      check('saved-first-revision-' + width, saved.revision === 1 && saved.draft.supplements[0].origin === 'clinician');
      await navigate(page, 'knowledge'); await navigate(page, 'consultation');
      check('navigation-keeps-edit-' + width, await page.locator('#consultation_answer').inputValue() === 'Synthetic observed finding');
      await page.locator('#consultation_new').click();
      await page.locator('[data-draft-id="' + saved.id + '"]').click(); await ready(page);
      check('resume-source-' + width, await page.locator('#consultation_instruction').inputValue() === title);
      await page.locator('#consultation_instruction').fill(title + ' version two');
      check('save-second-version-' + width, (await action(page, '#consultation_save', 'assistant/drafts/')).revision === 2);
      await page.locator('#consultation_history').click(); await page.locator('[data-revision="1"]').waitFor();
      await page.locator('[data-revision="1"]').click(); await page.locator('#consultation_restore').waitFor();
      await page.locator('#consultation_restore').click();
      check('restore-source-' + width, await page.locator('#consultation_instruction').inputValue() === title);
      check('restore-appends-version-' + width, (await action(page, '#consultation_save', 'assistant/drafts/')).revision === 3);
      flow = await action(page, '#consultation_run', 'assistant/consultation');
      for (let turns = 0; flow.stage === 'question' && turns < 30; turns++) flow = await action(page, '#consultation_unavailable', 'assistant/consultation');
      check('graph-reaches-review-' + width, flow.stage === 'review_ready');
      check('human-review-required-' + width, await page.locator('#consultation_review').isDisabled());
      await capture(page, width + '-review');
      await page.locator('#consultation_review_check').check();
      flow = await action(page, '#consultation_review', 'assistant/consultation');
      check('review-not-clinical-approval-' + width, flow.stage === 'reviewed' && flow.clinical_approval === null);
      await action(page, '#consultation_save', 'assistant/drafts/');
      await page.locator('#consultation_handoff').click();
      await page.waitForURL('**/#analysis-quick');
      await page.locator('.department-review textarea').first().waitFor();
      check('handoff-retains-supplement-' + width, await page.locator('.department-review textarea').evaluateAll(nodes => nodes.some(node => node.value === 'Synthetic observed finding')));
      await navigate(page, 'analysis'); await page.locator('#department_rx_frame').waitFor();
      await page.frameLocator('#department_rx_frame').locator('#workspace-tab-intake').waitFor();
      check('original-report-links-' + width, await page.locator('.department-full-reports a').count() === 9);
      await navigate(page, 'consultation');
      await page.locator('#consultation_instruction').fill(title + ' changed');
      check('edit-revokes-review-' + width, await page.locator('#consultation_handoff').count() === 0);
      await action(page, '#consultation_save', 'assistant/drafts/');
      await page.locator('#logout').click(); await page.locator('#auth_shell').waitFor({ state: 'visible' });
      check('logout-unmounts-react-' + width, await page.locator('.consultation-grid').count() === 0);
      await page.close();
    }
    check('no-browser-errors', errors.length === 0); check('no-external-requests', external.length === 0);
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ passed: true, checks, errors, external }, null, 2));
    console.log(JSON.stringify({ passed: true, checks: checks.length, output }));
  } catch (error) {
    const page = browser.contexts().flatMap(context => context.pages()).at(-1);
    if (page) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ passed: false, checks, errors, external, failure: error.message }, null, 2));
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
