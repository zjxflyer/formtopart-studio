import { useId, type ReactNode } from 'react';
import { t, useLanguage } from './i18n';
import type { DrawingResultItem } from './drawingResultItems';
import './drawing-results.css';

type Props = { items: DrawingResultItem[]; value: string; onChange: (id: string) => void; children?: ReactNode;
  selectLabel?: string; allowUnselected?: boolean };

function statusSuffix(status?: string) {
  if (status === 'stale') return t('Needs updating', '需要更新');
  if (status === 'incomplete') return t('Incomplete', '不完整');
  if (status === 'needs_review') return t('Needs review', '需要审阅');
  return '';
}

/** One controlled list, using result identity rather than guessed directions. */
export function DrawingResults({ items, value, onChange, children, selectLabel, allowUnselected = false }: Props) {
  useLanguage();
  const selectId = useId();
  const matchingIndex = items.findIndex(item => item.id === value);
  const index = allowUnselected ? matchingIndex : Math.max(0, matchingIndex);
  const selected = items[index];
  const optionSections = new Map<string, { label?: string; options: ReactNode[] }>();
  items.forEach((item, itemIndex) => {
    const key = item.group?.id || '';
    const section = optionSections.get(key) || { label: item.group?.label, options: [] };
    section.options.push(<option key={item.id} value={item.id}>
      {`${itemIndex + 1}. ${item.label}${item.page ? ` · P${item.page}` : ''}${statusSuffix(item.status) ? ` · ${statusSuffix(item.status)}` : ''}`}
    </option>);
    optionSections.set(key, section);
  });
  const change = (id: string) => { if (items.some(item => item.id === id)) onChange(id); };
  return <nav className="drawing-results" aria-label={t('Drawing results', '图纸成果列表')}>
    <div className="drawing-results-selection">
      {items.length ? <><label className="drawing-results-label" htmlFor={selectId}>{t('Results', '成果')}</label>
        <select id={selectId} aria-label={selectLabel || t('Drawing result', '图纸成果')} value={selected?.id || ''} title={selected?.label}
          onChange={event => change(event.target.value)}>
          {!selected && <option value="" disabled>{t('Choose a drawing', '选择图纸')}</option>}
          {Array.from(optionSections, ([key, section]) => section.label ? <optgroup key={key} label={section.label}>{section.options}</optgroup> : section.options)}
        </select></> : <span className="drawing-results-empty" role="status">{t('No drawing results yet', '尚无图纸成果')}</span>}
    </div>
    <div className="drawing-results-controls">
      <button type="button" aria-label={t('Previous drawing', '上一张图纸')} disabled={!selected || index === 0}
        onClick={() => { if (index > 0) change(items[index - 1].id); }}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m10 3-5 5 5 5" /></svg><span>{t('Previous', '上一张')}</span>
      </button>
      <span className="drawing-results-count" aria-label={t(`Drawing ${selected ? index + 1 : 0} of ${items.length}`, `第${selected ? index + 1 : 0}张，共${items.length}张`)}>
        {selected ? index + 1 : 0}/{items.length}
      </span>
      <button type="button" aria-label={t('Next drawing', '下一张图纸')} disabled={!items.length || index >= items.length - 1}
        onClick={() => { if (index < items.length - 1) change(items[index + 1].id); }}>
        <span>{t('Next', '下一张')}</span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5" /></svg>
      </button>
    </div>
    {children && <div className="drawing-results-extra">{children}</div>}
  </nav>;
}
