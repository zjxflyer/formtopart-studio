import { t } from './i18n';
import type { StudioJob } from './types';
import { useId, useState, type ReactNode } from 'react';

export type TaskControlAction = 'pause' | 'resume' | 'stop';
type Props = {
  dimension: '2D' | '3D'; job: StudioJob | null; active: boolean;
  activeDimension?: '2D' | '3D';
  controlsInBanner?: boolean;
  workingPreview?: { url: string; label: string; cycle: number };
  startDisabled: boolean; startReason?: string; controlsDisabled: boolean;
  retry2D?: boolean; resume2D?: boolean; no2DResult?: boolean; interrupted?: boolean; projectInactive?: boolean;
  draft3D?: { nextAction?: ReactNode };
  buildActions?: ReactNode;
  resultAvailable: boolean; workingAvailable: boolean; assistantDisabled: boolean;
  onStart: () => void; onControl: (action: TaskControlAction) => void;
  onResult: () => void; onWorking: () => void; onAssistant: () => void;
  options?: ReactNode; groupProgress?: ReactNode;
  compact?: { output?: ReactNode; extraActions?: ReactNode; secondaryActions?: ReactNode; nextStep?: ReactNode };
};

/** Secondary explanations live in Notices, outside the drawing viewport. */
export function workflowTaskNotes({ job, active, startReason }: Pick<Props, 'job' | 'active' | 'startReason'>) {
  const notes: string[] = [];
  if (active && job?.status === 'pausing') notes.push(t('The current AI request may finish before the task pauses. Saved work and completed results are retained.', '当前AI请求可能会先完成，然后任务才会暂停。已保存设计和已完成成果会保留。'));
  if (active && job?.status === 'paused') notes.push(t('Resume continues this same task and its existing allowance while the app stays open. Exiting the app interrupts the task; saved work remains.', '应用保持运行时，恢复会继续同一任务及其现有额度。退出应用会中断任务，但已保存设计会保留。'));
  if (!active && startReason) notes.push(startReason);
  if (active) notes.push(t('You can inspect saved or available working results and prepare feedback while the task runs.', '任务运行时，可以查看已保存或已产生的工作成果，并准备反馈。'));
  return notes;
}

export function TaskControls({ status, disabled, onControl, hidePausingButton = false }: {
  status?: StudioJob['status']; disabled: boolean; onControl: (action: TaskControlAction) => void; hidePausingButton?: boolean;
}) {
  const paused = status === 'paused', pausing = status === 'pausing';
  return <>
    {paused ? <button type="button" className="secondary" disabled={disabled} onClick={() => onControl('resume')}>{t('Resume task', '恢复任务')}</button>
      : (!pausing || !hidePausingButton) && <button type="button" className="secondary" disabled={disabled || pausing}
        onClick={() => onControl('pause')}>{pausing ? t('Pausing…', '正在暂停…') : t('Pause task', '暂停任务')}</button>}
    {pausing && <button type="button" className="secondary" disabled={disabled} onClick={() => onControl('resume')}>{t('Continue task', '继续任务')}</button>}
    <button type="button" className="secondary" disabled={disabled} onClick={() => onControl('stop')}>{t('Stop task', '停止任务')}</button>
  </>;
}

function CompactTaskPanel({ dimension, heading, status, startAction, activeActions, compact, children }: {
  dimension: Props['dimension']; heading: ReactNode; status: ReactNode; startAction: ReactNode;
  activeActions: ReactNode; compact: NonNullable<Props['compact']>; children: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  return <section className="workflow-run-panel workflow-run-panel-compact" aria-label={t(`${dimension} task controls`, `${dimension === '2D' ? '二维' : '三维'}任务控制`)}>
    <div className="workflow-run-row">
      {startAction}{status}{activeActions}{compact.output}
      <button type="button" className="subtle workflow-run-details-toggle" aria-expanded={expanded} aria-controls={detailsId}
        onClick={() => setExpanded(open => !open)}>
        <span aria-hidden="true">{expanded ? '▾' : '▸'}</span> {t(`${dimension} task details`, `${dimension === '2D' ? '二维' : '三维'}任务详情`)}
      </button>
      {compact.extraActions}
      {compact.nextStep && <div className="workflow-create-actions workflow-run-next">{compact.nextStep}</div>}
    </div>
    <div className="workflow-run-expanded" id={detailsId} hidden={!expanded}>
      {heading}{compact.secondaryActions}{children}
    </div>
  </section>;
}

/** One explicit run surface; none of its rendering or navigation dispatches AI. */
export function WorkflowRunPanel(props: Props) {
  const { dimension, job, active, compact } = props;
  const workingPreview = dimension === '3D' ? props.workingPreview : undefined;
  const status = active ? job?.status || 'queued' : job?.status;
  const paused = status === 'paused', pausing = status === 'pausing';
  const completedDraft = props.draft3D && (status === 'ready' || status === 'needs_review');
  const label = status === 'queued' ? t('Waiting to start', '等待开始')
    : status === 'running' ? t('Running', '运行中')
    : pausing ? t('Pausing after the current request', '当前请求完成后暂停')
    : paused ? t('Paused', '已暂停')
    : props.interrupted ? t('Task interrupted', '任务已中断')
    : job?.editable_design_revision ? t('3D model saved', '三维模型已保存')
    : dimension === '2D' && !active && props.no2DResult ? t('No drawings generated', '未生成图纸')
    : completedDraft && job?.workflow_3d?.status === 'draft_ready' ? t('3D checks complete', '三维检查完成')
    : status === 'ready' ? job?.groups_2d?.length ? t('Drawing group previews available', '分组图纸预览可用') : t('Result ready for review', '结果已就绪，请审阅')
    : status === 'needs_review' ? props.draft3D && job?.working_result?.views.length ? t('3D draft needs review', '三维草稿需要审阅') : job?.groups_2d?.length ? t('Some drawing groups need review', '部分图纸分组需要审阅') : t('Result needs review', '结果仍需审阅')
    : status === 'cancelled' ? t('Task stopped', '任务已停止')
    : status === 'failed' ? t('Task ended with an issue', '任务遇到问题，已结束')
    : props.startDisabled && props.startReason ? t('Start unavailable', '暂不能开始') : t('Ready to start', '可以开始');
  const statusBadge = <span role="status" className={`task-state ${status || 'idle'}`}>{label}</span>;
  const heading = <div className="workflow-run-heading"><strong>{t(`${active ? props.activeDimension || dimension : dimension} AI task`, `${active ? props.activeDimension || dimension : dimension} AI任务`)}</strong>{statusBadge}</div>;
  const controlsInBanner = active && props.controlsInBanner;
  const startAction = controlsInBanner ? null : props.buildActions ?? <button type="button" className="primary" disabled={active || props.startDisabled}
    title={props.startDisabled ? props.startReason : undefined} onClick={props.onStart}>
    {dimension === '2D' && props.resume2D ? t('Resume 2D from checkpoint', '从检查点恢复二维任务') : dimension === '2D' && props.retry2D ? t('Retry 2D', '重试二维') : t(`Build ${dimension}`, `构建${dimension}`)}
  </button>;
  const activeActions = active && !props.projectInactive && !controlsInBanner
    && <TaskControls status={status} disabled={props.controlsDisabled} onControl={props.onControl} />;
  const controls = <>
    <div className="workflow-run-actions">
      {!compact && startAction}
      {props.draft3D?.nextAction}
      {!compact && activeActions}
      {props.workingAvailable && !workingPreview && <button type="button" className="secondary" onClick={() => props.onWorking()}>{t('View working output', '查看工作成果')}</button>}
      {props.resultAvailable && <button className="subtle" onClick={props.onResult}>{active ? t('View saved result', '查看已保存成果') : t('View result', '查看成果')}</button>}
      {!props.draft3D && <button className="subtle" disabled={props.assistantDisabled} onClick={props.onAssistant}>{t('Ask AI about the result', '与AI讨论成果')}</button>}
    </div>
    {workingPreview && <button type="button" className="working-preview-thumbnail" onClick={() => props.onWorking()} aria-label={t('View working output', '查看工作成果')}><img src={workingPreview.url} alt={workingPreview.label} /><span>{t(`Working output · Cycle ${workingPreview.cycle}`, `工作成果 · 第${workingPreview.cycle}轮`)}<small>{t('Not applied', '尚未应用')}</small></span></button>}
    {props.options && <div className="workflow-run-options">{props.options}</div>}
    {props.groupProgress}
  </>;
  if (compact) return <CompactTaskPanel key={dimension} dimension={dimension} heading={active ? null : heading}
    status={active && !controlsInBanner ? statusBadge : null} startAction={startAction} activeActions={activeActions} compact={compact}>{controls}</CompactTaskPanel>;
  return <section className="workflow-run-panel" aria-label={t(`${dimension} task controls`, `${dimension}任务控制`)}>
    {!controlsInBanner && heading}
    {controls}
  </section>;
}
