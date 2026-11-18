import { getLanguage, setLanguage, t, useLanguage } from './i18n';
import { ProjectHome } from './ProjectHome';
import { ShowcaseGallery } from './ShowcaseGallery';
import { StudioSheet } from './StudioSheet';
import { NoticeCenter, type StudioNotice } from './NoticeCenter';
import { PdfImportStatus, pdfImportInProgress, type PdfImportState } from './PdfImportStatus';
import { DrawingResults } from './DrawingResults';
import { DrawingGroupProgress } from './DrawingGroupProgress';
import { draftGroupActionLabel, drawingGroupName, Group3DDraftView } from './Group3DDraftView';
import { ArtifactPreview, ArtifactPreviewLink, type StudioArtifact } from './ArtifactPreview';
import { drawingResultItems, type DrawingResultItem } from './drawingResultItems';
import { KeySettings } from './KeySettings';
import { MaterialSuggestionDrawer } from './MaterialSuggestionDrawer';
import { ReferenceSourceList, ReferenceViewer } from './ReferenceDemoWorkspace';
import { useEffect, useMemo, useRef, useState, type FormEvent, type ClipboardEvent } from 'react';
import { KitchenViewer } from '../spatial/engine';
import { draftSVG } from '../spatial/drafts';
import { defaultOptions, valueText, type ViewOptions } from '../spatial/types';
import { studioAPI } from './api';
import { modelDisplayName } from './modelLabel';
import { sourceDrawing, preferredDrawingView, drawingApplyBlocked, drawingStatusText, drawingGeometryCount, drawingNotice } from './drawingState';
import { sceneFor3D, frameForObject } from './sceneScope';
import { MaterialProperties, MaterialSuggestionResults, contextForNode, isBoardPanel } from './materials';
import { MaterialLibrary } from './MaterialLibrary';
import { BoardSpecEditor } from './BoardSpecEditor';
import { BOMSheet } from './BOMSheet';
import { ProductionGuide, type ProductionAction } from './ProductionGuide';
import { Autonomous2DStatus, isUnclassified2DFallback, isUndrawn2D } from './Autonomous2DStatus';
import { ParameterCard } from './ParameterCard';
import { TaskControls, WorkflowRunPanel, workflowTaskNotes, type TaskControlAction } from './WorkflowRunPanel';
import { WorkflowBuildActions, type BuildAction } from './WorkflowBuildActions';
import './materials.css';
import './showcase.css';
import './reference-demo.css';
import './compact-workspace.css';
import type { BoardSpec, BOMReport, DrawingGroup2D, MaterialSuggestionMode, MaterialVariant, PanelSpecPreviewRow, ProjectSummary, Proposal, ReferenceDemoManifest, ShowcaseManifest, StudioHealth, StudioJob, StudioModel, StudioNode, StudioParameter, StudioProject, StudioReferenceParameter, StudioScene } from './types';

type View = '3d' | 'source' | string;
type RunningJob = { id: string; projectId: string; kind?: 'materials' | 'generate3d' | 'model-edit' };
type RenameTarget = Pick<ProjectSummary, 'id' | 'name' | 'revision'>;
const CABINET_KINDS = new Set(['cabinet', 'vanity', 'wardrobe', 'cupboard', 'base_cabinet', 'wall_cabinet', 'tall_cabinet']);
const DEFAULT_INTERIOR = { thickness_mm: 18, back_mm: 6, shelves: 2, dividers: 0, drawers: 0, clearance_mm: 2 };
const ICONS: Record<string, string> = {
  plus: 'M12 5v14M5 12h14', upload: 'M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5',
  folder: 'M3 6h6l2 3h10v11H3zM3 6V4h6l2 2', box: 'm3 7 9-5 9 5v10l-9 5-9-5V7Zm0 0 9 5 9-5M12 12v10',
  spark: 'm12 3 2.8 6.2L21 12l-6.2 2.8L12 21l-2.8-6.2L3 12l6.2-2.8L12 3Z',
  image: 'M3 3h18v18H3zM3 17l6-6 4 4 3-3 5 5M8 7h.01', close: 'm6 6 12 12M18 6 6 18',
  export: 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5', fit: 'M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6',
  undo: 'M8 4 3 9l5 5M3 9h10a7 7 0 0 1 0 14', redo: 'm16 4 5 5-5 5m5-5H11a7 7 0 0 0 0 14',
  check: 'm5 12 4 4L19 6', refresh: 'M20 8a8 8 0 1 0 1 7M20 3v5h-5', source: 'M5 3h10l4 4v14H5zM15 3v5h4M8 12h8M8 16h8',
  power: 'M12 2v10M6 5a9 9 0 1 0 12 0',
  settings: 'M10 2h4l.6 2.6 1.6.7 2.3-1.4 2.6 2.6-1.4 2.3.7 1.6L23 11v2l-2.6.6-.7 1.6 1.4 2.3-2.6 2.6-2.3-1.4-1.6.7L14 22h-4l-.6-2.6-1.6-.7-2.3 1.4-2.6-2.6 1.4-2.3-.7-1.6L1 13v-2l2.6-.6.7-1.6-1.4-2.3 2.6-2.6 2.3 1.4 1.6-.7Z M15 12a3 3 0 1 1-6 0 3 3 0 1 1 6 0Z',
  pencil: 'm4 16-1 5 5-1L21 7l-4-4L4 16Zm10-10 4 4',
};
function Icon({ name }: { name: string }) { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={ICONS[name] || ICONS.box} /></svg>; }
function saveBlob(blob: Blob, name: string) { const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1500); }
function safeName(name: string) { return name.replace(/[<>:"/\\|?*]/g, '_').slice(0, 100); }
function cleanDrawing(value: string): string {
  const document = new DOMParser().parseFromString(value, 'image/svg+xml');
  if (document.querySelector('parsererror')) return '';
  const allowed = new Set(['svg', 'g', 'rect', 'path', 'polygon', 'polyline', 'line', 'text', 'tspan', 'circle', 'ellipse', 'defs', 'marker', 'pattern', 'clippath']);
  for (const element of Array.from(document.querySelectorAll('*'))) {
    if (!allowed.has(element.localName.toLowerCase())) { element.remove(); continue; }
    for (const attribute of Array.from(element.attributes)) {
      if (/^on/i.test(attribute.name) || /^(xlink:)?href$/i.test(attribute.name) || /javascript:|url\(\s*["']?(?!#)/i.test(attribute.value)) element.removeAttribute(attribute.name);
    }
  }
  return new XMLSerializer().serializeToString(document.documentElement);
}
function projectHasReferences(value?: StudioProject | ProjectSummary | null) { return !!(value?.reference_source_key || value?.reference_project); }
function runningProjectJob(project: StudioProject): RunningJob | null {
  const job = project.active_job;
  if (!job || !['queued', 'running', 'pausing', 'paused'].includes(job.status)) return null;
  const kind = job.kind === 'edit3d' ? 'model-edit' : job.kind === 'generate3d' || job.kind === 'materials' ? job.kind : undefined;
  return { id: job.id, projectId: project.id, kind };
}
function taskInterrupted(job?: StudioJob | null) {
  return job?.status === 'failed' && job.error_category === 'interrupted'
    || job?.status === 'cancelled' && job.error_category === 'project_paused';
}
function taskStoppedMessage() {
  return t('Task stopped. Saved work and available results are retained.', '任务已停止，已保存设计和已有成果均已保留。');
}
function hasDraftOutput(job?: StudioJob | null) {
  return !!job?.draft_3d_scene_url || !!job?.working_result?.views.length;
}
function draftSequenceRoomFinished(status: StudioJob['status']) {
  return status === 'ready' || status === 'needs_review';
}
function flatten(root?: StudioNode): StudioNode[] { return root ? [root, ...root.children.flatMap(flatten)] : []; }
function referenceOwnerIds(model: StudioModel, scene: StudioScene | null, controlId: string): string[] {
  const reference = scene?.reference_parameters?.[controlId];
  if (!reference) return [];
  const known = new Set(flatten(model.root).map(node => node.id));
  const owners = [reference.owner_id];
  for (const drawing of model.drawings || []) for (const annotation of drawing.reference_annotations || []) {
    if (annotation.control_id === controlId) for (const binding of annotation.provenance?.original_control_bindings || []) owners.push(binding.owner_id);
  }
  return [...new Set(owners)].filter(id => known.has(id));
}
function dateText(value: string) { const d = new Date(value); return Number.isNaN(d.valueOf()) ? value : d.toLocaleString(getLanguage() === 'en' ? 'en-CA' : 'zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
function phaseLabel(phase?: string) {
  const labels: Record<string, string> = {
    queued: t('任务排队中 · Waiting to start'),
    reading_materials: t('Reading the material library', '正在读取材料库'),
    reading_material_sources: t('Reading finish notes from the PDF', '正在读取PDF饰面说明'),
    receiving_materials: t('Receiving material suggestions', '正在接收材料建议'),
    receiving_material_suggestions: t('Receiving material suggestions', '正在接收材料建议'),
    choosing_materials: t('Waiting for AI material suggestions', '正在等待AI材料建议'),
    matching_materials: t('Matching finishes to your library', '正在匹配材料库中的饰面'),
    validating_materials: t('Checking material compatibility', '正在检查材料兼容性'),
    preparing_material_preview: t('Preparing the material preview', '正在准备材料预览'),
    preparing_3d_sources: t('Preparing the saved 2D and original PDF', '正在准备已保存二维与原始PDF'),
    creating_3d: t('Creating the 3D design', '正在创建三维设计'),
    rendering_3d: t('Rendering the plain 3D views', '正在渲染素模三维视图'),
    checking_3d: t('Checking 3D against your drawings', '正在对照图纸检查三维'),
    '3d_ready': t('3D preview ready for your review', '三维预览已就绪，请审阅'),
    '3d_needs_review': t('3D needs further review', '三维仍需审阅'),
    reading_sources: t('正在读取客户原图 · Reading customer drawings'),
    mapping_sources: t('正在对应图页与视图 · Matching sheets and views'),
    mapping_drawing_groups: t('Mapping drawing groups from the original PDF', '正在根据原始 PDF 对应图纸分组'),
    resuming_2d: t('Resuming 2D from a saved checkpoint', '正在从已保存的检查点恢复二维任务'),
    source_index_reused: t('读取已保存的视图索引 · Reusing the saved view map'),
    generating_model: t('正在构建设计模型 · Building the design model'),
    receiving_model: t('正在接收模型结果 · Receiving the model'),
    validating: t('正在检查尺寸与结构 · Checking dimensions and structure'),
    drafting_sources: t('正在绘制原图视图 · Drafting source views'),
    extracting_drawings: t('正在提取原图线条与标注 · Extracting source lines and annotations'),
    rendering_drawings: t('正在生成图纸文件 · Rendering drawings'),
    checking_drawings: t('正在对照原图审查 · Checking drawings against sources'),
    repairing_drawings: t('正在修复图纸问题 · Repairing drawing issues'),
    extracting_evidence: t('Reading dimensions and object relationships', '正在读取尺寸和构件关系'),
    extracting_source_facts: t('Reading dimensions and object relationships', '正在读取尺寸和构件关系'),
    extracting_native_vectors: t('Reading original vector geometry', '正在读取原始矢量几何'),
    classifying_source_groups: t('Separating appearance texture from physical details', '正在区分外观纹理与实体细节'),
    grouping_native: t('Grouping source geometry for drawing', '正在分组源图几何'),
    classifying_groups: t('Separating appearance texture from physical details', '正在区分外观纹理与实体细节'),
    checking_exports: t('Checking the saved drawing files', '正在检查已保存的图纸文件'),
    refining_groups: t('Resolving mixed source details', '正在细分混合的源图细节'),
    checking_source_scope: t('Checking the requested room and drawing areas', '正在检查指定房间及图纸范围'),
    refining_source_scope: t('Refining the source drawing areas', '正在调整源图范围'),
    grouping_native_sources: t('Grouping the original drawing details', '正在分组原图细节'),
    refining_source_groups: t('Resolving mixed source details', '正在细分混合的源图细节'),
    rendering_source_drawings: t('Saving the drawing files', '正在保存图纸文件'),
    resolving_customer_references: t('Calculating reference dimensions', '正在计算参考尺寸'),
    review: t('等待核对图纸 · Review drawings'),
  };
  if (!phase) return t('正在处理设计 · Processing your design');
  return labels[phase] || (/^[a-z0-9_]+$/.test(phase) ? t('正在处理设计 · Processing your design') : phase);
}
function sceneWithPlan(scene: StudioScene): StudioScene {
  return { ...scene, views: { PLAN: { direction: [0, 0, -1], right: [1, 0, 0], up: [0, 1, 0], detail: t('Plan / 平面') }, ...scene.views } };
}
function Tree({ node, selected, onSelect, depth = 0 }: { node: StudioNode; selected: string; onSelect: (id: string) => void; depth?: number }) {
  const [expanded, setExpanded] = useState(depth < 2);
  return <li><div className={`tree-row ${selected === node.id ? 'selected' : ''}`}>
    <button className="tree-toggle" aria-label={`${expanded ? t('Collapse', '收起') : t('Expand', '展开')} ${t(node.name)}`} onClick={() => setExpanded(!expanded)} disabled={!node.children.length}>{node.children.length ? expanded ? '⌄' : '›' : '·'}</button>
    <button className="tree-name" onClick={() => onSelect(node.id)} title={depth === 0 ? node.name : node.id}><span>{t(node.name)}</span><small className="node-kind">{node.authority === 'designed' ? t('设计 · ') : ''}{node.kind}</small></button>
  </div>{expanded && node.children.length > 0 && <ul>{node.children.map(child => <Tree key={child.id} node={child} selected={selected} onSelect={onSelect} depth={depth + 1} />)}</ul>}</li>;
}
export default function StudioApp() {
  const language = useLanguage();
  const [showcase, setShowcase] = useState<ShowcaseManifest | null>(null);
  const [reference, setReference] = useState<ReferenceDemoManifest | null>(null);
  const [referenceSectionId, setReferenceSectionId] = useState('A200');
  const [referenceViewId, setReferenceViewId] = useState('plan');
  const [referenceContent, setReferenceContent] = useState<'source' | 'current'>('source');
  const [assistantRequested, setAssistantRequested] = useState(false);
  const [materialSuggestionsOpen, setMaterialSuggestionsOpen] = useState(false);
  const [materialInstruction, setMaterialInstruction] = useState('');
  const [replaceMaterials, setReplaceMaterials] = useState(false);
  const [materialScope, setMaterialScope] = useState<'selection' | 'project'>('project');
  const [presentation, setPresentation] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ProjectSummary | null>(null);
  const [stopDialog, setStopDialog] = useState(false);
  const [keySettingsOpen, setKeySettingsOpen] = useState(false);
  useEffect(() => { document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN'; }, [language]);
  const [health, setHealth] = useState<StudioHealth | null>(null); const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [closed, setClosed] = useState(false);
  const [project, setProject] = useState<StudioProject | null>(null); const [scene, setScene] = useState<StudioScene | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null); const [busy, setBusy] = useState('');
  const [pdfImport, setPdfImport] = useState<PdfImportState | null>(null);
  const importingPDF = pdfImportInProgress(pdfImport);
  const visiblePdfImport = pdfImport && (importingPDF || pdfImport.projectId === project?.id) ? pdfImport : null;
  const [error, setError] = useState(''); const [notice, setNotice] = useState('');
  const [noticeRequest, setNoticeRequest] = useState(0);
  const openNotices = () => setNoticeRequest(value => value + 1);
  const [view, setView] = useState<View>('source'); const [stage, setStage] = useState(1); const [leftTab, setLeftTab] = useState<'source' | 'tree'>('source');
  const [options, setOptions] = useState<ViewOptions>({ ...defaultOptions, hidden: [], unit: 'mm', componentSizes: true, viewLabels: false });
  const [openingMarks2D, setOpeningMarks2D] = useState(true);
  const [camera, setCamera] = useState('AXON'); const [inside, setInside] = useState(false); const [webglError, setWebglError] = useState('');
  const [localFrameId, setLocalFrameId] = useState('');
  const [pageKey, setPageKey] = useState(''); const [zoom, setZoom] = useState(1);
  const [viewportSize, setViewportSize] = useState({ width: 900, height: 650 });
  const [sourceImageSize, setSourceImageSize] = useState<{ width: number; height: number } | null>(null);
  const [newProjectOpen, setNewProjectOpen] = useState(false); const [newName, setNewName] = useState('');
  const [renameTarget, setRenameTarget] = useState<RenameTarget | null>(null);
  const [renameName, setRenameName] = useState('');
  const [instruction, setInstruction] = useState(''); const [analysisInstruction, setAnalysisInstruction] = useState('');
  const [threeDInstruction, setThreeDInstruction] = useState('');
  const [attachment, setAttachment] = useState<File | null>(null); const [attachmentURL, setAttachmentURL] = useState('');
  const [runningJob, setRunningJob] = useState<RunningJob | null>(null); const [job, setJob] = useState<StudioJob | null>(null);
  const [resumingTask, setResumingTask] = useState(false);
  const [requestingPause, setRequestingPause] = useState(false);
  const [showWorkingOutput, setShowWorkingOutput] = useState(false);
  const [workingViewId, setWorkingViewId] = useState('');
  const [showPreviousForCopyUrl, setShowPreviousForCopyUrl] = useState('');
  const handledGroupedPreviewJobs = useRef(new Set<string>());
  const returnTo2DPreview = useRef('');
  const [workingImageSize, setWorkingImageSize] = useState<{ width: number; height: number } | null>(null);
  const [build2DGroupId, setBuild2DGroupId] = useState('');
  const [draftGroupId, setDraftGroupId] = useState('');
  const [draftViewId, setDraftViewId] = useState('');
  const [showDraft, setShowDraft] = useState(false);
  const [artifactPreview, setArtifactPreview] = useState<StudioArtifact | null>(null);
  const [parameterFilter, setParameterFilter] = useState(''); const [historyTarget, setHistoryTarget] = useState('');
  const [undoStack, setUndoStack] = useState<number[]>([]); const [redoStack, setRedoStack] = useState<number[]>([]);
  const [interiorTarget, setInteriorTarget] = useState('');
  const [interior, setInterior] = useState({ ...DEFAULT_INTERIOR });
  const [documentTab, setDocumentTab] = useState<'customer' | 'outputs'>('customer');
  const [materialLibrary, setMaterialLibrary] = useState<'assign' | 'manage' | 'stock' | null>(null);
  const [boardSpecOpen, setBoardSpecOpen] = useState(false); const [bomOpen, setBomOpen] = useState(false); const [bomDetail, setBomDetail] = useState(false);
  const host = useRef<HTMLDivElement>(null); const viewer = useRef<KitchenViewer | null>(null);
  const isolatedBOMPart = useRef('');
  const fitProjectView = useRef(false);
  const viewport = useRef<HTMLDivElement>(null);
  const uploadInput = useRef<HTMLInputElement>(null); const screenshotInput = useRef<HTMLInputElement>(null); const importInput = useRef<HTMLInputElement>(null);
  const materialAppearanceBeforePreview = useRef<ViewOptions['appearance'] | null>(null);
  const operationBusy = useRef(false); const inputComposing = useRef(false);
  const newProjectDialog = useRef<HTMLFormElement>(null); const newProjectOpener = useRef<HTMLElement | null>(null); const modalLocked = useRef(false);
  const activeProject = useRef('');
  const navigationEpoch = useRef(0);
  const taskControlEpoch = useRef(0);
  const workflow2D = proposal
    ? (job?.proposal_id === proposal.id ? job.workflow_2d : null) ?? (project?.pending_proposal?.id === proposal.id ? project.workflow_2d : null)
    : project?.workflow_2d;
  const sourceOnlyFallback = !!proposal && isUnclassified2DFallback(workflow2D);
  const shown = useMemo(() => proposal?.scene && !sourceOnlyFallback ? sceneWithPlan(proposal.scene) : scene, [proposal, scene, sourceOnlyFallback]);
  const model = (!sourceOnlyFallback && proposal?.model) || project?.model;
  const nodes = useMemo(() => flatten(model?.root), [model?.root]);
  const selectedNode = nodes.find(node => node.id === options.selected);
  const selectedContext = !!model && !!selectedNode && contextForNode(model.root, selectedNode.id);
  const boardSizes = useMemo(() => Object.fromEntries([
    ...Object.values(shown?.local_frames || {}).flatMap(frame => frame.objects), ...(shown?.objects || []),
  ].filter(object => object.size?.length === 3 && object.size.every(Number.isFinite)).map(object => [object.id, object.size])), [shown]);
  const previewedPanels = useMemo<PanelSpecPreviewRow[] | undefined>(() => {
    if (!proposal?.board_specs_preview || !project) return undefined;
    const axes = { X: 0, Y: 1, Z: 2 } as const;
    const saved = new Set(flatten(project.model.root).filter(node => node.board_spec).map(node => node.id));
    return flatten(proposal.model.root).flatMap(node => {
      if (!node.board_spec || saved.has(node.id) || !boardSizes[node.id]) return [];
      const { length_axis, width_axis, thickness_axis } = node.board_spec;
      const sizes = boardSizes[node.id];
      return [{ part_id: node.id, part_name: node.name, length_axis, width_axis, thickness_axis,
        length_mm: sizes[axes[length_axis]], width_mm: sizes[axes[width_axis]], thickness_mm: sizes[axes[thickness_axis]] }];
    });
  }, [proposal, project, boardSizes]);
  const localFrames = Object.values(shown?.local_frames || {}).filter(frame => frame.meshes.length);
  const localFrame = shown?.local_frames?.[localFrameId];
  const viewerScene = useMemo(() => sceneFor3D(shown, localFrameId), [shown, localFrameId]);
  const has3DGeometry = !!shown?.meshes.length || localFrames.length > 0;
  const has2DOutput = Object.keys(shown?.drawings || {}).length > 0;
  const workflow3D = proposal
    ? (job?.proposal_id === proposal.id ? job.workflow_3d : null) ?? (project?.pending_proposal?.id === proposal.id ? project.workflow_3d : null)
    : project?.workflow_3d;
  const workflow = project?.workflow_summary;
  const selectedObject = viewerScene?.objects.find(object => object.id === options.selected);
  const locked = !!busy || !!runningJob;
  const globalLocked = !!busy;
  const grouped2DJob = job?.grouped_2d || job?.groups_2d?.length ? job : project?.grouped_2d_job;
  const drawingGroups = grouped2DJob?.groups_2d || [];
  const build2DGroup = drawingGroups.find(group => group.id === build2DGroupId) || drawingGroups[0];
  const retainedDrafts = new Set(Object.entries(project?.grouped_3d_jobs || {}).filter(([, entry]) => hasDraftOutput(entry)).map(([id]) => id));
  if (job?.draft_3d_group_id && hasDraftOutput(job)) retainedDrafts.add(job.draft_3d_group_id);
  const draftGroup = drawingGroups.find(group => group.id === draftGroupId)
    || drawingGroups.find(group => retainedDrafts.has(group.id))
    || drawingGroups.find(group => group.can_generate_3d_draft) || drawingGroups[0];
  const selectedGroupHasDraft = !!draftGroup && retainedDrafts.has(draftGroup.id);
  const draftSequenceGroups = drawingGroups.filter(group => group.can_generate_3d_draft);
  const resumeDraftSequence = job?.id && (job.status === 'failed' || job.status === 'cancelled')
    && job.draft_3d_sequence?.some(row => !draftSequenceRoomFinished(row.status)) ? job : undefined;
  const unfinishedDraftRow = resumeDraftSequence?.draft_3d_sequence?.find(row => !draftSequenceRoomFinished(row.status));
  const resumeSequenceGroup = unfinishedDraftRow && draftSequenceGroups.find(group => group.id === unfinishedDraftRow.group_id);
  const allDraftSourcesReady = draftSequenceGroups.length > 1 && draftSequenceGroups.length === drawingGroups.length;
  const canStartDraftSequence = !!resumeSequenceGroup || allDraftSourcesReady;
  const nextDraftGroup = selectedGroupHasDraft ? draftSequenceGroups.find(group => !retainedDrafts.has(group.id)) : undefined;
  const draftStartLabel = draftGroup ? draftGroupActionLabel(draftGroup, drawingGroups, selectedGroupHasDraft) : '';
  const hasSaved3DGeometry = !!scene?.meshes.length || Object.values(scene?.local_frames || {}).some(frame => frame.meshes.length);
  const canShowGroupedDraft = !!draftGroup;
  const groupDraftMode = stage === 3 && canShowGroupedDraft && !proposal && (showDraft || !has3DGeometry && !hasSaved3DGeometry);
  const hasReadOnlyDrafts = !has3DGeometry && !hasSaved3DGeometry && retainedDrafts.size > 0;
  const canOpenCuttingList = has3DGeometry || hasSaved3DGeometry || hasReadOnlyDrafts;
  const currentDraftJob = draftGroup && job?.draft_3d_group_id === draftGroup.id ? job : undefined;
  const draftJobForGroup = (groupId: string) => {
    const current = job?.draft_3d_group_id === groupId ? job : undefined;
    return hasDraftOutput(current) ? current : project?.grouped_3d_jobs?.[groupId] ?? current;
  };
  const draftJob = draftGroup ? draftJobForGroup(draftGroup.id) : undefined;
  const draftSourceChecked = draftJob?.draft_3d_source_checked ?? draftGroup?.accepted;
  const draftViews = draftJob?.working_result?.kind === '3d' ? draftJob.working_result.views : [];
  const selectedDraftView = draftViews.find(item => item.view_id === draftViewId) ?? draftViews[0];
  const draftSidebarViews = stage === 3 ? drawingGroups.flatMap(group => {
    const result = draftJobForGroup(group.id)?.working_result;
    return result?.kind === '3d' ? result.views.map(item => ({ group, item })) : [];
  }) : [];
  const draftSequenceCurrentRoom = runningJob && job?.draft_3d_current_group_id && job.draft_3d_current_group_id === draftGroup?.id ? job : null;
  const draftSequenceWaitingRoom = runningJob && job?.draft_3d_sequence?.some(row => row.group_id === draftGroup?.id && row.status === 'queued');
  const showingEarlierDraft = !!draftJob?.id && job?.draft_3d_sequence?.some(row =>
    row.group_id === draftGroup?.id && row.status === 'failed' && row.job_id !== draftJob.id);
  const draftAssumptions = draftJob?.workflow_3d?.draft_assumptions || [];
  const latestDraftReport = draftJob?.workflow_3d?.reports?.at(-1);
  const draftReviewNotes = [...new Set([
    ...(latestDraftReport?.findings || []).map(finding => finding.observed),
    ...(latestDraftReport?.limitations || []),
    ...(draftJob?.workflow_3d?.issues || []),
  ].filter((note): note is string => typeof note === 'string' && !!note.trim()))].slice(0, 6);
  const taskJob = runningJob ? job : stage === 2 && grouped2DJob ? grouped2DJob
    : groupDraftMode && !taskInterrupted(resumeDraftSequence) ? currentDraftJob ?? draftJob : job;
  const materialTask = runningJob?.kind === 'materials' || taskJob?.kind === 'materials';
  const materialControlsInBanner = !!runningJob && materialTask;
  const activeDimension = runningJob?.kind || ['generate3d', 'edit3d', 'materials'].includes(taskJob?.kind || '') ? '3D' : '2D';
  const interruptedTask = !runningJob && taskInterrupted(taskJob);
  const savedGroupedJob = project?.grouped_2d_job ?? project?.last_job;
  const canResume2D = interruptedTask && !!savedGroupedJob?.can_resume_2d && savedGroupedJob.id === taskJob?.id;
  const taskPaused = taskJob?.status === 'paused';
  const taskPausing = taskJob?.status === 'pausing';
  const reportedProgress = (taskPaused || taskPausing) ? taskJob.resume_progress ?? taskJob.progress : taskJob?.progress;
  // Older versions marked interruptions as 100% regardless of the last checkpoint.
  const taskProgress = typeof reportedProgress === 'number' && Number.isFinite(reportedProgress) && !(interruptedTask && reportedProgress === 100)
    ? Math.round(Math.max(0, Math.min(100, reportedProgress))) : undefined;
  modalLocked.current = globalLocked;
  const projectInactive = !!project && !!project.lifecycle && project.lifecycle !== 'active';
  const changeLocked = locked || !!proposal || projectInactive;
  const retryProposalId = project?.can_retry_2d && proposal?.id === project.pending_proposal?.id ? proposal?.id : undefined;
  const grouped2DEnabled = !!health?.grouped_2d && project?.can_analyze_groups !== false && !retryProposalId;
  const canMapSaved2D = !!project?.can_rebuild_2d_from_originals && !retryProposalId;
  const twoDLocked = locked || projectInactive || (!!proposal && !retryProposalId);
  const draftLocked = !!busy || projectInactive;
  const workingResult = stage === 2 && grouped2DJob ? grouped2DJob.working_result
    : groupDraftMode || job?.draft_3d_group_id || job === grouped2DJob ? null : job?.working_result;
  const working2DResult = grouped2DJob?.working_result ?? job?.working_result;
  const groupedJob = !!grouped2DJob;
  const groupedJobId = grouped2DJob?.id || (job?.grouped_2d ? runningJob?.id : undefined);
  const working2DViews = working2DResult?.kind === '2d' && (groupedJob || runningJob || proposal || taskJob?.status !== 'ready') ? working2DResult.views : [];
  const finishedDrawingGroups = drawingGroups.length > 0 && (grouped2DJob?.status === 'ready' || grouped2DJob?.status === 'needs_review')
    && drawingGroups.every(group => (group.status === 'ready' || group.status === 'needs_review') && !group.can_retry
      && working2DViews.some(result => result.group_id === group.id));
  const no2DResult = !working2DViews.length && (isUndrawn2D(workflow2D) || (taskJob?.kind === 'analyze' && taskJob.status === 'failed') || groupedJob && taskJob?.status !== 'cancelled');
  const workingView = workingResult?.views.find(item => item.view_id === workingViewId) || workingResult?.views[0];
  const copiedWorkingPreview = groupedJob && workingResult?.kind === '2d' && workingView?.copied_preview_url && workingView.copied_pdf_url
    ? { previewUrl: workingView.copied_preview_url, pdfUrl: workingView.copied_pdf_url } : null;
  const showingCopiedPreview = copiedWorkingPreview && copiedWorkingPreview.previewUrl !== showPreviousForCopyUrl;
  const workingPreviewUrl = showingCopiedPreview ? copiedWorkingPreview.previewUrl : workingView?.preview_url;
  const workingPdfUrl = showingCopiedPreview ? copiedWorkingPreview.pdfUrl : workingView?.pdf_url;
  const workingCycle = workingView?.cycle ?? workingResult?.cycle;
  const workingStatus = workingView?.status ?? workingResult?.status;
  const groupedWorkingItems: DrawingResultItem[] = groupedJob ? working2DViews.map(item => {
    const label = item.group_label || drawingGroups.find(group => group.id === item.group_id)?.label;
    return { id: item.view_id, label: item.label, status: item.status, kind: 'drawing', group: item.group_id && label ? { id: item.group_id, label } : undefined };
  }) : [];
  const firstGroupedPreview = groupedWorkingItems[0]?.id;
  const workingOutputVisible = showWorkingOutput && !!workingView;
  const aiEnabled = health?.ai_enabled !== false;
  const isShowcase = project?.demo_key === 'fde-cabinet-showcase';
  const hasReferenceAssets = projectHasReferences(project);
  const compact2DPanel = stage === 2 && !runningJob && !proposal && !interruptedTask && taskJob?.status !== 'failed' && taskJob?.status !== 'cancelled'
    && (finishedDrawingGroups || !groupedJob && (has2DOutput || hasReferenceAssets));
  const drawingResults = useMemo(() => {
    const items = drawingResultItems(shown, model?.views);
    return isShowcase && showcase ? [...items, { id: 'reviewed', label: t('Reviewed drawings', '已审阅图纸'), kind: 'reviewed' as const }] : items;
  }, [shown, model?.views, isShowcase, showcase, language]);
  const resultIds = drawingResults.map(item => item.id).join('\u0000');
  const cuttingListVisible = stage === 4 && !bomDetail;
  const useReferenceViewer = hasReferenceAssets && referenceContent === 'source' && view !== 'source' && stage === 2;
  const referenceMedia = useReferenceViewer && view !== 'source';
  const referenceSection = reference?.sections.find(item => item.id === referenceSectionId) || reference?.sections[0];
  const referenceImage = referenceSection?.views.find(item => item.id === referenceViewId) || referenceSection?.views[0];
  const interviewBuild = !health || !!health?.reference_project_mode || !!health?.reference_demo_mode || !!health?.showcase_demo || !!health?.version.startsWith('0.5.');
  const canRegenerate = !!proposal && (proposal.scene.drawing_quality?.status === 'stale'
    || Object.values(proposal.scene.drawings || {}).some(drawing => drawing.status === 'stale'));
  const pages = useMemo(() => (project?.documents || []).flatMap(document => document.pages.map(page => ({ ...page, key: `${document.id}:${page.number}`, document }))), [project?.documents]);
  const activePage = pages.find(page => page.key === pageKey) || pages[0];
  const cabinets = nodes.filter(node => node.id !== model?.root.id && (CABINET_KINDS.has(node.kind.toLowerCase()) || (node.kind === 'assembly' && node.size?.length === 3 && !node.context && (!!node.interior || /cabinet|vanity|wardrobe|cupboard|柜|盥洗/i.test(node.name)))));
  const materialScopeRoot = materialScope === 'project' ? model?.root : selectedNode;
  const materialScopeLeaves = flatten(materialScopeRoot).filter(node => !node.children.length &&
    (node.surface || (node.physical === true && (node.board_spec || !CABINET_KINDS.has(node.kind)))) &&
    !!model && !contextForNode(model.root, node.id));
  const materialScopeAlreadyAssigned = materialScopeLeaves.length > 0 && materialScopeLeaves.every(node => !!node.material_assignment);
  const hiddenForInside = useMemo(() => {
    if (!inside || !shown) return [];
    const target = interiorTarget || options.selected;
    const candidates = nodes.filter(node => (node.id === target || viewerScene?.objects.find(object => object.id === node.id)?.ancestors.includes(target)) && (node.surface?.plane === 'front' || /front|door|back|背板|门板/i.test(node.kind + ' ' + node.name + ' ' + node.id) || (node.id.startsWith(target + '/INTERIOR/') && /\/(TOP|BACK)$/.test(node.id))));
    return candidates.filter(node => node.id !== target && (node.surface?.plane === 'front' || node.physical !== false)).map(node => node.id);
  }, [inside, shown, viewerScene, nodes, interiorTarget, options.selected]);
  const displayOptions = useMemo(() => ({ ...options, hidden: [...options.hidden, ...hiddenForInside] }), [options, hiddenForInside]);
  const openingMarksShown = view === '3d' ? options.openingMarks : openingMarks2D;
  const openingMarksLabel = view === '3d' ? t('3D swing lines / 三维开启线') : t('2D source opening marks / 二维原图开启标记');
  const parameters = useMemo(() => {
    if (!model) return [];
    let list = model.parameters;
    if (selectedNode && selectedNode.id !== model.root.id && !parameterFilter) {
      const references = new Set(Object.values(selectedObject?.editable || {}));
      const members = flatten(selectedNode);
      const ownerIds = new Set(members.map(member => member.id));
      for (const controlId of Object.keys(shown?.reference_parameters || {})) {
        if (referenceOwnerIds(model, shown, controlId).some(id => ownerIds.has(id))) references.add(controlId);
      }
      for (const member of members) {
        for (const reference of Object.values(viewerScene?.objects.find(object => object.id === member.id)?.editable || {})) references.add(reference);
        for (const expression of [...(member.size || []), ...(member.position || []), member.rotation, member.surface?.width, member.surface?.span]) {
          if (typeof expression === 'string') (expression.match(/[A-Za-z_][A-Za-z0-9_]*/g) || []).forEach(id => references.add(id));
        }
      }
      list = list.filter(parameter => references.has(parameter.id));
    }
    const search = parameterFilter.trim().toLowerCase();
    return search ? list.filter(parameter => `${parameter.id} ${parameter.label} ${shown?.reference_parameters?.[parameter.id]?.label || ''}`.toLowerCase().includes(search)) : list;
  }, [model, selectedNode, selectedObject, parameterFilter, viewerScene, shown?.reference_parameters]);
  const hasReferenceParameters = Object.keys(shown?.reference_parameters || {}).length > 0;
  const sourceObservations = parameters.filter(parameter => hasReferenceParameters && parameter.status === 'tbc' && !Number.isFinite(shown?.reference_parameters?.[parameter.id]?.value_mm));
  const propertyParameters = parameters.filter(parameter => !sourceObservations.includes(parameter));
  const drawingView = view !== '3d' && view !== 'source' ? view : 'PLAN';
  const drawingOwners = useMemo(() => {
    const owners = flatten(selectedNode).map(node => node.id);
    function ancestors(node: StudioNode, path: string[] = []): boolean {
      if (node.id === selectedNode?.id) { owners.push(...path.reverse()); return true; }
      return node.children.some(child => ancestors(child, [...path, node.id]));
    }
    if (model) ancestors(model.root);
    return owners;
  }, [selectedNode, model]);
  const drawingAsset = sourceDrawing(shown, drawingView, drawingOwners);
  const drawingsBlocked = useMemo(() => drawingApplyBlocked(shown), [shown]);
  const matching3DJob = !!proposal && job?.proposal_id === proposal.id && ['generate3d', 'edit3d'].includes(job?.kind || '');
  const threeDPreviewHeld = !!proposal && ((!!workflow3D && workflow3D.accepted !== true)
    || (matching3DJob && (job?.status !== 'ready' || workflow3D?.accepted !== true)));
  const applyBlocked = drawingsBlocked || threeDPreviewHeld || (!!proposal && isUndrawn2D(workflow2D));
  const drawingsComplete = shown?.drawing_quality?.status === 'ready' && !drawingsBlocked;
  const hasOriginalPDF = !!project?.documents.some(document => document.media_type === 'application/pdf' || /\.pdf$/i.test(document.name));
  const saved2DReady = !!Object.keys(scene?.drawings || {}).length && scene?.drawing_quality?.status === 'ready'
    && !drawingApplyBlocked(scene);
  const threeDSourceStatus = project?.three_d_source_status;
  const threeDInputReady = threeDSourceStatus ? threeDSourceStatus === 'ready' : saved2DReady;
  const threeDInputReason = threeDSourceStatus === 'source_unavailable'
    ? t('Reimport the original PDF in Step 1 so Studio can verify the drawing source.', '请在第1步重新导入原始PDF，以便核查图纸来源。')
    : threeDSourceStatus === 'prepared_needs_checked_2d'
      ? t('The reviewed sample sheets are available to view. A rebuild needs checked 2D drawings saved in this project.', '可查看已审阅的样例图纸。重建需要在此项目中保存经过核查的二维图纸。')
      : t('Create, review and save the current 2D drawings in Step 2 first.', '请先在第2步创建、审阅并保存当前二维图纸。');
  const threeDTaskBlock = proposal || project?.pending_proposal ? t('Apply or discard the pending preview before creating 3D.', '请先应用或放弃待确认预览，再创建三维。')
    : locked ? t('Wait for the current project task to finish.', '请等待当前项目任务完成。')
    : projectInactive ? t('Resume the project to create 3D.', '请先恢复项目，再创建三维。') : '';
  const threeDBlockReason = threeDTaskBlock
    || (!hasOriginalPDF || threeDSourceStatus === 'missing_original_pdf' ? t('Upload the original customer PDF in Step 1.', '请在第1步上传客户原始PDF。')
    : !threeDInputReady ? threeDInputReason
    : !aiEnabled || !health?.key_available ? t('Save an OpenAI API key in Assistant settings to create 3D.', '请在设计助手设置中保存OpenAI API密钥，再创建三维。') : '');
  function draftBlockReason(group?: DrawingGroup2D) {
    if (locked) return t('Wait for the current project task to finish.', '请等待当前项目任务完成。');
    if (projectInactive) return t('Resume the project to create 3D.', '请先恢复项目，再创建三维。');
    if (proposal || project?.pending_proposal) return t('Apply or discard the pending preview before creating 3D.', '请先应用或放弃待确认预览，再创建三维。');
    if (!aiEnabled || !health?.key_available) return t('Save an OpenAI API key in Assistant settings to create 3D.', '请在设计助手设置中保存OpenAI API密钥，再创建三维。');
    if (!group?.can_generate_3d_draft || !grouped2DJob?.id) return t('This group needs a retained 2D drawing result before creating a draft.', '此分组需有保留的二维图纸成果，才能创建草稿。');
    return '';
  }
  const draft3DBlockReason = draftBlockReason(draftGroup);
  const twoDBlockReason = projectInactive ? t('Resume the project before starting a task.', '请先恢复项目，再开始任务。')
    : proposal && !retryProposalId && (sourceOnlyFallback || workflow2D?.failed_stage === 'grouping_native_sources')
    ? t('Discard this preview to retry with one room or cabinet.', '请先放弃当前预览，再按单个房间或柜体重试。')
    : (proposal || project?.pending_proposal) && !retryProposalId ? t('Review this preview and Apply or Discard it before starting another task.', '请先审阅并应用或放弃当前预览，再开始另一任务。')
    : !hasOriginalPDF ? t('Upload the original customer PDF in Step 1.', '请在第1步上传客户原始PDF。')
    : !aiEnabled || !health?.key_available ? t('Connect the assistant in settings to build 2D.', '请先在设置中连接设计助手，再构建二维图纸。') : '';
  const unmapped2DBlockReason = groupedJob && project?.can_analyze_groups === false && !canResume2D
    ? t('This source map cannot start a new run. Review the existing results and any available retry in Task details.', '此原图分组不能开始新任务。请在任务详情中审阅现有成果，并查看是否可重试。') : '';
  const sourceNativeView = view !== '3d' && view !== 'source' && !!drawingAsset;
  const drawing = useMemo(() => {
    if (drawingAsset) {
      if (drawingAsset.status === 'stale') return '';
      const value = cleanDrawing(drawingAsset.svg || '');
      if (!drawingGeometryCount(value)) return '';
      const document = new DOMParser().parseFromString(value, 'image/svg+xml');
      if (options.dimensions === 'off') document.querySelectorAll('[data-role="dimension"],[data-dimension-id]').forEach(element => element.remove());
      if (!openingMarks2D) document.querySelectorAll('[data-role="opening"],[data-opening-symbol-id]').forEach(element => element.remove());
      return new XMLSerializer().serializeToString(document.documentElement);
    }
    if (!shown?.meshes.length) return '';
    try {
      // Selecting a grouping should retain its descendant dimensions in the checking view.
      const group = selectedNode?.children.length ? selectedNode : null;
      const drawingOptions = group && options.dimensions === 'selected' ? { ...displayOptions, dimensions: 'all' as const } : displayOptions;
      const scoped = group ? { ...shown, dimensions: shown.dimensions.filter(item => item.owner === group.id || shown.objects.find(object => object.id === item.owner)?.ancestors.includes(group.id)) } : shown;
      const result = cleanDrawing(draftSVG(scoped, drawingView, options.selected, options.dimensions !== 'off', options.unit, options.appearance, { ...drawingOptions, openingMarks: openingMarks2D }, 900));
      return drawingGeometryCount(result) ? result : '';
    } catch { return ''; }
  }, [shown, drawingView, drawingAsset, options, displayOptions, openingMarks2D, selectedNode]);
  const drawingIssues = drawingAsset?.issues || [];
  const effectiveDrawingStatus = drawingAsset?.status === 'stale' ? 'stale' : !drawing ? 'incomplete' : drawingAsset?.status;
  const canExportDrawing = !groupDraftMode && !workingOutputVisible && !useReferenceViewer && view !== 'reviewed' && !locked && !!drawing && (!drawingAsset || effectiveDrawingStatus === 'ready');
  const canCaptureView = !groupDraftMode && (workingOutputVisible ? !!workingView : referenceMedia ? stage === 2 && !!referenceImage : view === 'source' ? !!activePage && !!sourceImageSize
    : view === '3d' ? !!viewerScene?.meshes.length && !webglError : !!drawing);
  const exportRevision = proposal ? proposal.base_revision + 1 : project?.revision || 1;
  const drawingAspect = useMemo(() => {
    if (!drawing) return 1.35;
    const value = new DOMParser().parseFromString(drawing, 'image/svg+xml').documentElement.getAttribute('viewBox')?.split(/[\s,]+/).map(Number);
    return value?.length === 4 && value[2] > 0 && value[3] > 0 ? value[3] / value[2] : 1.35;
  }, [drawing]);
  function fittedWidth(aspect: number, reservedHeight = 0) {
    const padding = window.innerWidth <= 700 ? 26 : 48;
    return Math.max(.01, Math.min(Math.max(1, viewportSize.width - padding), Math.max(1, viewportSize.height - padding - reservedHeight) / aspect)) * zoom;
  }
  const drawingWidth = fittedWidth(drawingAspect);
  const sourceWidth = fittedWidth(sourceImageSize ? sourceImageSize.height / sourceImageSize.width : 1.35, 24);
  const workingWidth = fittedWidth(workingImageSize ? workingImageSize.height / workingImageSize.width : 1.35, 48);

  async function run(name: string, action: () => Promise<void>) {
    if (operationBusy.current) return false;
    operationBusy.current = true; setBusy(name); setError(''); setNotice('');
    try { await action(); return true; } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); return false; }
    finally { operationBusy.current = false; setBusy(''); }
  }
  async function refreshList() { setProjects(await studioAPI.projects()); }
  function goHome() {
    if (busy) return;
    navigationEpoch.current += 1; activeProject.current = '';
    setProject(null); setScene(null); setProposal(null); setRunningJob(null); setJob(null);
    setPdfImport(null);
    setShowWorkingOutput(false); setWorkingViewId('');
    returnTo2DPreview.current = '';
    setMaterialLibrary(null); setMaterialSuggestionsOpen(false); setDocumentTab('customer'); materialAppearanceBeforePreview.current = null; setBoardSpecOpen(false); setBomOpen(false); setBomDetail(false); setError(''); setNotice('');
    setStopDialog(false); setDeleteTarget(null); setNewProjectOpen(false); setRenameTarget(null); setKeySettingsOpen(false); setReferenceSectionId('A200'); setReferenceViewId('plan');
  }
  async function loadReferenceManifest() {
    const prepared = await studioAPI.referenceManifest(); setReference(prepared);
    setShowcase({ id: prepared.id || 'fde-reference-demo', title: prepared.title, description: prepared.description || '',
      sheets: prepared.sections.flatMap(section => section.views.map(view => ({ id: section.id + ':' + view.id, title: section.title + ' · ' + view.label, image: view.image, image_url: view.image_url }))) });
    return prepared;
  }
  function chooseReference(sectionId: string, viewId = 'plan') {
    retainCanvasChoice(); setShowWorkingOutput(false); setReferenceContent('source'); setDocumentTab('outputs');
    setReferenceSectionId(sectionId); setZoom(1);
    const owner = sectionId === 'A202' ? 'POWDER' : 'KITCHEN';
    if (nodes.some(node => node.id === owner)) select(owner);
    setReferenceViewId(viewId); setStage(2); setView('reference');
  }
  async function openShowcase() {
    const target = projects.find(item => item.id === health?.prepared_project_id) || projects.find(projectHasReferences) || projects[0];
    if (!target) { setNewProjectOpen(true); return; }
    await run(t('Opening project…', '正在打开项目…'), async () => {
      if (projectHasReferences(target) && !reference) await loadReferenceManifest();
      await loadProject(target.id, true); setNotice(''); setNewProjectOpen(false);
    });
  }
  function focusShowcase(id: string) {
    setView('3d'); setStage(3); setLeftTab('tree');
    setOptions(previous => ({ ...previous, selected: id || model?.root.id || '', isolate: id, dimensions: 'off', componentSizes: false }));
    requestAnimationFrame(() => viewer.current?.fit());
  }
  async function changeLifecycle(action: TaskControlAction) {
    if (!project || operationBusy.current) return;
    taskControlEpoch.current += 1;
    if (action === 'resume' && runningJob) setResumingTask(true);
    try {
      await run(t('Updating project…', '正在更新项目…'), async () => {
        const next = await studioAPI.lifecycle(project.id, project.revision, action);
        const active = runningProjectJob(next);
        const latest = next.active_job ?? next.last_job ?? null;
        setProject(next);
        setRunningJob(active);
        setJob(latest);
        setStopDialog(false);
        if (next.pending_proposal?.id && next.pending_proposal.id !== proposal?.id) {
          setProposal(await studioAPI.proposal(next.id, next.pending_proposal.id));
        }
        await refreshList();
        if (action === 'resume' && active) {
          setNotice(active.kind === 'materials' ? t('Project resumed. The same material task is continuing.', '项目已恢复，原材料任务正在继续。')
            : t('Project resumed. The same drawing task is continuing.', '项目已恢复，原绘图任务正在继续。'));
        } else if (action === 'resume' && taskInterrupted(latest)) {
          setNotice(t('Project resumed. Review the interrupted task to see what you can recover.', '项目已恢复。请查看中断的任务，了解可恢复的内容。'));
        } else if (action === 'pause' && active) {
          setNotice(active.kind === 'materials' ? t('Resume project continues the same material task.', '恢复项目会继续原材料任务。')
            : t('Project paused. Resume project continues the same drawing task.', '项目已暂停。恢复项目会继续原绘图任务。'));
        } else {
          setNotice(action === 'resume' ? t('Project resumed.', '项目已恢复。') : action === 'pause' ? t('Project paused.', '项目已暂停。') : t('Project stopped. Resume it whenever you are ready.', '项目已停止，准备好后可随时恢复。'));
        }
      });
    } finally {
      setResumingTask(false);
    }
  }
  async function controlTask(action: TaskControlAction) {
    if (!project || !runningJob || projectInactive || operationBusy.current) return;
    const projectId = project.id, revision = project.revision, currentJob = runningJob;
    taskControlEpoch.current += 1;
    if (action === 'resume') setResumingTask(true);
    if (action === 'pause') setRequestingPause(true);
    try {
      await run(action === 'pause' ? t('Requesting a pause', '正在请求暂停') : action === 'resume' ? t('Resuming the same task', '正在恢复同一任务') : t('Stopping the task', '正在停止任务'), async () => {
        const next = await studioAPI.jobControl(currentJob.id, revision, action);
        if (activeProject.current !== projectId) return;
        setJob(next);
        if (next.status === 'cancelled' || next.status === 'failed') {
          setRunningJob(null);
          const current = await studioAPI.project(projectId);
          if (activeProject.current === projectId) setProject(current);
        } else setRunningJob({ ...currentJob });
        setNotice(action === 'pause' ? next.status === 'paused' ? t('Task paused. Resume continues the same run.', '任务已暂停，恢复后会继续同一运行。') : t('Pause requested. The current AI request may finish first.', '已请求暂停，当前AI请求可能会先完成。') : action === 'resume' ? t('Continuing the same task. Its existing allowance is retained.', '正在继续同一任务，保留其现有额度。') : taskStoppedMessage());
      });
    } finally {
      setResumingTask(false); setRequestingPause(false);
    }
  }
  async function confirmDelete() {
    if (!deleteTarget || busy || deleteTarget.can_delete === false) return;
    await run(t('Deleting project…', '正在删除项目…'), async () => {
      await studioAPI.deleteProject(deleteTarget.id, deleteTarget.revision);
      if (project?.id === deleteTarget.id) goHome();
      setDeleteTarget(null); await refreshList();
      setNotice(t('Project removed from your workspace.', '项目已从工作空间移除。'));
    });
  }
  async function loadProject(id: string, _first = false) {
    if (activeProject.current !== id) { setAnalysisInstruction(''); setThreeDInstruction(''); }
    taskControlEpoch.current += 1;
    const epoch = ++navigationEpoch.current;
    const next = await studioAPI.project(id);
    const nextScene = await studioAPI.scene(id);
    if (epoch !== navigationEpoch.current) return;
    isolatedBOMPart.current = '';
    activeProject.current = id; setProject(next); setScene(sceneWithPlan(nextScene)); setProposal(null); setJob(next.last_job || null);
    setShowWorkingOutput(false); setWorkingViewId(''); setShowPreviousForCopyUrl(''); setWorkingImageSize(null);
    returnTo2DPreview.current = '';
    const lastDraftGroupId = next.last_job?.draft_3d_group_id;
    const retainedGroupId = lastDraftGroupId && hasDraftOutput(next.grouped_3d_jobs?.[lastDraftGroupId]) ? lastDraftGroupId
      : Object.entries(next.grouped_3d_jobs || {}).find(([, draft]) => hasDraftOutput(draft))?.[0];
    setBuild2DGroupId(''); setShowDraft(false);
    setDraftGroupId(next.active_job?.draft_3d_current_group_id || next.active_job?.draft_3d_group_id || retainedGroupId || lastDraftGroupId || ''); setDraftViewId('');
    setMaterialLibrary(null); setMaterialSuggestionsOpen(false); setDocumentTab('customer'); materialAppearanceBeforePreview.current = null; setBoardSpecOpen(false); setBomOpen(false); setBomDetail(false);
    setPageKey(''); setInside(false); setCamera('AXON'); setLocalFrameId(''); setHistoryTarget(''); setParameterFilter(''); setZoom(1);
    setOptions(previous => ({ ...previous, selected: next.model.root.id, hidden: [], isolate: '', appearance: 'outline' }));
    const previous = next.history.filter(item => item.revision < next.revision).sort((a, b) => b.revision - a.revision)[0];
    setUndoStack(previous ? [previous.revision] : []); setRedoStack([]);
    const hasGeometry = nextScene.meshes.length > 0 || Object.values(nextScene.local_frames || {}).some(frame => frame.meshes.length);
    const savedDrawings = Object.keys(nextScene.drawings || {}).length > 0;
    setView(savedDrawings ? preferredDrawingView(nextScene) : hasGeometry ? '3d' : 'source'); setLeftTab('source'); setStage(savedDrawings ? 2 : hasGeometry ? 3 : 1);
    if (savedDrawings || hasGeometry) setDocumentTab('outputs');
    setReferenceSectionId('A200'); setReferenceViewId('plan');
    let content: 'source' | 'current' = 'source';
    try { if (localStorage.getItem('vwc-studio-content:' + id) === 'current') content = 'current'; } catch { /* Optional view preference. */ }
    setReferenceContent(content);
    setPresentation(next.demo_key === 'fde-cabinet-showcase');
    if (projectHasReferences(next)) { const island = flatten(next.model.root).find(node => node.id === 'KITCHEN/ISLAND'); setStage(2); setView(content === 'source' ? 'reference' : preferredDrawingView(nextScene)); setDocumentTab('outputs'); setOptions(previous => ({ ...previous, selected: island?.id || next.model.root.id, isolate: '', appearance: 'outline' })); }
    if (next.demo_key === 'fde-cabinet-showcase') { setView('3d'); setStage(3); setLeftTab('tree'); setOptions(previous => ({ ...previous, selected: 'KITCHEN/ISLAND', isolate: 'KITCHEN', appearance: 'outline', dimensions: 'off', componentSizes: false, text: false, openingMarks: false })); }
    const openSampleSource = health?.github_distribution && id === health.prepared_project_id;
    if (openSampleSource) {
      setStage(1); setView('source'); setLeftTab('source'); setDocumentTab('customer');
    }
    try { localStorage.setItem('vwc-studio-project', id); } catch { /* Per-user browser state is optional. */ }
    if (next.pending_proposal?.id) {
      const pending = await studioAPI.proposal(id, next.pending_proposal.id);
      if (epoch !== navigationEpoch.current) return;
      setProposal(pending);
      if (!openSampleSource) {
        if (pending.board_specs_preview) {
          setStage(4); setBomDetail(false); setView('3d'); setLeftTab('source'); setDocumentTab('outputs');
        } else if (next.last_job?.proposal_id === pending.id && next.last_job.material_suggestions) {
          setView('3d'); setStage(3); setReferenceContent('current'); setLeftTab('tree');
          setOptions(previous => ({ ...previous, appearance: 'material' }));
        } else if (isUnclassified2DFallback(next.workflow_2d)) {
          setStage(2); setView('source'); setLeftTab('source'); setDocumentTab('customer');
        } else if (isUndrawn2D(next.workflow_2d)) {
          setStage(2); setView(preferredDrawingView(pending.scene)); setLeftTab('source'); setDocumentTab('outputs');
        } else if (pending.scene.meshes.length || Object.values(pending.scene.local_frames || {}).some(frame => frame.meshes.length)) {
          setView('3d'); setStage(3); setReferenceContent('current'); setLeftTab('tree');
        } else if (Object.keys(pending.scene.drawings || {}).length) {
          setView(preferredDrawingView(pending.scene)); setStage(2); setLeftTab(next.workflow_2d?.accepted === false ? 'source' : 'tree'); setDocumentTab('outputs');
        }
      }
    }
    const active = runningProjectJob(next);
    if (active) {
      setJob(next.active_job ?? null); setRunningJob(active);
      if (openSampleSource) return;
      if (active.kind) {
        const showDraft = !!(next.active_job?.draft_3d_group_id || next.active_job?.draft_3d_sequence?.length);
        setStage(3); setView('3d'); setReferenceContent('current');
        setShowDraft(showDraft); setLeftTab('source'); setDocumentTab('outputs');
      }
      else { setStage(2); setView(preferredDrawingView(nextScene)); setLeftTab('source'); setDocumentTab('outputs'); }
    } else {
      setRunningJob(null);
      if (openSampleSource) return;
      if (!next.pending_proposal && (next.last_job?.draft_3d_group_id || next.last_job?.draft_3d_sequence?.length)) {
        setStage(3); setView('3d'); setReferenceContent('current'); setShowDraft(!hasGeometry); setLeftTab('source'); setDocumentTab('outputs');
      } else if (!next.pending_proposal && next.last_job?.working_result?.views.length) {
        const threeD = next.last_job.working_result.kind === '3d';
        setStage(threeD ? 3 : 2); setView(threeD ? '3d' : preferredDrawingView(nextScene));
        if (!threeD) { setLeftTab('source'); setDocumentTab('outputs'); }
        const grouped = next.last_job.grouped_2d || next.last_job.groups_2d?.length;
        if (grouped && !threeD) {
          setWorkingViewId(next.last_job.working_result.views[0].view_id);
          setShowWorkingOutput(true);
        } else if (threeD ? !hasGeometry : !savedDrawings) setShowWorkingOutput(true);
      } else if (!next.pending_proposal && taskInterrupted(next.last_job) && next.last_job?.kind === 'analyze') {
        setStage(2); setView(preferredDrawingView(nextScene)); setLeftTab('source'); setDocumentTab('outputs');
      }
    }
  }
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [status, items] = await Promise.all([studioAPI.health(), studioAPI.projects()]);
        if (cancelled) return; setHealth(status); setProjects(items);
        if (status.reference_project_mode || status.reference_demo_mode) { await loadReferenceManifest(); if (cancelled) return; }
        else if (status.showcase_demo) { const prepared = await studioAPI.showcase(); if (!cancelled) setShowcase(prepared); }
      } catch (reason) { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); }
    })();
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    const element = viewport.current;
    if (!element || closed) return;
    const measure = () => { const width = element.clientWidth, height = element.clientHeight; if (width <= 0 || height <= 0) return; setViewportSize(previous => previous.width === width && previous.height === height ? previous : { width, height }); };
    const observer = new ResizeObserver(measure); observer.observe(element); measure();
    return () => observer.disconnect();
  }, [project?.id, closed, cuttingListVisible]);
  useEffect(() => {
    const element = document.querySelector<HTMLElement>('.studio');
    if (!element || closed) return;
    const chrome = Array.from(element.children).filter(child => child.matches('.studio-header,.stage-bar,.global-alert,.job-banner,.proposal-banner,.pdf-import-status')) as HTMLElement[];
    const measure = () => { const value = `${chrome.reduce((sum, item) => sum + item.getBoundingClientRect().height, 0) + 30}px`; if (element.style.getPropertyValue('--studio-chrome-height') !== value) element.style.setProperty('--studio-chrome-height', value); };
    const observer = new ResizeObserver(measure); chrome.forEach(item => observer.observe(item)); measure();
    return () => observer.disconnect();
  }, [project?.id, closed, error, notice, !!proposal, !!runningJob, !!visiblePdfImport]);
  useEffect(() => setSourceImageSize(null), [activePage?.preview_url]);
  useEffect(() => setArtifactPreview(null), [project?.id]);
  useEffect(() => {
    if (stage !== 2 || !groupedJobId || !firstGroupedPreview || handledGroupedPreviewJobs.current.has(groupedJobId)) return;
    handledGroupedPreviewJobs.current.add(groupedJobId);
    setWorkingViewId(firstGroupedPreview); setShowWorkingOutput(true);
    setLeftTab('source'); setDocumentTab('outputs'); setZoom(1);
  }, [stage, groupedJobId, firstGroupedPreview]);
  useEffect(() => {
    if (stage !== 2 || workingOutputVisible || useReferenceViewer || view === 'source') return;
    if (drawingResults.some(item => item.id === view)) return;
    setView(drawingResults[0]?.id || 'source');
    setZoom(1);
  }, [stage, workingOutputVisible, useReferenceViewer, resultIds, view]);
  useEffect(() => {
    if (!newProjectOpen) return;
    const dialog = newProjectDialog.current;
    dialog?.querySelector('input')?.focus();
    function keyboard(event: KeyboardEvent) {
      if (inputComposing.current || event.isComposing || event.keyCode === 229) return;
      if (event.key === 'Escape' && !modalLocked.current) { event.preventDefault(); setNewProjectOpen(false); }
      if (event.key !== 'Tab' || !dialog) return;
      const controls = Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]'));
      const first = controls[0], last = controls.at(-1);
      if (!first || !last) return;
      if (!dialog.contains(document.activeElement)) { event.preventDefault(); first.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', keyboard, true);
    return () => { document.removeEventListener('keydown', keyboard, true); inputComposing.current = false; requestAnimationFrame(() => newProjectOpener.current?.focus()); };
  }, [newProjectOpen]);
  useEffect(() => {
    if (!runningJob) return;
    let cancelled = false; let timer: ReturnType<typeof setTimeout> | undefined;
    let publishedDraftIds = '';
    const current = runningJob;
    async function poll() {
      const controlEpoch = taskControlEpoch.current;
      function acceptPoll() {
        if (cancelled || activeProject.current !== current.projectId) return false;
        if (controlEpoch !== taskControlEpoch.current || operationBusy.current) {
          timer = setTimeout(poll, 500);
          return false;
        }
        return true;
      }
      try {
        if (!acceptPoll()) return;
        const next = await studioAPI.job(current.id);
        if (!acceptPoll()) return;
        setJob(next);
        const groupTask = !!next.grouped_2d || !!next.groups_2d?.length || !!next.draft_3d_group_id || !!next.draft_3d_sequence?.length;
        const groupTaskDone = groupTask && ['ready', 'needs_review', 'failed', 'cancelled'].includes(next.status);
        const finishedDraftIds = next.draft_3d_sequence?.filter(row => draftSequenceRoomFinished(row.status)).map(row => row.job_id || row.group_id).join(',') || '';
        if (groupTaskDone || finishedDraftIds !== publishedDraftIds) {
          const refreshed = await studioAPI.project(current.projectId);
          const saved = groupTaskDone && next.editable_design_revision === refreshed.revision;
          const savedScene = saved ? await studioAPI.scene(current.projectId) : undefined;
          if (!acceptPoll()) return;
          if (savedScene) showSaved3D(refreshed, savedScene, refreshed.revision - 1);
          else setProject(refreshed);
          publishedDraftIds = finishedDraftIds;
          if (groupTaskDone) {
            setRunningJob(null);
            if (next.error || next.editable_design_error) setError(next.error || next.editable_design_error || '');
          } else timer = setTimeout(poll, 1500);
        } else if (next.status === 'ready' || next.status === 'needs_review') {
          if (!next.proposal_id) throw new Error(t('The result is missing a preview. / 返回结果缺少预览。'));
          const result = await studioAPI.proposal(current.projectId, next.proposal_id);
          const modelResult = current.kind === 'materials' || current.kind === 'generate3d' || current.kind === 'model-edit' || ['generate3d', 'edit3d'].includes(next.kind || '');
          const noDrawings = !modelResult && isUndrawn2D(next.workflow_2d);
          const refreshed = noDrawings ? await studioAPI.project(current.projectId) : null;
          if (!acceptPoll()) return;
          if (refreshed) setProject(refreshed);
          setProposal(result); setRunningJob(null); setLeftTab(!modelResult && next.workflow_2d?.accepted === false ? 'source' : 'tree'); setDocumentTab('outputs'); setView(modelResult ? '3d' : preferredDrawingView(result.scene)); setStage(modelResult ? 3 : 2);
          setShowWorkingOutput(false);
          if (current.kind === 'materials') { setStage(3); setOptions(previous => ({ ...previous, appearance: 'material' })); }
          if (current.kind === 'generate3d' || next.kind === 'generate3d') setOptions(previous => ({ ...previous, appearance: 'outline' }));
          setNotice(drawingNotice(result.scene));
        } else if (next.status === 'cancelled') { setRunningJob(null); setNotice(taskStoppedMessage()); } else if (next.status === 'failed') { setRunningJob(null); setError(next.error_category === 'empty_suggestions' ? [next.error || t('No matching library materials were found.', '材料库中没有匹配的材料。'), ...(next.material_suggestions?.notes || [])].join(' ') : next.error || t('AI request failed. Your saved design is unchanged. / AI 请求失败，已保存设计保持不变。')); }
        else timer = setTimeout(poll, 1500);
      } catch (reason) { if (acceptPoll()) { setError(reason instanceof Error ? reason.message : String(reason)); timer = setTimeout(poll, 2000); } }
    }
    void poll(); return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [runningJob]);
  useEffect(() => {
    if (!viewerScene?.meshes.length || !host.current) return;
    try {
      const instance = new KitchenViewer(host.current, viewerScene, id => select(id));
      instance.setOptions(displayOptions); viewer.current = instance; setWebglError('');
    } catch { setWebglError(t('3D is unavailable on this device. Linked drawings remain available. / 此设备无法显示三维，仍可查看联动二维图。')); }
    return () => { viewer.current?.dispose(); viewer.current = null; };
  }, [project?.id, !!viewerScene?.meshes.length, useReferenceViewer, cuttingListVisible, groupDraftMode]);
  useEffect(() => {
    if (!proposal) return;
    setReferenceContent('current');
    const ids = new Set(flatten(proposal.model.root).map(node => node.id));
    setOptions(previous => ({ ...previous, selected: ids.has(previous.selected) ? previous.selected : proposal.model.root.id, isolate: ids.has(previous.isolate) ? previous.isolate : '', hidden: previous.hidden.filter(id => ids.has(id)) }));
    setLocalFrameId(previous => proposal.scene.local_frames?.[previous] ? previous : !proposal.scene.meshes.length ? Object.keys(proposal.scene.local_frames || {})[0] || '' : '');
    if (stage === 4 && !proposal.board_specs_preview) { setBomDetail(true); setView('3d'); }
    else if (hasReferenceAssets && (view === 'reference' || view === 'source')) setView(preferredDrawingView(proposal.scene));
  }, [proposal?.id]);
  useEffect(() => {
    if (!project || !hasReferenceAssets) return;
    try { localStorage.setItem('vwc-studio-content:' + project.id, referenceContent); } catch { /* Optional view preference. */ }
  }, [project?.id, hasReferenceAssets, referenceContent]);
  useEffect(() => {
    if (!assistantRequested || cuttingListVisible) return;
    requestAnimationFrame(() => { const input = document.querySelector<HTMLTextAreaElement>('.ai-input'); input?.scrollIntoView?.({ block: 'center' }); input?.focus(); });
    setAssistantRequested(false);
  }, [assistantRequested, cuttingListVisible]);
  useEffect(() => { if (viewerScene) viewer.current?.setData(viewerScene); }, [viewerScene]);
  useEffect(() => { if (hasReferenceAssets && (stage === 3 || stage === 4)) requestAnimationFrame(() => viewer.current?.fit()); }, [hasReferenceAssets, stage]);
  useEffect(() => {
    viewer.current?.setOptions(displayOptions);
    if (fitProjectView.current) {
      fitProjectView.current = false;
      viewer.current?.fit();
    }
  }, [displayOptions, viewerScene]);
  useEffect(() => { viewer.current?.preset(camera, true); }, [localFrame?.root_id]);
  useEffect(() => { if (localFrame) viewer.current?.fit(); }, [localFrame?.root_id, options.dimensions, options.componentSizes, options.selected]);
  useEffect(() => { if (selectedNode && cabinets.some(node => node.id === selectedNode.id)) setInteriorTarget(selectedNode.id); }, [selectedNode?.id]);
  useEffect(() => {
    const cabinet = flatten(project?.model.root).find(node => node.id === interiorTarget);
    setInterior({ ...DEFAULT_INTERIOR, ...cabinet?.interior });
    // Only saved revision/target changes replace the user's unfinished form draft.
  }, [project?.id, project?.revision, interiorTarget]);
  useEffect(() => {
    if (!attachment) { setAttachmentURL(''); return; }
    const url = URL.createObjectURL(attachment); setAttachmentURL(url); return () => URL.revokeObjectURL(url);
  }, [attachment]);

  function select(id: string) {
    setOptions(previous => ({ ...previous, selected: id })); setParameterFilter('');
    if (hasReferenceAssets) {
      if (id === 'POWDER' || id.startsWith('POWDER/')) setReferenceSectionId('A202');
      else if (id === 'KITCHEN' || id.startsWith('KITCHEN/')) setReferenceSectionId('A200');
      if (stage === 3 || stage === 4) { const group = id.startsWith('MATERIAL-LAB') ? 'MATERIAL-LAB' : id.startsWith('POWDER') ? 'POWDER' : id.startsWith('KITCHEN') ? 'KITCHEN' : ''; setOptions(previous => ({ ...previous, isolate: group })); requestAnimationFrame(() => viewer.current?.fit()); }
    }
    if (localFrameId && !localFrame?.objects.some(object => object.id === id)) setLocalFrameId(frameForObject(shown, id)?.root_id || '');
  }
  function selectDrawingTarget(target: EventTarget | null) {
    if (!(target instanceof Element)) return;
    const controlId = target.closest('[data-control-id]')?.getAttribute('data-control-id');
    const referenceOwner = controlId ? shown?.reference_parameters?.[controlId]?.owner_id : undefined;
    if (referenceOwner && nodes.some(node => node.id === referenceOwner)) { select(referenceOwner); return; }
    const owner = target.closest('[data-object-id],[data-owner-id]');
    const id = owner?.getAttribute('data-object-id') || owner?.getAttribute('data-owner-id');
    if (id && nodes.some(node => node.id === id)) select(id);
  }
  function choose3DScope(frameId: string) {
    setLocalFrameId(frameId); setCamera('AXON');
    const frame = shown?.local_frames?.[frameId];
    if (frame) { setOptions(previous => ({ ...previous, selected: frame.root_id })); setLeftTab('tree'); }
  }
  function changeOpeningMarks(value: boolean) {
    if (view === '3d') setOptions(previous => ({ ...previous, openingMarks: value }));
    else setOpeningMarks2D(value);
  }
  function fitSheet() {
    setZoom(1);
    requestAnimationFrame(() => viewport.current?.querySelectorAll<HTMLElement>('.source-viewport,.drawing-viewport,.reviewed-sheet-stage,.reference-drawing-stage').forEach(element => { element.scrollLeft = 0; element.scrollTop = 0; }));
  }
  async function createProject(event: FormEvent) {
    event.preventDefault(); if (globalLocked || !newName.trim()) return;
    await run(t('Creating project / 正在创建项目'), async () => { const next = await studioAPI.createProject(newName.trim()); await refreshList(); await loadProject(next.id); setNewProjectOpen(false); setNewName(''); });
  }
  function openRename(target: RenameTarget, opener: HTMLElement) {
    opener.focus();
    setError('');
    setRenameName(target.name);
    setRenameTarget(target);
  }
  async function renameProject(event: FormEvent) {
    event.preventDefault();
    const name = renameName.trim();
    if (!renameTarget || busy || runningJob?.projectId === renameTarget.id || !name || name === renameTarget.name) return;

    const saved = await run(t('Saving project name', '正在保存项目名称'), async () => {
      const renamed = await studioAPI.rename(renameTarget.id, renameTarget.revision, name);
      setProject(current => current?.id === renamed.id ? { ...current, name: renamed.name, display_name: renamed.display_name } : current);
      setProjects(previous => previous.map(item => item.id === renamed.id ? { ...item, name: renamed.name } : item));
      setNotice(t('Project name saved.', '项目名称已保存。'));
    });
    if (saved) setRenameTarget(null);
  }
  async function uploadFile(file?: File) {
    if (!file || changeLocked || operationBusy.current) return;
    const source = { filename: file.name, projectId: project?.id };
    const reject = (message: string) => {
      setError(message);
      setPdfImport({ ...source, phase: 'failed', message });
    };
    if (file.type !== 'application/pdf' && !/\.pdf$/i.test(file.name)) { reject(t('Upload the original customer PDF. Use screenshots with a design instruction.', '请上传客户原始PDF。截图请附加到设计修改要求中。')); return; }
    if (file.size > 50 * 1024 * 1024) { reject(t('Each source must be under 50 MB. / 每个原图文件需小于 50 MB。')); return; }
    await run(t('Importing source / 正在导入原图'), async () => {
      let uploaded = false;
      try {
        if (!project) setPdfImport({ ...source, phase: 'preparing' });
        const target = project || await studioAPI.createProject(file.name.replace(/\.[^.]+$/, ''));
        setPdfImport({ ...source, phase: 'importing' });
        const next = await studioAPI.upload(target.id, file);
        uploaded = true;
        setPdfImport({ ...source, phase: 'opening' });
        const document = next.documents.find(item => item.id === next.imported_document_id)
          ?? next.documents.filter(item => item.name === file.name).at(-1);
        await refreshList();
        await loadProject(next.id);
        setStage(1);
        setView('source');
        setLeftTab('source');
        setDocumentTab('customer');
        if (document?.pages[0]) setPageKey(`${document.id}:${document.pages[0].number}`);
        setPdfImport({ ...source, projectId: next.id, phase: 'ready', pages: document?.page_count,
          alreadyPresent: target.documents.some(item => item.id === document?.id) });
        setNotice(t('Source PDF saved locally. Continue to Step 2 to create and review 2D drawings.', '原始PDF已保存在本地。请继续第2步，创建并审阅二维图纸。'));
      } catch (reason) {
        setPdfImport({ ...source, phase: uploaded ? 'openingFailed' : 'failed', message: reason instanceof Error ? reason.message : String(reason) });
        throw reason;
      }
    });
  }
  async function prepareDesign() {
    if (!project?.reviewed_design_available || changeLocked) return;
    await run(t('Importing approved design results…', '正在导入已审阅设计成果…'), async () => {
      const next = await studioAPI.prepareDesign(project.id, project.revision);
      if (!reference) await loadReferenceManifest();
      await refreshList(); await loadProject(next.id, true); setReferenceContent('source'); setView('reference');
      setNotice(t(`Approved drawings, 3D and cutting-list data imported into this project as R${next.revision}.`, `已将审阅图纸、三维和开料数据导入本项目，保存为R${next.revision}。`));
    });
  }
  async function openDemo() { await run(t('Importing demo / 正在导入演示'), async () => { const next = await studioAPI.demo(); await refreshList(); await loadProject(next.id); setNotice(t('A200 + A202 demo imported. AI analysis starts only when you click Analyze. / 演示原图已导入，点击分析后才会调用 AI。')); }); }
  async function openPreparedDemo() { await run(t('Opening prepared example / 正在打开已准备的演示'), async () => { const next = await studioAPI.preparedDemo(); await refreshList(); await loadProject(next.id); setNotice(t('Vanity project opened.', '盥洗柜项目已打开。')); }); }
  async function openReviewedDemo() { await run(t('Opening reviewed example / 正在打开已审核演示'), async () => { const next = await studioAPI.reviewedDemo(); await refreshList(); await loadProject(next.id); setNewProjectOpen(false); setNotice(t('Reviewed drawing project opened.', '已审阅图纸项目已打开。')); }); }
  async function startAnalysis(rebuildAll = false) {
    if (!project || twoDLocked || twoDBlockReason || unmapped2DBlockReason || canResume2D || drawingGroups.length) return;
    await run(t('Starting 2D creation', '正在开始创建二维图纸'), async () => {
      const rebuildSavedGroups = rebuildAll && canMapSaved2D;
      const scope = rebuildSavedGroups ? '' : analysisInstruction.trim();
      const rebuild = !retryProposalId && (saved2DReady || hasReferenceAssets);
      const groupTask = rebuildSavedGroups || !rebuild && grouped2DEnabled && !scope;
      const result = retryProposalId ? await studioAPI.analyze(project.id, project.revision, scope, retryProposalId)
        : rebuildSavedGroups ? await studioAPI.analyzeGroups(project.id, project.revision, scope, true)
        : groupTask ? await studioAPI.analyzeGroups(project.id, project.revision, scope)
        : rebuild ? await studioAPI.rebuild2D(project.id, project.revision, scope) : await studioAPI.analyze(project.id, project.revision, scope);
      setStage(2); setLeftTab('source'); setDocumentTab('outputs');
      setJob({ status: 'queued', kind: 'analyze', grouped_2d: groupTask, phase: t('Preparing sources / 准备原图'), progress: 0 });
      setRunningJob({ id: result.job_id, projectId: project.id });
    });
  }
  async function rebuildDrawingGroups(group?: DrawingGroup2D) {
    if (!project || !grouped2DJob?.id || twoDLocked || twoDBlockReason || canResume2D ||
      !(group ? group.can_rebuild : grouped2DJob.can_rebuild_2d)) return;
    const existing = group ? working2DViews.some(item => item.group_id === group.id) : !!working2DViews.length;
    await run(existing ? t('Rebuilding 2D drawings', '正在重建二维图纸') : t('Building 2D drawings', '正在构建二维图纸'), async () => {
      const result = await studioAPI.rebuild2DGroups(project.id, project.revision, grouped2DJob.id!, group?.id);
      handledGroupedPreviewJobs.current.add(result.job_id);
      setJob({ ...grouped2DJob, id: result.job_id, status: 'queued', phase: 'queued', progress: 0, error: undefined,
        error_category: undefined, can_rebuild_2d: false, can_resume_2d: false,
        groups_2d: drawingGroups.map(item => !group || item.id === group.id
          ? { ...item, status: 'queued', can_retry: false, can_rebuild: false } : item) });
      setRunningJob({ id: result.job_id, projectId: project.id });
    });
  }
  async function resumeAnalysis() {
    if (!project || !taskJob?.id || !canResume2D || twoDLocked || twoDBlockReason || operationBusy.current) return;
    const previousJobId = taskJob.id;
    setResumingTask(true);
    try {
      await run(t('Resuming 2D from a saved checkpoint', '正在从已保存的检查点恢复二维任务'), async () => {
        const result = await studioAPI.resume2D(project.id, project.revision, previousJobId);
        handledGroupedPreviewJobs.current.add(result.job_id);
        setJob({ ...taskJob, id: result.job_id, status: 'queued', phase: 'resuming_2d', progress: taskProgress ?? 0,
          can_resume_2d: false, error: undefined, error_category: undefined });
        setRunningJob({ id: result.job_id, projectId: project.id });
      });
    } finally {
      setResumingTask(false);
    }
  }
  async function retryDrawingGroup(groupId: string) {
    const group = drawingGroups.find(item => item.id === groupId);
    if (!project || !grouped2DJob?.id || !group?.can_retry || locked || projectInactive || !aiEnabled || !health?.key_available) return;
    const previousJobId = grouped2DJob.id;
    await run(t('Retrying the drawing group', '正在重试图纸分组'), async () => {
      const result = await studioAPI.retryDrawingGroup(project.id, project.revision, groupId, previousJobId);
      // This explicit retry keeps the user's current view, including the original PDF.
      handledGroupedPreviewJobs.current.add(result.job_id);
      setJob({ ...grouped2DJob, id: result.job_id, status: 'queued', phase: 'queued', progress: 0, error: undefined, error_category: undefined,
        groups_2d: drawingGroups.map(item => item.id === groupId ? { ...item, status: 'queued', can_retry: false } : item) });
      setRunningJob({ id: result.job_id, projectId: project.id });
    });
  }
  function chooseDraftGroup(id: string, viewId = '') { setDraftGroupId(id); setDraftViewId(viewId); setShowDraft(true); }
  function openProject3D() {
    setShowDraft(false); setView('3d'); setShowWorkingOutput(false);
  }
  function showFullProject3D() {
    openProject3D();
    isolatedBOMPart.current = '';
    if (shown?.meshes.length) setLocalFrameId('');
    fitProjectView.current = true;
    setOptions(previous => ({ ...previous, isolate: '' }));
  }
  function showSaved3D(next: StudioProject, savedScene: StudioScene, previousRevision: number) {
    setProject(next); setScene(sceneWithPlan(savedScene)); openProject3D();
    setReferenceContent('current'); setLeftTab('source'); setDocumentTab('outputs'); setLocalFrameId('');
    setOptions(previous => ({ ...previous, selected: next.model.root.id, isolate: '', hidden: [], appearance: 'outline' }));
    setUndoStack(previous => [...previous, previousRevision]); setRedoStack([]);
  }
  async function startGroup3DDrafts(group?: DrawingGroup2D, resume = false) {
    const target = group ?? (resume ? resumeSequenceGroup : draftSequenceGroups[0]);
    if (!project || !target || (!group && !resume && !allDraftSourcesReady) || !grouped2DJob?.id || draftBlockReason(target)) return;
    const sourceJobId = grouped2DJob.id;
    await run(group ? t('Starting 3D review draft', '正在创建三维审阅草稿') : t('Starting 3D drafts in source order', '正在按原图顺序创建三维草稿'), async () => {
      const instructions = resume ? '' : threeDInstruction.trim();
      const previousSequence = resume ? resumeDraftSequence : undefined;
      const result = group ? await studioAPI.generateGroup3DDraft(project.id, project.revision, group.id, sourceJobId, instructions)
        : await studioAPI.generateGroup3DDrafts(project.id, project.revision, sourceJobId, instructions, previousSequence?.id);
      setProject(previous => previous && { ...previous, grouped_2d_job: grouped2DJob });
      chooseDraftGroup(target.id);
      setStage(3); setLeftTab('source'); setDocumentTab('outputs');
      const sequence = previousSequence?.draft_3d_sequence?.map(row => draftSequenceRoomFinished(row.status) ? row : { ...row, status: 'queued' as const, job_id: undefined })
        ?? draftSequenceGroups.map(room => ({ group_id: room.id, label: room.label, status: 'queued' as const }));
      setJob({ id: result.job_id, kind: 'generate3d', status: 'queued', phase: 'queued', progress: 0,
        draft_3d_group_label: target.label, ...(group ? { draft_3d_group_id: target.id }
          : { draft_3d_sequence: sequence, draft_3d_current_group_id: target.id, draft_3d_group_progress: 0 }) });
      setRunningJob({ id: result.job_id, projectId: project.id, kind: 'generate3d' });
    });
  }
  async function start3D() {
    if (!project || threeDBlockReason || operationBusy.current) return;
    await run(t('Starting 3D creation', '正在开始创建三维模型'), async () => {
      const result = await studioAPI.generate3D(project.id, project.revision, threeDInstruction.trim());
      setStage(3); setView('3d'); setShowDraft(false); setReferenceContent('current'); setLeftTab('source'); setDocumentTab('outputs');
      setOptions(previous => ({ ...previous, appearance: 'outline' }));
      setJob({ status: 'queued', kind: 'generate3d', phase: 'queued', progress: 0 });
      setRunningJob({ id: result.job_id, projectId: project.id, kind: 'generate3d' });
    });
  }
  function prepare3DSource() {
    if (threeDTaskBlock) return;
    if (!hasOriginalPDF || threeDSourceStatus === 'source_unavailable') {
      chooseStage(1);
      setNotice(threeDBlockReason);
      return;
    }
    chooseStage(2);
    setNotice(canMapSaved2D || drawingGroups.length
      ? t('Use Rebuild all 2D groups in Step 2 first. The project’s room results will supply the 3D group rebuild in Step 3.', '请先在第2步重建所有二维分组。各房间的二维成果将用于第3步重建三维分组。')
      : t('Build or rebuild 2D, then review the preview before applying it. A checked saved 2D set enables Rebuild 3D.',
        '请构建或重建二维图纸，并在应用前审阅预览。保存核查通过的二维图纸后，即可重建三维。'));
  }
  async function applyProposal() {
    if (!project || !proposal || applyBlocked) return;
    await run(t('Saving revision / 正在保存版本'), async () => {
      const previousRevision = project.revision; const next = await studioAPI.apply(project.id, proposal.id, project.revision);
      const nextScene = await studioAPI.scene(project.id); setProject(next); setScene(sceneWithPlan(nextScene)); setProposal(null); materialAppearanceBeforePreview.current = null; setReferenceContent('current'); if (view === 'reference' || view === 'source') setView(stage === 3 ? '3d' : preferredDrawingView(nextScene)); setUndoStack(previous => [...previous, previousRevision]); setRedoStack([]); await refreshList();
      setNotice(t(`Saved locally as R${next.revision}. / 已保存本地版本 R${next.revision}。`));
    });
  }
  async function discardProposal() { if (!project || !proposal) return; await run(t('Discarding preview / 正在放弃预览'), async () => { await studioAPI.discard(project.id, proposal.id); setProject(await studioAPI.project(project.id)); setProposal(null); setJob(null); const appearance = materialAppearanceBeforePreview.current; if (appearance) setOptions(previous => ({ ...previous, appearance })); materialAppearanceBeforePreview.current = null; setNotice(t('Preview discarded. Saved revision unchanged. / 已放弃预览，已保存版本保持不变。')); }); }
  async function regenerateProposal() {
    if (!project || !proposal || locked || projectInactive || !aiEnabled) return;
    await run(t('Regenerating linked drawings / 正在重新生成联动图纸'), async () => {
      const result = await studioAPI.redraw(project.id, proposal.id, project.revision);
      setJob({ status: 'queued', phase: 'repairing_drawings', progress: 0 });
      setRunningJob({ id: result.job_id, projectId: project.id });
    });
  }
  async function previewParameter(id: string, value: number) { if (!project || changeLocked) return; await run(t('Calculating preview / 正在计算预览'), async () => { setProposal(await studioAPI.parameter(project.id, project.revision, id, value)); }); }
  async function previewMaterial(material: MaterialVariant, partIds: string[]) {
    if (!project || changeLocked) return false;
    return run(t('Preparing material preview / 正在生成材料预览'), async () => {
      setProposal(await studioAPI.materialPreview(project.id, project.revision, partIds, material));
      setOptions(previous => ({ ...previous, appearance: 'material' }));
      if (has3DGeometry) setView('3d');
    });
  }
  async function previewBoard(spec: BoardSpec) {
    if (!project || !selectedNode || changeLocked || !isBoardPanel(selectedNode, selectedContext)) return false;
    return run(t('Preparing board preview / 正在生成板件预览'), async () => { setProposal(await studioAPI.boardSpecPreview(project.id, project.revision, selectedNode.id, spec)); });
  }
  async function previewBoardSpecs(report: BOMReport) {
    if (!project || changeLocked || report.project_id !== project.id || report.revision !== project.revision) return;
    await run(t('Preparing panel specifications', '正在准备板件规格'), async () => {
      setProposal(await studioAPI.boardSpecsPreview(project.id, project.revision, report.bom_sha256, report.scope_id));
    });
  }
  async function previewClearMaterial(partIds: string[]) {
    if (!project || changeLocked) return false;
    return run(t('Preparing assignment removal / 正在预览清除材料分配'), async () => { setProposal(await studioAPI.clearMaterialPreview(project.id, project.revision, partIds)); });
  }
  function selectBOMPart(id: string) {
    select(id); setView('3d'); setLeftTab('tree');
    isolatedBOMPart.current = id;
    setStage(4); setBomDetail(true); setReferenceContent('current'); setOptions(previous => ({ ...previous, isolate: id })); requestAnimationFrame(() => viewer.current?.fit());
    if (!shown?.objects.some(object => object.id === id)) setLocalFrameId(frameForObject(shown, id)?.root_id || '');
  }
  function chooseBOMBoardStock(id: string) {
    if (changeLocked || !nodes.some(node => node.id === id && node.board_spec)) return;
    selectBOMPart(id); setBomOpen(false); setMaterialLibrary('stock');
  }
  async function previewInterior(event: FormEvent) { event.preventDefault(); if (!project || !interiorTarget || changeLocked) return; await run(t('Designing interior / 正在生成内部结构'), async () => { const result = await studioAPI.interior(project.id, { expected_revision: project.revision, cabinet_id: interiorTarget, ...interior }); setProposal(result); setView('3d'); setInside(true); select(interiorTarget); }); }
  function changeInterior(key: keyof typeof interior, value: number) {
    setInterior(previous => {
      if (key === 'drawers' && value > 0) return { ...previous, drawers: value, shelves: 0, dividers: 0 };
      if ((key === 'shelves' || key === 'dividers') && value > 0) return { ...previous, [key]: value, drawers: 0 };
      return { ...previous, [key]: value };
    });
  }
  function attach(file?: File) { if (!file) return; if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) { setError(t('Attach a PNG, JPEG or WebP screenshot. / 请附加 PNG、JPEG 或 WebP 截图。')); return; } if (file.size > 10 * 1024 * 1024) { setError(t('Screenshot must be under 10 MB. / 截图需小于 10 MB。')); return; } setAttachment(file); }
  function pasteImage(event: ClipboardEvent<HTMLTextAreaElement>) { const image = Array.from(event.clipboardData.files).find(file => file.type.startsWith('image/')); if (image) { event.preventDefault(); attach(image); } }
  async function captureView(): Promise<Blob> {
    if (workingOutputVisible && workingPreviewUrl) {
      const response = await fetch(workingPreviewUrl);
      if (!response.ok) throw new Error(t('The working image is unavailable.', '工作图像暂不可用。'));
      return response.blob();
    }
    if (referenceMedia && stage === 2 && referenceImage) { const response = await fetch(referenceImage.image_url || studioAPI.referenceAsset(referenceImage.image)); if (!response.ok) throw new Error(t('Could not export this drawing.', '无法导出此图纸。')); return response.blob(); }
    if (view !== 'source' && view !== '3d' && !drawing) throw new Error(t('This drawing is incomplete or needs updating. / 此图纸尚不完整或需要更新。'));
    if (view === '3d' && !viewerScene?.meshes.length) throw new Error(t('Choose a resolved model or a local assembly before capturing it. / 请先选择可显示的模型或局部构件。'));
    let svg = ''; let source: HTMLCanvasElement | HTMLImageElement | null = null;
    if (view === '3d') { source = viewer.current?.renderer.domElement || null; if (!source) throw new Error(t('3D capture is unavailable; attach a screenshot instead. / 无法截取三维画面，请附加截图。')); }
    else if (view === 'source') { source = document.querySelector<HTMLImageElement>('.source-image'); if (!source?.complete) throw new Error(t('Source image is still loading. / 原图正在加载。')); }
    else svg = drawing;
    const canvas = document.createElement('canvas'); const context = canvas.getContext('2d'); if (!context) throw new Error(t('Image capture unavailable. / 无法截取图像。'));
    if (source) { canvas.width = source instanceof HTMLCanvasElement ? source.width : source.naturalWidth; canvas.height = source instanceof HTMLCanvasElement ? source.height : source.naturalHeight; context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(source, 0, 0); }
    else { canvas.width = 1600; canvas.height = Math.round(1600 * drawingAspect); context.fillStyle = '#fff'; context.fillRect(0, 0, canvas.width, canvas.height); }
    async function drawSVG(value: string, width: number, height: number) {
      const url = URL.createObjectURL(new Blob([value], { type: 'image/svg+xml' }));
      try { const image = new Image(); await new Promise<void>((resolve, reject) => { image.onload = () => resolve(); image.onerror = () => reject(new Error(t('Could not capture drawing. / 无法截取图纸。'))); image.src = url; }); context!.drawImage(image, 0, 0, width, height); } finally { URL.revokeObjectURL(url); }
    }
    if (svg) await drawSVG(svg, canvas.width, canvas.height);
    if (view === '3d' && viewer.current?.dimensionOverlay.childElementCount) {
      const overlay = viewer.current.dimensionOverlay.cloneNode(true) as SVGSVGElement;
      overlay.setAttribute('xmlns', 'http://www.w3.org/2000/svg'); overlay.setAttribute('width', String(host.current?.clientWidth || 900)); overlay.setAttribute('height', String(host.current?.clientHeight || 600));
      await drawSVG(new XMLSerializer().serializeToString(overlay), canvas.width, canvas.height);
    }
    if (view === '3d' && localFrame) {
      context.fillStyle = '#fff'; context.fillRect(0, canvas.height - 34, canvas.width, 34);
      context.fillStyle = '#173e37'; context.font = '16px Segoe UI,Arial';
      context.fillText(t(`${localFrame.label} · ${t('Local assembly; global placement TBC', '局部构件；整体位置待确认')}`), 12, canvas.height - 12);
    }
    return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error(t('Capture failed. / 截图失败。'))), 'image/png'));
  }
  async function attachCapture() { if (draftLocked || !canCaptureView) return; await run(t('Capturing current view / 正在截取当前视图'), async () => { setAttachment(new File([await captureView()], `${workingOutputVisible ? 'working-output' : 'current-view'}${view === '3d' && localFrame ? '-local-' + safeName(localFrame.root_id) : ''}-R${project?.revision || 0}.png`, { type: 'image/png' })); }); }
  async function sendEdit(event: FormEvent) { event.preventDefault(); if (!project || !instruction.trim() || changeLocked || !aiEnabled) return; await run(t('Sending request / 正在提交请求'), async () => { const target = stage >= 3 ? '3d' : '2d'; const result = await studioAPI.edit(project.id, project.revision, instruction.trim(), options.selected, attachment, target); setRunningJob({ id: result.job_id, projectId: project.id, kind: target === '3d' ? 'model-edit' : undefined }); setJob({ status: 'queued', phase: t('Preparing edit / 准备修改'), progress: 0 }); }); }
  async function restore(target: number, kind: 'undo' | 'redo' | 'history') {
    if (!project) return; await run(t('Restoring revision / 正在恢复版本'), async () => {
      const current = project.revision; const next = await studioAPI.restore(project.id, current, target); setProject(next); setScene(sceneWithPlan(await studioAPI.scene(project.id))); setProposal(null); setReferenceContent('current'); setHistoryTarget('');
      if (kind === 'undo') { setUndoStack(stack => stack.slice(0, -1)); setRedoStack(stack => [...stack, current]); }
      else if (kind === 'redo') { setRedoStack(stack => stack.slice(0, -1)); setUndoStack(stack => [...stack, current]); }
      else { setUndoStack(stack => [...stack, current]); setRedoStack([]); }
      await refreshList(); setNotice(t(`R${target} restored into new R${next.revision}. / 已将 R${target} 恢复为新版本 R${next.revision}。`));
    });
  }
  async function exportHTML() {
    if (!scene || !project) return;
    await run(t('Preparing offline 3D / 正在准备离线三维'), async () => {
      const runtime = await studioAPI.portableRuntime(); const portable = structuredClone(localFrame ? viewerScene! : scene);
      delete portable.local_frames;
      portable.project.source = {};
      portable.default_selection = options.selected;
      portable.project.viewer_defaults = { ...portable.project.viewer_defaults, unit: options.unit, appearance: options.appearance, dimensions: options.dimensions, componentSizes: options.componentSizes, openingMarks: options.openingMarks, text: options.text, viewLabels: options.viewLabels, transparentWalls: options.transparentWalls };
      const escape = (text: string) => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
      portable.views = Object.fromEntries(Object.entries(portable.views).map(([id, definition]) => [id, { ...definition, detail: escape(definition.detail) }]));
      const json = JSON.stringify(portable).replaceAll('<', '\\u003c');
      const title = project.name.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
      const style = `*{box-sizing:border-box}html,body{margin:0;height:100%;font:14px Segoe UI,Arial,sans-serif;background:#f4f1eb;color:#243c36}body{display:flex;flex-direction:column}header{padding:16px 20px;background:#173c35;color:#fff;display:flex;gap:15px;align-items:center;flex-wrap:wrap}header small{color:#d8e1d8}nav{display:flex;flex-wrap:wrap;gap:7px;padding:10px}nav button,nav select{padding:8px;border:1px solid #c7cec7;border-radius:6px;background:#fff;color:#243c36;font:inherit}nav label{display:flex;align-items:center;gap:4px}#viewer{position:relative;flex:1;min-height:280px;overflow:hidden}#fallback{flex:1;overflow:auto;padding:15px}#fallback svg{max-height:75vh;width:100%}.sp-labels{position:absolute;inset:0;pointer-events:none}.sp-label{position:absolute;transform:translate(-50%,-50%);padding:3px 6px;background:#fffefa;border-radius:3px;font-size:12px;white-space:nowrap}.dimension{color:#2563eb}.inferred{background:#fff1a6}.view-reference{border:1px solid #98b0aa}footer{padding:8px 15px;font-size:11px;color:#65736c}@media(max-width:700px){header{font-size:12px}nav{font-size:11px}nav button,nav select{padding:6px}}`;
      const html = `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title} · 3D</title><style>${style}</style><header><b>${title} · R${project.revision}</b><small>${localFrame ? escape(localFrame.label) + t(' · Local assembly; global placement TBC / 局部构件；整体位置待确认 · ') : ''}View only · Drag to orbit</small></header><nav id="controls"></nav><div id="viewer"></div><div id="fallback" hidden></div><footer>Customer review · Provisional dimensions use yellow</footer><script id="a200-scene" type="application/json">${json}</script><script>${runtime.replaceAll('</script', '<\\/script')}</script></html>`;
      saveBlob(new Blob([html], { type: 'text/html;charset=utf-8' }), `${safeName(project.name)}-3D-R${project.revision}.html`); setNotice(t('Self-contained 3D file exported. / 已导出独立离线三维文件。'));
    });
  }
  function chooseContent(content: 'source' | 'current') {
    retainCanvasChoice(); setShowWorkingOutput(false); setReferenceContent(content); setDocumentTab('outputs'); setZoom(1);
    setView(content === 'source' ? 'reference' : preferredDrawingView(shown));
  }
  function openAssistant() {
    setReferenceContent('current'); setAssistantRequested(true);
    if (stage === 3 && has3DGeometry) openProject3D();
    if (stage === 4) { setBomDetail(true); setView('3d'); }
    else if (hasReferenceAssets && view === 'reference') setView(stage === 3 ? '3d' : preferredDrawingView(shown));
  }
  function adjustReference(parameter: StudioParameter, reference: StudioReferenceParameter) {
    if (changeLocked || !aiEnabled) return;
    const sharedOwners = model ? referenceOwnerIds(model, shown, parameter.id) : [];
    const ownerId = sharedOwners.includes(options.selected) ? options.selected : reference.owner_id;
    const owner = nodes.find(node => node.id === ownerId);
    if (owner) setOptions(previous => ({ ...previous, selected: owner.id }));
    setInstruction(t(
      `Adjust the reference value for ${reference.label || parameter.label || parameter.id} (${parameter.id})${ownerId ? ` on ${ownerId}` : ''}. Preserve the original source observations and evidence. Current reference: ${reference.value_mm} mm. New reference value: `,
      `调整${reference.label || parameter.label || parameter.id}（${parameter.id}）${ownerId ? `，所属构件 ${ownerId}` : ''}的参考值。保留原图记录和依据。当前参考值：${reference.value_mm} mm。新参考值：`,
    ));
    openAssistant();
  }
  function openMaterialSuggestions(scope: 'selection' | 'project' = 'project') {
    setError(''); setReplaceMaterials(false); setMaterialScope(scope); setMaterialSuggestionsOpen(true);
  }
  function suggestCuttingMaterials(scopeId?: string) {
    chooseStage(3);
    setReferenceContent('current'); openProject3D(); setLeftTab('tree'); setMaterialInstruction('');
    if (scopeId) select(scopeId);
    openMaterialSuggestions(scopeId ? 'selection' : 'project');
  }
  async function suggestMaterials(mode: MaterialSuggestionMode) {
    const preference = materialInstruction.trim();
    if (!project || changeLocked || (materialScopeAlreadyAssigned && !replaceMaterials) ||
      (mode === 'api' ? !aiEnabled || !health?.key_available : !!preference) ||
      (mode === 'prepared' && !hasReferenceAssets)) return;
    materialAppearanceBeforePreview.current = options.appearance;
    const status = mode === 'source' ? t('Matching source finishes to your material library…', '正在匹配原图饰面与材料库…')
      : mode === 'prepared' ? t('Preparing project palette…', '正在准备项目材料方案…') : t('Requesting material suggestions…', '正在请求材料建议…');
    const started = await run(status, async () => {
      const result = await studioAPI.materialSuggestions(project.id, project.revision, preference, materialScope === 'project' ? '' : options.selected, replaceMaterials, mode);
      setMaterialSuggestionsOpen(false); setReferenceContent('current'); setStage(3); setView('3d'); setLeftTab('tree');
      setRunningJob({ id: result.job_id, projectId: project.id, kind: 'materials' }); setJob({ status: 'queued', phase: 'queued', progress: 0 });
    });
    if (!started) materialAppearanceBeforePreview.current = null;
  }
  function retainCanvasChoice() {
    if (groupedJobId) handledGroupedPreviewJobs.current.add(groupedJobId);
  }
  function chooseStage(value: number, groupId?: string) {
    if (!project || importingPDF || (value === 4 && !canOpenCuttingList)) return;
    if (value !== 1) setPdfImport(null);
    const previousPreview = (stage === 3 || stage === 4) && value === 2
      ? working2DViews.find(item => item.view_id === returnTo2DPreview.current) : undefined;
    if (value === 3 && stage === 2) {
      returnTo2DPreview.current = workingOutputVisible ? workingView?.view_id || '' : '';
      const previewGroupId = workingOutputVisible ? workingView?.group_id
        || drawingGroups.find(group => workingView && group.view_ids.includes(workingView.view_id))?.id : undefined;
      const nextGroupId = groupId || previewGroupId;
      if (nextGroupId && nextGroupId !== draftGroup?.id) {
        setDraftGroupId(nextGroupId); setDraftViewId('');
      }
      if (groupId || previewGroupId && !hasSaved3DGeometry) setShowDraft(true);
    } else if (value === 1) returnTo2DPreview.current = '';
    setStage(value); setBomDetail(false); setShowWorkingOutput(false);
    if (value === 4) { setBomOpen(false); setLeftTab('source'); setDocumentTab('outputs'); return; }
    if (value === 3) {
      if (!groupId && isolatedBOMPart.current && options.isolate === isolatedBOMPart.current) showFullProject3D();
      setView('3d'); setLeftTab('source'); setDocumentTab('outputs');
      return;
    }
    if (value === 2) {
      if (previousPreview) {
        setWorkingViewId(previousPreview.view_id);
        setShowWorkingOutput(true);
      }
      setDocumentTab('outputs'); setView(hasReferenceAssets && referenceContent === 'source' ? 'reference' : preferredDrawingView(shown));
      setLeftTab('source');
      return;
    }
    retainCanvasChoice();
    setView('source'); setDocumentTab('customer'); setLeftTab('source');
  }
  function openWorkingOutput(viewId?: string) {
    if (!workingView || !workingResult) return;
    retainCanvasChoice();
    setStage(workingResult.kind === '3d' ? 3 : 2); setView(workingResult.kind === '3d' ? '3d' : preferredDrawingView(shown));
    if (workingResult.kind === '3d') setShowDraft(false);
    if (workingResult.kind === '2d') { setLeftTab('source'); setDocumentTab('outputs'); }
    if (viewId) {
      setWorkingViewId(viewId); setZoom(1);
      const groupId = working2DViews.find(item => item.view_id === viewId)?.group_id;
      if (workingResult.kind === '2d' && groupId) setBuild2DGroupId(groupId);
    }
    setShowWorkingOutput(true); setBomDetail(false);
  }
  function choose2DBuildGroup(groupId: string) {
    setBuild2DGroupId(groupId);
    const first = working2DViews.find(item => item.group_id === groupId);
    if (first) openWorkingOutput(first.view_id);
  }
  async function saveEditable3D(thenSuggest: boolean) {
    if (!project || changeLocked || project.grouped_3d_design_status?.status !== 'ready') return;
    await run(t('Saving 3D model', '正在保存三维模型'), async () => {
      const next = await studioAPI.save3DDesign(project.id, project.revision);
      const nextScene = await studioAPI.scene(project.id);
      chooseStage(3); showSaved3D(next, nextScene, project.revision); setJob(next.last_job ?? null);
      if (thenSuggest) { setMaterialInstruction(''); openMaterialSuggestions(); }
      await refreshList();
    });
  }
  function openCabinetSetup() {
    chooseStage(3); openProject3D(); setLeftTab('tree');
    const cabinet = cabinets.find(node => node.id === interiorTarget) || cabinets[0];
    if (cabinet) { setInteriorTarget(cabinet.id); select(cabinet.id); }
    requestAnimationFrame(() => document.querySelector<HTMLSelectElement>('.interior-section select')?.focus());
  }





  const applyBlockMessage = threeDPreviewHeld
    ? t('3D checks are incomplete; Apply is unavailable. Your saved 2D is unchanged.', '三维检查尚未完成，暂不能应用。已保存二维保持不变。')
    : proposal?.scene.drawing_quality?.model_preview
      ? t('No drawable model geometry is available; Apply is unavailable.', '尚无可绘制模型，暂不能应用。')
      : t('Drawing checks are incomplete; Apply is unavailable.', '图纸尚未通过检查，暂不能应用。');
  const currentDrawingVisible = !workingOutputVisible && !useReferenceViewer && !['source', '3d', 'reviewed'].includes(view);
  const currentDrawingLabel = drawingAsset ? drawingStatusText(effectiveDrawingStatus)
    : drawing ? shown?.drawing_quality?.model_preview ? t('Current design projection', '当前设计投影图') : t('Spatial checking view', '空间投影检查图') : drawingStatusText('incomplete');
  const notices: StudioNotice[] = [];
  if (error) notices.push({ id: 'action-error', title: t('Action could not be completed', '操作未完成'), tone: 'error', messages: [error], onDismiss: () => setError('') });
  if (notice) notices.push({ id: 'latest-message', title: t('Latest update', '最新消息'), messages: [notice], onDismiss: () => setNotice('') });
  if (job?.status === 'failed' && job.error_category === 'empty_suggestions' && job.material_suggestions?.unresolved?.length) {
    notices.push({ id: 'material-unmatched', title: t('Material suggestion details', '材料建议详情'), tone: 'warning',
      content: <MaterialSuggestionResults receipt={job.material_suggestions} nodes={nodes} /> });
  }
  if (projectInactive) notices.push({ id: 'project-state', title: t('Project status', '项目状态'), messages: [t('Viewing is available. Resume to edit.', '可继续查看，恢复后可编辑。')] });
  if (proposal) {
    notices.push({ id: 'preview', title: t('Preview changes', '预览修改'), messages: [proposal.summary],
      content: job?.proposal_id === proposal.id && job.material_suggestions
        ? <MaterialSuggestionResults receipt={job.material_suggestions} nodes={nodes} snapshots={model?.material_snapshots} /> : undefined });
    if (applyBlocked) notices.push({ id: 'apply-blocked', title: t('Apply unavailable', '暂不能应用'), tone: 'warning', messages: [applyBlockMessage] });
    if (proposal.warnings?.length) notices.push({ id: 'preview-review', title: t('Review notes', '审阅备注'), tone: 'warning', messages: proposal.warnings });
    if (proposal.scene.drawing_quality?.model_preview && !applyBlocked) notices.push({ id: 'model-preview', title: t('Design preview', '设计预览'), messages: [t('Current design preview. Review source dimensions and pending items before applying.', '当前设计预览。应用前请核对原图尺寸及待确认事项。')] });
  }
  if (shown?.project.pending?.length) notices.push({ id: 'pending-items', title: t('Items to confirm', '待确认事项'), tone: 'warning', messages: shown.project.pending.map(item => typeof item === 'string' ? item : JSON.stringify(item)) });
  if (stage === 2 && workflow2D) notices.push({ id: '2d-checks', title: t('2D checks', '二维检查'), tone: workflow2D.accepted ? 'success' : 'warning', content: <Autonomous2DStatus receipt={workflow2D} /> });
  if (stage === 3 && workflow3D) notices.push({ id: '3d-checks', title: workflow3D.accepted ? t('3D checks complete', '三维检查完成') : t('3D review pending', '三维审阅待完成'), tone: workflow3D.accepted ? 'success' : 'warning', messages: [t('The checked 2D drawings remain separate from this 3D preview.', '已检查二维图纸与本次三维预览分别保留。')] });
  if (currentDrawingVisible) notices.push({ id: 'current-drawing', title: t('Current drawing', '当前图纸'), tone: effectiveDrawingStatus === 'ready' ? 'success' : 'warning', messages: [currentDrawingLabel,
    ...(drawingAsset ? [`${drawingAsset.label} · ${drawingAsset.geometry_count} ${t('shapes', '个图形')} · ${drawingAsset.dimension_count} ${t('dimensions', '个尺寸')}`, t('Original dimension units · NTS', '保留原图标注单位 · 不按比例NTS')] : []),
    ...drawingIssues, ...(!drawing ? [t('This view lacks drawable contours; an object list does not establish drawing completeness.', '当前视图缺少可绘制轮廓；构件列表有内容不代表图纸完整。')] : [])] });
  if (view === '3d' && localFrames.length) notices.push({ id: '3d-scope', title: t('3D scope', '三维范围'), tone: 'warning', messages: [localFrame ? `${localFrame.label} · ${t('Local assembly; global placement TBC', '局部构件；整体位置待确认')}` : `${t('World view', '整体视图')} · ${localFrames.length} ${t('unplaced assemblies', '个构件位置待确认')}`,
    localFrame ? (localFrame.orientation_known ? t('Known local dimensions; no global location is asserted.', '显示已知局部尺寸，不代表已确定整体位置。') : t('Local axes only; global position and orientation remain TBC.', '仅使用局部坐标轴；整体位置与方向仍待确认。')) : t('Choose a local assembly in the 3D scope control to inspect known geometry.', '可在三维范围中选择局部构件，查看其已知结构。'), ...(localFrame?.issues || [])] });
  if (view === '3d' && webglError) notices.push({ id: '3d-view-error', title: t('3D view unavailable', '三维视图暂不可用'), tone: 'error', messages: [webglError] });
  if (project && (stage === 2 || stage === 3)) {
    const taskMessages = workflowTaskNotes({ job: taskJob ?? null, active: !!runningJob, startReason: stage === 2 ? twoDBlockReason : groupDraftMode ? draft3DBlockReason : threeDBlockReason });
    if (taskMessages.length) notices.push({ id: 'task', title: t('AI task', 'AI任务'), messages: taskMessages });
  }
  if (project) notices.push({ id: 'workflow-guide', title: t('Using this workspace', '工作区使用说明'), messages: [stage === 1
    ? t('Review the original pages here, then continue to create 2D drawings. Uploading does not start AI.', '在这里审阅原始页面，然后继续创建二维图纸。上传不会启动AI。')
    : stage === 2 ? t('Use the original PDF to create plans and elevations. Review each preview before saving.', '根据原始PDF创建平面和立面图。保存前请审阅每次预览。')
    : stage === 3 ? groupDraftMode
      ? t('Build and check all eligible 3D groups in source order, or use a named room button to build one. The app completes up to two build-and-check cycles for each room before starting the next.', '可以按原图顺序构建并检查所有符合条件的三维分组，也可以用房间按钮单独创建。应用会先完成当前房间最多两轮构建与检查，再处理下一个房间。')
      : t('Start with a plain model, then choose materials. This step starts only when you click Start 3D.', '先生成素模，再选择材料。只有点击开始三维才会启动。')
    : t('Review panel dimensions and materials before downloading Excel.', '下载Excel前，请核对板件尺寸和材料。'),
    ...(stage === 2 ? [t('For example: remove appearance hatch, correct a label, or adjust a yellow reference value. Keep the original source facts; attach a screenshot to identify the area.', '例如：移除外观填充、修正文字标签或调整黄色参考值。保留原图事实，可附加截图指出区域。')] : []),
    ...(aiEnabled && (stage === 2 || stage === 3) ? [runningJob ? t('Prepare feedback now. Send it after this task ends or stops; Resume keeps the existing request.', '现在可以准备反馈。任务结束或停止后再发送；恢复会继续现有请求。') : proposal ? t('Review the result first. Apply or Discard this preview before sending another request; the two-cycle allowance is not reset.', '请先审阅成果。应用或放弃预览后再发送其他请求，两轮额度不会重置。') : t('Review every change before applying it. You can write in English or Chinese and attach a screenshot.', '应用前请审阅每次修改。可以使用中文或英文，并附加截图。')] : [])] });

  if (closed) return <div className="studio"><main className="empty-canvas"><span className="empty-icon"><Icon name="check" /></span><h2>{t("应用已退出")}</h2><p>{t("项目保留在本地。可以关闭此标签页，重新打开 EXE 即可继续。 Your projects are saved. Close this tab and reopen the application to continue.")}</p></main></div>;
  const outputViews = drawingResults;
  const pendingOutput = !!proposal && !sourceOnlyFallback;
  const pendingDrawings = pendingOutput ? outputViews.filter(item => item.kind === 'drawing' && (shown?.drawings?.[item.id]?.geometry_count || 0) > 0) : [];
  const previewIds = new Set([...pendingDrawings.map(item => item.id), ...working2DViews.map(item => item.view_id)]);
  const workingOutputViews = working2DViews.filter(item => hasReferenceAssets || !pendingDrawings.some(drawing => drawing.id === item.view_id));
  const reviewedOutputCount = reference?.sections.reduce((sum, section) => sum + section.views.length, 0) || 0;
  const sidebarWorkingViews = stage === 3 ? workingResult?.kind === '3d' ? workingResult.views : [] : workingOutputViews;
  const outputCount = stage === 3
    ? Number(has3DGeometry) + draftSidebarViews.length + sidebarWorkingViews.length
    : (hasReferenceAssets ? reviewedOutputCount : outputViews.length) + sidebarWorkingViews.length;
  const projectModelResultId = 'project-model';
  const draftResults = draftSidebarViews.map(({ group, item }) => ({ id: `${group.id}:${item.view_id}`, group, item }));
  const working3DResults = stage === 3 ? sidebarWorkingViews.map(item => ({ id: `working:${item.view_id}`, item })) : [];
  const threeDResults: DrawingResultItem[] = [
    ...(has3DGeometry ? [{ id: projectModelResultId, label: t('Project model', '项目模型'), kind: 'projection' as const }] : []),
    ...draftResults.map(({ id, group, item }) => ({ id, label: item.label, kind: 'projection' as const,
      group: { id: group.id, label: drawingGroupName(group) } })),
    ...working3DResults.map(({ id, item }) => ({ id, label: item.label, kind: 'projection' as const,
      group: { id: 'working', label: t('Working output', '工作成果') } })),
  ];
  const selected3DResult = workingOutputVisible && workingResult?.kind === '3d' ? `working:${workingView?.view_id}` : groupDraftMode
    ? selectedDraftView && draftGroup ? `${draftGroup.id}:${selectedDraftView.view_id}` : ''
    : has3DGeometry ? projectModelResultId : '';
  function choose3DResult(id: string) {
    if (id === projectModelResultId) { showFullProject3D(); return; }
    const working = working3DResults.find(item => item.id === id);
    if (working) { openWorkingOutput(working.item.view_id); return; }
    const result = draftResults.find(item => item.id === id);
    if (result) { chooseDraftGroup(result.group.id, result.item.view_id); setShowWorkingOutput(false); }
  }
  const fullProjectAction = !groupDraftMode && view === '3d' && !workingOutputVisible && !!shown?.meshes.length && (options.isolate || localFrame)
    ? <button type="button" className="subtle" onClick={showFullProject3D}>{t('Show full project', '显示完整项目')}</button> : null;
  const savedDrawingCount = workflow?.reviewed_drawings ?? Object.keys(scene?.drawings || {}).length;
  const taskPhase = (taskPaused || taskPausing) ? taskJob?.resume_phase ?? taskJob?.phase : taskJob?.phase;
  // Group draft phases report 15–45% for the first cycle and 55–85% for the second.
  const draftSequence = taskJob?.draft_3d_sequence;
  const draftSequenceIndex = draftSequence?.findIndex(row => row.group_id === taskJob?.draft_3d_current_group_id) ?? -1;
  const draftSequenceGroup = drawingGroups.find(group => group.id === taskJob?.draft_3d_current_group_id);
  const draftProgressGroup = draftSequenceGroup ? drawingGroupName(draftSequenceGroup) : taskJob?.draft_3d_group_label;
  const draftGroupProgress = draftSequence ? taskJob?.draft_3d_group_progress : taskProgress;
  const draftCycle = (taskJob?.draft_3d_group_id || taskJob?.draft_3d_current_group_id) && draftGroupProgress !== undefined && /^(creating|rendering|checking)_3d$/.test(taskPhase || '')
    ? (draftGroupProgress >= 55 ? 2 : 1) : undefined;
  const taskPhaseLabel = phaseLabel(materialTask && taskPhase === 'reading_sources' ? 'reading_materials'
    : materialTask && taskPhase === 'receiving_model' ? 'receiving_materials' : taskPhase);
  const taskProgressHeld = !resumingTask && (interruptedTask || taskPaused || (materialTask && (taskPausing || requestingPause)));
  const taskBannerLabel = resumingTask ? t('Resuming the same task', '正在恢复同一任务')
    : interruptedTask ? t('Run interrupted', '任务已中断')
    : taskPaused ? t('Task paused', '任务已暂停')
    : taskPausing ? materialTask ? t('Pause requested', '已请求暂停') : t('Pausing after the current request', '当前请求完成后暂停')
    : requestingPause && materialTask ? t('Requesting a pause…', '正在请求暂停…')
    : taskPhaseLabel;
  const taskBannerHelp = interruptedTask
    ? projectInactive ? t('Select Resume project to see which recovery actions are available.', '请先恢复项目，再查看可用的恢复操作。')
      : resumeDraftSequence ? t('Resume 3D sequence continues the unfinished rooms and keeps the completed drafts.', '恢复三维顺序任务会继续处理尚未完成的房间，并保留已完成的草稿。')
      : canResume2D ? t('Completed groups and available previews are kept. An unfinished drawing may use its remaining cycle.', '已完成的分组和现有预览均会保留。尚未完成的图纸可能会使用剩余的一轮。')
      : job?.error_category === 'project_paused' ? t('An earlier project pause ended this run. Review any available results before starting again.', '此前暂停项目时结束了该任务。请在重新开始前查看现有成果。')
      : t('Studio closed before this task finished. Review any available results and use a group’s Retry if offered.', 'Studio 在任务完成前关闭。请查看现有成果，如有分组重试选项，可使用该选项。')
    : materialTask && (taskPaused || taskPausing || requestingPause)
      ? projectInactive ? t('Select Resume project to continue this material task.', '选择恢复项目即可继续此材料任务。')
        : taskPaused ? t('Resume continues this task from its last stage.', '恢复后将从上次阶段继续同一任务。')
        : t('The current step can finish. Studio will hold the result until you resume.', '当前步骤可以完成，Studio 会保留结果，直到您恢复任务。')
    : (taskPaused || taskPausing) && projectInactive
      ? t('Select Resume project to continue this drawing task.', '选择恢复项目即可继续此绘图任务。')
      : taskPaused && job?.resume_phase ? taskPhaseLabel : t("已保存的版本保持不变 · Your saved revision is preserved");
  function openCustomerPage(key: string) { retainCanvasChoice(); setShowWorkingOutput(false); setPageKey(key); setView('source'); setStage(1); setBomDetail(false); setDocumentTab('customer'); setZoom(1); }
  function openCurrentOutput(id: string) { retainCanvasChoice(); setShowWorkingOutput(false); setReferenceContent('current'); setDocumentTab('outputs'); setStage(2); setView(id); setZoom(1); }
  function selectDrawingResult(id: string) {
    if (!drawingResults.some(item => item.id === id)) return;
    setShowWorkingOutput(false); setReferenceContent('current'); setView(id); setZoom(1);
  }
  const referenceResults = reference?.sections.flatMap(section => section.views.map(item => ({
    id: JSON.stringify([section.id, item.id]), viewId: item.id, label: item.label, kind: 'reviewed' as const,
    page: item.source_page ?? item.page, group: { id: section.id, label: `${section.id} · ${section.title}` },
  }))) ?? [];
  const working2DResultVisible = workingOutputVisible && workingResult?.kind === '2d';
  const showWorking2DResults = working2DResultVisible || (!hasReferenceAssets && groupedWorkingItems.length > 0);
  const working2DResults: DrawingResultItem[] = groupedJob ? groupedWorkingItems
    : working2DResultVisible ? workingResult.views.map(item => ({ id: item.view_id, label: item.label, status: item.status, kind: 'drawing' })) : [];
  const showReviewed2DResults = hasReferenceAssets && referenceContent === 'source';
  const step2Results = showWorking2DResults ? working2DResults : showReviewed2DResults ? referenceResults : drawingResults;
  const step2ResultId = showWorking2DResults ? working2DResultVisible ? workingView?.view_id || '' : ''
    : view === 'source' ? '' : showReviewed2DResults ? JSON.stringify([referenceSection?.id, referenceImage?.id]) : view;
  function selectStep2Result(id: string) {
    if (showWorking2DResults) { openWorkingOutput(id); return; }
    if (showReviewed2DResults) {
      const result = referenceResults.find(item => item.id === id);
      if (result) chooseReference(result.group.id, result.viewId);
      return;
    }
    selectDrawingResult(id);
  }
  const continueTo3D = (has2DOutput || hasReferenceAssets || drawingGroups.length > 0)
    && <button className="secondary" onClick={() => chooseStage(3)}>{t('Continue to Step 3', '继续第3步')}</button>;
  const twoDContentToggle = hasReferenceAssets && view !== 'source'
    && <div className="design-content-toggle" role="group" aria-label={t('Design content', '设计内容')}>
      <button type="button" className={referenceContent === 'current' ? 'active' : ''} aria-pressed={referenceContent === 'current'}
        onClick={() => chooseContent('current')}>{t('Current design', '当前设计')}</button>
      <button type="button" className={referenceContent === 'source' ? 'active' : ''} aria-pressed={referenceContent === 'source'}
        onClick={() => chooseContent('source')}>{t('Reviewed drawings', '已审阅图纸')}</button>
    </div>;
  const reviewedPdfLinks = hasReferenceAssets && !!reference?.sections.length && <div className="reviewed-pdf-links" role="group"
    aria-label={t('Reviewed drawing PDFs', '已审阅图纸 PDF')}>
    {reference.sections.map(section => <a className="subtle" key={section.id}
      href={section.pdf_url || studioAPI.referenceAsset(section.pdf)} download={`${section.id}-Reviewed-Drawings.pdf`}>
      {section.id} · {section.title} PDF
    </a>)}
  </div>;
  const twoDOutputLabel = workingOutputVisible
    ? `${workingView?.label} · ${t(`Cycle ${workingCycle} · Not applied`, `第${workingCycle}轮 · 尚未应用`)}`
    : view === 'source' && activePage ? `${activePage.document.name} · ${t('Page', '页')} ${activePage.number}`
    : `${useReferenceViewer ? referenceImage?.label || t('Reviewed drawings', '已审阅图纸') : drawingResults.find(item => item.id === view)?.label || view} · ${t('Project R', '项目R')}${project?.revision}`;
  const twoDOutputIdentity = <div className="canvas-document-identity"
    data-content-kind={workingOutputVisible ? 'working-output' : view === 'source' ? 'customer-pdf' : 'design-output'}>
    <strong>{workingOutputVisible ? t('WORKING OUTPUT', '工作成果') : view === 'source' ? t('CUSTOMER PDF', '客户PDF') : t('DESIGN OUTPUT', '设计成果')}</strong>
    <span title={twoDOutputLabel}>{twoDOutputLabel}</span>
    {currentDrawingVisible && <button type="button" data-testid="drawing-quality"
      className={`drawing-state-chip ${effectiveDrawingStatus || 'incomplete'}`} onClick={openNotices}>{currentDrawingLabel}</button>}
  </div>;
  const draftSelector = draftGroup && <div className="group-3d-draft-options">
    <label htmlFor="draft-3d-group">{t('3D drawing group', '三维图纸分组')}</label>
    <select id="draft-3d-group" value={draftGroup.id} onChange={event => chooseDraftGroup(event.target.value)}>
      {drawingGroups.map(group => <option key={group.id} value={group.id}>{drawingGroupName(group)} · {
        runningJob && (job?.draft_3d_group_id === group.id || job?.draft_3d_current_group_id === group.id) ? t('Creating draft', '正在创建草稿')
          : runningJob && job?.draft_3d_sequence?.some(row => row.group_id === group.id && row.status === 'queued') ? t('Queued', '已排队')
          : retainedDrafts.has(group.id) ? t('Draft available', '草稿可用')
          : group.can_generate_3d_draft ? t('No draft yet', '暂无草稿') : t('Waiting for 2D', '等待二维成果')
      }</option>)}
    </select>
  </div>;
  const showDraftSequence = drawingGroups.length > 1;
  const draftSequenceReason = draftBlockReason(draftSequenceGroups[0] || draftGroup)
    || (!canStartDraftSequence ? t('Finish the remaining 2D groups in Step 2 before rebuilding all rooms.', '请先在第2步完成剩余二维分组，再重建所有房间。') : '');
  const grouped2DHasResults = !!working2DViews.length;
  const selected2DHasResults = !!build2DGroup && working2DViews.some(item => item.group_id === build2DGroup.id);
  const mapped2DUnavailable = t('This group cannot start a new run. Review the retained output and any available retry in Task details.',
    '此分组暂不能开始新任务。请在任务详情中审阅保留的成果，并查看是否可重试。');
  const groupAll2DReason = twoDBlockReason || (!grouped2DJob?.can_rebuild_2d ? mapped2DUnavailable : '');
  const groupSelected2DReason = twoDBlockReason || (!build2DGroup?.can_rebuild ? mapped2DUnavailable : '');
  const buildingAll2D = grouped2DEnabled && !analysisInstruction.trim();
  const twoDGroupScope = build2DGroup && drawingGroups.length > 1 && <div className="group-3d-draft-options">
    <label htmlFor="build-2d-group">{t('2D drawing group', '二维图纸分组')}</label>
    <select id="build-2d-group" value={build2DGroup.id} onChange={event => choose2DBuildGroup(event.target.value)}>
      {drawingGroups.map(group => <option key={group.id} value={group.id}>{drawingGroupName(group)}</option>)}
    </select>
  </div>;
  const twoDGroupAction = build2DGroup && drawingGroups.length > 1 ? {
    label: selected2DHasResults ? t('Rebuild selected 2D group', '重建所选二维分组') : t('Build selected 2D group', '构建所选二维分组'),
    onClick: () => void rebuildDrawingGroups(build2DGroup), secondary: true,
    disabled: twoDLocked || !!groupSelected2DReason, reason: groupSelected2DReason || undefined,
  } : undefined;
  const twoDBuildActions = canResume2D || retryProposalId ? undefined : build2DGroup
    ? <WorkflowBuildActions all={{
        label: grouped2DHasResults || has2DOutput || hasReferenceAssets ? t('Rebuild all 2D groups', '重建所有二维分组') : t('Build all 2D groups', '构建所有二维分组'),
        onClick: () => void rebuildDrawingGroups(), disabled: twoDLocked || !!groupAll2DReason,
        reason: groupAll2DReason || undefined,
      }} scope={compact2DPanel ? undefined : twoDGroupScope} selected={compact2DPanel ? undefined : twoDGroupAction} />
    : <WorkflowBuildActions all={{
        label: canMapSaved2D ? t('Rebuild all 2D groups', '重建所有二维分组') : saved2DReady || hasReferenceAssets
          ? t('Rebuild 2D', '重建二维')
          : buildingAll2D ? t('Build all 2D groups', '构建所有二维分组') : t('Build 2D', '构建二维'),
        onClick: () => void startAnalysis(canMapSaved2D), disabled: twoDLocked || !!(twoDBlockReason || unmapped2DBlockReason),
        reason: twoDBlockReason || unmapped2DBlockReason || undefined,
      }} />;
  const rebuildDraftSequence = retainedDrafts.size > 0 || hasSaved3DGeometry;
  const groupedSourceRequired = !draftSequenceGroups.length && (canMapSaved2D || canShowGroupedDraft && hasSaved3DGeometry);
  const prepareBeforeRebuild = hasSaved3DGeometry && (!threeDInputReady || groupedSourceRequired);
  const repairOriginalPDF = !hasOriginalPDF || threeDSourceStatus === 'source_unavailable';
  const nextDraftReason = nextDraftGroup ? draftBlockReason(nextDraftGroup) : '';
  const reviewInstructions = !!threeDInstruction.trim();
  const nextDraftAction = nextDraftGroup && <button type="button" className={reviewInstructions || canStartDraftSequence ? 'secondary' : 'primary'}
    disabled={!reviewInstructions && !!nextDraftReason} title={reviewInstructions ? undefined : nextDraftReason || undefined}
    onClick={() => reviewInstructions ? chooseDraftGroup(nextDraftGroup.id) : void startGroup3DDrafts(nextDraftGroup)}>
    {reviewInstructions ? t(`Go to ${drawingGroupName(nextDraftGroup)}`, `前往 ${drawingGroupName(nextDraftGroup)}`) : draftGroupActionLabel(nextDraftGroup, drawingGroups)}
  </button>;
  const draftAllAction: BuildAction | undefined = showDraftSequence ? {
    label: rebuildDraftSequence ? t('Rebuild all 3D groups', '重建所有三维分组') : t('Build all 3D groups', '构建所有三维分组'),
    onClick: () => void startGroup3DDrafts(), disabled: !!draftSequenceReason || !allDraftSourcesReady,
    reason: draftSequenceReason || draftSequenceGroups.map(drawingGroupName).join(' → '),
    describedBy: 'draft-sequence-hint',
  } : undefined;
  const draftSelectedAction: BuildAction = {
    label: draftStartLabel, onClick: () => void startGroup3DDrafts(draftGroup), disabled: !!draft3DBlockReason,
    reason: draft3DBlockReason || undefined,
  };
  const draftResumeAction: BuildAction | undefined = resumeSequenceGroup ? {
    label: t('Resume 3D sequence', '恢复三维顺序任务'), onClick: () => void startGroup3DDrafts(undefined, true),
    disabled: !!draftSequenceReason, reason: draftSequenceReason || undefined,
  } : undefined;
  const primaryDraftGroup = !draftGroup?.can_generate_3d_draft && draftSequenceGroups.length === 1 ? draftSequenceGroups[0] : undefined;
  const primaryDraftGroupReason = primaryDraftGroup ? draftBlockReason(primaryDraftGroup) : '';
  const primaryDraftAction = draftResumeAction || (draftSequenceGroups.length === 1 && primaryDraftGroup ? {
    label: draftGroupActionLabel(primaryDraftGroup, drawingGroups, retainedDrafts.has(primaryDraftGroup.id)),
    onClick: () => void startGroup3DDrafts(primaryDraftGroup), disabled: !!primaryDraftGroupReason, reason: primaryDraftGroupReason || undefined,
  } : draftSequenceGroups.length === 1 ? draftSelectedAction : draftAllAction || draftSelectedAction);
  const selectedDraftInDetails = primaryDraftAction !== draftSelectedAction;
  const useGroup3DActions = canShowGroupedDraft && !groupedSourceRequired;
  const threeDBuildAction: BuildAction = useGroup3DActions ? primaryDraftAction : {
        label: prepareBeforeRebuild
          ? groupedSourceRequired ? t('Rebuild all 3D groups', '重建所有三维分组')
            : repairOriginalPDF ? t('Check source PDF', '检查原始PDF') : t('Prepare 2D for rebuild', '准备重建所需的二维图纸')
          : has3DGeometry || hasSaved3DGeometry ? t('Rebuild 3D', '重建三维') : t('Build 3D', '构建三维'),
        onClick: prepareBeforeRebuild ? prepare3DSource : () => void start3D(),
        disabled: !!(prepareBeforeRebuild ? threeDTaskBlock : threeDBlockReason),
        reason: (groupedSourceRequired ? t('First rebuild the 2D groups in Step 2.', '请先在第2步重建二维分组。') : threeDBlockReason) || undefined,
  };
  const groupedDesign = project?.grouped_3d_design_status;
  const blockingGroup = drawingGroups.find(group => group.id === groupedDesign?.blocking_group_id);
  const blockedRoom = blockingGroup && drawingGroupName(blockingGroup);
  const requiresEditableDesign = hasReadOnlyDrafts && !!groupedDesign;
  const editableDesignAction: ProductionAction | undefined = !requiresEditableDesign ? undefined :
    groupedDesign.status === 'ready' ? {
      title: t('Save the 3D model', '保存三维模型'),
      description: t('Use the built rooms to create an editable model for materials and panel setup.', '使用已构建的房间生成可编辑模型，以便选择材料和设置板件。'),
      label: t('Open editable 3D', '打开可编辑三维'), onClick: () => void saveEditable3D(false), disabled: changeLocked,
    } : threeDInputReady ? {
      title: t('Build your editable model', '构建可编辑模型'),
      description: t('The saved 2D drawings are ready. Build and apply the editable 3D design to prepare panels and materials.', '已保存的二维图纸已就绪。构建并应用可编辑三维设计后即可准备板件和材料。'),
      label: t('Build editable 3D', '构建可编辑三维'), onClick: () => void start3D(), disabled: !!threeDBlockReason,
    } : {
      title: t('Finish the 3D build', '完成三维构建'),
      description: blockedRoom ? t(`Build ${blockedRoom} in Step 3 to complete the model.`, `在第3步构建 ${blockedRoom} 以完成模型。`)
        : t('Build the 3D model in Step 3 before setting up panels.', '在设置板件之前，请先在第3步构建三维模型。'),
      label: t('Go to Step 3', '前往第3步'), onClick: () => { chooseStage(3); if (blockingGroup) chooseDraftGroup(blockingGroup.id); },
    };
  const cabinetSetupAction: ProductionAction = {
    title: t('Add cabinet panels', '添加柜体板件'),
    description: t('Use Cabinet interior to preview and save your panels before choosing board materials.', '先在柜内设计中预览并保存板件，然后选择板材。'),
    label: t('Set up cabinet panels', '设置柜体板件'), onClick: openCabinetSetup, disabled: changeLocked,
  };
  const needsBoardMaterials = hasSaved3DGeometry && workflow?.bom_status === 'blocked' && !!workflow.bom_missing_material;
  const materialsLabel = t('AI material suggestions', 'AI材料建议');
  const firstMaterials = hasSaved3DGeometry && workflow?.bom_status !== 'ready' && !nodes.some(node => node.material_assignment);
  const draftMaterialsAction: ProductionAction | undefined = hasReadOnlyDrafts && groupedDesign?.status === 'ready' ? {
    title: t('Choose materials', '选择材料'),
    description: error || t('Use the 3D rooms already built. Material preferences are optional.', '使用已构建的三维房间。材料偏好可以留空。'),
    label: materialsLabel, onClick: () => void saveEditable3D(true), disabled: changeLocked,
  } : undefined;
  const nextProductionAction: ProductionAction | undefined = runningJob || resumeSequenceGroup ? undefined : proposal && (has3DGeometry || hasSaved3DGeometry) ? {
    title: job?.material_suggestions ? t('Review material suggestions', '审阅材料建议') : t('Review the design preview', '审阅设计预览'),
    description: applyBlocked ? t('Open the review notes to see what still needs attention.', '打开审阅备注，查看仍需处理的事项。')
      : t('Check the preview, then click Apply to save it and continue.', '核对预览，然后点击应用以保存并继续。'),
    label: t('Review preview', '审阅预览'), onClick: openNotices,
  } : draftMaterialsAction || (hasSaved3DGeometry && workflow ? needsBoardMaterials || firstMaterials ? {
    title: needsBoardMaterials ? t('Choose board materials', '选择板材') : t('Choose materials', '选择材料'),
    description: needsBoardMaterials ? t('Preview material suggestions, apply them, then open the cutting list.', '预览并应用材料建议，然后打开开料清单。')
      : t('Get suggestions for the saved 3D model. Material preferences are optional.', '为已保存的三维模型获取建议。材料偏好可以留空。'),
    label: materialsLabel, onClick: () => suggestCuttingMaterials(), disabled: changeLocked,
  } : workflow.bom_status === 'empty' ? cabinetSetupAction : {
    title: workflow.bom_status === 'ready' ? t('Cutting list ready', '开料清单已就绪') : t('Panel details needed', '需要补充板件信息'),
    description: workflow.bom_status === 'ready' ? t('Review your saved panels and download Excel in Step 4.', '在第4步核对已保存的板件并下载Excel。')
      : t('Open the cutting list to see the panels that still need specifications.', '打开开料清单，查看仍需补充规格的板件。'),
    label: workflow.bom_status === 'ready' ? t('Continue to Step 4', '继续第4步') : t('Review panel details', '核对板件信息'), onClick: () => chooseStage(4),
  } : undefined);
  const threeDBuildActions = <WorkflowBuildActions all={nextProductionAction?.label
    ? { ...threeDBuildAction, secondary: true } : threeDBuildAction} />;
  const continueTo4 = !nextProductionAction && !requiresEditableDesign && <button type="button" className="secondary" disabled={!canOpenCuttingList || importingPDF}
    title={!canOpenCuttingList ? t('Available when a 3D design or review draft is ready.', '三维设计或审阅草稿就绪后可继续。') : undefined}
    onClick={() => chooseStage(4)}>{t('Continue to Step 4', '继续第4步')}</button>;
  const threeDExtras = (!groupDraftMode || hasSaved3DGeometry) && <div className="compact-3d-tools" role="toolbar" aria-label={t('3D and material tools', '三维与材料工具')}>
    {nextProductionAction?.label !== materialsLabel && <button type="button" className="secondary" disabled={changeLocked || !has3DGeometry}
      onClick={() => groupDraftMode ? suggestCuttingMaterials() : openMaterialSuggestions()}>{materialsLabel}</button>}
    {!groupDraftMode && <div className="appearance-switch" role="group" aria-label={t('Model appearance', '模型外观')}>
      <button type="button" aria-pressed={options.appearance === 'outline'} className={options.appearance === 'outline' ? 'active' : ''}
        onClick={() => setOptions(previous => ({ ...previous, appearance: 'outline' }))}>{t('Plain', '素模')}</button>
      <button type="button" aria-pressed={options.appearance === 'material'} className={options.appearance === 'material' ? 'active' : ''}
        onClick={() => setOptions(previous => ({ ...previous, appearance: 'material' }))}>{t('Materials', '材质')}</button>
    </div>}
  </div>;
  const threeDDetails = <>
    {useGroup3DActions && <WorkflowBuildActions scope={draftSelector}
      all={draftAllAction && draftAllAction !== primaryDraftAction ? { ...draftAllAction, secondary: true } : undefined}
      selected={selectedDraftInDetails ? { ...draftSelectedAction, secondary: true } : undefined} />}
    {hasSaved3DGeometry && threeDInputReady && (useGroup3DActions || groupedSourceRequired) && <button type="button" className="secondary"
      disabled={!!threeDBlockReason} onClick={() => void start3D()}>{t('Rebuild editable 3D model', '重建可编辑三维模型')}</button>}
    {!useGroup3DActions && !runningJob && (groupedSourceRequired || threeDBlockReason) && <span className="workflow-task-reason">{groupedSourceRequired
      ? t('First rebuild the 2D groups in Step 2. Your saved model remains available while you review new room drafts.', '请先在第2步重建二维分组。审阅新房间草稿期间，仍可查看已保存的模型。') : threeDBlockReason}</span>}
    {!groupDraftMode && workflow3D && <button type="button" data-testid="3d-quality"
      className={`drawing-state-chip ${workflow3D.accepted ? 'ready' : 'needs_review'}`} onClick={openNotices}>
      {workflow3D.accepted ? t('3D checks complete', '三维检查完成') : t('3D review pending', '三维审阅待完成')}</button>}
    {!groupDraftMode && localFrames.length > 0 && <button type="button" data-testid="3d-scope-status"
      className="drawing-state-chip needs_review" onClick={openNotices}>
      {localFrame ? t('Local assembly', '局部构件') : t('Placement needs review', '位置需要核对')}</button>}
  </>;
  return <div className={`studio ${isShowcase && presentation ? 'presentation' : ''}`} onCompositionStartCapture={() => { inputComposing.current = true; }} onCompositionEndCapture={() => { inputComposing.current = false; }} onKeyDownCapture={event => { if (event.key === 'Enter' && (inputComposing.current || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229)) event.preventDefault(); }} onSubmitCapture={event => { if (inputComposing.current) { event.preventDefault(); event.stopPropagation(); } }}>
    <header className="studio-header">
      <button type="button" className="brand brand-home" aria-label={t("Go to home", "返回主页")} disabled={!!busy} onClick={goHome}><div className="brand-mark"><svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M4 10.5 16 4l12 6.5L16 17 4 10.5Z" fill="currentColor" fillOpacity=".06" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="m4 15.5 12 6.5 12-6.5M4 20.5 16 27l12-6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /><path d="M23.5 27.5H28m-4.5 3H28" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" /></svg></div><div><div className="brand-name">FormToPart <span>Studio</span></div><div className="brand-caption">{t("Design · Materials · BOM", "设计 · 材料 · BOM")}</div></div></button>
      <div className="project-switch"><Icon name="folder" /><select aria-label={t("Current project / 当前项目")} value={project?.id || ''} disabled={globalLocked} onChange={event => void run(t('Opening project / 正在打开项目'), () => loadProject(event.target.value))}><option value="" disabled>{t("选择项目 / Choose project")}</option>{projects.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>{project && <span className="revision-pill">R{project.revision}</span>}</div>
      <div className="header-actions"><NoticeCenter notices={notices} contextKey={project?.id || 'home'} requestOpen={noticeRequest} /><label className="language-switch"><span className="sr-only">{t("Interface language", "界面语言")}</span><select aria-label={t("Interface language", "界面语言")} value={language} onChange={event => setLanguage(event.target.value as "en" | "zh")}><option value="en">English</option><option value="zh">{language === "en" ? "Chinese" : "中文"}</option></select></label><span className={`connection-pill ${health?.key_available ? 'online' : 'offline'}`} title={aiEnabled ? health?.model || t('Design Studio', '设计工作室') : t('Design Studio', '设计工作室')}><i />{!health || !aiEnabled ? t('Design Studio', '设计工作室') : health?.key_available ? `${modelDisplayName(health.model)} · High` : t('待连接 AI')}</span><button className="secondary" disabled={globalLocked} onClick={event => { newProjectOpener.current = event.currentTarget; setNewProjectOpen(true); }}><Icon name="plus" />{t("新建项目")}</button><button className="icon-button" aria-label={t("Assistant settings", "设计助手设置")} title={t("Assistant settings", "设计助手设置")} disabled={!!busy} onClick={() => setKeySettingsOpen(true)}><Icon name="settings" /></button><button className="icon-button" aria-label={t("Refresh / 刷新")} title={t("Refresh project / 刷新项目")} disabled={globalLocked} onClick={() => void run(t('Refreshing / 正在刷新'), async () => { setHealth(await studioAPI.health()); await refreshList(); if (project) await loadProject(project.id); })}><Icon name="refresh" /></button><button className="icon-button" aria-label={t("Exit application / 退出应用")} title={t("退出应用 / Exit application")} disabled={globalLocked} onClick={() => void run(t('Closing application / 正在退出应用'), async () => { await studioAPI.shutdown(); setClosed(true); })}><Icon name="power" /></button></div>
    </header>
    {(project || !interviewBuild) && <nav className="stage-bar" aria-label={t('Design steps', '设计步骤')}>{[
      { n: 1, title: t('Upload PDF', '上传PDF'), sub: `${pages.length} ${t('source pages', '页原图')}` },
      { n: 2, title: t('Create & review 2D', '创建与审阅二维'), sub: previewIds.size
        ? t(`${savedDrawingCount} saved · ${previewIds.size} previews`, `${savedDrawingCount} 张已保存 · ${previewIds.size} 张预览`)
        : `${savedDrawingCount} ${t('drawings', '张图纸')}` },
      { n: 3, title: t('3D & materials', '三维与材料'), sub: !hasSaved3DGeometry && canShowGroupedDraft && retainedDrafts.size
        ? draftMaterialsAction ? t(`${retainedDrafts.size} rooms built`, `${retainedDrafts.size} 个房间已构建`)
          : retainedDrafts.size === 1 ? t('1 review draft', '1 个审阅草稿') : t(`${retainedDrafts.size} review drafts`, `${retainedDrafts.size} 个审阅草稿`)
        : workflow ? `${workflow.model_meshes} ${t('model parts', '个三维构件')}` : t('Create 3D · Structure · Materials', '创建三维 · 结构 · 材料') },
      { n: 4, title: t('Cutting list Excel', 'Excel开料清单'), sub: hasReadOnlyDrafts
        ? t('Saved design needed', '需要已保存的设计')
        : workflow?.bom_status === 'blocked' ? t('Panel details needed', '需补充板件信息')
          : workflow ? `${workflow.bom_boards} ${t('panels', '块板件')} · ${workflow.bom_rows} ${t('rows', '项明细')}` : t('Review panels · Download Excel', '审阅板件 · 下载Excel') }
    ].map(item => <button key={item.n} className={`stage ${stage === item.n ? 'active' : ''} ${item.n === 2 && drawingsComplete ? 'complete' : ''}`} aria-current={stage === item.n ? 'step' : undefined} disabled={!project || (importingPDF && item.n !== stage) || (item.n === 4 && !canOpenCuttingList)} title={item.n === 4 && !canOpenCuttingList ? t('Create or import a 3D design to review the cutting list.', '请先创建或导入三维设计，再审阅开料清单。') : undefined} onClick={() => chooseStage(item.n)}><span className="stage-number">{item.n === 2 && drawingsComplete ? <Icon name="check" /> : `0${item.n}`}</span><span><strong>{item.title}</strong><small>{item.sub}</small></span></button>)}<span className="stage-note">{t('PDF → 2D → 3D → Excel', 'PDF → 二维 → 三维 → Excel')}</span></nav>}

    {visiblePdfImport && <PdfImportStatus state={visiblePdfImport} onDismiss={() => setPdfImport(null)} />}
    {error && !(visiblePdfImport && 'message' in visiblePdfImport && visiblePdfImport.message === error) && <span className="sr-only" role="alert">{t('An action needs attention. Open Notices for details.', '有操作需要处理，请打开通知查看详情。')}</span>}
    {project && <div className="project-control-bar">
      <div><span className={`project-status ${project.lifecycle || 'active'}`}>{project.lifecycle === 'paused' ? t('Paused', '已暂停') : project.lifecycle === 'stopped' ? t('Stopped', '已停止') : t('Active', '进行中')}</span></div>
      <div>
        {projectInactive && <button className="primary" disabled={!!busy} onClick={() => void changeLifecycle('resume')}>{t('Resume project', '恢复项目')}</button>}
        <details className="project-controls-menu">
          <summary>{t('Project options', '项目选项')}</summary>
          <div>
            <button className="subtle" disabled={!!busy || !!runningJob} onClick={event => {
              const menu = event.currentTarget.closest('details');
              const opener = menu?.querySelector('summary') || event.currentTarget;
              if (menu) menu.open = false;
              openRename(project, opener);
            }}>{t('Rename project', '重命名项目')}</button>
            {!projectInactive && <>
              <p>{runningJob?.kind === 'materials'
                ? t('Pause project holds the current material task. Resume project continues it. Stop project ends the task.', '暂停项目会暂停当前材料任务，恢复项目会继续该任务，停止项目会结束该任务。')
                : runningJob && job?.kind && job.kind !== 'analyze'
                ? t('Pausing or stopping the project ends this task. Use Pause task to continue the same run later.', '暂停或停止项目会结束此任务。若要稍后继续同一任务，请选择暂停任务。')
                : t('Pause lets you continue the same 2D drawing task while Studio stays open. Stop ends the current task.', 'Studio 保持打开时，暂停后可继续同一二维绘图任务。停止会结束当前任务。')}</p>
              <button className="subtle" disabled={!!busy} onClick={event => { event.currentTarget.closest('details')?.removeAttribute('open'); void changeLifecycle('pause'); }}>{t('Pause project', '暂停项目')}</button>
              <button className="subtle" disabled={!!busy} onClick={() => setStopDialog(true)}>{t('Stop project', '停止项目')}</button>
            </>}
          </div>
        </details>
        <button className="subtle danger-text" disabled={!!busy || !!runningJob || project.can_delete === false}
          title={project.can_delete === false ? t('This project cannot be deleted.', '此项目暂不能删除。') : undefined}
          onClick={() => setDeleteTarget({ ...project, document_count: project.documents.length, updated_at: '' })}>{t('Delete project', '删除项目')}</button>
      </div>
    </div>}
    {(runningJob || interruptedTask) && <div className={`job-banner${materialTask ? ' material-job-banner' : ''}${taskProgressHeld ? ' progress-held' : ''}`}>
      <span aria-hidden="true" className={taskProgressHeld ? 'paused-job-mark' : 'busy-spinner'}>{taskProgressHeld ? interruptedTask ? '!' : 'Ⅱ' : null}</span>
      <div role="status" className="job-banner-status"><strong><span>{taskBannerLabel}</span>{draftSequence && draftSequenceIndex >= 0 && ` · ${t(`Group ${draftSequenceIndex + 1} of ${draftSequence.length}`, `第 ${draftSequenceIndex + 1} 组，共 ${draftSequence.length} 组`)}`}{draftProgressGroup ? ` · ${draftProgressGroup}` : ''}{draftCycle && ` · ${t(`Cycle ${draftCycle} of 2`, `第 ${draftCycle} 轮，共 2 轮`)}`}</strong><small>{taskBannerHelp}</small></div>
      {materialControlsInBanner && !projectInactive && <div className="material-task-controls" role="group" aria-label={t('Material task controls', '材料任务控制')}>
        <TaskControls status={taskJob?.status} disabled={!!busy || requestingPause || resumingTask} onControl={action => void controlTask(action)} hidePausingButton />
      </div>}
      {(!interruptedTask || taskProgress !== undefined) && <div
        className="job-progress"
        role="progressbar" aria-label={materialTask ? t('Material task progress', '材料任务进度') : t(`${activeDimension} task progress`, `${activeDimension}任务进度`)}
        aria-valuemin={0} aria-valuemax={100} aria-valuenow={taskProgress}
        aria-valuetext={interruptedTask ? t(`Last recorded progress ${taskProgress}%`, `上次记录的进度为 ${taskProgress}%`)
          : materialTask && taskProgress !== undefined ? t(`${taskProgress}% through task stages`, `任务阶段进度 ${taskProgress}%`) : undefined}>
        <i style={{ width: `${taskProgress ?? 0}%` }} />
      </div>}
      {taskProgress !== undefined && <span className="job-percent">{taskProgress}%</span>}
    </div>}
    {!runningJob && job?.kind === 'materials' && job.status === 'cancelled' && notice === taskStoppedMessage() &&
      <div className="global-alert notice material-stop-notice">
        <span role="status">{notice}</span>
        <button type="button" className="alert-dismiss" aria-label={t('Dismiss task message', '关闭任务消息')} onClick={() => setNotice('')}><Icon name="close" /></button>
      </div>}

    {!project && interviewBuild ? <ProjectHome projects={projects} showcase={showcase} busy={!!busy} onShowcase={() => void openShowcase()} onOpen={id => void run(t("Opening project…", "正在打开项目…"), () => loadProject(id, true))} onNew={() => setNewProjectOpen(true)} onImport={() => importInput.current?.click()} onRename={openRename} onDelete={setDeleteTarget} /> : !project ? <main className="welcome"><div className="welcome-copy"><div className="welcome-eyebrow">FROM CUSTOMER DRAWING TO CABINET DESIGN</div><h1>{t("让原图，成为")}<br /><em>{t("可以推敲的设计。")}</em></h1><p>{t("Import a drawing. Shape the interior. Explore it in 3D. 导入客户原图，设计柜体内部，用三维检查每一处细节。")}</p><div className="welcome-actions"><button className="primary" disabled={locked} onClick={() => uploadInput.current?.click()}><Icon name="upload" />{t("导入客户图纸")}</button><button className="secondary" disabled={locked} onClick={() => void openDemo()}>{t("打开 A200 + A202 演示")}<span>↗</span></button>{health?.reviewed_demo && <button className="secondary" disabled={locked} onClick={() => void openReviewedDemo()}>{t("打开已审核 A200 + A202 / Reviewed example")}<span>↗</span></button>}{health?.prepared_demo && <button className="secondary" disabled={locked} onClick={() => void openPreparedDemo()}>{t("打开已准备的盥洗柜演示 / Ready vanity pilot")}<span>↗</span></button>}</div><div className="demo-file"><Icon name="source" /><span>{t("原始PDF · 文件保存在本地")}<br /><small>PDF · Local project storage</small></span></div></div><div className="welcome-mark"><svg viewBox="0 0 380 350" fill="none" aria-hidden="true"><path d="m70 110 140-60 110 65-140 65-110-70Zm0 0v160l110 65 140-65V115M180 180v155" stroke="currentColor" strokeWidth="2" /><path d="m70 155 110 65 140-65M70 220l110 65 140-65M127 147v155M240 151v157" stroke="currentColor" strokeWidth="1.3" /><path d="m70 110 110 70 140-65-110-65-140 60Z" fill="currentColor" opacity=".04" /><circle cx="70" cy="110" r="4" fill="currentColor" /><circle cx="180" cy="180" r="4" fill="currentColor" /><circle cx="320" cy="115" r="4" fill="currentColor" /></svg><span>DRAW · DESIGN · EXPLORE</span></div><div className="welcome-steps"><div className="welcome-step"><b>01</b><strong>{t("Upload PDF", "上传PDF")}</strong><span>{t("Original customer drawings", "客户原始图纸")}</span></div><div className="welcome-step"><b>02</b><strong>{t("Create & review 2D", "创建与审阅二维")}</strong><span>{t("Plans and elevations", "平面与立面图")}</span></div><div className="welcome-step"><b>03</b><strong>{t("3D & materials", "三维与材料")}</strong><span>{t("Plain model, then materials", "先素模，再选材料")}</span></div><div className="welcome-step"><b>04</b><strong>{t("Cutting list Excel", "Excel开料清单")}</strong><span>{t("Review panels and export", "审阅板件并导出")}</span></div></div></main>
      : <main className={`studio-body ${stage === 1 ? "source-step" : ""} ${cuttingListVisible ? "cutting-list-mode" : ""}`}>
        <aside className="left-panel"><div className="panel-tabs"><button className={leftTab === 'source' ? 'active' : ''} onClick={() => setLeftTab('source')}><Icon name="source" />{t("Documents", "文档")}</button>{stage !== 1 && <button className={leftTab === 'tree' ? 'active' : ''} onClick={() => { if (stage === 3 && has3DGeometry) openProject3D(); setLeftTab('tree'); }}><Icon name="box" />{t("构件 Objects")}</button>}</div>
          {leftTab === 'source' ? <div className="left-scroll documents-panel"><div className="document-segments" role="group" aria-label={t('Document collection', '文档分类')}><button type="button" aria-pressed={documentTab === 'customer'} className={documentTab === 'customer' ? 'active' : ''} onClick={() => setDocumentTab('customer')}>{t('Customer PDF', '客户PDF')} ({pages.length})</button>{stage !== 1 && <button type="button" aria-pressed={documentTab === 'outputs'} className={documentTab === 'outputs' ? 'active' : ''} onClick={() => setDocumentTab('outputs')}>{t('Design outputs', '设计成果')} ({outputCount})</button>}</div>
            {documentTab === 'customer' ? <><div className="panel-heading"><strong>{t('Customer documents', '客户文件')}<small>{project.documents.length} {t('files', '个文件')}</small></strong><button className="icon-button" aria-label={t('Add source', '添加原图')} disabled={changeLocked} onClick={() => uploadInput.current?.click()}><Icon name="plus" /></button></div><div className="source-list">{pages.map(page => <button key={page.key} className={`source-card ${view === 'source' && page.key === activePage?.key ? 'selected' : ''}`} title={`${page.document.name} · Page ${page.number}`} onClick={() => openCustomerPage(page.key)}><div className="source-thumb"><img src={page.preview_url} alt={`${page.document.name} page ${page.number}`} loading="lazy" /><span>P{page.number}</span></div><span className="source-meta"><small className="document-kind">{t('CUSTOMER PDF', '客户PDF')}</small><strong>{page.document.name}</strong><small>{t('Page', '页')} {page.number}</small></span></button>)}</div>{!pages.length && <div className="tree-empty"><Icon name="upload" /><p>{t('Import a customer drawing to begin.', '请先导入客户图纸。')}</p></div>}<div className="source-actions"><button className="secondary full-width" disabled={changeLocked} onClick={() => uploadInput.current?.click()}><Icon name="upload" />{t('Add original PDF', '添加原始PDF')}</button></div></> : <>
              <div className="panel-heading"><strong>{t('Design outputs', '设计成果')}<small>{groupDraftMode ? t('Read-only draft', '只读草稿') : t(`Saved R${project.revision}`, `已保存 R${project.revision}`)}</small></strong></div>
              {stage === 3 ? <div className="source-map-list">
                {has3DGeometry && <button type="button" className={`source-map-card ${selected3DResult === projectModelResultId && !workingOutputVisible ? 'selected' : ''}`}
                  onClick={showFullProject3D}>
                  <small className="document-kind">{t('3D DESIGN', '三维设计')}</small>
                  <span>{t('Project model', '项目模型')}</span>
                  <small>{pendingOutput ? t('Preview', '预览') : `R${project.revision}`}</small>
                </button>}
                {draftResults.map(({ id, group, item }) => <button type="button" key={id} className={`source-map-card ${selected3DResult === id ? 'selected' : ''}`}
                  aria-current={selected3DResult === id || undefined} onClick={() => choose3DResult(id)}>
                  <small className="document-kind">{t('3D REVIEW DRAFT', '三维审阅草稿')}</small>
                  <span>{item.label}</span><small>{drawingGroupName(group)}</small>
                </button>)}
                {!outputCount && <p className="tree-empty">{groupDraftMode ? t('No rendered 3D views yet.', '暂无三维渲染视图。')
                  : t('No project 3D results yet.', '暂无项目三维成果。')}</p>}
              </div> : hasReferenceAssets && reference ? <ReferenceSourceList manifest={reference}
                sectionId={referenceSection?.id || ''} viewId={useReferenceViewer && !workingOutputVisible ? referenceImage?.id || '' : ''}
                onSelect={chooseReference} /> : <div className="source-map-list">
                {outputViews.map(item => <button type="button" key={item.id} className={`source-map-card ${!workingOutputVisible && referenceContent === 'current' && view === item.id ? 'selected' : ''}`} onClick={() => openCurrentOutput(item.id)}>
                  <small className="document-kind">{pendingOutput ? t('PREVIEW', '预览') : `${t('OUTPUT', '成果')} · R${project.revision}`}</small>
                  <span>{t(item.label)}</span>
                  <small>{pendingOutput ? item.status === 'ready' ? t('Awaiting Apply', '等待应用') : t('Needs review', '需要审阅') : t('Current design', '当前设计')}</small>
                </button>)}
                {!outputCount && <p className="tree-empty">{runningJob && stage === 2
                  ? (taskPaused ? t('Drawing is paused. Previews will appear here after drawing resumes.', '绘图已暂停。恢复绘图后，预览会出现在这里。') : t('Studio is preparing drawings. Previews will appear here as each group renders.', 'Studio 正在准备图纸。每组渲染后，预览会出现在这里。'))
                  : interruptedTask && stage === 2 ? t('No drawing preview was saved before the interruption.', '任务中断前尚未保存图纸预览。')
                  : no2DResult ? t('This 2D run produced no drawings. Open Notices for details.', '本次二维任务未生成图纸。请查看通知中的详情。')
                  : t('Generate or import a design to see its outputs.', '生成或导入设计后可查看成果。')}</p>}
              </div>}
              {!groupDraftMode && !!sidebarWorkingViews.length && <div className="source-map-list">
                {sidebarWorkingViews.map(item => <button type="button" key={item.view_id} className={`source-map-card ${workingOutputVisible && workingView?.view_id === item.view_id ? 'selected' : ''}`} onClick={() => openWorkingOutput(item.view_id)}>
                  <small className="document-kind">{t('WORKING OUTPUT', '工作成果')} · {t(`Cycle ${item.cycle ?? workingResult?.cycle}`, `第 ${item.cycle ?? workingResult?.cycle} 轮`)}</small>
                  <span>{item.group_label && <small>{item.group_label} · </small>}{item.label}</span>
                  <small>{t('Preview', '预览')} · {(item.status ?? workingResult?.status) === 'needs_review' ? t('Needs review', '需要审阅') : t('Not applied', '未应用')}</small>
                </button>)}
              </div>}
            </>}
          </div>
            : <div className="left-scroll"><div className="panel-heading"><strong>{t("构件层级")}<small>{nodes.length} objects</small></strong></div>{model?.root ? <ul className="tree-list"><Tree key={project.id} node={{ ...model.root, name: project.name }} selected={options.selected} onSelect={id => { select(id); if (stage === 4) { setBomDetail(true); setView("3d"); } }} /></ul> : <div className="tree-empty">{t("分析原图后显示构件 Analyze sources to see objects")}</div>}</div>}
          <div className="left-bottom"><button className="subtle" disabled={globalLocked} onClick={() => importInput.current?.click()}><Icon name="folder" />{t("打开项目文件")}</button><span>{t("所有更改按版本保存")}</span></div>
        </aside>
        <section className="main-panel"><div className="workspace-toolbar"><div className="toolbar-left">
          <button type="button" className="workspace-project-name" disabled={locked}
            aria-label={`${t('Rename project', '重命名项目')} ${project.name}`}
            title={`${t('Rename project', '重命名项目')} — ${project.name}`}
            onClick={event => openRename(project, event.currentTarget)}>
            <strong>{project.name}</strong><Icon name="pencil" />
          </button>
          <span className="saved-indicator">{proposal ? t('预览未保存 · Preview') : t('已保存 · Saved')} R{project.revision}</span>{proposal && <button type="button" className={`preview-notice-link ${applyBlocked ? 'held' : ''}`} onClick={openNotices}>{applyBlocked ? t('Apply unavailable', '暂不能应用') : t('Preview details', '预览详情')}</button>}</div><div className="toolbar-right">{proposal && <div className="proposal-actions"><span>{t("基于 R")}{proposal.base_revision}</span>{canRegenerate && aiEnabled && <button className="secondary redraw-button" disabled={locked} onClick={() => void regenerateProposal()}><Icon name="refresh" />{t("重新生成联动图纸 Regenerate linked drawings")}</button>}<button className="secondary" disabled={locked || projectInactive} onClick={() => void discardProposal()}>{t("放弃 Discard")}</button><button className="primary" disabled={locked || projectInactive || applyBlocked} title={applyBlocked ? t('Resolve incomplete or outdated drawing views before Apply / 请先处理不完整或过期的图纸视图') : undefined} onClick={() => void applyProposal()}><Icon name="check" />{t("应用并保存 Apply")}</button></div>}{aiEnabled && <button type="button" className="secondary" disabled={globalLocked || groupDraftMode && !has3DGeometry} onClick={openAssistant}>{t("Adjust with assistant", "通过助手修改")}</button>}{stage === 4 && <button type="button" className="secondary" onClick={() => setMaterialLibrary("manage")}>{t("Material library", "材料库")}</button>}{stage === 4 && bomDetail && fullProjectAction}{stage === 4 && bomDetail && <button type="button" className="secondary" onClick={() => setBomDetail(false)}>{t("Back to cutting list", "返回开料清单")}</button>}{isShowcase && <button type="button" className="secondary presentation-toggle" aria-pressed={presentation} onClick={() => setPresentation(value => !value)}>{presentation ? t("Show details", "显示详情") : t("Presentation", "演示模式")}</button>}<button className="icon-button" aria-label={t("Undo / 撤销")} title={t("Undo / 撤销")} disabled={changeLocked || !undoStack.length} onClick={() => void restore(undoStack.at(-1)!, 'undo')}><Icon name="undo" /></button><button className="icon-button" aria-label={t("Redo / 重做")} title={t("Redo / 重做")} disabled={changeLocked || !redoStack.length} onClick={() => void restore(redoStack.at(-1)!, 'redo')}><Icon name="redo" /></button><details className="export-menu"><summary><Icon name="export" />{t("导出 Export")}</summary><div>{has2DOutput && <button disabled={!drawingsComplete || workingOutputVisible} onClick={() => void run(t('Preparing the drawing PDF', '\u6b63\u5728\u51c6\u5907\u56fe\u7eb8 PDF'), async () => { const response = await fetch(studioAPI.drawingSetURL(project.id, proposal?.id)); if (!response.ok) throw new Error(t('The drawing group is not ready to export.', '\u56fe\u7eb8\u7ec4\u5c1a\u4e0d\u80fd\u5bfc\u51fa\u3002')); saveBlob(await response.blob(), `${safeName(project.name)}-2D-R${exportRevision}.pdf`); })}>{t('All 2D drawings PDF', '\u5168\u90e8\u4e8c\u7ef4\u56fe\u7eb8 PDF')}</button>}<button disabled={!canExportDrawing} onClick={() => { if (drawing) saveBlob(new Blob([drawing], { type: 'image/svg+xml;charset=utf-8' }), `${safeName(project.name)}-${drawingAsset?.id || drawingView}-R${exportRevision}.svg`); }}>{t("二维图纸 SVG")}</button>{hasReferenceAssets && referenceContent === "source" && referenceSection && <a href={referenceSection.pdf_url || studioAPI.referenceAsset(referenceSection.pdf)} download={`${referenceSection.id}-Reviewed-Drawings.pdf`}>{t("Reviewed source PDF", "已审阅原图PDF")}</a>}{drawingAsset && <a className={!canExportDrawing ? 'disabled' : ''} aria-disabled={!canExportDrawing} href={canExportDrawing ? studioAPI.drawingURL(project.id, drawingAsset.id, 'pdf', proposal?.id) : undefined} download>{t("二维图纸 PDF")}</a>}<button disabled={locked || !canCaptureView || (view !== '3d' && view !== 'source' && !canExportDrawing && !referenceMedia)} onClick={() => void run(t('Exporting image / 正在导出图像'), async () => saveBlob(await captureView(), `${safeName(project.name)}-${view}${view === '3d' && localFrame ? '-local-' + safeName(localFrame.root_id) : ''}-R${exportRevision}.png`))}>{t("当前视图 PNG")}</button><button disabled={locked} onClick={() => setBomOpen(true)}>{t("Excel 开料清单 Cutting list")}</button><button disabled={changeLocked || !viewerScene?.meshes.length} onClick={() => void exportHTML()}>{t('3D viewer HTML', '三维查看器HTML')}</button><a className={changeLocked ? 'disabled' : ''} href={changeLocked ? undefined : studioAPI.archiveURL(project.id)} download>{t("项目备份 Project archive")}</a></div></details></div></div>
          {cuttingListVisible ? <BOMSheet projectId={project.id} revision={project.revision} pending={!!proposal} embedded
            readOnlyDrafts={hasReadOnlyDrafts} onBackTo3D={() => chooseStage(3)}
            nextAction={editableDesignAction || (hasSaved3DGeometry && workflow?.bom_status === 'empty' ? cabinetSetupAction : undefined)}
            onSuggestMaterials={hasSaved3DGeometry && !changeLocked ? suggestCuttingMaterials : undefined}
            onChooseBoardStock={hasSaved3DGeometry && !changeLocked ? chooseBOMBoardStock : undefined}
            onPreviewPanelSpecs={hasSaved3DGeometry ? report => void previewBoardSpecs(report) : undefined}
            panelPreviewDisabled={changeLocked} previewedPanels={previewedPanels}
            onClose={() => {}} onSelect={selectBOMPart} onDownload={(blob, filename) => saveBlob(blob, `${safeName(project.name)}-${filename}`)} /> : <>
          {stage === 1 && <section className="project-next-step" aria-label={t('Upload PDF step', '上传PDF步骤')}><div><strong>{t('1. Upload the original customer PDF', '1. 上传客户原始PDF')}</strong></div><button className="primary" disabled={!hasOriginalPDF || importingPDF} onClick={() => chooseStage(2)}>{t('Continue to Step 2', '继续第2步')}</button></section>}


          {(stage === 2 || stage === 3) && <WorkflowRunPanel
            dimension={stage === 2 ? '2D' : '3D'} job={taskJob ?? null} active={!!runningJob} activeDimension={activeDimension}
            startDisabled={stage === 2 ? twoDLocked || !!twoDBlockReason : groupDraftMode ? !!draft3DBlockReason : !!threeDBlockReason}
            draft3D={stage === 3 && useGroup3DActions ? { nextAction: nextDraftAction } : undefined}
            buildActions={stage === 3 ? threeDBuildActions : twoDBuildActions}
            retry2D={!!retryProposalId} resume2D={canResume2D} no2DResult={no2DResult}
            interrupted={interruptedTask && activeDimension === (stage === 2 ? '2D' : '3D')}
            projectInactive={projectInactive} startReason={stage === 2 ? twoDBlockReason : groupDraftMode ? draft3DBlockReason : threeDBlockReason}
            controlsDisabled={!!busy} controlsInBanner={materialControlsInBanner}
            resultAvailable={stage === 2 ? has2DOutput || hasReferenceAssets : !groupDraftMode && (view !== '3d' || workingOutputVisible) && has3DGeometry}
            workingAvailable={!!workingView && (stage !== 2 || !workingOutputVisible)}
            workingPreview={workingView && workingPreviewUrl && workingCycle ? { url: workingPreviewUrl, label: workingView.label, cycle: workingCycle } : undefined}
            assistantDisabled={draftLocked || !aiEnabled}
            onStart={() => void (stage === 3 ? useGroup3DActions ? startGroup3DDrafts(draftGroup) : start3D() : canResume2D ? resumeAnalysis() : startAnalysis())}
            onControl={action => void controlTask(action)} onResult={() => chooseStage(stage)} onWorking={openWorkingOutput} onAssistant={openAssistant}
            compact={compact2DPanel ? {
              output: twoDOutputIdentity, nextStep: continueTo3D,
              secondaryActions: <>{twoDContentToggle}{reviewedPdfLinks}{twoDGroupAction && <WorkflowBuildActions scope={twoDGroupScope} selected={twoDGroupAction} />}</>,
            } : stage === 3 ? {
              extraActions: threeDExtras, nextStep: continueTo4, secondaryActions: threeDDetails,
            } : undefined}
            groupProgress={stage === 2 && <DrawingGroupProgress key={grouped2DJob?.id || project.id} groups={drawingGroups} views={working2DViews} taskStatus={grouped2DJob?.status || taskJob?.status} collapsible={finishedDrawingGroups} onView={openWorkingOutput}
              onRetry={id => void retryDrawingGroup(id)} retryDisabled={locked || projectInactive || !aiEnabled || !health?.key_available}
              onPreview={setArtifactPreview} draftGroups={retainedDrafts} onOpen3D={canShowGroupedDraft ? id => chooseStage(3, id) : undefined} />}
            options={<>{stage === 2 ? <>
              {!compact2DPanel && <>{twoDContentToggle}{reviewedPdfLinks}</>}
              {!build2DGroup && !canMapSaved2D && <details><summary>{t('Drawing scope (optional)', '图纸范围（可选）')}</summary><textarea aria-label={t('Drawing scope', '图纸范围')} maxLength={8000} value={analysisInstruction} onChange={event => setAnalysisInstruction(event.target.value)} placeholder={grouped2DEnabled ? t('Leave blank to map all complete groups and draw them in source order, or name one room or cabinet.', '留空可识别所有完整分组并按原图顺序绘制，也可指定一个房间或柜体。') : t('Leave blank to draw one complete area from the PDF, or name the room or cabinet you want.', '留空时从 PDF 中选择一个完整区域绘图，也可以指定房间或柜体。')} disabled={twoDLocked} /></details>}
              <div className="workflow-create-actions">
                {project.reviewed_design_available && <button className="secondary" disabled={changeLocked} onClick={() => void prepareDesign()}>{t('Use reviewed design', '使用已审阅设计')}</button>}
                {!compact2DPanel && continueTo3D}
              </div>
            </> : <>
              {useGroup3DActions && showDraftSequence && <span id="draft-sequence-hint" className="group-3d-source-status">
                {t('Up to 2 cycles per room, in source order. Existing drafts stay available until new views render.', '按原图顺序处理，每个房间最多 2 轮。新视图渲染前，原有草稿仍可查看。')}</span>}
              {useGroup3DActions && <span className="group-3d-source-status">{draftSourceChecked ? t('Source 2D checks passed', '原始二维已通过检查') : t('Source 2D needs review', '原始二维需审阅')}</span>}
              <details><summary>{t('3D instructions (optional)', '三维要求（可选）')}</summary><textarea aria-label={t('3D instructions', '三维要求')} maxLength={8000} value={threeDInstruction} onChange={event => setThreeDInstruction(event.target.value)} disabled={changeLocked} placeholder={t('Optional: describe the 3D result you need.', '可选：描述需要的三维成果。')} /></details>
              <button className="secondary" onClick={() => chooseStage(2)}>{t('Return to Step 2', '返回第2步')}</button></>}</>} />}
          {stage === 3 && nextProductionAction && <ProductionGuide action={nextProductionAction} />}
          {stage === 3 && <DrawingResults items={threeDResults} value={selected3DResult} onChange={choose3DResult}
            selectLabel={t('3D result', '三维成果')} allowUnselected>
            {fullProjectAction}
            {groupDraftMode && selectedDraftView && draftGroup && <ArtifactPreviewLink onPreview={setArtifactPreview}
              artifact={{ kind: 'image', url: selectedDraftView.preview_url,
                title: `${t('3D review draft', '三维审阅草稿')} · ${draftGroup.label} · ${selectedDraftView.label}` }}>
              {t('Open image preview', '打开图片预览')}</ArtifactPreviewLink>}
          </DrawingResults>}
          {groupDraftMode && draftGroup ? <Group3DDraftView key={draftGroup.id + ':' + (draftJob?.id || '')}
            group={draftGroup} job={draftJob ?? draftSequenceCurrentRoom ?? undefined} view={selectedDraftView} startLabel={draftStartLabel}
            startInDetails={selectedDraftInDetails}
            startReason={draftSequenceWaitingRoom ? t('This room starts after the earlier rooms finish their build and check cycles.', '前面的房间完成构建与检查后，才会开始处理此房间。') : draft3DBlockReason} /> : <>
          {(stage === 1 || stage === 2 && !compact2DPanel) && twoDOutputIdentity}
          {stage === 2 && <DrawingResults items={step2Results} value={step2ResultId} onChange={selectStep2Result}
            selectLabel={showWorking2DResults ? t('Working result view', '工作成果视图') : undefined}
            allowUnselected={showWorking2DResults || view === 'source'} />}

          {!workingOutputVisible && isShowcase && view === '3d' && <div className="showcase-focus-bar"><span>{t('Explore', '探索')}</span>{[{ id: 'KITCHEN', title: t('Kitchen', '厨房') }, { id: 'POWDER', title: t('Powder room', '盥洗间') }, { id: 'MATERIAL-LAB', title: t('Material studio', '材料工作室') }, { id: '', title: t('Full project', '全部项目') }].map(item => <button className={options.isolate === item.id ? 'active' : ''} key={item.id} onClick={() => focusShowcase(item.id)}>{item.title}</button>)}<button className="subtle" onClick={() => setMaterialLibrary('manage')}>{t('Materials', '材料')}</button><button className="subtle" onClick={() => setBomOpen(true)}>{t('Excel BOM', 'Excel BOM')}</button></div>}
          <div ref={viewport} className={`viewport ${workingOutputVisible ? 'working-output-visible' : ''}`}>
            {workingOutputVisible && workingView && workingResult && workingPreviewUrl && <div className="working-output-viewport">
              <div className="working-output-heading">
                <strong>{t('Working output', '工作成果')} · {workingStatus === 'stopped' ? t('Stopped', '已停止') : workingStatus === 'needs_review' ? t('Needs review', '需要审阅') : workingStatus === 'ready' ? t('Awaiting your review', '等待你审阅') : t('Checking', '检查中')}</strong>
                <span>{workingView.group_label && `${workingView.group_label} · `}{t(`Cycle ${workingCycle} · Not applied`, `第${workingCycle}轮 · 尚未应用`)}</span>
                {showingCopiedPreview && <span>{workingView.copied_from_project
                  ? t(`Copied from ${workingView.copied_from_project} · Review required`, `复制自 ${workingView.copied_from_project} · 需要审阅`)
                  : t('Copied preview · Review required', '复制预览 · 需要审阅')}</span>}
                {copiedWorkingPreview && <button type="button" className="subtle" onClick={() => setShowPreviousForCopyUrl(showingCopiedPreview ? copiedWorkingPreview.previewUrl : '')}>
                  {showingCopiedPreview ? t('Show previous working preview', '显示之前的工作预览') : t('Show copied preview', '显示复制预览')}
                </button>}
                {workingPdfUrl && <ArtifactPreviewLink onPreview={setArtifactPreview} artifact={{ kind: 'pdf', url: workingPdfUrl, previewImageUrl: workingPreviewUrl,
                  title: `${showingCopiedPreview ? t('Copied preview · Working PDF', '复制预览 · 工作图PDF') : t('Working PDF', '工作图PDF')} · ${workingView.label}` }}>{t('Working PDF', '工作图PDF')}</ArtifactPreviewLink>}
              </div>
              <div className="working-output-image"><img src={workingPreviewUrl} alt={t(`Working output: ${workingView.label}`, `工作成果：${workingView.label}`)}
                style={{ width: workingWidth, aspectRatio: workingImageSize ? `${workingImageSize.width} / ${workingImageSize.height}` : '1 / 1.35' }}
                onLoad={event => {
                  const width = event.currentTarget.naturalWidth, height = event.currentTarget.naturalHeight;
                  if (width && height) setWorkingImageSize(previous => previous?.width === width && previous.height === height ? previous : { width, height });
                }} /></div>
            </div>}
{!useReferenceViewer && <div ref={host} className={`three-host ${view !== '3d' ? 'is-hidden' : ''}`} data-testid="studio-3d-viewport" />}
            {referenceMedia && reference && <ReferenceViewer manifest={reference} sectionId={referenceSectionId} viewId={referenceViewId} zoom={zoom} />}
            {referenceMedia && !reference && <div className="empty-canvas" role="alert"><p>{t('The reference views are unavailable.', '参考视图暂不可用。')}</p><button className="secondary" onClick={() => void run(t('Opening reference views…', '正在打开参考视图…'), async () => { await loadReferenceManifest(); })}>{t('Reload reference views', '重新加载参考视图')}</button></div>}
            {view === 'reviewed' && isShowcase && showcase && <ShowcaseGallery manifest={showcase} zoom={zoom} onThreeD={() => { setView('3d'); setStage(3); }} />}
            {view === 'source' && (activePage ? <div className="source-viewport"><img className="source-image" src={activePage.preview_url} alt={`${activePage.document.name}, page ${activePage.number}`} onLoad={event => { const width = event.currentTarget.naturalWidth, height = event.currentTarget.naturalHeight; setSourceImageSize(previous => previous?.width === width && previous.height === height ? previous : { width, height }); }} style={{ width: sourceWidth, minWidth: 0, maxWidth: 'none', margin: '0 auto' }} /><div className="viewport-caption">{activePage.document.name} · P{activePage.number} {t("· 原始依据 Source evidence")}</div></div> : <div className="empty-canvas"><span className="empty-icon"><Icon name="source" /></span><h2>{t("从客户原图开始")}</h2><p>Upload the original customer PDF to start your design.</p><button className="primary" disabled={changeLocked} onClick={() => uploadInput.current?.click()}><Icon name="upload" />{t("导入原图")}</button></div>)}
            {!useReferenceViewer && view !== 'source' && view !== '3d' && view !== 'reviewed' && (drawing ? <div className="drawing-viewport"><div className="drawing-sheet" style={{ width: drawingWidth, minWidth: 0, margin: '0 auto' }} onClick={event => selectDrawingTarget(event.target)} dangerouslySetInnerHTML={{ __html: drawing }} /></div> : <div className="empty-canvas"><Icon name="box" /><h2>{effectiveDrawingStatus === 'stale' ? t('图纸需要更新') : t('当前视图尚不完整')}</h2><button type="button" className="subtle" onClick={openNotices}>{t('View details', '查看详情')}</button><button className="secondary" onClick={() => { setView('source'); setLeftTab('source'); }}>{t("查看原图 View sources")}</button></div>)}
            {!useReferenceViewer && view === '3d' && (!viewerScene?.meshes.length || webglError) && <div className="empty-canvas">{webglError ? <><h2>{t('3D view unavailable', '三维视图暂不可用')}</h2><button className="subtle" onClick={openNotices}>{t('View details', '查看详情')}</button>{drawing && <div className="fallback-drawing" dangerouslySetInnerHTML={{ __html: drawing }} />}</> : <><span className="empty-icon"><Icon name="box" /></span><h2>{localFrames.length ? t('整体位置仍待确认') : t('等待生成三维模型')}</h2><p>{localFrames.length ? t('Choose a local assembly below to inspect its known structure. / 请在下方选择局部构件，查看已知结构。') : 'Review an analysis preview to begin exploring.'}</p><button className="secondary" onClick={() => { setView('source'); setLeftTab('source'); }}>{t("查看原图 View sources")}</button></>}</div>}
            {!useReferenceViewer && view === '3d' && !!viewerScene?.meshes.length && <div className="viewport-caption">{t("拖动旋转 · 滚轮缩放 · 点击选择")}<span>Drag · Zoom · Select</span></div>}
          </div>
          {workingOutputVisible ? <div className="display-controls"><div><button className="icon-button" aria-label={t('Zoom out / 缩小')} onClick={() => setZoom(value => Math.max(.5, value - .25))}>−</button><button className="subtle" onClick={() => setZoom(1)}>{Math.round(zoom * 100)}%</button><button className="icon-button" aria-label={t('Zoom in / 放大')} onClick={() => setZoom(value => Math.min(4, value + .25))}>+</button><button className="subtle" onClick={() => { retainCanvasChoice(); setShowWorkingOutput(false); }}>{groupedJob && !has2DOutput ? t('Return to original PDF', '返回原始 PDF') : t('Return to saved design', '返回已保存设计')}</button></div><span>{t('Working image · Review required', '工作图像 · 需要审阅')}</span></div> : referenceMedia ? <div className="display-controls"><div><button className="icon-button" aria-label={t('Zoom out', '缩小')} onClick={() => setZoom(value => Math.max(.5, value - .25))}>−</button><button className="subtle" onClick={fitSheet}>{Math.round(zoom * 100)}%</button><button className="icon-button" aria-label={t('Zoom in', '放大')} onClick={() => setZoom(value => Math.min(4, value + .25))}>+</button><button className="subtle" aria-label={t('Fit view', '适应窗口')} onClick={fitSheet}>{t('Fit view', '适应窗口')}</button></div><div><select aria-label={t('Property units', '属性单位')} value={options.unit} onChange={event => setOptions(previous => ({ ...previous, unit: event.target.value as 'mm' | 'in' }))}><option value="mm">mm</option><option value="in">in</option></select><span className="reference-interaction-note">{t('Reviewed drawing · Original annotation units', '已审阅图纸 · 原始标注单位')}</span></div></div> : <div className="display-controls"><div>{view === '3d' ? <>{localFrames.length > 0 && <select aria-label={t("3D scope / 三维范围")} value={localFrame?.root_id || ''} onChange={event => choose3DScope(event.target.value)}><option value="">{t("整体 World")}</option>{localFrames.map(frame => <option key={frame.root_id} value={frame.root_id}>{t("局部 Local ·")}{frame.label}</option>)}</select>}<select aria-label={t("3D camera / 三维视角")} value={camera} onChange={event => { setCamera(event.target.value); viewer.current?.preset(event.target.value); }}><option value="AXON">{t("轴测 3D")}</option><option value="ORTHO-FRONT">{t("前 Front")}</option><option value="ORTHO-RIGHT">{t("右 Right")}</option><option value="ORTHO-BACK">{t("后 Back")}</option><option value="ORTHO-LEFT">{t("左 Left")}</option><option value="PLAN-UP">{t("顶部 Top")}</option></select><button className="subtle" onClick={() => viewer.current?.fit()}><Icon name="fit" />{t("全图 Fit")}</button></> : <><button className="icon-button" aria-label={t("Zoom out / 缩小")} onClick={() => setZoom(value => Math.max(.5, value - .25))}>−</button><button className="subtle" onClick={fitSheet}>{Math.round(zoom * 100)}%</button><button className="icon-button" aria-label={t("Zoom in / 放大")} onClick={() => setZoom(value => Math.min(4, value + .25))}>+</button><button className="subtle" aria-label={t("Fit view / 适应窗口")} onClick={fitSheet}><Icon name="fit" />{t("适应 Fit")}</button></>}</div>{view === 'reviewed' ? <span className="reviewed-units-note">{t("Original annotation units", "原始标注单位")}</span> : <div><select aria-label={sourceNativeView ? t('Property units / 属性单位') : t('Units / 单位')} title={sourceNativeView ? t('Only property fields convert units; source drawing labels retain their original units and are NTS. / 仅属性输入换算单位；原图标注保留原单位且不按比例。') : undefined} value={options.unit} onChange={event => setOptions(previous => ({ ...previous, unit: event.target.value as 'mm' | 'in' }))}><option value="mm">{sourceNativeView ? t('属性 毫米 mm') : t('毫米 mm')}</option><option value="in">{sourceNativeView ? t('属性 英寸 in') : t('英寸 in')}</option></select><label className="checkbox"><input type="checkbox" checked={options.dimensions !== 'off'} onChange={event => setOptions(previous => ({ ...previous, dimensions: event.target.checked ? 'selected' : 'off' }))} />{t("尺寸")}</label><label className="checkbox" title={t("Door swing and drawer pull-out symbols. Display only—not an animation. / 柜门开启方向及抽屉拉出符号，仅显示符号，不是开启动画。")}><input type="checkbox" disabled={view === '3d' ? !viewerScene?.symbols.length : !(drawingAsset?.symbol_count || shown?.symbols.length)} aria-label={openingMarksLabel} checked={openingMarksShown} onChange={event => changeOpeningMarks(event.target.checked)} />{t("开启线")}</label><label className="checkbox"><input type="checkbox" checked={inside} onChange={event => setInside(event.target.checked)} />{t("看内部")}</label><details className="display-menu"><summary>{t("显示 ▾")}</summary><div><label><span>{t("尺寸范围 / Dimensions")}</span><select value={options.dimensions} onChange={event => setOptions(previous => ({ ...previous, dimensions: event.target.value as ViewOptions['dimensions'] }))}><option value="off">{t("关闭 Off")}</option><option value="selected">{t("选中构件 Selected")}</option><option value="all">{t("全部 All")}</option><option value="inferred">{t("暂定尺寸 Provisional")}</option></select></label><label><input type="checkbox" checked={!!options.componentSizes} onChange={event => setOptions(previous => ({ ...previous, componentSizes: event.target.checked }))} />{t("构件自身尺寸 / Component sizes")}</label><label><input type="checkbox" checked={options.text} onChange={event => setOptions(previous => ({ ...previous, text: event.target.checked }))} />{t("构件文字 / Object labels")}</label><label><input type="checkbox" checked={options.viewLabels} onChange={event => setOptions(previous => ({ ...previous, viewLabels: event.target.checked }))} />{t("视图索引 / View references")}</label><label><input type="checkbox" checked={options.transparentWalls} onChange={event => setOptions(previous => ({ ...previous, transparentWalls: event.target.checked }))} />{t("透明周边 / Transparent context")}</label><label><span>{t("外观 / Appearance")}</span><select value={options.appearance} onChange={event => setOptions(previous => ({ ...previous, appearance: event.target.value as ViewOptions['appearance'] }))}><option value="outline">{t("白面黑线 Outlines")}</option><option value="material">{t("预设颜色 Colors")}</option></select></label></div></details></div>}</div>}
          <div className="selection-status"><span>{selectedNode ? selectedNode.id === model?.root.id ? project.name : `${t(selectedNode.name)} · ${selectedNode.id}` : t('点击构件查看尺寸 · Select an object to inspect it')}</span><span>{selectedNode?.surface ? t('Source contour; thickness not asserted / 原图轮廓，未指定板厚') : selectedObject?.size.length === 3 ? selectedObject.size.map(value => valueText(value, options.unit)).join(' × ') : ''}</span></div>
          </>}
          </>}
        </section>
        {groupDraftMode && draftGroup && <aside className="right-panel"><div className="right-scroll">
          <section className="panel-section properties-section">
            <div className="panel-heading"><div><span className="section-label">{t('3D REVIEW DRAFT', '三维审阅草稿')}</span><h3>{drawingGroupName(draftGroup)}</h3></div></div>
            {draftJob?.draft_3d_donor_project_name && <p className="hint">{t('2D baseline', '二维基准')} · {draftJob.draft_3d_donor_project_name}</p>}
            <p className="hint">{draftSourceChecked ? t('Uses a 2D group that passed its drawing checks.', '使用已通过图纸检查的二维分组。') : t('Uses a held 2D group. Check its drawings against the original PDF.', '使用待审阅的二维分组。请对照原始 PDF 核对图纸。')}</p>
            <p className="hint">{t('Inspect the draft and its source views before making design decisions.', '做出设计决定前，请检查草稿及其原图视图。')}</p>
            {showingEarlierDraft && <p className="hint">{t('The latest build ended without a new result. You are viewing the previously saved draft.', '最近一次构建未生成新成果。当前显示之前保存的草稿。')}</p>}
            {!!draftAssumptions.length && <details><summary>{t('Provisional dimensions and assumptions', '暂定尺寸与推断依据')}</summary>
              <ul>{draftAssumptions.map((note, index) => <li key={index}>{note}</li>)}</ul>
            </details>}
            {!!draftReviewNotes.length && <details><summary>{t('Draft review notes', '草稿审阅记录')}</summary><ul>{draftReviewNotes.map(note => <li key={note}>{note}</li>)}</ul></details>}
          </section>
        </div></aside>}
        {!groupDraftMode && !cuttingListVisible && stage !== 1 && <aside className="right-panel"><div className="right-scroll"><section className="panel-section properties-section"><div className="panel-heading"><div><span className="section-label">{t("PROPERTIES / 属性")}</span><h3>{selectedNode?.id === model?.root.id ? project.name : t(selectedNode?.name || t('构件尺寸'))}</h3></div>{selectedNode && <span className={`status-tag ${selectedNode.authority || 'source'}`}>{selectedNode.authority === 'designed' ? t('设计') : selectedNode.authority === 'user' ? t('已修改') : t('原图')}</span>}</div>{stage === 3 && selectedNode && <MaterialProperties node={selectedNode} snapshots={model?.material_snapshots} context={selectedContext} libraryDisabled={locked} disabled={changeLocked || selectedContext || selectedNode.id === model?.root.id} onChoose={() => setMaterialLibrary('assign')} onManage={() => { if (!locked) setMaterialLibrary('manage'); }} onBoard={() => setBoardSpecOpen(true)} />}<input className="parameter-search" aria-label={t("Find dimension / 查找尺寸")} placeholder={t("查找尺寸 · Find a dimension")} value={parameterFilter} onChange={event => setParameterFilter(event.target.value)} /><div className="property-list">{propertyParameters.slice(0, 50).map(parameter => <ParameterCard key={parameter.id} parameter={parameter} unit={options.unit} resolved={shown?.resolved[parameter.id]} reference={shown?.reference_parameters?.[parameter.id]} disabled={changeLocked} onPreview={(id, value) => void previewParameter(id, value)} onAdjustReference={aiEnabled ? adjustReference : undefined} />)}{!parameters.length && <p className="hint">{t("选中一个构件，查看和修改其控制尺寸。 Select a component to inspect its dimensions.")}</p>}{propertyParameters.length > 50 && <p className="hint">{t("显示前 50 项，请搜索具体尺寸。 / Showing first 50; search for a dimension.")}</p>}{sourceObservations.length > 0 && <details className="source-observations"><summary>{t("Source observations", "原图记录")} · {sourceObservations.length}</summary>{sourceObservations.slice(0, 50).map(parameter => <ParameterCard key={parameter.id} parameter={parameter} unit={options.unit} resolved={shown?.resolved[parameter.id]} disabled={changeLocked} onPreview={(id, value) => void previewParameter(id, value)} />)}{sourceObservations.length > 50 && <p className="hint">{t("显示前 50 项，请搜索具体尺寸。 / Showing first 50; search for a dimension.")}</p>}</details>}</div></section>
          {stage === 3 && <section className="panel-section interior-section"><div className="panel-heading"><div><span className="section-label">{t("INTERIOR / 柜内设计")}</span><h3>{t("Cabinet interior", "柜内设计")}</h3></div><Icon name="box" /></div><form onSubmit={event => void previewInterior(event)}><label className="input-label">{t("目标柜体 / Cabinet")}<select aria-label={t("Cabinet interior target / 内部设计目标柜体")} value={interiorTarget} onChange={event => { setInteriorTarget(event.target.value); select(event.target.value); }} disabled={changeLocked}><option value="">{t("选择柜体 Select cabinet")}</option>{cabinets.map(node => <option key={node.id} value={node.id}>{t(node.name)}</option>)}</select></label><div className="interior-grid">{[{ key: 'thickness_mm', label: t('板厚 Thickness'), suffix: 'mm', min: 1, step: .1 }, { key: 'back_mm', label: t('背板 Back'), suffix: 'mm', min: 1, step: .1 }, { key: 'shelves', label: t('层板 Shelves'), suffix: '', min: 0, step: 1 }, { key: 'dividers', label: t('竖隔板 Dividers'), suffix: '', min: 0, step: 1 }, { key: 'drawers', label: t('抽屉 Drawers'), suffix: '', min: 0, step: 1 }, { key: 'clearance_mm', label: t('间隙 Clearance'), suffix: 'mm', min: 0, step: .1 }].map(item => <label key={item.key}>{item.label}<div><input type="number" min={item.min} max={item.step === 1 ? 20 : 100} step={item.step} value={interior[item.key as keyof typeof interior]} onChange={event => changeInterior(item.key as keyof typeof interior, Number(event.target.value))} disabled={changeLocked} aria-label={item.label} />{item.suffix && <span>{item.suffix}</span>}</div></label>)}</div><p className="hint">{t("层板／隔板与抽屉布局择一，另一种会自动清零。 Choose shelves/dividers or drawers; the other layout resets.")}</p><p className="hint">{t("所选外形用于柜体设计。 Selected envelope is used for cabinet design.")}</p><p className="hint">{t("这是你的内部设计方案，将保留原柜体外形。 Designed additions stay separate from source facts.")}</p><button className="secondary full-width" type="submit" disabled={changeLocked || !interiorTarget}><Icon name="box" />{t("预览内部结构 Preview")}</button></form></section>}
          {aiEnabled && <section className="panel-section assistant-section"><div className="assistant-title"><span><Icon name="spark" /></span><div><h3>{t("说出你的修改")}</h3></div></div><form onSubmit={event => void sendEdit(event)}><textarea className="ai-input" maxLength={8000} aria-label={t("Design instruction / 设计修改要求")} placeholder={stage === 2 && health?.ai_design_mode === 'autonomous_2d' ? t('Describe a 2D change or attach a screenshot.', '描述二维修改，或附加截图。') : t('例如：把选中柜体加宽到 900mm，内部改为两层层板。\nYou can also paste a screenshot here.')} value={instruction} onChange={event => setInstruction(event.target.value)} onPaste={pasteImage} disabled={draftLocked} rows={3} />{attachmentURL && <div className="attachment-preview"><img src={attachmentURL} alt={t("Screenshot attached to this request / 本次请求附加的截图")} /><div><span>{attachment?.name}</span><button type="button" className="icon-button" aria-label={t("Remove screenshot / 移除截图")} onClick={() => setAttachment(null)} disabled={draftLocked}><Icon name="close" /></button></div></div>}<div className="attachment-controls"><button type="button" className="subtle" disabled={draftLocked} onClick={() => screenshotInput.current?.click()}><Icon name="image" />{t("附加截图")}</button><button type="button" className="subtle" disabled={draftLocked || !canCaptureView} onClick={() => void attachCapture()}>{t("截取当前视图")}</button></div><button className="primary full-width" disabled={changeLocked || !aiEnabled || !instruction.trim() || !health?.key_available} type="submit"><Icon name="spark" />{t("生成修改预览")}</button></form></section>}
          <section className="panel-section history-section"><div className="section-label">{t("REVISION HISTORY / 版本历史")}</div><div className="history-row"><select aria-label={t("Revision to restore / 待恢复版本")} value={historyTarget} onChange={event => setHistoryTarget(event.target.value)} disabled={changeLocked}><option value="">{t("选择历史版本")}</option>{[...project.history].sort((a, b) => b.revision - a.revision).map(item => <option key={item.revision} value={item.revision}>R{item.revision} · {t(item.summary || dateText(item.created_at))}</option>)}</select><button className="subtle" disabled={changeLocked || !historyTarget || Number(historyTarget) === project.revision} onClick={() => void restore(Number(historyTarget), 'history')}>{t("恢复")}</button></div><p className="hint">{t("恢复将创建新版本，不删除历史。 Restore creates a new revision.")}</p></section>
        </div></aside>}
      </main>}
    <footer className="studio-footer"><span>{busy ? <><span className="busy-spinner" />{busy}</> : t('本地项目 · Local workspace')}</span><span>{t("客户确认设计 · Customer-review design")}</span><span>FormToPart Studio {health?.version || 'MVP'}</span></footer>
    <input ref={uploadInput} className="sr-only" type="file" accept=".pdf,application/pdf" aria-label="Import customer drawing" onChange={event => { void uploadFile(event.target.files?.[0]); event.target.value = ''; }} />
    <input ref={screenshotInput} className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" aria-label="Attach screenshot" onChange={event => { attach(event.target.files?.[0]); event.target.value = ''; }} />
    <input ref={importInput} className="sr-only" type="file" accept=".vwc,.zip,.json" aria-label="Import project archive" onChange={event => { const file = event.target.files?.[0]; if (file) void run(t('Opening project archive / 正在打开项目文件'), async () => { const next = await studioAPI.importProject(file); await refreshList(); await loadProject(next.id); }); event.target.value = ''; }} />
    {materialSuggestionsOpen && !keySettingsOpen && project && <MaterialSuggestionDrawer
      revision={project.revision} scope={materialScope} scopeName={materialScopeRoot?.name || project.name}
      assignedCount={materialScopeAlreadyAssigned ? materialScopeLeaves.length : 0}
      preference={materialInstruction} replaceExisting={replaceMaterials} connected={aiEnabled && !!health?.key_available}
      allowPalette={hasReferenceAssets} busy={!!busy} locked={changeLocked} error={error}
      onScopeChange={setMaterialScope} onPreferenceChange={setMaterialInstruction} onReplaceChange={setReplaceMaterials}
      onSubmit={mode => void suggestMaterials(mode)} onClose={() => setMaterialSuggestionsOpen(false)}
      onConnect={() => setKeySettingsOpen(true)} onLibrary={() => { setMaterialSuggestionsOpen(false); setMaterialLibrary('manage'); }}
      onShowExisting={() => {
        setMaterialSuggestionsOpen(false); setReferenceContent('current'); setStage(3); setView('3d');
        setOptions(previous => ({ ...previous, appearance: 'material' }));
      }} />}
    {materialLibrary && <MaterialLibrary sizes={boardSizes} onClear={materialLibrary === 'stock' ? undefined : previewClearMaterial}
      node={materialLibrary === 'manage' ? undefined : selectedNode} boardStockOnly={materialLibrary === 'stock'}
      assignEnabled={!changeLocked && !selectedContext && selectedNode?.id !== model?.root.id} onClose={() => setMaterialLibrary(null)} onPreview={previewMaterial} />}
    {boardSpecOpen && selectedNode && isBoardPanel(selectedNode, selectedContext) && <BoardSpecEditor node={selectedNode} dimensions={selectedObject?.size || selectedNode.size?.map(value => typeof value === 'number' ? value : shown?.resolved[value] ?? null) || [null, null, null]} onClose={() => setBoardSpecOpen(false)} onPreview={previewBoard} />}
    {bomOpen && project && <BOMSheet projectId={project.id} revision={project.revision} pending={!!proposal} onClose={() => setBomOpen(false)} onSelect={selectBOMPart} onDownload={(blob, filename) => saveBlob(blob, `${safeName(project.name)}-${filename}`)} />}
    {keySettingsOpen && <KeySettings onClose={() => setKeySettingsOpen(false)} onSaved={settings => setHealth(previous => previous ? { ...previous, key_available: settings.key_available, model: settings.model, reasoning: settings.reasoning } : previous)} />}
    {project && artifactPreview && <ArtifactPreview key={artifactPreview.url} artifact={artifactPreview} onClose={() => setArtifactPreview(null)} />}
    {deleteTarget && <StudioSheet title={t('Delete project?', '删除项目？')} titleId="delete-project-title" onClose={() => setDeleteTarget(null)} locked={!!busy}><div className="sheet-body confirmation-body"><h3>{deleteTarget.name}</h3><p>{t('This removes the project from your workspace. Export a project archive first if you want a portable copy.', '这会将项目从工作空间移除。如果需要可携带副本，请先导出项目归档。')}</p><div className="sheet-actions"><button className="secondary" disabled={!!busy} onClick={() => setDeleteTarget(null)}>{t('Keep project', '保留项目')}</button><button className="danger-button" disabled={!!busy || deleteTarget.can_delete === false} onClick={() => void confirmDelete()}>{t('Delete project', '删除项目')}</button></div></div></StudioSheet>}
    {stopDialog && project && <StudioSheet title={t('Stop this project?', '停止此项目？')} titleId="stop-project-title" onClose={() => setStopDialog(false)} locked={!!busy}><div className="sheet-body confirmation-body"><h3>{project.name}</h3><p>{t('Current work will stop. Your saved design and pending preview are kept, and you can resume the project later.', '当前任务将停止，已保存设计和待确认预览会保留，之后可以恢复项目。')}</p><div className="sheet-actions"><button className="secondary" disabled={!!busy} onClick={() => setStopDialog(false)}>{t('Keep working', '继续工作')}</button><button className="primary" disabled={!!busy} onClick={() => void changeLifecycle('stop')}>{t('Stop project', '停止项目')}</button></div></div></StudioSheet>}
    {renameTarget && <StudioSheet title={t('Rename project', '重命名项目')} titleId="rename-project-title" onClose={() => setRenameTarget(null)} locked={!!busy}>
      <form className="sheet-body" onSubmit={event => void renameProject(event)}>
        <label className="input-label">{t('Project name', '项目名称')}
          <input data-autofocus required maxLength={120} value={renameName} readOnly={!!busy} onFocus={event => event.currentTarget.select()} onChange={event => setRenameName(event.target.value)} />
        </label>
        {error && <p className="field-error" role="alert">{t(error)}</p>}
        <div className="sheet-actions">
          <button type="button" className="secondary" disabled={!!busy} onClick={() => setRenameTarget(null)}>{t('Cancel', '取消')}</button>
          <button type="submit" className="primary" disabled={!!busy || !renameName.trim() || renameName.trim() === renameTarget.name}>{t('Save name', '保存名称')}</button>
        </div>
      </form>
    </StudioSheet>}
    {newProjectOpen && <div className="modal-backdrop"><form ref={newProjectDialog} className="modal-card" role="dialog" aria-modal="true" aria-labelledby="new-project-title" onSubmit={event => void createProject(event)}><div className="modal-heading"><span className="section-label">{t("NEW PROJECT / 新建项目")}</span><button type="button" className="icon-button" aria-label={t("Close / 关闭")} disabled={globalLocked} onClick={() => setNewProjectOpen(false)}><Icon name="close" /></button></div><h2 id="new-project-title">{t("开始一个新的设计。")}</h2><p>{t("Each project keeps its own sources and history. 每个项目独立保存原图、模型和版本历史。")}</p><label className="input-label">{t("项目名称 / Project name")}<input autoFocus required maxLength={120} value={newName} onChange={event => setNewName(event.target.value)} placeholder={t("例如：李先生 · 厨房柜体")} /></label><div className="modal-actions"><button type="button" className="secondary" disabled={globalLocked} onClick={() => setNewProjectOpen(false)}>{t("取消 Cancel")}</button><button className="primary" disabled={globalLocked || !newName.trim()} type="submit">{t("创建项目 Create")}</button></div></form></div>}
  </div>;
}
