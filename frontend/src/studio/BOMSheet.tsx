import { t } from './i18n';
import { useEffect, useRef, useState } from 'react';
import { studioAPI } from './api';
import { StudioSheet } from './StudioSheet';
import { WorkflowBuildActions } from './WorkflowBuildActions';
import { ProductionGuide, type ProductionAction } from './ProductionGuide';
import { materialDisplayText } from './materials';
import type { BOMIssue, BOMReport, BOMReviewRow, BOMRow, PanelSpecPreviewRow, SuggestedBoard } from './types';

const number = (value: number | null) => value != null && Number.isFinite(value) ? String(Math.round(value * 1000) / 1000) : '—';
function contextText(row: Pick<BOMRow, 'contexts'>) { return row.contexts?.[0]?.context_path.map(item => t(item.name)).join(' › ') || ''; }
function modeledSize(board: SuggestedBoard) { return [board.length_mm, board.width_mm, board.thickness_mm].map(number).join(' × '); }
function modeledAxes(board: SuggestedBoard) { return `L ${board.length_axis} · W ${board.width_axis} · T ${board.thickness_axis}`; }
function IssueList({ title, issues, onSelect, onChooseBoardStock }: { title: string; issues: BOMIssue[]; onSelect?: (id: string) => void; onChooseBoardStock?: (id: string) => void }) {
  return <section className="bom-issues"><h3>{title} <small>{issues.length}</small></h3>{issues.map((issue, index) => <article key={issue.part_id + index}>
    {onSelect ? <button type="button" className="subtle" onClick={() => onSelect(issue.part_id)}>{t(issue.part_name || issue.part_id)}</button> : <strong>{t(issue.part_name || issue.part_id)}</strong>}
    <small>{issue.context_path?.map(item => t(item.name)).join(' › ')}</small>
    {issue.suggested_board && <small>{t('Modeled L × W × T', '模型长 × 宽 × 厚')} · {modeledSize(issue.suggested_board)} mm · {modeledAxes(issue.suggested_board)}</small>}
    <ul>{(issue.reasons?.length ? issue.reasons : [issue.reason]).map((reason, ordinal) => <li key={ordinal}>{t(reason)}</li>)}</ul>
    {onChooseBoardStock && issue.reason_codes.includes('finish_not_stock') && <button type="button" className="subtle" onClick={() => onChooseBoardStock(issue.part_id)}>{t('Choose board stock', '选择板材原板')}</button>}
  </article>)}</section>;
}

function PanelTableHead({ review = false }: { review?: boolean }) {
  return <thead><tr><th>{t('Panel', '板件')}</th><th>{t('Material', '材料')}</th>
    <th>{review ? t('Modeled L × W × T', '模型长 × 宽 × 厚') : t('成品 L × W × T')}</th><th>{t('开料 L × W')}</th>
    <th>{t('数量 Qty')}</th><th>{t('纹理 / 封边 Grain / edges')}</th><th>{review ? t('Area / review status', '面积 / 审阅状态') : t('面积 / 说明 Area / notes')}</th></tr></thead>;
}

function PanelReviewTable({ rows, revision, onSelect, onChooseBoardStock }: {
  rows: BOMReviewRow[]; revision: number; onSelect: (id: string) => void; onChooseBoardStock?: (id: string) => void;
}) {
  return <div className="bom-table-scroll"><table className="bom-table">
    <caption>{t('Planning review', '规划审阅')} · R{revision} · mm</caption><PanelTableHead review />
    <tbody>{rows.map(row => <tr key={row.row_id}>
      <td><button type="button" className="subtle" onClick={() => onSelect(row.part_ids[0])}>{t(row.part_names[0] || row.part_ids[0])}</button><small>{contextText(row)}</small></td>
      <td>{row.material_code && <strong>{row.material_code}</strong>}{row.material_name && <span>{materialDisplayText(row.material_name, row.material_code)}</span>}
        {row.material_category === 'finish' && <small>{t('Finish only', '仅饰面')}</small>}
        {row.material_version == null && <small>{t('Board stock pending', '原板待指定')}</small>}
        {onChooseBoardStock && row.review_reason_codes.includes('finish_not_stock') && <button type="button" className="subtle" onClick={() => onChooseBoardStock(row.part_ids[0])}>{t('Choose board stock', '选择板材原板')}</button>}</td>
      <td>{modeledSize(row)}<small>{modeledAxes(row)}</small></td>
      <td>{t('Pending', '待定')}</td>
      <td>{row.quantity}</td>
      <td>{row.grain == null ? t('Pending', '待定') : row.grain === 'length' ? t('沿长 Length') : row.grain === 'width' ? t('沿宽 Width') : t('无指定 None')}
        {!!row.edges.length && <small>L / R / T / B<br />{row.edges.join(' / ')}</small>}</td>
      <td>{number(row.area_m2)} m²<small>{row.spec_status === 'suggested' ? t('Axes suggested', '已建议尺寸轴') : t('Axes saved', '已保存尺寸轴')}</small>
        {row.review_reasons.map(reason => <small key={reason}>{t(reason)}</small>)}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function BOMSheet({ projectId, revision, pending, onClose, onSelect, onDownload, embedded = false, readOnlyDrafts = false, onBackTo3D, onSuggestMaterials, onChooseBoardStock, onPreviewPanelSpecs, panelPreviewDisabled, previewedPanels, nextAction }: {
  projectId: string; revision: number; pending: boolean; embedded?: boolean; onClose: () => void; onSelect: (id: string) => void;
  readOnlyDrafts?: boolean; onBackTo3D?: () => void; onSuggestMaterials?: (scopeId?: string) => void;
  onChooseBoardStock?: (id: string) => void;
  onPreviewPanelSpecs?: (report: BOMReport) => void; panelPreviewDisabled?: boolean; previewedPanels?: PanelSpecPreviewRow[];
  nextAction?: ProductionAction;
  onDownload: (blob: Blob, filename: string) => void;
}) {
  const [report, setReport] = useState<BOMReport | null>(null); const [error, setError] = useState('');
  const [wholeReport, setWholeReport] = useState<BOMReport | null>(null);
  const [selectedScope, setSelectedScope] = useState('');
  const [builtScopes, setBuiltScopes] = useState<ReadonlySet<string>>(new Set());
  const [loading, setLoading] = useState(!pending); const [busy, setBusy] = useState(false); const mutex = useRef(false);
  const [search, setSearch] = useState(''); const [page, setPage] = useState(0); const [parts, setParts] = useState<Record<string, string>>({});
  const heading = useRef<HTMLHeadingElement>(null);
  const loadSequence = useRef(0);
  const showDesignGuide = readOnlyDrafts && !!nextAction;
  async function load(scopeId?: string) {
    if (pending || showDesignGuide) return;
    const sequence = ++loadSequence.current;
    setLoading(true); setError(''); setReport(null); setPage(0); setParts({});
    try {
      const next = await (scopeId ? studioAPI.bom(projectId, scopeId) : studioAPI.bom(projectId));
      if (sequence !== loadSequence.current) return;
      if ((next.scope_id || '') !== (scopeId || '')) {
        throw new Error(t('The cutting list scope changed. Rebuild the selected group.', '开料清单范围已变化，请重建所选分组。'));
      }
      setReport(next);
      if (next.project_id === projectId && next.revision === revision) {
        if (scopeId) setBuiltScopes(previous => new Set(previous).add(scopeId));
        else setWholeReport(next);
      }
    } catch (reason) {
      if (sequence === loadSequence.current) setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }
  useEffect(() => {
    setWholeReport(null); setSelectedScope(''); setBuiltScopes(new Set()); setReport(null);
    void load();
    return () => { loadSequence.current += 1; };
  }, [projectId, revision, pending, showDesignGuide]);
  useEffect(() => { if (embedded) heading.current?.focus(); }, [embedded]);
  const current = report?.project_id === projectId && report.revision === revision;
  async function download(review = false) {
    if (mutex.current || !report || !current || pending || loading || (review ? !report.review_rows?.length : report.status !== 'ready')) return;
    mutex.current = true; setBusy(true); setError('');
    try {
      const args = [projectId, report.revision, report.bom_sha256] as const;
      const exportReport = review ? studioAPI.exportReviewBOM : studioAPI.exportBOM;
      const result = await (report.scope_id ? exportReport(...args, report.scope_id) : exportReport(...args));
      onDownload(result.blob, result.filename);
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { mutex.current = false; setBusy(false); }
  }
  function select(id: string) { onSelect(id); onClose(); }
  const reviewRows = report?.review_rows || [];
  const panelCount = [...(report?.rows || []), ...reviewRows].reduce((sum, row) => sum + row.quantity, 0);
  const query = search.trim().toLowerCase();
  const matches = (row: BOMRow | BOMReviewRow) => `${row.part_names.join(' ')} ${row.part_ids.join(' ')} ${row.material_code} ${materialDisplayText(row.material_name, row.material_code)} ${materialDisplayText(row.color_name, row.material_code)} ${contextText(row)}`.toLowerCase().includes(query);
  const filtered = (report?.rows || []).filter(matches);
  const filteredReview = reviewRows.filter(matches);
  const reviewPartIds = new Set(reviewRows.flatMap(row => row.part_ids));
  const remainingIssues = report?.blocked.filter(issue => !reviewPartIds.has(issue.part_id)) || [];
  const pageCount = Math.max(1, Math.ceil(filtered.length / 50)); const shownPage = Math.min(page, pageCount - 1);
  const scopeOptions = new Map<string, string>();
  if (wholeReport && !readOnlyDrafts) {
    const panelContexts = wholeReport.rows.flatMap(row => row.contexts.map(item => item.context_path));
    for (const path of [...panelContexts, ...wholeReport.blocked.map(issue => issue.context_path)]) {
      const group = path[1]; // The first context is the saved model root.
      if (group) scopeOptions.set(group.id, group.name);
    }
  }
  const buildDisabled = pending || loading || busy;
  const canSuggestMaterials = !!onSuggestMaterials && current && !readOnlyDrafts
    && report.blocked.some(issue => issue.reason_codes.includes('missing_material'));
  const canPreviewPanelSpecs = !!onPreviewPanelSpecs && current && !readOnlyDrafts
    && report.blocked.some(issue => issue.reason_codes.includes('missing_board_spec') && issue.suggested_board);
  const stockAction = current && !buildDisabled && !readOnlyDrafts ? onChooseBoardStock : undefined;
  const content = <>
    <div className="sheet-body bom-heading">
      <div>{embedded && <h2 ref={heading} tabIndex={-1}>{t("Excel cutting list", "Excel开料清单")}</h2>}<strong>{t("已保存版本 Saved R")}{revision} · mm
        {report?.scope_name && <> · {t(report.scope_name)}</>}</strong>{!embedded && <p>{t("实体板件与指定材料 / Physical panels and assigned materials")}</p>}</div>
      <div className="sheet-actions">
        {onBackTo3D && !showDesignGuide && <button type="button" className="secondary" onClick={onBackTo3D}>{t('Back to Step 3', '返回第3步')}</button>}
        {!embedded && <button type="button" className="secondary" disabled={buildDisabled} onClick={() => void load()}>{t("刷新 Refresh")}</button>}
        {!showDesignGuide && !!reviewRows.length && <button type="button" className="secondary" disabled={buildDisabled || !current} onClick={() => void download(true)}>{t('Download review Excel', '下载审阅版 Excel')}</button>}
        {!showDesignGuide && <button type="button" className="primary" disabled={pending || loading || busy || !current || report?.status !== 'ready'} onClick={() => void download()}>{embedded ? t("Download Excel", "下载Excel") : t("导出 Excel Export")}</button>}
      </div>
    </div>
    {embedded && !showDesignGuide && <details className="sheet-body bom-build-row bom-build-options">
      <summary>{t('Cutting list options', '开料清单选项')}</summary>
      <WorkflowBuildActions all={{
        label: scopeOptions.size
          ? t('Rebuild all groups', '重建所有分组')
          : wholeReport ? t('Rebuild cutting list', '重建开料清单') : t('Build cutting list', '构建开料清单'),
        onClick: () => void load(), disabled: buildDisabled, secondary: true,
      }} scope={scopeOptions.size > 0 && <label className="bom-build-scope">
        {t('Cutting list group', '开料清单分组')}
        <select value={selectedScope} onChange={event => setSelectedScope(event.target.value)} disabled={buildDisabled}>
          <option value="">{t('Choose a group', '选择分组')}</option>
          {Array.from(scopeOptions).sort(([, left], [, right]) => t(left).localeCompare(t(right))).map(([id, name]) => <option key={id} value={id}>{t(name)}</option>)}
        </select>
      </label>} selected={scopeOptions.size ? {
        label: builtScopes.has(selectedScope) ? t('Rebuild selected group', '重建所选分组') : t('Build selected group', '构建所选分组'),
        onClick: () => void load(selectedScope), disabled: buildDisabled || !scopeOptions.has(selectedScope), secondary: true,
      } : undefined} />
    </details>}
    {error && <p className="sheet-error" role="alert">{t(error)}</p>}
    {showDesignGuide && nextAction ? <ProductionGuide action={nextAction} />
      : pending ? <div className={`sheet-body${previewedPanels ? ' cutting-list-results' : ''}`}>{previewedPanels ? <>
          <strong role="status">{t('Panel specifications previewed', '板件规格已预览')}</strong>
          <p>{t('Review the modeled dimensions and axes. Apply to save these specifications, or discard the preview. Board stock is chosen separately.', '请审阅模型尺寸和尺寸轴。应用以保存这些规格，或放弃预览。原板需另行选择。')}</p>
          {previewedPanels.length > 0 && <ul className="bom-panel-preview">{previewedPanels.map(panel => <li key={panel.part_id}>
            <strong>{t(panel.part_name)}</strong> · {modeledSize(panel)} mm · {modeledAxes(panel)}
          </li>)}</ul>}
        </> : <p role="status">{t("当前有未应用预览。先应用或放弃，再更新已保存版本的开料清单。 Apply or discard the current preview before updating the saved cutting list.")}</p>}</div>
      : loading ? <p className="sheet-body" role="status">{t("正在读取板件清单… Loading panels…")}</p> : report && <>
        {!current && <p className="sheet-error" role="alert">{t("清单版本已变化，请刷新后导出。 The list revision changed. Refresh before exporting.")}</p>}
        {(report.rows.length > 0 || reviewRows.length > 0) && <div className="sheet-body bom-filter"><label className="input-label">{t("查找板件 Find a panel")}<input data-autofocus value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} placeholder={t("板件、材料、颜色 / Panel, material, color")} /></label><span>{filtered.length + filteredReview.length} {filtered.length + filteredReview.length === 1 ? t("row", "项明细") : t("rows", "项明细")} · {panelCount} {panelCount === 1 ? t("panel", "块板件") : t("panels", "块板件")}</span></div>}
        <div className={embedded ? "cutting-list-results" : undefined}>
        {report.status === 'blocked' ? <div className="sheet-body bom-readiness">
            {reviewRows.length > 0 ? <>
              <strong>{t('Panel review is available', '板件审阅清单已就绪')}</strong>
              <p>{t('You can download the review workbook now. The production cutting list requires complete panel specifications and compatible stock.', '现在可以下载审阅工作簿。正式开料清单需要完整的板件规格和匹配的板材。')}</p>
            </> : <>
              {!report.rows.length && <strong>{t('No panels are ready for Excel yet', '暂无可导出到 Excel 的板件')}</strong>}
              <p>{t('Complete the panel details listed below before downloading Excel.', '请补充下方所列板件的信息，再下载Excel。')}</p>
            </>}
            {canPreviewPanelSpecs && <>
              <p>{t('Preview length, width and thickness axes from the modeled panels. Choose board stock separately.', '根据模型板件预览长、宽和厚度轴。原板需另行选择。')}</p>
              <button type="button" className="primary" disabled={buildDisabled || panelPreviewDisabled} onClick={() => onPreviewPanelSpecs?.(report)}>{t('Preview panel specifications', '预览板件规格')}</button>
            </>}
            {report.blocked.some(issue => issue.reason_codes.includes('missing_board_spec') && (!canPreviewPanelSpecs || !issue.suggested_board)) &&
              <p>{t('Select a panel below to inspect it. In Step 3, use Set board specification to define how it will be cut.', '选择下方的板件进行查看。在第 3 步中使用“设置开料规格”定义板件的开料方式。')}</p>}
            {report.blocked.some(issue => issue.reason_codes.includes('finish_not_stock')) && <p>{t('For a finish-only panel, choose compatible board stock in its row. The source finish remains recorded.', '只有饰面的板件，请在对应行选择兼容原板。原图饰面仍会保留。')}</p>}
            {canSuggestMaterials && <button type="button" className={canPreviewPanelSpecs ? 'secondary' : 'primary'} onClick={() => onSuggestMaterials?.(report.scope_id)}>{t('Suggest materials', '建议材料')}</button>}
          </div>
          : !report.rows.length && nextAction ? <ProductionGuide action={nextAction} />
          : !report.rows.length && <div className="sheet-body bom-readiness" role="status">
            <strong>{t('No saved boards to cut', '暂无已保存的开料板件')}</strong>
            <small>{t('0 panels · 0 rows', '0块板件 · 0项明细')}</small>
            <p>{readOnlyDrafts
              ? t('This project has read-only 3D review drafts. For Excel, save an editable 3D design with cabinet panels, then assign board materials.', '此项目目前只有只读三维审阅草稿。生成Excel前，请保存包含柜体板件的可编辑三维设计，再为板件指定材料。')
              : t('In Step 3, select a cabinet and use Cabinet interior in Properties to add panels. Specify their dimensions and materials, then save the design.', '在第3步中选择柜体，然后在属性的“柜内设计”中添加板件。指定尺寸和材料后保存设计。')}</p>
          </div>}
        {report.rows.length > 0 && <div className="bom-table-scroll"><table className="bom-table"><caption>R{report.revision} {t("· 成品及开料尺寸 Finished and cutting sizes · mm")}</caption><PanelTableHead /><tbody>{filtered.slice(shownPage * 50, shownPage * 50 + 50).map(row => <tr key={row.row_id}>
          <td><strong>{t(row.part_names[0] || row.part_ids[0])}</strong><small>{contextText(row)}</small>{row.part_ids.length > 1 && <select aria-label={t(`Panel instance ${row.row_id} / 具体板件`)} value={parts[row.row_id] || row.part_ids[0]} onChange={event => setParts(previous => ({ ...previous, [row.row_id]: event.target.value }))}>{row.part_ids.map((id, index) => <option key={id} value={id}>{t(row.part_names[index] || id)}</option>)}</select>}<button type="button" className="subtle" onClick={() => select(parts[row.row_id] || row.part_ids[0])}>{t("查看三维 View in 3D")}</button></td>
          <td><span className="material-swatch small" style={{ backgroundColor: row.color_hex }} aria-hidden="true" /><strong>{row.material_code}</strong><span>{materialDisplayText(row.material_name, row.material_code)}</span><small>{materialDisplayText(row.color_name, row.material_code)}<br />{[row.substrate, row.finish].filter(Boolean).join(' · ')}</small></td>
          <td>{[row.length_mm, row.width_mm, row.thickness_mm].map(number).join(' × ')}</td><td>{number(row.cut_length_mm)} × {number(row.cut_width_mm)}</td><td>{row.quantity}</td>
          <td>{row.grain === 'length' ? t('沿长 Length') : row.grain === 'width' ? t('沿宽 Width') : t('无指定 None')}<small>L / R / T / B<br />{row.edges.join(' / ')}</small></td><td>{number(row.area_m2)} m²<small>{row.machining_notes || '—'}</small></td>
        </tr>)}</tbody></table></div>}
        {pageCount > 1 && <div className="sheet-body bom-pagination"><button className="secondary" disabled={shownPage === 0} onClick={() => setPage(shownPage - 1)}>{t("上一页 Previous")}</button><span>{shownPage + 1} / {pageCount}</span><button className="secondary" disabled={shownPage + 1 >= pageCount} onClick={() => setPage(shownPage + 1)}>{t("下一页 Next")}</button></div>}
        {reviewRows.length > 0 && <PanelReviewTable rows={filteredReview} revision={report.revision} onSelect={select} onChooseBoardStock={stockAction} />}
        {remainingIssues.length > 0 && <div className="sheet-body"><IssueList title={t("待补充的板件 Panel details needed")} issues={remainingIssues} onSelect={select} onChooseBoardStock={stockAction} /></div>}
        {report.excluded.length > 0 && <details className="sheet-body bom-excluded"><summary>{t("不属于开料板件的构件 Excluded objects (")}{report.excluded.length})</summary><IssueList title={t("排除原因 Reasons")} issues={report.excluded} /></details>}
        {report.rows.length > 0 && <p className="sheet-body hint">{t("Excel 包含板件规格。排版与机型专用刀路需另行准备。 Excel contains panel specifications. Nesting and machine-specific toolpaths are separate.")}</p>}
        </div>
      </>}
  </>;
  return embedded ? <section className="studio-sheet cutting-list-page" aria-label={t("Excel cutting list", "Excel开料清单")}>{content}</section> : <StudioSheet title={t("开料清单 Excel cutting list")} titleId="bom-sheet-title" onClose={onClose} locked={busy} wide>{content}</StudioSheet>;
}
