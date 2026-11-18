import { t } from './i18n';
import type { MaterialSnapshot, MaterialSuggestionReceipt, StudioNode } from './types';

/** Localize only the stock library's known bilingual labels; never translate user names. */
export function materialDisplayText(value: string, code: string): string {
  const thickness = /^SAMPLE-PLY-(6|16|18)$/.exec(code)?.[1];
  if (!thickness) return value;
  const knownName = `Sample plywood ${thickness} mm / 示例夹板 ${thickness} 毫米`;
  const compactName = `Sample plywood ${thickness} mm / 示例夹板${thickness}毫米`;
  return value === knownName || value === compactName || value === 'Sample natural / 示例原木色' ? t(value) : value;
}

export function assignedMaterial(node: StudioNode, snapshots: MaterialSnapshot[] = []) {
  return snapshots.find(item => item.snapshot_id === node.material_assignment)?.variant;
}

export function MaterialSuggestionResults({ receipt, nodes, snapshots = [] }: {
  receipt: MaterialSuggestionReceipt; nodes: StudioNode[]; snapshots?: MaterialSnapshot[];
}) {
  const name = (id: string) => t(nodes.find(node => node.id === id)?.name || id);
  const basis = {
    source_match: t('Source finish match', '原图饰面匹配'),
    provisional: t('Provisional appearance', '暂定外观'),
    requested: t('Requested preference', '用户偏好'),
  };
  return <details className="material-suggestion-results" open>
    <summary>{receipt.assignment_count} {receipt.assignment_count === 1
      ? t('material assignment proposed', '项材料分配建议') : t('material assignments proposed', '项材料分配建议')}</summary>
    {!!receipt.assignments.length && <ul>{receipt.assignments.map(item => {
      const product = snapshots.find(snapshot => snapshot.variant.id === item.material_id && snapshot.variant.version === item.material_version)?.variant;
      return <li key={item.part_id}>
        <strong>{name(item.part_id)}</strong> · {product ? `${product.code} · ${materialDisplayText(product.name, product.code)}` : item.material_id}
        {item.basis && <small>{basis[item.basis]}{item.assignment_mode && ` · ${item.assignment_mode === 'stock'
          ? t('Board stock', '板材库存') : t('Appearance only', '仅外观')}`}</small>}
        {item.reason && <small>{t(item.reason)}</small>}
        {item.source_evidence?.map((evidence, index) => <small key={index}>
          {evidence.document_name || evidence.document_id} · {t('Page', '页')} {evidence.page}{evidence.text && ` · ${evidence.text}`}
        </small>)}
      </li>;
    })}</ul>}
    {!!receipt.unresolved?.length && <details>
      <summary>{t('Unmatched parts', '未匹配构件')} ({receipt.unresolved.length})</summary>
      <ul>{receipt.unresolved.map(item => <li key={item.part_id}><strong>{name(item.part_id)}</strong> · {t(item.reason)}</li>)}</ul>
    </details>}
    {receipt.notes.map((note, index) => <p key={index}>{t(note)}</p>)}
  </details>;
}
const BOARD_KINDS = new Set(['panel', 'board', 'shelf', 'divider', 'back', 'side', 'top', 'bottom', 'drawer_board', 'drawer_panel', 'carcass_panel', 'back_panel', 'side_panel', 'top_panel', 'bottom_panel']);
export function isBoardPanel(node: StudioNode, context = false) {
  return node.physical === true && !context && !node.context && !node.surface && !node.children.length &&
    (!!node.board_spec || BOARD_KINDS.has(node.kind.toLowerCase().replace(/[- ]/g, '_')));
}
export function childPanels(node: StudioNode, context = false): StudioNode[] {
  const inherited = context || !!node.context;
  return node.children.flatMap(child => [...(isBoardPanel(child, inherited) ? [child] : []), ...childPanels(child, inherited)]);
}
export function panelThickness(node: StudioNode, sizes: Record<string, number[]>) {
  const axis = node.board_spec?.thickness_axis;
  if (!axis) return null;
  const value = sizes[node.id]?.[{ X: 0, Y: 1, Z: 2 }[axis]];
  return value != null && Number.isFinite(value) && value > 0 ? value : null;
}
export function compatiblePanels(node: StudioNode, thickness: number | null, sizes: Record<string, number[]>) {
  if (thickness == null) return [];
  return childPanels(node).filter(panel => { const value = panelThickness(panel, sizes); return value != null && Math.abs(value - thickness) <= 1e-6; });
}
export function contextForNode(root: StudioNode, id: string, context = false): boolean {
  const inherited = context || !!root.context;
  if (root.id === id) return inherited;
  return root.children.some(child => contextForNode(child, id, inherited));
}

export function MaterialProperties({ node, snapshots, disabled, context = false, libraryDisabled = false, onChoose, onManage, onBoard }: {
  node: StudioNode; snapshots?: MaterialSnapshot[]; disabled: boolean; context?: boolean; libraryDisabled?: boolean;
  onChoose: () => void; onManage: () => void; onBoard: () => void;
}) {
  const material = assignedMaterial(node, snapshots);
  return <div className="material-properties">
    <div className="material-source"><span>{t("原图饰面 Source finish")}</span><strong>{node.material || t('未记录 Not recorded')}</strong></div>
    <div className="material-assigned"><span className="material-swatch" style={{ backgroundColor: material?.color_hex || '#e7e8e1' }} aria-hidden="true" /><div><span>{t("指定材料 Assigned material")}</span><strong>{material ? `${material.code} · ${materialDisplayText(material.name, material.code)}` : t('尚未指定 Not assigned')}</strong>{material && <small>{materialDisplayText(material.color_name, material.code) || material.color_hex} · v{material.version}</small>}</div></div>
    <div className="material-property-actions"><button type="button" className="secondary" disabled={disabled} onClick={onChoose}>{t("选择材料 Choose material")}</button><button type="button" className="subtle" disabled={libraryDisabled} onClick={onManage}>{t("材料库 Library")}</button></div>
    {isBoardPanel(node, context) && <button type="button" className="subtle board-spec-trigger" disabled={disabled} onClick={onBoard}>{node.board_spec ? t('板件规格 Board specification') : t('设置开料规格 Set board specification')}</button>}
    {node.surface && <p className="hint">{t("原图表面不是实体开料板件。 A source face is not a physical cutting board.")}</p>}
  </div>;
}
