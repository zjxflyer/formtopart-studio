import { selectedDimensions } from './dimensions';
import type { SpatialScene, Vec, ViewOptions } from './types';

/** Fit visible local measurement witnesses without adding any geometry. */
export function localDimensionFitAnchors(scene: SpatialScene, view: string, options: ViewOptions, geometryView = view): Vec[] {
  if (!scene.active_local_frame) return [];
  return selectedDimensions(scene, view, options, geometryView)
    .flatMap(dimension => [dimension.a, dimension.b, dimension.structural_a, dimension.structural_b]);
}
