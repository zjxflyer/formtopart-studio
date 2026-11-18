import { t } from './i18n';
import type { DrawingAsset, StudioScene } from './types';

/** Source drawings have their own local view; a missing world mesh cannot hide them. */
export function sourceDrawing(scene: StudioScene | null | undefined, view: string, ownerIds: string[] = []): DrawingAsset | undefined {
  if (!scene || scene.drawing_quality?.model_preview) return undefined;
  const drawings = scene.drawings || {};
  if (drawings[view]) return drawings[view];
  if (view === 'PLAN') {
    const plans = Object.values(drawings).filter(item => item.kind === 'plan'
      || scene.views[item.id]?.direction?.[2] === -1);
    for (const owner of ownerIds) {
      const matching = plans.filter(item => item.owner_ids?.includes(owner));
      if (matching.length) return matching.find(item => item.status !== 'stale' && item.geometry_count > 0) || matching[0];
    }
    return plans.find(item => item.status !== 'stale' && item.geometry_count > 0) || plans[0];
  }
  return undefined;
}

export function preferredDrawingView(scene: StudioScene | null | undefined): string {
  if (!scene) return 'source';
  if (scene.drawing_quality?.model_preview) return scene.meshes.length || Object.values(scene.local_frames || {}).some(frame => frame.meshes.length) ? 'PLAN' : 'source';
  const items = Object.values(scene.drawings || {});
  const usable = items.filter(item => item.status !== 'stale' && item.geometry_count > 0);
  return usable.find(item => item.kind === 'plan' || scene.views[item.id]?.direction?.[2] === -1)?.id
    || usable[0]?.id || items[0]?.id || (scene.meshes.length ? 'PLAN' : 'source');
}

export function drawingApplyBlocked(scene: StudioScene | null | undefined): boolean {
  const quality = scene?.drawing_quality;
  if (quality?.model_preview) return quality.can_apply !== true || !(scene?.meshes.length || Object.values(scene?.local_frames || {}).some(frame => frame.meshes.length));
  if (quality && quality.status !== 'ready') return true;
  return Object.values(scene?.drawings || {}).some(item => item.status !== 'ready'
    || item.geometry_count < 1 || !drawingGeometryCount(item.svg));
}

export function drawingStatusText(status: string | undefined): string {
  if (status === 'ready') return t('图纸检查通过 · Drawing checks passed');
  if (status === 'stale') return t('图纸需要更新 · Drawing needs updating');
  if (status === 'needs_review') return t('等待图纸审查 · Drawing review pending');
  return t('图纸尚未完整 · Drawing incomplete');
}

/** A page background and captions are not a drawing. Count actual geometric marks. */
export function drawingGeometryCount(svg: string): number {
  if (!svg) return 0;
  const document = new DOMParser().parseFromString(svg, 'image/svg+xml');
  if (document.querySelector('parsererror')) return 0;
  function paintProperty(element: Element, name: string, fallback: string): string {
    for (let node: Element | null = element; node; node = node.parentElement) {
      const inline = (node as HTMLElement).style?.getPropertyValue(name);
      const value = inline || node.getAttribute(name);
      if (value && value !== 'inherit') return value.trim().toLowerCase();
    }
    return fallback;
  }
  function ink(element: Element): boolean {
    for (let node: Element | null = element; node; node = node.parentElement) {
      const style = (node as HTMLElement).style;
      const opacity = style?.getPropertyValue('opacity') || node.getAttribute('opacity');
      if ((opacity && Number(opacity) === 0) || style?.display === 'none') return false;
    }
    const colored = (value: string) => !['none', 'transparent', 'white', '#fff', '#ffffff', 'rgb(255,255,255)', 'rgba(255,255,255,1)'].includes(value.replaceAll(/\s/g, ''));
    const color = paintProperty(element, 'color', 'black');
    const stroke = paintProperty(element, 'stroke', 'none').replace('currentcolor', color);
    const fill = paintProperty(element, 'fill', 'black').replace('currentcolor', color);
    return (colored(stroke) && Number(paintProperty(element, 'stroke-opacity', '1')) !== 0 && parseFloat(paintProperty(element, 'stroke-width', '1')) > 0)
      || (colored(fill) && Number(paintProperty(element, 'fill-opacity', '1')) !== 0);
  }
  return Array.from(document.querySelectorAll('path,polygon,polyline,line,rect,circle,ellipse')).filter(element => {
    const role = element.closest('[data-role]')?.getAttribute('data-role');
    if (role && !['geometry', 'context'].includes(role)) return false;
    if (role !== 'geometry' && !element.closest('[data-object-id],[data-owner-id]')) return false;
    if (!ink(element)) return false;
    const number = (name: string) => Number(element.getAttribute(name));
    if (element.localName === 'path') return /[lchvqsatz]/i.test(element.getAttribute('d') || '');
    if (element.localName === 'line') return number('x1') !== number('x2') || number('y1') !== number('y2');
    if (element.localName === 'rect') return number('width') > 0 && number('height') > 0;
    if (element.localName === 'circle') return number('r') > 0;
    if (element.localName === 'ellipse') return number('rx') > 0 && number('ry') > 0;
    return (element.getAttribute('points') || '').trim().split(/[\s,]+/).length >= 4;
  }).length;
}

export function drawingNotice(scene: StudioScene): string {
  if (scene.drawing_quality?.model_preview) return drawingApplyBlocked(scene) ? t("No drawable model geometry is available. Review the source and missing information before applying.", "尚无可绘制模型，请先检查原图与缺失信息。") : t("Model preview ready. Review dimensions and source warnings before Apply or Discard.", "模型预览已就绪，请审阅尺寸及原图提示后应用或放弃。 ");
  return drawingApplyBlocked(scene)
    ? t('Drawing review found incomplete or outdated views. Inspect the listed issues; Apply is unavailable. / 图纸检查发现不完整或过期视图，请查看问题；暂不能应用。')
    : t('Drawing preview available. Review the source views, then Apply or Discard. / 图纸预览已生成，请核对原图视图后应用或放弃。');
}
