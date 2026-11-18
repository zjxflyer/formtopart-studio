import { useEffect, useMemo, useRef, useState } from 'react';
import { KitchenViewer } from '../spatial/engine';
import { defaultOptions } from '../spatial/types';
import { studioAPI } from './api';
import { t } from './i18n';
import { sceneFor3D } from './sceneScope';
import type { DrawingGroup2D, StudioJob, StudioScene, WorkingResultView } from './types';
import './group-3d-draft.css';

const presets: Record<string, string> = { AXON: 'AXON', PLAN: 'PLAN-UP', FRONT: 'ORTHO-FRONT', RIGHT: 'ORTHO-RIGHT' };

function drawingGroupSheets(group: DrawingGroup2D) {
  return [...new Set(group.source_views?.flatMap(view => view.kind === 'elevation' && view.sheet ? [view.sheet] : []))];
}

export function drawingGroupName(group: DrawingGroup2D) {
  const sheets = drawingGroupSheets(group).filter(sheet => !group.label.toUpperCase().includes(sheet.toUpperCase()));
  return sheets.length ? `${sheets.join(', ')} · ${group.label}` : group.label;
}

export function draftGroupActionLabel(group: DrawingGroup2D, groups: DrawingGroup2D[], rebuild = false) {
  const sheets = drawingGroupSheets(group).join(', ');
  const sharedSheet = sheets && groups.some(other => other.id !== group.id
    && drawingGroupSheets(other).join(', ').toUpperCase() === sheets.toUpperCase());
  const target = sheets && !sharedSheet ? sheets : drawingGroupName(group);
  return rebuild ? t(`Rebuild ${target} 3D draft`, `重建 ${target} 三维草稿`) : t(`Build ${target} 3D draft`, `构建 ${target} 三维草稿`);
}

export function Group3DDraftView({ group, job, view, startLabel, startReason, startInDetails }: {
  group: DrawingGroup2D; job?: StudioJob; view?: WorkingResultView;
  startLabel: string;
  startReason?: string;
  startInDetails?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<KitchenViewer | null>(null);
  const [viewingMode, setViewingMode] = useState<'interactive' | 'rendered' | null>(null);
  const [scene, setScene] = useState<StudioScene | null>(null);
  const [frameId, setFrameId] = useState('');
  const [sourceCameraChoice, setSourceCameraChoice] = useState<{ draftViewId?: string; cameraId: string }>();
  const [error, setError] = useState('');
  const [imageFailed, setImageFailed] = useState(false);
  const interactive = viewingMode === 'interactive' || viewingMode === null && !!scene && !error;
  const active = job && ['queued', 'running', 'pausing', 'paused'].includes(job.status);
  const emptyHint = active ? t('Rendered views appear here when available.', '可用的渲染视图将显示在这里。')
    : startReason || (startInDetails ? t(`Open 3D task details and select ${startLabel}.`, `打开三维任务详情，然后选择“${startLabel}”。`)
      : job ? t(`Select ${startLabel} to try again.`, `选择“${startLabel}”即可重试。`)
      : t(`Select ${startLabel} to build from the retained 2D drawings and original PDF.`, `选择“${startLabel}”，使用保留的二维图纸和原始 PDF 创建草稿。`));
  const frames = useMemo(() => Object.values(scene?.local_frames || {}).filter(frame => frame.meshes.length), [scene]);
  const activeFrame = frameId || (!scene?.meshes.length ? frames[0]?.root_id || '' : '');
  const selectedScene = useMemo(() => sceneFor3D(scene, activeFrame), [scene, activeFrame]);
  const sourceViews = scene?.draft_3d?.source_views ?? group.source_views;
  const sourceCameras = !activeFrame || frames.find(frame => frame.root_id === activeFrame)?.orientation_known
    ? sourceViews?.filter(source => !!selectedScene?.views[source.view_id]?.direction
        && (source.kind === 'plan' || !!source.callout && !!source.sight_direction)) || [] : [];
  const sourceCamera = sourceCameraChoice && sourceCameraChoice.draftViewId === view?.view_id
    && sourceCameras.some(source => source.view_id === sourceCameraChoice.cameraId) ? sourceCameraChoice.cameraId : '';
  const camera = sourceCamera || presets[view?.view_id || ''] || 'AXON';
  const cameraRef = useRef(camera); cameraRef.current = camera;

  useEffect(() => {
    setImageFailed(false);
  }, [view?.preview_url]);
  useEffect(() => {
    if (!job?.draft_3d_scene_url || !job.id) return;
    const controller = new AbortController();
    setError('');
    void studioAPI.group3DDraftScene(job.id, controller.signal).then(value => {
      if (!controller.signal.aborted) setScene(value);
    }, () => {
      if (!controller.signal.aborted) setError(t('The interactive draft could not be opened. The rendered views are still available.', '无法打开交互草稿。仍可查看已渲染视图。'));
    });
    return () => controller.abort();
  }, [job?.id, job?.draft_3d_scene_url]);
  useEffect(() => {
    if (!interactive || !selectedScene?.meshes.length || !host.current) return;
    try {
      const instance = new KitchenViewer(host.current, selectedScene);
      instance.setOptions({ ...defaultOptions, dimensions: 'off', viewLabels: false });
      instance.preset(cameraRef.current, true);
      viewer.current = instance;
      return () => { instance.dispose(); viewer.current = null; };
    } catch {
      setError(t('The interactive draft could not be opened. The rendered views are still available.', '无法打开交互草稿。仍可查看已渲染视图。'));
    }
  }, [interactive, selectedScene]);
  useEffect(() => viewer.current?.preset(camera, true), [camera]);

  return <div className="group-3d-draft" data-content-kind="group-3d-draft">
      {(view || job?.draft_3d_scene_url) && <div className="group-3d-draft-controls" role="group" aria-label={t('Draft viewing mode', '草稿查看模式')}>
        <button type="button" className="subtle" aria-pressed={!interactive} disabled={!view} onClick={() => setViewingMode('rendered')}>{t('Rendered views', '渲染视图')}</button>
        <button type="button" className="subtle" aria-pressed={interactive} disabled={!job?.draft_3d_scene_url} onClick={() => setViewingMode('interactive')}>{t('Interactive draft', '交互草稿')}</button>
        {interactive && sourceCameras.length > 0 && <select value={sourceCamera} onChange={event => setSourceCameraChoice({ draftViewId: view?.view_id, cameraId: event.target.value })} aria-label={t('Source camera', '原图视角')}>
          <option value="">{t('Selected draft view', '选中的草稿视图')}</option>
          {sourceCameras.map(source => <option key={source.view_id} value={source.view_id}>{source.callout ? `${source.callout} · ` : ''}{source.label}</option>)}
        </select>}
        {interactive && frames.length > 0 && <select value={activeFrame} onChange={event => setFrameId(event.target.value)} aria-label={t('Draft scope', '草稿范围')}>
          {!!scene?.meshes.length && <option value="">{t('Whole group', '整个分组')}</option>}
          {frames.map(frame => <option key={frame.root_id} value={frame.root_id}>{frame.label} · {t('Local assembly', '局部构件')}</option>)}
        </select>}
        {interactive && !!selectedScene?.meshes.length && !error && <button type="button" className="subtle" onClick={() => viewer.current?.fit()}>{t('Fit', '适应窗口')}</button>}
      </div>}
      {interactive ? error ? <p role="alert">{error}</p> : <>
        {(!scene || !selectedScene?.meshes.length) && <p role="status">{scene ? t('This draft has no interactive geometry.', '此草稿没有可交互的几何体。') : t('Opening the interactive draft…', '正在打开交互草稿…')}</p>}
        <div className="group-3d-draft-model" ref={host} data-testid="3d-draft-viewport" />
      </> : view ? imageFailed ? <p role="alert">{t('This rendered view could not be opened.', '无法打开此渲染视图。')}</p>
        : <div className="group-3d-draft-image"><img src={view.preview_url} alt={t(`3D draft: ${view.label}`, `三维草稿：${view.label}`)} onError={() => setImageFailed(true)} /></div>
        : <div className="group-3d-draft-empty" role="status"><strong>{active
          ? t('Creating the 3D draft', '正在创建三维草稿')
          : t(`No 3D draft for ${drawingGroupName(group)} yet`, `${drawingGroupName(group)} 暂无三维草稿`)}</strong><p>{emptyHint}</p></div>}
    </div>;
}
