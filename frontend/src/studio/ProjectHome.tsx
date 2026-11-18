import { t } from './i18n';
import type { ProjectSummary, ShowcaseManifest } from './types';

export function ProjectHome({ projects, showcase, busy, onShowcase, onOpen, onNew, onImport, onRename, onDelete }: {
  projects: ProjectSummary[]; showcase: ShowcaseManifest | null; busy: boolean;
  onShowcase: () => void; onOpen: (id: string) => void; onNew: () => void; onImport: () => void;
  onRename: (project: ProjectSummary, opener: HTMLButtonElement) => void;
  onDelete: (project: ProjectSummary) => void;
}) {
  return <main className="project-home">
    <section className="showcase-hero">
      <div className="showcase-hero-copy"><span className="eyebrow">FormToPart Studio · Design · Materials · BOM</span>
        <h1>{t('A considered space.', '让空间，经过推敲。')}<br /><em>{t('Every detail connected.', '让细节，彼此相连。')}</em></h1>
        <p>{t('Start with customer drawings. Review the plans, explore the design in 3D, choose materials, and export the cabinet cutting list.', '从客户图纸开始，审阅平面、探索三维设计、选择材料并导出柜体开料清单。')}</p>
        <div className="showcase-hero-actions"><button className="primary" disabled={busy} onClick={projects.length ? onShowcase : onNew}>{projects.length ? t('Open project', '打开项目') : t('New project', '新建项目')} <span aria-hidden="true">↗</span></button><button className="secondary" disabled={busy} onClick={projects.length ? onNew : onImport}>{projects.length ? t('New project', '新建项目') : t('Open project archive', '打开项目归档')}</button></div>
        <div className="showcase-capabilities"><span>{t('Plans & elevations', '平面与立面')}</span><span>{t('Interactive 3D', '交互三维')}</span><span>{t('Materials & Excel BOM', '材料与Excel BOM')}</span></div>
        <small className="showcase-offline-note">{t('PDF drawings · 3D design · Excel cutting list', 'PDF图纸 · 三维设计 · Excel开料清单')}</small>
      </div>
      <div className="showcase-hero-art" aria-hidden="true">
        {typeof showcase?.hero_image_url === 'string' ? <img src={showcase.hero_image_url} style={{ transform: `rotate(${Number(showcase.hero_rotation) || 0}deg)` }} alt="" /> : <svg viewBox="0 0 600 410" fill="none"><defs><linearGradient id="oak" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#e2c7a2"/><stop offset="1" stopColor="#a98865"/></linearGradient><linearGradient id="stone" x1="0" y1="0" x2="1" y2="1"><stop stopColor="#f6f2e9"/><stop offset="1" stopColor="#d7d5ca"/></linearGradient></defs><path d="M60 155 310 45l225 112-249 116z" fill="#e7e7dc"/><path d="M60 155v133l226 115V273z" fill="url(#oak)"/><path d="m286 273 249-116v132L286 403z" fill="#b59772"/><path d="m45 146 265-117 240 119-264 124z" fill="url(#stone)"/><path d="M45 146v13l241 122 264-124v-9L286 272z" fill="#c8c7bb"/><path d="M118 185v132m56-104v132m57-103v131M304 282l211-98v97L304 380z" stroke="#705d46" strokeOpacity=".4"/><path d="m322 288 174-81m-174 112 174-82m-174 113 174-82" stroke="#725e45" strokeOpacity=".45"/><path d="m320 148 49-22 58 28-51 24z" fill="#a5a69c"/><path d="M376 159v-38c0-18 27-22 27-4v9" stroke="#494c45" strokeWidth="7" strokeLinecap="round"/><path d="M80 335 270 430M324 421l191-90" stroke="#c7ccbe"/><circle cx="488" cy="66" r="44" fill="#e5e9dc"/><path d="M475 88V47m0 24 23-13m-23 0-14-8" stroke="#87977e" strokeWidth="3"/></svg>}
        <div className="hero-materials"><span style={{ background: '#c5a17a' }} /><span style={{ background: '#efede5' }} /><span style={{ background: '#536256' }} /><small>OAK · STONE · SAGE</small></div>
      </div>
    </section>
    <section className="project-library"><div className="project-library-heading"><div><span className="eyebrow">{t('YOUR WORKSPACE', '你的工作空间')}</span><h2>{t('Projects', '项目')}</h2></div><button className="subtle" disabled={busy} onClick={onImport}>{t('Open project archive', '打开项目归档')} ↗</button></div>
      {!projects.length ? <div className="project-library-empty"><p>{t('Your saved projects will appear here.', '保存的项目会显示在这里。')}</p><span>{t('Create a project or open an archive to begin.', '创建项目或打开归档，即可开始。')}</span></div> : <div className="project-card-grid">{projects.map(project => <article className="project-card" key={project.id}>
        <div className="project-card-top"><span className={`project-status ${project.lifecycle || 'active'}`}>{project.lifecycle === 'paused' ? t('Paused', '已暂停') : project.lifecycle === 'stopped' ? t('Stopped', '已停止') : t('Active', '进行中')}</span><span>R{project.revision}</span></div>
        <button className="project-card-open" disabled={busy} onClick={() => onOpen(project.id)}><strong>{project.name}</strong><span>{project.document_count} {t('source files', '个原图文件')} <b aria-hidden="true">↗</b></span></button>
        <div className="project-card-bottom">
          <span>{t('Saved locally', '本地保存')}</span>
          <div className="project-card-actions">
            <button type="button" className="subtle" disabled={busy} onClick={event => onRename(project, event.currentTarget)} aria-label={`${t('Rename project', '重命名项目')} ${project.name}`}>{t('Rename', '重命名')}</button>
            {project.can_delete !== false && <button type="button" className="subtle danger-text" disabled={busy} onClick={() => onDelete(project)} aria-label={t(`${t('Delete project', '删除项目')} ${project.name}`)}>{t('Delete', '删除')}</button>}
          </div>
        </div>
      </article>)}</div>}
    </section>
  </main>;
}
