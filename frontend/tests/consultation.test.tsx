import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Consultation } from '../src/Consultation';
import { createConsultation } from '../src/model';
import type { Api, Flow, SavedDraft } from '../src/types';

const record = { record_id: 'REC-' + 'a'.repeat(24), subject_code: 'SYN-1', date: '2026-01-01', source_sha256: 'b'.repeat(64),
  evidence: { symptoms: [1] }, symptoms: 'Synthetic observation', tongue: '', pulse: '', syndrome: '', principle: '', prescription: '' };
const result = (stage: Flow['stage'] = 'review_ready'): Flow => ({ engine: 'langgraph', model_called: false, clinical_approval: null,
  stage, question: null, trace: ['recognize', 'assess', 'review'], counts: { pending: 0, recorded: 1, unavailable: 4 },
  prepared: { records: [record], original_records: [record], missing: [], supplements: [] } });
const simpleApi = (value: unknown): Api => async <T,>() => structuredClone(value) as T;
const deferred = () => { let resolve!: (value: unknown) => void; const promise = new Promise<unknown>(done => { resolve = done; }); return { promise, resolve }; };

describe('consultation session isolation', () => {
  it('ignores a late graph result after cancellation and retains source edits', async () => {
    const pending = deferred(); const model = createConsultation(async <T,>() => await pending.promise as T);
    model.change({ text: 'Synthetic source' }); const running = model.run(); model.cancel();
    pending.resolve(result()); await running;
    expect(model.getSnapshot().flow).toBeNull(); expect(model.getSnapshot().draft.text).toBe('Synthetic source');
    expect(model.getSnapshot().dirty).toBe(true);
  });
  it('rejects a response belonging to an older edit', async () => {
    const pending = deferred(); const model = createConsultation(async <T,>() => await pending.promise as T);
    const running = model.run(); model.change({ text: 'New synthetic source' }); pending.resolve(result()); await running;
    expect(model.getSnapshot().flow).toBeNull();
  });
  it('reconciles an explicit save after navigation but never after logout', async () => {
    for (const logout of [false, true]) {
      const pending = deferred(); const model = createConsultation(async <T,>() => await pending.promise as T);
      model.change({ text: 'Synthetic source' }); const original = model.getSnapshot(); const saving = model.save();
      if (logout) model.clear(); else model.pause();
      pending.resolve({ id: original.id, revision: 1, draft: original.draft, saved_at: '2026-11-02T00:00:00Z', task: 'intake', data_origin: 'synthetic', instruction: '' });
      await saving;
      expect(model.getSnapshot().revision).toBe(logout ? 0 : 1);
      expect(model.getSnapshot().draft.text).toBe(logout ? '' : 'Synthetic source');
    }
  });
  it('keeps dirty content when another task is requested', async () => {
    let called = false; const api: Api = async <T,>() => { called = true; return {} as T; }; const model = createConsultation(api);
    model.change({ text: 'Unsaved synthetic source' }); await model.open('other');
    expect(called).toBe(false); expect(model.getSnapshot().draft.text).toBe('Unsaved synthetic source');
  });
  it('restores history into a new revision with the current expected revision', async () => {
    const source = createConsultation(simpleApi({})).getSnapshot();
    const saved: SavedDraft = { id: source.id, revision: 2, draft: { ...source.draft, text: 'Current synthetic source' }, instruction: '', task: 'intake', data_origin: 'synthetic', saved_at: '2026-11-02T00:00:00Z' };
    const calls: object[] = [];
    const api: Api = async <T,>(path: string, body?: object) => {
      if (body) { calls.push(body); return { ...saved, revision: 3 } as T; }
      return (path.endsWith('/revisions/1') ? { ...saved, revision: 1, draft: { ...saved.draft, text: 'Earlier synthetic source' } } : saved) as T;
    };
    const model = createConsultation(api); await model.open(saved.id); await model.preview(1); model.restore();
    expect(model.getSnapshot().revision).toBe(2); expect(model.getSnapshot().draft.text).toBe('Earlier synthetic source');
    expect(model.getSnapshot().dirty).toBe(true); await model.save();
    expect(calls[0]).toMatchObject({ expected_revision: 2, draft: { text: 'Earlier synthetic source' } });
    expect(model.getSnapshot().revision).toBe(3);
  });
});

describe('React review boundary', () => {
  let container: HTMLDivElement, root: Root;
  beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
  afterEach(async () => { await act(() => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
  const button = (text: string) => [...container.querySelectorAll('button')].find(node => node.textContent === text)!;
  it('requires a human checkbox, calls the review endpoint, and resets on edits', async () => {
    const api: Api = async <T,>(_path: string, body?: object) => result(body && 'action' in body && body.action === 'review' ? 'reviewed' : 'review_ready') as T;
    const model = createConsultation(api);
    await act(async () => { root.render(<Consultation model={model}/>); await model.run(); });
    expect(button('确认本轮人工复核').disabled).toBe(true);
    await act(() => container.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());
    expect(button('确认本轮人工复核').disabled).toBe(false);
    await act(() => button('确认本轮人工复核').click());
    expect(button('带入快速访次复核')).toBeDefined();
    await act(() => model.change({ text: 'Changed synthetic source' }));
    expect(button('带入快速访次复核')).toBeUndefined();
  });
  it('renders source content as text and exposes task links without source parameters', async () => {
    const flow = result(); flow.prepared.records[0] = { ...record, symptoms: '<img src=x onerror=alert(1)>' };
    const model = createConsultation(simpleApi(flow));
    await act(async () => { root.render(<Consultation model={model}/>); await model.run(); });
    expect(container.querySelector('img')).toBeNull(); expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
    expect([...container.querySelectorAll('a')].map(link => link.getAttribute('href'))).toContain('#knowledge');
  });
});
