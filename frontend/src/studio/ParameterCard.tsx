import { useEffect, useState, type FormEvent } from 'react';
import { readValue } from '../spatial/types';
import { t } from './i18n';
import type { StudioParameter, StudioReferenceParameter } from './types';

function inputValue(value: number | null | undefined, unit: 'mm' | 'in') {
  if (value == null) return '';
  return unit === 'mm' ? String(Math.round(value * 1000) / 1000) : String(Math.round(value / 25.4 * 1000000) / 1000000);
}

export function ParameterCard({ parameter, unit, resolved, reference, disabled, onPreview, onAdjustReference }: {
  parameter: StudioParameter; unit: 'mm' | 'in'; resolved?: number; reference?: StudioReferenceParameter;
  disabled: boolean; onPreview: (id: string, value: number) => void;
  onAdjustReference?: (parameter: StudioParameter, reference: StudioReferenceParameter) => void;
}) {
  const sourceValue = parameter.expression ? resolved : parameter.value_mm;
  const usableReference = reference && Number.isFinite(reference.value_mm) ? reference : undefined;
  const current = usableReference ? usableReference.value_mm : sourceValue;
  const [input, setInput] = useState(() => inputValue(current, unit));
  const [invalid, setInvalid] = useState(false);
  useEffect(() => { setInput(inputValue(current, unit)); setInvalid(false); }, [parameter.id, current, unit]);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (usableReference) return;
    const value = readValue(input, unit);
    if (value === null || !Number.isFinite(value)) { setInvalid(true); return; }
    setInvalid(false); onPreview(parameter.id, value);
  }
  const status = { source: t('原图 Source'), inferred: t('推断 Inferred'), user: t('修改 Amended'), designed: t('设计 Designed'), tbc: t('待确认 TBC') }[parameter.status] || parameter.status;
  const label = usableReference?.label || parameter.label || parameter.id;
  return <section className={`parameter-card${usableReference ? ' reference-parameter' : ''}`}>
    <div className="parameter-heading"><strong>{label}</strong><span className={`status-tag ${usableReference ? 'reference' : parameter.status}`}>{usableReference ? t('Reference', '参考') : status}</span></div>
    <form className="parameter-form" onSubmit={submit}>
      <input aria-label={label} className={usableReference ? 'reference-value' : undefined} value={input} placeholder={t('待确认 TBC')} readOnly={!!usableReference} onChange={event => { if (!usableReference) setInput(event.target.value); }} disabled={disabled || (!usableReference && !!parameter.expression)} aria-invalid={invalid} />
      <span>{unit}</span>
      {usableReference ? <button className="subtle" disabled={disabled || !onAdjustReference} type="button" onClick={() => onAdjustReference?.(parameter, usableReference)}>{t('Adjust', '调整')}</button> : <button className="subtle" disabled={disabled || !!parameter.expression || current === readValue(input, unit)} type="submit">{t('预览')}</button>}
    </form>
    {invalid && <p className="field-error">{t('Enter a number or fraction / 请输入数字或分数')}</p>}
    {!usableReference && parameter.expression && <p className="hint">{t('由关联尺寸计算 ·')}{parameter.expression}</p>}
    {(usableReference || parameter.evidence?.length > 0) && <details className="parameter-evidence">
      <summary>{usableReference ? t('Source details', '原图详情') : <>{t('原图依据 ·')}{parameter.evidence.length}</>}</summary>
      {usableReference && <>
        <p>{t('Original control', '原图控制项')}: {parameter.label || parameter.id}</p>
        <p>{t('Original observation', '原图记录')}: {sourceValue == null ? t('待确认 TBC') : `${inputValue(sourceValue, unit)} ${unit}`} · {status}</p>
        {parameter.expression && <p>{t('由关联尺寸计算 ·')}{parameter.expression}</p>}
      </>}
      {parameter.evidence?.map((item, index) => <p key={index}>P{item.page ?? item.page_number ?? '?'} · {item.text || item.description || item.document_id}</p>)}
    </details>}
  </section>;
}
