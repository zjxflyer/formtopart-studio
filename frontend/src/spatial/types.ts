export type Vec = [number, number, number];
export type Parameter = { value_mm?: number; expression?: string; status: string; method: string; evidence: string[]; uncertainty_mm?: number; unit?: string };
export type SpatialNode = { id: string; name: string; children: SpatialNode[]; editable: Record<string,string>; };
export type SpatialObject = { id: string; name: string; description: string; material: string; origin: Vec; size: number[]; rotation: number; ancestors: string[]; children: string[]; inferred: boolean; dependencies: string[]; evidence: string[]; context: boolean; editable: Record<string,string>; provenance?: Record<string,unknown>; authority?: string; confidence?: string; source_sheet?: string; source_page?: number; evidence_region?: string; inference_method?: string; conflict_ids?: string[]; affected_views?: string[]; source_role?: string; variant_detail?: string };
export type SpatialDimension = { id: string; owner: string; axis: string; value_mm: number; inferred: boolean; dependencies: string[]; a: Vec; b: Vec; structural_a: Vec; structural_b: Vec; kind?: 'relationship'; subjects?: string[]; views?: string[]; side?: string; evidence?: string[]; amended?: boolean; anchors?: Record<string,{owner:string}> };
export type SpatialMesh = { id: string; vertices: Vec[]; indices: number[]; edges: [number,number][]; material: string; context: boolean; ancestors: string[]; inferred: boolean; physical?:boolean; representation?:'solid'|'source_surface' };
export type SpatialScene = {
  project_key?: string; variant?: string; default_selection?: string;
  active_local_frame?: { root_id: string; label: string; global_placement_known: false };
  project: { schema: string; id: string; revision: number; name: string; status: string; source: Record<string,unknown>; root: SpatialNode; parameters: Record<string,Parameter>; materials: Record<string,string>; pending: string[]; viewer_defaults?: Partial<ViewOptions>; material_snapshots?: Array<{ snapshot_id: string; variant: { code: string; name: string; category: string; substrate: string; finish: string } }>; };
  objects: SpatialObject[]; meshes: SpatialMesh[]; dimensions: SpatialDimension[];
  symbols: { id: string; owner: string; points: Vec[]; kind: string; pattern: string; face_normal?:Vec; views?:string[]; display_2d_plan?:boolean; owner_face?:string }[];
  views: Record<string,{direction: Vec; right: Vec; up: Vec; detail: string; include?: string[]; exclude?: string[]; symbols?: string[]}>;
  bounds: { min: Vec; max: Vec }; resolved: Record<string,number>; geometry_hash: string;
};
export type ViewOptions = { appearance: 'outline'|'material'; selected: string; dimensions: 'off'|'selected'|'all'|'inferred'; componentSizes?: boolean; openingMarks: boolean; text: boolean; viewLabels: boolean; transparentWalls: boolean; hidden: string[]; isolate: string; unit: 'mm'|'in' };
export const defaultOptions: ViewOptions = { appearance: 'outline', selected: '', dimensions: 'selected', componentSizes: false, openingMarks: false, text: false, viewLabels: true, transparentWalls: true, hidden: [], isolate: '', unit: 'in' };
export function viewVisible(scene:SpatialScene, view:string, id:string){
  const rule=scene.views[view];if(!rule)return true;
  const match=(prefix:string)=>id===prefix||id.startsWith(prefix+'/');
  return !(rule.exclude||[]).some(match)&&(!rule.include||rule.include.some(match));
}
export const isWithin = (id: string, ancestors: string[], parent: string) => id === parent || ancestors.includes(parent);
export function valueText(mm: number, unit: 'in'|'mm') {
  if (unit === 'mm') return `${Math.round(mm*10)/10} mm`;
  const total = Math.round(mm / 25.4 * 16); const whole = Math.floor(total/16); let n = total%16, d=16;
  while (n && n%2===0) { n/=2; d/=2; }
  return `${whole}${n ? ` ${n}/${d}`:''}″`;
}

/** Strict UI parser. Feet/inches, decimals and fractions; never silently round the model. */
export function readValue(text: string, unit: 'in'|'mm'): number | null {
  const s = text.trim().replaceAll('′',"'").replaceAll('″','"');
  function inches(t: string): number | null {
    const v=t.trim().replace(/"$/, '').trim();
    if (/^[+-]?(\d+(\.\d+)?|\.\d+)$/.test(v)) return Number(v);
    const m=v.match(/^([+-]?)(?:(\d+)\s+)?(\d+)\/(\d+)$/);
    if (!m || Number(m[4])===0) return null;
    return (m[1]==='-'?-1:1)*(Number(m[2]||0)+Number(m[3])/Number(m[4]));
  }
  if (unit==='mm') { const n=Number(s.replace(/\s*mm$/, '')); return s && Number.isFinite(n)?n:null; }
  const feet=s.match(/^([+-]?\d+)\s*'\s*-?\s*(.*)$/);
  if (feet) { const rest=feet[2]?inches(feet[2]):0; return rest===null?null:(Number(feet[1])*12+rest)*25.4; }
  const n=inches(s); return n===null?null:n*25.4;
}
