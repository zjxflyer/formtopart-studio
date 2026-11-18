import { t } from './i18n';
import type { StudioScene, StudioView } from './types';

export type DrawingResultItem = {
  id: string;
  label: string;
  status?: string;
  kind: 'drawing' | 'projection' | 'reviewed';
  page?: number;
  group?: { id: string; label: string };
};

const PROJECTION_IDS = ['PLAN', 'ORTHO-FRONT', 'ORTHO-RIGHT', 'ORTHO-BACK', 'ORTHO-LEFT'];

/** Real drawing IDs are selectable results; source poses alone are not output. */
export function drawingResultItems(scene: StudioScene | null | undefined, views: StudioView[] = []): DrawingResultItem[] {
  if (!scene) return [];
  const drawings = scene.drawings || {};
  if (!scene.drawing_quality?.model_preview && Object.keys(drawings).length) {
    const ordered = [...new Set([...views.map(view => view.id).filter(id => Object.hasOwn(drawings, id)), ...Object.keys(drawings)])];
    return ordered.map((id, index) => {
      const asset = drawings[id];
      const source = views.find(view => view.id === id);
      return {
        id,
        label: asset.label?.trim() ? asset.label : source?.label?.trim() ? source.label : t(`Drawing ${index + 1}`, `图纸${index + 1}`),
        status: Number.isFinite(asset.geometry_count) && asset.geometry_count > 0 ? asset.status : 'incomplete',
        kind: 'drawing',
        page: asset.page ?? source?.page,
      };
    });
  }
  // The current 2D exporter renders world meshes, not isolated local frames.
  const geometryAvailable = !!scene.meshes?.length;
  return geometryAvailable ? PROJECTION_IDS.map((id, index) => ({
    id, label: t(`Model projection ${index + 1}`, `模型投影${index + 1}`), kind: 'projection',
  })) : [];
}
