import { isWithin, viewVisible, type SpatialScene, type SpatialObject, type Vec, type ViewOptions } from './types';

export type OpeningSymbol = SpatialScene['symbols'][number];
/** Only existing, finite, owner-bound operation records. Never infer marks from a material. */
export function supportedOpeningSymbols(scene:SpatialScene):OpeningSymbol[]{
  return scene.symbols.filter(s=>s.kind==='opening_operation'&&scene.meshes.some(m=>m.id===s.owner||m.ancestors.includes(s.owner))&&
    scene.objects.some(o=>o.id===s.owner&&o.size.length===3)&&s.points.length>=2&&
    s.points.every(p=>p.length===3&&p.every(Number.isFinite)));
}

export function openingMarkAllowed(scene:SpatialScene,s:OpeningSymbol,view:string,options:ViewOptions,checking=false){
  if(!options.openingMarks||(view==='PLAN'&&!(checking&&s.display_2d_plan)))return false;
  if(s.views&&view!=='AXON'&&!s.views.includes(view))return false;
  if(s.views&&view==='AXON'&&s.views.every(v=>v==='PLAN'))return false;
  const owner=scene.objects.find(o=>o.id===s.owner);
  if(!owner||!viewVisible(scene,view,s.owner))return false;
  if(options.hidden.some(h=>isWithin(owner.id,owner.ancestors,h)))return false;
  if(options.isolate&&!isWithin(owner.id,owner.ancestors,options.isolate))return false;
  if(view==='AXON')return true;
  return (scene.views[view]?.symbols||[]).some(p=>s.owner===p||s.owner.startsWith(p+'/'));
}

/** Solver binds opening points to the owner's local -Y face, followed by its world Z rotation. */
export function openingFaceFrontFacing(owner:SpatialObject,towardViewer:Vec,symbol?:OpeningSymbol){
  if(symbol?.face_normal)return symbol.face_normal.reduce((sum,x,i)=>sum+x*towardViewer[i],0)>1e-6;
  const angle=owner.rotation*Math.PI/180;
  return Math.sin(angle)*towardViewer[0]-Math.cos(angle)*towardViewer[1]>1e-6;
}
