import { t } from './i18n';
import { ArtifactPreviewLink, type StudioArtifact } from './ArtifactPreview';
import type { DrawingGroup2D, WorkingResultView } from './types';

function pageDirection(direction?: string | null) {
  switch (direction) {
    case 'page-up': return t('Up on PDF page', '朝 PDF 页面上方');
    case 'page-down': return t('Down on PDF page', '朝 PDF 页面下方');
    case 'page-left': return t('Left on PDF page', '朝 PDF 页面左侧');
    case 'page-right': return t('Right on PDF page', '朝 PDF 页面右侧');
    default: return t('Direction unresolved', '朝向待确认');
  }
}

function groupStatus(status: DrawingGroup2D['status']) {
  switch (status) {
    case 'running': return t('Drawing', '绘制中');
    case 'pausing': return t('Pausing', '正在暂停');
    case 'paused': return t('Paused', '已暂停');
    case 'ready': return t('Checks passed', '检查通过');
    case 'needs_review': return t('Needs review', '需要审阅');
    case 'failed': return t('Failed', '失败');
    case 'cancelled': return t('Stopped', '已停止');
    default: return t('Waiting', '待处理');
  }
}

export function DrawingGroupProgress({ groups, views, taskStatus, collapsible, onView, onRetry, retryDisabled, onPreview, draftGroups, onOpen3D }: {
  groups: DrawingGroup2D[];
  views: WorkingResultView[];
  taskStatus?: DrawingGroup2D['status'];
  collapsible: boolean;
  onView: (id: string) => void;
  onRetry: (id: string) => void;
  retryDisabled: boolean;
  onPreview: (artifact: StudioArtifact) => void;
  draftGroups?: ReadonlySet<string>;
  onOpen3D?: (id: string) => void;
}) {
  if (!groups.length) return null;
  const rows = groups.map(group => ({ group, previews: views.filter(view => view.group_id === group.id),
    status: group.status === 'running' && (taskStatus === 'pausing' || taskStatus === 'paused') ? taskStatus : group.status,
    draftAction: draftGroups?.has(group.id) ? t('Open 3D draft', '打开三维草稿')
      : group.can_generate_3d_draft ? t('Go to 3D', '前往三维步骤') : '',
    sheets: [...new Set(group.source_views?.filter(view => view.kind === 'elevation' && view.sheet)
      .map(view => view.sheet))].filter(sheet => sheet && !group.label.toUpperCase().includes(sheet.toUpperCase())) }));
  const groupList = <ol aria-label={t('2D drawing groups', '二维图纸分组')}>
      {rows.map(({ group, previews, sheets, status, draftAction }) => <li key={group.id}>
        <strong>{group.label}{sheets.length ? ` · ${sheets.join(', ')}` : ''}</strong>
        <span>{groupStatus(status)} · {previews.length === 1 ? t('1 preview', '1 张预览') : t(`${previews.length} previews`, `${previews.length} 张预览`)}</span>
        {group.cycles_remaining !== undefined && <span>{group.cycles_remaining === 1 ? t('1 cycle left', '剩余 1 轮')
          : t(`${group.cycles_remaining} cycles left`, `剩余 ${group.cycles_remaining} 轮`)}</span>}
        {!!previews.length && <button type="button" className="subtle" onClick={() => onView(previews[0].view_id)}
          aria-label={`${t('View group output', '查看分组成果')} ${group.label}`}>{t('View output', '查看成果')}</button>}
        {onOpen3D && draftAction && <button type="button" className="subtle" onClick={() => onOpen3D(group.id)}
          aria-label={`${draftAction} · ${group.label}`}>{draftAction}</button>}
        {group.can_retry && <button type="button" className="subtle" disabled={retryDisabled} onClick={() => onRetry(group.id)}
          aria-label={`${t('Retry group', '重试分组')} ${group.label}`}>{t('Retry group', '重试分组')}</button>}
      </li>)}
    </ol>;
  return <div className="drawing-group-progress">
    {collapsible ? <details className="drawing-group-summary">
      <summary>{t('Drawing groups', '图纸分组')}</summary>
      {groupList}
    </details> : groupList}
    <details>
      <summary>{t('Source groups', '原图分组')}</summary>
      {groups.map(group => <section key={group.id} aria-label={`${t('Source group', '原图分组')} ${group.label}`}>
        <div><strong>{group.label}</strong>
          {group.source_map_url && <ArtifactPreviewLink onPreview={onPreview} artifact={{ kind: 'image', url: group.source_map_url,
            title: `${t('Source map', '原图索引图')} · ${group.label}` }}>{t('Source map', '原图索引图')}</ArtifactPreviewLink>}
          {group.source_evidence_url && <ArtifactPreviewLink onPreview={onPreview} artifact={{ kind: 'json', url: group.source_evidence_url,
            title: `${t('Source evidence', '原图定位依据')} · ${group.label}` }}>{t('Source evidence', '原图定位依据')}</ArtifactPreviewLink>}
        </div>
        <ul>{group.source_views?.map(view => <li key={view.view_id} title={view.correspondence_note}>
          {[view.label, view.kind === 'plan' ? t('Plan', '平面图') : t('Elevation', '立面图'),
            t(`PDF page ${view.page}`, `PDF 第${view.page}页`), view.callout || view.sheet, view.kind === 'elevation' && pageDirection(view.sight_direction)].filter(Boolean).join(' · ')}
          {(view.source_name || view.region?.length) && <small className="source-view-position">
            {[view.source_name, view.region?.length && `${t('Page-relative crop', '页面相对裁切范围')} (${view.region.join(', ')})`].filter(Boolean).join(' · ')}
          </small>}
        </li>)}</ul>
        {!!group.issues?.length && <details><summary>{t('Review findings', '审阅发现')}</summary><ul>{group.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul></details>}
      </section>)}
    </details>
  </div>;
}
