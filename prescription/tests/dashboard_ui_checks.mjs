import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const html = fs.readFileSync(process.argv[2], 'utf8');
const source = html.split('<script>')[1].split('</script>')[0]
  .replace('initializeReference();render();', '');

function setup() {
  const contextRow = { group: 'ra', stratum_type: 'overall', stratum: 'all' };
  const item = (name, value) => ({ ...contextRow, item_name: name, prevalence: value,
    exposed_patients: '10', group_patients: '20' });
  const change = (name, type) => ({ ...contextRow, item_name: name,
    change_type: type, patient_prevalence: '0.5', mean_patient_transition_fraction: '0.2',
    patients_with_change: '10', repeat_patients: '20' });
  const data = { version: 'test', clinicalMode: true, groups: [{ code: 'ra', label: 'RA' }],
    provenance: { dataset_id: 'synthetic-v1', source_sha256: { 'fixture.csv': 'a'.repeat(64) } },
    research: { cohorts: [{ group: 'ra_strict', label: 'Strict RA', patients: '30' },
                          { group: 'sjd_strict', label: 'Strict SjD', patients: '40' }],
      matched: [{ group: 'ra_strict', patients: '20', matched_transitions: '30', observed_patient_median_jaccard: '0.73' },
                { group: 'sjd_strict', patients: '25', matched_transitions: '45', observed_patient_median_jaccard: '0.41' }] },
    summaries: [{ ...contextRow, patients: '20' }],
    items: [item('Other', '0.9'), item('Target', '0.5')],
    changes: [change('Other', 'addition'), change('Target', 'addition'), change('Target', 'removal')],
    yearSummaries: [{ ...contextRow, year: '2020' }, { ...contextRow, year: '2022' }],
    yearItems: [{ ...item('Other', '0.9'), year: '2020' }, { ...item('Target', '0.5'), year: '2022' }],
    yearChanges: [{ ...change('Other', 'addition'), year: '2020' }],
    combinations: ['2', '3'].map(size => ({ ...contextRow, combination_size: size,
      combination: `Target | Pair${size}`, support: '0.5', support_patients: '10',
      stable_core_combination: 'True', bootstrap_core_selection_probability: '1' })),
    comparisons: [], longitudinal: [] };
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { innerHTML: '', textContent: '', hidden: false,
      disabled: false, value: '', dataset: {}, listeners: {}, attributes: {},
      addEventListener(type, fn) {
        const previous = this.listeners[type];
        this.listeners[type] = event => { previous?.(event); fn(event); };
      },
      setAttribute(name, value) { this.attributes[name] = value; }, focus() {} });
    return elements.get(id);
  };
  element('dashboard-data').textContent = JSON.stringify(data);
  const annual = ['prevalence', 'addition', 'removal'].map(metric => {
    const button = element(metric); button.dataset.annual = metric; return button;
  });
  const sizes = ['all', '2', '3'].map(size => {
    const button = element(`size-${size}`); button.dataset.size = size; return button;
  });
  const downloads = [];
  const document = { getElementById: element, body: { appendChild() {} },
    createElement: () => ({ click() { downloads.at(-1).name = this.download; }, remove() {} }),
    querySelectorAll: selector => ({ '.annual-btn': annual,
      '.filter-btn': [element('clear-search'), ...sizes],
      '.filter-btn[data-size]': sizes }[selector] || []) };
  const context = vm.createContext({ document, Blob, setTimeout: fn => fn(),
    URL: { createObjectURL(blob) { downloads.push({ blob }); return 'blob:synthetic'; }, revokeObjectURL() {} } });
  vm.runInContext(source, context);
  return { element, downloads, run: code => vm.runInContext(code, context) };
}

test('showcase overview filters navigation without pooling or changing selection', () => {
  const {element,run}=setup();
  run(`data.privacy={profile:'synthetic-showcase-v1',comparisons_enabled:true,combinations_enabled:true};
    data.provenance.synthetic_mode=true;
    data.groups=[{code:'ra',label:'Rheumatoid arthritis',patients:'40',disease_count:'1'},
    {code:'sle',label:'Systemic lupus erythematosus',patients:'60',disease_count:'1'},
    {code:'ra+sle',label:'Rheumatoid arthritis + Systemic lupus erythematosus',patients:'80',disease_count:'2'}];
    groupFilter='comorbidity';renderDiseaseOverview();renderNav();`);
  assert.equal(run('selected'),'ra');
  assert.equal(run('navigationGroups().length'),1);
  assert.match(element('overview-summary').textContent,/180/);
  assert.match(element('overview-groups').innerHTML,/data-group="ra\+sle"/);
  assert.match(element('group-nav').innerHTML,/系统性红斑狼疮/);
  assert.doesNotMatch(element('group-nav').innerHTML,/data-group="ra"/);
  assert.equal(run("groupLabel('Osteoarthritis + Gout')"),'骨关节炎 ＋ 痛风');
  assert.equal(run("groupLabel('Sjogren disease')"),'干燥病');
  assert.equal(run("groupLabel('Sjögren disease')"),'干燥综合征');
});

test('showcase comparison displays and exports the same rows and side denominators', async () => {
  const {element,run,downloads}=setup();
  run(`data.privacy={profile:'synthetic-showcase-v1',comparisons_enabled:true,combinations_enabled:true};
    data.provenance.synthetic_mode=true;data.source_identity={key:'primary',title:'Synthetic primary'};
    data.groups.push({code:'ra+sjd',label:'Rheumatoid arthritis + Sjögren disease',patients:'60',disease_count:'2'});
    data.comparisons=['.25','-.25','0'].map((difference,index)=>({combination_group:'ra+sjd',combination_label:'Rheumatoid arthritis + Sjögren disease',single_group:'ra',single_label:'Rheumatoid arthritis',stratum_type:'overall',stratum:'all',item_name:['Herb A','Herb B','Herb C'][index],change_type:'addition',combination_repeat_patients:'60',single_repeat_patients:'40',combination_patients_with_change:'30',single_patients_with_change:'20',combination_prevalence:'.5',single_prevalence:'.5',combination_mean_transition_fraction:String(.5+Number(difference)),single_mean_transition_fraction:'.5',mean_transition_fraction_difference:difference,higher_frequency:Number(difference)>0?'combination':Number(difference)<0?'single':'equal'}));
    renderComparisons();`);
  assert.equal(element('comparison-section').hidden,false);
  assert.equal(run('comparisonDisplayRows().length'),3);
  assert.match(element('comparison-combo').innerHTML,/30 \/ 60/);
  assert.match(element('comparison-single').innerHTML,/20 \/ 40/);
  assert.match(element('comparison-combo').innerHTML,/data-difference="0.25"/);
  assert.match(element('comparison-single').innerHTML,/data-difference="-0.25"/);
  assert.equal(run('comparisonExportRows()[0].synthetic_mode'),true);
  element('export-comparison').listeners.click();
  const csv=await downloads.at(-1).blob.text();
  assert.match(csv,/combination_repeat_patients/);
  assert.match(csv,/primary/);
  assert.match(csv,/Herb C/);
  run("query='herb a';renderComparisons()");
  assert.equal(run('comparisonDisplayRows().length'),1);
  assert.equal(run('comparisonExportRows().length'),1);
  run("query='NO MATCH';renderComparisons()");
  assert.equal(element('export-comparison').disabled,true);
  assert.equal(element('comparison-empty').hidden,false);
  run("query='';selected='unrelated';renderComparisons()");
  assert.equal(run('comparisonKey'),'');
  assert.equal(run('comparisonExportRows().length'),0);
});

test('showcase only enables admitted combinations while restricted panels stay hidden', () => {
  const {element,run}=setup();
  run(`data.privacy={profile:'synthetic-showcase-v1',combinations_enabled:true,comparisons_enabled:true};
    data.provenance.synthetic_mode=true;renderPresentationPolicy();`);
  assert.equal(element('combination-panel').hidden,false);
  assert.equal(element('size-2').hidden,false);
  assert.equal(element('strict-research').hidden,true);
  assert.equal(element('reference-section').hidden,true);
  run("data.privacy={profile:'conservative-v1'};renderPresentationPolicy()");
  assert.equal(element('combination-panel').hidden,true);
  assert.equal(element('size-2').hidden,true);
});

test('combination folding uses exact members, counts and cohort denominators', () => {
  const {run}=setup();
  run(`globalThis.comboFixture=(name,count='10',patients='20',stratum='all')=>({group:'ra',stratum_type:'overall',stratum,patients,combination:name,combination_size:String(name.split(' | ').length),support_patients:count,support:String(Number(count)/Number(patients)),stable_core_combination:'True',bootstrap_core_selection_probability:'1'});`);
  assert.equal(run(`comboFamilies([comboFixture('A | B'),comboFixture('A | B | C')]).length`),1);
  assert.equal(run(`comboFamilies([comboFixture('A | B'),comboFixture('A | B | C')])[0].children.length`),1);
  for(const expression of [
    "comboFixture('A | B | C','11')", "comboFixture('A | B | C','10','30')",
    "comboFixture('A | B | C','10','20','female')", "comboFixture('AA | B | C')",
    "({...comboFixture('A | B | C'),patients:undefined})",
    "({...comboFixture('A | B | C'),stable_core_combination:'False'})",
    "({...comboFixture('A | B | C'),combination_size:'2'})",
  ]) assert.equal(run(`comboFamilies([comboFixture('A | B'),${expression}]).length`),2,expression);
  run(`globalThis.ambiguous=[comboFixture('A | B'),comboFixture('A | B | D'),comboFixture('A | B | C')];globalThis.before=JSON.stringify(ambiguous)`);
  assert.equal(run(`comboFamilies(ambiguous).find(f=>f.children.length).row.combination`),'A | B | C');
  assert.equal(run(`comboFamilies(ambiguous).reduce((n,f)=>n+1+f.children.length,0)`),3);
  assert.equal(run(`JSON.stringify(ambiguous)===before`),true);
});

test('combination folding is reversible and respects search, size and root limits',()=>{
  const {run,element}=setup();
  run(`data.combinations=['A | B','A | B | C'].map((combination)=>({group:'ra',stratum_type:'overall',stratum:'all',patients:'20',combination,combination_size:String(combination.split(' | ').length),support_patients:'10',support:'0.5',stable_core_combination:'True',bootstrap_core_selection_probability:'1'}));limit=1`);
  element('fold-combos').checked=true;
  run('renderCombos()');
  assert.equal((element('combo-list').innerHTML.match(/<article/g)||[]).length,1);
  assert.match(element('combo-list').innerHTML,/<details/);
  assert.match(element('combo-list').innerHTML,/A ＋ B ＋ C/);
  element('fold-combos').checked=false;
  element('fold-combos').listeners.change({});
  assert.doesNotMatch(element('combo-list').innerHTML,/<details/);
  assert.match(element('combo-list').innerHTML,/A ＋ B/);
  element('fold-combos').checked=true;
  run("comboSize='2';renderCombos()");
  assert.doesNotMatch(element('combo-list').innerHTML,/<details/);
  run("comboSize='all';query='c';renderCombos()");
  assert.doesNotMatch(element('combo-list').innerHTML,/<details/);
  assert.match(element('combo-list').innerHTML,/A ＋ B ＋ C/);
});

test('medication search filters every trajectory lane and clears consistently', () => {
  const { element, run } = setup();
  element('search').listeners.input({ target: { value: 'Target' } });
  for (const id of ['trajectory-core', 'trajectory-addition', 'trajectory-removal']) {
    assert.match(element(id).innerHTML, /Target/);
    assert.doesNotMatch(element(id).innerHTML, /Other/);
  }
  element('search').listeners.input({ target: { value: 'missing' } });
  assert.doesNotMatch(element('trajectory-core').innerHTML, /Target|Other/);
  element('clear-search').listeners.click();
  assert.match(element('trajectory-core').innerHTML, /Other/);
  assert.equal(run('query'), '');
});

test('annual metric switches preserve medication and show unavailable data', () => {
  const { element, run } = setup();
  run('renderAnnual()');
  assert.equal(run('annualItem'), 'Other');
  assert.match(element('annual-chart').innerHTML, /<svg/);
  run("annualItem='Target';renderAnnual()");
  element('addition').listeners.click();
  assert.equal(run('annualItem'), 'Target');
  assert.equal(element('annual-section').hidden, false);
  assert.equal(element('addition').attributes['aria-pressed'], 'true');
  assert.match(element('annual-chart').innerHTML, /Target/);
  assert.doesNotMatch(element('annual-chart').innerHTML, /<svg/);
  element('removal').listeners.click();
  assert.equal(element('annual-section').hidden, false);
  assert.equal(run('annualItem'), 'Target');
  element('prevalence').listeners.click();
  assert.match(element('annual-chart').innerHTML, /<svg/);
  assert.match(element('annual-item').innerHTML, /Target/);
});

test('annual missing years break line segments without changing to zero', () => {
  const { run } = setup();
  assert.equal(run('annualLineSegments([{value:.5},{value:null},{value:.3}]).length'), 2);
  assert.equal(run('annualLineSegments([{value:0},{value:.3}]).length'), 1);
});

test('clear search preserves each combination filter with cumulative click listeners', () => {
  for (const size of ['all', '2', '3']) {
    const { element, run } = setup();
    element(`size-${size}`).listeners.click();
    element('search').listeners.input({ target: { value: 'missing' } });
    element('clear-search').listeners.click();
    assert.equal(run('comboSize'), size);
    assert.equal(element(`size-${size}`).attributes['aria-pressed'], 'true');
    assert.match(element('combo-list').innerHTML, /Target/);
  }
});

test('research results preserve strict cohort scope across clinical strata', () => {
  const { element, run } = setup();
  const before = element('matched-results').innerHTML;
  run("stratumType='sex';stratum='female';renderItemResearch()");
  assert.equal(run('strictGroup'), 'ra_strict');
  assert.equal(element('matched-results').innerHTML, before);
  element('strict-group').listeners.change({ target: { value: 'sjd_strict' } });
  assert.match(element('matched-results').innerHTML, /0.41/);
  assert.doesNotMatch(element('matched-results').innerHTML, /0.73/);
  assert.equal(run('stratumType'), 'sex');
});

test('item comparison and exports preserve missingness and one-dimensional strata', () => {
  const { element, run } = setup();
  run("researchItem='Target';renderItemResearch()");
  assert.match(element('item-comparison').innerHTML, /10 \/ 20/);
  run("stratumType='sex';stratum='female';renderItemResearch()");
  assert.equal(run('researchItem'), 'Target');
  assert.doesNotMatch(element('item-comparison').innerHTML, /10 \/ 20/);
  assert.equal(run('itemExportRows()[0].numerator'), '');
  assert.equal(run('itemExportRows()[0].prevalence'), '');
  assert.equal(run('itemExportRows()[0].stratum'), 'female');
  assert.equal(run("metricText('')"), run('metricText(null)'));
  assert.equal(run("metricText('0')"), '0');
});

test('exports execute downloads with formula-safe CSV and source provenance', async () => {
  const { element, run, downloads } = setup();
  run("researchItem='=SUM(1,2)';renderItemResearch()");
  element('export-item').listeners.click();
  assert.equal(downloads[0].name, 'mingyirx-item-view.csv');
  const csv = await downloads[0].blob.text();
  assert.match(csv, /"'=SUM\(1,2\)"/);
  assert.match(csv, /not_disclosed_or_not_estimated/);
  assert.match(csv, /synthetic-v1/);
  element('export-provenance').listeners.click();
  const record = JSON.parse(await downloads[1].blob.text());
  assert.equal(record.view.item, '=SUM(1,2)');
  assert.equal(record.provenance.source_sha256['fixture.csv'], 'a'.repeat(64));
  for (const value of ['=1', '+1', '-1', '@SUM(A1)', ' \t=1']) {
    assert.equal(run(`safeCsvCell(${JSON.stringify(value)})`).slice(0, 2), '"\'');
  }
});

test('CSV preserves finite numeric differences without trusting numeric-looking strings', () => {
  const {run}=setup();
  for (const value of [-0.25, -2, 0, 0.25, 2]) {
    assert.equal(run(`safeCsvCell(${value})`), `"${value}"`);
  }
  for (const value of ['-0.25', '-2', '-1e3', ' \t-0.25', '=HYPERLINK("x")', '+1', '@SUM(A1)']) {
    assert.equal(run(`safeCsvCell(${JSON.stringify(value)})`).slice(0, 2), '"\'');
  }
  assert.equal(run('safeCsvCell(-Infinity)'), '"\'-Infinity"');
});

test('all medication selectors sort by total visit usage and retain selection', () => {
  const {element, run} = setup();
  run(`research.usage=[{item_name:'Other',total_usage_visits:'12'},{item_name:'Target',total_usage_visits:'200'}];
    annualItem='Other';researchItem='Other';renderAnnual();renderItemResearch();
    research.nodes=['Other','Target'].map(item_name=>({group:strictGroup,item_name}));networkItem='Other';renderResearchNetwork();`);
  for(const id of ['annual-item','research-item','network-item']) {
    assert.ok(element(id).innerHTML.indexOf('value="Target"') < element(id).innerHTML.indexOf('value="Other"'));
    assert.match(element(id).innerHTML, /200 次/);
  }
  assert.equal(run('annualItem'), 'Other');
  assert.equal(run('researchItem'), 'Other');
  assert.equal(run('networkItem'), 'Other');
  assert.equal(run("usageOrder(['Missing','Other','Target']).join('|')"), 'Target|Other|Missing');
  assert.equal(run("usageLabel('Missing')"), 'Missing · 总次数未公开');
  run("research.usage.push({item_name:'Invalid',total_usage_visits:''})");
  assert.equal(run("usageCount('Invalid')"), null);
});

test('network shows only selected strict-group edges and links to matching table rows', () => {
  const { element, run } = setup();
  run(`research.nodes = [{ group:'ra_strict', item_name:'Center', patients:'20', node_prevalence_threshold:'.2', edge_cosine_threshold:'.5' }];
    research.edges = [{ group:'ra_strict', item_1:'Center', item_2:'<Peer>', cosine_similarity:'.8', cooccurrence_patients:'10', support:'.5' },
      { group:'sjd_strict', item_1:'Center', item_2:'Other cohort', cosine_similarity:'.9' }];
    renderResearchNetwork();`);
  assert.match(element('network-graph').innerHTML, /&lt;Peer&gt;/);
  assert.match(element('network-graph').innerHTML, /href="#network-edge-0"/);
  assert.match(element('network-edges').innerHTML, /id="network-edge-0"/);
  assert.doesNotMatch(element('network-edges').innerHTML, /Other cohort/);
  element('strict-group').listeners.change({ target: { value:'sjd_strict' } });
  assert.doesNotMatch(element('network-graph').innerHTML, /<svg/);
});

test('annual handoff retains a research item with no disclosed annual rows', () => {
  const { element, run } = setup();
  run("annualItem='NoAnnualRecords';renderAnnual()");
  assert.equal(run('annualItem'), 'NoAnnualRecords');
  assert.match(element('annual-item').innerHTML, /NoAnnualRecords/);
  assert.doesNotMatch(element('annual-chart').innerHTML, /<svg/);
});

test('strict-only fallback summary retains its public patient count', () => {
  const { run } = setup();
  run("data.clinicalMode=false;data.summaries=[{group:'ra',patients:'20'}]");
  assert.equal(run('currentSummary().patients'), '20');
});

test('annual SVG export retains metric, scope, styles, geometry and source provenance', async () => {
  const { element, run, downloads } = setup();
  run("annualItem='Target';annualMetric='prevalence';renderAnnual()");
  assert.equal(element('export-annual-svg').disabled, false);
  element('export-annual-svg').listeners.click();
  const svg = await downloads[0].blob.text();
  assert.equal(downloads[0].name, 'mingyirx-annual-ra-Target.svg');
  assert.match(svg, /xmlns="http:\/\/www.w3.org\/2000\/svg"/);
  assert.match(svg, /class="annual-point prevalence"/);
  assert.match(svg, /\.annual-line.prevalence\{stroke:var\(--blue\)\}/);
  assert.match(svg, /&quot;dataset_id&quot;:&quot;synthetic-v1&quot;/);
  assert.match(svg, /&quot;stratum_type&quot;:&quot;overall&quot;/);
  assert.match(element('annual-export-status').textContent, /mingyirx-annual-ra-Target.svg/);
  if (process.argv[3]) fs.writeFileSync(`${process.argv[3]}/annual.svg`, svg);
  element('addition').listeners.click();
  assert.equal(element('export-annual-svg').disabled, true);
  element('export-annual-svg').listeners.click();
  assert.equal(downloads.length, 1);
});

test('annual endpoint labels stay inside the plot for multiple and single years', async () => {
  const { element, run, downloads } = setup();
  run("annualItem='Target';data.yearItems.forEach(row=>Object.assign(row,{dose_patients:'20',most_common_dose_patients:'10',most_common_dose_values_g:'10;15',most_common_dose_fraction:'.5',most_common_dose_tied:'True'}));renderAnnual()");
  const plot=element('annual-chart').innerHTML;
  assert.match(plot, /class="annual-year-label" x="58"[^>]*text-anchor="start"/);
  assert.match(plot, /class="annual-dose-label" x="656"[^>]*text-anchor="end"/);
  assert.match(plot, /class="annual-n-label" x="656"[^>]*text-anchor="end"/);
  element('export-annual-svg').listeners.click();
  assert.match(await downloads[0].blob.text(), /class="annual-dose-label" x="656"[^>]*text-anchor="end"/);
  run("data.yearSummaries=data.yearSummaries.filter(row=>row.year==='2022');renderAnnual()");
  assert.match(element('annual-chart').innerHTML, /class="annual-dose-label" x="58"[^>]*text-anchor="start"/);
});

test('network SVG isolates strict cohort, strips dashboard links and wraps long labels', async () => {
  const { element, run, downloads } = setup();
  run(`research.nodes=[{group:'ra_strict',item_name:'A & <B>',patients:'20',node_prevalence_threshold:'.2',edge_cosine_threshold:'.5'}];
    research.edges=[{group:'ra_strict',item_1:'A & <B>',item_2:'Peer',cosine_similarity:'.7'}];
    renderResearchNetwork();selected='other_clinical_group';stratumType='sex';stratum='female';`);
  assert.equal(element('export-network-svg').disabled, false);
  element('export-network-svg').listeners.click();
  const svg = await downloads[0].blob.text();
  assert.match(svg, /A &amp; &lt;B&gt;/);
  assert.doesNotMatch(svg, /href=|<script|other_clinical_group/);
  assert.match(svg, /&quot;group&quot;:&quot;ra_strict&quot;/);
  assert.match(svg, /&quot;stratum_type&quot;:&quot;overall&quot;/);
  assert.match(svg, /&quot;displayed_edges&quot;/);
  assert.equal(run("figureLines('Long text '.repeat(100),30).every(line=>line.length<=30)"), true);
  assert.equal(run("figureLines('Very long title '.repeat(100),30).join('')"), 'Very long title '.repeat(100));
  if (process.argv[3]) fs.writeFileSync(`${process.argv[3]}/network.svg`, svg);
  element('strict-group').listeners.change({target:{value:'sjd_strict'}});
  assert.equal(element('export-network-svg').disabled, true);
});
