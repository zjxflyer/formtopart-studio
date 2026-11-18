import type { StudioLocalFrame, StudioScene } from './types';

/** Isolated assembly coordinates never enter the saved world scene. */
export function sceneFor3D(scene: StudioScene | null, frameId: string): StudioScene | null {
  const frame = scene?.local_frames?.[frameId];
  if (!scene || !frame) return scene;
  return { ...scene, objects: frame.objects, meshes: frame.meshes, dimensions: frame.dimensions,
    symbols: frame.symbols, bounds: frame.bounds, geometry_hash: `${scene.geometry_hash}:local:${frame.root_id}`,
    active_local_frame: { root_id: frame.root_id, label: frame.label, global_placement_known: false } };
}

export function frameForObject(scene: StudioScene | null, ownerId: string): StudioLocalFrame | undefined {
  const frames = Object.values(scene?.local_frames || {});
  return frames.find(frame => frame.root_id === ownerId)
    || frames.filter(frame => frame.objects.some(object => object.id === ownerId))
      .sort((a, b) => (b.ancestors?.length || 0) - (a.ancestors?.length || 0))[0];
}
