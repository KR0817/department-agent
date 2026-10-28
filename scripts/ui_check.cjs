/* Optional browser regression. Requires an installed Playwright module and Edge. */
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const base = process.env.UI_CHECK_BASE || 'http://127.0.0.1:18930';
const output = path.resolve(process.env.UI_CHECK_OUTPUT || 'work/ui-verda-20261029/browser');
const root = path.resolve(__dirname, '..');
const checks = [], errors = [], external = [];
let completed = false;
function check(name, ok, detail) {
  checks.push({ name, passed: Boolean(ok), ...(detail === undefined ? {} : { detail }) });
  if (!ok) throw new Error(name);
}
async function settle(page) {
  await page.waitForFunction(() => !document.querySelector('#content .skeleton, #department_full_analysis .skeleton'));
  await page.evaluate(() => document.fonts.ready);
}
async function navigate(page, name) {
  const nav = page.locator('#nav_' + name);
  if (!(await nav.isVisible())) await page.locator('#navigation_toggle').click();
  await nav.click();
  await page.waitForFunction(id => document.getElementById(id)?.getAttribute('aria-current') === 'page', 'nav_' + name);
  await settle(page);
}
async function capture(page, name) {
  check(name + '-no-outer-overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  // Edge full-page capture transiently reports a 1px viewport. Fixed dialogs need viewport capture.
  const floating = await page.locator('dialog[open]').count() > 0;
  if (!floating) await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(output, name + '.png'), fullPage: !floating });
}
async function uploadSynthetic(page) {
  const status = await (await page.request.get(base + '/api/status')).json();
  check('synthetic-runtime-only', status.mode === 'synthetic-demo');
  const raw = fs.readFileSync(path.join(root, 'clinical/fixtures/lab.csv'));
  check('marked-fixture-only', raw.toString('utf8').startsWith('# SJD-SYNTHETIC'));
  const row = raw.toString('utf8').split(/\r?\n/)[2].split(',');
  const registration = await page.request.post(base + '/api/patient-registry', { headers: { Origin: base }, data: { patient_id: row[0], name: row[1] } });
  check('synthetic-registration', registration.ok());
  const name = 'ui-synthetic-' + Date.now() + '.csv';
  const response = await page.request.post(base + '/api/upload', { headers: { Origin: base }, multipart: {
    file: { name, mimeType: 'text/csv', buffer: raw }, synthetic: 'true', patient_id: row[0]
  }});
  check('synthetic-upload', response.ok());
  const job = await response.json();
  for (let i = 0; i < 150; i++) {
    const item = await (await page.request.get(base + '/api/jobs/' + job.id)).json();
    if (item.state === 'review') return { id: job.id, name: item.filename };
    if (['failed', 'blocked'].includes(item.state)) throw new Error('Synthetic review did not become ready');
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('Synthetic review timeout');
}

(async () => {
  if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(base)) throw new Error('Use an isolated loopback synthetic service');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.UI_CHECK_CHANNEL || 'msedge', headless: true });
  try {
    for (const [size, width, height] of [['desktop', 1440, 1000], ['compact', 1280, 960], ['tablet', 768, 1024], ['mobile', 390, 844]]) {
      const page = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' });
      page.on('pageerror', error => errors.push({ size, message: error.message }));
      page.on('console', item => { if (item.type() === 'error') errors.push({ size, message: item.text() }); });
      page.on('request', request => { if (!request.url().startsWith(base + '/') && !request.url().startsWith('data:') && !request.url().startsWith('blob:')) external.push({ size, url: new URL(request.url()).origin }); });
      await page.goto(base + '/#overview');
      await page.locator('#workspace').waitFor({ state: 'visible' });
      await settle(page);
      if (size === 'mobile') {
        await page.locator('#navigation_toggle').click();
        check('mobile-menu-modal', await page.locator('#primary_navigation').getAttribute('aria-modal') === 'true');
        check('mobile-menu-inert-background', await page.locator('#workspace_layout').evaluate(node => node.inert));
        await page.keyboard.press('Escape');
        check('mobile-menu-escape', await page.locator('#navigation_toggle').getAttribute('aria-expanded') === 'false');
        check('mobile-menu-focus-return', await page.locator('#navigation_toggle').evaluate(node => document.activeElement === node));
      }
      for (const view of ['overview', 'workbench', 'knowledge', 'analysis']) {
        await navigate(page, view);
        if (view === 'analysis') {
          await page.locator('#department_rx_frame').waitFor({ state: 'visible' });
          await page.frameLocator('#department_rx_frame').locator('body').waitFor();
        }
        await capture(page, size + '-' + view);
      }
      const frameHandle = await page.locator('#department_rx_frame').elementHandle();
      const frame = await frameHandle.contentFrame();
      await frame.locator('#workspace-tab-intake').click();
      check(size + '-original-import-reachable', await frame.locator('#intake-file').isVisible());
      await frame.locator('#workspace-tab-cases').click();
      check(size + '-original-cases-reachable', await frame.locator('#show-exact-rx').isVisible());
      await frame.evaluate(() => { document.body.dataset.uiRetention = 'preserved'; });
      await navigate(page, 'knowledge');
      await navigate(page, 'analysis');
      check(size + '-frame-retained', await frameHandle.evaluate(node => node === document.getElementById('department_rx_frame')));
      check(size + '-frame-state-retained', await frame.evaluate(() => document.body.dataset.uiRetention === 'preserved'));
      check(size + '-original-tab-retained', await frame.locator('#show-exact-rx').isVisible());
      await frame.locator('#workspace-tab-aggregate').click();
      check(size + '-original-aggregate-reachable', await frame.locator('#aggregate-frame').isVisible());
      check(size + '-all-report-links', await page.locator('.department-full-reports a').count() === 9);
      check(size + '-standalone-preserved', (await page.locator('#department_rx_open').getAttribute('href')) === '/api/department/mingyirx/site/index.html');
      await page.locator('#department_rx_expand').click();
      check(size + '-canvas-expanded', await page.locator('#department_rx_expand').getAttribute('aria-pressed') === 'true');
      check(size + '-expanded-frame-retained', await frameHandle.evaluate(node => node === document.getElementById('department_rx_frame')));
      await capture(page, size + '-expanded-prescription');
      await page.keyboard.press('Escape');
      check(size + '-canvas-escape', await page.locator('#department_rx_expand').getAttribute('aria-pressed') === 'false');
      check(size + '-canvas-focus-return', await page.locator('#department_rx_expand').evaluate(node => document.activeElement === node));
      if (size === 'desktop') {
        await page.locator('#department_rx_expand').click();
        const aggregate = await (await frame.locator('#aggregate-frame').elementHandle()).contentFrame();
        await aggregate.locator('body').click({ position: { x: 12, y: 12 } });
        await page.keyboard.press('Escape');
        check('nested-prescription-escape', await page.locator('#department_rx_expand').getAttribute('aria-pressed') === 'false');
      }
      await navigate(page, 'knowledge');
      const catalog = await (await page.request.get(base + '/api/department/knowledge/catalog')).json();
      await page.locator('#department_question').fill(catalog.example_question);
      await page.locator('#department_ask').click();
      await page.locator('.department-answer').first().waitFor();
      check(size + '-knowledge-source-link', await page.locator('a[href^="/api/department/knowledge/section/"]').count() > 0);
      await capture(page, size + '-knowledge-answer');
      const reader = page.locator('.department-read-source').first();
      const [sourcePage] = await Promise.all([page.waitForEvent('popup'), reader.click()]);
      await sourcePage.locator('main').waitFor();
      check(size + '-protected-source-opens', sourcePage.url().startsWith(base + '/api/department/knowledge/section/'));
      await capture(sourcePage, size + '-knowledge-source');
      await sourcePage.close();

      await page.goto(base + '/#analysis-quick');
      await page.locator('#department_example').waitFor();
      await page.locator('#department_example').click();
      await page.locator('#department_record_0_date').waitFor();
      await capture(page, size + '-quick-analysis');

      if (size === 'desktop' || size === 'mobile') {
        const job = await uploadSynthetic(page);
        await navigate(page, 'workbench');
        const queued = page.locator('#jobs .job').filter({ hasText: job.name });
        await queued.waitFor({ timeout: 15000 });
        await queued.click();
        await page.locator('#archive_button').waitFor();
        check(size + '-archive-requires-confirmation', await page.locator('#archive_button').isDisabled());
        await page.locator('#reviewed').check();
        check(size + '-default-accepted-archive-enabled', await page.locator('#archive_button').isEnabled());
        await capture(page, size + '-clinical-review');
        const opener = page.locator('.source-actions button').last();
        await opener.click();
        await page.locator('.source-dialog .source-page-view pre').waitFor();
        check(size + '-source-fields-retained', await page.locator('.source-dialog .source-field-button').count() === 3);
        await capture(page, size + '-clinical-evidence');
        if (size === 'desktop') {
          await page.locator('#source_pin_toggle').click();
          check('desktop-source-pinned', await page.locator('.source-dialog').evaluate(node => node.open && !node.matches(':modal')));
          check('desktop-review-accessible-while-pinned', await page.locator('#archive_button').isEnabled());
          await capture(page, 'desktop-clinical-pinned');
          await page.locator('.field-source-action').nth(1).click();
          await page.waitForFunction(() => document.querySelectorAll('.source-dialog').length === 1 && document.querySelector('.source-field-button:nth-child(2)')?.getAttribute('aria-pressed') === 'true');
          check('desktop-single-evidence-panel', await page.locator('.source-dialog').count() === 1);
          await page.locator('#source_pin_toggle').click();
          check('desktop-source-modal-restored', await page.locator('.source-dialog').evaluate(node => node.matches(':modal')));
        }
        await page.keyboard.press('Escape');
        await page.locator('.source-dialog').waitFor({ state: 'detached' });
        check(size + '-source-escape', await page.locator('.source-dialog').count() === 0);
        const expectedOpener = size === 'desktop' ? page.locator('.field-source-action').nth(1) : opener;
        check(size + '-source-focus-return', await expectedOpener.evaluate(node => document.activeElement === node));
        await page.locator('.decision-button[data-action="modify"]').first().click();
        check(size + '-unsaved-change-blocks-archive', await page.locator('#archive_button').isDisabled());
      }
      await page.close();
    }
    const session = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await session.goto(base + '/#analysis');
    await session.locator('#department_rx_frame').waitFor();
    await session.locator('#department_rx_expand').click();
    await session.locator('#logout').click();
    await session.locator('#workspace').waitFor({ state: 'hidden' });
    check('logout-clears-prescription-frame', await session.locator('#department_rx_frame').count() === 0);
    check('logout-clears-canvas-state', !(await session.locator('body').evaluate(node => node.classList.contains('department-canvas-expanded'))));
    await session.close();
    check('no-browser-errors', errors.length === 0, errors);
    check('no-external-requests', external.length === 0, external);
    completed = true;
  } finally {
    await browser.close();
    const report = { completed, passed: completed && checks.every(item => item.passed), synthetic: true, clinical_validation: false, checks, errors, external };
    fs.writeFileSync(path.join(output, 'checks.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ completed, passed: report.passed, checks: checks.length, errors: errors.length, external: external.length }));
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
