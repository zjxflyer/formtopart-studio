import { defaultOptions, viewVisible, type SpatialScene, type Vec, type ViewOptions } from './types';
import { dimensionGraphics } from './dimensions';
import { supportedOpeningSymbols, openingMarkAllowed, openingFaceFrontFacing } from './openingMarks';
import { resolveCameraPreset } from './viewPresets';
import { viewContext, type ViewContext } from './viewContext';
const escape=(s:string)=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const dot=(a:number[],b:number[])=>a.reduce((s,x,i)=>s+x*b[i],0);
function hull(points:number[][]){
  const sorted=[...new Map(points.map(p=>[p.join(','),p])).values()].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
  const cross=(o:number[],a:number[],b:number[])=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]);
  const lower:number[][]=[],upper:number[][]=[];
  for(const p of sorted){while(lower.length>=2&&cross(lower.at(-2)!,lower.at(-1)!,p)<=0)lower.pop();lower.push(p);}
  for(const p of sorted.reverse()){while(upper.length>=2&&cross(upper.at(-2)!,upper.at(-1)!,p)<=0)upper.pop();upper.push(p);}
  return lower.slice(0,-1).concat(upper.slice(0,-1));
}
/** Live checking projection from solved spatial vertices, never the delivered source SVG. */
export function draftSVG(scene:SpatialScene,view:string,selected='',dimensions=true,unit:'mm'|'in'='in',appearance:'outline'|'material'='outline',options:ViewOptions=defaultOptions,viewportWidth=680,context:ViewContext=viewContext(scene,view,'checking')){
  const preset=resolveCameraPreset(scene,view,false);
  const baseView=preset?.baseView||view;
  const annotationView=context.annotationView;
  const displayView=view;
  view=baseView;
  const def=preset?{direction:preset.cameraPositionDirection.map(value=>-value) as Vec,right:preset.right,up:preset.up,detail:preset.label}:scene.views[view];
  const raw=(p:Vec):[number,number]=>[dot(p,def.right),-dot(p,def.up)];
  const meshes=scene.meshes.filter(m=>{
    // A room can be the main subject: retain explicitly included context owners.
    if(m.context&&context.geometryView!=='AXON'&&!preset&&!scene.views[baseView]?.include?.some(p=>m.id===p||m.id.startsWith(p+'/')))return false;
    return viewVisible(scene,context.geometryView,m.id)&&!options.hidden.some(id=>m.id===id||m.ancestors.includes(id))&&(!options.isolate||m.id===options.isolate||m.ancestors.includes(options.isolate));
  }).sort((a,b)=>{
    const depth=dot(b.vertices[0],def.direction)-dot(a.vertices[0],def.direction);
    return Math.abs(depth)>1e-6?depth:Number(a.representation==='source_surface')-Number(b.representation==='source_surface');
  });
  const pts=meshes.flatMap(m=>m.vertices.map(raw));
  const min=pts.length?[Math.min(...pts.map(p=>p[0])),Math.min(...pts.map(p=>p[1]))]:[0,0],max=pts.length?[Math.max(...pts.map(p=>p[0])),Math.max(...pts.map(p=>p[1]))]:[1,1];
  const width=Math.max(320,viewportWidth),height=width*1.35;
  const scale=Math.min((width-170)/Math.max(1,max[0]-min[0]),(height-150)/Math.max(1,max[1]-min[1]));
  const toScreen=(p:Vec):[number,number]=>{const v=raw(p);return [width/2+(v[0]-(min[0]+max[0])/2)*scale,height/2+(v[1]-(min[1]+max[1])/2)*scale];};
  const project=raw; // Preserve source-owned primitive coordinates; transform their group only.
  const detailOwners=new Set<string>();
  const visit=(n:SpatialScene['project']['root'])=>{if('mesh' in n)detailOwners.add(n.id);n.children.forEach(visit);};if(scene.project.root)visit(scene.project.root);
  const shapes=meshes.map(m=>{
    const p=hull(m.vertices.map(project));if(p.length<3)return '';
    const outline=`<polygon data-object-id="${escape(m.id)}" points="${p.map(a=>a.join(',')).join(' ')}" fill="${appearance==='outline'?'#ffffff':scene.project.materials[m.material]}" fill-opacity="${context.geometryView==='AXON'&&m.context&&options.transparentWalls?.1:1}" stroke="#000000" stroke-width="${1.4/scale}"/>`;
    if(view!=='PLAN')return outline+(detailOwners.has(m.id)?`<path data-object-detail-id="${escape(m.id)}" data-object-id="${escape(m.id)}" d="${m.edges.map(([a,b])=>`M${project(m.vertices[a]).join(',')}L${project(m.vertices[b]).join(',')}`).join(' ')}" fill="none" stroke="#000000" stroke-width="${1.2/scale}"/>`:'');
    // Convex hull alone loses supported inner basin rims. Emit exposed top-face
    // detail edges, not triangulation or duplicate outer-perimeter strokes.
    const top=Math.max(...m.vertices.map(v=>v[2]));
    const onSegment=(v:number[],a:number[],b:number[])=>Math.abs((b[0]-a[0])*(v[1]-a[1])-(b[1]-a[1])*(v[0]-a[0]))<.01&&v[0]>=Math.min(a[0],b[0])-.01&&v[0]<=Math.max(a[0],b[0])+.01&&v[1]>=Math.min(a[1],b[1])-.01&&v[1]<=Math.max(a[1],b[1])+.01;
    const inner=m.edges.filter(([a,b])=>Math.abs(m.vertices[a][2]-top)<.001&&Math.abs(m.vertices[b][2]-top)<.001).map(([a,b])=>[project(m.vertices[a]),project(m.vertices[b])]).filter(([a,b])=>!p.some((v,i)=>onSegment(a,v,p[(i+1)%p.length])&&onSegment(b,v,p[(i+1)%p.length])));
    return outline+(inner.length?`<path data-object-detail-id="${escape(m.id)}" d="${inner.map(([a,b])=>`M${a.join(',')}L${b.join(',')}`).join(' ')}" fill="none" stroke="#000000" stroke-width="${1.2/scale}"/>`:'');
  }).join('');
  const symbols=supportedOpeningSymbols(scene).filter(s=>{
    const mesh=meshes.find(m=>m.id===s.owner||m.ancestors.includes(s.owner));if(!mesh)return false;
    const owner=scene.objects.find(o=>o.id===s.owner)!;
    return openingMarkAllowed(scene,s,annotationView,options,true)&&openingFaceFrontFacing(owner,def.direction.map(x=>-x) as Vec,s);
  }).map(s=>`<polyline data-opening-symbol-id="${escape(s.id)}" data-owner="${escape(s.owner)}" data-pattern="${escape(s.pattern)}" points="${s.points.map(p=>project(p).join(',')).join(' ')}" fill="none" stroke="#000000" stroke-width="${1.2/scale}" ${s.pattern==='source-dash-segment'?'':'stroke-dasharray="30 18"'}/>`).join('');
  const b:[number,number,number,number]=[width/2-(max[0]-min[0])*scale/2,height/2-(max[1]-min[1])*scale/2,width/2+(max[0]-min[0])*scale/2,height/2+(max[1]-min[1])*scale/2];
  const ds=dimensionGraphics(scene,annotationView,{...options,selected,unit,dimensions:dimensions?options.dimensions:'off'},toScreen,b,width,height,context.geometryView);
  const transform=`translate(${width/2-(min[0]+max[0])*scale/2} ${height/2-(min[1]+max[1])*scale/2}) scale(${scale})`;
  const caption=`${displayView} / ${def.detail||displayView}`;
  const short=(value:string,limit:number)=>value.length>limit?value.slice(0,limit-1)+'…':value;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(displayView)} checking draft"><rect width="${width}" height="${height}" fill="#ffffff"/><text x="15" y="22" font-family="Arial,sans-serif" font-size="12" fill="#53626b">${escape(short(scene.project.name||scene.project.id||'Project',72))}</text><g transform="${transform}">${shapes}${symbols}</g>${ds}<text x="15" y="${height-32}" font-family="Arial,sans-serif" font-size="12" fill="#6b7479">${escape(short(caption,56))} · R${scene.project.revision} · ${unit}</text><text x="15" y="${height-16}" font-family="Arial,sans-serif" font-size="10" fill="#6b7479">spatial checking draft · Customer review</text></svg>`;
}
