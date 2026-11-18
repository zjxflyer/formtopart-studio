import { t } from './i18n';
import { useRef, useState, type FormEvent } from 'react';
import { StudioSheet } from './StudioSheet';
import type { BoardAxis, BoardSpec, Grain, StudioNode } from './types';

export function BoardSpecEditor({ node, dimensions, onClose, onPreview }: {
  node: StudioNode; dimensions: Array<number | null>; onClose: () => void; onPreview: (spec: BoardSpec) => Promise<boolean>;
}) {
  const [axes, setAxes] = useState({ length_axis: node.board_spec?.length_axis || '', width_axis: node.board_spec?.width_axis || '', thickness_axis: node.board_spec?.thickness_axis || '' });
  const [grain, setGrain] = useState<Grain>(node.board_spec?.grain || 'none');
  const [lengthAllowance, setLengthAllowance] = useState(node.board_spec?.allowance_length_mm || 0);
  const [widthAllowance, setWidthAllowance] = useState(node.board_spec?.allowance_width_mm || 0);
  const [edges, setEdges] = useState<[string, string, string, string]>(node.board_spec?.edges || ['0', '0', '0', '0']);
  const [notes, setNotes] = useState(node.board_spec?.machining_notes || '');
  const [busy, setBusy] = useState(false); const mutex = useRef(false); const [error, setError] = useState('');
  const validAxes = Object.values(axes).every(Boolean) && new Set(Object.values(axes)).size === 3;
  async function submit(event: FormEvent) {
    event.preventDefault(); if (mutex.current) return;
    if (!validAxes) { setError(t('Choose a different axis for length, width and thickness. / 长、宽、厚须选择三个不同的轴。')); return; }
    if (![lengthAllowance, widthAllowance].every(value => Number.isFinite(value) && value >= 0)) { setError(t('Allowances must be zero or positive. / 余量须为零或正数。')); return; }
    mutex.current = true; setBusy(true); setError('');
    try {
      if (await onPreview({ length_axis: axes.length_axis as BoardAxis, width_axis: axes.width_axis as BoardAxis, thickness_axis: axes.thickness_axis as BoardAxis,
        grain, allowance_length_mm: lengthAllowance, allowance_width_mm: widthAllowance, edges, profile: 'rectangle', machining_notes: notes })) onClose();
      else setError(t('Could not prepare the board preview. Your saved design is unchanged. / 未能生成板件预览，已保存设计保持不变。'));
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { mutex.current = false; setBusy(false); }
  }
  return <StudioSheet title={t("板件规格 Board specification")} titleId="board-spec-title" onClose={onClose} locked={busy}>
    <form className="sheet-body board-spec-form" onSubmit={event => void submit(event)}><h3>{t(node.name)}</h3>
      <p className="hint">{t("矩形实体板件 · 本地尺寸 / Rectangular physical panel · local dimensions")}</p>
      <div className="board-local-dimensions">{['X', 'Y', 'Z'].map((axis, index) => <span key={axis}>{axis}: {dimensions[index] == null ? t('待确认 TBC') : `${Math.round(dimensions[index]! * 1000) / 1000} mm`}</span>)}</div>
      <fieldset disabled={busy}><div className="material-form-grid">
        {([{ key: 'length_axis', label: t('长度轴 Length axis') }, { key: 'width_axis', label: t('宽度轴 Width axis') }, { key: 'thickness_axis', label: t('厚度轴 Thickness axis') }] as const).map(({ key, label }) => <label key={key}>{label}<select aria-label={label} value={axes[key]} required onChange={event => setAxes(previous => ({ ...previous, [key]: event.target.value }))}><option value="">{t("选择轴 Choose axis")}</option>{['X', 'Y', 'Z'].map(axis => <option key={axis} value={axis}>{axis}</option>)}</select></label>)}
        <label>{t("纹理 Grain")}<select aria-label={t("纹理 Grain")} value={grain} onChange={event => setGrain(event.target.value as Grain)}><option value="none">{t("无指定 None")}</option><option value="length">{t("沿长度 Length")}</option><option value="width">{t("沿宽度 Width")}</option></select></label>
        <label>{t("长度总余量 Length allowance (mm)")}<input type="number" min="0" step="any" value={lengthAllowance} onChange={event => setLengthAllowance(Number(event.target.value))} /></label>
        <label>{t("宽度总余量 Width allowance (mm)")}<input type="number" min="0" step="any" value={widthAllowance} onChange={event => setWidthAllowance(Number(event.target.value))} /></label>
      </div><p className="hint">{t("余量是开料长宽的总增量，成品尺寸保持不变。 Allowances are total additions to cutting sizes; finished sizes stay unchanged.")}</p>
      <h4>{t("封边 Edge treatment")}</h4><div className="material-form-grid">{[t('左 Left'), t('右 Right'), t('上 Top'), t('下 Bottom')].map((label, index) => <label key={label}>{label}<input maxLength={120} value={edges[index]} onChange={event => setEdges(previous => previous.map((value, ordinal) => ordinal === index ? event.target.value : value) as typeof edges)} /></label>)}</div>
      <label className="input-label">{t("加工说明 Machining notes")}<textarea rows={3} maxLength={3000} value={notes} onChange={event => setNotes(event.target.value)} /></label></fieldset>
      {error && <p className="field-error" role="alert">{t(error)}</p>}
      <div className="sheet-actions"><button type="button" className="secondary" disabled={busy} onClick={onClose}>{t("取消 Cancel")}</button><button type="submit" className="primary" disabled={busy}>{t("预览板件规格 Preview")}</button></div>
    </form>
  </StudioSheet>;
}
