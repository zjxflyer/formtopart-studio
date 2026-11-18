import type { SpatialScene } from '../spatial/types';

export type EvidenceRef = { document_id?: string; page?: number; page_number?: number; text?: string; description?: string; region?: number[] | null };
export type StudioParameter = {
  id: string; label: string; value_mm: number | null; expression: string | null;
  status: 'source' | 'inferred' | 'user' | 'designed' | 'tbc' | string;
  evidence: EvidenceRef[];
};
export type StudioInterior = {
  thickness_mm: number; back_mm: number; shelves: number;
  dividers: number; drawers: number; clearance_mm: number;
};
export type StudioNode = {
  id: string; name: string; kind: string; children: StudioNode[];
  size?: Array<number | string> | null; position?: Array<number | string>;
  rotation?: number | string; physical?: boolean; context?: boolean;
  authority?: string; evidence?: EvidenceRef[];
  surface?: { plane: 'front' | 'plan'; width: number | string; span: number | string } | null;
  interior?: StudioInterior | null;
  material?: string; material_assignment?: string | null; board_spec?: BoardSpec | null;
};
export type StudioView = {
  id: string; label: string; kind: 'plan' | 'elevation'; page: number;
  document_id: string; region?: number[] | null;
};
export type StudioModel = {
  name: string; parameters: StudioParameter[]; root: StudioNode;
  views: StudioView[]; warnings: string[];
  material_snapshots?: MaterialSnapshot[];
  drawings?: Array<{ reference_annotations?: Array<{ control_id: string; provenance?: {
    original_control_bindings?: Array<{ owner_id: string; axis?: 'width' | 'depth' | 'height' }>;
  } }> }>;
};
export type ProjectDocument = {
  id: string; name: string; page_count: number; sha256: string;
  media_type?: string;
  pages: Array<{ number: number; preview_url: string; text?: string }>;
};
export type Revision = { revision: number; summary: string; created_at: string };
export type DrawingAsset = {
  id: string; label: string; kind?: 'plan' | 'elevation'; document_id?: string; page?: number;
  owner_ids?: string[];
  svg: string; status: 'ready' | 'incomplete' | 'stale' | 'needs_review'; issues: string[];
  geometry_count: number; dimension_count: number; symbol_count: number;
};
export type DrawingQuality = {
  status: 'ready' | 'incomplete' | 'stale' | 'needs_review'; issues?: string[]; model_preview?: boolean; can_apply?: boolean;
  views?: Array<{ id: string; label?: string; status: string; issues?: string[] }>;
};
export type StudioReferenceParameter = {
  value_mm: number; label: string; method: string; confidence: number; owner_id: string; estimate_id: string;
};
export type StudioScene = SpatialScene & {
  drawings?: Record<string, DrawingAsset>;
  drawing_quality?: DrawingQuality;
  reference_parameters?: Record<string, StudioReferenceParameter>;
  local_frames?: Record<string, StudioLocalFrame>;
  active_local_frame?: { root_id: string; label: string; global_placement_known: false };
  draft_3d?: { source_views?: DrawingGroup2D['source_views'] };
};
export type StudioLocalFrame = Pick<SpatialScene, 'objects' | 'meshes' | 'dimensions' | 'symbols' | 'bounds'> & {
  root_id: string; owner_id: string; label: string; ancestors?: string[];
  global_placement_known: false; coordinate_system: 'assembly-local';
  origin: [number, number, number]; orientation_known: boolean;
  issues?: string[]; pending_parts?: string[];
  omitted_parent_transform?: { position: Array<number | string | null>; rotation: number | string | null };
};
export type WorkflowSummary = {
  source_documents: number; source_pages: number; reviewed_drawings: number; model_objects: number; model_meshes: number;
  bom_status: 'empty' | 'ready' | 'blocked'; bom_rows: number; bom_boards: number; revision: number;
  bom_missing_material?: boolean;
};
export type StudioProject = {
  id: string; name: string; revision: number; model: StudioModel;
  documents: ProjectDocument[]; history: Revision[]; pending_proposal?: { id: string } | null;
  reviewed_design_available?: boolean; can_retry_2d?: boolean; can_analyze_groups?: boolean; workflow_summary?: WorkflowSummary; workflow_2d?: Autonomous2DReceipt | null;
  can_rebuild_2d_from_originals?: boolean;
  grouped_3d_design_status?: { status: 'unavailable' | 'needs_3d_draft' | 'ready' | 'saved';
    group_count: number; checked_2d_count: number; checked_3d_count: number; blocking_group_id?: string };
  three_d_source_status?: 'ready' | 'missing_original_pdf' | 'source_unavailable' | 'missing_checked_2d' | 'prepared_needs_checked_2d';
  workflow_3d?: Workflow3DReceipt | null;
  grouped_2d_job?: StudioJob | null;
  grouped_3d_jobs?: Record<string, StudioJob>;
  active_job?: StudioJob & { id: string; project_id: string } | null;
  last_job?: StudioJob & { id: string; project_id: string } | null;
  lifecycle?: 'active' | 'paused' | 'stopped'; is_demo?: boolean; can_delete?: boolean;
  demo_key?: string; reference_demo?: boolean; reference_source_key?: string | null; reference_project?: boolean; display_name?: string; lifecycle_updated_at?: string;
};
export type ProjectSummary = { id: string; name: string; revision: number; document_count: number; updated_at: string;
  lifecycle?: 'active' | 'paused' | 'stopped'; is_demo?: boolean; can_delete?: boolean; demo_key?: string; reference_demo?: boolean; reference_source_key?: string | null; reference_project?: boolean };
export type Proposal = {
  id: string; base_revision: number; summary: string; warnings: string[];
  model: StudioModel; scene: StudioScene;
  board_specs_preview?: boolean;
};
export type StudioHealth = { application: string; version: string; key_available: boolean; model: string; reasoning: string; prepared_demo?: boolean; reviewed_demo?: boolean; showcase_demo?: boolean; ai_enabled?: boolean; grouped_2d?: boolean; ai_design_mode?: 'model' | 'native' | 'autonomous_2d'; reference_demo_mode?: boolean; reference_demo_only?: boolean; canonical_demo_id?: string; reference_project_mode?: boolean; prepared_project_id?: string | null; github_distribution?: boolean };
export type Autonomous2DReceipt = { accepted: boolean; status: string; cycle_count: number; max_cycles: number; request_count: number; max_requests: number; view_count: number; issues: string[]; three_d_held?: boolean;
  failed_stage?: string | null; group_cycles?: { latest_cycle?: { metadata?: { phase?: string } } | null } | null };
export type Workflow3DReceipt = { accepted: boolean; status: string; calls_used: number; max_calls: number; can_apply?: boolean; source_2d_preserved?: boolean; issues?: unknown[];
  reports?: Array<{ findings?: Array<{ observed?: string }>; limitations?: string[] }>; draft_assumptions?: string[] };
type StudioJobStatus = 'queued' | 'running' | 'pausing' | 'paused' | 'ready' | 'needs_review' | 'failed' | 'cancelled';
type WorkingResultStatus = 'checking' | 'stopped' | 'needs_review' | 'ready';
export type WorkingResultView = { view_id: string; label: string; preview_url: string; pdf_url?: string;
  copied_preview_url?: string; copied_pdf_url?: string; copied_from_project?: string;
  group_id?: string; group_label?: string; cycle?: number; status?: WorkingResultStatus };
export type WorkingResult = { kind: '2d' | '3d'; cycle: number; status: WorkingResultStatus; checked: false;
  view_count: number; views: WorkingResultView[] };
export type DrawingGroup2D = { id: string; label: string; status: StudioJobStatus; view_ids: string[]; cycle_count?: number; accepted?: boolean;
  can_retry?: boolean; can_rebuild?: boolean; cycles_remaining?: number; can_generate_3d_draft?: boolean;
  source_map_url?: string; source_evidence_url?: string; issues?: string[]; source_views?: Array<{ view_id: string; label: string; kind: 'plan' | 'elevation'; page: number;
    source_name?: string; region?: number[] | null; sheet?: string | null; callout?: string | null;
    sight_direction?: 'page-up' | 'page-down' | 'page-left' | 'page-right' | null; correspondence_note?: string }> };
export type Draft3DSequenceRow = { group_id: string; label: string; status: StudioJobStatus; job_id?: string };
export type MaterialSuggestionMode = 'api' | 'prepared' | 'source';
export type MaterialSuggestionReceipt = {
  origin?: MaterialSuggestionMode;
  assignment_count: number;
  assignments: Array<{
    part_id: string;
    material_id: string;
    material_version: number;
    reason: string;
    assignment_mode?: 'appearance' | 'stock';
    basis?: 'source_match' | 'provisional' | 'requested';
    source_evidence?: Array<{ document_id: string; document_name?: string; page: number; text: string; region: number[] | null }>;
  }>;
  notes: string[];
  unresolved?: Array<{ part_id: string; reason: string }>;
};
export type StudioJob = {
  id?: string;
  kind?: string;
  workflow_2d?: Autonomous2DReceipt;
  workflow_3d?: Workflow3DReceipt;
  grouped_2d?: boolean; groups_2d?: DrawingGroup2D[];
  draft_3d_group_id?: string; draft_3d_group_label?: string; draft_3d_scene_url?: string; draft_3d_source_checked?: boolean;
  draft_3d_donor_project_name?: string;
  draft_3d_sequence?: Draft3DSequenceRow[]; draft_3d_current_group_id?: string; draft_3d_group_progress?: number;
  editable_design_revision?: number; editable_design_error?: string;
  can_resume_2d?: boolean;
  can_rebuild_2d?: boolean;
  working_result?: WorkingResult | null;
  error_category?: string; material_suggestions?: MaterialSuggestionReceipt;
  status: StudioJobStatus; phase: string; progress: number;
  resume_phase?: string; resume_progress?: number;
  proposal_id?: string; error?: string; usage?: Record<string, unknown>;
};
export type ShowcaseManifest = {
  id: string; title: string; description: string; archive?: string;
  reviewed_pdf?: string; pdf_url?: string;
  sheets: Array<{ id: string; title: string; image: string; image_url?: string }>;
  [key: string]: unknown;
};
export type KeySettings = { key_available: boolean; model: string; reasoning: 'high'; models: string[]; saved?: boolean };
export type ReferenceDemoManifest = {
  id?: string; title: string; description?: string; canonical_demo_id?: string;
  sections: Array<{ id: string; title: string; pdf: string; pdf_url?: string; viewer_html: string; viewer_url?: string;
    views: Array<{ id: string; label: string; image: string; image_url?: string; source_title?: string; source_view?: string; source_page?: number; page?: number }> }>;
};
export type Grain = 'none' | 'length' | 'width';
export type MaterialInput = {
  code: string; name: string; color_hex: string; color_name: string;
  category: 'sheet' | 'stone' | 'metal' | 'glass' | 'finish' | 'other';
  substrate: string; finish: string; thickness_mm: number | null;
  stock_sizes: Array<{ length_mm: number; width_mm: number }>;
  supplier: string; sku: string; stock_count: number | null; grain: Grain; active: boolean;
};
export type MaterialVariant = MaterialInput & { id: string; version: number };
export type MaterialSnapshot = { snapshot_id: string; variant: MaterialVariant };
export type BoardAxis = 'X' | 'Y' | 'Z';
export type BoardSpec = {
  length_axis: BoardAxis; width_axis: BoardAxis; thickness_axis: BoardAxis;
  grain: Grain; allowance_length_mm: number; allowance_width_mm: number;
  edges: [string, string, string, string]; profile: 'rectangle'; machining_notes: string;
};
export type SuggestedBoard = Pick<BoardSpec, 'length_axis' | 'width_axis' | 'thickness_axis'> & {
  length_mm: number; width_mm: number; thickness_mm: number;
};
export type PanelSpecPreviewRow = SuggestedBoard & { part_id: string; part_name: string };
export type BOMContext = { id: string; name: string; kind: string };
export type BOMRow = {
  row_id: string; part_ids: string[]; part_names: string[];
  length_mm: number; width_mm: number; thickness_mm: number;
  cut_length_mm: number; cut_width_mm: number; quantity: number; area_m2: number; piece_area_m2: number;
  material_code: string; material_name: string; color_name: string; color_hex: string;
  substrate: string; finish: string; grain: Grain; edges: string[]; profile: string; machining_notes: string;
  contexts: Array<{ part_id: string; context_path: BOMContext[] }>;
};
export type BOMIssue = { part_id: string; part_name: string; reason_codes: string[]; reasons: string[]; reason: string; context_path: BOMContext[]; suggested_board?: SuggestedBoard };
export type BOMReviewRow = Omit<BOMRow, 'cut_length_mm' | 'cut_width_mm' | 'grain' | 'material_version'> & SuggestedBoard & {
  cut_length_mm: number | null; cut_width_mm: number | null; grain: Grain | null; material_version: number | null;
  spec_status: 'suggested' | 'saved'; review_reason_codes: string[]; review_reasons: string[]; material_category?: string | null;
};
export type BOMReport = {
  project_id: string; revision: number; bom_sha256: string; units: 'mm';
  scope_id?: string; scope_name?: string;
  status: 'ready' | 'blocked' | 'empty'; rows: BOMRow[]; review_rows?: BOMReviewRow[]; blocked: BOMIssue[]; excluded: BOMIssue[];
};
