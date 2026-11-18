import { t } from './i18n';
import type { BoardSpec, BOMReport, KeySettings, MaterialInput, MaterialSuggestionMode, MaterialVariant, ProjectSummary, Proposal, ReferenceDemoManifest, ShowcaseManifest, StudioHealth, StudioJob, StudioProject, StudioScene } from './types';

const BASE = '/api/studio';
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, init);
  if (!response.ok) {
    let message = t(`Request failed (${response.status}) / 请求失败`);
    try {
      const value = await response.json();
      const detail = value.detail ?? value.error;
      if (typeof detail === 'string') message = detail;
      else if (Array.isArray(detail)) message = detail.map(item => item.msg || 'Invalid input').join('; ');
    } catch { /* Keep the understandable status; never display a raw HTML response. */ }
    throw new Error(message);
  }
  return response.status === 204 ? undefined as T : response.json();
}
const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`;
async function exportBOMFile(id: string, revision: number, bom_sha256: string, scopeId: string | undefined, review: boolean) {
  const route = review ? '/bom/review-export' : '/bom/export';
  const response = await fetch(BASE + projectPath(id) + route, json({ expected_revision: revision, bom_sha256, ...(scopeId ? { scope_id: scopeId } : {}) }));
  if (!response.ok) {
    let message = review ? t(`Could not export the review list (${response.status}).`, '无法导出审阅清单。')
      : t(`Could not export the cutting list (${response.status}). / 无法导出开料清单。`);
    try { const value = await response.json(); if (typeof value.detail === 'string') message = value.detail; } catch { /* Keep the friendly status. */ }
    throw new Error(message);
  }
  const scope = scopeId ? `-${scopeId.replace(/[^\p{L}\p{N}_.-]/gu, '-').slice(0, 70)}` : '';
  return { blob: await response.blob(), filename: `${review ? 'Panel-review' : 'Cutting-list'}${scope}-R${revision}.xlsx` };
}
export const studioAPI = {
  health: () => request<StudioHealth>('/health'),
  keySetup: () => request<unknown>('/key-setup', json({})),
  keySettings: () => request<KeySettings>('/key-settings'),
  saveKeySettings: (model: string, apiKey: string) => request<KeySettings>('/key-settings', json({ model, ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) })),
  shutdown: () => request<unknown>('/shutdown', json({})),
  projects: () => request<ProjectSummary[]>('/projects'),
  createProject: (name: string) => request<StudioProject>('/projects', json({ name })),
  project: (id: string) => request<StudioProject>(projectPath(id)),
  rename: (id: string, revision: number, name: string) => request<StudioProject>(projectPath(id) + '/name', { ...json({ name, expected_revision: revision }), method: 'PATCH' }),
  prepareDesign: (id: string, revision: number) => request<StudioProject>(projectPath(id) + '/prepare-design', json({ expected_revision: revision })),
  scene: (id: string) => request<StudioScene>(projectPath(id) + '/scene'),
  drawingSetURL: (id: string, proposal?: string) => BASE + projectPath(id) + '/drawings/export-set' + (proposal ? '?proposal_id=' + encodeURIComponent(proposal) : ''),
  demo: () => request<StudioProject>('/demo', json({})),
  preparedDemo: () => request<StudioProject>('/prepared-demo', json({})),
  reviewedDemo: () => request<StudioProject>('/reviewed-demo', json({})),
  showcase: () => request<ShowcaseManifest>('/showcase'),
  showcaseDemo: () => request<StudioProject>('/projects/showcase', json({})),
  showcaseAsset: (name: string) => BASE + '/showcase/assets/' + encodeURIComponent(name),
  referenceManifest: () => request<ReferenceDemoManifest>('/reference-demo'),
  referenceDemo: () => request<StudioProject>('/projects/reference-demo', json({})),
  referenceAsset: (name: string) => BASE + '/reference-demo/assets/' + encodeURIComponent(name),
  lifecycle: (id: string, revision: number, action: 'pause' | 'stop' | 'resume') => request<StudioProject>(projectPath(id) + '/lifecycle', json({ action, expected_revision: revision })),
  deleteProject: (id: string, revision: number) => request<{ deleted: boolean; id: string }>(projectPath(id) + `?expected_revision=${revision}`, { method: 'DELETE' }),
  materials: (includeInactive = false) => request<MaterialVariant[]>('/materials' + (includeInactive ? '?include_inactive=true' : '')),
  createMaterial: (material: MaterialInput) => request<MaterialVariant>('/materials', json(material)),
  updateMaterial: (id: string, version: number, material: MaterialInput) => request<MaterialVariant>(`/materials/${encodeURIComponent(id)}`, { ...json({ expected_version: version, material }), method: 'PUT' }),
  materialSuggestions: (id: string, revision: number, instruction: string, selection: string, replaceExisting = false, mode: MaterialSuggestionMode = 'api') => request<{ job_id: string }>(projectPath(id) + '/material-suggestions', json({ expected_revision: revision, instruction, selection, replace_existing: replaceExisting, mode })),
  materialPreview: (id: string, revision: number, part_ids: string[], material: MaterialVariant) => request<Proposal>(projectPath(id) + '/material-preview', json({ expected_revision: revision, part_ids, material_id: material.id, expected_material_version: material.version })),
  clearMaterialPreview: (id: string, revision: number, part_ids: string[]) => request<Proposal>(projectPath(id) + '/material-clear-preview', json({ expected_revision: revision, part_ids })),
  boardSpecPreview: (id: string, revision: number, part_id: string, spec: BoardSpec) => request<Proposal>(projectPath(id) + '/board-spec-preview', json({ expected_revision: revision, part_id, spec })),
  boardSpecsPreview: (id: string, revision: number, bom_sha256: string, scopeId?: string) => request<Proposal>(
    projectPath(id) + '/board-specs-preview', json({ expected_revision: revision, bom_sha256, ...(scopeId ? { scope_id: scopeId } : {}) })),
  bom: (id: string, scopeId?: string) => request<BOMReport>(projectPath(id) + '/bom' + (scopeId ? '?scope_id=' + encodeURIComponent(scopeId) : '')),
  exportBOM: (id: string, revision: number, bom_sha256: string, scopeId?: string) => exportBOMFile(id, revision, bom_sha256, scopeId, false),
  exportReviewBOM: (id: string, revision: number, bom_sha256: string, scopeId?: string) => exportBOMFile(id, revision, bom_sha256, scopeId, true),
  upload: (id: string, file: File) => {
    const data = new FormData(); data.append('file', file);
    return request<StudioProject & { imported_document_id?: string }>(projectPath(id) + '/documents', { method: 'POST', body: data });
  },
  importProject: (file: File) => {
    const data = new FormData(); data.append('file', file);
    return request<StudioProject>('/import', { method: 'POST', body: data });
  },
  analyze: (id: string, revision: number, instruction: string, retryProposalId?: string) => request<{ job_id: string }>(projectPath(id) + '/analyze', json({ expected_revision: revision, instruction, retry_proposal_id: retryProposalId })),
  analyzeGroups: (id: string, revision: number, instruction: string, rebuildSaved = false) => request<{ job_id: string }>(projectPath(id) + '/analyze-groups', json({ expected_revision: revision, instruction, ...(rebuildSaved ? { rebuild_saved: true } : {}) })),
  rebuild2D: (id: string, revision: number, instruction: string) => request<{ job_id: string }>(
    projectPath(id) + '/rebuild-2d', json({ expected_revision: revision, instruction })),
  resume2D: (id: string, revision: number, previousJobId: string) => request<{ job_id: string }>(
    projectPath(id) + '/resume-2d', json({ expected_revision: revision, previous_job_id: previousJobId })),
  retryDrawingGroup: (id: string, revision: number, groupId: string, previousJobId: string) => request<{ job_id: string }>(
    projectPath(id) + `/drawing-groups/${encodeURIComponent(groupId)}/retry`, json({ expected_revision: revision, previous_job_id: previousJobId })),
  rebuild2DGroups: (id: string, revision: number, sourceJobId: string, groupId?: string) => request<{ job_id: string }>(
    projectPath(id) + '/rebuild-2d-groups', json({ expected_revision: revision, source_job_id: sourceJobId, group_id: groupId })),
  generate3D: (id: string, revision: number, instruction: string) => request<{ job_id: string }>(projectPath(id) + '/generate-3d', json({ expected_revision: revision, instruction })),
  save3DDesign: (id: string, revision: number) => request<StudioProject>(projectPath(id) + '/save-3d-design', json({ expected_revision: revision })),
  generateGroup3DDraft: (id: string, revision: number, groupId: string, sourceJobId: string, instruction: string) => request<{ job_id: string }>(
    projectPath(id) + `/drawing-groups/${encodeURIComponent(groupId)}/generate-3d`, json({ expected_revision: revision, instruction, source_job_id: sourceJobId })),
  generateGroup3DDrafts: (id: string, revision: number, sourceJobId: string, instruction: string, resumeJobId?: string) => request<{ job_id: string }>(
    projectPath(id) + '/generate-3d-groups', json({ expected_revision: revision, instruction, source_job_id: sourceJobId, resume_job_id: resumeJobId })),
  group3DDraftScene: (jobId: string, signal?: AbortSignal) => request<StudioScene>(`/jobs/${encodeURIComponent(jobId)}/draft-3d/scene`, { signal }),
  edit: (id: string, revision: number, instruction: string, selection: string, screenshot: File | null, target: '2d' | '3d' = '2d') => {
    const data = new FormData(); data.append('expected_revision', String(revision)); data.append('instruction', instruction);
    data.append('selection', selection); data.append('target', target); if (screenshot) data.append('screenshot', screenshot);
    return request<{ job_id: string }>(projectPath(id) + '/ai-edit', { method: 'POST', body: data });
  },
  job: (id: string) => request<StudioJob>(`/jobs/${encodeURIComponent(id)}`),
  jobControl: (id: string, revision: number, action: 'pause' | 'resume' | 'stop') => request<StudioJob>(`/jobs/${encodeURIComponent(id)}/control`, json({ action, expected_revision: revision })),
  proposal: (id: string, proposal: string) => request<Proposal>(projectPath(id) + `/proposals/${encodeURIComponent(proposal)}`),
  redraw: (id: string, proposal: string, revision: number, instruction = '') => request<{ job_id: string }>(projectPath(id) + `/proposals/${encodeURIComponent(proposal)}/redraw`, json({ expected_revision: revision, instruction })),
  apply: (id: string, proposal: string, revision: number) => request<StudioProject>(projectPath(id) + `/proposals/${encodeURIComponent(proposal)}/apply`, json({ expected_revision: revision })),
  discard: (id: string, proposal: string) => request<unknown>(projectPath(id) + `/proposals/${encodeURIComponent(proposal)}/discard`, json({})),
  parameter: (id: string, revision: number, parameter_id: string, value_mm: number) => request<Proposal>(projectPath(id) + '/parameter-preview', json({ expected_revision: revision, parameter_id, value_mm })),
  interior: (id: string, command: Record<string, unknown>) => request<Proposal>(projectPath(id) + '/interior-preview', json(command)),
  restore: (id: string, revision: number, target_revision: number) => request<StudioProject>(projectPath(id) + '/restore', json({ expected_revision: revision, target_revision })),
  archiveURL: (id: string) => BASE + projectPath(id) + '/export',
  drawingURL: (id: string, view: string, format: 'pdf' | 'svg' | 'png', proposal?: string) => BASE
    + projectPath(id) + `/drawings/${encodeURIComponent(view)}/export?format=${format}`
    + (proposal ? `&proposal_id=${encodeURIComponent(proposal)}` : ''),
  portableRuntime: async () => {
    const response = await fetch(BASE + '/portable-runtime');
    if (!response.ok) throw new Error(t('Offline 3D export is unavailable in this build. / 此版本暂不能导出离线三维演示。'));
    return response.text();
  },
};
