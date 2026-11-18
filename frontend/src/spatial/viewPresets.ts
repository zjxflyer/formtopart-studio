import type { SpatialScene, Vec } from './types';

export type DirectionPresetKind = 'elevation' | 'plan' | 'bottom';
export type CameraPreset = {
  id: string;
  label: string;
  kind: DirectionPresetKind;
  cameraPositionDirection: Vec;
  up: Vec;
  right: Vec;
  /** View used for checking-draft projection and source annotation eligibility. */
  baseView: string;
  /** View used for 3D geometry visibility. Direction cameras retain the full model. */
  visibilityView: string;
  /** View used for annotations. Bottom views intentionally use their virtual id. */
  annotationView: string;
  draftView?: string;
};
export type CameraPresetGroup = { id: string; label: string; items: CameraPreset[] };

const PAGE_DIRECTIONS: { id: string; label: string; up: Vec; right: Vec }[] = [
  {id: 'UP', label: '↑ Page-up / 页面上', up: [0, 1, 0], right: [1, 0, 0]},
  {id: 'RIGHT', label: '→ Page-right / 页面右', up: [1, 0, 0], right: [0, -1, 0]},
  {id: 'DOWN', label: '↓ Page-down / 页面下', up: [0, -1, 0], right: [-1, 0, 0]},
  {id: 'LEFT', label: '← Page-left / 页面左', up: [-1, 0, 0], right: [0, 1, 0]},
];

function orthographicFaces(): CameraPreset[] {
  return [
    {id:'ORTHO-FRONT',label:'Front / 前',direction:[0,-1,0],right:[1,0,0]},
    {id:'ORTHO-RIGHT',label:'Right / 右',direction:[1,0,0],right:[0,1,0]},
    {id:'ORTHO-BACK',label:'Back / 后',direction:[0,1,0],right:[-1,0,0]},
    {id:'ORTHO-LEFT',label:'Left / 左',direction:[-1,0,0],right:[0,-1,0]},
  ].map(face => ({
      id:face.id,
      label:face.label,
      kind: 'elevation',
      cameraPositionDirection: face.direction as Vec,
      up: [0,0,1] as Vec,
      right: face.right as Vec,
      baseView: face.id,
      visibilityView: 'AXON',
      annotationView: 'AXON',
    }));
}

export function directionPresetGroups(scene: SpatialScene): CameraPresetGroup[] {
  const elevations = orthographicFaces();
  const plans = PAGE_DIRECTIONS.map(d => ({
    id: `PLAN-${d.id}`,
    label: d.label,
    kind: 'plan' as const,
    cameraPositionDirection: [0, 0, 1] as Vec,
    up: d.up,
    right: d.right,
    baseView: 'PLAN',
    visibilityView: 'AXON',
    annotationView: 'PLAN',
  }));
  const bottoms = PAGE_DIRECTIONS.map(d => ({
    id: `BOTTOM-${d.id}`,
    label: d.label,
    kind: 'bottom' as const,
    cameraPositionDirection: [0, 0, -1] as Vec,
    up: d.up,
    // Looking upward reverses handedness; never mirror the projected underside.
    right: d.right.map(value=>-value) as Vec,
    baseView: 'PLAN',
    visibilityView: 'AXON',
    annotationView: `BOTTOM-${d.id}`,
  }));
  return [
    {id: 'elevations', label: 'Vertical faces / 四个正立面', items: elevations},
    {id: 'plans', label: 'Plan directions / 平面方向', items: plans},
    {id: 'bottoms', label: 'Bottom directions / 底面方向', items: bottoms},
  ];
}

export function directionPresetList(scene: SpatialScene): CameraPreset[] {
  return directionPresetGroups(scene).flatMap(group => group.items);
}

export function resolveCameraPreset(scene: SpatialScene, id: string, _includeSourceElevations=true): CameraPreset | null {
  return directionPresetList(scene).find(item => item.id === id) || null;
}

