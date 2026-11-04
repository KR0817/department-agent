/* Domain views reuse the clinical session, request errors and safe text renderer. */
(() => {
  let epoch = 0;
  let fullContainer = null;
  let collapseCanvas = null;
  let knowledgeView = 0;
  const initial = () => ({question:'',disease:'all',source:'',search:'',catalog:null,answer:null,
    mode:'literature',subject:'',provider:'local',expertProvider:'local',publicTopic:false,publicEvidence:false,knowledgeRevision:0,collaborative:false,answerReviewed:null,
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
  function clear() { epoch++; for(const item of controllers)item.abort();controllers.clear();state=initial();if(collapseCanvas){collapseCanvas();collapseCanvas=null;}if(fullContainer){fullContainer.replaceChildren();fullContainer.hidden=true;fullContainer=null;} }
  function button(el,text,handler,cls='secondary') {const item=el('button',text,cls);item.type='button';item.onclick=handler;return item;}
  function field(el,text,control) {const item=el('label');item.append(el('span',text),control);return item;}
  function details(el,title,text) {const item=el('details');item.append(el('summary',title),el('pre',typeof text==='string'?text:JSON.stringify(text,null,2)));return item;}
  function tag(el,text,warning=false) {return el('span',text,'department-tag'+(warning?' warning':''));}
  function sourceLink(el,url,text='查看来源全文') {
    if(typeof url!=='string'||!/^\/api\/department\/knowledge\/(page|section)\/[A-Za-z0-9_-]+$/.test(url))return el('span','来源定位暂不可用');
    const a=el('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;
  }
  async function request(ctx,path,body,controller=new AbortController()) {
    controllers.add(controller);
    try {return await ctx.api('department/'+path,body,controller.signal);}finally{controllers.delete(controller);}
  }
  function pollDelay(signal) {
    return new Promise((resolve,reject)=>{
      if(signal.aborted){reject(new DOMException('Aborted','AbortError'));return;}
      const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
      const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},1200);
      signal.addEventListener('abort',abort,{once:true});
    });
  }
  const expertLabels={tcm:'中医知识',evidence:'文献证据',pharmacy:'药学安全',synthesis:'汇总'};
  const expertStatuses={pending:'等待中',running:'处理中',completed:'已完成',insufficient:'依据不足',failed:'未完成',skipped:'已跳过'};
  function expertModel(info){return info?' · '+(info.provider==='kimi'?'Kimi API':'本地')+' / '+info.model:'';}
  function renderExperts(target,ctx,answer) {
    const {el}=ctx;
    target.append(tag(el,answer.execution==='all_kimi'?'专家协作 · 全部 Kimi 3.1 · 试用':answer.provider==='kimi'?'专家协作 · 本地 + Kimi · 试用':'专家协作 · 本地试用'),el('h3',answer.subject||'本次协作'));
    if(state.answerQuestion)target.append(el('p',state.answerQuestion,'department-question-card'));
    const statuses={completed:'各角色处理完成，等待人工核对。',partial:'部分角色未完成，以下仅展示已通过格式与来源检查的结果。',
      insufficient:'本轮信息不足，请调整问题或补充来源。',failed:'本轮协作未完成，请核对模型调用状态后重试。',cancelled:'已停止后续协作。',
      model_unavailable:'所选模型尚未配置或配置无效，请由管理员核对。',
      public_evidence_required:'全部 Kimi 模式需要确认发送选中的公开文献片段和角色报告。',
      source_unavailable:'原文校验未通过，本轮生成内容已撤回。',busy:'本地模型正在处理其他任务，请稍后再试。',
      model_disabled:'连接本地全文库后可使用专家协作。',public_topic_required:'请输入通用知识问题，移除身份标识和病例资料。',
      needs_clinician:'个体处方与用药调整请由接诊医师结合完整资料评估。',urgent_care:'误服、过量服药或严重不适请立即就医，不要等待本页回答。'};
    target.append(el('p',statuses[answer.status]||'本次未取得完整结果。','department-help'));
    if(answer.model_calls?.length){
      const calls=el('ul',null,'department-expert-progress');
      const errors={api_authentication_failed:'API 身份验证失败',api_quota_exceeded:'API 额度不足',api_rate_limited:'API 限流',api_timeout:'API 超时',api_key_missing:'API 密钥未配置',api_invalid_response:'API 输出不完整',api_request_failed:'API 请求失败',api_response_limit:'API 响应超限',public_materials_required:'含身份标记，已阻止发送'};
      for(const role of Object.keys(expertLabels)){
        const call=answer.model_calls.find(item=>item.role===role),info=answer.role_models?.[role];
        calls.append(el('li',expertLabels[role]+expertModel(info)+'：'+(expertStatuses[answer.roles?.[role]]||'未完成')+
          (call?.provider_error?'（'+(errors[call.provider_error]||'API 调用失败')+'）':call?.error==='invalid_output'?'（输出检查未通过）':call?.error==='transport_unavailable'?'（模型连接失败）':'')));
      }target.append(calls);
    }
    if(!answer.reports||!Object.keys(answer.reports).length)return;
    target.append(el('p',(answer.execution==='all_kimi'?'四个角色均使用 Kimi 3.1。已发送本次通用问题、选中的公开文献片段及角色报告；原文检索和核对在本机完成。':answer.provider==='kimi'?'Kimi 处理通用知识，本地模型处理文献、药学审查和汇总。仅本次名称和通用问题发送至 API。':'同一模型按不同职责协作。')+'意见一致不等于独立验证。文献引用已核对片段身份，结论支持程度仍待人工核对。','department-help'));
    if(answer.retrieval_budget?.omitted_for_public_scope)target.append(el('p','另有 '+answer.retrieval_budget.omitted_for_public_scope+' 个片段因缺少公开文献标识或含身份标记，未发送至 API。','department-help'));
    if(answer.retrieval_budget?.omitted_for_budget)target.append(el('p','本轮仅纳入适合本机处理的完整片段，另有 '+answer.retrieval_budget.omitted_for_budget+' 个候选片段超出预算；可缩小文献范围再查。','department-help'));
    const allClaims=Object.values(answer.reports).flatMap(report=>report.claims||[]);
    if(answer.synthesis){
      const summary=el('article',null,'department-answer');summary.append(el('h3','汇总意见'),el('p',answer.synthesis.overview,'department-prose'));
      const selected=el('ul');for(const id of answer.synthesis.selected_claim_ids||[]){const claim=allClaims.find(row=>row.id===id);if(claim)selected.append(el('li',claim.text+' ['+id+']'));}summary.append(selected);
      for(const issue of answer.synthesis.unresolved||[])summary.append(el('p','待解决：'+issue,'department-help'));target.append(summary);
    }
    const concerns=answer.reports.pharmacy?.concerns||[];
    const caution=el('section',null,'department-evidence-card');caution.append(el('h3','药学审查与分歧'));
    caution.append(el('p','当前资料库尚未覆盖完整药品说明书和相互作用数据库；未发现问题不代表已确认安全。','department-help'));
    for(const concern of concerns)caution.append(el('p',concern.text+(concern.claim_ids?.length?' ['+concern.claim_ids.join(', ')+']':'')));
    if(!concerns.length)caution.append(el('p',answer.roles?.pharmacy==='failed'?'药学角色未完成，风险评估缺失。':'本轮未返回具体审查意见，仍需按原始资料核对。','department-help'));target.append(caution);
    for(const role of ['tcm','evidence','pharmacy']){
      const report=answer.reports[role];if(!report)continue;
      const article=el('details',null,'department-answer');article.open=true;
      article.append(el('summary',expertLabels[role]+expertModel(answer.role_models?.[role])+' · '+(expertStatuses[answer.roles?.[role]]||'未完成')));
      for(const claim of report.claims||[]){
        article.append(el('p',claim.text,'department-prose'),el('p',claim.id+' · '+(claim.basis==='source'?'来源引文已逐字匹配 · 支持关系待核对':'模型知识 · 尚无本地引文支持'),'department-help'));
        if(claim.quote){const quote=el('details');quote.append(el('summary','展开完整来源片段'),el('blockquote',claim.quote));article.append(quote);const ref=(answer.references||[]).find(row=>row.id===claim.passage_id);if(ref)article.append(sourceLink(el,ref.page_url,'核对这条原文 ↗'));}
      }
      for(const issue of report.uncertainties||[])article.append(el('p','待核对：'+issue,'department-help'));
      if(report.status==='failed')article.append(el('p','未取得通过检查的输出，未以其他角色结果补充。','department-help'));target.append(article);
    }
    if(answer.references?.length){
      const refs=el('details',null,'department-evidence-card');refs.append(el('summary','本地相关文献（'+answer.references.length+'）'));
      for(const ref of answer.references)refs.append(el('h4',ref.title_zh||ref.title),el('blockquote',ref.quote),sourceLink(el,ref.page_url));target.append(refs);
    }
    const review=el('input');review.type='checkbox';review.id='department_expert_review';review.checked=Boolean(state.answerReviewed);
    review.onchange=()=>{state.answerReviewed=review.checked?new Date().toISOString():null;};
    const reviewField=field(el,'我已阅读并核对本次结果（仅记录人工核对状态，不授予临床审批）。',review);reviewField.className='department-check';target.append(reviewField);
    target.append(button(el,'下载本次协作记录',()=>{
      const record={result:answer,question:state.answerQuestion,user_review:{reviewed_at:state.answerReviewed,clinical_approval:null}};
      const url=URL.createObjectURL(new Blob([JSON.stringify(record,null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download='expert-review-'+answer.result_sha256?.slice(0,12)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }));
    target.append(details(el,'流程与版本记录',{workflow:answer.workflow,trace:answer.trace,model:answer.model,model_calls:answer.model_calls,
      elapsed_seconds:answer.elapsed_seconds,input_sha256:answer.input_sha256,index_sha256:answer.index_sha256,prompt_sha256:answer.prompt_sha256,result_sha256:answer.result_sha256}));
  }
  function renderConsultation(target,ctx,answer) {
    const {el}=ctx;
    const providers={local:'本地模型',deepseek:'DeepSeek API',kimi:'Kimi API'};
    const statuses={
      model_disabled:'当前为合成演示。连接本地全文库后可使用药材与方剂咨询。',
      busy:'模型正在处理其他问题，请稍后再试。',
      model_unavailable:'模型暂不可用，请检查所选服务的配置后重试。',
      invalid_model_output:'回答格式或内容检查未通过，本次未展示生成内容。请调整问题后重试。',
      source_unavailable:'本地来源校验未通过，请核对文献文件。',
      needs_clinician:'本页提供药材与方剂知识查询。个体选方、剂量或用药调整请结合完整病史由接诊医师评估。',
      public_topic_required:'API 咨询仅接收通用问题。请移除姓名、联系方式、证件或病案标识，并确认输入范围。',
      urgent_care:'如已发生误服、过量服药或严重不适，请立即联系当地急救或就近急诊，携带药品包装并说明服用时间；不要等待本页生成用药建议。'
    };
    const errors={api_key_missing:'所选 API 尚未配置服务端密钥，请由管理员配置后重启工作台。',
      invalid_model_configuration:'模型配置无效，请由管理员核对。',api_authentication_failed:'API 身份验证失败，请由管理员核对密钥和权限。',
      api_quota_exceeded:'API 账户额度不足，请核对服务商账户。',api_rate_limited:'API 请求受到限流，请稍后再试。',
      api_timeout:'API 等待超时，尚未取得完整回答。',api_request_failed:'API 请求失败，请核对服务可用性和模型名称。',
      api_invalid_response:'API 未返回完整回答，本次未展示生成内容。',api_response_limit:'API 响应超过时间或大小限制。'};
    target.append(tag(el,answer.kind==='herb'?'药材咨询':'方剂咨询'),tag(el,providers[answer.provider]||'模型咨询'));
    const question=el('div',null,'department-question-card');question.append(el('p',answer.subject||'本次咨询','eyebrow'),el('p',state.answerQuestion));target.append(question);
    if(!['answer','clarify'].includes(answer.status)){
      target.append(el('p',errors[answer.error]||statuses[answer.status]||'本次未得到可展示的回答。','department-empty'));return;
    }
    target.append(el('p',answer.sent_scope==='public_question_only'?'模型知识整理 · API 仅接收本次名称和通用问题。下方文献仅在本机检索，未发送给 API。':answer.evidence_status==='related_passages'?'模型结合本地片段整理；原文关联与结论支持仍需分别核对。':'本地全文库未匹配到相关片段，以下为模型知识整理。','department-help'));
    const headings={identity:'名称与辨别',tradition:answer.kind==='herb'?'药性与传统功效':'组成与方义',uses:'应用与研究',cautions:'禁忌与相互作用',uncertainty:'待核对事项'};
    for(const section of answer.sections||[]){
      const article=el('article',null,'department-answer');article.append(el('h3',headings[section.key]||'咨询内容'),el('div',section.text,'department-prose'));
      for(const id of section.evidence_ids||[]){
        const index=(answer.references||[]).findIndex(item=>item.id===id);if(index<0)continue;
        article.append(button(el,'关联原文片段 '+(index+1),()=>{const ref=target.querySelector('[data-consult-reference="'+index+'"]');ref?.focus();ref?.scrollIntoView({block:'start'});},'text-button'));
      }
      target.append(article);
    }
    if(answer.references?.length){
      target.append(el('h3','本地相关文献'),el('p','片段与名称匹配，支持关系待核对；文献提及药材或方剂不等于证实疗效。','department-help'));
      for(const [index,item] of answer.references.entries()){
        const reference=el('details',null,'department-evidence-card');reference.dataset.consultReference=String(index);reference.tabIndex=-1;
        reference.append(el('summary',(index+1)+' · '+(item.title_zh||item.title)),el('blockquote',item.quote),
          el('p',[item.pmid?'PMID '+item.pmid:'',item.doi?'DOI '+item.doi:''].filter(Boolean).join(' · '),'department-help'),
          sourceLink(el,item.page_url,'阅读原文 ↗'),details(el,'来源记录',{quote_sha256:item.quote_sha256,support_status:item.support_status}));target.append(reference);
      }
    }
    target.append(el('p','供专业知识查阅，内容尚未经临床审核；个体选方与剂量由接诊医师判断。','department-help'));
    if(answer.model)target.append(el('p','模型：'+answer.model+(answer.elapsed_seconds!=null?' · 用时 '+answer.elapsed_seconds+' 秒':''),'department-help'));
  }
  function renderAnswer(target,ctx) {
    const {el}=ctx,answer=state.answer;target.replaceChildren();
    if(!answer) {target.append(el('div','选择病种和文献范围，输入问题后在这里阅读回答与原文依据。','department-empty'));return;}
    if(answer.workflow){renderExperts(target,ctx,answer);return;}
    if(answer.kind){renderConsultation(target,ctx,answer);return;}
    const synthetic=answer.data_origin==='synthetic';
    target.append(tag(el,synthetic?'合成示例 · 非医学证据':'公共文献问答'),tag(el,synthetic?'未调用模型':'临床审核待完成',true));
    if(state.answerQuestion){const question=el('div',null,'department-question-card');question.append(el('p','本次问题','eyebrow'),el('p',state.answerQuestion));target.append(question);}
    if(answer.answer_scope==='classification_criteria')target.append(el('p','以下为研究分类标准；临床诊断需结合具体病情判断。','department-help'));
    if(!(answer.extracts||[]).length)target.append(el('p',synthetic?'合成演示只回答页面给出的固定示例问题；其他问题不生成医学回答。':statusLabels[answer.status]||'本次未得到可展示的中文回答。','department-empty'));
    const extracts=answer.extracts||[];
    if(extracts.length>1){
      const contents=el('nav',null,'department-answer-contents');contents.setAttribute('aria-label','回答段落');
      extracts.forEach((item,index)=>contents.append(button(el,String(index+1)+' · '+(item.title_zh||item.title),()=>{const section=target.querySelector('[data-extract="'+index+'"]');section?.focus();section?.scrollIntoView({block:'start'});},'text-button')));target.append(contents);
    }
    for(const [index,item] of extracts.entries()) {
      const article=el('article',null,'department-answer');article.dataset.extract=String(index);article.tabIndex=-1;
      const heading=el('div',null,'department-answer-heading');heading.append(el('span',String(index+1).padStart(2,'0'),'department-evidence-number'),el('h3',item.title_zh||item.title));article.append(heading);
      article.append(el('div',item.answer_zh||'中文转换未通过校验，请查阅原文依据。','department-prose'));
      const meta=el('p',null,'department-help');meta.textContent=[item.pmid?'PMID '+item.pmid:null,item.doi?'DOI '+item.doi:null].filter(Boolean).join(' · ');article.append(meta);
      const evidence=el('section',null,'department-evidence-card');evidence.setAttribute('aria-label','本段原文依据');
      const evidenceBar=el('div',null,'department-evidence-bar');evidenceBar.append(el('strong','原文依据'));
      // The source endpoint deliberately disallows framing. Retain its protected standalone reader.
      const read=sourceLink(el,item.page_url,synthetic?'阅读合成出处 ↗':'阅读原文 ↗');read.className='department-read-source';evidenceBar.append(read);
      const quote=el('details',null,'department-evidence-quote');quote.open=true;quote.append(el('summary','摘录与翻译状态'),el('blockquote',item.quote),
        el('p',item.translation_status==='versioned_translation'?'版本化中文译文 · AI 翻译 · 待临床人工审核。':'来源摘录与中文显示保留独立核查状态。','department-help'),
        details(el,'来源记录',{quote_sha256:item.quote_sha256,translation_status:item.translation_status,translation_origin:item.translation_origin,translation_review_status:item.translation_review_status,translation_artifact_sha256:item.translation_artifact_sha256,translation_bundle_sha256:item.translation_bundle_sha256,translation_checks:item.translation_checks,locator:item.locator}));
      evidence.append(evidenceBar,quote);article.append(evidence);target.append(article);
    }
    target.append(el('p','原文定位与结论支持分别核对；回答完整性及临床适用性保留人工判断。','department-help'));
  }
  async function knowledge(box,ctx) {
    const {el,error,isCurrent}=ctx,view=++knowledgeView,session=epoch;
    if(!state.catalog){const catalog=await request(ctx,'knowledge/catalog');if(session!==epoch||view!==knowledgeView||!isCurrent())return;state.catalog=catalog;}
    if(!isCurrent())return;
    let active=null,activeJob=null;
    const synthetic=state.catalog.data_origin==='synthetic';
    const grid=el('div',null,'department-grid'), left=el('section',null,'department-query-panel'),right=el('section',null,'department-reading-panel');
    const queryTitle=el('h2','查找有出处的回答');left.append(el('p','本地知识库','eyebrow'),queryTitle);
    const mode=el('select');mode.id='department_mode';
    for(const [value,label] of [['literature','文献问答'],['herb','药材咨询'],['formula','方剂咨询']]){const option=el('option',label);option.value=value;mode.append(option);}mode.value=state.mode;
    const subject=el('input');subject.type='text';subject.id='department_subject';subject.maxLength=80;subject.value=state.subject;
    const subjectField=field(el,'咨询名称',subject);
    const collaboration=el('select');collaboration.id='department_collaboration';
    for(const [value,label] of [['single','单模型咨询'],['experts','专家协作 · 试用']]){const option=el('option',label);option.value=value;collaboration.append(option);}
    collaboration.value=state.collaborative?'experts':'single';const collaborationField=field(el,'处理方式',collaboration);
    const provider=el('select');provider.id='department_provider';
    const providers=state.catalog.consultation?.providers||[];
    for(const [value,label] of [['local','本地模型'],['deepseek','DeepSeek API'],['kimi','Kimi API']]){
      const available=providers.find(item=>item.provider===value),option=el('option',label+(available?.configured?'':' · 未配置'));option.value=value;provider.append(option);
    }provider.value=state.provider;
    const providerField=field(el,'回答模型',provider),modelNote=el('p',null,'department-help');modelNote.id='department_model_status';
    const expertProvider=el('select');expertProvider.id='department_expert_provider';
    for(const [value,label] of [['local','本地模型'],['kimi','本地 + Kimi API'],['kimi_all','全部 Kimi 3.1']]){
      const option=el('option',label);option.value=value;expertProvider.append(option);
    }expertProvider.value=state.expertProvider;
    const expertProviderField=field(el,'协作模型',expertProvider);
    const publicTopic=el('input');publicTopic.type='checkbox';publicTopic.id='department_public_topic';publicTopic.checked=state.publicTopic;
    const publicField=field(el,'本次仅含通用咨询问题，不含患者身份信息或病例资料。',publicTopic);publicField.className='department-check';
    const publicEvidence=el('input');publicEvidence.type='checkbox';publicEvidence.id='department_public_evidence';publicEvidence.checked=state.publicEvidence;
    const evidenceField=field(el,'允许将本轮选中的公开文献片段及角色报告发送给 Kimi；不含私有病例或患者资料。',publicEvidence);evidenceField.className='department-check';
    const form=el('form'), question=el('textarea');question.id='department_question';question.maxLength=1000;question.required=true;question.value=state.question;
    question.placeholder=synthetic?state.catalog.example_question:'例如：2016年干燥综合征分类标准是什么？';question.oninput=()=>{state.question=question.value;invalidate();};
    const disease=el('select');disease.id='department_disease';for(const [value,label] of [['all','全部病种'],['sjd','干燥综合征'],['ra','类风湿关节炎'],['gout','痛风']]) {const o=el('option',label);o.value=value;disease.append(o);}disease.value=state.disease;
    const search=el('input');search.type='search';search.id='department_source_search';search.value=state.search;search.placeholder='标题、PMID 或 DOI';
    const selected=el('p',null,'department-help'),sources=el('div',null,'department-source-list');sources.setAttribute('aria-label','文献范围');
    const count=el('p',null,'department-help');count.setAttribute('role','status');
    function fillSources() {
      const all=state.catalog.sources||[],query=state.search.trim().toLowerCase();
      const matches=all.filter(s=>(state.disease==='all'||s.disease===state.disease)&&(!query||[s.title,s.title_zh,s.pmid,s.doi].join(' ').toLowerCase().includes(query)));
      selected.textContent=synthetic?'当前范围：合成软件示例':state.source?'当前范围：'+(all.find(s=>s.id===state.source)?.title_zh||all.find(s=>s.id===state.source)?.title||state.source):'当前范围：所选病种的全部可检索全文';
      count.textContent=synthetic?'合成软件示例 '+all.length+' 条 · 不包含临床文献':'已接入 '+all.length+' 篇全文 · 匹配 '+matches.length+' 篇'+(matches.length>30?'，显示前 30 篇，请继续缩小搜索':'');
      sources.replaceChildren();
      const auto=button(el,synthetic?'使用合成软件示例':'在全部可检索全文中查找',()=>{state.source='';invalidate();fillSources();},'department-source');auto.setAttribute('aria-pressed',String(!state.source));sources.append(auto);
      for(const source of matches.slice(0,30)) {
        const b=button(el,source.title_zh||source.title,()=>{state.source=source.id;invalidate();fillSources();},'department-source');b.setAttribute('aria-pressed',String(state.source===source.id));
        b.append(el('small',[source.year,source.pmid?'PMID '+source.pmid:'',synthetic?'固定合成示例':source.retrieval_eligible?'可检索':'仅阅读'].filter(Boolean).join(' · ')));sources.append(b);
      }
      if(!matches.length)sources.append(el('p','当前筛选没有匹配文献。请调整病种或搜索词。','department-help'));
    }
    search.oninput=()=>{state.search=search.value;fillSources();};disease.onchange=()=>{state.disease=disease.value;state.source='';invalidate();fillSources();};
    const submit=el('button','查找依据并回答','primary');submit.type='submit';submit.id='department_ask';
    const feedback=el('div');feedback.setAttribute('role','status');feedback.setAttribute('aria-live','polite');
    const cancel=button(el,'停止等待',()=>{invalidate();feedback.replaceChildren(el('p','已停止等待并请求停止后续协作；当前模型调用可能仍在处理，晚到结果不会写入当前页面。','department-help'));});cancel.id='department_cancel';cancel.hidden=true;
    const example=button(el,'填入咨询示例',()=>{invalidate();subject.value=state.mode==='herb'?'黄芪':'桂枝汤';question.value=state.mode==='herb'?'介绍药性、传统功效，以及禁忌和相互作用方面需要核对的事项。':'介绍组成、方义与传统适用证候，以及使用时需要核对的风险。';state.subject=subject.value;state.question=question.value;});example.id='department_consult_example';
    form.append(field(el,'咨询类型',mode),subjectField,collaborationField,providerField,expertProviderField,modelNote,publicField,evidenceField,field(el,synthetic?'合成示例或通用咨询问题':'通用咨询问题',question),example,field(el,'病种范围',disease),submit,cancel,feedback);
    if(synthetic){form.prepend(el('p','当前为合成软件演示，无医学文献、无模型推理。仅示例问题返回固定的合成出处。','department-help'));form.append(button(el,'填入合成示例问题',()=>{invalidate();question.value=state.catalog.example_question;state.question=question.value;}));}
    left.append(form,el('p','仅输入通用医学问题。患者档案不会自动带入问答。','department-help'),el('h3','文献范围'),field(el,'搜索本地全文库',search),selected,count,sources);
    right.append(el('p','回答 · 原文 · 来源','eyebrow'),el('h2','回答与依据'));const answer=el('div');answer.id='department_answer';answer.tabIndex=-1;answer.setAttribute('aria-label','本次回答与依据');right.append(answer);renderAnswer(answer,ctx);
    function syncMode(){
      const consulting=state.mode!=='literature',experts=consulting&&state.collaborative,selectedProvider=experts?state.expertProvider:state.provider,
        allKimi=experts&&selectedProvider==='kimi_all',remote=consulting&&selectedProvider!=='local',info=providers.find(item=>item.provider===(allKimi?'kimi':selectedProvider)),
        supported=allKimi?state.catalog.collaboration?.modes?.includes('all_kimi'):!experts||selectedProvider==='local'||state.catalog.collaboration?.providers?.includes(selectedProvider);
      queryTitle.textContent=consulting?'查阅药材与方剂知识':'查找有出处的回答';
      subjectField.hidden=providerField.hidden=modelNote.hidden=example.hidden=!consulting;publicField.hidden=!remote;
      collaborationField.hidden=!consulting;providerField.hidden=!consulting||experts;
      expertProviderField.hidden=!experts;
      evidenceField.hidden=!allKimi;
      subject.required=consulting;subject.placeholder=state.mode==='herb'?'例如：黄芪（注明炮制品）':'例如：桂枝汤（注明版本）';
      subjectField.querySelector('span').textContent=state.mode==='herb'?'药材名称':'方剂名称';
      modelNote.textContent=!state.catalog.consultation?.enabled?'连接本地全文库后可使用模型咨询。':!info?.configured?'所选服务尚未配置，请由管理员配置后重启。':remote?'仅将本次名称和通用问题发送至所选 API；本地文献全文和患者档案留在本机。':'使用 '+info.model+' 在本机整理，并检索相关文献片段。';
      if(experts)modelNote.textContent=!supported?'当前服务尚未启用混合协作，请由管理员更新服务。':!info?.configured?'所选协作模型尚未配置或配置无效，请由管理员核对。':remote?
        'Kimi（'+info.model+'）与本地文献角色同时运行，再由本地模型做药学审查和汇总。每轮最多调用 Kimi 一次；仅发送本次名称和通用问题，文献全文和病例资料留在本机。':
        '本地试用：依次完成中医知识、文献证据、药学安全与汇总，可能需要数分钟。模型仍可能误解文献，每条结论均需核对原文。';
      if(allKimi&&supported)modelNote.textContent=info?.model!=='kimi-k3.1-pro'?'全部 Kimi 模式需要配置 kimi-k3.1-pro，请由管理员核对。':!info?.configured?'Kimi 尚未配置，请由管理员配置后重启。':
        '四个角色均调用 Kimi 3.1，每轮最多 4 次 API 调用。中医知识与文献证据并行，随后药学审查和汇总。发送本次通用问题、最多 3 个公开文献片段（合计不超过 2600 字符）及角色报告。';
      submit.textContent=experts?'开始专家协作':consulting?'咨询并查找相关文献':'查找依据并回答';
      submit.disabled=Boolean(active)||(consulting&&(!info?.enabled||(remote&&!state.publicTopic)))||(experts&&(!state.catalog.collaboration?.enabled||!supported||(!allKimi&&!providers.find(item=>item.provider==='local')?.enabled)))||(allKimi&&(!state.publicEvidence||info?.model!=='kimi-k3.1-pro'));
      cancel.hidden=!active;
    }
    function invalidate(clearAnswer=false){
      state.knowledgeRevision++;if(active)active.abort();active=null;feedback.replaceChildren();
      if(activeJob){void request(ctx,'knowledge/collaborations/'+activeJob+'/cancel',{}).catch(()=>{});activeJob=null;}
      if(clearAnswer){state.answer=null;state.answerQuestion='';state.answerReviewed=null;renderAnswer(answer,ctx);}syncMode();
    }
    mode.onchange=()=>{state.mode=mode.value;invalidate(true);};
    collaboration.onchange=()=>{state.collaborative=collaboration.value==='experts';invalidate(true);};
    subject.oninput=()=>{state.subject=subject.value;invalidate();};
    provider.onchange=()=>{state.provider=provider.value;state.publicTopic=false;publicTopic.checked=false;invalidate(true);};
    expertProvider.onchange=()=>{state.expertProvider=expertProvider.value;state.publicTopic=false;publicTopic.checked=false;state.publicEvidence=false;publicEvidence.checked=false;invalidate(true);};
    publicTopic.onchange=()=>{state.publicTopic=publicTopic.checked;invalidate();};
    publicEvidence.onchange=()=>{state.publicEvidence=publicEvidence.checked;invalidate();};
    form.onsubmit=async event=> {
      event.preventDefault();if(submit.disabled)return;const token=epoch,revision=++state.knowledgeRevision,asked=question.value.trim(),consulting=state.mode!=='literature',controller=new AbortController();active=controller;
      controller.signal.addEventListener('abort',()=>{if(activeJob){const job=activeJob;activeJob=null;void request(ctx,'knowledge/collaborations/'+job+'/cancel',{}).catch(()=>{});}},{once:true});
      submit.disabled=true;cancel.hidden=false;submit.textContent=consulting?'正在整理咨询回答…':synthetic?'正在读取合成示例…':'正在查阅全文…';feedback.replaceChildren(el('p',consulting?'正在调用所选模型并核对来源，请稍候。':synthetic?'正在核对合成示例的来源摘要；未调用模型。':'本地模型正在选择证据，请稍候。','department-help'));
      try {
        const payload={question:asked,disease:state.disease,source_id:state.source||'all',index_sha256:state.catalog.index_sha256};
        if(consulting)Object.assign(payload,{kind:state.mode,subject:subject.value.trim(),provider:state.provider,public_topic_confirmed:state.publicTopic});
        const experts=consulting&&state.collaborative;
        if(experts){payload.provider=state.expertProvider==='kimi_all'?'kimi':state.expertProvider;
          if(state.expertProvider==='kimi_all')Object.assign(payload,{expert_mode:'all_kimi',public_evidence_confirmed:state.publicEvidence});}
        let result=await request(ctx,experts?'knowledge/collaborate':consulting?'knowledge/consult':'knowledge/extract',payload,controller);
        if(experts&&result.job_id){
          const job=result.job_id;activeJob=job;
          while(['running','cancel_requested'].includes(result.status)){
            if(token!==epoch||view!==knowledgeView||revision!==state.knowledgeRevision||!isCurrent()||controller.signal.aborted){void request(ctx,'knowledge/collaborations/'+job+'/cancel',{}).catch(()=>{});return;}
            const progress=el('ol',null,'department-expert-progress');
            for(const [role,label] of Object.entries(expertLabels))progress.append(el('li',label+'：'+(expertStatuses[result.roles?.[role]]||'等待中')+expertModel(result.role_models?.[role])));
            feedback.replaceChildren(el('p',result.stage==='retrieve'?'正在检索与核对原文…':'专家协作处理中…','department-help'),progress);
            controllers.add(controller);await pollDelay(controller.signal);result=await request(ctx,'knowledge/collaborations/'+job,undefined,controller);
          }
          activeJob=null;result=result.result||{workflow:'expert-knowledge-v1',status:result.status};
        }
        if(token!==epoch||view!==knowledgeView||revision!==state.knowledgeRevision||!isCurrent()||controller.signal.aborted)return;state.answer=result;state.answerQuestion=asked;state.answerReviewed=null;renderAnswer(answer,ctx);feedback.replaceChildren();
        if(window.matchMedia('(max-width: 1100px)').matches){answer.focus({preventScroll:true});right.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}
      }catch(exc){if(token===epoch&&view===knowledgeView&&revision===state.knowledgeRevision&&isCurrent()&&exc.name!=='AbortError')error(feedback,exc);}
      finally{
        controllers.delete(controller);
        if(activeJob){const job=activeJob;activeJob=null;void request(ctx,'knowledge/collaborations/'+job+'/cancel',{}).catch(()=>{});}
        if(token===epoch&&view===knowledgeView&&active===controller){active=null;if(isCurrent())syncMode();}
      }
    };
    syncMode();fillSources();grid.append(left,right);box.replaceChildren(grid);
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
      const heading=el('div',null,'department-full-heading');heading.append(el('p','完整工作区','eyebrow'),el('strong','MingYiRx 门诊处方分析'));
      const standalone=el('a','在独立窗口展开');standalone.id='department_rx_open';standalone.href='/api/department/mingyirx/site/index.html';standalone.target='_blank';standalone.rel='noopener';
      const quick=el('a','快速访次核对');quick.href='#analysis-quick';quick.id='department_rx_quick';
      const expand=button(el,'展开画布',()=>setExpanded(!box.classList.contains('department-canvas-expanded')));expand.id='department_rx_expand';expand.setAttribute('aria-pressed','false');expand.setAttribute('aria-controls','department_rx_frame');
      const actions=el('div',null,'department-full-actions');actions.append(expand,standalone,quick);controls.append(heading,actions);
      const reports=el('details',null,'department-full-reports');reports.append(el('summary','研究报告与下载'));
      reports.id='department_rx_reports';
      const reportLinks=el('div');
      for(const [name,label] of [['research-report.html','文献研究报告'],['supplement.html','补充来源与汇总'],['analysis-report.md','分析报告（Markdown）'],['conditional_retention.csv','条件性保留率'],['disease-change-results.csv','病种与处方变化结果'],['literature-analysis-results.csv','文献分析结果'],['source-ledger.json','来源台账'],['source-correction.json','来源更正记录'],['teaching-provenance.json','教学资料来源']]) {
        if(!(status.static_assets||[]).includes(name))continue;
        const link=el('a',label);link.href='/api/department/mingyirx/site/'+name;link.target='_blank';link.rel='noopener';if(!name.endsWith('.html'))link.download=name;reportLinks.append(link);
      }
      reports.append(reportLinks);
      const note=el('p','沿用原处方网页及页内来源标记。导入后经核对保存为版本集合；切换科室模块会保留当前页面。临床工作台演示状态不改变本页资料来源。','department-help');
      if(status.collection_scope==='local_single_operator')note.append(' 当前为本机单操作者集合。');
      const help=el('details',null,'department-full-help');help.append(el('summary','资料来源与保存范围'),note,el('p','导入集合保存后生成对应医案比较视图。汇总图按原流程生成；传承标注在浏览器中保留为草稿，沿用导出、验证与冻结流程。','department-help'));
      const context=el('div',null,'department-full-context');context.append(reports,help);
      const frame=el('iframe');frame.id='department_rx_frame';frame.title='MingYiRx 原处方分析、医案传承与导入工作区';frame.src=standalone.href;
      // Keep the same iframe in normal document flow: expansion must never reload its drafts.
      function setExpanded(value,restoreFocus=true){
        box.classList.toggle('department-canvas-expanded',value);document.body.classList.toggle('department-canvas-expanded',value);
        expand.setAttribute('aria-pressed',String(value));expand.textContent=value?'收起画布 · Esc':'展开画布';
        if(restoreFocus){expand.focus();if(value)controls.scrollIntoView({block:'start'});}
      }
      const escape=event=>{if(!event.defaultPrevented&&event.key==='Escape'&&box.classList.contains('department-canvas-expanded')){event.preventDefault();setExpanded(false);}};
      window.addEventListener('keydown',escape);
      // Events do not cross iframe boundaries. Follow only accessible documents and release
      // old document listeners on navigation, so imported collections retain their own handlers.
      function bindFrameEscape(owner){
        let releaseDocument=()=>{};
        const loaded=()=>{
          releaseDocument();releaseDocument=()=>{};
          let doc;try{doc=owner.contentDocument;}catch{return;}
          const view=doc?.defaultView;if(!view)return;
          const children=new Map();
          const sync=()=>{
            const frames=new Set(doc.querySelectorAll('iframe'));
            for(const [child,release] of children)if(!frames.has(child)){release();children.delete(child);}
            for(const child of frames)if(!children.has(child))children.set(child,bindFrameEscape(child));
          };
          view.addEventListener('keydown',escape);
          const observer=new MutationObserver(sync);observer.observe(doc,{childList:true,subtree:true});sync();
          releaseDocument=()=>{observer.disconnect();view.removeEventListener('keydown',escape);for(const release of children.values())release();children.clear();};
        };
        owner.addEventListener('load',loaded);loaded();
        return()=>{owner.removeEventListener('load',loaded);releaseDocument();};
      }
      const releaseFrameEscape=bindFrameEscape(frame);
      const visibility=new MutationObserver(()=>{if(box.hidden)setExpanded(false,false);});visibility.observe(box,{attributes:true,attributeFilter:['hidden']});
      collapseCanvas=()=>{setExpanded(false,false);visibility.disconnect();window.removeEventListener('keydown',escape);releaseFrameEscape();};
      box.replaceChildren(controls,context,frame);
    }catch(exc){if(token===epoch&&ctx.isCurrent()){box.replaceChildren();ctx.error(box,exc);box.append(button(el,'重新连接原工作区',()=>renderFull(box,ctx)));}}
  }
  function useAssistantRecords(records,origin,text) {
    state.records=structuredClone(records);state.origin=origin;state.text=text;
    state.recognition={records:state.records};state.excluded=new Set();state.confirmed=false;state.result=null;state.revision++;
  }
  function selectKnowledgeSource(sourceId) {
    state.mode='literature';state.knowledgeRevision++;state.source=sourceId;state.disease='all';state.search='';state.question='';state.answer=null;state.answerQuestion='';
  }
  window.Department=Object.freeze({render,renderFull,clear,useAssistantRecords,selectKnowledgeSource});
})();
