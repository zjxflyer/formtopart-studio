import { useEffect, useRef, useState } from 'react';
import { KitchenViewer } from './engine';
import {exportCanvasImage} from './exportImage';
import { draftSVG } from './drafts';
import { dimensionView, dimensionApplies, dimensionFeedback, componentSizeLabel, componentSizeTooltip } from './dimensions';
import { supportedOpeningSymbols } from './openingMarks';
import { openingMarkLabel, openingMarkTooltip, noOpeningMarks } from './openingMarkLabels';
import { defaultOptions, readValue, valueText, type SpatialScene, type SpatialNode, type ViewOptions } from './types';
import { directionPresetGroups, resolveCameraPreset } from './viewPresets';
import { viewContext } from './viewContext';
import './spatial.css';

async function projectAPI<T>(base:string,path:string,body?:unknown):Promise<T>{
  const r=await fetch(base+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);
  if(!r.ok){let message=await r.text();try{message=JSON.parse(message).detail;}catch{/* non-JSON server error */}throw new Error(message);}
  return r.json();
}
function saveFile(name:string,text:string,type:string){const url=URL.createObjectURL(new Blob([text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function NodeTree({node,selected,onSelect}:{node:SpatialNode;selected:string;onSelect:(id:string)=>void}){
  const [open,setOpen]=useState(node.id.split('/').length<2);
  return <li><div className={selected===node.id?'active':''}>{node.children.length>0&&<button className="sp-disclosure" onClick={()=>setOpen(!open)}>{open?'−':'+'}</button>}<button className="sp-tree-item" onClick={()=>onSelect(node.id)} title={node.id}>{node.name}</button></div>{open&&node.children.length>0&&<ul>{node.children.map(n=><NodeTree key={n.id} node={n} selected={selected} onSelect={onSelect}/>)}</ul>}</li>;
}
type Preview={scene:SpatialScene;affected:string[];preview_hash:string};
type Change={object_id:string;field:string;value:string|number};

export default function Workspace3D({projectKey,variant}:{projectKey:string;variant?:string}){
  const base='/api/spatial/projects/'+encodeURIComponent(projectKey);
  const variantQuery=variant?`?variant=${encodeURIComponent(variant)}`:'';
  const api=<T,>(path:string,body?:unknown)=>projectAPI<T>(base,path+variantQuery,body);
  const [metadata,setMetadata]=useState<{name:string;status:string}|null>(null);
  const [scene,setScene]=useState<SpatialScene|null>(null),[options,setOptions]=useState<ViewOptions>({...defaultOptions});
  const defaultsApplied=useRef('');
  const [camera,setCamera]=useState('AXON'),[directionOpen,setDirectionOpen]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[webgl,setWebgl]=useState(true);
  const [cameraMoved,setCameraMoved]=useState(false);
  const [preview,setPreview]=useState<Preview|null>(null),[command,setCommand]=useState<unknown>(null),[inputs,setInputs]=useState<Record<string,string>>({});
  const [history,setHistory]=useState<{revision:number;created_at:string}[]>([]),[undo,setUndo]=useState<number[]>([]),[redo,setRedo]=useState<number[]>([]),[restoreTarget,setRestoreTarget]=useState('');
  const [draft,setDraft]=useState('PLAN'),[source,setSource]=useState(false);
  const host=useRef<HTMLDivElement>(null),viewer=useRef<KitchenViewer|null>(null),file=useRef<HTMLInputElement>(null);
  const shown=preview?.scene||scene;
  const object=shown?.objects.find(o=>o.id===options.selected);
  const updateOption=<K extends keyof ViewOptions>(key:K,value:ViewOptions[K])=>setOptions(o=>({...o,[key]:value}));
  function chooseCamera(id:string,fit?:boolean){
    setCamera(id);setCameraMoved(false);setDirectionOpen(false);viewer.current?.preset(id,fit);
    const preset=shown&&resolveCameraPreset(shown,id);
    if(preset?.draftView)setDraft(preset.draftView);
    else if(shown&&id in shown.views)setDraft(id);
  }
  async function load(){
    const meta=await api<{name:string;status:string}>('');setMetadata(meta);
    if(meta.status==='awaiting-model')return;
    const next=await api<SpatialScene>('/scene');
    if(next.project_key!==projectKey || (variant && next.variant!==variant))throw new Error('Project identity/variant mismatch; refused to display another project.');
    setDraft(d=>d in next.views?d:Object.keys(next.views)[0]);
    setPreview(null);setCommand(null);
    const initial=defaultsApplied.current===next.project.id?{}:next.project.viewer_defaults;
    defaultsApplied.current=next.project.id;
    setOptions(o=>({...o,...initial,selected:next.objects.some(x=>x.id===o.selected)?o.selected:(next.default_selection||next.project.root.id)}));
    if(next.dimensions.some(d=>!d.structural_a||!d.structural_b))throw new Error('An older backend is still running. Use launchers/Start-Workbench.cmd to start the current compiled application. / 旧后端仍在运行，请关闭旧本地服务后重新启动。');
    setScene(next);setHistory(await api('/history'));
  }
  useEffect(()=>{void load().catch(e=>setError(String(e)));},[]);
  useEffect(()=>{
    if(!scene||!host.current||viewer.current)return;
    try{const v=new KitchenViewer(host.current,scene,id=>setOptions(o=>({...o,selected:id})));v.onOrbit=()=>setCameraMoved(true);viewer.current=v;setWebgl(true);}
    catch(e){setWebgl(false);setNotice(`3D initialization failed. Linked drafts remain available. / 三维初始化失败，仍可使用二维草稿。 ${String(e)}`);console.warn(e);}
    return ()=>{viewer.current?.dispose();viewer.current=null;};
  },[!!scene]);
  useEffect(()=>{if(shown)viewer.current?.setData(shown);},[shown]);
  useEffect(()=>viewer.current?.setOptions(options),[options,shown]);
  useEffect(()=>{
    if(!scene||!object)return;
    const values:Record<string,string>={name:object.name,description:object.description,material:object.material};
    for(const [field,param] of Object.entries(object.editable)){
      const v=scene.resolved[param];values[field]=['rotation'].includes(field)?String(v):options.unit==='mm'?String(Math.round(v*1000)/1000):String(Math.round(v/25.4*1000000)/1000000);
    }
    setInputs(values);setPreview(null);setCommand(null);
  },[scene,options.selected,options.unit]);
  async function run(action:()=>Promise<void>){setBusy(true);setError('');try{await action();}catch(e){setError(String(e));}finally{setBusy(false);}}
  function changed(){
    if(!scene||!object)return [];
    const result:Change[]=[];
    for(const field of ['name','description','material',...Object.keys(object.editable)]){
      const text=inputs[field]??'';
      if(['name','description','material'].includes(field)){
        if(text!==object[field as 'name'|'description'|'material'])result.push({object_id:object.id,field,value:text});
      }else{
        const v=field==='rotation'?Number(text):readValue(text,options.unit);
        if(v===null||!Number.isFinite(v))throw new Error(`Invalid ${field}; use mm, decimal inches, a fraction or feet/inches.`);
        if(Math.abs(v-scene.resolved[object.editable[field]])>.0001)result.push({object_id:object.id,field,value:v});
      }
    }
    return result;
  }
  async function makePreview(){
    if(!scene)return;const changes=changed();if(!changes.length)throw new Error('No values changed. / 数值尚未改变。');
    const c={expected_revision:scene.project.revision,changes};const p=await api<Preview>('/preview',c);setCommand(c);setPreview(p);
  }
  async function apply(){
    if(!scene||!preview)return;const old=scene.project.revision;
    const r=await api<{scene:SpatialScene}>('/commit',{...(command as object),preview_hash:preview.preview_hash});
    setUndo(u=>[...u,old]);setRedo([]);setScene(r.scene);setPreview(null);setCommand(null);setHistory(await api('/history'));setNotice(`Saved locally as R${r.scene.project.revision}. / 已保存本地版本。`);
  }
  async function restore(target:number,kind:'undo'|'redo'|'history'){
    if(!scene)return;const current=scene.project.revision;
    const r=await api<SpatialScene>('/restore',{expected_revision:current,target_revision:target});
    if(kind==='undo'){setUndo(u=>u.slice(0,-1));setRedo(r=>[...r,current]);}
    else if(kind==='redo'){setRedo(r=>r.slice(0,-1));setUndo(u=>[...u,current]);}
    else{setUndo(u=>[...u,current]);setRedo([]);}
    setScene(r);setPreview(null);setHistory(await api('/history'));setNotice(`Restored R${target} into new R${r.project.revision}; history preserved. / 恢复为新版本，历史保留。`);
  }
  async function exportHTML(){
    if(!scene)return;
    const res=await fetch('/api/spatial/portable-runtime');if(!res.ok)throw new Error('Offline viewer bundle missing. Use the explicit rebuild command; normal startup never installs or builds packages.');
    const runtime=await res.text();const portable=structuredClone(scene);delete portable.project.source.path;
    const json=JSON.stringify(portable).replaceAll('<','\\u003c');
    const title=scene.project.name.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
    const html=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>${title} - read-only 3D</title><style>html,body{margin:0;height:100%;font-family:system-ui,sans-serif;background:#f4f3ef;color:#233039}*{box-sizing:border-box}button,select{font:inherit;padding:8px;border:1px solid #c4c8c9;background:white;border-radius:5px}header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px;background:#21343b;color:white}header small{opacity:.75}nav{display:flex;gap:6px;flex-wrap:wrap;padding:8px}#viewer{position:relative;width:100%;height:calc(100dvh - 165px);min-height:260px;overflow:hidden}.sp-labels{position:absolute;inset:0;pointer-events:none}.sp-label{position:absolute;transform:translate(-50%,-50%);background:#ffffffdd;border-radius:3px;padding:3px 6px;font-size:12px;white-space:nowrap;max-width:240px;overflow:hidden;text-overflow:ellipsis}.dimension{color:#2563eb}.inferred{background:#fff1a6}.view-reference{font-size:11px;border:1px solid #607c89}.description{color:#233039}#note{padding:6px 12px;font-size:12px;color:#53626b}#fallback{padding:15px}#fallback svg{width:100%;max-height:70vh}</style><header><b>${title} · R${scene.project.revision}</b><span>View only / 仅查看</span><small>Drag to orbit · pinch to zoom / 拖动旋转，双指缩放</small></header><nav id="controls"></nav><div id="viewer"></div><div id="fallback" hidden></div><div id="note">Customer-confirmation draft, not fabrication CAD. Yellow = inferred dimension. / 客户确认草稿，非加工 CAD；黄底为推断尺寸。</div><script id="a200-scene" type="application/json">${json}</script><script>${runtime.replaceAll('</script','<\\/script')}</script></html>`;
    const responsiveCSS='.direction-wrap{position:relative;display:inline-block}.direction-menu{position:absolute;z-index:30;top:calc(100% + 4px);left:0;min-width:350px;padding:8px;background:#fff;border:1px solid #b9c6c3;border-radius:5px;box-shadow:0 7px 24px #1b353b2b;color:#233039}.direction-menu section+section{border-top:1px solid #e0e5e2;margin-top:7px;padding-top:7px}.direction-menu b{display:block;font-size:10px;color:#456a67;margin-bottom:4px}.direction-menu section>div{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px}.direction-menu button{padding:6px 3px;font-size:10px;white-space:normal}.direction-menu button:hover{background:#e9efed}body{display:flex;flex-direction:column;min-height:100dvh;height:100dvh;overflow:hidden}header,nav,#note{flex:none}nav{font-size:12px}nav label{display:flex;align-items:center;gap:3px}nav input{margin:0}#viewer{flex:1;height:auto;min-height:180px}#fallback{flex:1;overflow:auto;min-height:0}#note{font-size:11px}@media(max-width:600px){header{font-size:13px;padding:9px;gap:6px}header small{font-size:10px}nav{font-size:11px;padding:7px;gap:7px}nav button,nav select{padding:6px;font-size:11px}.direction-menu{position:fixed;left:7px;right:7px;top:112px;min-width:0}.direction-menu section>div{grid-template-columns:repeat(2,minmax(0,1fr))}#note{font-size:10px;line-height:1.4}}';
    saveFile(`${projectKey}-3D-view-only-R${scene.project.revision}.html`,html.replace('</style>',responsiveCSS+'</style>'),'text/html');setNotice('HTML exported: view-only, self-contained, no server/CDN/login. Share the actual file, not a screenshot. / 已导出离线只读 HTML，请分享文件。');
  }
  function exportImage(){
    const canvas=host.current?.querySelector('canvas');if(!canvas)return;
    exportCanvasImage(canvas,`${projectKey}-${camera}-3D.png`);
    setNotice('PNG exported: current 3D geometry and opening marks; HTML/SVG labels are separate. / 已导出当前三维实体及开启标记 PNG；HTML／SVG 标签另存。');
  }
  async function importFile(f:File){
    if(!scene)return;if(f.size>10*1024*1024)throw new Error('JSON file exceeds 10 MB');
    const project=JSON.parse(await f.text());const c={expected_revision:scene.project.revision,project};const p=await api<Preview>('/preview',c);setCommand(c);setPreview(p);
  }
  async function copyRequest(){
    if(!scene||!object)return;
    const text=`${projectKey} 3D edit request / 修改请求\nProject: ${scene.project.id}\nRevision: ${scene.project.revision}\nObject: ${object.id}\nName: ${object.name}\nProperties (mm/degrees): ${JSON.stringify(Object.fromEntries(Object.entries(object.editable).map(([f,p])=>[f,scene.resolved[p]])))}\nRequested change / 希望修改：`;
    try{await navigator.clipboard.writeText(text);setNotice('Edit request copied. Paste it into this chat and describe the change. / 修改请求已复制，可粘贴至聊天。');}
    catch{setNotice(text);}
  }
  if(!shown)return <div className="sp-loading"><h1>{metadata?.name||projectKey}</h1><p><a href="/">← Projects / 项目列表</a></p>{metadata?.status==='awaiting-model'?<p>Empty isolated project. Place originals in its source folder; a separately reviewed model is required. No A200 geometry or paid analysis.<br/>独立空白项目：请放入客户原图，单独重建并审查模型。未复制 A200 几何，未执行付费分析。</p>:error?<p role="alert">{error}</p>:<p>Loading local project / 读取本地项目…</p>}<button onClick={()=>void run(load)}>Retry / 重试</button></div>;
  const context=viewContext(shown,camera),feedback=dimensionFeedback(shown,context.annotationView,options,context.geometryView);
  const fallbackView=camera==='AXON'?'PLAN':camera;
  return <div className="sp-app">
    <header className="sp-header"><div><span className="sp-eyebrow">VANCOUVER WOOD CARVING · {projectKey}{variant?` · ${variant}`:''}</span><h1>Project spatial workspace <small>项目三维工作区</small></h1></div><div className="sp-save-status">R{scene?.project.revision} · {preview?'UNSAVED PREVIEW / 未保存预览':'LOCAL / 本地保存'}<small>Customer-confirmation draft / 客户确认草稿</small></div><a href="/">Projects / 项目列表 ↗</a></header>
    <div className="sp-actionbar"><button disabled={busy||!undo.length||!!preview} onClick={()=>void run(()=>restore(undo.at(-1)!,'undo'))}>↶ Undo / 撤销</button><button disabled={busy||!redo.length||!!preview} onClick={()=>void run(()=>restore(redo.at(-1)!,'redo'))}>↷ Redo / 重做</button><button onClick={()=>void run(load)} disabled={busy}>Reload / 重载</button><span className="sp-separator"/><button onClick={()=>scene&&saveFile(`${projectKey}-project-R${scene.project.revision}.json`,JSON.stringify(scene.project,null,2),'application/json')}>Export project JSON</button><button onClick={()=>file.current?.click()} disabled={busy}>Import JSON</button><input ref={file} type="file" hidden accept=".json,application/json" onChange={e=>{const f=e.target.files?.[0];if(f)void run(()=>importFile(f));e.target.value='';}}/><button className="sp-primary" disabled={busy||!!preview} onClick={()=>void run(exportHTML)}>Export 3D HTML / 导出只读 HTML</button></div>
    <div className="sp-source-status" style={{padding:'4px 14px',fontSize:12,background:'#fff5dd'}}><button onClick={exportImage} disabled={!webgl}>Export view PNG / 导出视图 PNG</button> {metadata?.name} · {shown.project.pending.length} pending source notes / 项原图待核实；see Inference & pending / 请查看推断与待核实。</div>
    {(error||notice)&&<div className={error?'sp-message error':'sp-message'} role={error?'alert':'status'}>{error||notice}<button onClick={()=>{setError('');setNotice('');}}>×</button></div>}
    <div className="sp-layout">
      <aside className="sp-tree"><h2>Objects / 构件</h2><p>Select a model part or tree item.<br/>点击模型或构件树。</p><ul><NodeTree node={shown.project.root} selected={options.selected} onSelect={id=>{setPreview(null);setOptions(o=>({...o,selected:id}));}}/></ul><details><summary>Revision history / 版本历史 ({history.length})</summary><select aria-label="Historical revision" value={restoreTarget} onChange={e=>setRestoreTarget(e.target.value)}><option value="">Choose revision…</option>{history.map(h=><option value={h.revision} key={h.revision}>R{h.revision} · {h.created_at.slice(0,19)}</option>)}</select><button disabled={!restoreTarget||busy} onClick={()=>void run(()=>restore(Number(restoreTarget),'history'))}>Restore as new revision</button></details><details><summary>Inference & pending / 推断与待核实</summary>{shown.project.pending.map((p,i)=><p key={i}>{p}</p>)}</details></aside>
      <main className="sp-main">
        <div className="sp-camera-bar"><button className={!cameraMoved&&camera==='AXON'?'active':''} onClick={()=>chooseCamera('AXON')}>3D / 轴测</button><div className="sp-direction-wrap"><button aria-expanded={directionOpen} aria-controls="direction-menu" onClick={()=>setDirectionOpen(value=>!value)}>Orthographic quick views / 正交快视{!cameraMoved&&resolveCameraPreset(shown,camera)?` · ${resolveCameraPreset(shown,camera)!.label}`:''} ▾</button>{directionOpen&&<div id="direction-menu" className="sp-direction-menu">{directionPresetGroups(shown).map(group=><section key={group.id}><b>{group.label}</b><div>{group.items.map(item=><button key={item.id} aria-pressed={!cameraMoved&&camera===item.id} className={!cameraMoved&&camera===item.id?'active':''} onClick={()=>chooseCamera(item.id)}>{item.label}</button>)}</div></section>)}</div>}</div><label>Source views / 原图视图 <select aria-label="Source views / 原图视图" value={cameraMoved?'__FREE__':resolveCameraPreset(shown,camera)?'__QUICK__':camera} onChange={e=>chooseCamera(e.target.value)}><option value="AXON">3D / 轴测</option><option value="__QUICK__" disabled>3D quick view / 三维快视</option><option value="__FREE__" disabled>Free orbit / 自由旋转</option>{Object.keys(shown.views).map(v=><option key={v} value={v}>{v} · {shown.views[v].detail}</option>)}</select></label><button onClick={()=>viewer.current?.fit()}>Fit / 全图</button><button onClick={()=>viewer.current?.focus()}>Focus / 聚焦</button><select aria-label="Appearance / 外观" value={options.appearance} onChange={e=>updateOption('appearance',e.target.value as ViewOptions['appearance'])}><option value="outline">White faces + black outlines / 白面黑线</option><option value="material">Material colors / 材料颜色</option></select></div>
        <div className="sp-options"><label>Dimensions / 尺寸 <select aria-label="Dimension mode" value={options.dimensions} onChange={e=>updateOption('dimensions',e.target.value as ViewOptions['dimensions'])}><option value="off">Off / 关闭</option><option value="selected">Selected / 选中</option><option value="all">Assemblies / 全部组件</option><option value="inferred">Inferred / 推断</option></select></label><label title={supportedOpeningSymbols(shown).length?openingMarkTooltip:openingMarkTooltip+' '+noOpeningMarks }><input type="checkbox" aria-label={openingMarkLabel} aria-description={openingMarkTooltip} checked={options.openingMarks} disabled={!supportedOpeningSymbols(shown).length} onChange={e=>updateOption('openingMarks',e.target.checked)}/>{openingMarkLabel}{!supportedOpeningSymbols(shown).length?' (none / 无)':''}</label><label><input type="checkbox" checked={options.text} onChange={e=>updateOption('text',e.target.checked)}/>Text / 说明</label><label><input type="checkbox" checked={options.viewLabels} onChange={e=>updateOption('viewLabels',e.target.checked)}/>View labels / 视图索引</label><label><input type="checkbox" checked={options.transparentWalls} onChange={e=>updateOption('transparentWalls',e.target.checked)}/>Transparent walls / 透明墙</label><select aria-label="Units" value={options.unit} onChange={e=>updateOption('unit',e.target.value as 'in'|'mm')}><option value="in">Inches / 英寸</option><option value="mm">mm / 毫米</option></select></div>
        <div className="sp-options"><label title={options.dimensions==='off'?feedback.hint:componentSizeTooltip}><input type="checkbox" aria-label={componentSizeLabel} aria-description={options.dimensions==='off'?feedback.hint:componentSizeTooltip} disabled={options.dimensions==='off'} checked={!!options.componentSizes} onChange={e=>updateOption('componentSizes',e.target.checked)}/>{componentSizeLabel}</label><button disabled={!dimensionView(shown,options.selected)} onClick={()=>{const v=dimensionView(shown,options.selected);if(v){chooseCamera(v,true);setDraft(v);}}}>Align to dimension view / 对齐尺寸视图</button></div>
        <div className="sp-selection-status" role="status">{feedback.selection}{feedback.hint&&<> — {feedback.hint}</>}</div>
        <div ref={host} className="sp-viewport" data-testid="3d-viewport">{!webgl&&<div className="sp-webgl-fallback"><h2>WebGL unavailable / 三维不可用</h2><p>Spatial projection only, not a 3D render. / 仅空间投影，不是三维渲染。</p><div onClick={e=>{const id=(e.target as Element).closest('[data-object-id]')?.getAttribute('data-object-id');if(id)updateOption('selected',id);}} dangerouslySetInnerHTML={{__html:draftSVG(shown,fallbackView,options.selected,options.dimensions!=='off',options.unit,options.appearance,options,680,context)}}/></div>}<div className="sp-gesture">Drag: orbit · Right-drag: pan · Wheel: zoom<br/>拖动旋转 · 右键拖动平移 · 滚轮缩放</div></div>
        <div className="sp-draft-header"><b>Linked checking draft / 联动检查草稿</b><div>{Object.keys(shown.views).map(v=><button key={v} className={draft===v?'active':''} onClick={()=>setDraft(v)}>{v}</button>)}<label><input type="checkbox" checked={source} onChange={e=>setSource(e.target.checked)}/>Original PDF / 原图</label><button onClick={()=>saveFile(`${projectKey}-${draft}-spatial-draft-R${shown.project.revision}.svg`,draftSVG(shown,draft,options.selected,options.dimensions!=='off',options.unit,'outline',options),'image/svg+xml')}>Export SVG</button></div></div>
        <div className={`sp-drafts ${source?'with-source':''}`}><div onClick={e=>{const id=(e.target as Element).closest('[data-object-id]')?.getAttribute('data-object-id');if(id)updateOption('selected',id);}} dangerouslySetInnerHTML={{__html:draftSVG(shown,draft,options.selected,options.dimensions!=='off',options.unit,'outline',options)}}/>{source&&<a href={`${base}/source/${draft}${variantQuery}`} target="_blank" rel="noreferrer"><img alt={`${draft} original PDF evidence`} src={`${base}/source/${draft}${variantQuery}`}/><span>Open original source crop / 打开原图局部</span></a>}</div>
      </main>
      <aside className="sp-properties"><h2>Inspect & edit / 查看与编辑</h2>{object&&<><code className="sp-object-id">{object.id}</code><div className="sp-selection-actions"><button onClick={()=>updateOption('hidden',[...options.hidden,object.id])}>Hide / 隐藏</button><button onClick={()=>updateOption('isolate',options.isolate?'':object.id)}>{options.isolate?'Unisolate':'Isolate / 隔离'}</button><button onClick={()=>setOptions(o=>({...o,hidden:[],isolate:''}))}>Show all</button></div><button className="sp-copy" onClick={()=>void copyRequest()}>Copy edit request / 复制修改请求</button>
        <label>Name / 名称<input value={inputs.name??''} onChange={e=>{setInputs(i=>({...i,name:e.target.value}));setPreview(null);}}/></label>
        <label>Material / 材料<select value={inputs.material??object.material} onChange={e=>{setInputs(i=>({...i,material:e.target.value}));setPreview(null);}}>{Object.keys(shown.project.materials).map(m=><option key={m}>{m}</option>)}</select></label>
        <label>Description / 说明<textarea value={inputs.description??''} onChange={e=>{setInputs(i=>({...i,description:e.target.value}));setPreview(null);}}/></label>
        {Object.entries(object.editable).map(([field,p])=>{const param=shown.project.parameters[p];const isInferred=param.status==='inferred';return <label key={field} className={isInferred?'sp-inferred-field':''}>{field} ({field==='rotation'?'degrees':options.unit}) <small>{param.status}</small><input aria-label={`Edit ${field}`} value={inputs[field]??''} onChange={e=>{setInputs(i=>({...i,[field]:e.target.value}));setPreview(null);}}/><details><summary>Evidence / 依据</summary><p>{param.method}</p><p>{param.evidence.join(' · ')}</p>{param.uncertainty_mm? <p>± {param.uncertainty_mm} mm</p>:null}</details></label>;})}
        {!Object.keys(object.editable).length&&<p className="sp-hint">Geometry is derived. Select a controlling parent to change its inputs.<br/>几何由上级参数计算，请选择控制组件。</p>}
        {object.ancestors.filter(a=>shown.objects.find(o=>o.id===a)&&a!==shown.project.root.id).map(a=><button key={a} className="sp-parent" onClick={()=>updateOption('selected',a)}>Edit parent / 上级：{a}</button>)}
        <div className="sp-edit-actions"><button disabled={busy} onClick={()=>void run(makePreview)}>Preview / 预览修改</button>{preview&&<><button className="sp-primary" disabled={busy} onClick={()=>void run(apply)}>Apply & save R{(scene?.project.revision||0)+1}</button><button onClick={()=>{setPreview(null);setCommand(null);}}>Cancel / 取消</button></>}</div>
        {preview&&<div className="sp-preview-notice"><b>Unsaved preview / 未保存预览</b><p>{preview.affected.length} affected objects. Neighbour sizes are not stretched.</p><details><summary>Changed IDs</summary>{preview.affected.map(id=><code key={id}>{id}<br/></code>)}</details></div>}
        <details><summary>Resolved dimensions / 已求解尺寸</summary>{shown.dimensions.filter(d=>dimensionApplies(shown,d,object.id)).map(d=><p key={d.id}><span className={d.inferred?'sp-yellow':''}>{d.axis}: {valueText(d.value_mm,options.unit)}</span></p>)}</details>
      </>}</aside>
    </div><footer className="sp-footer">One spatial model → 3D + linked drafts · Yellow = provisional/inference-dependent · No AI calls · Not fabrication CAD / 同一空间模型联动；黄底表示暂定或依赖推断；不调用付费模型；非加工 CAD</footer>
  </div>;
}
