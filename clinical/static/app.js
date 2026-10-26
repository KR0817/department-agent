const $ = id => document.getElementById(id);
const states = {queued:'排队中',reading:'正在读取 / OCR',extracting:'正在生成候选',review:'待核对归档',blocked:'需要处理',failed:'提取失败，可重试',publishing:'正在归档',partial:'部分归档，待继续',published:'已归档'};
const actions = {accept:'接受原值',modify:'修改后接受',reject:'拒绝',defer:'暂缓'};
const drafts = new Map();
let selected=null, tab='job', signature='', fields={}, busy=false, demo=false;
let currentUser=null, setupRequired=false, documentMode='synthetic', sessionVersion=0;
let uploadBatch=[], uploading=false, uploadRun=0, uploadController=null;
let uploadPatient=null, registryPatients=[], registryRequest=0, registryLoaded=false, patientCreating=false;
let overviewSource='registry', registryQuery='';
const clinicalSections={medications:'用药记录',inpatient_exams:'住院主要检查',infection_status:'感染状况',comorbidities:'基础病',baseline_exams:'重要基础检查'};
const attentionLabels={red:'优先核实',orange:'重点复核',yellow:'关注变化',gray:'资料待核对'};
const careDrafts=new Map();
const careStates={unreviewed:'待核实',acknowledged:'已阅',in_progress:'处理中',reviewed:'完成复核'};
const planStates={overdue:'已逾期',in_window:'窗口内',upcoming:'未到期',completed:'本轮已完成',cancelled:'计划已取消',unknown:'计划待明确'};
const careCategories={medication:'用药',infection:'感染',hospital:'住院',other:'其他病程'};
const tabs=['job','patients','tasks','outbox','admin'];
let overviewRequest=0, viewVersion=0, workbenchTab='job', activePatientId=null;
let overviewCache=null, overviewPending=null, overviewFetchVersion=0;
let overviewFilter='all', overviewQuery='';
const overviewStates={completed:'首次随访已完成',overdue:'已逾期',in_window:'窗口内',upcoming:'未到期'};
const outboxStates={draft:'待复核草稿',pending_send:'待发送',completed:'已完成访视',cancelled:'已取消'};
const roleLabel=role=>role==='admin'?'管理员':'工作人员';
const methods={'digital-text':'文档文字读取','local-ocr':'本机 OCR 识别','deterministic-csv':'结构化表格读取'};
const auditActions={account_initialized:'创建首位管理员',signed_in:'登录',password_changed:'修改密码',account_created:'创建账户',
  business_database_export:'导出业务数据库',business_archive_export:'导出业务资料包',source_uploaded:'上传原始资料',
  read_source:'读取原始资料',extract_local:'本机提取信息',candidate_ready:'生成待复核信息',extraction_failed:'信息提取失败',
  human_reviewed:'完成人工复核',published:'完成归档',publication_failed:'归档失败',retry_requested:'申请重新提取',followup_completed:'完成访视待办'};
const errorMessages={
  'Care follow-up requires an in-progress state and next date':'需要继续跟进的事项请选择“处理中”，并填写跟进日期。',
  'Select or register a patient before uploading':'请先选择已有患者或新建患者，再上传资料。',
  'Selected patient was not found in the business registry':'未找到所选业务患者，请刷新患者名单后重新选择。',
  'This document is already associated with a different patient':'该文件已关联另一位患者，请核对原件与所选患者。',
  'Existing document has no confirmed patient binding; identity review is required':'该文件已有任务，但患者归属尚未确认，请先核对原任务。',
  'Selected patient does not match the document identity':'原件身份与所选患者不一致，请核对后重新上传。',
  'Patient identifier has conflicting names; identity review is required':'同一患者编号对应不同姓名，请核对身份资料。',
  'Patient registration already exists with different details':'该患者编号已有不同资料，请核对编号和姓名。',
  'Patient selection is required':'请先选择已有患者或新建患者，再上传资料。',
  'Patient not found':'未找到这位患者，请刷新患者名单后重新选择。',
  'Patient identifier is already registered with different details':'该患者编号已有不同资料，请核对编号和姓名。',
  'Patient identity conflict':'患者身份不一致，请核对原件与所选患者。',
  'Upload patient does not match existing document':'该文件已属于另一位患者，请核对原件与所选患者。',
  'Document patient identity does not match selected patient':'原件身份与所选患者不一致，请核对后重新上传。',
  'Duplicate document has no confirmed patient association':'重复资料尚未确认患者归属，请先核对原任务，不能直接重新绑定。',
  'Patient overview demo is unavailable':'合成患者总览暂不可用，请重新读取；若仍失败，请联系管理员检查演示资料。',
  'Invalid username or password':'账户名或密码不正确，请重新输入。',
  'Invalid current password':'当前密码不正确，请重新输入。',
  'Sign in again':'登录已过期，请重新登录。',
  'Sign in with your username and password':'请先使用账户名和密码登录。',
  'Administrator access required':'此操作需要管理员账户。',
  'Username is already in use':'该账户名已被使用，请换一个账户名。',
  'Initial administrator is already configured':'管理员账户已经建立，请直接登录。',
  'Username must contain 3-64 letters, digits, dots, underscores or hyphens':'账户名须为 3–64 位英文字母、数字、点、下划线或短横线。',
  'Password must contain 12-128 characters':'密码长度须为 12–128 位。',
  'Password must contain valid Unicode characters':'密码包含无法识别的字符，请重新输入。',
  'Role must be admin or staff':'请选择管理员或工作人员角色。',
  'Too many login attempts; try again later':'登录尝试次数过多，请稍后再试。',
  'Invalid request fields or value limits':'提交内容不符合要求，请检查必填字段和长度限制。',
  'Local host required':'请通过本机工作台地址访问。',
  'Same-origin action required':'页面来源验证未通过，请从工作台原地址重新打开页面。',
  'Invalid content length':'请求大小无法识别，请重新上传。',
  'Upload exceeds 10 MB':'上传文件过大，请将文件控制在 10 MB 以内。',
  'Upload must contain 1 byte to 10 MB':'请上传非空文件，且文件大小不超过 10 MB。',
  'Unsupported document format':'暂不支持此文件格式，请选择页面列出的资料格式。',
  'Unsupported file format':'暂不支持此文件格式，请选择页面列出的资料格式。',
  'Synthetic-only acknowledgement required':'请先确认上传的是虚构测试资料。',
  'This simulation accepts SJD-SYNTHETIC marked fixtures only':'当前为合成演示模式，请使用带 SJD-SYNTHETIC 标记的测试资料。',
  'Synthetic demo uses deterministic CSV only; model calls are disabled':'当前演示仅支持结构化 CSV，请使用示例表格。',
  'Job not found':'未找到这份资料，请刷新处理队列。',
  'Review changed; reload before saving':'复核版本已更新，请刷新后重新核对并保存。',
  'Review is unavailable or publication is frozen':'当前复核不可编辑；请先完成正在进行的归档。',
  'Unknown field':'未找到该字段，请刷新当前资料。',
  'A reason is required':'请填写本次处理的原因。',
  'Modified value, unit and source quote are required':'请填写修改值、单位和支持修改的原文摘录。',
  'Correction requires an archived field and modify action':'请从已归档字段的更正入口修改。',
  'A correction is already pending':'该字段已有待归档的更正，请先完成归档。',
  'Archived fields require an explicit correction':'已归档字段请使用“更正已归档值”。',
  'Correction must change the archived value or unit':'更正值或单位须与当前归档记录不同。',
  'Current source-backed candidates require explicit review':'请先逐项核对并保存当前候选信息。',
  'Follow-up interval is frozen for this job; explicit rescheduling is separate':'本份资料的随访间隔已固定；后续排程调整需单独处理。',
  'Follow-up interval is frozen for this publication':'本次归档的随访间隔已固定。',
  'Every field needs an explicit decision':'请先为每个字段保存处理决定。',
  'No accepted or modified fields to archive':'当前没有已接受或修改后可归档的字段。',
  'Job is not ready for review':'资料尚未准备好，请查看处理队列中的进度。',
  'Only failed/blocked jobs can retry':'只有提取失败或需要处理的资料可以重新提取。',
  'Follow-up authority unavailable':'访视服务暂不可用，请稍后刷新。',
  'Follow-up item not found':'未找到该随访安排，请刷新队列。',
  'Follow-up item changed; reload before editing':'随访安排已有新版本，请刷新后再修改。',
  'Revision changed':'记录已有新版本，请刷新后再修改。',
  'Completed follow-up items are read-only':'已完成访视的随访安排保留为只读。',
  'A reviewed clinical Task is required before pending_send':'请先复核并归档资料，关联访视待办后再设为待发送。',
  'Status must be draft, pending_send or cancelled':'请选择草稿、待发送或已取消状态。',
  'Expected revision, due_date, message, status and reason':'请完整填写计划日期、消息草稿、状态和修改原因。',
  'Revision is invalid':'记录版本无效，请刷新后重试。',
  'Date must use YYYY-MM-DD':'请填写有效日期，格式为年-月-日。',
  'Date is invalid':'日期无效，请检查年月日。',
  'Follow-up date is outside the supported range':'随访日期超出可支持的范围，请重新设置。',
  'Follow-up interval must be 1-730 days':'随访间隔须为 1–730 天。',
  'Patient identifier has a different name; identity review required':'该患者编号对应的姓名不一致，请先核对身份信息。',
  'Patient identifier has a different name; manual identity review required':'该患者编号对应的姓名不一致，请先人工核对身份信息。',
  'Identity conflict: multiple clinical resources':'患者身份对应多个记录，请先核对身份信息。',
  'Clinical Task already belongs to another follow-up obligation':'该访视待办已关联其他随访安排，请核对关联关系。',
  'Follow-up obligation is already linked to a different clinical Task':'该随访安排已关联其他访视待办，请核对关联关系。',
  'Clinical Task window changed; explicit reconciliation required':'访视窗口已变更，请先核对排程。',
  'Existing follow-up window differs; explicit rescheduling required':'已有随访窗口与本次安排不同，请先核对并调整排程。',
  'Clinical transaction incomplete':'临床记录尚未全部归档，请查看已完成项后重试。',
  'Clinical transaction has no durable receipt':'尚未取得完整归档回执，请保留资料并重试。',
  'Archive receipt does not match the reviewed fact':'归档回执与复核内容不一致，请核对记录。',
  'Existing event has a conflicting value; explicit correction workflow required':'同一事件已有不同数值，请使用更正流程。',
  'Existing observation has inconsistent identity bindings':'已有字段的患者或事件关联不一致，请核对来源。',
  'Correction target does not match the patient, event and field':'待更正记录与当前患者、事件或字段不匹配。',
  'Correction target was already superseded; reload current history':'该记录已有更新版本，请刷新更正历史。',
  'Follow-up completion requires a confirmed, in-window reviewed visit; manual completion is disabled':'请归档随访窗口内已复核的后续就诊资料，系统将据此完成访视待办。',
  'Document expansion exceeds limit':'文档解压后过大，请拆分后上传。',
  'PDF must be unencrypted and contain 1-12 pages':'请上传未加密且包含 1–12 页的 PDF。',
  'Image dimensions exceed limit':'图片尺寸过大，请缩小后上传。',
  'No readable text or document exceeds 18000 characters':'未读取到有效文字，或文字超过 18000 字符；请核对原件或拆分资料。',
  'Exactly one explicit patient identifier required; identity review needed':'资料须包含一个明确的患者编号，请核对后重新上传。',
  'Exactly one explicit patient name required; identity review needed':'资料须包含一个明确的患者姓名，请核对后重新上传。',
  'Visit date is not supported by an exact source excerpt':'就诊日期缺少对应原文依据，请核对资料。',
  'Event identifier requires an exact source reference':'事件标识缺少对应原文依据，请核对资料。',
  'Unit is not present in the source excerpt':'该单位未出现在所选原文摘录中，请核对依据。',
  'Numeric value must match a complete source token':'数值须与原文中的完整数值一致，请核对摘录。',
  'Symptom value out of range; source review required':'症状评分超出支持范围，请核对原文。',
  'Conflicting values for the same visit and field':'同次就诊的同一字段存在冲突值，请核对原文。',
  'No supported visit facts were extracted':'未提取到可支持的就诊信息，请核对资料中的日期和字段。',
  'No supported source field labels found':'未找到可识别的字段名称，请核对资料内容。',
  'Pinned local model digest mismatch':'本地模型版本校验不一致，请联系管理员检查模型。',
  'A source line exceeds the bounded model context':'单行文字过长，请按就诊内容分段后上传。',
  'A visit exceeds the bounded extraction context':'单次就诊资料过长，请拆分后上传。',
  'Model source line is outside the document':'模型返回的原文行号无效，请重新提取并核对。',
  'Long source has an unassigned date before its visit header':'长文档中的日期归属不清，请为每次就诊添加明确日期标题。',
  'Clinical facts before a visit date require source review':'部分临床信息位于日期之前，请核对其就诊日期归属。',
  'Long source requires explicit visit-date headers for safe segmentation':'长文档须为每次就诊添加明确日期标题。',
  'An unbroken source paragraph exceeds the context limit':'单段文字过长，请按就诊内容分段后上传。',
  'CSV requires 1-100 rows':'CSV 须包含 1–100 条记录。',
  'CSV requires patient_id,name,visit_date,code,value,unit':'CSV 缺少必需表头，请参照中文示例填写。',
  'CSV identity is missing or ambiguous':'CSV 中的患者编号或姓名缺失或不一致，请核对。',
  'CSV requires one physical line per record and an explicit name':'CSV 每条记录须占一行，并提供明确姓名。',
  'Database snapshot failed integrity validation':'数据库快照完整性检查未通过，暂未提供下载。',
  'Clinical resource export unavailable; no partial archive is offered':'临床资料暂时无法完整导出，请稍后重试。',
  'Unexpected source identifier; archive refused':'原始资料标识异常，暂未生成资料包。',
  'Source integrity mismatch; archive refused':'原始资料完整性检查未通过，暂未生成资料包。',
};

const departmentErrors={
  AUTHENTICATION_REQUIRED:'请先登录工作台。',
  NONCE_REQUIRED:'页面校验已过期，请重新打开处方工作区。',
  WORKSPACE_NOT_CONFIGURED:'处方分析工作区尚未配置，请联系本机维护人员。',
  WORKSPACE_STATE_INVALID:'处方工作区的保存目录未通过校验，工作区未加载。请联系本机维护人员检查恢复配置。',
  WORKSPACE_STATE_NOT_OWNED:'处方工作区的保存目录与当前资料来源不匹配，工作区未加载。请联系本机维护人员。',
  WORKSPACE_SITE_INVALID:'原处方网页文件未通过完整性检查，工作区未加载。请联系本机维护人员。',
  WORKSPACE_HTML_INVALID:'原处方网页文件未通过完整性检查，工作区未加载。请联系本机维护人员。',
  WORKSPACE_SCRIPT_UNSUPPORTED:'原处方网页文件未通过完整性检查，工作区未加载。请联系本机维护人员。',
  WORKSPACE_CONTROLLER_UNSUPPORTED:'原处方网页文件未通过完整性检查，工作区未加载。请联系本机维护人员。',
  WORKSPACE_UNAVAILABLE:'处方分析工作区暂不可用，请稍后重试。',
  REQUEST_SIZE_LIMIT:'提交内容过大，请拆分后重试。',
  REQUEST_TOO_LARGE:'提交内容过大，请拆分后重试。',
  JSON_REQUIRED:'提交内容格式不正确，请检查后重试。',
  INVALID_JSON:'提交内容格式不正确，请检查后重试。',
  JSON_INVALID:'提交内容格式不正确，请检查后重试。',
  REQUEST_INVALID:'提交内容格式不正确，请检查后重试。',
  OPERATION_FAILED:'处理未完成，请核对资料后重试。',
  NO_COMMITTED_CASES:'尚无已保存的医案集合。',
  REVISION_NOT_FOUND:'未找到所选版本，请刷新后重试。',
  NOT_FOUND:'未找到请求的内容，请刷新后重试。'
};

function errorInfo(value,status=0) {
  if(value?.localized) return {message:value.message,technical:value.technical||''};
  const raw=typeof value==='string'?value:String(value?.message||'');
  let message=errorMessages[raw];
  if(!message && /^Care /.test(raw))message=status===409?'记录或来源版本已变化，请刷新后核对；当前输入已保留。':status===404?'未找到对应患者或记录，请刷新重试。':'请核对日期、必填内容、缺失原因及本患者的来源依据后重新提交。';
  if(!message && /Failed to fetch|NetworkError|fetch failed|Network request failed|Load failed/i.test(raw)) message='无法连接本机工作台，请检查服务是否运行后重试。';
  if(!message && /timed? ?out|timeout|AbortError/i.test(raw)) message='处理超时，请稍后查看任务状态或重试。';
  if(!message && /(?:Synthetic )?Clinical API rejected request: HTTP \d+/.test(raw)) message='临床服务暂未接受请求，请查看任务状态后重试。';
  if(!message && /^Unsupported source value for field: /.test(raw)) message='字段值缺少有效原文依据，请核对后再保存。';
  if(!message && /^Source label absent for field: /.test(raw)) message='原文中未找到该字段的名称，请核对并暂缓不确定项。';
  if(!message && /^Numeric field must separate the literal value from the unit: /.test(raw)) message='请将数值与单位分别填写。';
  if(!message && / is missing or invalid$/.test(raw)) message='必需内容缺失或无效，请检查后重新提交。';
  if(!message && /[\u3400-\u9fff]/.test(raw)) return {message:raw,technical:''};
  if(!message) message=({401:'请先登录工作台。',403:'当前账户无权执行此操作。',404:'未找到请求的记录，请刷新后重试。',409:'记录状态已变化，请刷新后核对。',413:'上传文件过大，请拆分后重新上传。',422:'提交内容不符合要求，请检查后重试。',429:'操作过于频繁，请稍后重试。',503:'服务暂不可用，请稍后重试。'})[status]||'处理未完成，请查看技术详情并联系管理员，或稍后重试。';
  return {message,technical:raw|| (status?'HTTP '+status:'')};
}
function localizedError(value,status=0) {
  const info=errorInfo(value,status), exception=new Error(info.message);
  exception.localized=true;exception.technical=info.technical;exception.status=status;return exception;
}
function traceDetails(title,value) {
  const details=el('details',undefined,'technical-details');
  details.append(el('summary',title),el('p',value,'resource-id'));return details;
}
function feedbackError(target,value,suffix='',prefix='') {
  const info=errorInfo(value);target.replaceChildren(el('span',prefix+info.message+suffix));
  if(info.technical) target.append(traceDetails('技术详情（原始信息）',info.technical));
}
function eventLabel(value) {
  const known={morning:'上午就诊',evening:'晚间就诊',afternoon:'下午就诊',followup:'后续访视'};
  const wrapper=el('div',undefined,'event-label');
  wrapper.append(el('span','事件：'+(known[value]||'来源事件')));
  if(value) wrapper.append(traceDetails('查看事件标识',value));return wrapper;
}

function el(tag,text,cls) {
  const node=document.createElement(tag);
  if(text!==undefined && text!==null) node.textContent=text;
  if(cls) node.className=cls;
  return node;
}
async function api(path,body,signal) {
  const requestSession=sessionVersion;
  let response;
  try {response=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',
    headers:body instanceof FormData || body===undefined?{}:{'Content-Type':'application/json'},
    body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body),signal});}
  catch(exception) {throw localizedError(exception);}
  let value;
  try {value=await response.json();}
  catch {throw localizedError('服务响应无法读取，请稍后重试。',response.status);}
  if(!response.ok) {
    if(response.status===401 && currentUser && requestSession===sessionVersion && !path.startsWith('auth/')) {
      signedOut('登录已过期，请重新登录。');
    }
    if(typeof value?.detail!=='string'&&typeof value?.error==='string') {
      const exception=localizedError(departmentErrors[value.error]||'',response.status);
      exception.technical=value.error;throw exception;
    }
    throw localizedError(typeof value?.detail==='string'?value.detail:response.status===422?'提交内容不符合要求，请检查字段后重试。':'',response.status);
  }
  return value;
}
function loadingState(text,variant='list') {
  const box=el('div',undefined,'skeleton skeleton-'+variant);
  box.setAttribute('role','status');box.setAttribute('aria-live','polite');box.setAttribute('aria-busy','true');
  box.append(el('p',text,'skeleton-label'));
  const rows=variant==='detail'?['w-40 h-lg','w-100 h-block','w-70','w-90','w-60']:['w-30 h-lg','w-100','w-90','w-100','w-80','w-60'];
  for(const classes of rows) {const bar=el('span',undefined,'skeleton-bar '+classes);bar.setAttribute('aria-hidden','true');box.append(bar);}
  return box;
}
function workbenchGuide() {
  const guide=el('div',undefined,'empty workbench-guide');
  guide.append(el('h2','上传检查单和病例'),el('p','可一次选择多份资料，统一排队处理。提取信息默认接受；有问题时修改、拒绝或暂缓，最后统一确认归档。'));
  const steps=el('ol',undefined,'guide-steps');
  for(const [title,text] of [['选择患者','在左侧选择已有患者，或新建患者档案。'],['上传资料','拖入或选择检查单、病例，可一次多份。'],['核对归档','逐项核对原文，统一确认后生成待办。']]) {
    const item=el('li');item.append(el('strong',title),el('span',text));steps.append(item);
  }
  guide.append(steps,el('p','同日不同事件分开呈现。更正保留旧值；部分归档可继续未完成项。','help'));
  return guide;
}
function error(target,value,prefix='') {
  const notice=el('div',undefined,'error');feedbackError(notice,value,'',prefix);
  notice.setAttribute('role','alert');
  target.append(notice);
}
function draftKey(job,field) { return job+':'+field; }
function hasDrafts(job) { return [...drafts.keys()].some(key=>key.startsWith(job+':')); }
function frozen(job) { return ['publishing','partial'].includes(job.publication?.state); }
function archived(field) { return field.archive?.state==='archived' && Number(field.archive.revision||0)>=Number(field.decision?.revision||0); }
function pendingCorrection(field) { return Boolean(field.decision?.correction_of) && !archived(field); }
function literal(fact) { return String(fact.value??'')+(fact.unit?' '+fact.unit:''); }
function fieldName(code) { return fields[code]||clinicalSections[code]||code; }
function timeLabel(value) {
  if(!value) return '';
  const date=new Date(value);
  return Number.isNaN(date.getTime())?value:date.toLocaleString('zh-CN',{hour12:false});
}
function label(text,control,cls) {
  const wrapper=el('label',undefined,cls||'form-label');
  wrapper.append(el('span',text),control);
  return wrapper;
}
async function list(refreshDetail=true) {
  if(!currentUser) return;
  const version=sessionVersion;
  try {
    const jobs=await api('jobs');
    if(!currentUser||version!==sessionVersion) return;
    $('count').textContent=jobs.length;
    const box=$('jobs'); box.replaceChildren();
    for(const job of jobs) {
      const button=el('button',undefined,'job'+(job.id===selected?' active':''));
      button.type='button';button.dataset.state=job.state;
      button.append(el('span',job.filename),el('small',states[job.state]||job.state));
      if(job.id===selected) button.setAttribute('aria-current','true');
      button.onclick=()=>{selected=job.id;signature='';show('job');};
      box.append(button);
    }
    if(!jobs.length) box.append(el('p','上传资料后，处理进度会显示在这里。','help'));
    if(refreshDetail && selected && tab==='job') await detail();
  } catch(exception) {if(currentUser&&version===sessionVersion) feedbackError($('upload_status'),exception);}
}
function renderHistory(job) {
  const history=job.history||[], publications=job.publication_history||[];
  if(!history.length && !publications.length) return null;
  const details=el('details',undefined,'history');
  details.append(el('summary','决定与归档历史 · '+history.length+' 条处理记录'));
  const ordered=el('ol',undefined,'history-list');
  for(const item of [...history].reverse()) {
    const field=(job.fields||[]).find(value=>value.id===item.field_id), entry=el('li');
    entry.append(el('strong',(field?fieldName(field.original.code):'字段')+' · '+(item.correction_of?'更正':item.origin==='batch_default_accept'?'统一确认接受':actions[item.action]||item.action)),
      el('small','复核版本 '+item.revision+' · '+(item.actor||'操作员')+' · '+timeLabel(item.at)));
    if(item.value!==undefined && ['accept','modify'].includes(item.action)) entry.append(el('p',literal(item),'history-value'));
    if(item.reason) entry.append(el('p','原因：'+item.reason));
    if(item.quote) entry.append(el('blockquote',item.quote,'quote'));
    if(item.correction_of) entry.append(el('p','关联前一已归档版本，原记录保留。','help'));
    ordered.append(entry);
  }
  if(history.length) details.append(ordered);
  for(const publication of [...publications].reverse()) {
    const entry=el('div',undefined,'publication-history');
    const completed=Object.values(publication.progress?.fields||{}).filter(item=>item.state==='archived').length;
    entry.append(el('strong','归档版本 '+publication.revision+' · '+(states[publication.state]||publication.state)),
      el('p','已归档字段：'+completed,'help'));
    details.append(entry);
  }
  return details;
}
function updateDirtyNotice(jobId) {
  const notice=$('draft_notice');
  if(!notice) return;
  notice.hidden=!hasDrafts(jobId);
  notice.textContent='存在未保存的处理决定。请先保存或撤销，再统一确认归档。';
  if($('archive_button') && hasDrafts(jobId)) $('archive_button').disabled=true;
}
function reviewFieldCard(job,field) {
  const original=field.original, decision=field.decision, card=el('article',undefined,'field-card');
  card.dataset.fieldId=field.id;
  const top=el('div',undefined,'field-heading');
  top.append(el('h4',fieldName(original.code)));
  const status=archived(field)?'已归档':pendingCorrection(field)?'更正待归档':decision?actions[decision.action]:'默认接受';
  top.append(el('span',status,'badge '+(archived(field)?'success':decision?.action==='reject'?'muted':'')));
  card.append(top,el('p','原始候选','eyebrow'),el('p',literal(original),'candidate-value'),
    el('p','原文依据','field-caption'),el('blockquote',original.quote,'quote'));
  if(decision) {
    const saved=el('div',undefined,'saved-decision');
    if(decision.action==='modify') {
      saved.append(el('strong','已保存值：'+literal(decision)));
      if(decision.quote!==original.quote) saved.append(el('blockquote',decision.quote,'quote'));
    } else saved.append(el('strong','已保存：'+(decision.origin==='batch_default_accept'?'统一确认接受':actions[decision.action])));
    if(decision.reason) saved.append(el('p','原因：'+decision.reason));
    saved.append(el('small','复核版本 '+decision.revision+' · '+(decision.actor||'操作员')+' · '+timeLabel(decision.at)));
    card.append(saved);
  }
  if(field.archive?.state==='failed') error(card,field.archive.error||'等待重试','该项归档失败：');
  if(job.legacy_read_only) {
    card.append(el('p','历史归档记录保留为只读；本轮逐字段复核记录从新任务开始。','help'));
    return card;
  }
  if(frozen(job)) {
    card.append(el('p','本次归档计划已冻结。继续完成归档后可进行后续复核或更正。','help'));
    return card;
  }
  if(pendingCorrection(field)) {
    card.append(el('p','本次更正已保存，等待归档。归档成功后可再次更正。','help'));
    return card;
  }
  const key=draftKey(job.id,field.id);
  if(archived(field) && !drafts.has(key)) {
    const correction=el('button','更正已归档值','secondary');
    correction.type='button';
    correction.onclick=()=>{
      drafts.set(key,{mode:'correction',action:'modify',value:decision?.value??original.value,
        unit:decision?.unit??original.unit,quote:decision?.quote??original.quote,reason:''});
      signature=''; detail(true);
    };
    card.append(correction); return card;
  }
  const draft=drafts.get(key), correction=draft?.mode==='correction';
  const form=el('form',undefined,'field-review'), group=el('div',undefined,'decision-buttons');
  let action=draft?.action||decision?.action||'accept';
  group.setAttribute('role','group');group.setAttribute('aria-label',fieldName(original.code)+'的处理决定');
  if(correction) {
    action='modify';
    form.append(el('p','更正将生成关联的新版本，原值和历史记录保留。','help'));
  } else {
    for(const [name,text] of Object.entries(actions)) {
      const button=el('button',name==='accept'&&!decision?'默认接受':text,'decision-button');
      button.type='button';button.dataset.action=name;
      button.onclick=()=>{
        if(action===name&&(name==='accept'||drafts.has(key))) return;
        action=name;
        if(name==='accept'&&!decision) drafts.delete(key); else capture();
        updateControls();updateDirtyNotice(job.id);
        if(!hasDrafts(job.id)) $('reviewed')?.dispatchEvent(new Event('change'));
      };
      group.append(button);
    }
    form.append(group);
    if(!decision) form.append(el('p','无问题无需点击；归档时统一确认接受原值。','help default-accept-note'));
  }
  const edit=el('div',undefined,'edit-fields'), value=el('input'), unit=el('input');
  value.type='text';value.value=draft?.value??decision?.value??original.value??'';value.autocomplete='off';
  unit.type='text';unit.value=draft?.unit??decision?.unit??original.unit??'';unit.autocomplete='off';
  const pair=el('div',undefined,'value-unit');
  pair.append(label('确认值',value),label('单位（原文未提供时留空）',unit));
  const quote=el('textarea');quote.rows=3;quote.value=draft?.quote??decision?.quote??original.quote??'';
  edit.append(pair,label('支持修改的原文摘录',quote),el('p','逐字粘贴本份资料中的依据，数值与单位须受该段原文支持。','help'));
  const reason=el('textarea');reason.rows=2;reason.value=draft?.reason??(correction?'':decision?.reason)??'';
  const reasonLabel=label('处理原因',reason), buttons=el('div',undefined,'form-actions');
  const save=el('button',correction?'保存更正，待归档':'保存字段决定','secondary');save.type='submit';
  const cancel=el('button','撤销未保存输入','text-button');cancel.type='button';
  cancel.onclick=()=>{drafts.delete(key);signature='';detail(true);};
  buttons.append(save,cancel);
  const feedback=el('div','','form-feedback');feedback.setAttribute('role','status');
  form.append(edit,reasonLabel,buttons,feedback);
  function capture() {
    drafts.set(key,{mode:correction?'correction':'review',action,value:value.value,unit:unit.value,quote:quote.value,reason:reason.value});
    updateDirtyNotice(job.id);
  }
  function updateControls() {
    const dirty=drafts.has(key), modify=dirty&&action==='modify', needsReason=dirty&&['modify','reject','defer'].includes(action);
    edit.hidden=!modify;reasonLabel.hidden=!needsReason;value.required=modify;quote.required=modify;reason.required=needsReason;
    for(const button of group.children) {button.setAttribute('aria-pressed',String(button.dataset.action===action));button.disabled=busy;}
    buttons.hidden=!dirty;save.disabled=!dirty||busy;cancel.hidden=!dirty;
  }
  for(const input of [value,unit,quote,reason]) input.oninput=()=>{capture();updateControls();};
  form.onsubmit=async event=>{
    event.preventDefault();
    if(busy||!drafts.has(key)||!form.reportValidity()) return;
    capture();busy=true;save.disabled=true;feedback.textContent='正在保存…';
    const body={version:job.version,review_revision:job.review_revision,field_id:field.id,action};
    if(action==='modify') Object.assign(body,{value:value.value,unit:unit.value,quote:quote.value});
    if(['modify','reject','defer'].includes(action)) body.reason=reason.value;
    try {
      await api('jobs/'+job.id+(correction?'/correction':'/review'),body);
      drafts.delete(key);signature='';busy=false;await detail(true);await list();
    } catch(exception) {
      feedbackError(feedback,exception,' 输入已保留；若版本已更新，请先刷新最新状态，再核对提交。');
      feedback.className='form-feedback error';
    } finally {busy=false;save.disabled=false;}
  };
  updateControls();card.append(form);return card;
}
function renderPublication(job) {
  const publication=job.publication, section=el('section',undefined,'archive-panel');
  section.append(el('h3',frozen(job)?'继续本次归档':'统一确认并归档'));
  const count={pending:0,accept:0,modify:0,reject:0,defer:0,archived:0};
  for(const field of job.fields||[]) {
    if(archived(field)) count.archived++;
    const action=field.decision?.action||'pending';
    if(Object.hasOwn(count,action)) count[action]++;
  }
  const summary=el('div',undefined,'review-counts');
  for(const [text,value] of [['默认接受',count.pending],['已保存接受 / 修改',count.accept+count.modify],['拒绝',count.reject],['暂缓',count.defer],['已归档',count.archived]]) {
    const item=el('span');item.append(el('b',value),document.createTextNode(' '+text));summary.append(item);
  }
  section.append(summary);
  if(publication) {
    const progress=publication.progress?.fields||{};
    const total=publication.plan?.candidate?.visits?.reduce((sum,visit)=>sum+visit.facts.length,0)??Object.keys(progress).length;
    const done=Object.values(progress).filter(item=>item.state==='archived').length;
    section.append(el('p','归档计划版本 '+publication.revision+' · '+(states[publication.state]||publication.state)+(total?' · '+done+'/'+total+' 项已写入':''),'help'));
    for(const [fieldId,item] of Object.entries(progress)) {
      if(item.state!=='failed') continue;
      const field=(job.fields||[]).find(entry=>entry.id===fieldId);
      error(section,item.error||'归档失败，等待重试',field?fieldName(field.original.code)+'：':'');
    }
    if(frozen(job)) section.append(el('p','已完成项保留，重试沿用本次复核版本与随访间隔，只继续未完成项。完成前暂停字段编辑。','help'));
  }
  const receipt=publication?.receipt||job.receipt;
  if(receipt) section.append(el('p','已形成 '+(receipt.visits?.length||0)+' 个就诊事件'+(receipt.window_start?' · 随访窗口 '+receipt.window_start+' 至 '+receipt.window_end:''),'receipt'));
  const eligible=(job.fields||[]).filter(field=>(!field.decision||['accept','modify'].includes(field.decision.action))&&!archived(field)).length;
  if(!frozen(job)&&!eligible) {
    section.append(el('p','当前没有待归档的已接受字段。暂缓项可在后续复核，已归档项可发起更正。','help'));
    return section;
  }
  const days=el('select');days.id='days';
  const interval=Number(publication?.followup_days??90);
  for(const day of [...new Set([14,30,90,180,interval])].sort((a,b)=>a-b)) days.append(new Option(day+' 天',String(day)));
  days.value=String(interval);days.disabled=Boolean(publication);
  section.append(label(demo?'随访间隔（合成演示设置）':'随访间隔',days),el('p','按归档的就诊日期生成访视待办，窗口为目标日期前后 14 天，并关联待发送队列。请核对本次随访安排。','help'));
  if(publication) section.append(el('p','本任务沿用首次归档的随访间隔，后续复核与更正不调整排程。','help'));
  if(demo && !frozen(job)) {
    const fault=el('button','模拟下一字段归档失败','text-button');
    fault.type='button';
    fault.onclick=async()=>{
      fault.disabled=true;
      const accepted=(job.fields||[]).filter(field=>(!field.decision||['accept','modify'].includes(field.decision.action))&&!archived(field));
      try {
        await api('demo/fault',{mode:'before_commit',field_id:(accepted[1]||accepted[0])?.id||'*'});
        fault.textContent='已设置一次失败：归档后可演示继续处理';
      } catch(exception) {error(section,exception);fault.disabled=false;}
    };
    section.append(el('p','隔离演示：可注入一次归档失败，验证进度保留与重试。','help'),fault);
  }
  const reviewed=el('input');reviewed.id='reviewed';reviewed.type='checkbox';
  const check=label(frozen(job)?'我已查看归档进度，确认继续同一冻结计划':'我已核对患者、事件和原文依据，确认默认接受项及已保存的处理决定',reviewed,'check');
  const approve=el('button',frozen(job)?'继续归档未完成项':'确认并归档','primary');approve.id='archive_button';approve.type='button';
  const enabled=()=>!busy&&reviewed.checked&&!hasDrafts(job.id)&&job.state!=='publishing';
  const updateButton=()=>{approve.disabled=!enabled();};reviewed.onchange=updateButton;updateButton();
  if(count.pending&&!frozen(job)) section.append(el('p',count.pending+' 项将按原值统一确认接受；已拒绝、暂缓或修改的决定保持不变。','help'));
  approve.onclick=async()=>{
    if(!enabled()) return;
    busy=true;approve.disabled=true;
    try {
      await api('jobs/'+job.id+'/approve',{version:job.version,review_revision:frozen(job)?publication.revision:job.review_revision,
        reviewed:true,followup_days:Number(days.value),accept_defaults:frozen(job)?Boolean(publication.plan?.accept_defaults):true});
    } catch(exception) {error(section,exception);}
    finally {busy=false;signature='';await detail(true);await list();}
  };
  section.append(check,approve);return section;
}
async function detail(force=false) {
  const id=selected, version=sessionVersion;if(!id) return;
  const job=await api('jobs/'+id);
  if(!currentUser||version!==sessionVersion||selected!==id||tab!=='job') return;
  const nextSignature=JSON.stringify([job.id,job.state,job.version,job.review_revision,job.error,job.publication,job.publication_history?.length]);
  if(!force&&signature===nextSignature) return;
  if(!force&&hasDrafts(id)&&signature) {
    const notice=$('draft_notice');
    if(notice) {notice.hidden=false;notice.textContent='服务器状态已更新，当前输入已保留。请刷新最新状态后重新核对；提交时会检查复核版本。';}
    return;
  }
  signature=nextSignature;
  const box=$('content');box.replaceChildren();
  const heading=el('div',undefined,'content-heading');
  heading.append(el('h2',job.filename),el('span',states[job.state]||job.state,'pill'));box.append(heading);
  if(job.patient_context)box.append(el('p','上传时选择患者：'+job.patient_context.name+' · '+job.patient_context.patient_id+'。此身份来自操作员选择，原件身份仍需核对。','patient-selected'));
  if(job.error) error(box,job.error);
  const sourceActions=el('div',undefined,'source-actions'), original=el('a','下载原始资料核对');
  original.href='/api/jobs/'+job.id+'/source';
  const refresh=el('button','刷新最新状态','text-button');refresh.type='button';refresh.onclick=()=>{signature='';detail(true);};
  sourceActions.append(original,refresh);box.append(sourceActions);
  const locateSource=el('button','原件与字段对照','secondary');locateSource.type='button';locateSource.onclick=()=>openSourceReview(job);sourceActions.append(locateSource);
  const draftNotice=el('p','','warning');draftNotice.id='draft_notice';draftNotice.setAttribute('role','status');draftNotice.hidden=true;box.append(draftNotice);
  if(job.method==='local-ocr') box.append(el('p','OCR 可能漏字或识别错误，请对照原始扫描件核对。药名与数值须逐项确认。','warning'));
  if(job.text) {
    const details=el('details',undefined,'source-panel');
    details.append(el('summary','查看资料全文 · '+(methods[job.method]||'文档读取')),el('pre',job.text,'source'));
    if(job.method) details.append(traceDetails('查看读取方式标识',job.method));box.append(details);
  }
  if(job.candidate) {
    const candidate=job.candidate;
    box.append(el('h3',candidate.name+' · '+candidate.patient_id),
      el('p','候选方式：'+(methods[candidate.model]||candidate.model)+' · 复核版本 '+(job.review_revision||0)+'。无问题无需逐项点击；修改、拒绝和暂缓需保存原因，归档时统一确认。','help'));
    const groups=new Map();
    for(const field of job.fields||[]) {
      const key=field.date+':'+field.event_id;
      if(!groups.has(key)) groups.set(key,{date:field.date,event:field.event_id,fields:[]});
      groups.get(key).fields.push(field);
    }
    for(const group of groups.values()) {
      const section=el('section',undefined,'visit');
      section.append(el('h3',group.date),eventLabel(group.event));
      for(const field of group.fields) section.append(reviewFieldCard(job,field));
      box.append(section);
    }
    if(!groups.size) box.append(el('p','当前候选尚无可复核字段。','help'));
    if(groups.size && !job.legacy_read_only) box.append(renderPublication(job));
    if(job.legacy_read_only) box.append(el('p','此任务来自早期整份复核流程，保留原始候选和归档回执；未生成本轮逐字段复核历史。','warning'));
    const history=renderHistory(job);if(history) box.append(history);
  }
  if(['failed','blocked'].includes(job.state)) {
    const retry=el('button','重新提取候选','secondary');retry.type='button';
    retry.onclick=async()=>{
      retry.disabled=true;
      try {await api('jobs/'+job.id+'/retry',{});signature='';await list();}
      catch(exception) {error(box,exception);retry.disabled=false;}
    };box.append(retry);
  }
  updateDirtyNotice(job.id);
}
function timelineFact(fact) {
  const card=el('article',undefined,'timeline-fact'+(fact.current===false?' superseded':''));
  const top=el('div',undefined,'field-heading');
  top.append(el('strong',fieldName(fact.code)),el('span',fact.current===false?'历史版本 · 已替代':'当前有效','badge '+(fact.current===false?'muted':'success')));
  card.append(top,el('p',literal(fact),'candidate-value'),el('blockquote',fact.quote,'quote'));
  if(fact.correction_of) card.append(el('p','更正版本 · 关联前一条归档记录','help'));
  if(fact.reason) card.append(el('p','更正原因：'+fact.reason,'help'));
  if(fact.observation) {
    const trace=el('details');trace.append(el('summary','查看归档标识'),el('p',fact.observation,'resource-id'));
    if(fact.correction_of) trace.append(el('p','前一版本：'+fact.correction_of,'resource-id'));
    card.append(trace);
  }
  if(fact.source_job) {
    const source=el('button','查看该字段来源','text-button');source.type='button';
    source.onclick=()=>{selected=fact.source_job;show('job');};card.append(source);
  }
  for(const old of fact.history||[]) card.append(timelineFact({...old,history:[],current:false}));
  return card;
}
async function show(which,options={}) {
  if(!currentUser) return;
  if(which==='admin'&&currentUser.role!=='admin') return;
  tab=which;const version=++viewVersion;
  const patientSection=['overview','patient','record'].includes(which);
  const departmentSection=['knowledge','analysis','analysis-quick'].includes(which);
  activePatientId=['patient','record'].includes(which)?options.patientId:null;
  if(!patientSection&&!departmentSection&&which!=='account') workbenchTab=which;
  const hash=departmentSection?'#'+which:which==='overview'?'#overview':which==='patient'?'#patient/'+encodeURIComponent(activePatientId):which==='record'?'#record/'+encodeURIComponent(activePatientId):'#workbench';
  if(!options.fromRoute&&location.hash!==hash) history.pushState(null,'',location.pathname+location.search+hash);
  $('workspace_layout').classList.toggle('overview-layout',patientSection||departmentSection);
  $('upload_sidebar').hidden=patientSection||departmentSection;$('workbench_tabs').hidden=patientSection||departmentSection;$('workbench_status').hidden=patientSection||departmentSection;
  $('nav_overview').setAttribute('aria-current',patientSection?'page':'false');$('nav_workbench').setAttribute('aria-current',!patientSection&&!departmentSection?'page':'false');
  $('nav_knowledge').setAttribute('aria-current',which==='knowledge'?'page':'false');$('nav_analysis').setAttribute('aria-current',which.startsWith('analysis')?'page':'false');
  $('workspace_title').textContent=which==='knowledge'?'科室知识问答':which==='analysis'?'门诊处方与随访分析':which==='analysis-quick'?'快速访次核对':['patient','record'].includes(which)?'患者详情':which==='overview'?'患者总览':'科室资料工作台';
  $('workspace_eyebrow').textContent=which==='knowledge'?'提出问题 · 查阅全文 · 核对依据':which==='analysis'?'原处方工作区 · 汇总分析 · 医案传承 · 导入与保存':which==='analysis-quick'?'医案识别 · 逐项核对 · 相邻处方对照':patientSection?'患者档案 · 资料来源 · 访视与指标':'批量提取 · 核对异常 · 纵向归档';
  for(const name of tabs) {
    $('tab_'+name).className=name===which?'selected':'';
    $('tab_'+name).setAttribute('aria-selected',String(name===which));
  }
  const box=$('content');
  box.hidden=which==='analysis';
  $('department_full_analysis').hidden=which!=='analysis';
  $('mode_notice').hidden=which==='analysis';
  $('footer_note').hidden=which==='analysis';
  if(which==='analysis') {
    await window.Department.renderFull($('department_full_analysis'),{api,el,error,isCurrent:()=>Boolean(currentUser)&&tab===which&&version===viewVersion});
    return;
  }
  box.classList.toggle('department',departmentSection);
  if(departmentSection) {
    await window.Department.render(which,box,{api,el,error,isCurrent:()=>Boolean(currentUser)&&tab===which&&version===viewVersion});
    return;
  }
  if(which==='job') {
    signature='';
    if(selected) {
      try {await detail(true);} catch(exception) {if(version===viewVersion){box.replaceChildren();error(box,exception);}}
    } else box.replaceChildren(workbenchGuide());
    return;
  }
  box.replaceChildren(loadingState('正在读取…'));
  try {
    if(which==='overview') {if(overviewSource==='registry') await renderRegistryOverview();else await renderPatientOverview(Boolean(options.refresh));return;}
    if(which==='patient') {await renderPatientDetail(activePatientId);return;}
    if(which==='record') {await renderRegistryDetail(activePatientId);return;}
    if(which==='outbox') {await renderOutbox();return;}
    if(which==='admin') {await renderAdmin();return;}
    if(which==='account') {renderAccount();return;}
    if(which==='patients') {
      const patients=await api('patients');if(tab!==which||version!==viewVersion) return;
      box.replaceChildren(el('h2','纵向档案'),el('p','仅展示已成功归档的字段；同日不同事件分开呈现，更正前的版本保留在原事件下。','help'));
      if(!patients.length) box.append(el('p','归档首个字段后，患者档案会出现在这里。'));
      for(const patient of patients) {
        box.append(el('h3',patient.name+' · '+patient.patient_id));
        for(const visit of patient.visits) {
          const section=el('section',undefined,'visit');
          section.append(el('h3',visit.date),eventLabel(visit.event_id));
          for(const fact of visit.facts) section.append(timelineFact(fact));
          if(visit.source_job) {
            const source=el('button','查看来源与复核历史','secondary');source.type='button';
            source.onclick=()=>{selected=visit.source_job;show('job');};section.append(source);
          }
          box.append(section);
        }
      }
    } else {
      const [tasks,patients]=await Promise.all([api('tasks'),api('patients')]);if(tab!==which||version!==viewVersion) return;
      box.replaceChildren(el('h2','访视待办'),el('p','依据已复核的就诊记录跟踪随访。消息文案与计划日期可在待发送队列中查看。','help'));
      for(const task of tasks) {
        const name=patients.find(patient=>'Patient/'+patient.fhir_id===task.patient)?.name||task.patient||'患者',card=el('div',undefined,'task');
        card.append(el('h3',name),el('p',(task.status==='completed'?'已完成':'待随访')+' · '+(task.window?.start||'未设置')+' 至 '+(task.window?.end||'未设置')));
        if(task.status==='requested') {
          card.append(el('p','审核并归档窗口内的后续访视资料后，系统自动关联就诊记录并完成本任务。','help'));
        }
        for(const reference of task.evidence||[]) card.append(el('p','已审核访视依据：'+reference,'resource-id'));
        box.append(card);
      }
      if(!tasks.length) box.append(el('p','暂无随访任务。'));
    }
  } catch(exception) {if(tab===which&&version===viewVersion){box.replaceChildren();error(box,exception);}}
}
function routeFromHash() {
  if(!currentUser) return;
  if(['#knowledge','#analysis','#analysis-quick'].includes(location.hash)) return show(location.hash.slice(1),{fromRoute:true});
  if(location.hash==='#overview') return show('overview',{fromRoute:true});
  if(location.hash.startsWith('#patient/')) {
    let patientId='';try {patientId=decodeURIComponent(location.hash.slice(9));} catch {patientId='';}
    return show('patient',{fromRoute:true,patientId});
  }
  if(location.hash.startsWith('#record/')) {
    let patientId='';try {patientId=decodeURIComponent(location.hash.slice(8));} catch {patientId='';}
    return show('record',{fromRoute:true,patientId});
  }
  return show(workbenchTab,{fromRoute:true});
}
function patientSourceSwitch() {
  const controls=el('div',undefined,'patient-source-switch');controls.setAttribute('role','group');controls.setAttribute('aria-label','患者资料来源');
  const demoLabel=overviewCache?.detail_schema_version===1?overviewCache.summary.enrolled+'人合成演示':'50人·5年合成演示';
  for(const [value,title] of [['registry','已登记患者'],['demo',demoLabel]]) {
    const button=el('button',title);button.type='button';button.dataset.patientSource=value;button.setAttribute('aria-pressed',String(value===overviewSource));
    button.onclick=()=>{overviewSource=value;return show('overview');};controls.append(button);
  }
  return controls;
}
function attentionData(value) {
  return value&&value.rules_version==='attention-v1'&&typeof value.as_of==='string'&&Object.hasOwn(attentionLabels,value.level)&&Array.isArray(value.items)&&Array.isArray(value.limitations)?value:null;
}
function patientAttentionBadge(button,patient,compact=false) {
  const data=attentionData(patient.attention),level=data?.level||'gray';
  const label=!data?'关注信息暂不可用':data.items.length?attentionLabels[level]:'未识别信号';
  const text=label+(data?.items.length?' · '+data.items.length+' 条':'');
  button.classList.add('attention-target');button.dataset.attentionLevel=level;
  button.setAttribute('aria-label',(button.getAttribute('aria-label')||'查看 '+patient.name+' 的患者详情')+'，复核优先级：'+text);
  const badge=el('span',compact?label:text,compact?'attention-tile-label':'attention-badge');badge.dataset.attentionLevel=level;
  return badge;
}
function patientAttentionPanel(value,synthetic=false) {
  const section=el('section',undefined,'patient-attention');section.setAttribute('aria-label','患者关注提示');
  const data=attentionData(value),level=data?.level||'gray';section.dataset.attentionLevel=level;
  const heading=el('div',undefined,'attention-heading');heading.append(el('h2','关注提示'),el('span','复核优先级','help'));section.append(heading);
  if(!data) {section.append(el('p','关注信息暂不可用。请刷新患者档案或核对资料。','attention-empty'));return section;}
  section.append(el('p',(synthetic?'依据合成记录展示提示':'依据已归档记录自动提示')+'，请结合当前病情复核。四色表示复核优先级，不代表自动临床分诊。','attention-intro'));
  if(data.items.length) {
    const overview=el('p',attentionLabels[level]+' · '+data.items.length+' 条提示 · 截至 '+data.as_of,'attention-summary');section.append(overview);
    const list=el('div',undefined,'attention-items');
    for(const item of data.items) {
      if(!item||typeof item!=='object')continue;
      const itemLevel=Object.hasOwn(attentionLabels,item.level)?item.level:'gray',card=el('article',undefined,'attention-item');card.dataset.attentionLevel=itemLevel;
      const title=el('div',undefined,'attention-item-heading'),badge=el('span',attentionLabels[itemLevel],'attention-badge');badge.dataset.attentionLevel=itemLevel;
      title.append(badge,el('h3',typeof item.title==='string'?item.title:'记录待核对'));card.append(title);
      if(typeof item.summary==='string')card.append(el('p',item.summary));
      if(Array.isArray(item.evidence)&&item.evidence.length) {
        const evidence=el('div',undefined,'attention-evidence');
        for(const record of item.evidence) {
          if(!record||typeof record!=='object')continue;
          const entry=el('div',undefined,'attention-evidence-entry'),names={igg:'免疫球蛋白G（IgG）',c3:'补体C3',c4:'补体C4',dryness:'口干评分',fatigue:'疲劳评分',pain:'疼痛评分',prescription:'处方原文'};
          const field=fields[record.code]||clinicalSections[record.code]||names[record.code]||'来源项目';
          entry.append(el('p',(record.date||'日期未记录')+' · '+field+'：'+String(record.value??'未记录')+(record.unit?' '+record.unit:''),'attention-evidence-value'));
          if(typeof record.quote==='string'&&record.quote)entry.append(el('blockquote',record.quote,'quote'));
          if(!synthetic&&typeof record.source_job==='string'&&record.source_job) {const source=el('button','查看来源与复核记录','text-button');source.type='button';source.onclick=()=>{selected=record.source_job;return show('job');};entry.append(source);}
          evidence.append(entry);
        }
        card.append(evidence);
      }
      if(typeof item.action==='string'&&item.action)card.append(el('p','建议核对：'+item.action,'attention-action'));
      list.append(card);
    }
    section.append(list);
  } else section.append(el('p','未识别到关注信号；资料不足不等于正常。','attention-empty'));
  const limitations=el('details',undefined,'attention-limitations');limitations.append(el('summary','规则与资料限制'+(data.limitations.length?' · '+data.limitations.length+' 项':'')),el('p','记录截止日期：'+data.as_of+'。提示依据本地规则与可用记录生成，不能替代对原件和当前病情的核实。','help'));
  if(data.limitations.length) {const list=el('ul');for(const item of data.limitations)if(typeof item==='string')list.append(el('li',item));limitations.append(list);}
  section.append(limitations);return section;
}
function renderPatientOptions() {
  const box=$('patient_options'), query=$('patient_search').value.trim().toLocaleLowerCase();box.replaceChildren();
  const matches=registryPatients.filter(patient=>(patient.patient_id+' '+patient.name).toLocaleLowerCase().includes(query));
  for(const patient of matches) {
    const button=el('button',undefined,'patient-option');button.type='button';button.dataset.patientId=patient.patient_id;
    button.setAttribute('aria-pressed',String(uploadPatient?.patient_id===patient.patient_id));button.disabled=uploading||patientCreating;
    button.append(el('strong',patient.name),el('small',patient.patient_id));button.onclick=()=>selectUploadPatient(patient);box.append(button);
  }
  if(!matches.length) box.append(el('p',registryLoaded?query?'没有匹配的患者。':'暂无患者，请先新建患者。':'尚未读取患者名单，请点击刷新。','help'));
}
function renderSelectedPatient() {
  const box=$('patient_selected');box.replaceChildren();
  if(uploadPatient) box.append(el('strong','已选：'+uploadPatient.name),el('span',uploadPatient.patient_id));
  else box.append(el('span','尚未选择患者'));
  const bound=uploadBatch.find(item=>item.patient)?.patient;
  if(bound&&uploadPatient&&bound.patient_id!==uploadPatient.patient_id)box.append(el('p','当前批次仍属于 '+bound.name+'（'+bound.patient_id+'）。为新选患者上传时，请重新选择文件。','help'));
  $('upload_button').disabled=uploading||patientCreating||!uploadPatient;
  $('file').disabled=uploading||patientCreating||!uploadPatient;
}
function selectUploadPatient(patient) {
  if(uploading||patientCreating) return;
  uploadPatient={patient_id:patient.patient_id,name:patient.name};renderSelectedPatient();renderPatientOptions();
  $('patient_picker_feedback').textContent='后续新批次将关联此患者；已有批次重试保持原患者。';
}
async function loadRegistry() {
  const version=sessionVersion, request=++registryRequest;
  const data=await api('patient-registry');
  if(!Array.isArray(data.patients)||data.patients.some(patient=>typeof patient.patient_id!=='string'||typeof patient.name!=='string')) throw localizedError('患者名单格式不完整，请刷新重试。');
  if(currentUser&&version===sessionVersion&&request===registryRequest) {registryPatients=data.patients;registryLoaded=true;renderPatientOptions();}
  return data.patients;
}
async function refreshRegistry() {
  if(!currentUser) return;
  const version=sessionVersion;$('patient_refresh').disabled=true;$('patient_picker_feedback').textContent='正在读取患者名单…';
  try {await loadRegistry();if(currentUser&&version===sessionVersion)$('patient_picker_feedback').textContent='';}
  catch(exception) {if(currentUser&&version===sessionVersion)feedbackError($('patient_picker_feedback'),exception);}
  finally {if(currentUser&&version===sessionVersion)$('patient_refresh').disabled=false;}
}
async function renderRegistryOverview() {
  const version=sessionVersion,view=viewVersion,box=$('content');
  const active=()=>currentUser&&version===sessionVersion&&view===viewVersion&&tab==='overview'&&overviewSource==='registry';
  box.replaceChildren(patientSourceSwitch(),loadingState('正在读取已登记患者…'));
  try {
    const patients=await loadRegistry();if(!active())return;
    const heading=pageHeading('已登记患者 · '+patients.length+' 人',()=>show('overview'));
    const create=el('button','新建患者并上传','secondary');create.type='button';create.onclick=async()=>{await show('job');setPatientMode('new');$('patient_create_id').focus();};heading.append(create);
    const search=el('input');search.type='search';search.id='registry_search';search.value=registryQuery;search.placeholder='搜索姓名或患者编号';
    const rows=el('div',undefined,'registry-roster');rows.setAttribute('aria-live','polite');
    const work=el('section',undefined,'care-dashboard');
    box.replaceChildren(patientSourceSwitch(),heading,el('p','登记资料与已归档临床记录。合成演示队列单独查看；新建档案的临床信息等待资料归档后补充。','overview-disclosure'),work,label('查找患者',search,'form-label overview-search'),rows);
    function renderRows() {
      rows.replaceChildren();const query=search.value.trim().toLocaleLowerCase();
      const matches=patients.filter(patient=>(patient.patient_id+' '+patient.name).toLocaleLowerCase().includes(query));
      for(const patient of matches) {
        const row=el('article',undefined,'registry-row'), name=el('button',patient.name,'patient-name');name.type='button';name.onclick=()=>show('record',{patientId:patient.patient_id});
        const identity=el('div');identity.append(name,el('small',patient.patient_id),patientAttentionBadge(name,patient));
        const details=el('p',({female:'女',male:'男',unknown:'性别未记录'})[patient.sex]||'性别未记录','help');
        if(patient.birth_date) details.append(el('span',' · 出生日期 '+patient.birth_date));
        const open=el('button','查看档案','secondary');open.type='button';open.onclick=name.onclick;patientAttentionBadge(open,patient);
        row.append(identity,details,el('span',patient.source==='registered'?'已登记':'历史归档','badge muted'),open);rows.append(row);
      }
      if(!matches.length)rows.append(el('p',query?'没有匹配的患者。':'暂无已登记患者，可先新建患者，再上传资料。','overview-empty'));
    }
    search.oninput=()=>{registryQuery=search.value;renderRows();};renderRows();await mountCareRoster(work,'business',active);
  } catch(exception) {if(active()){box.replaceChildren(patientSourceSwitch(),pageHeading('患者名单暂不可用',()=>show('overview')));error(box,exception);}}
}
function clinicalContextPanel(context,synthetic=false) {
  const section=el('section',undefined,'clinical-context');section.append(el('h2','临床资料'));
  section.append(el('p',synthetic?'以下分类记录均为合成演示资料。':'仅展示已成功归档的原文记录。处方不代表持续服药；未记录不表示没有相关情况。','help'));
  const grid=el('div',undefined,'clinical-context-grid');
  for(const [key,title] of Object.entries(clinicalSections)) {
    const card=el('section',undefined,'clinical-context-card');card.dataset.clinicalSection=key;card.append(el('h3',title));
    const records=Array.isArray(context?.[key])?context[key]:[];
    const ordered=[...records].filter(record=>synthetic||['reviewed_archive','legacy_archive'].includes(record.verification)).sort((a,b)=>String(b.date).localeCompare(String(a.date)));
    if(!ordered.length)card.append(el('p','未记录','help'));
    for(const record of ordered) {
      const item=el('article',undefined,'clinical-context-record');item.dataset.current=String(record.current!==false);
      const heading=el('div',undefined,'field-heading');heading.append(el('strong',record.date||'日期未记录'),el('span',record.current===false?'已被更正':synthetic?'合成记录':record.verification==='legacy_archive'?'历史归档':'已审核归档','badge'+(record.current===false?' muted':' success')));
      item.append(heading,el('p',literal(record)));
      if(record.quote)item.append(el('blockquote',record.quote,'quote'));
      if(synthetic) {if(record.source_label)item.append(el('p',record.source_label,'help'));}
      else if(record.source_job) {const source=el('button','查看原件与复核记录','text-button');source.type='button';source.onclick=()=>{selected=record.source_job;return show('job');};item.append(source);}
      card.append(item);
    }
    grid.append(card);
  }
  section.append(grid);return section;
}
async function renderRegistryDetail(patientId) {
  const version=sessionVersion,view=viewVersion,box=$('content');
  const active=()=>currentUser&&version===sessionVersion&&view===viewVersion&&tab==='record'&&activePatientId===patientId;
  box.replaceChildren(loadingState('正在读取患者档案…','detail'));
  try {
    const patient=await api('patient-registry/'+encodeURIComponent(patientId));if(!active())return;
    if(patient.patient_id!==patientId||typeof patient.name!=='string'||!Array.isArray(patient.visits)||!Array.isArray(patient.documents))throw localizedError('患者档案格式不完整，请刷新重试。');
    $('workspace_title').textContent=patient.name+' · 患者详情';
    const back=el('button','返回已登记患者','text-button patient-back');back.type='button';back.onclick=()=>{overviewSource='registry';return show('overview');};
    const upload=el('button','为此患者上传资料','secondary');upload.type='button';upload.disabled=uploading||patientCreating;upload.onclick=async()=>{if(uploading||patientCreating)return;selectUploadPatient(patient);await show('job');$('file').focus();};
    const refresh=el('button','刷新患者档案','secondary');refresh.type='button';refresh.id='record_refresh';refresh.onclick=()=>show('record',{patientId});
    const riskPanel=patientRiskPanel(patient.risk);
    const heading=el('div',undefined,'patient-heading');heading.append(back,upload,refresh,patientRiskJump(riskPanel));
    const info=el('dl',undefined,'patient-profile');
    for(const [key,value] of [['姓名',patient.name],['患者编号',patient.patient_id],['性别',({female:'女',male:'男'})[patient.sex]||'未记录'],['出生日期',patient.birth_date||'未记录']])info.append(el('dt',key),el('dd',value));
    const carePanel=el('section',undefined,'patient-care');carePanel.append(patientAttentionPanel(patient.attention));
    box.replaceChildren(heading,el('h2','基本信息'),info,carePanel,riskPanel,clinicalContextPanel(patient.clinical_context));
    const timeline=el('section',undefined,'registry-timeline');timeline.append(el('h2','归档病程与指标'));
    if(!patient.visits.length)timeline.append(el('p','暂无已归档就诊记录。上传并复核资料后，记录会显示在这里。','help'));
    else {
      timeline.append(businessMetricPanel(patient.visits));
      for(const visit of patient.visits) {
        const section=el('section',undefined,'visit');section.append(el('h3',visit.date),eventLabel(visit.event_id));
        for(const fact of visit.facts||[])section.append(timelineFact(fact));timeline.append(section);
      }
    }
    box.append(timeline);
    const documents=el('section',undefined,'registry-documents');documents.append(el('h2','检查单与病例 · '+patient.documents.length+' 份'));
    if(!patient.documents.length)documents.append(el('p','尚未上传资料。','help'));
    for(const document of patient.documents) {
      const button=el('button',undefined,'job');button.type='button';button.append(el('span',document.filename),el('small',states[document.state]||'处理中'));
      button.onclick=()=>{selected=document.id;return show('job');};documents.append(button);
    }
    box.append(documents);
    const followups=el('section',undefined,'registry-followups');followups.setAttribute('aria-label','随访记录与计划');box.append(followups);
    $('workspace_title').tabIndex=-1;$('workspace_title').focus();
    await renderPatientFollowups(followups,patientId,active);
    if(active())await mountCarePanel(carePanel,'business',patientId,active);
  } catch(exception) {if(active()){box.replaceChildren(pageHeading('患者详情暂不可用',()=>show('record',{patientId})));error(box,exception);}}
}
async function renderPatientFollowups(section,patientId,active) {
  const heading=el('h2','随访记录与计划'), note=el('p','完成访视表示已有符合窗口的审核就诊记录，不表示消息已送达。随访消息仅排队，暂不发送。','help');
  const loading=el('p','正在同步此患者的随访状态…','help');loading.setAttribute('role','status');section.replaceChildren(heading,note,loading);
  try {
    const data=await api('outbox');if(!active())return;
    if(!Array.isArray(data.items))throw localizedError('随访状态格式不完整，请刷新患者档案后重试。');
    const unsynced=Boolean(data.sync_error), items=data.items.filter(item=>item.patient_id===patientId).sort((a,b)=>String(a.due_date||'').localeCompare(String(b.due_date||''))||String(a.id).localeCompare(String(b.id)));
    section.replaceChildren(heading,note);
    if(unsynced) {const warning=el('p','未同步：当前展示保存的随访状态，尚未核实最新访视变化。请稍后刷新患者档案。','warning');warning.setAttribute('role','status');section.append(warning);}
    if(!items.length)section.append(el('p',unsynced?'保存记录中暂无该患者的随访安排，当前状态尚未同步。':'暂无该患者的随访安排。','help'));
    for(const item of items) {
      const card=el('article',undefined,'patient-followup');card.dataset.followupId=item.id;
      const top=el('div',undefined,'field-heading');
      top.append(el('h3','目标日期：'+(item.due_date||'未设置')),el('span',(unsynced?'保存状态：':'')+(outboxStates[item.status]||'状态未识别')+(unsynced?'（未同步）':''),'badge '+(unsynced||item.status==='cancelled'?'muted':item.status==='completed'?'success':'')));
      card.append(top,el('p','访视窗口：'+(item.window_start||'未设置')+' 至 '+(item.window_end||'未设置'),'help'));
      if(item.job_id) {const source=el('button','查看关联资料与归档依据','text-button');source.type='button';source.onclick=()=>{selected=item.job_id;return show('job');};card.append(source);}
      section.append(card);
    }
  } catch(exception) {
    if(!active())return;
    section.replaceChildren(heading,note,el('p','随访状态暂不可用，临床档案仍可查看。请稍后刷新患者档案。','warning'));
    const feedback=el('div',undefined,'form-feedback');feedbackError(feedback,exception);section.append(feedback);
  }
}
function businessMetricPanel(visits) {
  const panel=el('section',undefined,'patient-chart-section');panel.append(el('h3','主要指标变化'),el('p','按实际日期展示已归档原值；同日不同事件分别保留。仅同单位数值进入图表，未测量不补零。','help'));
  const definitions=[['dryness','口干评分','',1],['fatigue','疲劳评分','',1],['pain','疼痛评分','',1],['igg','免疫球蛋白G（IgG）','g/L',2],['c3','补体C3','g/L',2],['c4','补体C4','g/L',2]];
  const controls=el('div',undefined,'patient-metric-controls'),content=el('div');controls.setAttribute('role','group');controls.setAttribute('aria-label','选择已归档指标');
  const ordered=[...visits].sort((a,b)=>a.date.localeCompare(b.date)||String(a.event_id).localeCompare(String(b.event_id)));
  let selectedMetric='igg';
  function render(code) {
    selectedMetric=code;for(const button of controls.children)button.setAttribute('aria-pressed',String(button.dataset.metric===code));
    const [id,title,unit,precision]=definitions.find(definition=>definition[0]===code),group=['dryness','fatigue','pain'].includes(code)?'symptoms':'measurements';
    const points=ordered.map(visit=>{
      const facts=(visit.facts||[]).filter(fact=>fact.code===code&&fact.current!==false&&fact.unit===unit);
      const raw=facts.length===1?String(facts[0].value):'';
      const value=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw)&&Number.isFinite(Number(raw))?Number(raw):null;
      return {date:visit.date,[group]:{[code]:value},event_id:visit.event_id,raw:facts.length===1?literal(facts[0]):null};
    });
    const definition={code:id,label:title,unit:unit||'分',precision,group};
    content.replaceChildren(el('h3',title),patientMetricPlot(points,definition));
    const table=el('table',undefined,'patient-observations');table.append(el('caption','已归档原始观测 · '+definition.unit));
    const head=el('tr');for(const value of ['日期','事件','数值']) {const th=el('th',value);th.scope='col';head.append(th);}const thead=el('thead');thead.append(head);const body=el('tbody');
    for(const point of points){const row=el('tr');row.append(el('td',point.date),el('td',({morning:'上午',evening:'晚间',afternoon:'下午',followup:'随访'})[point.event_id]||'来源事件'),el('td',point.raw===null?'无可用同单位记录':point.raw));body.append(row);}
    table.append(thead,body);content.append(table);
  }
  for(const [code,title] of definitions){const button=el('button',title);button.type='button';button.dataset.metric=code;button.onclick=()=>render(code);controls.append(button);}
  panel.append(controls,content);render(selectedMetric);return panel;
}
async function loadPatientOverview(refresh=false) {
  if(overviewCache&&!refresh) return overviewCache;
  if(overviewPending&&!refresh) return overviewPending.promise;
  if(refresh) overviewCache=null;
  const version=sessionVersion, request=++overviewFetchVersion;
  const promise=(async()=>{
    const data=await api('demo/patient-overview');
    if(data.synthetic!==true||![1,2].includes(data.detail_schema_version)||!Array.isArray(data.patients)||!data.summary||
      !['enrolled','completed','pending','completion_percent','overdue','in_window','upcoming','visits'].every(key=>Number.isFinite(data.summary[key]))||
      !Array.isArray(data.metric_definitions)||data.metric_definitions.length!==6||
      data.metric_definitions.some(metric=>!['symptoms','measurements'].includes(metric.group)||typeof metric.unit!=='string'||!Number.isInteger(metric.precision))||
      data.patients.some(patient=>!overviewStates[patient.first_followup?.status]||!patient.profile||!Array.isArray(patient.visits)||
        patient.visits.some(visit=>data.metric_definitions.some(metric=>{
          const value=visit[metric.group]?.[metric.code];return value!==null&&!Number.isFinite(value);
        })))) throw localizedError('合成总览数据不完整，请刷新重试。');
    if(data.detail_schema_version===2) {
      const period=data.observation_period,counts=data.summary.attention_counts;
      const validDate=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
      if(!period||!validDate(period.start)||!validDate(period.end)||!Number.isInteger(period.years)||period.years<1||
        period.start>=period.end||Number(period.end.slice(0,4))-Number(period.start.slice(0,4))!==period.years||period.start.slice(4)!==period.end.slice(4)||
        data.as_of!==period.end||!counts||!Object.keys(attentionLabels).every(level=>Number.isInteger(counts[level])&&counts[level]>=0)||
        Object.keys(attentionLabels).reduce((sum,level)=>sum+counts[level],0)!==data.summary.enrolled||
        data.summary.enrolled!==data.patients.length||data.summary.visits!==data.patients.reduce((sum,patient)=>sum+patient.visits.length,0)||
        data.patients.some(patient=>patient.visits.some(visit=>!validDate(visit.date)||visit.date<period.start||visit.date>period.end||
          !['baseline','first_followup','annual_followup'].includes(visit.kind)))) throw localizedError('合成总览时间范围或复核人数不完整，请刷新重试。');
    }
    if(currentUser&&version===sessionVersion&&request===overviewFetchVersion) overviewCache=data;
    return data;
  })();
  overviewPending={promise,request};
  try {return await promise;} finally {if(overviewPending?.request===request) overviewPending=null;}
}
async function renderPatientOverview(refresh=false) {
  const version=sessionVersion, request=++overviewRequest, view=viewVersion, box=$('content');
  const active=()=>currentUser&&version===sessionVersion&&request===overviewRequest&&view===viewVersion&&tab==='overview';
  box.replaceChildren(loadingState('正在读取合成患者总览…'));
  try {
    const data=await loadPatientOverview(refresh);
    if(!active()) return;
    const summary=data.summary,longitudinal=data.detail_schema_version===2,heading=pageHeading('队列与首次随访',()=>show('overview',{refresh:true}));
    const badge=el('span',data.cohort_label,'overview-demo');heading.insertBefore(badge,heading.lastElementChild);
    const periodText=longitudinal?data.observation_period.start+' 至 '+data.observation_period.end+' · 每人 '+data.observation_period.years+' 年记录 · '+summary.visits+' 次模拟访视':'截至 '+data.as_of+' · 首次随访口径 · '+summary.visits+' 次模拟访视';
    const work=el('section',undefined,'care-dashboard');
    box.replaceChildren(patientSourceSwitch(),heading,el('p',periodText,'overview-caption'),
      el('p','本页展示独立合成演示队列，完成状态依据模拟随访访视。原有业务档案与待发送队列单独保留。','overview-disclosure'),work);
    const metrics=el('div',undefined,'overview-metrics');
    for(const [key,title,value,note] of [['enrolled','已纳入患者',summary.enrolled,'独立合成编号'],['completed','首次随访完成',summary.completed,'有模拟访视依据'],['pending','首次随访待完成',summary.pending,'按目标窗口跟进'],['percent','首次随访完成率',summary.completion_percent+'%','分母为 '+summary.enrolled+' 名纳入患者']]) {
      const card=el('div',undefined,'overview-metric');card.dataset.metric=key;
      card.append(el('span',title),el('strong',value),el('small',note));metrics.append(card);
    }
    box.append(metrics);
    if(longitudinal) {
      const counts=el('div',undefined,'overview-attention-counts');counts.setAttribute('aria-label','按患者最高复核优先级统计');
      for(const [level,color] of [['red','红色'],['orange','橙色'],['yellow','黄色'],['gray','灰色']]) {
        const count=el('span',color+' · '+(level==='gray'?'未识别信号或资料待核对':attentionLabels[level])+' '+summary.attention_counts[level]+' 人','attention-badge');count.dataset.attentionLevel=level;counts.append(count);
      }
      box.append(counts);
    }
    const upper=el('div',undefined,'overview-upper'), progress=el('section',undefined,'overview-section'), priority=el('section',undefined,'overview-section overview-priority');
    progress.append(el('h3',longitudinal?'患者复核提示':'首次随访进度'),el('p',longitudinal?'每格代表一位合成患者，点击查看五年记录。颜色与文字表示复核优先级，不代表自动临床分诊。':'每格代表一位合成患者，点击查看详情。方格同时标注复核提示，优先核实的患者以红色突出。','help'));
    const tiles=el('div',undefined,'overview-tiles');tiles.setAttribute('aria-label',longitudinal?'合成患者复核优先级':'合成患者首次随访进度');if(longitudinal)tiles.dataset.colorMode='attention';
    const legend=el('div',undefined,'overview-legend');
    for(const [state,key] of longitudinal?[]:[['completed','completed'],['overdue','overdue'],['in_window','in_window'],['upcoming','upcoming']]) {
      const item=el('span',overviewStates[state]+' '+summary[key]);item.dataset.state=state;legend.append(item);
    }
    progress.append(tiles,longitudinal?el('p','按每位患者的最高复核优先级统计；灰色不等于正常，详情保留资料不足与来源说明。','help'):legend);
    priority.append(el('h3',longitudinal?'优先关注':'优先跟进'),el('p',longitudinal?'按最高复核优先级列出前 6 人，点击核对提示与来源。':'已逾期 '+summary.overdue+' 人 · 窗口内 '+summary.in_window+' 人','help'));
    const priorityList=el('ul',undefined,'overview-priority-list');priority.append(priorityList);upper.append(progress,priority);box.append(upper);
    const roster=el('section',undefined,'overview-roster');roster.append(el('h3','患者名单'));
    const search=el('input');search.type='search';search.id='overview_search';search.placeholder='搜索姓名或合成编号';search.autocomplete='off';
    roster.append(label('搜索患者',search,'form-label overview-search'));
    const filters=el('div',undefined,'overview-filters');filters.setAttribute('role','group');filters.setAttribute('aria-label','首次随访状态筛选');
    let filter=overviewFilter;search.value=overviewQuery;
    for(const [state,title,count] of [['all','全部',summary.enrolled],['pending','待完成',summary.pending],['completed','已完成',summary.completed],['overdue','已逾期',summary.overdue],['in_window','窗口内',summary.in_window],['upcoming','未到期',summary.upcoming]]) {
      const button=el('button',title+' '+count);button.type='button';button.dataset.filter=state;button.setAttribute('aria-pressed',String(state===filter));
      button.onclick=()=>{filter=state;overviewFilter=state;for(const item of filters.children)item.setAttribute('aria-pressed',String(item.dataset.filter===filter));renderRows();};filters.append(button);
    }
    const resultCount=el('p','','help');resultCount.id='overview_result_count';resultCount.setAttribute('role','status');
    const table=el('table',undefined,'overview-table');table.setAttribute('aria-label','合成患者名单');
    const head=el('thead'), headRow=el('tr');
    for(const title of ['患者','入组日期','首次随访','首次目标日期','最近访视','详情']) {const cell=el('th',title);cell.scope='col';headRow.append(cell);}
    head.append(headRow);const body=el('tbody');table.append(head,body);
    const empty=el('p','没有符合条件的患者，请修改搜索或筛选条件。','overview-empty');empty.hidden=true;
    const reset=el('button','清除搜索与筛选','text-button');reset.type='button';reset.hidden=true;
    reset.onclick=()=>{search.value='';overviewQuery='';filter='all';overviewFilter='all';for(const button of filters.children)button.setAttribute('aria-pressed',String(button.dataset.filter==='all'));renderRows();};
    roster.append(filters,resultCount,table,empty,reset);box.append(roster);
    const links=el('div',undefined,'overview-return');
    for(const [title,target] of [['返回原文与复核','job'],['查看已归档档案','patients']]) {const button=el('button',title,'secondary');button.type='button';button.onclick=()=>show(target);links.append(button);}
    box.append(links,el('p','合成队列只供展示，不创建业务归档、发送任务或患者消息。','help'));
    function statusBadge(patient) {
      const badge=el('span',overviewStates[patient.first_followup.status],'overview-status');badge.dataset.state=patient.first_followup.status;return badge;
    }
    function openPatient(patient) {
      return show('patient',{patientId:patient.id});
    }
    function renderRows() {
      const query=search.value.trim().toLocaleLowerCase();
      const patients=data.patients.filter(patient=>(filter==='all'||(filter==='pending'?patient.first_followup.status!=='completed':patient.first_followup.status===filter))&&
        (patient.name+' '+patient.id).toLocaleLowerCase().includes(query));
      body.replaceChildren();resultCount.textContent='显示 '+patients.length+' / '+summary.enrolled+' 名合成患者';empty.hidden=patients.length>0;table.hidden=!patients.length;reset.hidden=filter==='all'&&!query;
      for(const patient of patients) {
        const row=el('tr');row.dataset.patientId=patient.id;
        const values=[['患者',null],['入组日期',patient.enrolled_at],['首次随访',null],['首次目标日期',patient.first_followup.due_date],['最近访视',patient.last_visit],['详情',null]];
        values.forEach(([caption,value],index)=>{
          const cell=el('td',value);cell.dataset.label=caption;
          if(index===0) {const name=el('button',patient.name,'patient-name');name.type='button';name.setAttribute('aria-label','打开 '+patient.name+' 的患者详情');name.onclick=()=>openPatient(patient);cell.append(name,el('small',patient.id,'resource-id'),patientAttentionBadge(name,patient));}
          if(index===2) cell.append(statusBadge(patient));
          if(index===5) {const button=el('button','查看详情','text-button');button.type='button';button.setAttribute('aria-label','查看 '+patient.name+' 的合成访视详情');button.onclick=()=>openPatient(patient);patientAttentionBadge(button,patient);cell.append(button);}
          row.append(cell);
        });body.append(row);
      }
    }
    for(const [index,patient] of data.patients.entries()) {
      const tile=el('button',String(index+1).padStart(2,'0'),'overview-tile');tile.type='button';tile.dataset.patientId=patient.id;tile.dataset.state=patient.first_followup.status;
      tile.setAttribute('aria-pressed','false');tile.setAttribute('aria-label',patient.name+'，'+overviewStates[patient.first_followup.status]+'，查看详情');tile.append(patientAttentionBadge(tile,patient,true));tile.onclick=()=>openPatient(patient);tiles.append(tile);
    }
    const priorityPatients=longitudinal?data.patients.filter(item=>attentionData(item.attention)&&['red','orange','yellow'].includes(item.attention.level)&&item.attention.items.length)
      .sort((a,b)=>['red','orange','yellow'].indexOf(a.attention.level)-['red','orange','yellow'].indexOf(b.attention.level)||a.id.localeCompare(b.id)).slice(0,6):
      data.patients.filter(item=>['overdue','in_window'].includes(item.first_followup.status)).sort((a,b)=>a.first_followup.window_end.localeCompare(b.first_followup.window_end));
    for(const patient of priorityPatients) {
      const item=el('li'), button=el('button',undefined,'overview-priority-button');button.type='button';
      const name=el('span');name.append(el('strong',patient.name),el('small',longitudinal?'记录截至 '+patient.attention.as_of:'窗口截至 '+patient.first_followup.window_end));
      button.append(name);if(!longitudinal)button.append(statusBadge(patient));button.setAttribute('aria-label','查看 '+patient.name+'，'+overviewStates[patient.first_followup.status]);name.append(patientAttentionBadge(button,patient));button.onclick=()=>openPatient(patient);item.append(button);priorityList.append(item);
    }
    if(!priorityList.childElementCount) priorityList.append(el('li',longitudinal?'暂无红、橙、黄色复核提示；资料不足不等于正常。':'暂无处于逾期或窗口内的患者。','help'));
    search.oninput=()=>{overviewQuery=search.value;renderRows();};renderRows();await mountCareRoster(work,'demo',active);
  } catch(exception) {
    if(!active()) return;
    box.replaceChildren(el('h2','患者总览暂不可用'));error(box,exception);
    const retry=el('button','重新读取总览','secondary');retry.type='button';retry.onclick=()=>show('overview',{refresh:true});box.append(retry);
  }
}
function svgElement(tag,attributes={},text) {
  const node=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [key,value] of Object.entries(attributes)) node.setAttribute(key,String(value));
  if(text!==undefined) node.textContent=text;return node;
}
function metricValue(value,definition) {
  return value===null?'未测量':String(value)+' '+definition.unit;
}
function metricChange(visits,definition) {
  if(visits.length<2) return '仅1次记录，无法比较';
  const first=visits[0][definition.group][definition.code], last=visits.at(-1)[definition.group][definition.code];
  if(first===null||last===null) return '端点未测量，无法比较';
  const difference=Number((last-first).toFixed(definition.precision));
  return (difference>0?'+':difference<0?'−':'')+Math.abs(difference).toFixed(definition.precision)+' '+definition.unit;
}
function patientMetricPlot(visits,definition,events=[],suffix='') {
  const container=el('div',undefined,'patient-plot');
  const points=visits.map(visit=>({date:visit.date,day:Date.parse(visit.date+'T00:00:00Z')/86400000,value:visit[definition.group][definition.code]}));
  const valid=points.filter(point=>point.value!==null);
  if(!valid.length) {container.append(el('p','该指标尚无测量记录，暂不生成曲线。','patient-plot-empty'));return container;}
  const width=640,height=300,left=62,right=42,top=32,bottom=54,plotWidth=width-left-right,plotHeight=height-top-bottom;
  const eventDays=events.map(item=>Date.parse(item.date+'T00:00:00Z')/86400000);
  const start=Math.min(points[0].day,...eventDays),end=Math.max(points.at(-1).day,...eventDays);
  const maximum=Math.max(...valid.map(point=>point.value));
  const yMax=definition.group==='symptoms'?10:maximum>0?maximum*1.15:1;
  const x=point=>start===end?left+plotWidth/2:left+(point.day-start)/(end-start)*plotWidth;
  const y=value=>top+plotHeight-value/yMax*plotHeight;
  const chart=svgElement('svg',{viewBox:'0 0 '+width+' '+height,role:'img','aria-labelledby':'patient_chart_title'+suffix+' patient_chart_desc'+suffix,class:'patient-chart'});
  chart.dataset.metric=definition.code;chart.dataset.yMax=String(yMax);
  chart.append(svgElement('title',{id:'patient_chart_title'+suffix},definition.label+'随访变化'),
    svgElement('desc',{id:'patient_chart_desc'+suffix},'横轴为实际访视日期，纵轴单位为'+definition.unit+'。'+points.map(point=>point.date+'：'+metricValue(point.value,definition)).join('；')+'。缺失测量不补零、不连线。'));
  for(let step=0;step<=4;step++) {
    const value=yMax*step/4,position=y(value);
    chart.append(svgElement('line',{x1:left,y1:position,x2:width-right,y2:position,class:'chart-grid'}),
      svgElement('text',{x:left-10,y:position+4,'text-anchor':'end',class:'chart-axis-label'},String(Number(value.toFixed(Math.max(definition.precision,2))))));
  }
  chart.append(svgElement('text',{x:left,y:16,class:'chart-unit'},definition.unit));
  const dates=points.filter((point,index)=>index===0||point.day!==points[index-1].day);
  const ticks=dates.length<=3?dates:[dates[0],dates[Math.floor((dates.length-1)/2)],dates.at(-1)];
  for(const [index,point] of ticks.entries()) chart.append(svgElement('text',{x:x(point),y:height-22,'text-anchor':ticks.length===1?'middle':index===0?'start':index===ticks.length-1?'end':'middle',class:'chart-date'},point.date));
  let segment=[];
  const finish=()=>{if(segment.length>=2) chart.append(svgElement('polyline',{points:segment.map(point=>x(point)+','+y(point.value)).join(' '),fill:'none',class:'chart-line'}));segment=[];};
  for(const point of points) {if(point.value===null) finish();else segment.push(point);}finish();
  for(const point of valid) {
    const marker=svgElement('circle',{cx:x(point),cy:y(point.value),r:5,tabindex:'0',role:'graphics-symbol','aria-label':point.date+'，'+definition.label+' '+metricValue(point.value,definition),class:'chart-point'});
    marker.dataset.date=point.date;marker.dataset.value=String(point.value);marker.dataset.day=String(point.day);
    marker.append(svgElement('title',{},point.date+' · '+metricValue(point.value,definition)));chart.append(marker);
  }
  for(const date of [...new Set(events.map(item=>item.date))]) {
    const at=x({day:Date.parse(date+'T00:00:00Z')/86400000}),group=events.filter(item=>item.date===date);
    const marker=svgElement('line',{x1:at,x2:at,y1:top,y2:height-bottom,class:'care-event-marker',tabindex:0,'aria-label':date+' · '+group.map(item=>item.title).join('；')});
    marker.append(svgElement('title',{},date+' · '+group.map(item=>item.title).join('；')));chart.append(marker);
    chart.append(svgElement('text',{x:at,y:height-bottom+14,'text-anchor':'middle',class:'care-event-count'},group.length+'项'));
  }
  container.append(chart);
  if(points.length===1) container.append(el('p','仅有1次观测，以单点显示；取得后续记录后才能比较变化。','help'));
  else if(valid.length!==points.length) container.append(el('p','缺失测量不补零，曲线在缺失处断开。','help'));
  return container;
}
async function renderPatientDetail(patientId) {
  overviewSource='demo';
  const version=sessionVersion,view=viewVersion,box=$('content');
  const active=()=>currentUser&&version===sessionVersion&&view===viewVersion&&tab==='patient'&&activePatientId===patientId;
  box.replaceChildren(loadingState('正在读取合成患者详情…','detail'));
  try {
    const data=await loadPatientOverview();if(!active()) return;
    const patient=data.patients.find(item=>item.id===patientId);
    const back=el('button','返回患者名单','text-button patient-back');back.type='button';back.onclick=()=>show('overview');
    if(!patient) {box.replaceChildren(back,el('h2','未找到这位合成患者'),el('p','请返回患者名单，重新选择需要查看的患者。','help'));return;}
    $('workspace_title').textContent=patient.name+' · 患者详情';
    const riskPanel=patientRiskPanel(patient.risk,true);
    const heading=el('div',undefined,'patient-heading');heading.append(back,el('span',data.cohort_label+' · 截至 '+data.as_of,'overview-demo'),patientRiskJump(riskPanel));
    box.replaceChildren(heading,el('p','本页人口学、病情记录和测量值均为合成演示资料。','overview-disclosure'));
    if(data.detail_schema_version===2)box.append(el('p',data.observation_period.start+' 至 '+data.observation_period.end+' · '+data.observation_period.years+' 年 · '+patient.visits.length+' 次模拟访视','overview-caption'));
    const grid=el('div',undefined,'patient-detail-grid'), left=el('div',undefined,'patient-context'), right=el('div',undefined,'patient-measurements');
    const profile=el('section',undefined,'patient-section');profile.append(el('h2','基本信息'),el('p',patient.id,'resource-id'));
    const facts=el('dl',undefined,'patient-profile'), sex={female:'女',male:'男',unknown:'未记录'};
    for(const [key,value] of [['姓名',patient.name],['性别',sex[patient.profile.sex]||'未记录'],['入组年龄',patient.profile.age_at_enrollment===null?'未记录':patient.profile.age_at_enrollment+' 岁'],['病情标签',patient.profile.condition_label],['入组日期',patient.enrolled_at],['最近访视',patient.last_visit]]) facts.append(el('dt',key),el('dd',value));
    const first=patient.first_followup,status=el('span',overviewStates[first.status],'overview-status');status.dataset.state=first.status;
    const firstHistory=el('details',undefined,'patient-first-history');firstHistory.append(el('summary','首次随访依据与下一轮目标'),status,el('p','首次目标：'+first.due_date,'help'),el('p','首次窗口：'+first.window_start+' 至 '+first.window_end,'help'));
    if(first.status==='completed') firstHistory.append(el('p','完成日期：'+first.completed_at,'help'),el('p','完成依据：'+first.evidence_visit_id,'resource-id'),el('p','下一轮目标：'+patient.next_due_date+(data.detail_schema_version===2?'（按最近访视安排，与首次随访分开计算）':'（与首次随访分开计算）'),'help'));
    else firstHistory.append(el('p','尚无完成首次随访的模拟访视依据。','help'));
    profile.append(facts,firstHistory);
    const carePanel=el('section',undefined,'patient-care');carePanel.append(patientAttentionPanel(patient.attention,true));box.append(profile,carePanel,riskPanel);
    const timeline=el('section',undefined,'patient-section patient-condition');timeline.append(el('h2','病情与访视记录'));
    const visitList=el('ol',undefined,'patient-timeline');
    for(const visit of patient.visits) {
      const item=el('li');item.dataset.visitId=visit.id;
      item.append(el('h3',visit.date+' · '+(visit.kind==='baseline'?'入组访视':visit.kind==='annual_followup'?'年度随访':'首次随访')),el('p',visit.condition_note),el('p',visit.source_label,'help'));
      const values=el('dl',undefined,'patient-visit-values');
      for(const metric of data.metric_definitions) values.append(el('dt',metric.label),el('dd',metricValue(visit[metric.group][metric.code],metric)));
      item.append(values,el('small',visit.id,'resource-id'));visitList.append(item);
    }
    timeline.append(visitList);left.append(timeline);
    const chartSection=el('section',undefined,'patient-section patient-chart-section');chartSection.append(el('h2','指标变化'),el('p','按访视日期展示原始观测，变化为最近记录减入组记录。','help'));
    const controls=el('div',undefined,'patient-metric-controls');controls.setAttribute('role','group');controls.setAttribute('aria-label','选择查看的指标');
    const chartContent=el('div');chartContent.id='patient_metric_content';chartContent.setAttribute('aria-live','polite');
    let selectedMetric=data.metric_definitions.find(item=>item.code==='igg')||data.metric_definitions[0];
    for(const metric of data.metric_definitions) {
      const button=el('button',metric.label);button.type='button';button.dataset.metric=metric.code;button.setAttribute('aria-pressed',String(metric.code===selectedMetric.code));
      button.onclick=()=>{selectedMetric=metric;for(const control of controls.children)control.setAttribute('aria-pressed',String(control.dataset.metric===metric.code));renderMetric();};controls.append(button);
    }
    function renderMetric() {
      const metric=selectedMetric,visits=patient.visits,baseline=visits[0],latest=visits.at(-1),summary=el('div',undefined,'patient-metric-summary');
      for(const [key,title,value,date] of [['baseline','入组记录',metricValue(baseline[metric.group][metric.code],metric),baseline.date],['latest','最近记录',metricValue(latest[metric.group][metric.code],metric),latest.date],['change','较入组变化',metricChange(visits,metric),'最近减入组']]) {
        const card=el('div');card.dataset.metricSummary=key;card.append(el('span',title),el('strong',value),el('small',date));summary.append(card);
      }
      chartContent.replaceChildren(el('h3',metric.label+'（'+metric.unit+'）'),summary,patientMetricPlot(visits,metric));
      const table=el('table',undefined,'patient-observations');table.setAttribute('aria-label',metric.label+'原始观测表');
      const caption=el('caption','原始观测 · '+metric.label+' · 单位：'+metric.unit),head=el('thead'),row=el('tr');
      for(const title of ['访视日期','访视类型','原始值']) {const cell=el('th',title);cell.scope='col';row.append(cell);}head.append(row);
      const body=el('tbody');
      for(const visit of visits) {const row=el('tr');row.append(el('td',visit.date),el('td',visit.kind==='baseline'?'入组':visit.kind==='annual_followup'?'年度随访':'首次随访'),el('td',metricValue(visit[metric.group][metric.code],metric)));body.append(row);}
      table.append(caption,head,body);chartContent.append(table);
    }
    chartSection.append(controls,chartContent);right.append(chartSection);renderMetric();
    grid.append(left,right);const original=el('details',undefined,'patient-original-details');original.append(el('summary','原始访视与指标明细'),grid);box.append(original,clinicalContextPanel(patient.clinical_context,true));
    $('workspace_title').tabIndex=-1;$('workspace_title').focus();
    await mountCarePanel(carePanel,'demo',patientId,active);
  } catch(exception) {
    if(!active()) return;
    box.replaceChildren(el('h2','患者详情暂不可用'));error(box,exception);
    const retry=el('button','重新读取详情','secondary');retry.type='button';retry.onclick=async()=>{overviewCache=null;await show('patient',{patientId});};
    const back=el('button','返回患者名单','text-button');back.type='button';back.onclick=()=>show('overview');box.append(retry,back);
  }
}
function patientRiskJump(panel) {
  const button=el('button','查看个人风险','secondary');button.type='button';button.setAttribute('aria-controls','patient_risk');
  button.onclick=()=>{panel.scrollIntoView({block:'start'});panel.focus({preventScroll:true});};return button;
}
function patientRiskPanel(risk,synthetic=false) {
  const panel=el('section',undefined,'patient-risk');panel.id='patient_risk';panel.tabIndex=-1;panel.setAttribute('aria-label','个人风险预测');
  const heading=el('div',undefined,'risk-heading');heading.append(el('h2','个人风险预测'),el('span',synthetic?'合成模型演示':'临床模型待验证','risk-mode'));panel.append(heading);
  // Business pages never render demo probabilities, even if an inconsistent DTO arrives.
  if(!synthetic) {
    panel.dataset.riskState='clinical_unavailable';
    panel.append(el('p','当前尚未启用真实患者的个人风险百分比。','risk-state'));
    const reasons=el('ul',undefined,'risk-reasons');
    const items=risk?.mode==='clinical'&&risk.status==='clinical_unavailable'&&Array.isArray(risk.reasons)?risk.reasons.filter(item=>typeof item==='string'):[];
    for(const text of items.length?items:['需要明确病情活动加重与感染结局，补齐经确认的随访结局，并完成模型验证和临床审核。'])reasons.append(el('li',text));
    panel.append(reasons,el('p','现有关注提示和归档病程继续保留。合成演示结果可在“50人合成演示”中查看。','help'));return panel;
  }
  panel.append(el('p','模型由独立合成数据训练，展示计算流程；没有经过临床验证。','risk-disclosure'));
  const validDate=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
  const available=risk?.schema_version===1&&risk.mode==='synthetic_demo'&&risk.status==='available'&&typeof risk.model_version==='string'&&validDate(risk.index_date);
  const models=available&&Array.isArray(risk.models)?risk.models:[];
  const validModels=models.length===2&&['activity_worsening','infection'].every(id=>models.filter(model=>model?.id===id).length===1)&&models.every(model=>typeof model.label==='string'&&Array.isArray(model.estimates)&&model.estimates.length===3&&model.estimates.every((point,index)=>point&&point.days===[90,180,365][index]&&typeof point.risk==='number'&&Number.isFinite(point.risk)&&point.risk>=0&&point.risk<=1&&(index===0||point.risk>=model.estimates[index-1].risk)&&validDate(point.date)&&Date.parse(point.date+'T00:00:00Z')-Date.parse(risk.index_date+'T00:00:00Z')===point.days*86400000));
  if(!available||!validModels) {
    panel.dataset.riskState=risk?.status==='input_unavailable'?'input_unavailable':'model_unavailable';
    panel.append(el('p',risk?.status==='input_unavailable'?'入组资料不足，暂无法生成模拟预测。':'模拟模型暂不可用。','risk-state'));
    const reasons=el('ul',undefined,'risk-reasons');
    const items=Array.isArray(risk?.reasons)?risk.reasons.filter(item=>typeof item==='string'):[];
    for(const text of items.length?items:['请刷新患者档案重试；原始资料与其他功能仍可查看。'])reasons.append(el('li',text));
    panel.append(reasons);return panel;
  }
  panel.dataset.riskState='available';
  panel.append(el('p',risk.index_date+' 入组日起 365 天 · 历史模拟，非当前风险','risk-index'),el('p','感染与活动加重事件由模拟生成器定义，尚无经审核的临床结局标准。曲线连接三个预测时点。','risk-disclosure'));
  const grid=el('div',undefined,'risk-models');
  const ordered=['activity_worsening','infection'].map(id=>models.find(model=>model.id===id));
  const percent=value=>(value*100).toFixed(1)+'%';
  for(const model of ordered) {
    const card=el('section',undefined,'risk-model');card.dataset.riskModel=model.id;
    card.append(el('h3',model.label));
    const value=el('div',undefined,'risk-value');value.append(el('strong',percent(model.estimates[2].risk)),el('span','模拟 · 12个月（365天）'));card.append(value);
    const svg=svgElement('svg',{viewBox:'0 0 440 182',role:'img','aria-label':model.label+'模拟累积发生概率曲线，具体数值见下表',class:'risk-chart'});
    svg.append(svgElement('title',{},model.label+' · 合成模型演示'));
    const x=days=>58+days/365*356,y=value=>140-value*116;
    for(const tick of [0,0.5,1])svg.append(svgElement('line',{x1:58,y1:y(tick),x2:414,y2:y(tick),class:'risk-grid'}),svgElement('text',{x:48,y:y(tick)+4,'text-anchor':'end',class:'risk-axis'},(tick*100)+'%'));
    const points=[{days:0,risk:0},...model.estimates];
    svg.append(svgElement('polyline',{points:points.map(point=>x(point.days)+','+y(point.risk)).join(' '),fill:'none',class:'risk-line'}));
    for(const point of model.estimates) {
      const dot=svgElement('circle',{cx:x(point.days),cy:y(point.risk),r:4,class:'risk-point'});dot.append(svgElement('title',{},point.days+'天 · 模拟 '+percent(point.risk)));svg.append(dot);
      svg.append(svgElement('text',{x:x(point.days),y:165,'text-anchor':point.days===365?'end':'middle',class:'risk-axis'},({90:'3个月',180:'6个月',365:'12个月'})[point.days]));
    }
    card.append(svg);
    const table=el('table',undefined,'risk-estimates');table.setAttribute('aria-label',model.label+'模拟预测值');
    table.append(el('caption','入组起累计发生概率 · 均为模拟结果'));
    const head=el('thead'),row=el('tr');for(const text of ['时点','截至日期','模拟概率']){const cell=el('th',text);cell.scope='col';row.append(cell);}head.append(row);
    const body=el('tbody');
    for(const point of model.estimates){const row=el('tr');row.append(el('td',({90:'3个月 / 90天',180:'6个月 / 180天',365:'12个月 / 365天'})[point.days]),el('td',point.date),el('td',percent(point.risk)+'（模拟）'));body.append(row);}
    table.append(head,body);card.append(table);grid.append(card);
  }
  panel.append(grid);
  const details=el('details',undefined,'risk-inputs');details.append(el('summary','查看入组指标、来源与模型版本'));
  details.append(el('p','两项模型使用同一入组时点的指标；缺失不补零，后续访视不用于填补入组资料。','help'));
  const inputs=el('dl',undefined,'risk-features');
  for(const feature of Array.isArray(risk.features)?risk.features:[]) {
    if(!feature||typeof feature.label!=='string')continue;
    const value=typeof feature.value==='number'&&Number.isFinite(feature.value)?String(feature.value)+(typeof feature.unit==='string'?' '+feature.unit:''):'未记录';
    const item=el('div');item.append(el('dt',feature.label),el('dd',value),el('dd','来源日期：'+(validDate(feature.source_date)?feature.source_date:'未记录'),'help'),el('dd',typeof feature.source_ref==='string'?feature.source_ref:'来源未记录','risk-source'));inputs.append(item);
  }
  details.append(inputs,el('p','模型版本：'+risk.model_version,'risk-version'),el('p','模型方法：Cox 比例风险模型。预测值来自合成训练数据，不能据此判断真实预后或调整治疗。','help'));panel.append(details);return panel;
}
function careInput(form,title,value='',type='text',required=false) {
  const input=el(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;else input.rows=2;
  input.value=value??'';input.required=required;input.maxLength=type==='textarea'?1000:200;
  form.append(label(title,input,'form-label'));return input;
}
function careChoice(form,title,choices,value) {
  const group=el('div',undefined,'decision-buttons');group.setAttribute('role','group');group.setAttribute('aria-label',title);
  const result={value};
  for(const [key,text] of Object.entries(choices)) {const button=el('button',text,'secondary');button.type='button';button.dataset.value=key;button.setAttribute('aria-pressed',String(value===key));
    button.onclick=()=>{result.value=key;for(const child of group.children)child.setAttribute('aria-pressed',String(child.dataset.value===key));group.dispatchEvent(new Event('input',{bubbles:true}));};group.append(button);}
  form.append(el('p',title,'field-caption'),group);return result;
}
function careEvidence(form,data,selected=[]) {
  const group=el('details',undefined,'care-evidence');group.append(el('summary','关联原始依据（可多选）'));const inputs=[];
  for(const ref of data.evidence_refs) {const input=el('input');input.type='checkbox';input.checked=selected.includes(ref);input.dataset.reference=ref;group.append(label(ref.startsWith('visit:')?'模拟访视 '+ref.slice(6):'归档资料 '+ref.slice(4),input));inputs.push(input);}
  if(!inputs.length)group.append(el('p','暂无可关联的归档来源；请明确填写人工记录依据。','help'));form.append(group);
  return ()=>inputs.filter(input=>input.checked).map(input=>input.dataset.reference);
}
function wireCareForm(form,collect,key,data,kind,id,revision,active,reload) {
  const feedback=el('p','','form-feedback');feedback.setAttribute('role','status');
  const save=el('button','保存记录','secondary');save.type='submit';form.append(save,feedback);
  let saving=false;form.oninput=()=>careDrafts.set(key,collect());
  form.onsubmit=async event=>{
    event.preventDefault();if(!active()||saving||!form.reportValidity())return;
    const body=collect();careDrafts.set(key,body);saving=true;save.disabled=true;feedback.textContent='正在保存…';
    try {await api('care/'+data.scope+'/'+encodeURIComponent(data.patient_id)+'/'+kind+'/'+encodeURIComponent(id),{expected_revision:revision,data:body});
      careDrafts.delete(key);if(active())await reload();
    } catch(exception) {if(active())feedbackError(feedback,exception,' 输入已保留。');}
    finally {saving=false;save.disabled=false;}
  };
}
function careActionForm(data,item,active,reload) {
  const details=el('details',undefined,'care-action-form'),record=item.review,key=data.scope+':'+data.patient_id+':attention:'+item.signal_key;
  const value=careDrafts.get(key)||record.body;
  details.append(el('summary','处理记录 · '+careStates[record.body.state]+(record.body.owner?' · '+record.body.owner:'')));
  if(record.revision||record.actor)details.append(el('p',(record.actor==='synthetic-scenario'?'合成场景':record.actor||'')+' · '+timeLabel(record.recorded_at)+' · 版本 '+record.revision,'help'));
  if(record.body.note)details.append(el('p',record.body.note));
  if(record.body.evidence_note)details.append(el('p','处置依据：'+record.body.evidence_note));
  const form=el('form');form.dataset.careKind='attention';
  const state=careChoice(form,'处理状态',careStates,value.state),owner=careInput(form,'负责人',value.owner||currentUser.username),due=careInput(form,'跟进日期（可留空）',value.due_date,'date');
  const disposition=careChoice(form,'复核结论',{confirmed:'确认记录',already_managed:'已有处置依据',not_applicable:'核实为不适用',needs_followup:'需要继续跟进'},value.disposition);
  const note=careInput(form,'处理说明 / 重新打开原因',value.note,'textarea',true),evidence=careInput(form,'处置依据（完成复核时必填）',value.evidence_note,'textarea');
  const refs=careEvidence(form,data,value.evidence_refs);
  form.append(el('p','已阅保留原优先级。需要继续跟进时，请选“处理中”并填写跟进日期；完成复核需记录依据。原报告和历史持续保留。','help'));
  wireCareForm(form,()=>({state:state.value,owner:owner.value,due_date:due.value||null,note:note.value,
    disposition:disposition.value,evidence_note:evidence.value,evidence_refs:refs()}),key,data,'attention',item.signal_key,record.revision,active,reload);
  details.append(form);return details;
}
function careRecordEditor(data,kind,record,active,reload) {
  const id=record?.item_id||crypto.randomUUID(),key=data.scope+':'+data.patient_id+':'+kind+':'+(record?.item_id||'new');
  const value=careDrafts.get(key)||record?.body||{},details=el('details',undefined,'care-editor');
  details.append(el('summary',record?'编辑记录 · '+(value.title||value.visit_date):kind==='event'?'记录用药、感染或住院事件':'填写结构化随访'));
  const form=el('form');form.dataset.careKind=kind;let collect;
  if(kind==='event') {
    const category=careChoice(form,'事件分类',careCategories,value.category||'medication');
    const title=careInput(form,'记录标题',value.title,'text',true),date=careInput(form,'事件日期',value.date||data.as_of,'date',true),end=careInput(form,'结束日期（未知时留空）',value.end_date,'date');
    const source=careChoice(form,'信息来源',{clinician_record:'医务记录',patient_report:'患者报告',unknown:'待核实'},value.source_type||'unknown');
    const drug=careInput(form,'药物名称（用药记录必填）',value.drug_name),dose=careInput(form,'剂量及单位（未知时留空）',value.dose),frequency=careInput(form,'频次（未知时留空）',value.frequency),route=careInput(form,'给药途径（未知时留空）',value.route);
    const status=careChoice(form,'记录状态',{unknown:'未知',current:'记录为在用',stopped:'记录为停用',active:'事件进行中',resolved:'有结束依据'},value.status||'unknown');
    const site=careInput(form,'感染部位 / 事件部位',value.site),description=careInput(form,'具体记录与依据',value.details,'textarea');
    const merge=el('select');merge.append(new Option('保持独立事件',''));
    for(const entry of data.timeline.filter(item=>item.kind==='event'&&item.id!==id&&item.record.body.category==='infection'&&!item.record.body.merged_into))merge.append(new Option(entry.date+' · '+entry.record.body.title,entry.id));
    merge.value=value.merged_into||'';form.append(label('同一次感染的重复记录（核实后关联）',merge));
    const reason=careInput(form,'保存或更正原因',value.note,'textarea',true),refs=careEvidence(form,data,value.evidence_refs);
    collect=()=>({category:category.value,date:date.value,end_date:end.value||null,title:title.value,details:description.value,source_type:source.value,drug_name:drug.value,dose:dose.value,frequency:frequency.value,route:route.value,status:status.value,site:site.value,merged_into:merge.value||null,note:reason.value,evidence_refs:refs()});
  } else {
    const date=careInput(form,'随访记录日期',value.visit_date||data.as_of,'date',true),responses={};
    for(const [code,title] of [['dryness','口干评分'],['fatigue','疲劳评分'],['pain','疼痛评分']]) {
      const row=el('div',undefined,'care-symptom-row'),number=careInput(row,title+'（0–10；未测量留空）',value.responses?.[code]?.value,'number');number.min='0';number.max='10';number.step='0.1';
      const reason=careInput(row,'缺失原因（未测量时必填）',value.responses?.[code]?.missing_reason);responses[code]={number,reason};form.append(row);
    }
    const medications=careInput(form,'用药情况（未知请注明）',value.medications,'textarea',true),infection=careInput(form,'感染情况（未知请注明）',value.infection_status,'textarea',true),comorbidities=careInput(form,'基础病情况（未知请注明）',value.comorbidities,'textarea',true),note=careInput(form,'记录依据与更正原因',value.note,'textarea',true),refs=careEvidence(form,data,value.evidence_refs);
    form.append(el('p','表单版本 '+data.form_version+' · 单项原值分别保存。保存表单不自动完成临床随访待办。','help'));
    collect=()=>({template_version:data.form_version,visit_date:date.value,responses:Object.fromEntries(Object.entries(responses).map(([code,{number,reason}])=>[code,{value:number.value===''?null:Number(number.value),missing_reason:reason.value}])),medications:medications.value,infection_status:infection.value,comorbidities:comorbidities.value,note:note.value,evidence_refs:refs()});
  }
  wireCareForm(form,collect,key,data,kind,id,record?.revision||0,active,reload);details.append(form);return details;
}
function careFollowupPanel(data) {
  const section=el('section',undefined,'care-followup');section.append(el('h3','当前随访待办 · '+planStates[data.followup.status]));
  section.append(el('p','截至 '+data.as_of+'。优先显示最早未完成计划；历史未完成事项持续保留。发送状态与访视完成分开记录。','help'));
  if(data.sync_error)section.append(el('p','临床计划暂未同步，完成状态待核实。','warning'));
  for(const plan of data.followup.plans) {
    const card=el('article',undefined,'care-plan');card.dataset.state=plan.status;
    card.append(el('strong',planStates[plan.status]),el('p','目标 '+(plan.due_date||'未设置')+' · 窗口 '+(plan.window_start||'未设置')+' 至 '+(plan.window_end||'未设置')));
    if(plan.index_date)card.append(el('p','本计划在 '+plan.index_date+' 访视后建立，该次访视不计入完成依据。','help'));
    for(const evidence of plan.evidence||[])card.append(el('p','完成依据：'+evidence,'help'));section.append(card);
  }
  if(!data.followup.plans.length)section.append(el('p','尚无明确的当前计划。请核对归档资料与随访安排。','help'));return section;
}
function careTimeline(data,active,reload) {
  const section=el('section',undefined,'care-timeline');section.append(el('h3','纵向病程 · 指标与事件'));
  const filter=el('div',undefined,'care-range'),from=careInput(filter,'起始日期','','date'),to=careInput(filter,'结束日期',data.as_of,'date');
  const type=el('select');for(const [key,title] of Object.entries({all:'全部事件',medication:'用药',infection:'感染',hospital:'住院',form:'随访表',visit:'访视与检验'}))type.append(new Option(title,key));filter.append(label('事件类型',type));
  const result=el('div');section.append(filter,result);
  function render() {
    if(from.value&&to.value&&from.value>to.value){result.replaceChildren(el('p','起始日期应早于结束日期。','warning'));return;}
    const entries=data.timeline.filter(item=>(!from.value||item.date>=from.value)&&(!to.value||item.date<=to.value));
    const visits=entries.filter(item=>item.kind==='visit'),events=[];
    for(const item of entries) {
      if(item.kind==='event'&&!item.record.body.merged_into)events.push({date:item.date,title:item.record.body.title});
      if(item.kind==='form')events.push({date:item.date,title:'结构化随访'});
      for(const fact of item.facts||[])if(['medications','prescription','infection_status','inpatient_exams'].includes(fact.code))events.push({date:item.date,title:(clinicalSections[fact.code]||'用药')+'：'+fact.value});
    }
    result.replaceChildren();
    if(visits.length) {
      const choices=el('div',undefined,'patient-metric-controls'),plot=el('div');result.append(choices,plot);
      const definitions=[['igg','免疫球蛋白G','g/L'],['c3','补体C3','g/L'],['c4','补体C4','g/L'],['dryness','口干评分','分'],['fatigue','疲劳评分','分'],['pain','疼痛评分','分']];
      const draw=(code,title,unit)=>{
        for(const button of choices.children)button.setAttribute('aria-pressed',String(button.dataset.metric===code));
        const group=unit==='分'?'symptoms':'measurements',points=visits.map(visit=>{
          const facts=visit.facts.filter(f=>f.code===code&&(f.unit===unit||(unit==='分'&&f.unit===''))),raw=facts.length===1?String(facts[0].value):'';
          const value=/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw)&&Number.isFinite(Number(raw))?Number(raw):null;
          return {date:visit.date,[group]:{[code]:value}};
        });
        plot.replaceChildren(el('p',title+' · '+unit+'；虚线对应病程事件。仅比较同单位原值，检测方法仍需核对。','help'),patientMetricPlot(points,{code,label:title,unit,group,precision:2},events,'_care'));
      };
      for(const [code,title,unit] of definitions){const button=el('button',title,'secondary');button.type='button';button.dataset.metric=code;button.onclick=()=>draw(code,title,unit);choices.append(button);}draw(...definitions[0]);
    }
    const rows=el('div',undefined,'care-timeline-rows');result.append(rows);let count=0;
    for(const item of [...entries].reverse()) {
      const category=item.record?.body.category||item.kind;
      if(type.value!=='all'&&type.value!==category&&!(item.kind==='visit'&&item.facts.some(f=>({medication:['medications','prescription'],infection:['infection_status'],hospital:['inpatient_exams']})[type.value]?.includes(f.code))))continue;
      count++;const card=el('article',undefined,'care-time-event');card.dataset.eventDate=item.date;
      card.append(el('h4',item.date+' · '+(careCategories[category]||{visit:'访视与检验',form:'结构化随访'}[category])));
      if(item.kind==='visit') {
        const facts=type.value==='all'||type.value==='visit'?item.facts:item.facts.filter(f=>({medication:['medications','prescription'],infection:['infection_status'],hospital:['inpatient_exams']})[type.value]?.includes(f.code));
        for(const fact of facts) {const row=el('div',undefined,'care-fact'),line=el('p',(fields[fact.code]||clinicalSections[fact.code]||fact.code)+'：'+literal(fact));row.append(line);card.append(row);if(fact.quote){const source=el('details',undefined,'care-source');source.append(el('summary','查看原文依据'),el('blockquote',fact.quote,'quote'));row.append(source);}if(fact.source_job){const open=el('button','查看原件','text-button');open.type='button';open.onclick=()=>{selected=fact.source_job;return show('job');};row.append(open);}}
      } else {
        const record=item.record,value=record.body;
        if(item.kind==='event') {
          card.append(el('strong',value.title),el('p',value.details||'未补充详细描述'),el('p','资料来源：'+({clinician_record:'医嘱或医务记录',patient_report:'患者自述',unknown:'来源待核对'})[value.source_type],'help'));
          if(value.category==='medication')card.append(el('p',[value.drug_name,value.dose||'剂量未知',value.frequency||'频次未知',value.route||'途径未知'].join(' · ')));
          if(value.site)card.append(el('p','部位：'+value.site));
          card.append(el('p','状态：'+({unknown:'未知',current:'记录为在用',stopped:'记录为停用',active:'事件进行中',resolved:'有结束依据'})[value.status]+' · 结束日期：'+(value.end_date||'未知')));
          if(value.merged_into)card.append(el('p','已关联同次感染事件；本记录及更正历史保留。','help'));
        } else {
          for(const [code,response] of Object.entries(value.responses))card.append(el('p',({dryness:'口干',fatigue:'疲劳',pain:'疼痛'})[code]+'：'+(response.value===null?'未测量（'+response.missing_reason+'）':response.value+' 分')));
          for(const [key,title] of [['medications','用药'],['infection_status','感染'],['comorbidities','基础病']])card.append(el('p',title+'：'+value[key]));
        }
        card.append(el('p','记录人：'+(record.actor==='synthetic-scenario'?'合成场景':record.actor)+' · 录入时间 '+timeLabel(record.recorded_at)+' · 版本 '+record.revision,'help'),careRecordEditor(data,item.kind,record,active,reload));
      }
      rows.append(card);
    }
    if(!count)rows.append(el('p','所选日期和类型暂无记录。','help'));
  }
  from.onchange=to.onchange=type.onchange=render;render();return section;
}
async function mountCarePanel(section,scope,patientId,active) {
  try {
    const data=await api('care/'+scope+'/'+encodeURIComponent(patientId));if(!active())return;
    if(data.patient_id!==patientId||data.scope!==scope||!Array.isArray(data.history))throw localizedError('患者处理记录格式不完整，请刷新重试。');
    const reload=()=>mountCarePanel(section,scope,patientId,active),attention=patientAttentionPanel(data.attention,scope==='demo');
    attention.querySelectorAll('.attention-item').forEach((card,index)=>card.append(careActionForm(data,data.attention.items[index],active,reload)));
    const status=el('p','待处理 '+data.attention.open_count+' 项 · 已完成复核 '+data.attention.reviewed_count+' 项','care-summary');
    const current=el('div',undefined,'care-current-grid');current.append(careFollowupPanel(data),attention);
    const editors=el('div',undefined,'care-editors');editors.append(careRecordEditor(data,'event',null,active,reload),careRecordEditor(data,'form',null,active,reload));
    section.replaceChildren(status,current,editors,careTimeline(data,active,reload));
    if(scope==='demo')section.prepend(el('p','合成操作演示：所有处理和表单单独保存；原始50人资料保持。','overview-disclosure'));
    const history=el('details',undefined,'care-history');history.append(el('summary','处理与更正历史 · '+data.history.length+' 条'));
    for(const record of [...data.history].reverse()) {
      const entry=el('details'),body=record.body;
      entry.append(el('summary',(record.actor==='synthetic-scenario'?'合成场景':record.actor)+' · '+timeLabel(record.recorded_at)+' · '+({attention:'异常复核',event:'病程事件',form:'随访表'})[record.kind]+' · 版本 '+record.revision),el('p',body.note||''));
      if(record.kind==='attention') {
        entry.append(el('p','处理状态：'+careStates[body.state]+' · 负责人：'+(body.owner||'未指定')+' · 下次日期：'+(body.due_date||'未设置')),
          el('p','依据：'+(body.evidence_note||'未补充')));
        for(const source of body.source_snapshot?.evidence||[])entry.append(el('blockquote',source.quote||source.value||'','quote'));
      }
      if(body.evidence_refs?.length)entry.append(el('p','来源标识：'+body.evidence_refs.join('、'),'resource-id'));
      history.append(entry);
    }
    section.append(history);
  } catch(exception) {if(active()){const warning=el('div',undefined,'warning');warning.append(el('p','处置记录暂不可用，原始临床信息仍保留。'));feedbackError(warning,exception);section.append(warning);}}
}
async function mountCareRoster(section,scope,active) {
  section.append(el('p','正在读取当前待办…','help'));
  try {
    const data=await api('care/'+scope);if(!active())return;
    if(!Array.isArray(data.patients)||!data.followup_counts)throw localizedError('当前待办格式不完整，请刷新重试。');
    section.replaceChildren(el('h3','当前随访与异常待办'),el('p','按每位患者最早未完成计划分类；全部完成时展示最新完成计划。首次随访指标单独保留。','help'));
    if(data.sync_error)section.append(el('p','临床服务暂未同步，计划状态待核实。','warning'));
    const controls=el('div',undefined,'care-dashboard-filters'),results=el('div',undefined,'care-dashboard-results');let selectedFilter='open';
    const filters={open:'待处理异常',red:'红色待核实',...planStates,all:'全部患者'};
    function render(filter) {
      selectedFilter=filter;for(const button of controls.children)button.setAttribute('aria-pressed',String(button.dataset.filter===filter));
      const matches=data.patients.filter(p=>filter==='all'||(filter==='open'?p.open_count>0:filter==='red'?p.open_count>0&&p.open_level==='red':p.followup_status===filter));
      results.replaceChildren(el('p','显示 '+matches.length+' / '+data.total+' 人','help'));
      for(const patient of matches){const button=el('button',undefined,'care-work-item');button.type='button';button.dataset.patientId=patient.patient_id;
        button.append(el('strong',patient.name),el('span',planStates[patient.followup_status]),el('small','待处理 '+patient.open_count+' 项 · 已复核 '+patient.reviewed_count+' 项'));button.dataset.attentionLevel=patient.open_count?patient.open_level:'gray';button.onclick=()=>show(scope==='demo'?'patient':'record',{patientId:patient.patient_id});results.append(button);}
    }
    for(const [key,title] of Object.entries(filters)) {const count=key==='all'?data.total:key==='open'?data.patients.filter(p=>p.open_count>0).length:key==='red'?data.attention_counts.red:data.followup_counts[key];
      const button=el('button',title+' '+count,'secondary');button.type='button';button.dataset.filter=key;button.onclick=()=>render(key);controls.append(button);}
    section.append(controls,results);render(selectedFilter);
  } catch(exception) {if(active()){section.replaceChildren(el('p','当前待办暂不可用，患者名单仍可查看。','warning'));feedbackError(section,exception);}}
}
async function openSourceReview(job,fieldId='') {
  const version=sessionVersion,view=viewVersion,dialog=el('dialog',undefined,'source-dialog'),heading=el('div',undefined,'field-heading');
  const close=el('button','关闭原件对照','secondary');close.type='button';close.onclick=()=>dialog.close();heading.append(el('h2','原件与字段对照'),close);
  const content=el('div',undefined,'source-compare'),switcher=el('div',undefined,'source-mobile-switch');
  function setPane(pane){content.dataset.pane=pane;for(const button of switcher.children)button.setAttribute('aria-pressed',String(button.dataset.pane===pane));}
  for(const [pane,title] of [['fields','查看字段'],['page','查看原件']]){const button=el('button',title,'secondary');button.type='button';button.dataset.pane=pane;button.onclick=()=>setPane(pane);switcher.append(button);}setPane('page');
  dialog.append(heading,switcher,content);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
  const active=()=>dialog.open&&version===sessionVersion&&view===viewVersion&&currentUser;
  const fieldsBox=el('section',undefined,'source-field-list'),pageBox=el('section',undefined,'source-page-view');content.append(fieldsBox,pageBox);
  let request=0;
  async function load(id) {
    const current=++request;setPane('page');
    for(const button of fieldsBox.children)button.setAttribute('aria-pressed',String(button.dataset.fieldId===id));
    pageBox.replaceChildren(el('p','正在定位原文…','help'));
    try {
      const data=await api('jobs/'+job.id+'/source-map'+(id?'?field_id='+encodeURIComponent(id):''));if(!active()||current!==request)return;
      const pageButtons=el('div',undefined,'source-page-buttons');pageBox.replaceChildren(pageButtons);
      if(data.quote)pageBox.append(el('blockquote',data.quote,'quote'));
      const found=data.matches||[];pageBox.append(el('p',id?(found.length?'找到 '+found.length+' 处候选位置，请核对上下文。':'未定位到完全对应的摘录，请查看全文或下载原件。'):'请选择字段定位原文。','help'));
      if(data.warnings?.includes('logical_page_only'))pageBox.append(el('p','文本类资料按逻辑页展示。','help'));
      const display=el('div');pageBox.append(display);
      function showPage(number) {
        const page=data.pages.find(p=>p.page===number);display.replaceChildren(el('h3','第 '+number+' 页'));
        for(const button of pageButtons.children)button.setAttribute('aria-pressed',String(button.dataset.page===String(number)));
        if(page.image_available) {
          const wrapper=el('div',undefined,'source-image-wrap'),image=el('img');image.src='/api/jobs/'+job.id+'/page/'+number;image.alt='原件第 '+number+' 页';image.onerror=()=>{image.hidden=true;wrapper.append(el('p','页面图像暂不可用，请使用原始资料下载。','warning'));};wrapper.append(image);
          if(page.width&&page.height) {
            const svg=svgElement('svg',{viewBox:'0 0 '+page.width+' '+page.height,class:'source-boxes','aria-hidden':'true'});
            for(const match of found.filter(m=>m.page===number))for(const [x,y,right,bottom] of match.boxes)svg.append(svgElement('rect',{x,y,width:right-x,height:bottom-y,class:'source-highlight'}));wrapper.append(svg);
          }
          display.append(wrapper);
        }
        const pre=el('pre',page.text||'当前页没有可用文字，请对照图像或下载原件。','source');display.append(pre);
      }
      for(const page of data.pages){const button=el('button','第 '+page.page+' 页','secondary');button.type='button';button.dataset.page=String(page.page);button.onclick=()=>showPage(page.page);pageButtons.append(button);}showPage(found[0]?.page||1);
    } catch(exception){if(active()&&current===request)feedbackError(pageBox,exception);}
  }
  for(const field of job.fields||[]) {const button=el('button',field.date+' · '+fieldName(field.original.code)+'：'+literal(field.original),'source-field-button');button.type='button';button.dataset.fieldId=field.id;button.onclick=()=>load(field.id);fieldsBox.append(button);}
  await load(fieldId||(job.fields||[])[0]?.id||'');
}
function pageHeading(title,refreshAction) {
  const heading=el('div',undefined,'content-heading');
  heading.append(el('h2',title));
  if(refreshAction) {
    const refresh=el('button','刷新','text-button');refresh.type='button';refresh.onclick=refreshAction;
    heading.append(refresh);
  }
  return heading;
}
async function renderOutbox() {
  const response=await api('outbox');if(tab!=='outbox'||!currentUser) return;
  const box=$('content');
  box.replaceChildren(pageHeading('待发送队列',()=>show('outbox')),
    el('p','检查单和病例提取后生成草稿；复核归档后，关联实际访视待办并进入待发送状态。当前仅保存安排与文案。','help'));
  if(response.sync_error) box.append(el('p','访视状态暂未同步，以下为已保存的队列。稍后刷新后再核对完成状态。','warning'));
  if(!response.items.length) box.append(el('p','暂无随访草稿。上传含患者编号与就诊日期的资料后，草稿会显示在这里。','empty'));
  for(const item of response.items) {
    const card=el('article',undefined,'outbox-card'), heading=el('div',undefined,'field-heading');
    card.dataset.outboxId=item.id;
    heading.append(el('h3',(item.name||'患者')+' · '+item.patient_id),
      el('span',outboxStates[item.status]||item.status,'badge '+(item.status==='completed'?'success':item.status==='cancelled'?'muted':'')));
    card.append(heading,el('p','版本 '+item.revision+' · '+timeLabel(item.updated_at),'help'));
    if(item.window_start||item.window_end) card.append(el('p','访视窗口：'+(item.window_start||'未设置')+' 至 '+(item.window_end||'未设置'),'help'));
    if(item.job_id) {
      const source=el('button','查看来源与复核','text-button');source.type='button';
      source.onclick=()=>{selected=item.job_id;show('job');};card.append(source);
    }
    if(item.status==='completed') {
      card.append(el('p','计划日期：'+item.due_date),el('blockquote',item.message,'quote'),
        el('p','已关联审核通过的后续访视，保留消息草稿。此状态不代表已向患者发送。','help'));
      box.append(card);continue;
    }
    const form=el('form',undefined,'outbox-form'), date=el('input'), status=el('select');
    date.type='date';date.value=item.due_date||'';date.required=true;
    for(const value of ['draft','pending_send','cancelled']) {
      const option=new Option(outboxStates[value],value);
      option.disabled=value==='pending_send'&&!item.task_id;status.append(option);
    }
    status.value=item.status;
    const pair=el('div',undefined,'value-unit');pair.append(label('计划日期',date),label('队列状态',status));
    const message=el('textarea');message.rows=4;message.value=item.message||'';message.required=true;message.maxLength=2000;
    const reason=el('textarea');reason.rows=2;reason.required=true;reason.maxLength=500;
    reason.placeholder='记录本次调整的原因';
    const save=el('button','保存随访安排','secondary');save.type='submit';
    const feedback=el('div','','form-feedback');feedback.setAttribute('role','status');
    form.append(pair,label('消息草稿',message),label('修改原因',reason),save,feedback);
    if(!item.task_id) form.append(el('p','资料复核归档后，才能设为待发送。','help'));
    form.onsubmit=async event=>{
      event.preventDefault();if(!form.reportValidity()) return;
      save.disabled=true;feedback.textContent='正在保存…';
      try {
        await api('outbox/'+encodeURIComponent(item.id),{revision:item.revision,due_date:date.value,
          message:message.value,status:status.value,reason:reason.value});
        if(tab==='outbox') await renderOutbox();
      } catch(exception) {feedbackError(feedback,exception,' 当前输入已保留。');feedback.className='form-feedback error';}
      finally {save.disabled=false;}
    };
    card.append(form);box.append(card);
  }
}
function metric(title,value) {
  const item=el('div',undefined,'metric');
  item.append(el('span',title),el('strong',Number.isFinite(value)?String(value):'未返回'));
  return item;
}
function stateCounts(title,counts,names) {
  const section=el('section',undefined,'admin-section');section.append(el('h3',title));
  const values=Object.entries(counts||{}), list=el('dl',undefined,'state-counts');
  for(const [state,count] of values) list.append(el('dt',names[state]||state),el('dd',String(count)));
  section.append(values.length?list:el('p','暂无记录。','help'));return section;
}
function usernameInput() {
  const input=el('input');input.type='text';input.required=true;input.minLength=3;input.maxLength=64;
  input.pattern='[A-Za-z0-9_.\\-]{3,64}';input.autocomplete='off';input.spellcheck=false;return input;
}
function passwordInput(autocomplete='new-password') {
  const input=el('input');input.type='password';input.required=true;input.minLength=12;input.maxLength=128;
  input.autocomplete=autocomplete;return input;
}
function newAccountForm(container,onCreated) {
  const form=el('form'), username=usernameInput(), password=passwordInput(), role=el('select');
  role.append(new Option('工作人员','staff'),new Option('管理员','admin'));
  const pair=el('div',undefined,'value-unit');pair.append(label('账户名',username),label('角色',role));
  const submit=el('button','创建账户','secondary');submit.type='submit';
  const feedback=el('div','','form-feedback');feedback.setAttribute('role','status');
  form.append(pair,el('p','账户名为 3–64 位英文字母、数字、点、下划线或短横线。','help'),
    label('初始密码（12–128 位）',password),el('p','请通过安全方式向使用者交付初始密码，使用者登录后可在账户设置中修改。','help'),submit,feedback);
  form.onsubmit=async event=>{
    event.preventDefault();if(!form.reportValidity()) return;
    submit.disabled=true;feedback.className='form-feedback';feedback.textContent='正在创建账户…';
    try {
      const user=await api('admin/users',{username:username.value,password:password.value,role:role.value});
      feedback.textContent='已创建 '+user.username+'（'+roleLabel(user.role)+'）。';
      username.value='';role.value='staff';await onCreated();
    } catch(exception) {feedbackError(feedback,exception);feedback.className='form-feedback error';}
    finally {password.value='';submit.disabled=false;}
  };
  container.append(form);
}
async function renderAdmin() {
  const results=await Promise.allSettled([api('admin/overview'),api('admin/users')]);
  if(tab!=='admin'||!currentUser||currentUser.role!=='admin') return;
  const box=$('content');box.replaceChildren(pageHeading('管理总览',()=>show('admin')));
  if(results[0].status==='fulfilled') {
    const overview=results[0].value, metrics=el('div',undefined,'metrics');
    metrics.append(metric('已归档患者',overview.patients),metric('就诊事件',overview.events),metric('当前有效字段',overview.fields));
    box.append(metrics);
    const panels=el('div',undefined,'admin-grid');
    panels.append(stateCounts('资料处理',overview.jobs_by_state,states),
      stateCounts('访视待办',overview.tasks_by_status,{requested:'待随访',completed:'已完成',cancelled:'已取消'}),
      stateCounts('待发送队列',overview.outbox_by_status,outboxStates));box.append(panels);
    const audit=el('details',undefined,'admin-section');audit.append(el('summary','最近操作记录'));
    const list=el('ol',undefined,'history-list');
    for(const item of overview.recent_audit||[]) {
      const row=el('li');row.append(el('strong',auditActions[item.event]||'其他操作记录'),el('small',timeLabel(item.at)+(item.actor?' · '+item.actor:'')),
        traceDetails('查看操作标识',item.event));list.append(row);
    }
    audit.append(list.childElementCount?list:el('p','暂无操作记录。','help'));box.append(audit);
  } else error(box,results[0].reason,'总览暂不可用：');
  const exports=el('section',undefined,'admin-section');exports.append(el('h3','导出业务数据'),
    el('p','数据库包含资料处理、复核及随访队列。资料包另外包含原始上传文件与临床资源，均保存在本机。','help'));
  const downloads=el('div',undefined,'download-actions');
  for(const [name,path] of [['下载数据库（SQLite）','database'],['下载业务资料包（ZIP）','archive']]) {
    const link=el('a',name,'button-link');link.href='/api/admin/export/'+path;link.download='';downloads.append(link);
  }
  exports.append(downloads,el('p','导出不包含账户密码、登录会话和服务凭据；资料包不是整个系统的完整备份。','help'));box.append(exports);
  const accounts=el('section',undefined,'admin-section');accounts.append(el('h3','账户管理'));
  const roster=el('ul',undefined,'user-list');
  function displayUsers(users) {
    roster.replaceChildren();
    for(const user of users) {
      const row=el('li');row.append(el('strong',user.username),el('span',roleLabel(user.role)+(user.active?'':' · 已停用'),'help'));roster.append(row);
    }
    if(!users.length) roster.append(el('li','暂无账户。','help'));
  }
  if(results[1].status==='fulfilled') displayUsers(results[1].value.users);
  else error(accounts,results[1].reason,'账户列表暂不可用：');
  accounts.append(roster,el('h4','新建账户'));
  newAccountForm(accounts,async()=>{const response=await api('admin/users');displayUsers(response.users);});box.append(accounts);
}
function renderAccount() {
  const box=$('content');box.replaceChildren(pageHeading('账户设置'),
    el('p',currentUser.username+' · '+roleLabel(currentUser.role),'help'));
  if(demo) {box.append(el('p','固定候选演示使用临时会话，无账户密码。'));return;}
  const form=el('form',undefined,'password-form'), current=passwordInput('current-password'), password=passwordInput(), confirm=passwordInput();
  const submit=el('button','更新密码','secondary');submit.type='submit';
  const feedback=el('div','','form-feedback');feedback.setAttribute('role','status');
  form.append(label('当前密码',current),label('新密码（12–128 位）',password),label('再次输入新密码',confirm),
    el('p','更新后保留当前登录，其他已登录会话将退出。','help'),submit,feedback);
  form.onsubmit=async event=>{
    event.preventDefault();confirm.setCustomValidity(password.value===confirm.value?'':'两次输入的新密码不一致。');
    if(!form.reportValidity()) return;
    submit.disabled=true;feedback.className='form-feedback';
    try {await api('auth/password',{current_password:current.value,new_password:password.value});feedback.textContent='密码已更新，其他登录会话已失效。';}
    catch(exception) {feedbackError(feedback,exception);feedback.className='form-feedback error';}
    finally {current.value='';password.value='';confirm.value='';submit.disabled=false;}
  };
  confirm.oninput=()=>confirm.setCustomValidity('');password.oninput=()=>confirm.setCustomValidity('');box.append(form);
}
let authVersion=0, recoveryVersion=0, recoveryRead=0, recoveryTimer=null;
let recoveryActive=false, recoveryState=null, recoveryChecking=false, recoverySaving=false;
function clearRecoveryPasswords() {
  $('recovery_password').value='';$('recovery_confirmation').value='';
  $('recovery_confirmation').setCustomValidity('');
}
function stopRecovery() {
  recoveryVersion++;recoveryRead++;clearTimeout(recoveryTimer);recoveryTimer=null;
  recoveryActive=false;recoveryChecking=false;recoverySaving=false;recoveryState=null;
  clearRecoveryPasswords();$('recovery_panel').hidden=true;
}
function recoveryFeedback(exception) {
  const messages={409:'本次申请已失效或尚未确认，请刷新状态后重新申请。',422:'请检查账户名及密码要求，两次新密码必须一致。',429:'申请过于频繁，请稍后再试。'};
  $('recovery_feedback').textContent=messages[exception.status]||errorInfo(exception).message;
  $('recovery_feedback').className='form-feedback error';
}
function scheduleRecoveryCheck() {
  clearTimeout(recoveryTimer);recoveryTimer=null;
  if(recoveryActive&&!currentUser&&!recoverySaving&&['pending','approved'].includes(recoveryState?.status)&&!document.hidden) {
    recoveryTimer=setTimeout(()=>refreshRecovery(),5000);
  }
}
function renderRecovery(state,focus=false) {
  const valid=['none','pending','approved','expired','consumed'];
  if(!valid.includes(state?.status)) throw localizedError('恢复状态暂时无法读取，请刷新后重试。');
  if(['pending','approved'].includes(state.status)&&(!Number.isFinite(state.expires_at)||typeof state.request_id!=='string'||typeof state.username!=='string')) {
    throw localizedError('恢复状态暂时无法读取，请刷新后重试。');
  }
  if(['pending','approved'].includes(state.status)&&state.expires_at*1000<=Date.now()) state={...state,status:'expired'};
  const replaced=recoveryState?.request_id&&state.request_id&&(state.request_id!==recoveryState.request_id||state.username!==recoveryState.username);
  const changed=state.status!==recoveryState?.status||state.request_id!==recoveryState?.request_id||state.username!==recoveryState?.username;
  if(changed) clearRecoveryPasswords();
  if(replaced) {$('recovery_feedback').textContent='当前申请已切换，原密码输入已清空。请核对下方账户名和申请编号。';$('recovery_feedback').className='form-feedback warning';}
  recoveryState=state;
  const status=state.status, entry=status==='none', approved=status==='approved', complete=status==='consumed';
  $('auth_title').textContent=({none:'重设账户密码',pending:'等待本机确认',approved:'设置新密码',expired:'申请已失效',consumed:'密码已重设'})[status];
  $('auth_description').textContent=({none:'使用现有账户名申请，无需邮箱。',pending:'确认本次申请后，即可在工作台设置新密码。',approved:'本机确认已通过，请由你本人输入新密码。',expired:'请重新申请，本次尚未保存的新密码不会保留。',consumed:'请返回登录，使用新密码进入工作台。'})[status];
  $('recovery_request_form').hidden=!entry;$('recovery_password_form').hidden=!approved;
  $('recovery_status').hidden=entry||complete;
  $('recovery_status_text').textContent=({pending:'申请已提交 · 等待确认',approved:'本机已确认 · 可以设置新密码',expired:'申请已失效，请重新申请。'})[status]||'';
  $('recovery_account').textContent=state.username||'';$('recovery_id').textContent=state.request_id||'';
  $('recovery_expiry').textContent=Number.isFinite(state.expires_at)?new Date(state.expires_at*1000).toLocaleString('zh-CN',{hour12:false}):'已结束';
  $('recovery_waiting_help').hidden=status!=='pending';$('recovery_refresh').hidden=!['pending','approved'].includes(status);
  $('recovery_restart').hidden=status!=='expired';$('recovery_back').textContent=complete?'返回登录工作台':'返回登录';
  $('recovery_back').classList.toggle('primary',complete);
  for(const step of document.querySelectorAll('[data-recovery-step]')) {
    const current=step.dataset.recoveryStep===(entry?'request':approved||complete?'approved':'pending');
    if(current) step.setAttribute('aria-current','step');else step.removeAttribute('aria-current');
  }
  if(focus&&changed) (approved?$('recovery_password'):entry?$('recovery_username'):complete?$('recovery_back'):$('recovery_refresh').hidden?$('recovery_restart'):$('recovery_refresh')).focus();
  scheduleRecoveryCheck();
}
function openRecovery(state={status:'none'},focus=true) {
  authVersion++;stopRecovery();recoveryActive=true;
  $('auth_password').value='';$('auth_confirm').value='';$('auth_form').hidden=true;
  $('auth_recovery').hidden=true;$('auth_retry').hidden=true;$('auth_feedback').textContent='';
  $('recovery_feedback').textContent='';$('recovery_feedback').className='form-feedback';
  $('recovery_username').value=state.username||$('auth_username').value;
  $('recovery_panel').hidden=false;$('recovery_request_submit').disabled=false;$('recovery_complete').disabled=false;$('recovery_refresh').disabled=false;
  renderRecovery(state,focus);
}
async function refreshRecovery() {
  if(!recoveryActive||currentUser||recoveryChecking||recoverySaving) return;
  clearTimeout(recoveryTimer);recoveryTimer=null;
  const version=recoveryVersion, request=++recoveryRead;
  recoveryChecking=true;$('recovery_refresh').disabled=true;
  try {
    const state=await api('auth/recovery/state');
    if(!recoveryActive||version!==recoveryVersion||request!==recoveryRead||currentUser) return;
    $('recovery_feedback').textContent='';$('recovery_feedback').className='form-feedback';
    renderRecovery(state,true);
  } catch(exception) {
    if(recoveryActive&&version===recoveryVersion&&request===recoveryRead&&!currentUser) recoveryFeedback(exception);
  } finally {
    if(recoveryActive&&version===recoveryVersion&&request===recoveryRead&&!currentUser) {
      recoveryChecking=false;$('recovery_refresh').disabled=false;scheduleRecoveryCheck();
    }
  }
}
async function resumeRecovery(version) {
  try {
    const state=await api('auth/recovery/state');
    if(version!==authVersion||currentUser||recoveryActive||setupRequired) return;
    if(state.status!=='none') openRecovery(state,false);
  } catch { /* Login remains available when recovery cannot be checked. */ }
}
function configureAuth(setup) {
  stopRecovery();
  setupRequired=setup;
  $('auth_title').textContent=setup?'设置首位管理员':'登录工作台';
  $('auth_description').textContent=setup?'设置账户名和密码后，即可上传资料并管理科室工作台。':'使用管理员为你创建的账户名和密码登录。';
  $('auth_submit').textContent=setup?'创建管理员并进入':'登录工作台';
  $('auth_confirm_label').hidden=!setup;$('auth_confirm').required=setup;
  $('auth_password_help').hidden=!setup;$('auth_password').autocomplete=setup?'new-password':'current-password';
  $('auth_form').hidden=false;$('auth_retry').hidden=true;$('auth_recovery').hidden=setup;
}
function signedOut(message='') {
  window.Department?.clear();
  authVersion++;
  registryRequest++;registryPatients=[];registryLoaded=false;uploadPatient=null;registryQuery='';overviewSource='registry';patientCreating=false;
  stopUploads();uploadBatch=[];renderUploads();
  sessionVersion++;viewVersion++;overviewFetchVersion++;overviewCache=null;overviewPending=null;overviewFilter='all';overviewQuery='';workbenchTab='job';activePatientId=null;
  currentUser=null;selected=null;signature='';tab='job';drafts.clear();careDrafts.clear();
  for(const dialog of document.querySelectorAll('dialog.source-dialog'))dialog.close();
  $('workspace').hidden=true;$('auth_shell').hidden=false;$('logout').hidden=true;$('account_button').hidden=true;
  $('tab_admin').hidden=true;$('jobs').replaceChildren();$('count').textContent='';$('content').replaceChildren();
  $('upload').reset();$('upload_status').textContent='';$('auth_password').value='';$('auth_confirm').value='';
  $('patient_create').reset();$('patient_search').value='';$('patient_picker_feedback').textContent='';setPatientMode('existing');renderPatientOptions();renderSelectedPatient();
  $('operator').textContent='';$('model').textContent='正在检查运行模式…';$('ocr').textContent='正在检查 OCR…';
  configureAuth(false);$('auth_feedback').textContent=message;
}
async function signedIn(user) {
  authVersion++;stopRecovery();$('auth_password').value='';$('auth_confirm').value='';
  sessionVersion++;currentUser=user;
  $('auth_shell').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;$('account_button').hidden=false;
  $('tab_admin').hidden=user.role!=='admin';$('auth_feedback').textContent='';
  await health();await refreshRegistry();await routeFromHash();await list();
}
async function checkAuth() {
  const version=++authVersion;
  $('auth_retry').hidden=true;$('auth_feedback').textContent='';
  try {
    const state=await api('auth/state');
    if(version!==authVersion) return;
    if(state.authenticated&&state.user) await signedIn(state.user);
    else {configureAuth(state.setup_required);if(!state.setup_required) await resumeRecovery(version);}
  } catch(exception) {
    if(version!==authVersion) return;
    $('auth_title').textContent='暂时无法连接工作台';$('auth_description').textContent='请确认本机服务已启动后重新检查。';
    feedbackError($('auth_feedback'),exception);$('auth_form').hidden=true;$('auth_retry').hidden=false;$('auth_recovery').hidden=true;
  }
}
$('auth_form').onsubmit=async event=>{
  event.preventDefault();
  if(recoveryActive) return;
  $('auth_confirm').setCustomValidity(!setupRequired||$('auth_password').value===$('auth_confirm').value?'':'两次输入的密码不一致。');
  if(!$('auth_form').reportValidity()) return;
  const version=++authVersion;
  $('auth_submit').disabled=true;$('auth_feedback').textContent=setupRequired?'正在创建管理员…':'正在登录…';
  try {
    const response=await api('auth/'+(setupRequired?'setup':'login'),{username:$('auth_username').value,password:$('auth_password').value});
    if(version!==authVersion||recoveryActive) return;
    $('auth_password').value='';$('auth_confirm').value='';
    await signedIn(response.user);
  } catch(exception) {
    if(version!==authVersion||recoveryActive) return;
    if(setupRequired&&exception.status===409) {configureAuth(false);$('auth_feedback').textContent='管理员账户已经建立，请使用账户名和密码登录。';}
    else feedbackError($('auth_feedback'),exception);
  }
  finally {$('auth_password').value='';$('auth_confirm').value='';$('auth_submit').disabled=false;}
};
$('auth_confirm').oninput=()=>$('auth_confirm').setCustomValidity('');
$('auth_password').oninput=()=>$('auth_confirm').setCustomValidity('');
$('auth_retry').onclick=checkAuth;
$('auth_recovery').onclick=async()=>{openRecovery();await refreshRecovery();};
$('recovery_back').onclick=()=>{
  const username=recoveryState?.username||$('recovery_username').value;
  authVersion++;configureAuth(false);$('auth_username').value=username;$('auth_feedback').textContent='';$('auth_password').focus();
};
$('recovery_restart').onclick=()=>openRecovery({status:'none',username:recoveryState?.username});
$('recovery_refresh').onclick=refreshRecovery;
$('recovery_request_form').onsubmit=async event=>{
  event.preventDefault();
  if(!recoveryActive||recoveryState?.status!=='none'||!$('recovery_request_form').reportValidity()) return;
  const version=recoveryVersion, request=++recoveryRead;
  recoveryChecking=false;$('recovery_request_submit').disabled=true;$('recovery_feedback').className='form-feedback';$('recovery_feedback').textContent='正在提交申请…';
  try {
    const state=await api('auth/recovery/request',{username:$('recovery_username').value});
    if(!recoveryActive||version!==recoveryVersion||request!==recoveryRead||currentUser) return;
    $('recovery_feedback').textContent='';renderRecovery(state,true);
  } catch(exception) {if(recoveryActive&&version===recoveryVersion&&request===recoveryRead&&!currentUser) recoveryFeedback(exception);}
  finally {if(recoveryActive&&version===recoveryVersion&&request===recoveryRead) $('recovery_request_submit').disabled=false;}
};
$('recovery_password_form').onsubmit=async event=>{
  event.preventDefault();
  if(!recoveryActive||recoveryState?.status!=='approved'||recoverySaving) return;
  if(recoveryState.expires_at*1000<=Date.now()) {renderRecovery({...recoveryState,status:'expired'},true);return;}
  const password=$('recovery_password'), confirmation=$('recovery_confirmation');
  confirmation.setCustomValidity(password.value===confirmation.value?'':'两次输入的新密码不一致。');
  if(!password.checkValidity()||!confirmation.checkValidity()||[...password.value].length<12||[...password.value].length>128) {
    $('recovery_feedback').className='form-feedback error';$('recovery_feedback').textContent=password.value!==confirmation.value?'两次输入的新密码不一致，请重新核对。':'密码长度须为 12–128 位。';
    $('recovery_password_form').reportValidity();return;
  }
  const version=recoveryVersion, request=++recoveryRead;
  recoveryChecking=false;recoverySaving=true;clearTimeout(recoveryTimer);recoveryTimer=null;
  $('recovery_complete').disabled=true;$('recovery_refresh').disabled=true;$('recovery_feedback').className='form-feedback';$('recovery_feedback').textContent='正在保存新密码…';
  try {
    const result=await api('auth/recovery/complete',{request_id:recoveryState.request_id,new_password:password.value,confirmation:confirmation.value});
    if(!recoveryActive||version!==recoveryVersion||request!==recoveryRead||currentUser) return;
    if(result.reset!==true) throw localizedError('密码保存结果无法确认，请刷新状态后重试。');
    if(result.username!==recoveryState.username) {renderRecovery({...recoveryState,status:'expired'},true);throw localizedError('账户状态已变化，请返回登录并由本机管理员核对本次申请。');}
    $('recovery_feedback').textContent='';renderRecovery({status:'consumed',username:result.username},true);
  } catch(exception) {
    if(recoveryActive&&version===recoveryVersion&&request===recoveryRead&&!currentUser) {
      if(exception.status===409) renderRecovery({...recoveryState,status:'expired'},true);
      recoveryFeedback(exception);
    }
  } finally {
    if(recoveryActive&&version===recoveryVersion&&request===recoveryRead&&!currentUser) {
      clearRecoveryPasswords();recoverySaving=false;$('recovery_complete').disabled=false;$('recovery_refresh').disabled=false;scheduleRecoveryCheck();
    }
  }
};
$('recovery_password').oninput=()=>$('recovery_confirmation').setCustomValidity('');
$('recovery_confirmation').oninput=()=>$('recovery_confirmation').setCustomValidity('');
document.addEventListener('visibilitychange',()=>{
  if(document.hidden) {clearTimeout(recoveryTimer);recoveryTimer=null;}else scheduleRecoveryCheck();
});
window.addEventListener('pagehide',()=>{stopRecovery();});
window.addEventListener('pageshow',event=>{if(event.persisted) checkAuth();});
$('logout').onclick=async()=>{
  stopUploads();
  $('logout').disabled=true;
  try {await api('auth/logout',{});signedOut('已退出登录。');}
  catch(exception) {error($('content'),exception,'退出失败：');}
  finally {$('logout').disabled=false;}
};
$('account_button').onclick=()=>show('account');
function renderUploads() {
  const results=$('upload_results');results.replaceChildren();
  const labels={unsubmitted:'未提交',uploading:'正在上传',uploaded:'已上传',duplicate:'重复资料，已在队列中',failed:'上传失败'};
  for(const item of uploadBatch) {
    const row=el('li',undefined,'upload-result');row.dataset.state=item.state;
    row.append(el('strong',item.file.name),el('span',labels[item.state],'upload-result-state'));
    if(item.patient)row.append(el('span','患者：'+item.patient.name+' · '+item.patient.patient_id,'upload-result-patient'));
    if(item.error) feedbackError(row.appendChild(el('div',undefined,'upload-result-error')),item.error);
    if(item.id) {
      const open=el('button','查看队列任务','text-button');open.type='button';
      open.onclick=()=>{selected=item.id;signature='';show('job');};row.append(open);
    }
    results.append(row);
  }
  const retryable=uploadBatch.filter(item=>['failed','unsubmitted'].includes(item.state)).length;
  $('upload_retry').hidden=!retryable;$('upload_retry').disabled=uploading;
  $('upload_button').disabled=uploading||patientCreating||!uploadPatient;$('file').disabled=uploading||patientCreating||!uploadPatient;$('synthetic').disabled=uploading;
  $('patient_existing').disabled=uploading||patientCreating;$('patient_new').disabled=uploading||patientCreating;$('patient_create_submit').disabled=uploading||patientCreating;
  for(const button of $('patient_options').querySelectorAll('button'))button.disabled=uploading||patientCreating;
  $('upload_button').textContent=uploading?'正在逐份上传…':'上传所选资料';
  renderSelectedPatient();
}
function stopUploads() {
  uploadRun++;uploadController?.abort();uploadController=null;uploading=false;
  for(const item of uploadBatch) if(item.state==='uploading') {
    item.state='unsubmitted';item.error='上传已中止；重试时会检查该资料是否已保存。';
  }
  renderUploads();
}
async function uploadPending() {
  if(uploading||patientCreating||!currentUser) return;
  if(uploadBatch.some(item=>['failed','unsubmitted'].includes(item.state)&&!item.patient)&&!uploadPatient) {
    $('upload_status').textContent='请先选择已有患者或新建患者，再上传资料。';return;
  }
  for(const item of uploadBatch)if(!item.patient)item.patient={...uploadPatient};
  const version=sessionVersion, run=++uploadRun, batch=uploadBatch;
  const acknowledged=documentMode==='synthetic'&&$('synthetic').checked;
  const active=()=>currentUser&&sessionVersion===version&&uploadRun===run;
  uploading=true;renderUploads();
  $('upload_status').textContent='正在逐份保存原件，成功的资料会进入同一处理队列。';
  try {
    for(const item of batch) {
      if(!active()) return;
      if(!['failed','unsubmitted'].includes(item.state)) continue;
      item.state='uploading';item.error=null;renderUploads();
      uploadController=new AbortController();
      try {
        const form=new FormData();form.append('file',item.file);form.append('synthetic',acknowledged);form.append('patient_id',item.patient.patient_id);
        const result=await api('upload',form,uploadController.signal);
        if(!active()) return;
        item.id=result.id;item.state=result.duplicate?'duplicate':'uploaded';
      } catch(exception) {
        if(!active()) return;
        item.state='failed';item.error=exception;
      }
      renderUploads();await list(false);
    }
    if(active()) {
      const completed=batch.filter(item=>['uploaded','duplicate'].includes(item.state)).length;
      const failed=batch.filter(item=>item.state==='failed').length;
      $('upload_status').textContent='本批 '+completed+' / '+batch.length+' 份已进入处理队列'+(failed?'，'+failed+' 份上传失败，可仅重试未成功项。':'。请选择队列中的资料查看提取进度。');
    }
  } finally {
    if(active()) {uploading=false;uploadController=null;renderUploads();}
  }
}
$('file').onchange=()=>{
  if(uploading) return;
  uploadBatch=[...$('file').files].map(file=>({file,state:'unsubmitted'}));
  $('upload_status').textContent=uploadBatch.length?'已选择 '+uploadBatch.length+' 份资料。':'';renderUploads();
};
$('upload').onsubmit=async event=>{
  event.preventDefault();if(uploading||patientCreating)return;
  if(!uploadPatient){$('upload_status').textContent='请先选择已有患者或新建患者，再上传资料。';$('patient_existing').focus();return;}
  if(!$('upload').reportValidity())return;
  const files=[...$('file').files];
  if(files.length!==uploadBatch.length||files.some((file,index)=>file!==uploadBatch[index]?.file))
    uploadBatch=files.map(file=>({file,state:'unsubmitted'}));
  await uploadPending();
};
$('upload_retry').onclick=async()=>{if($('upload').reportValidity()) await uploadPending();};
function setPatientMode(mode) {
  if(uploading||patientCreating)return;
  const existing=mode==='existing';$('patient_picker').hidden=!existing;$('patient_create').hidden=existing;
  $('patient_existing').setAttribute('aria-pressed',String(existing));$('patient_new').setAttribute('aria-pressed',String(!existing));
}
$('patient_existing').onclick=()=>setPatientMode('existing');$('patient_new').onclick=()=>setPatientMode('new');
$('patient_search').oninput=renderPatientOptions;$('patient_refresh').onclick=refreshRegistry;
$('patient_create').onsubmit=async event=>{
  event.preventDefault();if(uploading||patientCreating||!currentUser||!$('patient_create').reportValidity())return;
  const version=sessionVersion;patientCreating=true;renderUploads();$('patient_picker_feedback').textContent='正在登记患者…';
  try {
    const result=await api('patient-registry',{patient_id:$('patient_create_id').value.trim(),name:$('patient_create_name').value.trim(),sex:$('patient_create_sex').value,birth_date:$('patient_create_birth').value||null});
    if(!currentUser||version!==sessionVersion)return;
    if(!result.patient||typeof result.patient.patient_id!=='string'||typeof result.patient.name!=='string')throw localizedError('建档结果无法确认，请刷新患者名单核对。');
    registryRequest++;registryPatients=[...registryPatients.filter(patient=>patient.patient_id!==result.patient.patient_id),result.patient];registryLoaded=true;patientCreating=false;
    selectUploadPatient(result.patient);$('patient_create').reset();setPatientMode('existing');$('patient_search').value='';renderPatientOptions();
    $('patient_picker_feedback').textContent=result.created?'患者已新建并选中，可继续上传资料。':'已有相同档案，已选中，可继续上传资料。';$('file').focus();
  } catch(exception) {if(currentUser&&version===sessionVersion)feedbackError($('patient_picker_feedback'),exception);}
  finally {if(currentUser&&version===sessionVersion){patientCreating=false;renderUploads();}}
};
renderSelectedPatient();renderPatientOptions();
for(const name of tabs) $('tab_'+name).onclick=()=>show(name);
$('nav_overview').onclick=()=>show('overview');$('nav_workbench').onclick=()=>show(workbenchTab);
$('nav_knowledge').onclick=()=>show('knowledge');$('nav_analysis').onclick=()=>show('analysis');
window.addEventListener('hashchange',routeFromHash);
async function health() {
  if(!currentUser) return;
  const version=sessionVersion;
  try {
    const status=await api('status');if(!currentUser||version!==sessionVersion) return;
    fields=status.fields||{};demo=status.mode==='synthetic-demo';documentMode=status.document_mode||'synthetic';
    $('model').textContent=demo?'固定候选 · 合成演示 · 不调用模型':status.model_ready?status.model+' · 本机就绪':'本地模型尚未就绪，提取任务可重试';
    $('ocr').textContent=demo?'OCR 未启用 · 固定候选演示':status.ocr_ready?'OCR · 本机就绪':'OCR 尚未就绪，扫描件暂不可提取';
    $('operator').textContent=(currentUser.username||status.operator||'本地操作员')+' · '+roleLabel(currentUser.role);
    $('demo_fixtures').hidden=!demo;$('model_fixtures').hidden=demo;
    const synthetic=documentMode==='synthetic';
    $('synthetic_label').hidden=!synthetic;$('synthetic').required=synthetic;$('local_processing').hidden=synthetic;
    $('upload_title').textContent=synthetic?'上传合成资料':'上传检查单或病例';
    $('mode_notice').textContent=synthetic?'本机合成演示 · 仅接收标记 SJD-SYNTHETIC 的虚构资料 · 随访暂不发送':'资料在本机处理 · 有问题再处理，统一确认归档 · 随访消息保留在待发送队列';
    $('footer_note').textContent=synthetic?'合成开发验证 · 当前会话留痕 · 人工复核后归档':'本机处理 · 原文与更正历史保留 · 人工复核后归档';
  } catch(exception) {feedbackError($('model'),exception);}
}
await checkAuth();
setInterval(()=>{if(currentUser&&!busy) list();},3000);
setInterval(health,30000);

