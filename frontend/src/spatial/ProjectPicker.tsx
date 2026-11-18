import { useEffect, useState } from 'react';
import './spatial.css';
type Project={key:string;name:string;status:string;model_id:string;variants?:Array<{id:string;name:string;status:string}>};
export default function ProjectPicker(){
  const [projects,setProjects]=useState<Project[]>([]),[error,setError]=useState(''),[key,setKey]=useState(''),[name,setName]=useState(''),[busy,setBusy]=useState(false);
  useEffect(()=>{fetch('/api/spatial/projects').then(async r=>{if(!r.ok)throw Error(await r.text());setProjects(await r.json());}).catch(e=>setError(String(e)));},[]);
  async function create(){
    setBusy(true);setError('');try{
      const r=await fetch('/api/spatial/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,name})});
      if(!r.ok)throw Error(await r.text());
      window.location.href=`/?workspace=3d&project=${encodeURIComponent(key)}`;
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  return <main style={{maxWidth:850,margin:'40px auto',padding:24}}><h1>Drawing workbench / 图纸工作台</h1><p>One shared program · isolated customer projects / 共享程序 · 独立客户项目</p>
    {error&&<p role="alert">{error}</p>}
    <h2>Open a project / 打开项目</h2><ul>{projects.map(p=><li key={p.key} style={{margin:'20px 0'}}><a href={`/?workspace=3d&project=${encodeURIComponent(p.key)}`}>{p.name}</a><small> · {p.status} · {p.key}</small>{p.variants?.length?<ul>{p.variants.map(v=><li key={v.id}><a href={`/?workspace=3d&project=${encodeURIComponent(p.key)}&variant=${encodeURIComponent(v.id)}`}>{v.name}</a><small> · {v.status}</small></li>)}</ul>:null}</li>)}</ul>
    <h2>New empty project / 新建空白项目</h2><p>No A200 geometry is copied. No paid analysis runs. Another customer PDF needs separate reconstruction and verification.<br/>不复制 A200 模型，不执行付费分析。另一客户的 PDF 需要单独重建与验证。</p>
    <label>Project key / 项目键 <input aria-label="Project key" value={key} onChange={e=>setKey(e.target.value)} placeholder="customer-02" pattern="[a-z0-9][a-z0-9-]{0,62}"/></label>{' '}
    <label>Name / 名称 <input aria-label="Project name" value={name} onChange={e=>setName(e.target.value)}/></label>{' '}
    <button disabled={busy||!name||!/^[a-z0-9][a-z0-9-]{0,62}$/.test(key)} onClick={()=>void create()}>Create empty project / 创建空项目</button>
    <hr/><a href="/?workspace=legacy">Legacy PDF analysis workflow / 旧版 PDF 分析流程</a><p>This separate legacy workflow may make paid calls only after an explicit Analyze action.<br/>旧流程仅在明确点击分析后才可能产生付费调用。</p>
  </main>;
}
