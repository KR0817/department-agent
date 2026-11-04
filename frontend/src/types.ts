export const fieldLabels = { symptoms: '症状', tongue: '舌象', pulse: '脉象', syndrome: '证候', principle: '治法', prescription: '处方原文' };
export const originLabels = { unknown: '来源待确认', patient: '患者自述', clinician: '医生观察或记录', history: '历史资料', operator: '操作者补充' };
export type Field = keyof typeof fieldLabels;
export type Origin = keyof typeof originLabels;
export type Observation = { record_id: string; field: Field; value: string; status: 'recorded' | 'not_asked' | 'unavailable'; origin: Origin };
export interface Draft {
  schema: 'department-task-v1'; instruction: string; task: 'intake'; data_origin: 'synthetic' | 'deidentified';
  text: string; supplements: Observation[];
  context: { case_query: string; collection_revision: number | null; knowledge_source_id: string; knowledge_category: string };
}
export type CaseRecord = Record<Field, string> & {
  record_id: string; subject_code: string; date: string; source_sha256: string;
  evidence: Record<string, string | number[]>;
};
export interface Flow {
  engine: 'langgraph'; model_called: false; stage: 'need_source' | 'question' | 'review_ready' | 'reviewed';
  trace: string[]; question: { record_id: string; field: Field; prompt: string } | null;
  counts: { pending: number; recorded: number; unavailable: number };
  prepared: { records: CaseRecord[]; original_records: CaseRecord[]; supplements: Observation[]; missing: Observation[]; warnings?: unknown[] };
  clinical_approval: null;
}
export interface SavedSummary { id: string; revision: number; instruction: string; saved_at: string; task: string; data_origin: string }
export interface SavedDraft extends SavedSummary { draft: Draft }
export interface History { versions: SavedSummary[]; next_before: number | null }
export type Api = <T>(path: string, body?: object, signal?: AbortSignal) => Promise<T>;
export interface Host { api: Api; isCurrent: () => boolean }

declare global {
  interface Window {
    Department: { useAssistantRecords: (records: CaseRecord[], origin: string, text: string) => void };
  }
}
