import { useEffect, useState, useSyncExternalStore } from 'react';
import type { Consultation as Model } from './model';
import { fieldLabels, originLabels, type Observation, type Origin } from './types';

const nodeLabels: Record<string, string> = { recognize: '解析原始记录', assess: '检查资料缺项', ask_question: '等待补充信息', request_source: '等待原始资料', review: '准备人工复核' };
const statusLabels = { recorded: '已补充', unavailable: '无法提供', not_asked: '待补充' };

export function Consultation({ model }: { model: Model }) {
  const state = useSyncExternalStore(model.subscribe, model.getSnapshot);
  const { draft, flow, busy } = state;
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => { setConfirmed(false); }, [flow, state.flowCurrent]);
  const question = flow?.question;
  const observation: Observation | null = question ? draft.supplements.find(item => item.record_id === question.record_id && item.field === question.field) ??
    { record_id: question.record_id, field: question.field, status: 'not_asked', value: '', origin: 'unknown' } : null;
  const record = flow?.prepared.records.find(item => item.record_id === question?.record_id);
  const invalid = draft.supplements.some(item => item.status === 'recorded' && !item.value.trim());
  const activity = flow && !state.flowCurrent ? '内容已编辑，确认后更新本轮流程。' : flow?.stage === 'question' ? '请补充当前项目，或标记无法提供。' :
    flow?.stage === 'review_ready' ? '本轮采集已完成，等待人工复核。' : flow?.stage === 'reviewed' ? '本轮信息已复核，可继续核对访次。' : '选择一份资料，开始本次采集。';
  const updateAnswer = (patch: Partial<Observation>) => { if (observation) model.observe({ ...observation, status: 'recorded', ...patch }); };
  const handoff = () => {
    if (!flow || flow.stage !== 'reviewed' || !state.flowCurrent || busy) return;
    const records = structuredClone(flow.prepared.records);
    for (const item of draft.supplements) {
      const target = records.find(row => row.record_id === item.record_id);
      if (target) target.evidence[item.field] = 'user-reviewed';
    }
    window.Department.useAssistantRecords(records, draft.data_origin, draft.text);
    location.hash = '#analysis-quick';
  };
  return <div className="consultation-grid">
    <section className="consultation-main" aria-label="问诊信息采集">
      <div className="consultation-heading"><div><p className="eyebrow">问诊信息采集</p><h2>让每一项补充都有依据</h2>
        <p className="department-help">从原始记录开始，逐项补充信息，再进入人工复核。</p></div><span className="consultation-badge">本机处理</span></div>
      <div className="consultation-activity" role="status" aria-live="polite"><span>{busy || state.message || activity}</span>
        {busy && busy !== '正在保存草稿' && <button type="button" className="secondary" onClick={model.cancel}>取消等待</button>}</div>
      <fieldset disabled={Boolean(busy)} className="consultation-controls">
        <section className="consultation-card">
          <div className="consultation-section-title"><h3><span>01</span> 原始资料</h3><button id="consultation_example" type="button" className="secondary" onClick={() => void model.example()}>加载合成样例</button></div>
          <label>本次任务<input id="consultation_instruction" maxLength={1000} value={draft.instruction} placeholder="例如：补全本次门诊记录" onChange={event => model.change({ instruction: event.target.value })}/></label>
          <label>资料来源<select value={draft.data_origin} onChange={event => model.change({ data_origin: event.target.value as 'synthetic' | 'deidentified' })}>
            <option value="synthetic">合成示例资料</option><option value="deidentified">操作者声明的脱敏资料</option></select></label>
          <label>原始门诊记录<textarea id="consultation_text" rows={6} maxLength={40000} value={draft.text} placeholder="粘贴带字段标签的记录、CSV 或 JSON" onChange={event => model.change({ text: event.target.value, supplements: [] })}/></label>
          <p className="department-help">修改原文会重置当前补充。原文、来源定位和补充记录分别保留。</p>
          <button id="consultation_run" type="button" className="primary" onClick={() => void model.run()}>开始 / 更新流程</button>
        </section>
        {flow && <ol className="consultation-trace" aria-label="本轮已执行步骤">{flow.trace.map(node => <li key={node}>{nodeLabels[node] ?? node}</li>)}</ol>}
        {flow?.stage === 'need_source' && <p className="department-empty">尚未识别到访次。请填写结构化原文或加载合成样例。</p>}
        {flow && flow.stage !== 'need_source' && <div className="consultation-counts" role="status">
          {!state.flowCurrent && <span>上次流程结果：</span>}
          <span><b>{flow.prepared.records.length}</b> 个访次</span><span><b>{flow.counts.pending}</b> 项待补充</span><span><b>{flow.counts.recorded}</b> 项已补充</span><span><b>{flow.counts.unavailable}</b> 项无法提供</span>
        </div>}
        {question && observation && <section className="consultation-card consultation-question" aria-label="当前追问">
          <p className="eyebrow">{record?.subject_code || '当前访次'} · {record?.date || '日期未记录'}</p>
          <h3><span>02</span> 补充{fieldLabels[question.field]}</h3><p>{question.prompt}</p>
          <label>信息来源<select id="consultation_origin" value={observation.origin} onChange={event => updateAnswer({ origin: event.target.value as Origin })}>
            {Object.entries(originLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>本项补充<textarea id="consultation_answer" rows={3} maxLength={2000} value={observation.value} onChange={event => updateAnswer({ value: event.target.value })}/></label>
          <div className="consultation-actions"><button id="consultation_next" type="button" className="primary" disabled={observation.status !== 'recorded' || !observation.value.trim()} onClick={() => void model.run()}>确认本项并继续</button>
            <button id="consultation_unavailable" type="button" className="secondary" onClick={() => { model.observe({ ...observation, status: 'unavailable', value: '' }); void model.run(); }}>本项无法提供</button></div>
          <p className="department-help">补录已有观察或医生记录；没有资料的项目保留为空。</p>
        </section>}
        {!!draft.supplements.length && <section className="consultation-card"><h3>已补充的观察</h3><ul className="consultation-observations">
          {draft.supplements.map(item => <li key={item.record_id + item.field}>
            <div><strong>{fieldLabels[item.field]} · {statusLabels[item.status]}</strong><p>{item.value || '尚无可填写的资料'}</p><small>{flow?.prepared.records.find(row => row.record_id === item.record_id)?.subject_code || item.record_id} · {originLabels[item.origin]}</small></div>
            <button type="button" className="text-button" onClick={() => void model.reopenObservation(item)}>重新补录</button>
          </li>)}</ul></section>}
        {flow && ['review_ready', 'reviewed'].includes(flow.stage) && state.flowCurrent && <section className="consultation-card consultation-review" aria-label="人工复核">
          <h3><span>03</span> 核对本次采集</h3><p>本轮待补项已处理。请核对原文、补充内容及其来源；无法提供的项目仍保留为空。</p>
          {flow.prepared.records.map(row => <details key={row.record_id}><summary>{row.subject_code || row.record_id} · {row.date || '日期未记录'}</summary>
            <dl>{Object.entries(fieldLabels).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{row[key as keyof typeof fieldLabels] || '未记录'}</dd></div>)}</dl>
          </details>)}
          {flow.stage === 'review_ready' ? <><label className="consultation-check"><input id="consultation_review_check" type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)}/>我已核对原文、补充内容及其来源</label>
            <button id="consultation_review" type="button" className="primary" disabled={!confirmed} onClick={() => void model.run('review')}>确认本轮人工复核</button></> :
            <><p className="consultation-success">本轮信息已复核，可以继续核对访次与处方。</p><button id="consultation_handoff" type="button" className="primary" onClick={handoff}>带入快速访次复核</button></>}
          <p className="department-help">业务记录由原工作台进一步复核和显式保存。</p>
        </section>}
        {flow && <details className="consultation-card"><summary>查看原文解析与来源</summary><pre>{JSON.stringify(flow.prepared.original_records, null, 2)}</pre></details>}
      </fieldset>
    </section>
    <aside className="consultation-side" aria-label="任务保存与接续">
      <p className="eyebrow">本机任务</p><h2>保存与接续</h2>
      <p role="status">{state.dirty ? '有未保存修改' : state.revision ? '草稿已同步' : '新任务'} · {state.revision ? '版本 ' + state.revision : '尚未保存'}</p>
      <button id="consultation_save" type="button" className="primary" disabled={Boolean(busy) || invalid} onClick={() => void model.save()}>保存任务草稿</button>
      {invalid && <p className="department-help">请填写当前补充内容，或明确选择无法提供。</p>}
      <div className="consultation-actions"><button id="consultation_new" type="button" className="secondary" disabled={Boolean(busy)} onClick={model.fresh}>新建任务</button>
        <button type="button" className="secondary" disabled={Boolean(busy)} onClick={model.saveAsNew}>保留内容另建草稿</button></div>
      <button id="consultation_history" type="button" className="secondary" disabled={Boolean(busy) || !state.revision} onClick={() => void model.history()}>查看版本历史</button>
      {state.history && <section aria-label="版本历史"><h3>历史版本</h3>{state.history.versions.map(item => <button data-revision={item.revision} type="button" className="consultation-saved" disabled={Boolean(busy)} key={item.revision} onClick={() => void model.preview(item.revision)}>
        查看版本 {item.revision}<small>{new Date(item.saved_at).toLocaleString('zh-CN')}</small></button>)}
        {state.history.next_before && <button type="button" className="text-button" disabled={Boolean(busy)} onClick={() => void model.history(state.history?.next_before ?? undefined)}>更早版本</button>}
        <button type="button" className="text-button" disabled={Boolean(busy)} onClick={() => void model.history()}>最新历史</button></section>}
      {state.preview && <section className="consultation-history" aria-label="历史内容预览"><h3>预览版本 {state.preview.revision}</h3><p>{state.preview.draft.instruction || '未填写任务说明'}</p>
        <details><summary>历史原文</summary><pre>{state.preview.draft.text}</pre></details>
        {state.preview.draft.supplements.map(item => <p key={item.record_id + item.field}>{fieldLabels[item.field]} · {statusLabels[item.status]} · {originLabels[item.origin]}：{item.value || '未记录'}</p>)}
        <button id="consultation_restore" type="button" className="secondary" disabled={Boolean(busy) || state.dirty} onClick={model.restore}>载入此版本继续编辑</button><p className="department-help">保存会追加新版本，历史内容保持不变。</p></section>}
      <h3>已保存的采集任务</h3>
      <div className="consultation-saved-list">{state.saved.map(item => <button data-draft-id={item.id} type="button" className="consultation-saved" disabled={Boolean(busy)} key={item.id} onClick={() => void model.open(item.id)}>
        {item.instruction || '问诊采集草稿'}<small>版本 {item.revision} · {new Date(item.saved_at).toLocaleString('zh-CN')}</small></button>)}</div>
      {!state.saved.length && <p className="department-help">保存后可在这里恢复，或在科室助手中查看完整草稿历史。</p>}
      <h3>继续科室工作</h3><nav className="consultation-links" aria-label="业务工作台"><a href="#assistant">科室助手与医案检索</a><a href="#knowledge">知识问答</a><a href="#analysis">完整门诊处方工作台</a><a href="#workbench">临床资料工作台</a></nav>
      <p className="department-help">资料采集使用本机规则流程，当前没有调用语言模型。知识问答接收单独提出的通用问题。</p>
    </aside>
  </div>;
}
