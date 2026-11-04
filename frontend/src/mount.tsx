import { createRoot, type Root } from 'react-dom/client';
import { Consultation } from './Consultation';
import { createConsultation, type Consultation as Model } from './model';
import type { Host } from './types';
import './style.css';

let root: Root | null = null;
let model: Model | null = null;
window.addEventListener('beforeunload', event => {
  if (model?.getSnapshot().dirty) { event.preventDefault(); event.returnValue = ''; }
});

export function unmount() { model?.pause(); root?.unmount(); root = null; }
export function clear() { model?.clear(); unmount(); model = null; }
export function render(container: HTMLElement, host: Host) {
  unmount();
  if (!host.isCurrent()) return;
  if (!document.getElementById('consultation-styles')) {
    const link = document.createElement('link'); link.id = 'consultation-styles';
    link.rel = 'stylesheet'; link.href = '/static/consultation/consultation.css'; document.head.append(link);
  }
  model ??= createConsultation(host.api);
  container.replaceChildren();
  root = createRoot(container);
  root.render(<Consultation model={model}/>);
  void model.list();
}
