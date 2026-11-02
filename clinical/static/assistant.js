/* Local task orchestration. Business persistence remains in the original modules. */
(() => {
  const tasks={auto:'自动识别任务',intake:'整理与补全资料',knowledge:'查阅知识依据',cases:'检索已保存医案',prescriptions:'比较门诊处方'};
  const fields={symptoms:'症状',tongue:'舌象',pulse:'脉象',syndrome:'证候',principle:'治法',prescription:'处方原文'};
  const origins={unknown:'来源待确认',patient:'患者自述',clinician:'医生观察或记录',history:'历史资料',operator:'操作者补充'};
  const statuses={not_asked:'尚未询问或记录',recorded:'已补充',unavailable:'无法提供'};
  const categories={literature:'指南与文献',classics:'古籍',formula:'方药资料',synthetic:'合成示例',unclassified:'待分类'};
  const steps={recognize:'识别原始记录',supplement:'补充缺失信息',review:'人工复核',preview:'查看访次对照',choose_public_source:'选择公开资料',ask:'提出通用问题',read_evidence:'核对原文',search_saved_collection:'检索当前账户的已保存集合',read_matches:'查看命中依据',open_comparison:'打开原医案对照',open_complete_workspace:'打开完整处方工作台',explicit_save:'显式确认保存'};
  const blank=()=>({schema:'department-task-v1',instruction:'',task:'auto',data_origin:'synthetic',text:'',supplements:[],context:{case_query:'',collection_revision:null,knowledge_source_id:'',knowledge_category:'all'}});
  const initial=()=>({id:crypto.randomUUID(),revision:0,draft:blank(),dirty:false,version:0,prepared:null,plan:null,library:null,caseResult:null,query:'',category:'all',sourceSearch:''});
  let state=initial(),epoch=0,renderVersion=0,workController=null;
  const controllers=new Set();
  function clear(){epoch++;for(const controller of controllers)controller.abort();controllers.clear();state=initial();}
  window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
  function button(el,label,action,style='secondary'){const node=el('button',label,style);node.type='button';node.onclick=action;return node;}
  function field(el,label,control){const node=el('label');node.append(el('span',label),control);return node;}
  function select(el,values,value,id){const node=el('select');node.id=id;for(const [key,label] of Object.entries(values)){const option=el('option',label);option.value=key;node.append(option);}node.value=value;return node;}
  function link(el,label,hash){const node=el('a',label,'assistant-link');node.href=hash;return node;}
  async function request(ctx,path,body,controller=new AbortController()){controllers.add(controller);try{const value=await ctx.api('department/'+path,body,controller.signal);if(controller.signal.aborted)throw Object.assign(new Error('Cancelled'),{name:'AbortError'});return value;}finally{controllers.delete(controller);}}
  function failure(el,target,exc){target.replaceChildren(el('p',exc.name==='AbortError'?'已取消等待，当前编辑已保留。':exc.status===429?'本账户已保存 100 个任务，请接续已有任务；当前编辑仍保留在页面。':exc.status===409?'资料或草稿版本已变化。当前编辑已保留，可另存为新草稿或重新识别资料。':exc.status===422?'请检查任务内容、补充值和来源。识别支持带字段标签的文本、CSV 或 JSON。':exc.status===503?'本地资料服务暂不可用，请检查模块配置后重试。':'操作未完成，请检查连接后重试；当前编辑已保留。','department-danger'));}

  async function render(box,ctx){
    workController?.abort();
    const {el}=ctx,session=epoch,view=++renderVersion;
    const current=()=>session===epoch&&view===renderVersion&&ctx.isCurrent();
    const grid=el('div',null,'assistant-grid'),main=el('section',null,'assistant-main'),side=el('aside',null,'assistant-side');
    const status=el('p',null,'department-help');status.id='assistant_save_status';status.setAttribute('role','status');
    const feedback=el('div');feedback.id='assistant_feedback';feedback.setAttribute('role','status');
    const activity=el('div',null,'assistant-activity'),activityText=el('p','等待开始本次任务','department-help');
    activityText.id='assistant_activity';activityText.setAttribute('role','status');
    const cancel=button(el,'取消等待',()=>{workController?.abort();activityText.textContent='已取消等待，迟到结果将忽略。服务器可能仍在完成只读处理。';cancel.disabled=true;});
    cancel.id='assistant_cancel';cancel.disabled=true;activity.append(activityText,cancel);
    async function perform(path,body,label){
      workController?.abort();const controller=new AbortController();workController=controller;
      activityText.textContent=label+' · 正在处理';cancel.disabled=false;
      try{const value=await request(ctx,path,body,controller);if(current()&&workController===controller)activityText.textContent=label+' · 已收到结果';return value;}
      catch(exc){if(current()&&workController===controller)activityText.textContent=label+(exc.name==='AbortError'?' · 已取消等待':' · 处理失败，可重试');throw exc;}
      finally{if(current()&&workController===controller)cancel.disabled=true;}
    }
    const list=el('div',null,'assistant-drafts');list.id='assistant_drafts';
    let saving=false,reviewed=false;
    function updateStatus(){status.textContent=(state.dirty?'有未保存修改':state.revision?'草稿已同步':'新任务')+' · '+(state.revision?'版本 '+state.revision:'尚未保存');}
    function changed(reset=false){state.dirty=true;state.version++;if(reset)state.prepared=null;updateStatus();}
    const save=button(el,'保存任务草稿',async()=>{
      if(saving)return;saving=true;save.disabled=true;
      const id=state.id,version=state.version,body={expected_revision:state.revision,draft:structuredClone(state.draft)};
      try{const value=await request(ctx,'assistant/drafts/'+id,body);if(session!==epoch||id!==state.id)return;state.revision=value.revision;if(version===state.version)state.dirty=false;if(current()){updateStatus();feedback.replaceChildren(el('p','任务草稿已保存在本机。业务记录仍由原工作台复核保存。','department-help'));await loadDrafts();}}
      catch(exc){if(current()){failure(el,feedback,exc);if(exc.status===409)feedback.append(button(el,'保留当前内容，另存草稿',()=>{state.id=crypto.randomUUID();state.revision=0;changed();save.click();}));}}finally{saving=false;if(current())save.disabled=false;}
    },'primary');save.id='assistant_save';
    const fresh=button(el,'新建任务',()=>{if(state.dirty){feedback.replaceChildren(el('p','请先保存当前修改，再新建任务。','department-help'));return;}state=initial();render(box,ctx);});fresh.id='assistant_new';
    const history=el('div');history.id='assistant_history';
    async function loadHistory(before){
      if(!state.revision){history.replaceChildren(el('p','保存任务后可查看历史版本。','department-help'));return;}
      const id=state.id,version=state.version;
      try{const value=await request(ctx,'assistant/drafts/'+id+'/history'+(before?'?before='+before:''));if(!current()||id!==state.id||version!==state.version)return;history.replaceChildren();
        for(const item of value.versions){const inspect=button(el,'查看版本 '+item.revision,async()=>{
          const inputVersion=state.version;
          try{const saved=await request(ctx,'assistant/drafts/'+id+'/revisions/'+item.revision);if(!current()||id!==state.id||inputVersion!==state.version)return;
            const preview=el('section',null,'assistant-record');preview.id='assistant_history_preview';
            preview.append(el('h3','历史版本 '+saved.revision),el('p','保存时间：'+new Date(saved.saved_at).toLocaleString('zh-CN'),'department-help'),el('p',saved.draft.instruction||'未填写任务说明'),el('p',tasks[saved.draft.task]+' · '+(saved.draft.data_origin==='synthetic'?'合成示例':'声明的脱敏资料'),'department-help'));
            const source=el('details');source.append(el('summary','原始资料'),el('pre',saved.draft.text||'此版本未填写原文'));preview.append(source);
            const observations=el('details');observations.append(el('summary','补录内容与来源（'+saved.draft.supplements.length+' 项）'));
            for(const item of saved.draft.supplements)observations.append(el('p',fields[item.field]+' · '+statuses[item.status]+' · '+origins[item.origin]),el('p',item.value||'未填写数值'),el('small','记录：'+item.record_id));
            preview.append(observations);
            const restore=button(el,'载入此版本，继续编辑',()=>{
              if(state.dirty||saving){feedback.replaceChildren(el('p','请先保存当前修改，待保存完成后再载入历史版本。','department-help'));return;}
              if(id!==state.id||inputVersion!==state.version){feedback.replaceChildren(el('p','当前内容已变化，请重新打开历史预览。','department-help'));return;}
              state={...initial(),id,revision:state.revision,draft:{...blank(),...structuredClone(saved.draft)},dirty:true,version:state.version+1};
              state.query=state.draft.context.case_query;state.category=state.draft.context.knowledge_category;render(box,ctx);
            });restore.id='assistant_restore';
            preview.append(el('p','载入后需重新核对并保存；保存会追加版本，已有历史保持不变。','department-help'),restore);
            history.replaceChildren(preview);
          }catch(exc){if(current())failure(el,feedback,exc);}
        },'assistant-draft');inspect.append(el('small',new Date(item.saved_at).toLocaleString('zh-CN')));history.append(inspect);}
        if(value.next_before)history.append(button(el,'更早版本',()=>loadHistory(value.next_before)));
        if(before)history.append(button(el,'返回最新历史',()=>loadHistory()));
      }catch(exc){if(current())failure(el,history,exc);}
    }
    const historyButton=button(el,'查看当前任务历史',()=>loadHistory());historyButton.id='assistant_history_open';
    async function loadDrafts(){
      try{const value=await request(ctx,'assistant/drafts');if(!current())return;list.replaceChildren();
        for(const item of value.drafts){const open=button(el,item.instruction||tasks[item.task]||'任务草稿',async()=>{
          if(state.dirty){feedback.replaceChildren(el('p','请先保存当前修改，再恢复其他草稿。','department-help'));return;}
          const version=state.version,id=state.id;
          try{const saved=await request(ctx,'assistant/drafts/'+item.id);if(!current()||version!==state.version||id!==state.id)return;state={...initial(),id:saved.id,revision:saved.revision,draft:{...blank(),...saved.draft}};state.query=state.draft.context.case_query;state.category=state.draft.context.knowledge_category;render(box,ctx);}catch(exc){if(current())failure(el,feedback,exc);}
        },'assistant-draft');open.dataset.draftId=item.id;open.append(el('small','版本 '+item.revision+' · '+new Date(item.saved_at).toLocaleString('zh-CN')));list.append(open);}
        if(!value.drafts.length)list.append(el('p','保存后可从这里恢复任务。','department-help'));
      }catch(exc){if(current())failure(el,list,exc);}
    }
    side.append(el('p','本机任务','eyebrow'),el('h2','保存与接续'),status,save,fresh,historyButton,history,el('h3','已保存草稿'),list);
    const shortcuts=el('div',null,'assistant-shortcuts');shortcuts.append(link(el,'临床资料工作台','#workbench'),link(el,'知识问答','#knowledge'),link(el,'完整处方工作台','#analysis'),link(el,'快速访次核对','#analysis-quick'));
    side.append(el('h3','直接打开'),shortcuts,el('p','草稿按账户保存；公开演示共用合成操作者。','department-help'));
    const intro=el('div',null,'assistant-intro');intro.append(el('p','科室助手','eyebrow'),el('h2','从一项具体工作开始'),el('p','整理资料、补齐信息、查阅依据，接续到原有业务工作台。','department-help'));
    const instruction=el('textarea');instruction.id='assistant_instruction';instruction.maxLength=1000;instruction.rows=2;instruction.value=state.draft.instruction;instruction.placeholder='例如：整理这份门诊记录并列出缺失信息';instruction.oninput=()=>{state.draft.instruction=instruction.value;state.plan=null;changed();};
    const task=select(el,tasks,state.draft.task,'assistant_task');
    const planResult=el('div');planResult.id='assistant_plan';planResult.setAttribute('role','status');
    const area=el('div');area.id='assistant_task_area';
    function drawPlan(){planResult.replaceChildren();if(!state.plan)return;
      if(state.plan.needs_selection){planResult.append(el('p',state.plan.candidates.length?'请求涉及多个任务，请选择本次先处理的任务。':'暂未识别出明确任务，请选择一个入口。','department-help'));return;}
      const ol=el('ol',null,'assistant-steps');for(const step of state.plan.steps)ol.append(el('li',steps[step]||step));planResult.append(ol);
    }
    const route=button(el,'确定任务',async()=>{const version=state.version;route.disabled=true;try{const value=await perform('assistant/plan',{instruction:state.draft.instruction,task:task.value},'识别任务');if(!current()||version!==state.version)return;state.plan=value;if(value.task&&state.draft.task!==value.task){state.draft.task=value.task;task.value=value.task;changed();}drawPlan();drawArea();}catch(exc){if(current())failure(el,feedback,exc);}finally{if(current())route.disabled=false;}},'primary');route.id='assistant_route';
    task.onchange=()=>{state.draft.task=task.value;state.plan=null;changed();drawPlan();drawArea();};
    const controls=el('div',null,'department-toolbar');controls.append(field(el,'任务类型',task),route);
    main.append(intro,field(el,'本次工作',instruction),controls,planResult,activity,feedback,area);

    function drawIntake(){
      let guided=true;
      const origin=select(el,{synthetic:'合成示例资料',deidentified:'操作者声明的脱敏资料'},state.draft.data_origin,'assistant_origin');
      const source=el('textarea');source.id='assistant_text';source.rows=8;source.maxLength=40000;source.value=state.draft.text;source.placeholder='粘贴带字段标签的门诊记录、CSV 或 JSON；可先加载合成样例。';
      const result=el('div');result.id='assistant_intake_result';
      const review=el('input');review.type='checkbox';review.id='assistant_review';
      const handoff=button(el,'带入快速访次复核',()=>{
        if(!state.prepared||!review.checked||!reviewed)return;
        const records=structuredClone(state.prepared.records);
        for(const item of state.prepared.supplements){const record=records.find(row=>row.record_id===item.record_id);if(record)record.evidence[item.field]='user-reviewed';}
        window.Department.useAssistantRecords(records,state.draft.data_origin,state.draft.text);
        location.hash='#analysis-quick';
      },'primary');handoff.id='assistant_handoff';handoff.disabled=true;
      const invalidate=()=>{changed(true);review.checked=false;reviewed=false;handoff.disabled=true;};
      source.oninput=()=>{state.draft.text=source.value;state.draft.supplements=[];invalidate();result.replaceChildren(el('p','原文已改变，请重新识别。当前补充已重置，已保存草稿不受影响。','department-help'));};
      origin.onchange=()=>{state.draft.data_origin=origin.value;invalidate();};
      const example=button(el,'加载合成样例',async()=>{const version=state.version;example.disabled=true;try{const data=await request(ctx,'analysis/example');if(!current()||version!==state.version)return;state.draft.text=data.text;state.draft.data_origin='synthetic';state.draft.supplements=[];invalidate();source.value=data.text;origin.value='synthetic';result.replaceChildren();}catch(exc){if(current())failure(el,feedback,exc);}finally{if(current())example.disabled=false;}});example.id='assistant_example';
      const prepare=button(el,'识别 / 更新缺项',async()=>{const version=state.version;prepare.disabled=true;try{const data=await perform('assistant/prepare',structuredClone(state.draft),'识别与更新缺项');if(!current()||version!==state.version)return;state.prepared=data;review.checked=false;reviewed=false;handoff.disabled=true;feedback.replaceChildren();drawRecords();}catch(exc){if(current())failure(el,feedback,exc);}finally{if(current())prepare.disabled=false;}},'primary');prepare.id='assistant_prepare';
      function drawRecords(){
        result.replaceChildren();const data=state.prepared;if(!data)return;
        const pending=data.missing.filter(item=>item.status==='not_asked'),unavailable=data.missing.filter(item=>item.status==='unavailable'),recorded=data.missing.filter(item=>item.status==='recorded');
        const progress=el('p','尚未记录 '+pending.length+' 项 · 已补充 '+recorded.length+' 项 · 无法提供 '+unavailable.length+' 项','department-help');progress.id='assistant_progress';progress.setAttribute('role','status');
        result.append(el('h3','识别 '+data.records.length+' 个访次'),progress);
        const toggle=button(el,guided?'查看全部字段':'逐项补录',()=>{
          if(!state.prepared){feedback.replaceChildren(el('p','补充内容已改变，请先更新缺项后切换视图。','department-help'));return;}
          guided=!guided;drawRecords();
        });toggle.id='assistant_toggle_fields';result.append(toggle);
        const next=pending[0];
        if(guided&&!next&&data.records.length)result.append(el('p','本轮待补项均已处理。可查看全部字段核对补充内容；无法提供的项目仍保留为空。请继续人工复核。','department-help'));
        if(!data.records.length)result.append(el('p','未识别到访次。请使用字段标签、CSV 或 JSON，并核对原文。','department-help'));
        for(const record of data.records){
          if(guided&&next&&record.record_id!==next.record_id)continue;
          if(guided&&!next)continue;
          const card=el('section',null,'assistant-record');card.append(el('h3',(record.subject_code||'患者代号待补充')+' · '+(record.date||'日期待补充')));
          const details=el('details');details.append(el('summary','查看原始记录与来源'),el('pre',JSON.stringify(data.original_records.find(row=>row.record_id===record.record_id),null,2)));card.append(details);
          const missing=data.missing.filter(item=>item.record_id===record.record_id);
          const present=Object.entries(fields).filter(([key])=>!missing.some(item=>item.field===key));
          for(const [key,label] of present)card.append(el('p',label+'：'+record[key]));
          for(const item of missing){
            if(guided&&item!==next)continue;
            const wrapper=el('div',null,'assistant-observation');wrapper.dataset.recordId=record.record_id;wrapper.dataset.field=item.field;
            const value=el('textarea');value.id='assistant_value_'+record.record_id+'_'+item.field;value.rows=2;value.maxLength=2000;value.value=item.value;value.disabled=item.status!=='recorded';
            const statusControl=select(el,statuses,item.status,'assistant_status_'+record.record_id+'_'+item.field);
            const originControl=select(el,origins,item.origin,'assistant_origin_'+record.record_id+'_'+item.field);
            const update=()=>{const entry={record_id:record.record_id,field:item.field,status:statusControl.value,origin:originControl.value,value:statusControl.value==='recorded'?value.value:''};
              state.draft.supplements=state.draft.supplements.filter(s=>s.record_id!==entry.record_id||s.field!==entry.field);state.draft.supplements.push(entry);invalidate();
            };
            statusControl.onchange=()=>{value.disabled=statusControl.value!=='recorded';if(value.disabled)value.value='';update();};originControl.onchange=update;value.oninput=update;
            const row=el('div',null,'assistant-observation-meta');row.append(field(el,'记录状态',statusControl),field(el,'信息来源',originControl));
            wrapper.append(el('strong',fields[item.field]));
            if(guided)wrapper.append(el('p',['syndrome','principle','prescription'].includes(item.field)?'请补录已有病历或医生确认的'+fields[item.field]+'；当前没有资料时可标记无法提供。':'请补录原文缺少的'+fields[item.field]+'，并注明信息来源。','department-help'));
            wrapper.append(row,field(el,'补充内容',value));
            if(guided){
              const advance=button(el,'确认本项并继续',async()=>{
                if(statusControl.value==='not_asked'||(statusControl.value==='recorded'&&!value.value.trim())){feedback.replaceChildren(el('p','请填写补充内容并选择已补充，或明确标记无法提供。','department-danger'));return;}
                update();advance.disabled=true;try{await prepare.onclick();}finally{if(current())advance.disabled=false;}
              },'primary');advance.id='assistant_next';
              const skip=button(el,'本项无法提供',async()=>{statusControl.value='unavailable';value.value='';value.disabled=true;update();skip.disabled=true;try{await prepare.onclick();}finally{if(current())skip.disabled=false;}});skip.id='assistant_unavailable';
              const actions=el('div',null,'department-toolbar');actions.append(advance,skip);wrapper.append(actions,el('p','确认会更新当前草稿；点击“保存任务草稿”后可在下次接续。','department-help'));
            }
            card.append(wrapper);
          }
          result.append(card);
        }
        if(data.warnings?.length)result.append(el('p','识别器返回 '+data.warnings.length+' 条提示，请在快速访次复核中核对字段和顺序。','department-help'));
      }
      review.onchange=()=>{reviewed=review.checked;handoff.disabled=!(reviewed&&state.prepared?.records.length);};
      const toolbar=el('div',null,'department-toolbar');toolbar.append(field(el,'资料来源',origin),example);
      const confirmation=field(el,'我已核对当前原文、补充信息及其来源，继续进入访次复核。',review);confirmation.className='department-check';
      area.append(toolbar,field(el,'原始门诊记录',source),el('p','修改原文会重新计算来源并重置当前补充。证候、治法和处方按已有记录或医生补充填写。','department-help'),prepare,result,confirmation,handoff);
      drawRecords();
    }

    async function drawLibrary(){
      area.append(el('p','公开知识资料按来源分类。病例文字和任务内容不会自动带入知识问答。','department-help'));
      const output=el('div');area.append(output);
      try{if(!state.library){const value=await request(ctx,'assistant/library');if(!current())return;state.library=value;}if(!output.isConnected)return;
        const category=select(el,{all:'全部资料',...categories},state.category,'assistant_category'),search=el('input');search.id='assistant_library_search';search.type='search';search.value=state.sourceSearch;search.placeholder='标题、PMID 或 DOI';
        const cards=el('div',null,'assistant-sources');cards.id='assistant_library';
        function fill(){cards.replaceChildren();const query=state.sourceSearch.trim().toLowerCase(),sources=state.library.sources.filter(item=>(state.category==='all'||item.knowledge_category===state.category)&&(!query||[item.title,item.title_zh,item.pmid,item.doi].join(' ').toLowerCase().includes(query)));
          cards.append(el('p','匹配 '+sources.length+' 条'+(sources.length>30?'，显示前 30 条，请缩小范围。':''),'department-help'));
          for(const source of sources.slice(0,30)){const card=el('article',null,'assistant-record');card.append(el('h3',source.title_zh||source.title),el('p',categories[source.knowledge_category]+' · '+(source.year||'年份未标注'),'department-help'));
            if(source.id===state.draft.context.knowledge_source_id||source.fulltext_source_id===state.draft.context.knowledge_source_id)card.append(el('p','本任务已选择的来源','department-tag'));
            if(source.retrieval_eligible)card.append(button(el,'选用此来源并打开问答',()=>{state.draft.context.knowledge_source_id=source.fulltext_source_id||source.id;changed();window.Department.selectKnowledgeSource(state.draft.context.knowledge_source_id);location.hash='#knowledge';}));
            else card.append(el('p','当前仅登记元数据，尚未接入可检索全文。','department-help'));
            if(source.locator_url&&/^\/api\/department\/knowledge\/(section|page)\/ft_[a-f0-9]{24}$/.test(source.locator_url)){const original=link(el,'阅读原文',source.locator_url);original.target='_blank';original.rel='noopener noreferrer';card.append(original);}cards.append(card);}
          if(!sources.length)cards.append(el('p','此范围暂无已接入资料。导入并登记相应来源后，目录才会显示内容。','department-empty'));
        }
        category.onchange=()=>{state.category=category.value;state.draft.context.knowledge_category=category.value;changed();fill();};search.oninput=()=>{state.sourceSearch=search.value;fill();};output.append(field(el,'资料类别',category),field(el,'搜索资料',search),cards);fill();
      }catch(exc){if(current()&&output.isConnected)failure(el,output,exc);}
    }

    function drawCases(){
      const form=el('form'),query=el('input');query.id='assistant_case_query';query.type='search';query.maxLength=200;query.required=true;query.value=state.query;query.placeholder='例如：口干 乏力；多个词用空格分隔';query.oninput=()=>{state.query=query.value;state.draft.context.case_query=query.value;changed();};
      const submit=el('button','检索已保存医案','primary');submit.id='assistant_case_search';submit.type='submit';const result=el('div');result.id='assistant_cases';
      function fill(){result.replaceChildren();const data=state.caseResult;if(!data)return;result.append(el('p','集合版本 '+data.revision+' · 命中 '+data.total+' 个访次 · '+(data.data_origin==='synthetic'?'合成示例':'操作者声明的脱敏资料'),'department-help'));
        if(!data.matches.length)result.append(el('p',data.revision?'未找到关键词匹配的访次，请调整检索词。':'尚无已保存集合。先在完整处方工作台导入、复核并保存医案。','department-empty'));
        for(const match of data.matches){const record=match.record,card=el('article',null,'assistant-record');card.append(el('h3',record.subject_code+' · '+(record.date||'日期待补充')),el('p','命中：'+match.matched_terms.join('、')));
          for(const key of ['condition','symptoms','syndrome','prescription'])card.append(el('p',(fields[key]||'病种')+'：'+(record[key]||'未记录')));
          const evidence=el('details');evidence.append(el('summary','命中字段与原文定位'),el('pre',JSON.stringify({matched_fields:match.matched_fields,source_sha256:record.source_sha256,evidence:record.evidence},null,2)));card.append(evidence);
          if(/^\/api\/department\/mingyirx\/imported\.html\?revision=[1-9][0-9]*$/.test(data.collection_url||'')){const open=link(el,'打开此版本医案对照',data.collection_url);open.target='_blank';open.rel='noopener noreferrer';card.append(open);}result.append(card);}
      }
      form.onsubmit=async event=>{event.preventDefault();const asked=query.value;submit.disabled=true;try{const value=await perform('assistant/cases',{query:asked},'检索已保存医案');if(!current()||!result.isConnected||asked!==state.query)return;const previous=state.draft.context.collection_revision;state.caseResult=value;state.draft.context.collection_revision=value.revision;changed();fill();if(previous!==null&&previous!==value.revision)result.prepend(el('p','集合已从版本 '+previous+' 更新为 '+value.revision+'，本次结果使用最新版本。','department-help'));}catch(exc){if(current()&&result.isConnected)failure(el,result,exc);}finally{if(current())submit.disabled=false;}};
      form.append(field(el,'检索关键词',query),submit);area.append(el('p','仅检索当前账户已明确保存的集合，按关键词命中排序。原始记录与任务草稿保持各自的版本。'+(state.draft.context.collection_revision!==null?' 本任务上次使用集合版本 '+state.draft.context.collection_revision+'；请重新检索确认最新结果。':''),'department-help'),form,result,link(el,'打开完整处方工作台','#analysis'));fill();
    }
    function drawArea(){area.replaceChildren();reviewed=false;const task=state.draft.task;
      if(task==='intake')drawIntake();else if(task==='knowledge')drawLibrary();else if(task==='cases')drawCases();else if(task==='prescriptions')area.append(el('h3','使用完整门诊处方工作台'),el('p','汇总分析、精确处方、医案传承、导入与保存以及报告下载均保留在原工作区。','department-help'),link(el,'打开完整处方工作台','#analysis'),link(el,'打开快速访次核对','#analysis-quick'));
      else{const choices=el('div',null,'assistant-task-cards');for(const [key,label] of Object.entries(tasks)){if(key==='auto')continue;choices.append(button(el,label,()=>{state.draft.task=key;taskControl();changed();drawArea();}));}area.append(choices);}
    }
    function taskControl(){task.value=state.draft.task;state.plan=null;drawPlan();}
    grid.append(main,side);box.replaceChildren(grid);updateStatus();drawPlan();drawArea();await loadDrafts();
  }
  window.DepartmentAssistant=Object.freeze({render,clear});
})();
