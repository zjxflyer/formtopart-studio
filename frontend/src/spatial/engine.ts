import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { defaultOptions, isWithin, viewVisible, type SpatialScene, type ViewOptions, type Vec } from './types';
import { supportedOpeningSymbols, openingMarkAllowed, openingFaceFrontFacing } from './openingMarks';
import { dimensionGraphics } from './dimensions';
import { resolveCameraPreset } from './viewPresets';
import { CameraRig } from './cameraRig';
import { viewContext } from './viewContext';
import { localDimensionFitAnchors } from './fitAnchors';
import { finishStyle, finishTexture, finishUV } from './presentationMaterials';

/** Shared by the editable application and the completely offline HTML viewer. */
export class KitchenViewer {
  renderer: THREE.WebGLRenderer;
  camera: THREE.OrthographicCamera;
  rig: CameraRig;
  controls: OrbitControls;
  world = new THREE.Scene();
  geometry = new THREE.Group();
  dimensionGroup = new THREE.Group();
  openingGroup = new THREE.Group();
  data: SpatialScene;
  options: ViewOptions = {...defaultOptions};
  labels: {element: HTMLElement; at: THREE.Vector3; owner: string; kind: string; inferred?: boolean}[]=[];
  overlay: HTMLDivElement;
  dimensionOverlay: SVGSVGElement;
  lastDimensionSVG='';
  observer: ResizeObserver;
  frame=0;
  disposed=false;
  down=[0,0];
  onSelect?: (id:string)=>void;
  onOrbit?: ()=>void;
  snappedOrientation: THREE.Quaternion|null=null;
  view='AXON';
  visibilityView='AXON';
  finishMaps = new Map<string, THREE.CanvasTexture>();
  constructor(public container: HTMLElement, data: SpatialScene, onSelect?: (id:string)=>void) {
    this.data=data; this.onSelect=onSelect;
    this.renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
    this.renderer.setClearColor('#f4f3ef');
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = .9;
    this.renderer.domElement.setAttribute('aria-label','Interactive customer model');
    this.renderer.domElement.style.touchAction='none';
    container.append(this.renderer.domElement);
    this.overlay=document.createElement('div');this.overlay.className='sp-labels';container.append(this.overlay);
    this.dimensionOverlay=document.createElementNS('http://www.w3.org/2000/svg','svg');
    this.dimensionOverlay.setAttribute('class','sp-dimension-overlay');
    this.dimensionOverlay.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible';
    container.append(this.dimensionOverlay);
    this.camera=new THREE.OrthographicCamera(-4000,4000,4000,-4000,1,100000);
    this.camera.up.set(0,0,1);
    this.rig=new CameraRig(this.camera);
    this.controls=new OrbitControls(this.rig.input,this.renderer.domElement);
    this.controls.enableDamping=true;
    this.world.add(new THREE.HemisphereLight('#ffffff','#8a8176',2.5));
    const light=new THREE.DirectionalLight('#ffffff',2.5);light.position.set(-4000,6000,8000);this.world.add(light);
    const fill=new THREE.DirectionalLight('#e7edf5',1.2);fill.position.set(5000,-4000,3500);this.world.add(fill);
    this.openingGroup.name='opening-annotations';
    this.world.add(this.geometry,this.dimensionGroup,this.openingGroup);
    this.observer=new ResizeObserver(()=>this.resize()); this.observer.observe(container);
    this.renderer.domElement.addEventListener('pointerdown',this.pointerDown);
    this.renderer.domElement.addEventListener('pointerup',this.pointerUp);
    this.setData(data);this.preset('AXON',true);this.animate();
  }
  pointerDown=(e:PointerEvent)=>{this.down=[e.clientX,e.clientY];};
  pointerUp=(e:PointerEvent)=>{
    if (Math.hypot(e.clientX-this.down[0],e.clientY-this.down[1])>5)return;
    const rect=this.renderer.domElement.getBoundingClientRect();
    const mouse=new THREE.Vector2((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);
    const ray=new THREE.Raycaster();ray.setFromCamera(mouse,this.camera);
    const hit=ray.intersectObjects(this.geometry.children,false).find(h=>h.object instanceof THREE.Mesh && h.object.visible && (!h.object.userData.context || !this.options.transparentWalls));
    this.options.selected=hit?hit.object.userData.id:'';this.onSelect?.(this.options.selected);this.refresh();
  };
  clear(group:THREE.Group){
    for(const child of [...group.children]){
      const m=child as THREE.Mesh;m.geometry?.dispose();
      if(Array.isArray(m.material))m.material.forEach(x=>x.dispose());else m.material?.dispose();
      group.remove(child);
    }
  }
  setData(data:SpatialScene){
    this.data=data;this.clear(this.geometry);this.clear(this.openingGroup);
    for(const m of data.meshes){
      const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(m.vertices.flat(),3));g.setIndex(m.indices);g.computeVertexNormals();
      const finish=finishStyle(data,m.material);finishUV(g);
      if(!this.finishMaps.has(finish.kind)){const map=finishTexture(finish.kind);if(map)this.finishMaps.set(finish.kind,map);}
      const material=new THREE.MeshStandardMaterial({color:data.project.materials[m.material]||'#dedbd4',map:this.finishMaps.get(finish.kind)||null,roughness:finish.roughness,metalness:finish.metalness,flatShading:true,side:THREE.DoubleSide,polygonOffset:true,polygonOffsetFactor:1,polygonOffsetUnits:1});
      material.userData.finish=finish;
      const mesh=new THREE.Mesh(g,material);mesh.userData=m;this.geometry.add(mesh);
      if(m.representation==='source_surface'){
        // Observed exterior faces cover coincident proposed carcass edges without
        // moving source coordinates or defeating occlusion by foreground objects.
        material.polygonOffset=false;mesh.renderOrder=1;
      }
      const eg=new THREE.BufferGeometry().setFromPoints(m.edges.flatMap(([a,b])=>[new THREE.Vector3(...m.vertices[a]),new THREE.Vector3(...m.vertices[b])]));
      const line=new THREE.LineSegments(eg,new THREE.LineBasicMaterial({color:'#252b2d',transparent:true,opacity:1}));line.userData={...m,edge:true};this.geometry.add(line);
      if(m.representation==='source_surface')line.renderOrder=2;
      else if(m.representation==='solid')line.material.depthFunc=THREE.LessDepth;
    }
    for(const symbol of supportedOpeningSymbols(data)){
      const points=symbol.points.map(p=>new THREE.Vector3(...p));
      const material=symbol.pattern==='source-dash-segment'
        ?new THREE.LineBasicMaterial({color:'#000000',depthTest:true,depthWrite:false})
        :new THREE.LineDashedMaterial({color:'#000000',dashSize:30,gapSize:18,depthTest:true,depthWrite:false});
      const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),material);
      if(symbol.pattern!=='source-dash-segment')line.computeLineDistances();
      line.name=symbol.id;
      line.userData={symbol,owner:data.objects.find(o=>o.id===symbol.owner),allowed:false};
      this.openingGroup.add(line);
    }
    this.refresh();
  }
  setOptions(options:ViewOptions){this.options={...options,appearance:options.appearance||'outline'};this.refresh();}
  isVisible(id:string,ancestors:string[]){
    if(!viewVisible(this.data,this.visibilityView,id))return false;
    return !this.options.hidden.some(h=>isWithin(id,ancestors,h)) && (!this.options.isolate||isWithin(id,ancestors,this.options.isolate));
  }
  label(text:string,at:Vec,owner:string,kind:string,inferred=false){
    const element=document.createElement('span');element.className=`sp-label ${kind} ${inferred?'inferred':''}`;element.textContent=text;
    this.overlay.append(element);this.labels.push({element,at:new THREE.Vector3(...at),owner,kind,inferred});
  }
  refresh(){
    this.openingGroup.visible=!!this.options.openingMarks;
    for(const line of this.openingGroup.children)line.userData.allowed=openingMarkAllowed(this.data,line.userData.symbol,this.view,this.options);
    this.refreshOpeningFacing();
    this.renderer.setClearColor(this.options.appearance==='outline'?'#ffffff':'#f4f3ef');
    for(const o of this.geometry.children){
      const m=o.userData; o.visible=this.isVisible(m.id,m.ancestors);
      const selected=isWithin(m.id,m.ancestors,this.options.selected);
      const blank=this.options.appearance==='outline';
      if(o instanceof THREE.Mesh){
        o.material.color.set(blank?'#ffffff':this.data.project.materials[m.material]||'#dedbd4');
        o.material.emissive.set(blank?'#ffffff':selected?'#2a1600':'#000000');
        const finish=o.material.userData.finish;
        const map=blank?null:this.finishMaps.get(finish?.kind)||null;
        if(o.material.map!==map){o.material.map=map;o.material.needsUpdate=true;}
        o.material.metalness=blank?0:finish?.metalness||0;
        o.material.roughness=blank?1:finish?.roughness||.8;
        o.material.toneMapped=!blank;
        o.material.transparent=!!m.context&&this.options.transparentWalls;o.material.opacity=m.context&&this.options.transparentWalls?.1:1;o.material.depthWrite=!(m.context&&this.options.transparentWalls);
      }
      else if(o instanceof THREE.LineSegments){o.material.color.set(blank?'#000000':selected?'#a45d0b':'#403b35');o.material.opacity=blank?1:m.context&&this.options.transparentWalls?.2:.55;}
    }
    this.overlay.replaceChildren();this.labels=[];this.clear(this.dimensionGroup);
    this.lastDimensionSVG='\0'; // Empty/off is a real rendered state, not a cache miss.
    if(this.options.text){
      for(const o of this.data.objects.filter(o=>o.children.length>0||o.id===this.options.selected)){
        if(o.id===this.data.project.root.id||o.context||!this.isVisible(o.id,o.ancestors))continue;
        const meshes=this.data.meshes.filter(m=>isWithin(m.id,m.ancestors,o.id));
        if(!meshes.length)continue;const b=new THREE.Box3().setFromPoints(meshes.flatMap(m=>m.vertices.map(p=>new THREE.Vector3(...p))));
        const at=b.getCenter(new THREE.Vector3());at.z=b.max.z+70;
        this.label(o.description||o.name,at.toArray() as Vec,o.id,'description');
      }
    }
    if(this.options.viewLabels){
      const b=this.data.bounds,c=b.min.map((x,i)=>(x+b.max[i])/2);
      for(const [name,v] of Object.entries(this.data.views)){
        if(name==='PLAN')continue;
        const at=c.map((x,i)=>x-v.direction[i]*((b.max[i]-b.min[i])/2+400)) as Vec;at[2]=180;
        this.label(`${v.detail} → ${name}`,at,'','view-reference');
      }
    }
  }
  refreshOpeningFacing(){
    const direction=this.camera.getWorldDirection(new THREE.Vector3()).negate().toArray() as Vec;
    let visible=0;
    for(const line of this.openingGroup.children){
      line.visible=!!line.userData.allowed&&openingFaceFrontFacing(line.userData.owner,direction,line.userData.symbol);
      if(this.openingGroup.visible&&line.visible)visible++;
    }
    this.renderer.domElement.dataset.openingMarks=this.options.openingMarks?'on':'off';
    this.renderer.domElement.dataset.visibleOpeningMarks=String(visible);
  }
  resize(){
    const w=this.container.clientWidth,h=this.container.clientHeight;if(!w||!h)return;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));this.renderer.setSize(w,h);
    const aspect=w/h,camera=this.rig.input,half=(camera.top-camera.bottom)/2;
    camera.left=-half*aspect;camera.right=half*aspect;camera.updateProjectionMatrix();this.rig.sync(this.controls.target);
  }
  fittedHalfHeight(aspect:number,points?:THREE.Vector3[]){
    const pts=[...(points||this.visiblePoints()), ...localDimensionFitAnchors(this.data,this.view,this.options,this.visibilityView).map(point=>new THREE.Vector3(...point))];
    if(!pts.length)return 3000;
    this.camera.updateMatrixWorld();
    const right=new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld,0),up=new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld,1);
    const target=this.rig.world(this.controls.target);
    const xs=pts.map(p=>p.clone().sub(target).dot(right)),ys=pts.map(p=>p.clone().sub(target).dot(up));
    return Math.max(Math.max(...xs.map(Math.abs))/Math.max(aspect,.15),Math.max(...ys.map(Math.abs)),100)*1.25;
  }
  visiblePoints(){return this.data.meshes.filter(m=>this.isVisible(m.id,m.ancestors)).flatMap(m=>m.vertices.map(p=>new THREE.Vector3(...p)));}
  preset(name:string,fit?:boolean){
    const preset=resolveCameraPreset(this.data,name);
    if(name!=='AXON'&&!preset&&!this.data.views[name])return;
    const previousTarget=this.rig.world(this.controls.target);
    const distance=this.rig.distance;
    const context=viewContext(this.data,name);
    fit=fit??context.fitOnSelect;
    this.visibilityView=context.geometryView;
    this.view=context.annotationView;
    const previousHalf=Math.max((this.camera.top-this.camera.bottom)/2,100);
    const bounds=new THREE.Box3().setFromPoints(this.visiblePoints());
    if(bounds.isEmpty())bounds.set(new THREE.Vector3(...this.data.bounds.min),new THREE.Vector3(...this.data.bounds.max));
    const center=!fit?previousTarget:bounds.getCenter(new THREE.Vector3());
    const direction=name==='AXON'?new THREE.Vector3(-1.2,-1.3,.95):new THREE.Vector3(...(preset?.cameraPositionDirection||this.data.views[name].direction.map(value=>-value) as Vec));
    const up=new THREE.Vector3(...(name==='AXON'?[0,0,1] as Vec:preset?.up||this.data.views[name].up));
    this.controls.dispose();
    this.rig.snap(center,direction.normalize(),up,distance);
    // OrbitControls always receives model-world coordinates and vertical Z.
    this.controls=new OrbitControls(this.rig.input,this.renderer.domElement);this.controls.target.copy(center);this.controls.enableDamping=true;
    this.controls.update();this.rig.sync(this.controls.target);
    this.snappedOrientation=this.camera.quaternion.clone();
    const half=fit?this.fittedHalfHeight(this.container.clientWidth/this.container.clientHeight):previousHalf;
    this.rig.input.top=half;this.rig.input.bottom=-half;if(fit)this.rig.input.zoom=1;
    this.resize();this.refresh();
  }
  fit(){
    const points=this.visiblePoints();
    if(points.length){
      const center=new THREE.Box3().setFromPoints(points).getCenter(new THREE.Vector3());
      this.rig.input.position.add(center.clone().sub(this.controls.target));this.controls.target.copy(center);
    }
    this.rig.sync(this.controls.target);const half=this.fittedHalfHeight(this.container.clientWidth/this.container.clientHeight);
    this.rig.input.top=half;this.rig.input.bottom=-half;this.rig.input.zoom=1;this.resize();
  }
  focus(){
    const points=this.data.meshes.filter(m=>isWithin(m.id,m.ancestors,this.options.selected)).flatMap(m=>m.vertices.map(p=>new THREE.Vector3(...p)));
    if(!points.length)return;
    const box=new THREE.Box3().setFromPoints(points),center=box.getCenter(new THREE.Vector3());
    const local=this.rig.local(center);
    this.rig.input.position.add(local.clone().sub(this.controls.target));this.controls.target.copy(local);this.rig.sync(this.controls.target);
    const half=this.fittedHalfHeight(this.container.clientWidth/this.container.clientHeight,points);
    this.rig.input.top=half;this.rig.input.bottom=-half;this.rig.input.zoom=1;this.resize();this.controls.update();this.rig.sync(this.controls.target);
  }
  animate=()=>{
    if(this.disposed)return;this.frame=requestAnimationFrame(this.animate);this.controls.update();this.rig.sync(this.controls.target);
    if(this.snappedOrientation&&this.snappedOrientation.angleTo(this.camera.quaternion)>1e-6){this.snappedOrientation=null;this.onOrbit?.();}
    this.refreshOpeningFacing();this.renderer.render(this.world,this.camera);
    const w=this.container.clientWidth,h=this.container.clientHeight,occupied:{x:number;y:number;w:number;h:number}[]=[];
    const project=(p:Vec):[number,number]=>{const v=new THREE.Vector3(...p).project(this.camera);return [(v.x+1)*w/2,(-v.y+1)*h/2];};
    const projected=this.data.meshes.filter(m=>this.isVisible(m.id,m.ancestors)).flatMap(m=>m.vertices.map(project));
    if(projected.length){
      const bounds:[number,number,number,number]=[Math.min(...projected.map(p=>p[0])),Math.min(...projected.map(p=>p[1])),Math.max(...projected.map(p=>p[0])),Math.max(...projected.map(p=>p[1]))];
      const svg=dimensionGraphics(this.data,this.view,this.options,project,bounds,w,h,this.visibilityView);
      if(svg!==this.lastDimensionSVG){this.dimensionOverlay.setAttribute('viewBox',`0 0 ${w} ${h}`);this.dimensionOverlay.innerHTML=svg;this.lastDimensionSVG=svg;}
    }
    for(const label of this.labels){
      const p=label.at.clone().project(this.camera);let x=(p.x+1)*w/2,y=(-p.y+1)*h/2;
      if(Math.abs(p.z)>1||x<8||x>w-8||y<8||y>h-8){label.element.style.display='none';continue;}
      label.element.style.display='block';
      const lw=label.element.offsetWidth,lh=label.element.offsetHeight;
      x=Math.max(lw/2+4,Math.min(w-lw/2-4,x));
      let tries=0;
      while(occupied.some(b=>Math.abs(b.x-x)<(b.w+lw)/2+3&&Math.abs(b.y-y)<(b.h+lh)/2+3)&&tries++<8)y+=lh+4;
      if(y>h-lh||occupied.some(b=>Math.abs(b.x-x)<(b.w+lw)/2+3&&Math.abs(b.y-y)<(b.h+lh)/2+3)){label.element.style.display='none';continue;}
      occupied.push({x,y,w:lw,h:lh});label.element.style.left=`${x}px`;label.element.style.top=`${y}px`;
    }
  };
  dispose(){this.disposed=true;cancelAnimationFrame(this.frame);this.observer.disconnect();this.controls.dispose();this.clear(this.geometry);this.clear(this.dimensionGroup);this.clear(this.openingGroup);for(const texture of this.finishMaps.values())texture.dispose();this.finishMaps.clear();this.renderer.dispose();this.renderer.domElement.removeEventListener('pointerdown',this.pointerDown);this.renderer.domElement.removeEventListener('pointerup',this.pointerUp);this.renderer.domElement.remove();this.overlay.remove();this.dimensionOverlay.remove();}
}
