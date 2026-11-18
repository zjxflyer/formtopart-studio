import { t } from './i18n';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { studioAPI } from './api';
import { childPanels, compatiblePanels, materialDisplayText, panelThickness } from './materials';
import { StudioSheet } from './StudioSheet';
import type { MaterialInput, MaterialVariant, StudioNode } from './types';

const emptyMaterial = (): MaterialInput => ({ code: '', name: '', color_hex: '#cbb998', color_name: '', category: 'sheet', substrate: '', finish: '', thickness_mm: null, stock_sizes: [], supplier: '', sku: '', stock_count: null, grain: 'none', active: true });
const message = (error: unknown) => error instanceof Error ? error.message : String(error);

export function MaterialEditor({ material, disabled, onCancel, onSave }: {
  material?: MaterialVariant; disabled: boolean; onCancel: () => void; onSave: (value: MaterialInput) => Promise<void>;
}) {
  const [value, setValue] = useState<MaterialInput>(() => {
    if (!material) return emptyMaterial();
    const { id, version, ...input } = material; void id; void version;
    return { ...input, stock_sizes: material.stock_sizes.map(size => ({ ...size })) };
  });
  const [error, setError] = useState('');
  function field<K extends keyof MaterialInput>(key: K, next: MaterialInput[K]) { setValue(previous => ({ ...previous, [key]: next })); }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (disabled) return;
    if (!value.code.trim() || !value.name.trim()) { setError(t('Enter a code and name. / 请填写材料编号及名称。')); return; }
    if (value.stock_sizes.some(size => !Number.isFinite(size.length_mm) || !Number.isFinite(size.width_mm) || size.length_mm <= 0 || size.width_mm <= 0)) { setError(t('Enter both positive stock-sheet dimensions. / 请填写原板的正数长宽。')); return; }
    setError(''); await onSave({ ...value, code: value.code.trim(), name: value.name.trim() });
  }
  return <form className="material-editor sheet-body" onSubmit={event => void submit(event)}>
    <div className="sheet-subheading"><h3>{material ? t('编辑材料 Edit material') : t('新增材料 Add material')}</h3>{material && <span>{material.code} · v{material.version}</span>}</div>
    <fieldset disabled={disabled}><div className="material-form-grid">
      <label>{t("编号 Code")}<input autoFocus data-autofocus required maxLength={80} value={value.code} onChange={event => field('code', event.target.value)} /></label>
      <label>{t("名称 Name")}<input required maxLength={200} value={materialDisplayText(value.name, value.code)} onChange={event => field('name', event.target.value)} /></label>
      <label>{t("颜色 Color")}<input type="color" value={value.color_hex} onChange={event => field('color_hex', event.target.value)} /></label>
      <label>{t("颜色名称 Color name")}<input value={materialDisplayText(value.color_name, value.code)} onChange={event => field('color_name', event.target.value)} /></label>
      <label>{t("类别 Category")}<select aria-label={t("类别 Category")} value={value.category} onChange={event => field('category', event.target.value as MaterialInput['category'])}><option value="sheet">{t("板材 Sheet")}</option><option value="stone">{t("石材 Stone")}</option><option value="metal">{t("金属 Metal")}</option><option value="glass">{t("玻璃 Glass")}</option><option value="finish">{t("饰面 Finish")}</option><option value="other">{t("其他 Other")}</option></select></label>
      <label>{t("厚度 Thickness (mm)")}<input type="number" min="0.01" step="any" value={value.thickness_mm ?? ''} placeholder={t("未指定 Not specified")} onChange={event => field('thickness_mm', event.target.value === '' ? null : Number(event.target.value))} /></label>
      <label>{t("基材 Substrate")}<input value={value.substrate} onChange={event => field('substrate', event.target.value)} /></label>
      <label>{t("饰面 Finish")}<input value={value.finish} onChange={event => field('finish', event.target.value)} /></label>
      <label>{t("纹理 Grain")}<select aria-label={t("纹理 Grain")} value={value.grain} onChange={event => field('grain', event.target.value as MaterialInput['grain'])}><option value="none">{t("无指定 None")}</option><option value="length">{t("沿长度 Length")}</option><option value="width">{t("沿宽度 Width")}</option></select></label>
      <label>{t("库存数量 Stock count")}<input type="number" min="0" step="1" value={value.stock_count ?? ''} placeholder={t("未记录 Not recorded")} onChange={event => field('stock_count', event.target.value === '' ? null : Number(event.target.value))} /></label>
      <label>{t("供应商 Supplier")}<input value={value.supplier} onChange={event => field('supplier', event.target.value)} /></label>
      <label>{t("产品编号 SKU")}<input value={value.sku} onChange={event => field('sku', event.target.value)} /></label>
    </div>
    <section className="stock-sizes"><div className="sheet-subheading"><h3>{t("原板规格 Stock sheets · mm")}</h3><button type="button" className="subtle" onClick={() => field('stock_sizes', [...value.stock_sizes, { length_mm: 0, width_mm: 0 }])}>{t("添加规格 Add size")}</button></div>
      {value.stock_sizes.map((size, index) => <div className="stock-size-row" key={index}><label>{t("长 Length")}<input aria-label={t(`Stock length ${index + 1} / 原板长`)} type="number" required min="0.01" step="any" value={size.length_mm || ''} onChange={event => field('stock_sizes', value.stock_sizes.map((item, ordinal) => ordinal === index ? { ...item, length_mm: Number(event.target.value) } : item))} /></label><span>×</span><label>{t("宽 Width")}<input aria-label={t(`Stock width ${index + 1} / 原板宽`)} type="number" required min="0.01" step="any" value={size.width_mm || ''} onChange={event => field('stock_sizes', value.stock_sizes.map((item, ordinal) => ordinal === index ? { ...item, width_mm: Number(event.target.value) } : item))} /></label><button type="button" className="subtle" onClick={() => field('stock_sizes', value.stock_sizes.filter((_, ordinal) => ordinal !== index))}>{t("移除 Remove")}</button></div>)}
    </section>
    <label className="sheet-checkbox"><input type="checkbox" checked={value.active} onChange={event => field('active', event.target.checked)} />{t("可供选择 Active in library")}</label>
    <p className="hint">{t("停用材料会从选材列表隐藏，已保存项目保留其材料快照。 Archiving hides it from new assignments; saved projects keep their pinned material.")}</p></fieldset>
    {error && <p className="field-error" role="alert">{t(error)}</p>}
    <div className="sheet-actions"><button type="button" className="secondary" disabled={disabled} onClick={onCancel}>{t("返回 Back")}</button><button type="submit" className="primary" disabled={disabled}>{t("保存材料 Save material")}</button></div>
  </form>;
}

export function MaterialLibrary({ node, assignEnabled, sizes = {}, onClose, onPreview, onClear, boardStockOnly = false }: {
  node?: StudioNode; assignEnabled: boolean; sizes?: Record<string, number[]>; onClose: () => void;
  onPreview: (material: MaterialVariant, partIds: string[]) => Promise<boolean>;
  onClear?: (partIds: string[]) => Promise<boolean>; boardStockOnly?: boolean;
}) {
  const [items, setItems] = useState<MaterialVariant[]>([]); const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const mutex = useRef(false);
  const [error, setError] = useState(''); const [editor, setEditor] = useState<MaterialVariant | 'new' | null>(null);
  const [archived, setArchived] = useState(false); const [partIds, setPartIds] = useState<string[]>(node ? [node.id] : []);
  const panels = node ? childPanels(node) : [];
  const assignedCount = (node ? [node, ...panels] : []).filter(part => partIds.includes(part.id) && part.material_assignment).length;
  async function reload() { setLoading(true); setError(''); try { setItems(await studioAPI.materials(true)); } catch (reason) { setError(message(reason)); } finally { setLoading(false); } }
  useEffect(() => { void reload(); }, []);
  async function operation(action: () => Promise<void>) {
    if (mutex.current) return; mutex.current = true; setBusy(true); setError('');
    try { await action(); } catch (reason) { setError(message(reason)); } finally { mutex.current = false; setBusy(false); }
  }
  async function save(value: MaterialInput) {
    await operation(async () => {
      const next = editor && editor !== 'new' ? await studioAPI.updateMaterial(editor.id, editor.version, value) : await studioAPI.createMaterial(value);
      setItems(previous => [...previous.filter(item => item.id !== next.id), next]); setEditor(null);
    });
  }
  const query = search.trim().toLowerCase();
  const stockThickness = node && boardStockOnly ? panelThickness(node, sizes) : null;
  const filtered = items.filter(item => (archived || item.active)
    && (!boardStockOnly || (item.category !== 'finish' && item.thickness_mm != null && stockThickness != null && Math.abs(item.thickness_mm - stockThickness) <= 1e-6))
    && `${item.code} ${item.name} ${item.color_name} ${item.substrate} ${item.supplier} ${item.sku}`.toLowerCase().includes(query));
  return <StudioSheet title={t("材料库 Material library")} titleId="material-library-title" onClose={onClose} locked={busy}>
    {error && <div className="sheet-error" role="alert">{t(error)}<button type="button" className="subtle" disabled={busy} onClick={() => { setEditor(null); void reload(); }}>{t("重新加载 Reload")}</button></div>}
    {editor ? <MaterialEditor key={editor === 'new' ? 'new' : editor.id + editor.version} material={editor === 'new' ? undefined : editor} disabled={busy} onCancel={() => setEditor(null)} onSave={save} /> : <>
      <div className="sheet-body material-library-controls"><div className="sheet-subheading"><p>{t("本机材料 · Local library")}</p><button type="button" className="secondary" disabled={busy || loading} onClick={() => setEditor('new')}>{t("新增材料 Add material")}</button></div>
        <label className="input-label">{t("搜索材料 Search materials")}<input data-autofocus value={search} onChange={event => setSearch(event.target.value)} placeholder={t("编号、名称、颜色、供应商 / Code, name, color, supplier")} /></label>
        <label className="sheet-checkbox"><input type="checkbox" checked={archived} onChange={event => setArchived(event.target.checked)} />{t("显示已停用材料 Show archived")}</label>
        {node && <div className="material-scope"><strong>{t(node.name)}</strong><small>{t("原图饰面 Source finish:")}{node.material || t('未记录 Not recorded')}</small>
          {boardStockOnly && <p className="hint">{t('Choose stock with the panel’s thickness. Applying it replaces the assigned product and keeps the source finish recorded.', '请选择与板件厚度匹配的原板。应用后会替换指定产品，并保留原图饰面记录。')}</p>}
          <label className="sheet-checkbox"><input type="checkbox" disabled={!assignEnabled || busy} checked={partIds.includes(node.id)} onChange={event => setPartIds(previous => event.target.checked ? [...previous, node.id] : previous.filter(id => id !== node.id))} />{t("仅此构件 This part")}</label>
          {panels.length > 0 && <details><summary>{t("明确选择子板件 Choose child panels (")}{panels.length})</summary>{panels.map(panel => <label className="sheet-checkbox" key={panel.id}><input type="checkbox" aria-label={`${t(panel.name)} ${panel.material || ''}`} disabled={!assignEnabled || busy} checked={partIds.includes(panel.id)} onChange={event => setPartIds(previous => event.target.checked ? [...previous, panel.id] : previous.filter(id => id !== panel.id))} /><span>{t(panel.name)}{' '}<small>{panel.material || t('未记录 Not recorded')} · {panelThickness(panel, sizes) == null ? t('板厚待设置 Thickness not set') : `${panelThickness(panel, sizes)} mm`}</small></span></label>)}</details>}
          <p className="material-scope-count" aria-live="polite">{t("已选")}{partIds.length} {t("个构件 /")}{partIds.length} {t("selected · 子板件")}{panels.filter(panel => partIds.includes(panel.id)).length}/{panels.length}</p>
          {onClear && <button type="button" className="subtle" disabled={busy || !assignEnabled || !assignedCount} onClick={() => void operation(async () => { if (await onClear(partIds)) onClose(); else setError(t('Could not prepare the clear-assignment preview. / 未能生成清除材料分配的预览。')); })}>{t("清除已选材料 Clear selected assignments")}</button>}
          {assignedCount > 0 && <small>{t("仅清除指定产品，保留原图饰面。 / Clears the product assignment; source finish remains.")}</small>}
          {!assignEnabled && <p className="hint">{t("先应用或放弃当前预览，再分配材料。 Apply or discard the current preview before assigning material.")}</p>}
        </div>}
      </div>
      <div className="material-library-list" aria-busy={loading}>{loading ? <p role="status">{t("正在读取材料… Loading materials…")}</p> : !filtered.length ? <p>{t("没有匹配材料。可新增材料或调整搜索。 No matching material. Add one or adjust the search.")}</p> : filtered.map(item => {
        const compatible = node ? compatiblePanels(node, item.thickness_mm, sizes) : [];
        return <article className={`material-library-card ${item.active ? '' : 'archived'}`} key={item.id}>
        <span className="material-swatch" style={{ backgroundColor: item.color_hex }} aria-hidden="true" /><div className="material-card-copy"><strong>{item.code} · {materialDisplayText(item.name, item.code)}</strong><span>{materialDisplayText(item.color_name, item.code) || item.color_hex}{item.thickness_mm != null ? ` · ${item.thickness_mm} mm` : ''}</span><small>{[item.substrate, item.finish, item.supplier].filter(Boolean).join(' · ') || item.category}{!item.active ? t(' · 已停用 Archived') : ''}</small></div>
        <div className="material-card-actions"><button type="button" className="subtle" disabled={busy} aria-label={t(`Edit ${item.code} / 编辑材料`)} onClick={() => setEditor(item)}>{t("编辑 Edit")}</button>{compatible.length > 0 && <button type="button" className="subtle compatible-panels" disabled={busy || !assignEnabled || !item.active} aria-label={t(`Select ${item.thickness_mm} mm compatible panels / 选择匹配板厚`)} onClick={() => setPartIds(compatible.map(panel => panel.id))}>{t("选择")}{item.thickness_mm} {t("mm 板件 (")}{compatible.length})<br />Select compatible panels</button>}{node && <button type="button" className="secondary" disabled={busy || !assignEnabled || !item.active || !partIds.length} aria-label={t(`Use ${item.code} / 使用材料`)} onClick={() => void operation(async () => { if (await onPreview(item, partIds)) onClose(); else setError(t('Could not prepare the material preview. Your saved design is unchanged. / 未能生成材料预览，已保存设计保持不变。')); })}>{t("预览使用")}{partIds.length} {t("项 Use")}</button>}</div>
      </article>; })}</div>
    </>}
  </StudioSheet>;
}
