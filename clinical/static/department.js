/* Domain views reuse the clinical session, request errors and safe text renderer. */
(() => {
  let epoch = 0;
  let fullContainer = null;
  const initial = () => ({question:'',disease:'all',source:'',search:'',catalog:null,answer:null,
    text:'',origin:'synthetic',records:[],excluded:new Set(),confirmed:false,result:null,recognition:null,revision:0,answerQuestion:''});
  let state = initial();
  const controllers = new Set();
  const labels = {subject_code:'患者代号',episode_code:'就诊阶段代号',physician_code:'医生代号',visit_code:'访次代号',
    date:'就诊日期',sequence:'同日顺序',condition:'病种标签',symptoms:'症状',tongue:'舌象',pulse:'脉象',
    syndrome:'证候',principle:'治法',prescription:'处方原文'};
  const statusLabels = {insufficient:'现有全文依据不足，未生成回答。请核对病种、标准年份或所选文献。',
    busy:'本地模型正在处理其他问题，请稍后再试。',model_unavailable:'本地模型暂不可用，请稍后重试。',
    source_unavailable:'来源校验未通过，请联系本机维护人员核对资料。',invalid_model_output:'本次回答未通过原文校验，请换一种问法或查阅来源。'};
  function loading(el,text,variant) {
    const box=el('div',null,'skeleton skeleton-'+variant);box.setAttribute('role','status');box.setAttribute('aria-live','polite');box.setAttribute('aria-busy','true');
    box.append(el('p',text,'skeleton-label'));
    const bar=classes=>{const item=el('span',null,'skeleton-bar '+classes);item.setAttribute('aria-hidden','true');return item;};
    if(variant==='split') {
      const left=el('div',null,'skeleton-col'),right=el('div',null,'skeleton-col');
      left.append(bar('w-40'),bar('w-100 h-block'),bar('w-30'),bar('w-100 h-lg'),bar('w-100 h-lg'),bar('w-90'),bar('w-80'),bar('w-90'));
      right.append(bar('w-30 h-lg'),bar('w-100 h-block'));box.append(left,right);
    } else if(variant==='frame') box.append(bar('w-40 h-lg'),bar('w-60'),bar('w-100 h-frame'));
    else box.append(bar('w-40 h-lg'),bar('w-100'),bar('w-100 h-block'),bar('w-30 h-lg'));
    return box;
  }
  function clear() { epoch++; for(const item of controllers)item.abort();controllers.clear();state=initial();if(fullContainer){fullContainer.replaceChildren();fullContainer.hidden=true;fullContainer=null;} }
  function button(el,text,handler,cls='secondary') {const item=el('button',text,cls);item.type='button';item.onclick=handler;return item;}
  function field(el,text,control) {const item=el('label');item.append(el('span',text),control);return item;}
  function details(el,title,text) {const item=el('details');item.append(el('summary',title),el('pre',typeof text==='string'?text:JSON.stringify(text,null,2)));return item;}
  function tag(el,text,warning=false) {return el('span',text,'department-tag'+(warning?' warning':''));}
  function sourceLink(el,url,text='查看来源全文') {
    if(typeof url!=='string'||!/^\/api\/department\/knowledge\/(page|section)\/[A-Za-z0-9_-]+$/.test(url))return el('span','来源定位暂不可用');
    const a=el('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;
  }
  async function request(ctx,path,body) {
    const controller=new AbortController();controllers.add(controller);
    try {return await ctx.api('department/'+path,body,controller.signal);}finally{controllers.delete(controller);}
  }
  function renderAnswer(target,ctx) {
    const {el}=ctx,answer=state.answer;target.replaceChildren();
    if(!answer) {target.append(el('div','选择病种和文献范围，输入问题后在这里阅读回答与原文依据。','department-empty'));return;}
    const synthetic=answer.data_origin==='synthetic';
    target.append(tag(el,synthetic?'合成示例 · 非医学证据':'公共文献问答'),tag(el,synthetic?'未调用模型':'临床审核待完成',true));
    if(state.answerQuestion)target.append(el('p',state.answerQuestion,'department-help'));
    if(answer.answer_scope==='classification_criteria')target.append(el('p','以下为研究分类标准；临床诊断需结合具体病情判断。','department-help'));
    if(!(answer.extracts||[]).length)target.append(el('p',synthetic?'合成演示只回答页面给出的固定示例问题；其他问题不生成医学回答。':statusLabels[answer.status]||'本次未得到可展示的中文回答。','department-empty'));
    for(const item of answer.extracts||[]) {
      const article=el('article',null,'department-answer');article.append(el('h3',item.title_zh||item.title));
      article.append(el('div',item.answer_zh||'中文转换未通过校验，请查阅原文依据。','department-prose'));
      const meta=el('p',null,'department-help');meta.textContent=[item.pmid?'PMID '+item.pmid:null,item.doi?'DOI '+item.doi:null].filter(Boolean).join(' · ');article.append(meta);
      const quote=el('details');quote.append(el('summary','核对原文、出处与翻译状态'),el('blockquote',item.quote),sourceLink(el,item.page_url,synthetic?'查看合成出处':'查看来源全文'),
        el('p',item.translation_status==='versioned_translation'?'版本化中文译文 · AI 翻译 · 待临床人工审核。':'来源摘录与中文显示保留独立核查状态。','department-help'),
        details(el,'来源记录',{quote_sha256:item.quote_sha256,translation_status:item.translation_status,translation_origin:item.translation_origin,translation_review_status:item.translation_review_status,translation_artifact_sha256:item.translation_artifact_sha256,translation_bundle_sha256:item.translation_bundle_sha256,translation_checks:item.translation_checks,locator:item.locator}));
      article.append(quote);target.append(article);
    }
    target.append(el('p','原文定位与结论支持分别核对；回答完整性及临床适用性保留人工判断。','department-help'));
  }
  async function knowledge(box,ctx) {
    const {el,error,isCurrent}=ctx;
    if(!state.catalog)state.catalog=await request(ctx,'knowledge/catalog');
    if(!isCurrent())return;
    const synthetic=state.catalog.data_origin==='synthetic';
    const grid=el('div',null,'department-grid'), left=el('section'),right=el('section');
    const form=el('form'), question=el('textarea');question.id='department_question';question.maxLength=1000;question.required=true;question.value=state.question;
    question.placeholder=synthetic?state.catalog.example_question:'例如：2016年干燥综合征分类标准是什么？';question.oninput=()=>{state.question=question.value;};
    const disease=el('select');disease.id='department_disease';for(const [value,label] of [['all','全部病种'],['sjd','干燥综合征'],['ra','类风湿关节炎'],['gout','痛风']]) {const o=el('option',label);o.value=value;disease.append(o);}disease.value=state.disease;
    const search=el('input');search.type='search';search.id='department_source_search';search.value=state.search;search.placeholder='标题、PMID 或 DOI';
    const selected=el('p',null,'department-help'),sources=el('div',null,'department-source-list');sources.setAttribute('aria-label','文献范围');
    const count=el('p',null,'department-help');
    function fillSources() {
      const all=state.catalog.sources||[],query=state.search.trim().toLowerCase();
      const matches=all.filter(s=>(state.disease==='all'||s.disease===state.disease)&&(!query||[s.title,s.title_zh,s.pmid,s.doi].join(' ').toLowerCase().includes(query)));
      selected.textContent=synthetic?'当前范围：合成软件示例':state.source?'当前范围：'+(all.find(s=>s.id===state.source)?.title_zh||all.find(s=>s.id===state.source)?.title||state.source):'当前范围：所选病种的全部可检索全文';
      count.textContent=synthetic?'合成软件示例 '+all.length+' 条 · 不包含临床文献':'已接入 '+all.length+' 篇全文 · 匹配 '+matches.length+' 篇'+(matches.length>30?'，显示前 30 篇，请继续缩小搜索':'');
      sources.replaceChildren();
      const auto=button(el,synthetic?'使用合成软件示例':'在全部可检索全文中查找',()=>{state.source='';fillSources();},'department-source');auto.setAttribute('aria-pressed',String(!state.source));sources.append(auto);
      for(const source of matches.slice(0,30)) {
        const b=button(el,source.title_zh||source.title,()=>{state.source=source.id;fillSources();},'department-source');b.setAttribute('aria-pressed',String(state.source===source.id));
        b.append(el('small',[source.year,source.pmid?'PMID '+source.pmid:'',synthetic?'固定合成示例':source.retrieval_eligible?'可检索':'仅阅读'].filter(Boolean).join(' · ')));sources.append(b);
      }
    }
    search.oninput=()=>{state.search=search.value;fillSources();};disease.onchange=()=>{state.disease=disease.value;state.source='';fillSources();};
    const submit=el('button','查找依据并回答','primary');submit.type='submit';submit.id='department_ask';
    const feedback=el('div');feedback.setAttribute('role','status');feedback.setAttribute('aria-live','polite');
    form.append(field(el,synthetic?'合成示例问题':'公共文献问题',question),field(el,'病种范围',disease),submit,feedback);
    if(synthetic){form.prepend(el('p','当前为合成软件演示，无医学文献、无模型推理。仅示例问题返回固定的合成出处。','department-help'));form.append(button(el,'填入合成示例问题',()=>{question.value=state.catalog.example_question;state.question=question.value;}));}
    left.append(form,el('p','仅输入通用医学问题。患者档案不会自动带入问答。','department-help'),el('h3','文献范围'),field(el,'搜索本地全文库',search),selected,count,sources);
    right.append(el('h2','回答与依据'));const answer=el('div');right.append(answer);renderAnswer(answer,ctx);
    form.onsubmit=async event=> {
      event.preventDefault();const token=epoch,asked=question.value.trim();submit.disabled=true;submit.textContent=synthetic?'正在读取合成示例…':'正在查阅全文…';feedback.replaceChildren(el('p',synthetic?'正在核对合成示例的来源摘要；未调用模型。':'本地模型正在选择证据，请稍候。','department-help'));
      try {
        const result=await request(ctx,'knowledge/extract',{question:asked,disease:state.disease,source_id:state.source||'all',index_sha256:state.catalog.index_sha256});
        if(token!==epoch||!isCurrent())return;state.answer=result;state.answerQuestion=asked;renderAnswer(answer,ctx);feedback.replaceChildren();
      }catch(exc){if(token===epoch&&isCurrent())error(feedback,exc);}
      finally{if(token===epoch&&isCurrent()){submit.disabled=false;submit.textContent='查找依据并回答';}}
    };
    fillSources();grid.append(left,right);box.replaceChildren(grid);
  }
  function medicineNames(result,codes) {
    const vocabulary=result.vocabulary?.medicines||{};
    return codes.map(code=>Array.isArray(vocabulary)?(vocabulary.find(v=>v.code===code)?.label||code):(vocabulary[code]?.label||vocabulary[code]||code)).join('、')||'无';
  }
  function doseValue(result,pair,visitId,code,fallback) {
    const visit=result.cases?.find(item=>item.case_id===pair.case_id)?.visits?.find(item=>item.visit_id===visitId);
    const medicine=visit?.prescription?.find(item=>item.medicine_code===code);
    const value=medicine?.dose??fallback;
    return value==null?'缺失':String(value)+(medicine?.unit?' '+medicine.unit:'（单位待核对）');
  }
  function renderAnalysisResult(target,ctx) {
    const {el}=ctx,result=state.result;target.replaceChildren();if(!result)return;
    target.append(el('h2','相邻访次对照'),tag(el,state.origin==='synthetic'?'合成演示资料':'操作者声明的脱敏资料'),tag(el,'描述性分析',true));
    if(result.gate==='BLOCK') {target.append(el('p','当前资料存在冲突或缺项，修正后再分析。','department-danger'),details(el,'查看需要修正的字段',result.errors));return;}
    const metrics=el('div',null,'department-metrics');
    for(const [key,title] of [['visits','访次'],['eligible_pairs','可比较访次对'],['unresolved_pairs','顺序待核对']]) {const n=el('div');n.append(el('strong',String(result.counts?.[key]??result.view?.readiness?.[key]??0)),el('span',title));metrics.append(n);}target.append(metrics);
    for(const pair of result.pairs||[]) {
      const card=el('article',null,'department-pair');card.append(el('h3',pair.from_visit_id+' → '+pair.to_visit_id),el('p','间隔 '+pair.interval_days+' 天 · '+(pair.status==='eligible'?'顺序可比较':'同日顺序待核对'),'department-help'));
      if(pair.status!=='eligible'){card.append(el('p','补充明确的访次先后依据后，再解释本组处方变化。'));target.append(card);continue;}
      card.append(el('p','新增：'+medicineNames(result,pair.added)),el('p','去除：'+medicineNames(result,pair.removed)),el('p','保留：'+medicineNames(result,pair.retained)));
      if(pair.dose_changes?.length) {
        const table=el('table',null,'department-table'),head=el('tr');for(const title of ['药味','前次','本次','比较状态'])head.append(el('th',title));const thead=el('thead');thead.append(head);table.append(thead);const tbody=el('tbody');
        for(const dose of pair.dose_changes){const tr=el('tr');for(const value of [medicineNames(result,[dose.medicine_code]),doseValue(result,pair,pair.from_visit_id,dose.medicine_code,dose.before),doseValue(result,pair,pair.to_visit_id,dose.medicine_code,dose.after),dose.direction==='unresolved'?'剂量基准待核对':({increased:'增加',decreased:'减少',unchanged:'相同'}[dose.direction]||dose.direction)])tr.append(el('td',String(value)));tbody.append(tr);}table.append(tbody);const wrap=el('div',null,'department-scroll');wrap.append(table);card.append(wrap);
      }
      target.append(card);
    }
    target.append(el('p','分析描述处方及访次变化。医师归属、疗效与处方合理性保留独立评价。当前结果仅保留在本次登录的页面内。','department-help'));
    if(result.warnings?.length)target.append(details(el,'资料提示',result.warnings));
    target.append(details(el,'分析来源与可用状态',{gate:result.gate,data_origin:result.data_origin,provenance:result.provenance,readiness:result.view?.readiness}));
  }
  async function analysis(box,ctx) {
    const {el,error,isCurrent}=ctx,token=epoch;
    const toolbar=el('div',null,'department-toolbar'), origin=el('select');origin.id='department_origin';
    for(const [value,title] of [['synthetic','合成演示资料'],['deidentified','已获授权的脱敏资料']]){const o=el('option',title);o.value=value;origin.append(o);}origin.value=state.origin;
    const text=el('textarea');text.id='department_case_text';text.value=state.text;text.maxLength=100000;text.placeholder='粘贴包含患者代号、访次、日期和处方的医案文字，或加载合成样例。';text.oninput=()=>{state.text=text.value;state.records=[];state.recognition=null;changed();renderCandidates();};
    const file=el('input');file.type='file';file.accept='.txt,.csv,.json';file.id='department_case_file';
    const feedback=el('div');feedback.setAttribute('role','status');
    const candidates=el('div'),result=el('section');result.id='department_analysis_result';
    const confirm=el('input');confirm.type='checkbox';confirm.id='department_review_confirm';confirm.checked=state.confirmed;
    const analyze=button(el,'分析已核对的访次',async()=>{
      const revision=state.revision;analyze.disabled=true;feedback.replaceChildren(el('p','正在计算相邻访次…','department-help'));
      try {const response=await request(ctx,'analysis/preview',{records:state.records.filter((_,i)=>!state.excluded.has(i)),data_origin:state.origin,review_confirmed:confirm.checked});if(token!==epoch||!isCurrent()||revision!==state.revision)return;state.result=response;renderAnalysisResult(result,ctx);feedback.replaceChildren();result.scrollIntoView({block:'start',behavior:'smooth'});}
      catch(exc){if(token===epoch&&isCurrent())error(feedback,exc);}finally{if(token===epoch&&isCurrent())updateAction();}
    },'primary');analyze.id='department_analyze';
    function updateAction(){analyze.disabled=!state.confirmed||!state.records.some((_,i)=>!state.excluded.has(i));}
    function changed(){state.revision++;state.confirmed=false;confirm.checked=false;state.result=null;result.replaceChildren();feedback.replaceChildren();updateAction();}
    function install(value){state.records=value.records||[];state.recognition=value;state.excluded=new Set();changed();renderCandidates();}
    function renderCandidates(){
      candidates.replaceChildren();if(!state.records.length){candidates.append(el('p','识别资料后，在这里逐项核对患者代号、日期、症状与处方。','department-empty'));return;}
      candidates.append(el('h3','核对候选资料 · '+state.records.length+' 条'));
      for(const [i,record] of state.records.entries()) {
        const section=el('details',null,'department-review');section.open=i===0;section.append(el('summary','访次 '+(i+1)+' · '+record.subject_code+' · '+(record.date||'日期待补充')));
        const use=el('input');use.type='checkbox';use.checked=!state.excluded.has(i);const useLabel=field(el,'纳入本次分析',use);useLabel.className='department-check';section.append(useLabel);use.onchange=()=>{if(use.checked)state.excluded.delete(i);else state.excluded.add(i);changed();};
        const fields=el('div',null,'department-fields');
        for(const [key,title] of Object.entries(labels)){
          const control=el(['symptoms','tongue','pulse','syndrome','principle','prescription'].includes(key)?'textarea':'input');control.id='department_record_'+i+'_'+key;
          if(key==='date')control.type='date';if(key==='sequence'){control.type='number';control.min='0';control.step='1';}
          control.value=record[key]??'';control.oninput=()=>{record[key]=key==='sequence'?(control.value===''?null:Number(control.value)):control.value;changed();};fields.append(field(el,title,control));
        }
        section.append(fields,details(el,'原文定位与来源摘要',{source_sha256:record.source_sha256,evidence:record.evidence}));candidates.append(section);
      }
      if(state.recognition?.warnings?.length)candidates.append(details(el,'识别提示',state.recognition.warnings));updateAction();
    }
    const example=button(el,'加载合成样例',async()=>{changed();const revision=state.revision;example.disabled=true;try{const value=await request(ctx,'analysis/example');if(token!==epoch||!isCurrent()||revision!==state.revision)return;state.origin='synthetic';origin.value=state.origin;state.text=value.text;text.value=state.text;install(value);feedback.replaceChildren();}catch(exc){if(token===epoch&&isCurrent()&&revision===state.revision)error(feedback,exc);}finally{example.disabled=false;}});example.id='department_example';
    const recognize=button(el,'识别并核对资料',async()=>{changed();const revision=state.revision,submittedOrigin=state.origin;recognize.disabled=true;feedback.replaceChildren();try{const value=await request(ctx,'analysis/recognize',{text:text.value,data_origin:submittedOrigin});if(token!==epoch||!isCurrent()||revision!==state.revision||value.data_origin!==submittedOrigin)return;install(value);}catch(exc){if(token===epoch&&isCurrent()&&revision===state.revision)error(feedback,exc);}finally{recognize.disabled=false;}});recognize.id='department_recognize';
    origin.onchange=()=>{state.origin=origin.value;state.records=[];state.recognition=null;changed();renderCandidates();};
    file.onchange=async()=>{
      const chosen=file.files?.[0];if(!chosen)return;changed();const revision=state.revision;
      if(chosen.size>200000){feedback.replaceChildren(el('p','文件超过 200 KB，请拆分后导入。','department-danger'));return;}
      try{
        const bytes=await chosen.arrayBuffer();let value,encoding='UTF-8';
        try{value=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}
        catch{encoding='GB18030';value=new TextDecoder('gb18030',{fatal:true}).decode(bytes);}
        if(token!==epoch||!isCurrent()||revision!==state.revision)return;
        state.text=value;text.value=value;state.records=[];state.recognition=null;changed();renderCandidates();
        feedback.append(el('p','已按 '+encoding+' 解码。请核对文字；来源摘要按解码后的 UTF-8 文字计算。','department-help'));
      }catch{if(token===epoch&&isCurrent()&&revision===state.revision)feedback.append(el('p','文件无法按 UTF-8 或 GB18030 完整解码，请检查编码后重试。','department-danger'));}
    };
    confirm.onchange=()=>{state.confirmed=confirm.checked;updateAction();};
    toolbar.append(field(el,'资料来源',origin),example);
    const check=field(el,'我已核对拟纳入的患者与访次、原文和处方，并确认资料可用于本次本地分析。',confirm);check.className='department-check';
    box.replaceChildren(el('h2','医案资料与相邻处方'),el('p','沿用 MingYiRx 的访次、药味和剂量规则。相同代号才建立关联，同日顺序不明时保留待核对状态。','department-help'),toolbar,field(el,'选择本地文本、CSV 或 JSON',file),field(el,'医案文字',text),recognize,feedback,candidates,check,analyze,result);
    renderCandidates();renderAnalysisResult(result,ctx);updateAction();
  }
  async function render(which,box,ctx) {
    box.classList.add('department');box.replaceChildren(loading(ctx.el,which==='knowledge'?'正在载入本地全文索引。首次打开需要较长时间，请稍候。':'正在读取科室工具…',which==='knowledge'?'split':'list'));
    try {if(which==='knowledge')await knowledge(box,ctx);else await analysis(box,ctx);}catch(exc){if(ctx.isCurrent()){box.replaceChildren();ctx.error(box,exc);box.append(button(ctx.el,'重新读取',()=>render(which,box,ctx)));}}
  }
  async function renderFull(box,ctx) {
    if(box.querySelector('#department_rx_frame'))return;
    const {el}=ctx,token=epoch;fullContainer=box;
    box.replaceChildren(loading(el,'正在连接原处方分析工作区…','frame'));
    try {
      const status=await request(ctx,'mingyirx/status');
      if(token!==epoch||!ctx.isCurrent())return;
      const controls=el('div',null,'department-full-toolbar');
      const standalone=el('a','在独立窗口展开');standalone.id='department_rx_open';standalone.href='/api/department/mingyirx/site/index.html';standalone.target='_blank';standalone.rel='noopener';
      const quick=el('a','快速访次核对');quick.href='#analysis-quick';
      controls.append(el('strong','MingYiRx 完整处方工作区'),standalone,quick);
      const reports=el('details',null,'department-full-reports');reports.append(el('summary','研究报告与下载'));
      const reportLinks=el('div');
      for(const [name,label] of [['research-report.html','文献研究报告'],['supplement.html','补充来源与汇总'],['analysis-report.md','分析报告（Markdown）'],['conditional_retention.csv','条件性保留率'],['disease-change-results.csv','病种与处方变化结果'],['literature-analysis-results.csv','文献分析结果'],['source-ledger.json','来源台账'],['source-correction.json','来源更正记录'],['teaching-provenance.json','教学资料来源']]) {
        if(!(status.static_assets||[]).includes(name))continue;
        const link=el('a',label);link.href='/api/department/mingyirx/site/'+name;link.target='_blank';link.rel='noopener';if(!name.endsWith('.html'))link.download=name;reportLinks.append(link);
      }
      reports.append(reportLinks);controls.append(reports);
      const note=el('p','沿用原处方网页及页内来源标记。导入后经核对保存为版本集合；切换科室模块会保留当前页面。临床工作台演示状态不改变本页资料来源。','department-help');
      if(status.collection_scope==='local_single_operator')note.append(' 当前为本机单操作者集合。');
      const frame=el('iframe');frame.id='department_rx_frame';frame.title='MingYiRx 原处方分析、医案传承与导入工作区';frame.src=standalone.href;
      box.replaceChildren(controls,note,frame);
    }catch(exc){if(token===epoch&&ctx.isCurrent()){box.replaceChildren();ctx.error(box,exc);box.append(button(el,'重新连接原工作区',()=>renderFull(box,ctx)));}}
  }
  window.Department=Object.freeze({render,renderFull,clear});
})();
