import type { SpatialScene } from './types';
import { resolveCameraPreset } from './viewPresets';

/** Internal representation state, never serialized into the physical project. */
export type ViewContext = { geometryView:string; annotationView:string; fitOnSelect:boolean };
export function viewContext(scene:SpatialScene,id:string,representation:'model'|'checking'='model'):ViewContext{
  const preset=resolveCameraPreset(scene,id);
  return {
    geometryView:representation==='model'?'AXON':preset?.visibilityView||id,
    annotationView:preset?.annotationView||id,
    fitOnSelect:!preset&&id in scene.views,
  };
}
