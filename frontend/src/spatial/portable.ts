/** Offline, deliberately view-only entry. No API, file import, editor or save endpoint. */
import { KitchenViewer } from './engine';
import {exportCanvasImage} from './exportImage';
import { draftSVG } from './drafts';
import { defaultOptions, type SpatialScene, type ViewOptions } from './types';
import { supportedOpeningSymbols } from './openingMarks';
import { openingMarkLabel, openingMarkTooltip, noOpeningMarks } from './openingMarkLabels';
import { dimensionView, dimensionFeedback, componentSizeLabel, componentSizeTooltip } from './dimensions';
import { directionPresetGroups, resolveCameraPreset } from './viewPresets';
import { viewContext } from './viewContext';

// Only translate explicit paired interface labels. Source/model strings stay intact.
const englishUI = (value: string) => value.split(/\s\/\s(?=[\u3400-\u9fff])/)[0];

const data=JSON.parse(document.getElementById('a200-scene')!.textContent!) as SpatialScene;
const style=document.createElement('style');style.textContent='.direction-wrap{position:relative;display:inline-block}.direction-menu{position:absolute;z-index:30;top:calc(100% + 4px);left:0;min-width:350px;padding:8px;background:#fff;border:1px solid #b9c6c3;border-radius:5px;box-shadow:0 7px 24px #1b353b2b;color:#233039}.direction-menu section+section{border-top:1px solid #e0e5e2;margin-top:7px;padding-top:7px}.direction-menu b{display:block;font-size:10px;color:#456a67;margin-bottom:4px}.direction-menu section>div{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px}.direction-menu button{padding:6px 3px;font-size:10px;white-space:normal}.direction-menu button:hover{background:#e9efed}@media(max-width:600px){.direction-menu{position:fixed;left:7px;right:7px;top:112px;min-width:0}.direction-menu section>div{grid-template-columns:repeat(2,minmax(0,1fr))}}';document.head.append(style);
const firstView=Object.keys(data.views)[0];
const container=document.getElementById('viewer')!,controls=document.getElementById('controls')!,fallback=document.getElementById('fallback')!;
let viewer:KitchenViewer|null=null;let options:ViewOptions={...defaultOptions,...data.project.viewer_defaults,selected:data.default_selection||data.project.root.id};
let fallbackView=firstView,activeCamera='AXON';let directionButton:HTMLButtonElement|null=null;
function update(){
  if(viewer)viewer.setOptions(options);
  else fallback.innerHTML='<p>WebGL unavailable. Showing a spatial checking projection, not a 3D render.</p>'+draftSVG(data,fallbackView,options.selected,options.dimensions!=='off',options.unit,options.appearance,options,Math.max(320,fallback.clientWidth-30),viewContext(data,activeCamera));
  align.disabled=!dimensionView(data,options.selected);
  const feedback=dimensionFeedback(data,viewContext(data,activeCamera).annotationView,options,'AXON');
  const selectedObject=data.objects.find(object=>object.id===options.selected);
  const selection=selectedObject?`Selected: ${selectedObject.name} · ${selectedObject.id}`:'No component selected';
  selectionStatus.textContent=[selection,englishUI(feedback.hint)].filter(Boolean).join(' — ');
  sizeToggle.disabled=options.dimensions==='off';sizeToggle.checked=!!options.componentSizes;
  sizes.title=englishUI(sizeToggle.disabled?feedback.hint:componentSizeTooltip);
  sizeToggle.setAttribute('aria-description',sizes.title);
}
const align=document.createElement('button');align.textContent='Align to dimension view';align.setAttribute('aria-label',align.textContent);
align.onclick=()=>{const v=dimensionView(data,options.selected);if(!v)return;selectCamera(v,true);};
const camera=document.createElement('select');camera.setAttribute('aria-label','Camera');
camera.title='Source views — separate from 3D quick directions';
const quickOption=document.createElement('option');quickOption.value='__QUICK__';quickOption.disabled=true;quickOption.textContent='3D quick view';camera.append(quickOption);
const freeOption=document.createElement('option');freeOption.value='__FREE__';freeOption.disabled=true;freeOption.textContent='Free orbit';camera.append(freeOption);
for(const v of ['AXON',...Object.keys(data.views)]){const o=document.createElement('option');o.value=v;o.textContent=v==='AXON'?'3D':v==='PLAN'?'Plan':`${v} · ${data.views[v].detail}`;camera.append(o);}
const presetGroups=directionPresetGroups(data);
function selectCamera(value:string,fit?:boolean){activeCamera=value;const preset=resolveCameraPreset(data,value);camera.value=preset?'__QUICK__':value;if(directionButton)directionButton.textContent=`Orthographic quick views${preset?` · ${englishUI(preset.label)}`:''} ▾`;for(const b of directionMenu.querySelectorAll<HTMLButtonElement>('[data-preset]'))b.setAttribute('aria-pressed',String(b.dataset.preset===value));if(viewer){viewer.preset(value,fit);update();}else{fallbackView=value==='AXON'?firstView:value;update();}}
camera.value='AXON';
camera.onchange=()=>selectCamera(camera.value);controls.append(camera);
const directionWrap=document.createElement('div');directionWrap.className='direction-wrap';
const button=document.createElement('button');directionButton=button;button.textContent='Orthographic quick views ▾';button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','direction-menu');
const directionMenu=document.createElement('div');directionMenu.id='direction-menu';directionMenu.className='direction-menu';directionMenu.hidden=true;
for(const group of presetGroups){const section=document.createElement('section'),title=document.createElement('b');title.textContent=englishUI(group.label);const row=document.createElement('div');for(const item of group.items){const itemButton=document.createElement('button');itemButton.textContent=englishUI(item.label);itemButton.dataset.preset=item.id;itemButton.onclick=()=>{selectCamera(item.id);directionMenu.hidden=true;button.setAttribute('aria-expanded','false');};row.append(itemButton);}section.append(title,row);directionMenu.append(section);}
button.onclick=()=>{directionMenu.hidden=!directionMenu.hidden;button.setAttribute('aria-expanded',String(!directionMenu.hidden));};directionWrap.append(button,directionMenu);controls.append(directionWrap);
controls.append(align);
const fit=document.createElement('button');fit.textContent='Fit';fit.onclick=()=>viewer?.fit();controls.append(fit);
const png=document.createElement('button');png.textContent='Export view PNG';png.onclick=()=>{const canvas=container.querySelector('canvas');if(canvas)exportCanvasImage(canvas,`${data.project_key||'project'}-${activeCamera}-3D.png`);};controls.append(png);
const appearance=document.createElement('select');appearance.setAttribute('aria-label','Appearance');
for(const [value,text] of [['outline','White faces + black outlines'],['material','Material colors']]){const o=document.createElement('option');o.value=value;o.textContent=text;appearance.append(o);}
appearance.value=options.appearance;appearance.onchange=()=>{options={...options,appearance:appearance.value as ViewOptions['appearance']};update();};controls.append(appearance);
const dimensions=document.createElement('select');dimensions.setAttribute('aria-label','Dimensions');
for(const [v,t] of [['off','Dimensions off'],['selected','Selected dimensions'],['all','Assembly dimensions'],['inferred','Inferred dimensions']]){const o=document.createElement('option');o.value=v;o.textContent=t;dimensions.append(o);}
dimensions.value=options.dimensions;dimensions.onchange=()=>{options={...options,dimensions:dimensions.value as ViewOptions['dimensions']};update();};controls.append(dimensions);
const sizes=document.createElement('label'),sizeToggle=document.createElement('input');sizeToggle.type='checkbox';sizeToggle.setAttribute('aria-label',englishUI(componentSizeLabel));sizeToggle.onchange=()=>{options={...options,componentSizes:sizeToggle.checked};update();};sizes.append(sizeToggle,document.createTextNode(englishUI(componentSizeLabel)));controls.append(sizes);
for(const [key,text] of [['openingMarks',openingMarkLabel],['text','Text'],['viewLabels','View labels'],['transparentWalls','Transparent walls']] as const){
  const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.setAttribute('aria-label',englishUI(text));input.checked=options[key];input.onchange=()=>{options={...options,[key]:input.checked};update();};label.append(input,document.createTextNode(englishUI(text)));controls.append(label);
  if(key==='openingMarks'){
    label.title=englishUI(openingMarkTooltip);input.setAttribute('aria-description',englishUI(openingMarkTooltip));
    if(!supportedOpeningSymbols(data).length){input.disabled=true;label.title+=' '+englishUI(noOpeningMarks);label.append(document.createTextNode(' (none)'));}
  }
}
const units=document.createElement('select');units.setAttribute('aria-label','Units');for(const v of ['in','mm']){const o=document.createElement('option');o.value=v;o.textContent=v;units.append(o);}units.value=options.unit;units.onchange=()=>{options={...options,unit:units.value as 'in'|'mm'};update();};controls.append(units);
const selectionStatus=document.createElement('div');selectionStatus.className='sp-selection-status';selectionStatus.setAttribute('role','status');selectionStatus.style.cssText='flex-basis:100%;font-size:11px;overflow-wrap:anywhere';controls.append(selectionStatus);
fallback.addEventListener('click',e=>{const id=(e.target as Element).closest('[data-object-id]')?.getAttribute('data-object-id');if(id){options={...options,selected:id};update();}});
try{viewer=new KitchenViewer(container,data,id=>{options={...options,selected:id};update();});viewer.onOrbit=()=>{activeCamera='__FREE__';camera.value=activeCamera;button.textContent='Orthographic quick views ▾';for(const b of directionMenu.querySelectorAll('[data-preset]'))b.setAttribute('aria-pressed','false');};update();}
catch{container.hidden=true;fallback.hidden=false;fallbackView=dimensionView(data,options.selected)||firstView;activeCamera=fallbackView;camera.value=fallbackView;update();}
window.addEventListener('pagehide',()=>viewer?.dispose(),{once:true});
window.addEventListener('resize',()=>{if(!viewer)update();});
