import type { Api, Draft, Flow, History, Observation, SavedDraft, SavedSummary } from './types';

const blank = (): Draft => ({ schema: 'department-task-v1', instruction: '', task: 'intake', data_origin: 'synthetic', text: '', supplements: [], context: { case_query: '', collection_revision: null, knowledge_source_id: '', knowledge_category: 'all' } });
const initial = () => ({ id: crypto.randomUUID() as string, revision: 0, draft: blank(), dirty: false, flow: null as Flow | null,
  flowCurrent: false, busy: '', message: '', saved: [] as SavedSummary[], history: null as History | null, preview: null as SavedDraft | null });
export type State = ReturnType<typeof initial>;

/** In-memory session state; only explicit draft saves persist clinical text. */
export function createConsultation(api: Api) {
  let state = initial(), generation = 0, session = 0, edit = 0;
  let controller: AbortController | null = null;
  const listeners = new Set<() => void>();
  const set = (patch: Partial<State>) => { state = { ...state, ...patch }; listeners.forEach(fn => fn()); };
  const errorText = (error: unknown) => {
    const status = typeof error === 'object' && error !== null && 'status' in error ? error.status : null;
    return status === 409 ? '资料或草稿版本已变化。当前内容已保留，可另存草稿；复核前请先完成本轮采集。' :
      status === 422 ? '请核对输入：已补充项目须有内容，原文使用带字段标签的文本、CSV 或 JSON。' :
      status === 429 ? '本账户草稿已达到上限，请接续已有任务。' : '操作未完成，请检查本机服务后重试。当前编辑已保留。';
  };
  async function operation<T>(label: string, fn: (signal: AbortSignal) => Promise<T>, done: (value: T) => void, saving = false) {
    if (state.busy) return;
    const token = ++generation, epoch = session, identity = state.id, version = edit;
    const owned = new AbortController(); controller = owned;
    set({ busy: label, message: '' });
    try {
      const value = await fn(owned.signal);
      if (epoch === session && identity === state.id && !owned.signal.aborted && (saving || token === generation) && version === edit) done(value);
    } catch (error) {
      if (epoch === session && token === generation && !owned.signal.aborted) set({ message: errorText(error) });
    } finally {
      if (epoch === session && (token === generation || saving)) { controller = null; set({ busy: '' }); }
    }
  }
  function change(patch: Partial<Draft>, keepQuestion = false) {
    edit++;
    set({ draft: { ...state.draft, ...patch }, dirty: true, flowCurrent: false,
      flow: keepQuestion ? state.flow : null, preview: null, message: '' });
  }
  function observe(item: Observation) {
    change({ supplements: [...state.draft.supplements.filter(old => old.record_id !== item.record_id || old.field !== item.field), item] }, true);
  }
  function run(action: 'advance' | 'review' = 'advance') {
    const draft = structuredClone(state.draft);
    return operation('正在运行采集流程', signal => api<Flow>('department/assistant/consultation', { action, draft }, signal),
      flow => set({ flow, flowCurrent: true }));
  }
  function pause() {
    if (state.busy === '正在保存草稿') return;
    generation++; controller?.abort(); controller = null; set({ busy: '' });
  }
  return {
    getSnapshot: () => state,
    subscribe: (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; },
    change, observe, run, pause,
    cancel: () => { pause(); set({ message: '已取消等待，编辑已保留；服务器可能仍在完成只读处理。' }); },
    clear: () => { session++; generation++; controller?.abort(); controller = null; edit++; state = initial(); listeners.forEach(fn => fn()); },
    list: () => operation('正在读取任务', signal => api<{ drafts: SavedSummary[] }>('department/assistant/drafts', undefined, signal), value => set({ saved: value.drafts.filter(item => item.task === 'intake') })),
    example: () => operation('正在读取合成样例', signal => api<{ text: string }>('department/analysis/example', undefined, signal), value => change({ text: value.text, data_origin: 'synthetic', supplements: [] })),
    save: () => {
      const draft = structuredClone(state.draft), id = state.id, revision = state.revision;
      return operation('正在保存草稿', signal => api<SavedDraft>('department/assistant/drafts/' + id, { expected_revision: revision, draft }, signal), value => {
        const { draft: _, ...summary } = value;
        set({ revision: value.revision, dirty: false, message: '任务草稿已保存。业务归档继续由原工作台完成。', saved: [summary, ...state.saved.filter(item => item.id !== id)], history: null, preview: null });
      }, true);
    },
    saveAsNew: () => { if (!state.busy) { edit++; set({ id: crypto.randomUUID(), revision: 0, dirty: true, history: null, preview: null }); } },
    fresh: () => { if (state.dirty || state.busy) { set({ message: '请先保存当前修改，再新建任务。' }); return; } edit++; const saved = state.saved; set({ ...initial(), saved }); },
    open: (id: string) => {
      if (state.dirty) { set({ message: '请先保存当前修改，再打开其他任务。' }); return; }
      return operation('正在恢复任务', signal => api<SavedDraft>('department/assistant/drafts/' + id, undefined, signal), value => {
        edit++; set({ id: value.id, revision: value.revision, draft: { ...blank(), ...value.draft }, dirty: false, flow: null, flowCurrent: false, history: null, preview: null, message: '已恢复草稿。点击开始 / 更新流程，接续下一项。' });
      });
    },
    history: (before?: number) => operation('正在读取历史', signal => api<History>('department/assistant/drafts/' + state.id + '/history' + (before ? '?before=' + before : ''), undefined, signal), value => set({ history: value, preview: null })),
    preview: (revision: number) => operation('正在预览历史', signal => api<SavedDraft>('department/assistant/drafts/' + state.id + '/revisions/' + revision, undefined, signal), value => set({ preview: value })),
    restore: () => {
      if (state.dirty || state.busy) { set({ message: '请先保存当前编辑，再载入历史版本。' }); return; }
      if (state.preview) { change(structuredClone(state.preview.draft)); set({ message: '历史内容已载入。重新核对后保存将追加新版本。' }); }
    },
    reopenObservation: async (item: Observation) => { observe({ ...item, value: '', status: 'not_asked' }); await run(); },
  };
}
export type Consultation = ReturnType<typeof createConsultation>;
