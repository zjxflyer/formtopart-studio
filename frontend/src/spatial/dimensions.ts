import { isWithin, viewVisible, valueText, type SpatialScene, type SpatialDimension, type Vec, type ViewOptions } from './types';

export const xml=(s:string)=>s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
type P=[number,number];
const dot=(a:P,b:P)=>a[0]*b[0]+a[1]*b[1];
const plus=(a:P,b:P,n=1):P=>[a[0]+b[0]*n,a[1]+b[1]*n];
export function dimensionApplies(scene:SpatialScene,d:SpatialDimension,selected:string){
  const chosen=scene.objects.find(o=>o.id===selected);
  return !!chosen&&(d.subjects||[d.owner]).some(id=>{
    const subject=scene.objects.find(o=>o.id===id);
    return isWithin(chosen.id,chosen.ancestors,id)||!!subject&&isWithin(subject.id,subject.ancestors,selected);
  });
}
function visible(scene:SpatialScene,id:string,view:string,o:ViewOptions){
  return scene.objects.some(obj=>isWithin(obj.id,obj.ancestors,id)&&viewVisible(scene,view,obj.id)
    &&!o.hidden.some(h=>isWithin(obj.id,obj.ancestors,h))&&(!o.isolate||isWithin(obj.id,obj.ancestors,o.isolate)));
}
export const componentSizeLabel='Show component width / height / depth / 显示构件宽／高／深';
export const componentSizeTooltip='Display existing overall sizes, not placement distances or fabrication specifications. / 显示已有整体尺寸，不是位置关系或加工规格。';
export function dimensionFeedback(scene:SpatialScene,view:string,o:ViewOptions,geometryView=view){
  const object=scene.objects.find(x=>x.id===o.selected);
  const selection=object?`Selected / 已选：${object.name} · ${object.id}`:'No component selected / 未选择构件';
  let hint='';
  if(o.dimensions==='off')hint='Dimensions are off. Enable a dimension mode first. / 尺寸已关闭，请先开启尺寸模式。';
  else if(o.dimensions==='selected'){
    if(!object)hint='Select a component to see its dimensions. / 请选择构件查看尺寸。';
    else if(!visible(scene,object.id,geometryView,o))hint='Selected component is hidden or isolated out. / 所选构件已隐藏或不在隔离范围内。';
    else if(o.componentSizes&&!scene.dimensions.some(d=>d.kind!=='relationship'&&d.owner===object.id))hint='No overall size records for this selection; select a measurable component. / 所选对象没有整体尺寸记录，请选择有尺寸记录的构件。';
    else if(!selectedDimensions(scene,view,o,geometryView).length)hint='No eligible relationship dimensions. Enable component sizes to inspect existing sizes. / 当前没有适用的关系尺寸，可开启构件尺寸查看已有尺寸。';
  }
  return {selection,hint};
}
export function selectedDimensions(scene:SpatialScene,view:string,o:ViewOptions,geometryView=view){
  if(o.dimensions==='off')return [];
  if(o.dimensions==='selected'&&(!o.selected||!visible(scene,o.selected,geometryView,o)))return [];
  const candidates=scene.dimensions.filter(d=>{
    if(d.kind==='relationship'){
      if(view!=='AXON'&&!d.views?.includes(view))return false;
      if(!(d.subjects||[]).some(id=>visible(scene,id,geometryView,o)))return false;
      if(Object.values(d.anchors||{}).some(a=>{
        const obj=scene.objects.find(x=>x.id===a.owner);
        return obj&&o.hidden.some(h=>isWithin(obj.id,obj.ancestors,h));
      }))return false;
    }else{
      if(!o.componentSizes||!visible(scene,d.owner,geometryView,o))return false;
      if(o.dimensions==='selected')return d.owner===o.selected;
      const obj=scene.objects.find(x=>x.id===d.owner);
      if(obj&&!obj.children.length&&obj.ancestors.length>=3)return false;
    }
    return o.dimensions==='selected'?dimensionApplies(scene,d,o.selected):o.dimensions==='inferred'?d.inferred:true;
  });
  return [...new Map(candidates.map(d=>[d.id,d])).values()].sort((a,b)=>Number(b.kind==='relationship')-Number(a.kind==='relationship')||a.id.localeCompare(b.id));
}
export function dimensionView(scene:SpatialScene,selected:string){
  return scene.dimensions.find(d=>d.kind==='relationship'&&dimensionApplies(scene,d,selected))?.views?.[0];
}
export function dimensionText(d:SpatialDimension,unit:'in'|'mm'){
  if(unit==='mm'||d.kind!=='relationship')return valueText(d.value_mm,unit);
  const whole=Math.floor((d.value_mm+.001)/304.8),rest=d.value_mm-whole*304.8;
  return whole?`${whole}′-${valueText(Math.max(0,rest),'in')}`:valueText(d.value_mm,'in');
}

/** Same screen-space lanes/graphics for WebGL overlays, checking SVG and fallback. */
export function dimensionGraphics(scene:SpatialScene,view:string,o:ViewOptions,project:(p:Vec)=>P,bounds:[number,number,number,number],width:number,height:number,geometryView=view){
  const groups:string[]=[],lanes:Record<string,number>={},edgeOn:string[]=[];
  for(const d of selectedDimensions(scene,view,o,geometryView)){
    const a=project(d.a),b=project(d.b),delta:P=[b[0]-a[0],b[1]-a[1]],length=Math.hypot(...delta);
    if(!Number.isFinite(length)||length<12){edgeOn.push(d.id);continue;}
    let m:P=[delta[0]/length,delta[1]/length];
    if(m[0]<-.05||Math.abs(m[0])<.05&&m[1]<0)m=[-m[0],-m[1]];
    let n:P=[-m[1],m[0]];
    const side=d.side|| (Math.abs(m[0])>.7?'bottom':'right');
    const desired:P=side==='left'?[-1,0]:side==='right'?[1,0]:side==='top'?[0,-1]:[0,1];
    if(dot(n,desired)<0)n=[-n[0],-n[1]];
    const key=Math.abs(m[0])>.7?(n[1]<0?'top':'bottom'):(n[0]<0?'left':'right');
    const lane=lanes[key]||0;lanes[key]=lane+1;
    const corners:P[]=[[bounds[0],bounds[1]],[bounds[2],bounds[1]],[bounds[2],bounds[3]],[bounds[0],bounds[3]]];
    let coordinate=Math.max(...corners.map(p=>dot(p,n)))+24+lane*30;
    // Oblique projected axes can send a global-envelope lane outside the viewport.
    // Bound the whole graphic before drawing, not by silently hiding its label.
    let lo=-Infinity,hi=Infinity;
    for(const s of [dot(a,m),dot(b,m)])for(const axis of [0,1]){
      const pad=24,limit=axis===0?width:height;
      if(Math.abs(n[axis])<1e-6)continue;
      const one=(pad-m[axis]*s)/n[axis],two=(limit-pad-m[axis]*s)/n[axis];
      lo=Math.max(lo,Math.min(one,two));hi=Math.min(hi,Math.max(one,two));
    }
    if(lo<=hi)coordinate=Math.max(lo,Math.min(hi,coordinate));
    const p=plus([m[0]*dot(a,m),m[1]*dot(a,m)],n,coordinate),q=plus([m[0]*dot(b,m),m[1]*dot(b,m)],n,coordinate);
    const center:P=[(p[0]+q[0])/2,(p[1]+q[1])/2];
    const axis:Record<string,string>={Width:'Width',Height:'Height',Depth:'Depth'};
    const text=(d.kind==='relationship'?'':`${axis[d.axis]||d.axis}: `)+dimensionText(d,o.unit),font=width<600?11:13,tw=text.length*font*.6+12;
    const angle=Math.atan2(m[1],m[0])*180/Math.PI;
    const line=(x:P,y:P,role:string)=>`<line data-part="${role}" x1="${x[0].toFixed(2)}" y1="${x[1].toFixed(2)}" x2="${y[0].toFixed(2)}" y2="${y[1].toFixed(2)}"/>`;
    let lines=line(p,q,'dimension-line');
    for(const [start,end] of [[project(d.structural_a),p],[project(d.structural_b),q]] as [P,P][]){
      const dist=Math.hypot(end[0]-start[0],end[1]-start[1]);
      if(dist>9)lines+=line(plus(start,[(end[0]-start[0])/dist,(end[1]-start[1])/dist],7),plus(end,[(end[0]-start[0])/dist,(end[1]-start[1])/dist],5),'witness');
    }
    const tick:P=[(m[0]+n[0])*4,(m[1]+n[1])*4];
    lines+=line(plus(p,tick,-1),plus(p,tick),'tick')+line(plus(q,tick,-1),plus(q,tick),'tick');
    groups.push(`<g class="sp-dimension" data-dimension-id="${xml(d.id)}" data-kind="${d.kind||'size'}" data-inferred="${d.inferred}" data-value-mm="${d.value_mm}" data-witness-a="${d.structural_a.join(',')}" data-witness-b="${d.structural_b.join(',')}" fill="none" stroke="#2563eb" stroke-width="1.2"><title>${xml(d.axis)}</title>${lines}<g transform="translate(${center.join(',')}) rotate(${angle})"><rect x="${-tw/2}" y="-10" width="${tw}" height="20" rx="2" stroke="none" fill="${d.inferred?'#fff1a6':'#ffffff'}"/><text text-anchor="middle" dominant-baseline="central" fill="#2563eb" stroke="none" font-family="Arial,sans-serif" font-size="${font}">${xml(text)}</text></g></g>`);
  }
  const note=edgeOn.length?`<text data-edge-on="${xml(edgeOn.join(' '))}" x="12" y="${height-14}" fill="#53626b" font-family="Arial,sans-serif" font-size="${width<600?10:12}">${edgeOn.length} edge-on / too small: orbit or zoom</text>`:'';
  return groups.join('')+note;
}
