"""Original-PDF -> automatic source groups -> reviewed native2D, inside the app.

No experiment manifests, customer constants, templates, credentials or project
database writes are read here. The caller owns the canonical cycle-ledger path.
"""
from __future__ import annotations

import base64
from collections import Counter
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
from typing import Literal
import xml.etree.ElementTree as ET

from PIL import Image,ImageDraw,ImageChops,ImageOps
from pydantic import BaseModel,ConfigDict,Field,ValidationError,model_validator

from .ai import BOUNDARY,SourceIndex,IndexedView,AIError,_invalid_extraction_details
from .api_drawing_workflow import (EvidenceExtraction,ReviewReport,ReviewBindings,ReviewFindingReferenceError,SourceRef,content_hash,evidence_model,
    validate_review,_source_identity)
from .drawing_models import DrawingPlan,DrawingViewPlan,DrawingView,DrawingPrimitive,DrawingRule,Role
from .drawing_workflow import _source_crops,_image,inventory_identity
from .drafting import compile_drawings,render_pdf,render_svg,render_png,drawing_hash,stamp_review,_object_geometry,assess_drawings,_review_note_layout
from .drawing_state import semantic_fingerprint
from .drawing_cycle_budget import DrawingCycleBudget,DrawingCycleError
from .native_group_selection import NativeGroupDecision,NativeGroupSelection,apply_group_selection,neutral_group_metadata
from .models import StudioModel,Part,expression_names
from .progress import monotonic_progress
from .source_vectors import build_inventory
from .reference_models import ReferencePlan
from .customer_references import ReferenceValidationError,build_anchor_catalog,required_reference_controls,resolve_reference_plan
from .reference_layout import reference_graphics,paper_layout,_label_box
from .group_inspection import build_held_group_inspections

MAX_REQUESTS=36
MAX_SOURCE_EXTRACTION_ATTEMPTS=2
MAX_CHECK_OUTPUT_LIMIT_RETRIES=1
MAX_CHECK_FINDING_REFERENCE_RETRIES=1
MAX_VIEWS=12
BATCH_GROUPS=64
MAX_GROUPS_PER_VIEW=512
MAX_GROUPS_PER_DRAWING_SET=576
MAX_SCOPE_CHECKS=3
CUSTOMER_REVIEW_POLICY={
    'id':'practical_customer_review_2d_v2',
    'standard':'Complete and readable customer-review views with correct main geometry and controlling dimensions; no major obvious errors.',
    'minor_cosmetic_notes_allowed':True,
    'cosmetic_severity_basis':'Impact in the requested view at its normal legible review scale, not visibility under magnification alone. Localized harmless residual texture can remain a minor note; prominent or confusing texture remains blocking.',
    'failed_or_unperformed_checks_allowed':False,
    'approval_requires_fresh_source_and_actual_output_review':True}
RULES={
 'R01':{'name':'Source scope','criterion':'Independently identify all source-supported requested views; verify displayed-page region, source word/path/image scope and view identity. No missing difficult views or foreign-source geometry.'},
 'R02':{'name':'Functional geometry','criterion':'Preserve every applicable physical profile, thin member, band, joint, opening, fixture contour and visible void; decoration cannot replace a real edge.'},
 'R03':{'name':'Dimensions','criterion':'Retain printed values, units, qualifiers, conflicts and recognizable owner/datum witness endpoints. Separately verify every required user-authorized numeric reference against its host derivation and true structural anchors, with complete blue graphics and pale-yellow numeric-only labels. References do not establish source scale or source-confirmed geometry.'},
 'R04':{'name':'Operation marks','criterion':'Preserve source operation symbol owner, orientation, both arms, dashes and terminal contacts; do not turn material grain into seams.'},
 'R05':{'name':'Material/reference identity','criterion':'Preserve source material names/codes/leaders, grid and view references with their real targets.'},
 'R06':{'name':'Authority','criterion':'Original observations and unresolved source controls stay immutable. User-authorized estimated design references remain a separate provenance-linked annotation/control map. No fabricated geometry or claim that references are confirmed source facts.'},
 'R07':{'name':'Actual readability','criterion':'Inspect saved PDF content/raster and relevant closeups for usable labels, intact physical contours and complete readable dimensions. Major clipping, ambiguous dimension ownership or illegible results fail; a harmless cosmetic imperfection may remain a minor background note.'},
 'R08':{'name':'Requested presentation','criterion':'Follow the user texture/annotation instructions; omit prominent appearance-only grain, speckle fields, reflection and narrow section hatch while preserving physical profiles/joints. Judge severity in the requested view at its normal legible review scale. Localized residual texture or section marks may remain minor cosmetic notes when they do not obscure geometry, dimensions or operation symbols or dominate the view, even if recognizable when magnified. Broad or confusing texture remains blocking. Historic source scale is not a claim of current metric scale; exported review is NTS.'},
 'R09':{'name':'2D cross-view consistency','criterion':'Reconcile original plan and numbered elevations against all relevant native2D views of this same candidate, their source-supported directions, identities/interfaces and conflicting observations. No3D model/projection is required at this2D stage.'},
 'R12':{'name':'Evidence and limits','criterion':'Use supplied host source/binding/PDF-raster/SVG structural proof and actual visual evidence separately. Counts/hashes are not semantic proof. No unperformed check can pass; no Apply,3D or fabrication approval.'}}


def _valid_review_region(region):
    return (isinstance(region,list) and len(region)==4
        and all(type(value) in (int,float) and math.isfinite(value) for value in region)
        and 0<=region[0]<region[2]<=1 and 0<=region[1]<region[3]<=1)


def _reference_review_evidence(drawings, reference_control_ids, parameter_ids):
    """Original supporting observations, derived only from resolved provenance.

    Citations do not resolve another control or waive a drawing check. Parent
    bounds and arithmetic may depend on another validated reference; include
    its original observations transitively, without inventing source values.
    """
    controls=set(reference_control_ids);known=set(parameter_ids)
    linked={ident:set() for ident in controls}
    for view in drawings:
        for ref in view.reference_annotations:
            if ref.control_id not in controls:continue
            linked[ref.control_id].update(ref.source_parameter_ids)
            arithmetic=ref.provenance.get('arithmetic',{})
            linked[ref.control_id].update(arithmetic.get('source_parameter_ids',[]))
            linked[ref.control_id].update(arithmetic.get('design_reference_control_ids',[]))
            linked[ref.control_id].update(item['parent_parameter_id']
                for item in ref.provenance.get('original_parent_bound_checks',[])
                if item.get('passed') is True and item.get('parent_parameter_id') in known)
    for _ in controls:
        expanded={ident:values|set().union(*(linked[dep] for dep in values&controls))
            for ident,values in linked.items()}
        if expanded==linked:break
        linked=expanded
    return {ident:sorted((values&known)-controls) for ident,values in linked.items()}


def _validate_group_resolutions(report, required_groups, rendered, documents):
    """Clear only exact, evidenced transient classifier questions in this check.

    Candidate/source/artifact report bindings and all normal drawing verdicts are
    checked independently. A disposition cannot waive an actual drawing defect.
    """
    expected={item['group_id']:item for item in required_groups}
    grouped={}
    for resolution in report.group_resolutions:
        grouped.setdefault(resolution.group_id,[]).append(resolution)
    extra=set(grouped)-set(expected)
    if extra:
        return set(),['Fresh group resolution cites unrequested groups: '+', '.join(sorted(extra))]
    artifacts={item['artifact_id']:item for item in rendered}
    imported={item['id']:item for item in documents}
    resolved=set();issues=[]
    region_valid=_valid_review_region
    def overlaps(a,b):
        return a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3]
    for ident,required in expected.items():
        records=grouped.get(ident,[]);problems=[]
        if len(records)!=1:
            issues.append(f'Fresh group resolution must cover {ident} exactly once.');continue
        resolution=records[0]
        if resolution.view_id!=required['view_id']:problems.append('wrong source view')
        if resolution.native_members_sha256!=required['native_members_sha256']:problems.append('changed native membership')
        if resolution.disposition=='unresolved':problems.append('checker left the group unresolved')
        if not resolution.reason.strip():problems.append('missing source-based reason')
        if any(ref.document_id not in imported or ref.page>imported[ref.document_id]['page_count']
            or (ref.region is not None and not region_valid(ref.region)) for ref in resolution.source_refs):
            problems.append('invalid source evidence')
        if not any(ref.document_id==required['document_id'] and ref.page==required['page']
            and region_valid(ref.region) and overlaps(ref.region,required['region']) for ref in resolution.source_refs):
            problems.append('missing own original source page/region evidence')
        if any(ref.artifact_id not in artifacts or (ref.region is not None and not region_valid(ref.region))
            for ref in resolution.artifact_refs):problems.append('invalid current artifact evidence')
        if not any(ref.artifact_id in artifacts and artifacts[ref.artifact_id]['view_id']==required['view_id']
            and ref.artifact_id in required['actual_artifact_ids']
            and ref.artifact_id.endswith(('.pdf','.png')) for ref in resolution.artifact_refs):
            problems.append('missing own actual current PDF or saved-PDF raster')
        if problems:issues.append(f'Fresh group resolution {ident}: '+', '.join(problems)+'.')
        else:resolved.add(ident)
    return resolved,issues


def _refinement_group_targets(reports, groups, drawings, rendered, held_ids=()):
    """Prefer known problem groups over inferred overlaps for bounded splitting."""
    by_group={group['group_id']:group for group in groups}
    by_view={view.id:view for view in drawings};artifacts={item['artifact_id']:item for item in rendered}
    exact_targets=set(held_ids)&set(by_group)
    region_targets=set()
    for raw in reports:
        report=ReviewReport.model_validate(raw) if isinstance(raw,dict) else raw
        for finding in report.findings:
            if finding.kind not in ('core','cosmetic') or not finding.repairable:continue
            own_views=set(finding.view_ids)
            named=set(re.findall(r'(?<![A-Za-z0-9_])G[0-9]{3,6}(?![A-Za-z0-9_])',
                '\n'.join((finding.id,finding.observed,finding.expected,finding.repair))))
            exact_targets.update(ident for ident in named if ident in by_group and by_group[ident]['view_id'] in own_views)
            # Dimension/reference creation and authority findings can cite a
            # whole page without identifying any native classification defect.
            # Explicit native group IDs above remain actionable for these rules.
            if finding.rule_id in ('R03','R06'):continue
            for reference in finding.artifact_refs:
                artifact=artifacts.get(reference.artifact_id)
                if (artifact is None or not reference.artifact_id.endswith(('.pdf','.png'))
                    or artifact['view_id'] not in own_views or not _valid_review_region(reference.region)):continue
                view=by_view.get(artifact['view_id'])
                if view is None:continue
                layout=paper_layout(view,_review_note_layout(view)[1]);left,top=layout['origin'];region=reference.region
                # Artifact regions describe the whole actual exported page,
                # including titles/reference lanes; native groups use its local
                # source canvas. Clip before intersection, never swap margins.
                actual_box=[region[0]*layout['width']-left,region[1]*layout['height']-top,
                    region[2]*layout['width']-left,region[3]*layout['height']-top]
                # Local reference labels can lie in clear source-frame space.
                # A finding wholly inside their owned annotation box cannot
                # identify native ink merely through a broad carrier bbox.
                # Explicit group IDs above remain inspection targets.
                if any(bounds[0]-1e-7<=actual_box[0] and bounds[1]-1e-7<=actual_box[1]
                    and actual_box[2]<=bounds[2]+1e-7 and actual_box[3]<=bounds[3]+1e-7
                    for bounds in (_label_box(label,2.) for label in reference_graphics(view)['labels'])):
                    continue
                box=[max(0.,actual_box[0]),max(0.,actual_box[1]),min(view.width,actual_box[2]),min(view.height,actual_box[3])]
                if box[2]<=box[0] or box[3]<=box[1]:continue
                for ident,group in by_group.items():
                    if group['view_id']!=view.id:continue
                    native=group['bbox']
                    if (native[0]<=box[2] and box[0]<=native[2] and native[1]<=box[3] and box[1]<=native[3]):region_targets.add(ident)
    # A rectangle can touch hundreds of carriers across views. It is useful
    # when no precise target exists, but cannot take budget from a known group.
    # Every group, split or whole, still receives fresh semantic classification.
    return exact_targets or region_targets


class AutonomousGroupDecision(NativeGroupDecision):
    reason:str=Field(min_length=1,max_length=800)
    owner_id:str|None=Field(default=None,max_length=160)
    role:Role|None=None


class AutonomousGroupSelection(NativeGroupSelection):
    groups:list[AutonomousGroupDecision]=Field(min_length=1,max_length=BATCH_GROUPS)


class AutonomousIndexedView(IndexedView):
    id:str=Field(pattern=r'^[A-Za-z_][A-Za-z0-9_-]{0,79}$')
    label:str=Field(min_length=1,max_length=200)
    kind:Literal['plan','elevation']


class AutonomousSourceIndex(SourceIndex):
    views:list[AutonomousIndexedView]=Field(min_length=1,max_length=MAX_VIEWS)


class SourceScopeBindings(BaseModel):
    model_config=ConfigDict(extra='forbid')
    project_id:str
    run_id:str
    source_set_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    candidate_index_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    atlas_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    crops_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')


class ScopedSourceRef(SourceRef):
    region:list[float]=Field(min_length=4,max_length=4)


class SourceScopeView(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    view_id:str=Field(pattern=r'^[A-Za-z_][A-Za-z0-9_-]{0,79}$')
    action:Literal['accept','refine','hold']
    document_id:str
    page:int=Field(ge=1)
    kind:Literal['plan','elevation']
    label:str=Field(min_length=1,max_length=200)
    plan_reference:str|None
    region:list[float]|None
    subject_region:list[float]|None
    annotation_regions:list[list[float]]=Field(max_length=40)
    operation_regions:list[list[float]]=Field(default_factory=list,max_length=40)
    context_regions:list[list[float]]=Field(max_length=20)
    source_refs:list[ScopedSourceRef]=Field(max_length=40)
    reason:str=Field(min_length=1,max_length=1600)

    @model_validator(mode='after')
    def valid_regions(self):
        for box in [self.region,self.subject_region,*self.annotation_regions,*self.operation_regions,*self.context_regions]:
            if box is not None:DrawingRule.region_values(box)
        if self.action!='hold' and (self.region is None or self.subject_region is None or not self.source_refs):
            raise ValueError('A usable source scope needs a subject region, complete crop and original-source evidence')
        return self


class SourceScopeReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    bindings:SourceScopeBindings
    verdict:Literal['PASS','REFINE','HOLD']
    views:list[SourceScopeView]=Field(min_length=1,max_length=MAX_VIEWS)
    warnings:list[str]=Field(max_length=100)
    title_only:bool=False
    reference_only:bool=False

    @model_validator(mode='after')
    def distinct_amendment_modes(self):
        if self.title_only and self.reference_only:raise ValueError('Title-only and reference-only hints cannot both be true.')
        return self


class SourceScopeCoverageError(ValueError):
    """A proposed frame was not applied because required source ink would be lost."""
    def __init__(self,feedback):
        self.feedback=copy.deepcopy(feedback)
        super().__init__('The proposed source frame clips previously established subject, annotation or owned operation coverage.')


def source_scope_coverage(review,required_coverage=None):
    """Accumulate source-bound required regions; neighboring context is not a lock."""
    result=copy.deepcopy(required_coverage or {})
    for view in review.views:
        if view.action=='hold':continue
        row=result.setdefault(view.view_id,{'document_id':view.document_id,'page':view.page,
            'subject_regions':[],'annotation_regions':[],'operation_regions':[]})
        if (row['document_id'],row['page'])!=(view.document_id,view.page):
            raise ValueError('Established source coverage cannot be rebound to another document or page.')
        for name,boxes in (('subject_regions',[view.subject_region]),('annotation_regions',view.annotation_regions),('operation_regions',view.operation_regions)):
            for box in boxes:
                if box is not None and box not in row[name]:row[name].append(list(box))
    return result


def validate_source_scope(review,bindings,index,documents,required_coverage=None):
    """Bound a whole-map subject check; no drawing or physical dimension is made."""
    review=SourceScopeReview.model_validate(review.model_dump() if hasattr(review,'model_dump') else review)
    if review.bindings!=bindings:raise _Hold('The source-scope check belongs to different source images or mapping content.')
    old={v.id:v for v in index.views};decisions={v.view_id:v for v in review.views}
    if len(decisions)!=len(review.views) or set(decisions)!=set(old):raise _Hold('The source-scope check must preserve every required view exactly once.')
    if review.verdict=='HOLD' or any(v.action=='hold' for v in review.views):return index.model_copy(deep=True),False
    if review.verdict=='PASS' and any(v.action!='accept' for v in review.views):raise _Hold('A passing source-scope check cannot contain an unverified refinement.')
    if review.verdict=='REFINE' and not any(v.action=='refine' for v in review.views):raise _Hold('Source refinement requires a specific changed source frame.')
    docs={d['id']:d for d in documents};result=index.model_copy(deep=True)
    def contained(inner,outer):return outer[0]<=inner[0]<=inner[2]<=outer[2] and outer[1]<=inner[1]<=inner[3]<=outer[3]
    coverage_failures=[]
    for decision in review.views:
        previous=old[decision.view_id]
        if decision.kind!=previous.kind or decision.document_id not in docs or decision.page>docs[decision.document_id]['page_count']:
            raise _Hold('A source-scope refinement cannot invent a view type or unavailable source page.')
        if not decision.reason.strip():raise _Hold('Source scope needs an evidence-based reason.')
        if not any(ref.document_id==decision.document_id and ref.page==decision.page and
            ref.region[0]<decision.region[2] and decision.region[0]<ref.region[2] and
            ref.region[1]<decision.region[3] and decision.region[1]<ref.region[3] for ref in decision.source_refs):
            raise _Hold('Each source-scope decision needs evidence from its own original source page.')
        for ref in decision.source_refs:
            if ref.document_id not in docs or ref.page>docs[ref.document_id]['page_count']:raise _Hold('Source-scope evidence cites an unavailable page.')
            DrawingRule.region_values(ref.region)
        for name,boxes in (('subject_regions',[decision.subject_region]),('annotation_regions',decision.annotation_regions),
            ('operation_regions',decision.operation_regions),('context_regions',decision.context_regions)):
            for box in boxes:
                if not contained(box,decision.region):coverage_failures.append({'view_id':decision.view_id,'code':'declared_coverage_outside_crop',
                    'coverage_kind':name,'required_region':list(box),'reason':'Retain the complete declared source feature; adjacent geometry can be cleaned later.'})
        established=(required_coverage or {}).get(decision.view_id)
        if established:
            if (established['document_id'],established['page'])!=(decision.document_id,decision.page):
                coverage_failures.append({'view_id':decision.view_id,'code':'established_source_changed',
                    'reason':'Established source coverage belongs to the retained original document/page; it cannot be silently discarded.'})
            else:
                for name in ('subject_regions','annotation_regions','operation_regions'):
                    for box in established[name]:
                        if not contained(box,decision.region):coverage_failures.append({'view_id':decision.view_id,'code':'established_coverage_outside_crop',
                            'coverage_kind':name,'required_region':list(box),'reason':'This source feature was already established and must remain inside the crop.'})
        unchanged=(decision.document_id,decision.page,decision.region)==(previous.document_id,previous.page,previous.region)
        if decision.action=='accept' and not unchanged:raise _Hold('A changed source frame requires refinement and a fresh crop check.')
        if decision.action=='refine' and unchanged and decision.label==previous.label and decision.plan_reference==previous.plan_reference:
            raise _Hold('The source-scope refinement did not change its proposed mapping.')
        target=next(v for v in result.views if v.id==decision.view_id)
        target.document_id=decision.document_id;target.page=decision.page;target.region=list(decision.region)
        target.label=decision.label;target.plan_reference=decision.plan_reference;target.correspondence_notes=decision.reason
    if coverage_failures:raise SourceScopeCoverageError(coverage_failures[:20])
    result.warnings=list(dict.fromkeys([*index.warnings,*review.warnings]))
    return result,review.verdict=='PASS'


class _Hold(ValueError):pass


def _drawing_catalogs(inventory):
    from .automatic_native_groups import build_automatic_catalog
    parts=[{**inventory,'views':[view]} for view in inventory['views']]
    catalogs=[build_automatic_catalog(part,max_groups=MAX_GROUPS_PER_VIEW) for part in parts]
    number=0
    for catalog in catalogs:
        for group in catalog['groups']:
            number+=1;group['group_id']=f'G{number:06d}'
    if number>MAX_GROUPS_PER_DRAWING_SET:
        raise _Hold(f'The selected source area is too broad for safe processing ({number} groups, limit {MAX_GROUPS_PER_DRAWING_SET}). Focus on one room or cabinet.')
    return parts,catalogs


def _text(value):return {'type':'input_text','text':json.dumps(value,ensure_ascii=False,allow_nan=False)}
def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _key(value):return hashlib.sha256(str(value).encode()).hexdigest()[:20]


def _source_review_notes(extraction):
    """Disclose API-extracted uncertainty outside the unchanged source geometry."""
    notes=list(dict.fromkeys(text.strip() for text in extraction.warnings if text.strip()))
    unknown=list(dict.fromkeys(p.label for p in extraction.parameters if p.status=='tbc'))
    if unknown:notes.append('TBC controls: '+'; '.join(unknown)+'. No controlling sizes have been assumed.')
    if len(notes)>32 or any(len(text)>1600 for text in notes):
        raise _Hold('The source uncertainty notes exceed the bounded readable drawing group; use a smaller source scope.')
    return notes


def _source_extraction_feedback(error,candidate):
    """Describe rejected structure without editing, parenting or solving it."""
    feedback=copy.deepcopy(getattr(error,'validation_feedback',None) or getattr(error,'validation_errors',[]) or [])[:100]
    if not isinstance(candidate,dict):return feedback
    rows=candidate.get('owners',[])
    if not isinstance(rows,list):return feedback
    owners=[row for row in rows[:1000] if isinstance(row,dict)]
    roots=[row.get('id') for row in owners if row.get('parent_id') is None]
    if len(roots)!=1:
        feedback.append({'code':'owner_root_count','loc':['owners'],'type':'owner_graph',
            'message':'Extraction requires exactly one owner root; the model must produce a complete source-supported hierarchy.',
            'observed_root_count':len(roots),'root_owner_ids':[value[:160] for value in roots[:30] if isinstance(value,str)]})
    ids=[row['id'] for row in owners if isinstance(row.get('id'),str)];counts=Counter(ids);known=set(ids)
    duplicate=sorted(ident for ident,count in counts.items() if count>1)
    if duplicate:feedback.append({'code':'duplicate_owner_ids','loc':['owners'],'type':'owner_graph',
        'message':'Owner identities must be unique.','owner_ids':[ident[:160] for ident in duplicate[:30]]})
    missing=[{'owner_id':row['id'][:160],'parent_id':row['parent_id'][:160]} for row in owners
        if isinstance(row.get('id'),str) and isinstance(row.get('parent_id'),str) and row['parent_id'] not in known]
    if missing:feedback.append({'code':'missing_owner_parents','loc':['owners'],'type':'owner_graph',
        'message':'Every non-root owner must reference an existing source-supported parent.','owners':missing[:30]})
    return feedback[:100]


def _unaccepted_extraction_source_issues(candidate,index,documents):
    """An invalid graph cannot conceal drift from the pinned original source."""
    if not isinstance(candidate,dict):return []
    issues=[]
    if content_hash(candidate.get('source_index'))!=content_hash(index.model_dump()):
        issues.append({'code':'pinned_source_index_drift','loc':['source_index'],'type':'source_identity',
            'message':'The unaccepted candidate differs from the pinned source index; this is not an owner-graph correction.'})
    docs={item['id']:item for item in documents}
    for field in ('owners','parameters'):
        rows=candidate.get(field,[])
        if not isinstance(rows,list):continue
        for number,row in enumerate(rows):
            refs=row.get('evidence',[]) if isinstance(row,dict) else []
            if not isinstance(refs,list):continue
            for ordinal,ref in enumerate(refs):
                if not isinstance(ref,dict):continue
                ident=ref.get('document_id');page=ref.get('page')
                numeric_page=type(page) in (int,float)
                invalid_page=numeric_page and ((type(page) is float and (not math.isfinite(page) or not page.is_integer()))
                    or (isinstance(ident,str) and ident in docs and not 1<=page<=docs[ident].get('page_count',1)))
                if (isinstance(ident,str) and ident not in docs) or (isinstance(ident,str) and ident in docs
                        and invalid_page):
                    issues.append({'code':'foreign_source_evidence','loc':[field,number,'evidence',ordinal],'type':'source_identity',
                        'message':'The unaccepted candidate cites evidence outside the imported original source documents/pages.'})
                    if len(issues)>=100:return issues
    return issues


def _original_cross_view_evidence(extraction):
    """Compact immutable source observations for independent full-group checks."""
    raw=extraction.model_dump();bindings={}
    for item in raw['dimension_bindings']:
        bindings.setdefault(item['parameter_id'],[]).append({'owner_id':item['owner_id'],'axis':item['axis']})
    observations=[{'parameter_id':item['id'],'label':item['label'],'status':item['status'],
        'value_mm':item.get('value_mm'),'observed_value_mm':item.get('observed_value_mm'),
        'expression':item.get('expression'),'source_refs':copy.deepcopy(item['evidence']),
        'owner_axis_bindings':bindings.get(item['id'],[])} for item in raw['parameters']]
    return {'source_extraction_sha256':content_hash(raw),'observations_sha256':content_hash(observations),
        'observations':observations,'source_warnings':copy.deepcopy(raw['warnings']),
        'source_index_warnings':copy.deepcopy(raw['source_index']['warnings']),
        'scope':'Unchanged original numeric observations, unknowns, formulas and conflict warnings for independent cross-view reconciliation. These are source records, not customer-reference values, endpoint proofs, semantic resolutions or approval.'}


def _scoped_checker_evidence(extraction,drawings,requested,reference_parameters,reference_audit):
    """Detailed facts stay in the requested batch; correspondence remains global."""
    raw=extraction.model_dump();selected=set(requested)
    source_views=[view for view in raw['source_index']['views'] if view['id'] in selected]
    def relevant(ref):
        return any(ref['document_id']==view['document_id'] and ref['page']==view['page'] and
            (ref.get('region') is None or (ref['region'][0]<view['region'][2] and view['region'][0]<ref['region'][2]
             and ref['region'][1]<view['region'][3] and view['region'][1]<ref['region'][3])) for view in source_views)
    local=[view for view in drawings if view.id in selected]
    annotations=[ref for view in local for ref in view.reference_annotations];controls={ref.control_id for ref in annotations}
    parameter_ids={item['id'] for item in raw['parameters'] if any(relevant(ref) for ref in item['evidence'])}
    parameter_ids.update(controls)
    for ref in annotations:parameter_ids.update(ref.source_parameter_ids)
    parameters={item['id']:item for item in raw['parameters']};pending=list(parameter_ids)
    while pending:
        item=parameters.get(pending.pop());names=expression_names(item['expression']) if item and item.get('expression') is not None else set()
        for name in names-parameter_ids:parameter_ids.add(name);pending.append(name)
    owners={item['id']:item for item in raw['owners']}
    owner_ids={item['id'] for item in raw['owners'] if any(relevant(ref) for ref in item['evidence'])}
    owner_ids.update(ref.owner_id for ref in annotations);owner_ids.update(ident for view in local for ident in view.owner_ids)
    pending=list(owner_ids)
    while pending:
        item=owners.get(pending.pop());parent=item.get('parent_id') if item else None
        if parent is not None and parent not in owner_ids:owner_ids.add(parent);pending.append(parent)
    scoped_facts={**raw,'source_index':{**raw['source_index'],'views':source_views,'warnings':[]},
        'owners':[{**item,'evidence':[ref for ref in item['evidence'] if relevant(ref)]} for item in raw['owners'] if item['id'] in owner_ids],
        'parameters':[{**item,'evidence':[ref for ref in item['evidence'] if relevant(ref)]} for item in raw['parameters'] if item['id'] in parameter_ids],
        'dimension_bindings':[item for item in raw['dimension_bindings'] if item['owner_id'] in owner_ids and item['parameter_id'] in parameter_ids],
        'warnings':[],'context_scope':'Requested-view evidence subset; necessary ancestor/dependency identities and values may remain without foreign-view evidence detail. Original complete extraction remains unchanged in the background audit.'}
    audit={key:copy.deepcopy(value) for key,value in reference_audit.items() if key not in ('derivations','parent_bound_checks','validation_issues')}
    audit['derivations']={key:copy.deepcopy(value) for key,value in reference_audit.get('derivations',{}).items() if key in controls}
    audit['parent_bound_checks']=[copy.deepcopy(item) for item in reference_audit.get('parent_bound_checks',[]) if item.get('control_id') in controls]
    audit['validation_issues']=[copy.deepcopy(item) for item in reference_audit.get('validation_issues',[]) if item.get('view_id') in selected
        or item.get('view_id') is None and item.get('control_id') in parameter_ids]
    dependencies={ident for ref in annotations for ident in ref.source_parameter_ids}-controls
    return {'extracted_facts':scoped_facts,'reference_parameters':{key:copy.deepcopy(value) for key,value in reference_parameters.items() if key in controls},
        'requested_reference_control_ids':sorted(controls),'host_audit':audit,
        'dependency_reference_values':{key:reference_parameters[key]['value_mm'] for key in sorted(dependencies) if key in reference_parameters},
        'full_group_correspondence':{'views':[{'view_id':view.id,'label':view.label,'kind':view.kind,'document_id':view.document_id,
            'page':view.page,'region':view.region,'reference_control_ids':[ref.control_id for ref in view.reference_annotations],
            'reference_count':len(view.reference_annotations)} for view in drawings],
            'required_reference_count':len(reference_audit.get('required_control_ids',[])),
            'resolved_reference_count':len(reference_parameters),'original_source_warning_count':len(raw['warnings']),
            'scope':'Complete-group correspondence and coverage only; other-view annotations/derivations are checked in their own batches.'}}


def _checker_overview(rendered):
    rows=[item for item in rendered if item['path'].endswith('.png')]
    if not rows:return None
    sheet=Image.new('RGB',(960,math.ceil(len(rows)/3)*354),'#edf0ed');draw=ImageDraw.Draw(sheet)
    for number,item in enumerate(rows):
        x=(number%3)*320;y=(number//3)*354;draw.text((x+5,y+5),item['view_id'][:48],fill='black')
        with Image.open(item['path']) as image:
            image=image.convert('RGB');image.thumbnail((310,320));sheet.paste(image,(x+(320-image.width)//2,y+24))
    output=io.BytesIO();sheet.save(output,format='PNG');return output.getvalue()


def _verified_baseline(model,documents):
    """Reuse app-owned checked source views/facts for a styling amendment only."""
    fingerprint=semantic_fingerprint(model);docs={d['id']:d for d in documents}
    if not model.drawings or {v.id for v in model.drawings}!={v.id for v in model.views} or len(model.drawings)!=len(model.views):
        raise _Hold('A styling amendment requires the complete checked source-view group from the saved project.')
    quality=assess_drawings(model.drawings,expected_views=[v.id for v in model.views])
    if quality['status']!='ready' or any(v.semantic_snapshot!=fingerprint or v.representation!='source' for v in model.drawings):
        raise _Hold('The saved 2D baseline is not current and fully checked. Complete its review before starting a new styling amendment.')
    for view in model.drawings:
        if view.document_id not in docs or view.source_sha256!=docs[view.document_id]['sha256'] or view.page>docs[view.document_id]['page_count']:
            raise _Hold('The saved 2D baseline belongs to different original source bytes or pages.')
    index=AutonomousSourceIndex(project_name=model.name,warnings=[],views=[AutonomousIndexedView(id=v.id,label=v.label,
        kind=v.kind,document_id=v.document_id,page=v.page,region=v.region,plan_reference=None,
        correspondence_notes='Complete checked source-view identity retained from the saved app baseline.') for v in model.drawings])
    owners=[]
    def walk(part,parent=None):
        owners.append({'id':part.id,'parent_id':parent,'name':part.name,'kind':part.kind,'evidence':[e.model_dump() for e in part.evidence]})
        for child in part.children:walk(child,part.id)
    walk(model.root)
    if any(p.status not in ('source','tbc','inferred') for p in model.parameters):
        raise _Hold('This source-cleanup amendment cannot reinterpret user-designed dimension changes. Keep the existing parameter controls and use the linked geometry workflow.')
    bindings={}
    for drawing in model.drawings:
        for ref in drawing.reference_annotations:
            recovered=[{**binding,'parameter_id':ref.control_id} for binding in
                ref.provenance.get('original_control_bindings',[{'owner_id':ref.owner_id,'axis':ref.axis}])]
            recovered.extend({'owner_id':item['parent_owner_id'],'axis':item['axis'],'parameter_id':item['parent_parameter_id']}
                for item in ref.provenance.get('original_parent_bound_checks',[]))
            for binding in recovered:
                key=(binding['owner_id'],binding['axis'])
                item=dict(binding)
                if key in bindings and bindings[key]!=item:raise _Hold('Saved reference control bindings conflict across the checked baseline.')
                bindings[key]=item
    extraction=EvidenceExtraction.model_validate({'source_index':index.model_dump(),'owners':owners,
        'parameters':[p.model_dump() for p in model.parameters],'dimension_bindings':list(bindings.values()),'warnings':model.warnings})
    evidence_model(extraction,documents)  # Validate all original evidence without replacing the saved model.
    return index,extraction


def _saved_reference_guidance(drawings,required_controls):
    """Recover saved proposals as guidance; never reuse their validation pass."""
    estimates={};parameters={}
    for drawing in drawings:
        for reference in drawing.reference_annotations:
            estimate=reference.provenance.get('estimate')
            if not isinstance(estimate,dict):raise _Hold('Saved reference guidance lacks its original typed estimate.')
            if reference.control_id in estimates and content_hash(estimates[reference.control_id])!=content_hash(estimate):
                raise _Hold('Saved reference proposals disagree across the checked view group.')
            estimates[reference.control_id]=copy.deepcopy(estimate)
            parameters[reference.control_id]=dict(value_mm=reference.value_mm,label=reference.label,method=reference.method,
                confidence=reference.confidence,owner_id=reference.owner_id,estimate_id=reference.estimate_id,
                provenance_digest=reference.provenance_digest)
    required={item['control_id'] for item in required_controls}
    if not required or set(estimates)!=required:
        raise _Hold('A reference-only amendment needs every required reference in its complete checked baseline.')
    plan=ReferencePlan.model_validate({'estimates':[estimates[ident] for ident in sorted(estimates)]})
    return plan.model_dump(),parameters


def _page_atlas(documents,output,control):
    """Displayed-page images and native word positions, never a cropped-PDF trick."""
    import pdfplumber,pypdfium2 as pdfium
    from .source_vectors import _extract_words
    from .documents import _PDF_RENDER_LOCK
    if sum(d['page_count'] for d in documents)>12:raise _Hold('More than 12 source pages need an explicitly smaller source scope.')
    result=[]
    for document in documents:
        if document.get('media_type','application/pdf')!='application/pdf':raise _Hold('Autonomous native2D currently requires original vector PDF sources.')
        with pdfplumber.open(document['local_path']) as native:
            for number,page in enumerate(native.pages,1):
                control();words=_extract_words(page)
                rows=[{'text':w['text'],'region':[round(w['x0']/page.width,6),round(w['top']/page.height,6),round(w['x1']/page.width,6),round(w['bottom']/page.height,6)]} for w in words]
                if len(rows)>5000:raise _Hold('A source page exceeds the bounded native-word atlas; reduce source scope.')
                with _PDF_RENDER_LOCK,pdfium.PdfDocument(Path(document['local_path']).read_bytes()) as pdf:
                    p=pdf[number-1]
                    try:
                        width,height=p.get_size();bitmap=p.render(scale=min(2.,1600/max(width,height)))
                        try:
                            image=bitmap.to_pil().copy();path=output/f'atlas-{_key(document["id"])}-{number}.png';image.save(path)
                        finally:bitmap.close()
                    finally:p.close()
                result.append({'document_id':document['id'],'page':number,'width':page.width,'height':page.height,
                    'rotation':page.rotation,'words':rows,'image_path':str(path),'image_sha256':_sha(path),
                    'text_visibility_limit':'Native text may include painted-over glyphs; original image controls visible appearance.'})
    return result


def _saved_pdf_png(path,max_size=1600):
    import pypdfium2 as pdfium
    from .documents import _PDF_RENDER_LOCK
    with _PDF_RENDER_LOCK,pdfium.PdfDocument(Path(path).read_bytes()) as pdf:
        if len(pdf)!=1:raise _Hold('Each native view export must contain exactly one page.')
        page=pdf[0]
        try:
            w,h=page.get_size();bitmap=page.render(scale=max_size/max(w,h))
            try:
                output=io.BytesIO();bitmap.to_pil().save(output,format='PNG');return output.getvalue()
            finally:bitmap.close()
        finally:page.close()


def _svg_proof(path,view):
    raw=Path(path).read_bytes()
    if raw!=render_svg(view).encode():raise _Hold('Saved SVG serialization is not bound to this native view.')
    root=ET.fromstring(raw);counts={};texts=[]
    allowed={'svg','defs','clipPath','path','rect','text','g','title','desc'}
    for element in root.iter():
        kind=element.tag.split('}')[-1]
        if kind not in allowed or any(k.lower().startswith('on') or k.split('}')[-1] in ('href','src') for k in element.attrib):
            raise _Hold('Saved SVG contains unsupported executable/external content.')
        counts[kind]=counts.get(kind,0)+1
        if kind=='text':texts.append(''.join(element.itertext()))
    return {'serialization_matches_candidate':True,'safe_xml_elements':counts,'text_content':texts,
        'view_box':root.get('viewBox'),'svg_visual_browser_raster_performed':False,
        'scope':'SVG structure/serialization audited locally; independent browser raster not claimed.'}


def _existing_scope(path,project_id,documents):
    if not Path(path).exists():return None,None
    data=json.loads(Path(path).read_text(encoding='utf-8'));by_sha={d['sha256']:d['id'] for d in documents}
    views=[]
    for item in data['views']:
        if item['source_sha256'] not in by_sha:raise DrawingCycleError('Source drift cannot renew the project conversion budget.')
        views.append(IndexedView(id=item['id'],document_id=by_sha[item['source_sha256']],page=item['page'],kind=item['kind'],
            region=item['region'],label=item['id'],plan_reference=None,correspondence_notes='Persistent automatic full-group source identity.'))
    ledger=DrawingCycleBudget(path,project_id=project_id,documents=documents,required_views=views)
    return views,ledger


def _owner_ids(model):
    result=set()
    def visit(node):
        result.add(node.id)
        for child in node.children:visit(child)
    visit(model.root);return result


def _inspection_crop(full,view,box):
    """Crop inspection pixels within the visible source canvas; never swap edges."""
    left=max(0.,min(view.width,box[0]));top=max(0.,min(view.height,box[1]))
    right=max(0.,min(view.width,box[2]));bottom=max(0.,min(view.height,box[3]))
    if right<=left or bottom<=top:return None
    layout=paper_layout(view,_review_note_layout(view)[1]);origin_x,origin_y=layout['origin']
    sx=full.width/layout['width'];sy=full.height/layout['height']
    pixel=(max(0,min(full.width,math.floor((origin_x+left)*sx))),max(0,min(full.height,math.floor((origin_y+top)*sy))),
        max(0,min(full.width,math.ceil((origin_x+right)*sx))),max(0,min(full.height,math.ceil((origin_y+bottom)*sy))))
    if pixel[2]<=pixel[0] or pixel[3]<=pixel[1]:return None
    return full.crop(pixel)


def _contact_sheets(inventory,groups,output,prefix,control,source_images=None):
    """Isolated native groups; no geometry is synthesized or source data altered."""
    by_view={v['id']:v for v in inventory['views']};images=[]
    for offset in range(0,len(groups),12):
        sheet=Image.new('RGB',(1200,1000),'#edf0ed');draw=ImageDraw.Draw(sheet)
        context_sheet=Image.new('RGB',(1200,1000),'#edf0ed') if source_images is not None else None
        context_draw=ImageDraw.Draw(context_sheet) if context_sheet is not None else None
        for slot,group in enumerate(groups[offset:offset+12]):
            control();source=by_view[group['view_id']];members=set(group['native_ids'])
            primitives=[DrawingPrimitive.model_validate(p) for p in source['primitives'] if p['id'] in members]
            for p in primitives:p.role='geometry'
            view=DrawingView(id=source['id'],label=group['group_id'],kind=source['kind'],document_id=source['document_id'],page=source['page'],
                region=source['region'],source_sha256=source['source_sha256'],width=source['width'],height=source['height'],primitives=primitives)
            raw=render_png(view,max_size=1800);full=Image.open(io.BytesIO(raw)).convert('RGB')
            box=group.get('bbox') or [min(p.bbox[0] for p in primitives),min(p.bbox[1] for p in primitives),max(p.bbox[2] for p in primitives),max(p.bbox[3] for p in primitives)]
            margin=max(3.,max((p.stroke_width/2 for p in primitives if p.kind=='path' and p.stroke),default=0.))
            visible=[max(0.,box[0]-margin),max(0.,box[1]-margin),min(view.width,box[2]+margin),min(view.height,box[3]+margin)]
            x=(slot%4)*300;y=(slot//4)*330
            draw.text((x+8,y+5),group['group_id']+' '+group['view_id'][:28],fill='black')
            if context_sheet is not None:
                # Inspection overlay only. Position the same isolated native
                # ink on the unchanged original source crop, so a tiny stroke
                # can be understood at its real fixture/boundary location.
                # This never creates candidate geometry or classifies a group.
                context_draw.text((x+8,y+5),group['group_id']+' '+group['view_id'][:28],fill='black')
                context_draw.text((x+8,y+20),'Local source context / selected ink red',fill='#555555')
                with Image.open(io.BytesIO(source_images[source['id']])) as original:
                    background=original.convert('RGB')
                native_canvas=_inspection_crop(full,view,[0.,0.,view.width,view.height])
                if native_canvas is not None:
                    native_canvas=native_canvas.resize(background.size,Image.Resampling.LANCZOS)
                    selected=ImageOps.invert(native_canvas.convert('L')).point(lambda p:255 if p>90 else 0)
                    visible_ink=ImageOps.invert(background.convert('L')).point(lambda p:255 if p>35 else 0)
                    selected=ImageChops.multiply(selected,visible_ink)
                    muted=Image.blend(background,Image.new('RGB',background.size,'white'),.35)
                    overlay=Image.composite(Image.new('RGB',background.size,'#c02020'),muted,selected)
                else:overlay=background
                context_margin=max(16.,min(view.width,view.height)*.12)
                frame=[max(0.,box[0]-context_margin),max(0.,box[1]-context_margin),
                    min(view.width,box[2]+context_margin),min(view.height,box[3]+context_margin)]
                if frame[0]<frame[2] and frame[1]<frame[3]:
                    pixel=(max(0,math.floor(frame[0]/view.width*overlay.width)),max(0,math.floor(frame[1]/view.height*overlay.height)),
                        min(overlay.width,math.ceil(frame[2]/view.width*overlay.width)),min(overlay.height,math.ceil(frame[3]/view.height*overlay.height)))
                    overlay=overlay.crop(pixel)
                overlay.thumbnail((290,285));context_sheet.paste(overlay,(x+(300-overlay.width)//2,y+38))
            # Native bounds can extend far beyond a cropped source view. Pad
            # before intersection so legitimate zero-span strokes stay visible.
            image=_inspection_crop(full,view,visible)
            if image is None:
                draw.rectangle((x+5,y+25,x+295,y+215),fill='white')
                draw.text((x+12,y+45),'Group bounds outside source view',fill='#555555')
                continue
            image.thumbnail((290,190));sheet.paste(image,(x+(300-image.width)//2,y+25))
            # Honest top/middle/end detail samples supplement, not replace, the
            # whole-group crop and separately supplied original full-source view.
            width=visible[2]-visible[0];height=visible[3]-visible[1];span=max(12.,min(60.,min(width,height)*3))
            for sample,fraction in enumerate((0.,.5,1.)):
                cx=visible[0]+width*(fraction if width>=height else .5);cy=visible[1]+height*(fraction if height>width else .5)
                detail=_inspection_crop(full,view,[cx-span/2,cy-span/2,cx+span/2,cy+span/2])
                if detail is None:
                    draw.text((x+sample*100+5,y+240),'Outside view',fill='#555555');continue
                detail.thumbnail((94,94));sheet.paste(detail,(x+sample*100,y+225))
        path=output/f'{prefix}-{offset//12:02d}.png';sheet.save(path);images.append(path)
        if context_sheet is not None:
            path=output/f'{prefix}-context-{offset//12:02d}.png';context_sheet.save(path);images.append(path)
    return images


def run_autonomous_2d(gateway,documents,output_dir,*,project_id,run_id,instruction,current_model=None,
                     progress=None,check_control=None,cycle_ledger_path=None,selection='',screenshot=None,screenshot_type='image/png',preserve_baseline=False,initial_index=None):
    """No source-specific caller manifest, classification, correction or3D input."""
    output=Path(output_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    progress=monotonic_progress(progress);usage=[];issues=[];index=None;ledger=None;lease=None;request_count=0
    model=StudioModel.model_validate(current_model.model_dump() if hasattr(current_model,'model_dump') else current_model) if current_model else StudioModel(name='Original source2D',root=Part(id='SOURCE_ROOT',name='Original source',physical=False))
    model=model.model_copy(deep=True);model.requires_source_drawings=True;accepted=False;qualifications=[];stage='preflight';artifacts=[];reports=[]
    required_coverage={};scope_feedback=[];scope_checks=0;scope_frame_updates=0
    baseline_extraction=None;baseline_images={};baseline_members={};baseline_input_hash=None;baseline_frames={};title_only_baseline=False;reference_only_baseline=False
    reference_parameters={};reference_audit={};required_controls=[];reference_feedback=[];reference_history=[]
    reference_corrections=[]
    prior_valid_reference_plan=None;prior_valid_reference_parameters={};prior_reference_proposal=None
    source_extraction_attempts=0;source_extraction_validation=[];source_extraction_accepted=False
    check_output_limit_retries=0;check_output_limit_retry_records=[]
    check_finding_reference_retries=[]
    last_complete_output=None;recovered_complete_cycle=None;incomplete_output_cycle=None
    prompts_dir=Path(__file__).with_name('prompts')
    prompt_paths=[prompts_dir/f'autonomous_2d_{name}.md' for name in ('index','scope','extract','select','references','check')]
    prompts={p.stem.removeprefix('autonomous_2d_'):p.read_text(encoding='utf-8') for p in prompt_paths}
    prompt_pins={str(p):_sha(p) for p in prompt_paths};artifact_pins={};source_hash=None
    def save(name, value):
        destination = output / name
        temporary = destination.with_suffix(destination.suffix + '.tmp')
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    control_error=None
    def control():
        nonlocal control_error
        if check_control:
            try:check_control()
            except Exception as error:control_error=error;raise
    display_phase='reading_sources';display_percent=5
    def emit(phase,percent):
        nonlocal display_phase,display_percent,control_error,stage
        display_phase=phase;display_percent=percent;stage=phase
        control()
        if progress:
            try:progress(phase,percent)
            except Exception as error:control_error=error;raise
    def unchanged():
        control()
        if source_hash and _source_identity(documents)!=source_hash:raise _Hold('Original source bytes changed during autonomous2D.')
        if baseline_input_hash and content_hash(current_model.model_dump() if hasattr(current_model,'model_dump') else current_model)!=baseline_input_hash:
            raise _Hold('The saved amendment baseline changed during its fresh review.')
        if any(_sha(p)!=value for p,value in [*prompt_pins.items(),*artifact_pins.items()]):raise _Hold('Prompt or saved source/output evidence changed during a request.')
    def call(schema,name,content):
        nonlocal request_count,stage,source_extraction_attempts
        unchanged();stage=name
        if request_count>=MAX_REQUESTS:raise _Hold('The 36-request limit for this 2D check has been reached.')
        request_count+=1
        if schema is EvidenceExtraction and name=='extract':source_extraction_attempts+=1
        save('request-state.json',{'phase':name,'request_count':request_count,'max_requests':MAX_REQUESTS})
        def streaming_progress(*_):
            nonlocal control_error
            control()
            if progress:
                try:progress(display_phase,display_percent)
                except Exception as error:control_error=error;raise
        try:value,run=gateway._request(schema,BOUNDARY+prompts[name.split('_')[0]],content,progress=streaming_progress)
        except Exception as error:
            if getattr(error,'usage',None):usage.append({**error.usage,'kind':name,'failed':True})
            save('usage.json',usage);unchanged();raise
        usage.append({**run,'kind':name});save('usage.json',usage)
        raw_value=value.model_dump() if hasattr(value,'model_dump') else value
        try:value=schema.model_validate(raw_value)
        except ValidationError as error:
            if schema is not EvidenceExtraction or name!='extract':raise
            details=error.errors(include_input=False,include_context=False,include_url=False)
            raise AIError('The extraction did not meet its structured source contract.','invalid_output',
                validation_errors=[{'loc':list(item['loc']),'type':item['type']} for item in details],
                **_invalid_extraction_details(schema,raw_value,details)) from None
        save(f'response-{request_count:02d}-{name}.json',value.model_dump());unchanged();return value
    def record_extraction(candidate,available,error=None):
        feedback=_source_extraction_feedback(error,candidate) if error is not None else []
        if error is not None and available:
            feedback=(_unaccepted_extraction_source_issues(candidate,index,documents)+feedback)[:100]
        if error is not None and not feedback:
            feedback=[{'loc':[],'type':getattr(error,'category','source_validation'),
                'message':'The extraction did not satisfy its source-validation gate; no candidate was accepted.'}]
        record={'attempt':source_extraction_attempts,'max_attempts':MAX_SOURCE_EXTRACTION_ATTEMPTS,
            'accepted':error is None,'category':getattr(error,'category','source_validation') if error is not None else 'valid',
            'validation_feedback':feedback,'previous_candidate_available':available,
            'candidate_sha256':content_hash(candidate) if available else None,
            'pinned_source_index_sha256':content_hash(index.model_dump()),'source_set_sha256':source_hash,
            'request_count':request_count,'max_requests':MAX_REQUESTS,'drawing_cycles_reserved':0}
        if error is not None and available:save(f'extraction-attempt-{source_extraction_attempts}-unaccepted.json',candidate)
        source_extraction_validation.append(record);save(f'extraction-validation-{source_extraction_attempts}.json',record)
        return feedback
    def result():
        try:state=ledger.snapshot() if ledger else None
        except (ValueError,OSError):state={'cycles_used':2,'max_cycles':2,'status':'invalid_ledger_fail_closed','can_start_3d':False,'cycle_count_known':False}
        receipt={'schema':'vwc-autonomous2d/1','version':1,'accepted':accepted,'status':('PASS_WITH_LIMITS' if qualifications else 'PASS') if accepted else ('REVISE' if model.drawings else 'NOT_REVIEWED'),
            'cycle_count':state['cycles_used'] if state else 0,'max_cycles':2,'request_count':request_count,'max_requests':MAX_REQUESTS,
            'view_count':len(model.drawings),'issues':list(dict.fromkeys(issues)),'three_d_held':True,'noCodexruntime':True,
            'source_set_sha256':source_hash,'source_index':index.model_dump() if index else None,
            'group_cycles':state,'artifacts':[{**item,'path':str(Path(item['path']).relative_to(output))} for item in artifacts],
            'reports':reports,'limitations':qualifications,'failed_stage':None if accepted else stage,'can_apply':accepted,
            'source_scope_checks':scope_checks,'source_scope_frame_updates':scope_frame_updates,'required_source_coverage':required_coverage}
        receipt.update(amendment_mode='reference_only' if reference_only_baseline else 'title_only' if title_only_baseline else 'saved_style' if baseline_extraction is not None else 'source_creation',
            native_body_reused=title_only_baseline or reference_only_baseline,reference_only_amendment=reference_only_baseline,
            fresh_final_export_checks_required=True)
        receipt.update(acceptance_scope='customer_reference_2d',customer_review_policy=dict(CUSTOMER_REVIEW_POLICY),reference_parameters=reference_parameters,
            required_reference_controls=required_controls,reference_audit=reference_audit,
            reference_validation_history=reference_history,reference_corrections=reference_corrections,source_parameters_unchanged=True,
            source_approval=False,fabrication_approval=False)
        receipt['reference_evidence_parameter_ids']=_reference_review_evidence(model.drawings,reference_parameters,
            {parameter.id for parameter in model.parameters})
        receipt.update(source_extraction_attempts=source_extraction_attempts,
            max_source_extraction_attempts=MAX_SOURCE_EXTRACTION_ATTEMPTS,
            source_extraction_validation=source_extraction_validation,
            source_extraction_accepted=source_extraction_accepted or baseline_extraction is not None)
        receipt.update(check_output_limit_retries=check_output_limit_retries,
            max_check_output_limit_retries=MAX_CHECK_OUTPUT_LIMIT_RETRIES,
            check_output_limit_retry_records=check_output_limit_retry_records,
            check_finding_reference_retries=check_finding_reference_retries)
        receipt.update(latest_complete_output_cycle=last_complete_output['cycle'] if last_complete_output else None,
            recovered_complete_output_cycle=recovered_complete_cycle,incomplete_output_cycle=incomplete_output_cycle)
        save('workflow-receipt.json',receipt);save('candidate-model.json',model.model_dump())
        return {'model':model,'summary':('Customer-reference 2D candidate passed with review notes. Review the result before Apply.' if qualifications else 'Customer-reference 2D candidate passed the current checks. Review before Apply.') if accepted else 'Customer-reference 2D candidate needs review. 3D remains on hold.',
            'warnings':list(dict.fromkeys([*model.warnings,*issues])),'usage':{'runs':usage,'input_tokens':sum(r.get('input_tokens',0) for r in usage),
                'output_tokens':sum(r.get('output_tokens',0) for r in usage)},'source_index':index.model_dump() if index else None,
            'workflow_receipt':receipt,'accepted':accepted,'reference_parameters':reference_parameters}
    try:
        if cycle_ledger_path is None:raise DrawingCycleError('A canonical project-level drawing-cycle ledger is required.')
        if Path(cycle_ledger_path).resolve().is_relative_to(output):raise DrawingCycleError('The cycle ledger must remain outside individual run output folders.')
        if len(instruction)>8000:raise _Hold('Keep the drawing instruction under8000 characters.')
        if screenshot and (len(screenshot)>12*1024*1024 or screenshot_type not in ('image/png','image/jpeg','image/webp')):raise _Hold('The annotated capture format/size is unsupported.')
        source_hash=_source_identity(documents);stored,ledger=_existing_scope(cycle_ledger_path,project_id,documents)
        legacy_fallback=ledger if ledger and ledger.is_legacy_source_fallback() else None
        if legacy_fallback:
            stored,ledger=None,None
        if ledger and not ledger.snapshot()['can_start_drawing']:raise DrawingCycleError('The complete 2D group has reached its two drawing cycles or is awaiting its current check. No new API request was sent.')
        if preserve_baseline:
            if current_model is None:raise _Hold('A styling amendment needs its complete saved 2D baseline.')
            index,baseline_extraction=_verified_baseline(model,documents)
            baseline_input_hash=content_hash(current_model.model_dump() if hasattr(current_model,'model_dump') else current_model)
            save('amendment-baseline.json',{'model_sha256':baseline_input_hash,'view_ids':[v.id for v in index.views],
                'drawing_hashes':{v.id:drawing_hash(v) for v in model.drawings},'facts_reused_without_reextraction':True})
            for view in model.drawings:
                baseline_frames[view.id]={'document_id':view.document_id,'page':view.page,'region':list(view.region)}
                path=output/f'baseline-{_key(view.id)}.pdf';path.write_bytes(render_pdf(view));artifact_pins[str(path)]=_sha(path)
                baseline_images[view.id]=_saved_pdf_png(path)
                baseline_members[view.id]={alias for p in view.primitives for alias in [p.id,p.source_id,*p.source_ids]}
        emit('reading_sources',10);source_inputs=gateway._document_inputs(documents)
        capture=[_text({'authority':'User annotated intent only; original source observations remain authoritative','selection':selection}),
            {'type':'input_image','image_url':f'data:{screenshot_type};base64,'+base64.b64encode(screenshot).decode(),'detail':'high'}] if screenshot else []
        atlas=_page_atlas(documents,output,control);save('source-page-atlas.json',atlas)
        for page in atlas:artifact_pins[page['image_path']]=page['image_sha256']
        atlas_content=[_text({'page_atlas':[{k:v for k,v in p.items() if k!='image_path'} for p in atlas]})]
        atlas_content += [block for p in atlas for block in (_text({'original_page':p['page'],'document_id':p['document_id']}),_image(Path(p['image_path']).read_bytes()))]
        if stored:
            index=SourceIndex(project_name=model.name,views=stored,warnings=[])
            save('source-map-reuse.json',{'reason':'Persistent complete source-group identity reused; cycle history not reset.',
                'group_key':ledger.group_key,'cycles_used':ledger.snapshot()['cycles_used']})
        elif baseline_extraction is None:
            if initial_index is None:
                index=call(AutonomousSourceIndex,'index',[_text({'instruction':instruction,'selection':selection}),*source_inputs,*atlas_content,*capture])
            else:
                initial_data=initial_index.model_dump() if hasattr(initial_index,'model_dump') else initial_index
                index=AutonomousSourceIndex.model_validate(initial_data)
        pinned_frames={view.id:(view.document_id,view.page,view.region) for view in stored or []}
        gateway._check_index(index,documents)
        if not index.views or len(index.views)>MAX_VIEWS or any(v.kind not in ('plan','elevation') or v.region is None or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,79}',v.id) for v in index.views):
            raise _Hold('The source map needs complete, unambiguous plan and elevation regions, with at most 12 views.')
        save('source-index-initial.json',index.model_dump())
        atlas_manifest=[{k:v for k,v in page.items() if k!='image_path'} for page in atlas]
        for scope_round in range(MAX_SCOPE_CHECKS):
            emit('checking_source_scope',16+scope_round*4)
            mapped_crops=_source_crops(documents,index.views);scope_content=[];crop_manifest=[]
            for view in index.views:
                path=output/f'scope-{scope_round}-{_key(view.id)}.png';path.write_bytes(mapped_crops[view.id]);artifact_pins[str(path)]=_sha(path)
                item={'view_id':view.id,'document_id':view.document_id,'page':view.page,'region':view.region,'sha256':_sha(path)}
                crop_manifest.append(item);scope_content.extend([_text({'ACTUAL_ORIGINAL_SCOPE_CROP':item}),_image(mapped_crops[view.id])])
            binding=SourceScopeBindings(project_id=project_id,run_id=run_id,source_set_sha256=source_hash,
                candidate_index_sha256=content_hash(index.model_dump()),atlas_sha256=content_hash(atlas_manifest),crops_sha256=content_hash(crop_manifest))
            scope=call(SourceScopeReview,'scope',[_text({'instruction':instruction,'selection':selection,'bindings':binding.model_dump(),
                'source_evidence_mode':'Verified original full-page atlas and exact original-source crop rasters plus native word positions; full original PDF supplied to initial mapping only.',
                'candidate_views':[v.model_dump(exclude={'correspondence_notes'}) for v in index.views],
                'actual_crop_manifest':crop_manifest,'fresh_scope_check':scope_round>0,
                'required_source_coverage':required_coverage,'host_validation_feedback':scope_feedback,
                'scope_purpose':'Verify source coverage, not cosmetic output cleanup. Retain established owned operations/annotations despite unavoidable neighboring context.',
                'scope_check_number':scope_round+1,'max_scope_checks':MAX_SCOPE_CHECKS,
                'source_frames_pinned':bool(pinned_frames),
                'saved_checked_styling_baseline':baseline_extraction is not None,
                'saved_checked_reference_baseline':baseline_extraction is not None and any(v.reference_annotations for v in model.drawings),
                'frame_updates_used':scope_frame_updates,'max_frame_updates':0 if pinned_frames else 2}),*atlas_content,*scope_content,*capture])
            scope_checks+=1
            save(f'source-scope-review-{scope_round}.json',scope.model_dump())
            if scope.bindings!=binding:
                # A model can mistype a hash while inspecting the correct images.
                # Never repair that response locally or apply any of its frames:
                # spend a remaining existing scope check on the unchanged inputs.
                mismatched=[name for name,value in binding.model_dump().items()
                    if scope.bindings.model_dump().get(name)!=value]
                scope_feedback=[{'code':'source_scope_binding_mismatch','binding_fields':mismatched,
                    'reason':'The previous response was rejected. Inspect the supplied unchanged source images again and echo the current provided bindings exactly; none of the rejected frame or coverage decisions was applied.'}]
                save(f'source-scope-summary-{scope_round}.json',{'qualified':False,'verdict':scope.verdict,
                    'drawing_cycles_reserved':0,'proposed_frame_applied':False,
                    'retained_index_sha256':content_hash(index.model_dump()),
                    'required_source_coverage':required_coverage,'host_validation_feedback':scope_feedback})
                if scope_round==MAX_SCOPE_CHECKS-1:
                    raise _Hold('The source-scope response repeatedly mismatched its source identity. No source frame or drawing was applied.')
                emit('refining_source_scope',18+scope_round*4);continue
            if baseline_extraction is not None and scope.verdict!='HOLD':
                for proposal in scope.views:
                    original=baseline_frames.get(proposal.view_id)
                    if original is not None and proposal.action!='hold':
                        box=proposal.region;prior=original['region']
                        if scope.reference_only and (proposal.document_id!=original['document_id'] or proposal.page!=original['page'] or box!=prior):
                            raise _Hold('A reference-only amendment cannot change any original source document, page or frame.')
                        if proposal.document_id!=original['document_id'] or proposal.page!=original['page'] or box is None or not (
                            prior[0]<=box[0]<=box[2]<=prior[2] and prior[1]<=box[1]<=box[3]<=prior[3]):
                            save(f'source-scope-summary-{scope_round}.json',{'qualified':False,'proposed_frame_applied':False,
                                'reason':'Styling scope would introduce source content outside the checked baseline; source analysis is required.',
                                'drawing_cycles_reserved':0})
                            raise _Hold('This styling amendment would add a new source area or page. A new source analysis is required; existing exclusions cannot classify unseen source content.')
            try:
                revised,qualified=validate_source_scope(scope,binding,index,documents,required_coverage)
                changed_frames=[view.id for view in revised.views if view.id in pinned_frames
                    and (view.document_id,view.page,view.region)!=pinned_frames[view.id]]
                if changed_frames:
                    raise SourceScopeCoverageError([{'code':'source_frames_pinned','view_ids':changed_frames,
                        'reason':'This project already started drawing these exact source frames. Verify the unchanged original crops. Accept only if they contain the complete requested subject, or hold if different frames are needed.'}])
            except SourceScopeCoverageError as error:
                scope_feedback=error.feedback
                save(f'source-scope-summary-{scope_round}.json',{'qualified':False,'verdict':scope.verdict,'drawing_cycles_reserved':0,
                    'proposed_frame_applied':False,'retained_index_sha256':content_hash(index.model_dump()),
                    'required_source_coverage':required_coverage,'host_validation_feedback':scope_feedback})
                if scope_round==MAX_SCOPE_CHECKS-1:
                    if pinned_frames and any(item['code']=='source_frames_pinned' for item in scope_feedback):
                        raise _Hold('This project’s existing source frames could not be reverified. Its drawing-cycle history was preserved.') from error
                    raise _Hold('The source crop would lose required room-owned features. No unsafe frame change or drawing was applied.') from error
                emit('refining_source_scope',18+scope_round*4);continue
            scope_feedback=[]
            if scope.verdict!='HOLD':required_coverage=source_scope_coverage(scope,required_coverage)
            save('source-required-coverage.json',required_coverage)
            save(f'source-scope-summary-{scope_round}.json',{'qualified':qualified,'verdict':scope.verdict,'drawing_cycles_reserved':0,
                'old_index_sha256':content_hash(index.model_dump()),'proposed_index_sha256':content_hash(revised.model_dump()),
                'proposed_frame_applied':qualified or (scope.verdict=='REFINE' and scope_round<MAX_SCOPE_CHECKS-1),
                'required_source_coverage':required_coverage})
            if qualified:
                index=revised;title_only_baseline=bool(baseline_extraction is not None and scope.title_only)
                reference_only_baseline=bool(baseline_extraction is not None and scope.reference_only)
                if title_only_baseline and any(v.region!=baseline_frames[v.id]['region'] for v in index.views):
                    raise _Hold('A title-only amendment cannot change any source frame or native drawing content.')
                break
            if scope.verdict!='REFINE' or scope_round==MAX_SCOPE_CHECKS-1:raise _Hold('The requested room or object crop is not yet verified. No fact extraction or drawing was started.')
            index=revised;scope_frame_updates+=1;emit('refining_source_scope',18+scope_round*4)
        else:raise _Hold('Source view scope was not independently checked.')
        candidate_ledger=DrawingCycleBudget(cycle_ledger_path,project_id=project_id,documents=documents,required_views=index.views)
        if not legacy_fallback:
            try:candidate_ledger.snapshot()
            except DrawingCycleError as error:raise _Hold('The verified source frame differs from this project’s already bound group. Existing cycle history was preserved, not reset.') from error
            ledger=candidate_ledger
        save('source-index.json',index.model_dump());emit('extracting_source_facts',30)
        source_crops=_source_crops(documents,index.views);crop_content=[]
        for view in index.views:
            path=output/f'source-{_key(view.id)}.png';path.write_bytes(source_crops[view.id]);artifact_pins[str(path)]=_sha(path)
            crop_content += [_text({'SOURCE_VIEW':view.id,'document_id':view.document_id,'page':view.page,'region':view.region}),_image(source_crops[view.id])]
        scoped_words=[]
        for view in index.views:
            page=next(p for p in atlas if p['document_id']==view.document_id and p['page']==view.page)
            scoped_words.append({'view_id':view.id,'document_id':view.document_id,'page':view.page,'region':view.region,
                'words':[w for w in page['words'] if w['region'][0]<view.region[2] and view.region[0]<w['region'][2] and w['region'][1]<view.region[3] and view.region[1]<w['region'][3]]})
        save('verified-source-scope.json',{'source_set_sha256':source_hash,'source_index':index.model_dump(),
            'evidence_mode':'Original-PDF derivatives: qualified crop rasters and region-filtered native words; no fabricated/cropped PDF file.',
            'scoped_native_words':scoped_words})
        if baseline_extraction is None:
            previous_unaccepted_extraction=None;extraction_validation_feedback=[]
            for _ in range(MAX_SOURCE_EXTRACTION_ATTEMPTS):
                before_attempts=source_extraction_attempts;candidate=None
                try:
                    candidate=call(EvidenceExtraction,'extract',[_text({'instruction':instruction,'selection':selection,
                        'pinned_source_index':index.model_dump(),'source_set_sha256':source_hash,'original_scoped_native_words':scoped_words,
                        'extraction_attempt':source_extraction_attempts+1,'max_extraction_attempts':MAX_SOURCE_EXTRACTION_ATTEMPTS,
                        'extraction_validation_feedback':extraction_validation_feedback,
                        'previous_unaccepted_extraction':previous_unaccepted_extraction,
                        'correction_authority':'A prior candidate is unaccepted model output, not source truth or a host correction. Produce a fresh complete extraction from the same original evidence. The host never reparents owners or changes source facts.'}),
                        *crop_content,*capture])
                    if candidate.source_index.model_dump()!=index.model_dump():
                        raise _Hold('Source extraction changed the automatically mapped source scope.')
                    # Foreign evidence and source-identity errors are not schema
                    # repair requests and must stop before another API call.
                    evidence_model(candidate,documents)
                except Exception as error:
                    if error is control_error or 'cancel' in type(error).__name__.lower() or 'pause' in type(error).__name__.lower():raise
                    raw=getattr(error,'invalid_candidate',None)
                    available=bool(getattr(error,'invalid_candidate_available',False))
                    if candidate is not None:raw=candidate.model_dump();available=True
                    if source_extraction_attempts>before_attempts:
                        extraction_validation_feedback=record_extraction(raw,available,error)
                    # Retry only a completed, bounded structured extraction
                    # rejected by its schema/semantic validation. No raw text,
                    # network ambiguity, refusal or source/index drift retries.
                    if (getattr(error,'category',None)!='invalid_output' or not available or not isinstance(raw,dict)
                            or _unaccepted_extraction_source_issues(raw,index,documents)
                            or source_extraction_attempts>=MAX_SOURCE_EXTRACTION_ATTEMPTS):raise
                    previous_unaccepted_extraction=copy.deepcopy(raw)
                    emit('extracting_source_facts',31)
                    continue
                extraction=candidate;source_extraction_accepted=True
                record_extraction(candidate.model_dump(),True)
                break
            else:raise _Hold('Source extraction did not pass its two bounded validation attempts.')
        else:
            extraction=baseline_extraction.model_copy(deep=True);extraction.source_index=index.model_copy(deep=True)
            by_id={v.id:v for v in index.views}
            for view in model.views:
                source=by_id[view.id];view.document_id=source.document_id;view.page=source.page;view.region=list(source.region);view.label=source.label
        if extraction.source_index.model_dump()!=index.model_dump():raise _Hold('Source extraction changed the automatically mapped source scope.')
        required_controls=required_reference_controls(extraction)
        if reference_only_baseline:
            prior_valid_reference_plan,prior_valid_reference_parameters=_saved_reference_guidance(model.drawings,required_controls)
            prior_reference_proposal=copy.deepcopy(prior_valid_reference_plan)
            save('reference-amendment-guidance.json',{'source':'Complete verified saved annotations; guidance only, no imported acceptance',
                'prior_valid_reference_plan':prior_valid_reference_plan,'prior_valid_reference_parameters':prior_valid_reference_parameters})
        save('required-reference-controls.json',required_controls)
        if baseline_extraction is None:model=evidence_model(extraction,documents)
        model.requires_source_drawings=True;model.warnings=list(dict.fromkeys([*index.warnings,*extraction.warnings]))
        save('source-evidence.json',extraction.model_dump());emit('extracting_native_vectors',35)
        inventory=build_inventory(documents,index)
        if len(inventory['views'])!=len(index.views) or {v['id'] for v in inventory['views']}!={v.id for v in index.views}:raise _Hold('Required views lack supported original native geometry.')
        base=DrawingPlan(views=[DrawingViewPlan(view_id=v.id,default_owner_id=model.root.id) for v in index.views])
        if baseline_extraction is not None:
            originals={v.id:v for v in model.drawings}
            for source in inventory['views']:
                decision=next(v for v in base.views if v.view_id==source['id'])
                members=baseline_members[source['id']]
                omitted=[p['id'] for p in source['primitives'] if not ({p['id'],p['source_id'],*p.get('source_ids',[])}&members)]
                for offset in range(0,len(omitted),1000):decision.rules.append(DrawingRule(primitive_ids=omitted[offset:offset+1000],include=False))
                original=originals[source['id']];decision.edit_guards=copy.deepcopy(original.edit_guards)
                aliases={}
                for native in source['primitives']:
                    for alias in {native['id'],native['source_id']}:aliases.setdefault(alias,set()).add(native['id'])
                roles={}
                for primitive in original.primitives:
                    matching=sorted({ident for alias in primitive.source_ids or [primitive.source_id] for ident in aliases.get(alias,())})
                    roles.setdefault((primitive.owner_id,primitive.role),set()).update(matching)
                for (owner,role),ids in roles.items():
                    ordered=sorted(ids)
                    for offset in range(0,len(ordered),1000):decision.rules.append(DrawingRule(primitive_ids=ordered[offset:offset+1000],owner_id=owner,role=role))
            save('amendment-baseline-plan.json',base.model_dump())
        save('native-inventory.json',inventory)
        emit('grouping_native_sources',38)
        from .automatic_native_groups import refine_catalog
        catalog_parts,catalogs=([],[]) if title_only_baseline or reference_only_baseline else _drawing_catalogs(inventory)
        protected={v['id']:[p['id'] for p in v['primitives'] if p['kind']=='text' or p.get('fill')=='white' or p.get('role') in ('dimension','opening','material','view_reference')] for v in inventory['views']}
        owners=_owner_ids(model);params={p.id for p in model.parameters};last_review=[];held_ids=[]
        previous_candidate_images={};prior_group_questions=[]
        for cycle in range(2):
            control();groups=[] if title_only_baseline or reference_only_baseline else [g for c in catalogs for g in c['groups']]
            needed=(len(groups)+BATCH_GROUPS-1)//BATCH_GROUPS+(len(index.views)+1)//2+int(bool(required_controls) and not title_only_baseline)
            if request_count+needed>MAX_REQUESTS:raise _Hold('Remaining bounded requests cannot complete another whole-group classification and fresh check.')
            if legacy_fallback:
                if not legacy_fallback.retire_legacy_source_fallback():
                    raise _Hold('The saved drawing-cycle record changed. Reload the project before retrying.')
                legacy_fallback=None
                ledger=candidate_ledger
            if not ledger.snapshot()['can_start_drawing']:raise _Hold('The complete2D group has reached its TWO-cycle limit; quality remains held.')
            lease=ledger.reserve('create_2d' if ledger.snapshot()['cycles_used']==0 else 'repair_2d',{'run_id':run_id,'instruction_sha256':hashlib.sha256(instruction.encode()).hexdigest()})
            save(f'cycle-{lease["number"]}-catalogs.json',catalogs)
            decisions=[];held_ids=[]
            for offset in range(0,len(groups),BATCH_GROUPS):
                emit('classifying_source_groups',(40 if cycle==0 else 70)+int(13*offset/max(1,len(groups))))
                selected=groups[offset:offset+BATCH_GROUPS];catalog={'source_sha256':catalogs[0]['source_sha256'],'groups':selected}
                # Neutral metadata is validated separately per original source.
                metadata=[]
                for c in catalogs:
                    own=[g for g in selected if g in c['groups']]
                    if own:metadata.extend(neutral_group_metadata({**c,'groups':own})['groups'])
                source_lookup={v['id']:{p['id']:p for p in v['primitives']} for v in inventory['views']}
                group_lookup={g['group_id']:g for g in selected}
                for item in metadata:
                    group=group_lookup[item['group_id']];records=[source_lookup[group['view_id']][i] for i in group['native_ids']]
                    item['kind_counts']=dict(Counter(p['kind'] for p in records))
                    item['native_style_ids']=sorted({p.get('source_style_id','') for p in records})[:8]
                    item['protected_native_count']=len(set(group['native_ids'])&set(protected[group['view_id']]))
                    item['all_strokeless_white_fill']=all(p['kind']=='path' and p.get('fill')=='white' and not p.get('stroke') for p in records)
                    item['paint_states']=list({json.dumps({key:p.get(key) for key in ('stroke','stroke_color','fill','fill_rgb','stroke_width','dash')},sort_keys=True):
                        {key:p.get(key) for key in ('stroke','stroke_color','fill','fill_rgb','stroke_width','dash')} for p in records}.values())[:8]
                    item['clip_depths']=sorted({len(p.get('clips',[])) for p in records})
                    item['source_text_snippet']=' | '.join(p.get('text','') for p in records if p['kind']=='text')[:200]
                    item['prior_group_questions']=[{'previous_group_id':question['group_id'],'reason':question['reason']}
                        for question in prior_group_questions if question['view_id']==group['view_id'] and question['members'].intersection(group['native_ids'])]
                    if baseline_extraction is not None:item['saved_baseline_retained_native_count']=sum(bool({p['id'],p['source_id'],*p.get('source_ids',[])}&baseline_members.get(group['view_id'],set())) for p in records)
                sheets=_contact_sheets(inventory,selected,output,f'cycle{lease["number"]}-groups-{offset}',control,source_images=source_crops)
                for path in sheets:artifact_pins[str(path)]=_sha(path)
                response=call(AutonomousGroupSelection,'select',[_text({'instruction':instruction,'selection':selection,'requested_group_ids':[g['group_id'] for g in selected],
                    'groups':metadata,'source_owner_hierarchy':[o.model_dump() for o in extraction.owners],
                    'source_set_sha256':source_hash,'source_evidence_mode':'Verified original-source crop rasters and mechanical native group facts; no repeated full-PDF upload.',
                    'original_scoped_native_words':[v for v in scoped_words if v['view_id'] in {g['view_id'] for g in selected}],
                    'required_source_coverage':{key:value for key,value in required_coverage.items() if key in {g['view_id'] for g in selected}},
                    'context_overlay_scope':'Diagnostic selected-native ink positions in red on original source context; not a cleaned output or semantic answer. Original unmodified SOURCE_VIEW crops remain authoritative.',
                    'saved_baseline_style_amendment':baseline_extraction is not None,
                    'prior_fresh_reviews':last_review,'cycle':lease['number'],'protected_policy':'All source text, source white masks and previously semantic dimension/opening/material marks are protected.'}),
                    *[block for v in index.views if v.id in {g['view_id'] for g in selected} for block in
                        (_text({'SOURCE_VIEW':v.id,'document_id':v.document_id,'page':v.page,'region':v.region}),_image(source_crops[v.id]))],
                    *[block for ident,raw in previous_candidate_images.items() if ident in {g['view_id'] for g in selected} for block in
                        (_text({'ACTUAL_PREVIOUS_CANDIDATE_VIEW':ident,'authority':'Actual saved-PDF raster from the preceding drawing cycle; compare with original source and consolidated fresh findings, never treat it as source truth.'}),_image(raw))],
                    *[block for ident,image in baseline_images.items() if ident in {g['view_id'] for g in selected} for block in
                        (_text({'SAVED_ACCEPTED_BASELINE_VIEW':ident,'authority':'Existing saved style/visibility baseline; original source observations are unchanged.'}),_image(image))],
                    *capture,*[block for p in sheets for block in (_text({'isolated_group_contact_sheet':p.name}),_image(p.read_bytes()))]])
                if len(response.groups)!=len(selected) or {g.group_id for g in response.groups}!={g['group_id'] for g in selected}:raise _Hold('Group classifier omitted,duplicated or added a requested group.')
                if any(g.owner_id is not None and g.owner_id not in owners for g in response.groups):raise _Hold('Group classifier invented a semantic owner.')
                if any(g.action=='retain' and g.role=='texture' for g in response.groups):raise _Hold('Retain cannot hide source ink through a texture role; omission must pass protected-ID validation.')
                decisions.extend(response.groups)
            save(f'cycle-{lease["number"]}-selections.json',[decision.model_dump() for decision in decisions])
            plan=base.model_copy(deep=True)
            for c in ([] if title_only_baseline or reference_only_baseline else catalogs):
                ids={g['group_id'] for g in c['groups']};plain=[]
                for d in decisions:
                    if d.group_id not in ids:continue
                    raw=d.model_dump(exclude={'owner_id','role'})
                    if d.action=='review' or d.category=='uncertain':
                        held_ids.append(d.group_id);raw.update(action='retain',category='physical_boundary',reason='Conservative original-ink retention; unresolved classifier decision is disclosed to the fresh checker.')
                    plain.append(raw)
                plan=apply_group_selection(inventory,plan,c,NativeGroupSelection.model_validate({'groups':plain}),protected)
            by_group={g['group_id']:g for g in groups};by_plan={v.view_id:v for v in plan.views}
            prior_group_questions=[{'group_id':d.group_id,'view_id':d.view_id,'reason':d.reason,'members':set(by_group[d.group_id]['native_ids'])}
                for d in decisions if d.action=='review' or d.category=='uncertain']
            for d in decisions:
                if d.action!='omit' and d.role is None:
                    # RETAIN is a visibility decision. A native filled surface
                    # may have a neutral texture default; that default must not
                    # silently hide ink the API expressly retained. Keep every
                    # other original role, owner, RGB and path unchanged.
                    visible_ids=[ident for ident in by_group[d.group_id]['native_ids']
                        if source_lookup[d.view_id][ident].get('role')=='texture']
                    for offset in range(0,len(visible_ids),1000):
                        by_plan[d.view_id].rules.append(DrawingRule(primitive_ids=visible_ids[offset:offset+1000],role='geometry'))
                if d.action=='retain' and d.category!='uncertain' and (d.owner_id is not None or d.role is not None):
                    by_plan[d.view_id].rules.append(DrawingRule(primitive_ids=by_group[d.group_id]['native_ids'],owner_id=d.owner_id,role=d.role))
            if title_only_baseline or reference_only_baseline:
                drawings=[originals[v.id].model_copy(deep=True,update={'label':v.label}) for v in index.views]
                if reference_only_baseline:
                    for view in drawings:view.reference_annotations=[]
                save(f'cycle-{lease["number"]}-'+('reference-amendment.json' if reference_only_baseline else 'title-amendment.json'),{'mode':'reference_only' if reference_only_baseline else 'title_only',
                    'native_primitives_unchanged':all(v.primitives==originals[v.id].primitives for v in drawings),
                    'original_view_ids':[v.id for v in drawings],'source_frames_unchanged':True,
                    'old_reference_annotations_cleared_before_base_render':reference_only_baseline,
                    'fresh_reference_resolution_required':reference_only_baseline,'fresh_actual_export_checks_required':True})
            else:drawings=compile_drawings(inventory,plan)
            fingerprint=semantic_fingerprint(model)
            for view in drawings:
                view.semantic_snapshot=fingerprint;view.review_status='pending';view.review_hash=None
                view.annotation_margin=originals[view.id].annotation_margin if baseline_extraction is not None else 24.
                view.review_notes=list(originals[view.id].review_notes) if title_only_baseline or reference_only_baseline else []
            model.drawings=drawings
            if len(drawings)!=len(index.views) or any(not any(_object_geometry(p) for p in v.primitives) for v in drawings):
                raise _Hold('A required native view has no useful visible object geometry; it cannot be accepted as a blank sheet.')
            save(f'cycle-{lease["number"]}-plan.json',plan.model_dump())
            reference_failures=[];reference_parameters={};reference_audit={}
            if title_only_baseline:
                # Reusing an accepted annotation is a styling amendment, not a
                # new estimate. Preserve the exact saved resolved records.
                existing=[ref for view in drawings for ref in view.reference_annotations]
                for ref in existing:
                    reference_parameters[ref.control_id]=dict(value_mm=ref.value_mm,label=ref.label,method=ref.method,
                        confidence=ref.confidence,owner_id=ref.owner_id,estimate_id=ref.estimate_id,
                        provenance_digest=ref.provenance_digest)
                complete=set(reference_parameters)=={item['control_id'] for item in required_controls}
                reference_audit={'schema':'vwc-customer-reference-audit/1','mode':'exact_checked_baseline_annotations_preserved',
                    'coverage_complete':complete,'required_control_ids':[item['control_id'] for item in required_controls],
                    'resolved_control_ids':sorted(reference_parameters),'source_facts_preserved':True,
                    'reference_plan_requested':False,'fresh_final_export_checks_required':True}
                if not complete:reference_failures.append('Saved baseline does not contain every required original reference control.')
            elif required_controls:
                emit('resolving_customer_references',53 if cycle==0 else 83)
                anchors=build_anchor_catalog(inventory,drawings,extraction=extraction);save(f'cycle-{lease["number"]}-reference-anchors.json',anchors)
                compact_anchors={'schema':anchors['schema'],'digest':anchors['digest'],
                    'selection_policy':anchors['selection_policy'],'views':[
                        {**{key:view[key] for key in ('view_id','document_id','page','source_sha256','width','height','region','candidate_count','omitted_count')},
                         **({'required_owner_pair_coverage':view['required_owner_pair_coverage']} if 'required_owner_pair_coverage' in view else {}),
                         'target_anchor_eligibility':view['target_anchor_eligibility'],
                         'anchors':[{key:anchor[key] for key in ('id','point','normalized_point','owner_ids','source_id','command_index')}
                            for anchor in view['anchors']]} for view in anchors['views']]}
                if 'required_control_context_sha256' in anchors:compact_anchors['required_control_context_sha256']=anchors['required_control_context_sha256']
                base_rasters={};base_manifest=[]
                for view in drawings:
                    control();path=output/f'cycle-{lease["number"]}-reference-base-{_key(view.id)}.pdf'
                    path.write_bytes(render_pdf(view));artifact_pins[str(path)]=_sha(path)
                    raw=_saved_pdf_png(path);png=path.with_suffix('.png');png.write_bytes(raw);artifact_pins[str(png)]=_sha(png)
                    base_rasters[view.id]=raw;base_manifest.append({'view_id':view.id,'pdf_sha256':_sha(path),
                        'raster_sha256':_sha(png),'raster_reads_saved_pdf_bytes':True})
                reference_images=[*crop_content,*capture,*[block for ident,raw in base_rasters.items() for block in
                    (_text({'ACTUAL_BASE_CANDIDATE_VIEW':ident,'source':'Rasterized saved base candidate PDF before new reference annotations'}),_image(raw))]]
                review_requests=(len(drawings)+1)//2
                for attempt in range(2):
                    try:
                        proposal=call(ReferencePlan,'references',[_text({'instruction':instruction,'selection':selection,
                        'cycle':lease['number'],'source_set_sha256':source_hash,'extracted_facts':extraction.model_dump(),
                        'required_reference_controls':required_controls,'host_anchor_catalog':compact_anchors,
                        'actual_base_render_manifest':base_manifest,'original_scoped_native_words':scoped_words,
                        'prior_fresh_reviews':last_review,'prior_reference_validation':reference_feedback,
                        'host_reference_correction':attempt==1,
                        'prior_valid_reference_plan':prior_valid_reference_plan,
                        'prior_valid_reference_parameters':prior_valid_reference_parameters,
                        'prior_reference_proposal':prior_reference_proposal,
                        'within_operation_reference_stability':'During this operation, preserve prior valid reference values and structural anchors unaffected by fresh reference-specific findings. Prior proposals are guidance only: every returned plan must fully host-resolve and receive fresh final checks. A later explicit user reference amendment remains authorized.',
                        'authority':'Explicit user-authorized practical dimensional references only; never amend original parameters, owners, native geometry or printed observations.'}),*reference_images])
                        prior_reference_proposal=proposal.model_dump()
                        resolved=resolve_reference_plan(proposal,extraction=extraction,documents=documents,inventory=inventory,
                            drawings=drawings,anchor_catalog=anchors)
                        reference_parameters=resolved['reference_parameters'];reference_audit=resolved['audit']
                        prior_valid_reference_plan=proposal.model_dump();prior_valid_reference_parameters=copy.deepcopy(reference_parameters)
                        for view in drawings:view.reference_annotations=resolved['annotations_by_view'][view.id]
                        reference_feedback=[]
                        break
                    except Exception as error:
                        if error is control_error or 'cancel' in type(error).__name__.lower() or 'pause' in type(error).__name__.lower():raise
                        if not isinstance(error,ValueError) and getattr(error,'category',None)!='invalid_output':raise
                        message=str(error)[:1600] if isinstance(error,ValueError) and not hasattr(error,'errors') else 'Reference proposal did not satisfy the required typed coverage or arithmetic contract.'
                        reference_feedback=copy.deepcopy(error.issues[:200]) if isinstance(error,ReferenceValidationError) and error.issues else [
                            {'code':'invalid_customer_reference_plan','message':message,'required_control_ids':[item['control_id'] for item in required_controls]}]
                        # Correct a completed proposal with concrete binding feedback
                        # before consuming a full drawing cycle. Preserve budget for
                        # fresh checks and another complete cycle if it fits now.
                        remaining=MAX_REQUESTS-request_count-review_requests
                        reserve_next_cycle=needed if cycle==0 and remaining>=needed else 0
                        if attempt==0 and baseline_extraction is None and remaining>reserve_next_cycle and isinstance(error,ReferenceValidationError) and any(
                                issue['phase']=='binding_anchors_evidence' for issue in error.issues):
                            record={'cycle':lease['number'],'failed_request_count':request_count,
                                'reserved_review_requests':review_requests,'reserved_next_cycle_requests':reserve_next_cycle,
                                'validation_issues':reference_feedback}
                            reference_corrections.append(record)
                            save(f'cycle-{lease["number"]}-reference-correction.json',record)
                            continue
                        reference_failures=['Customer reference validation failed: '+message]
                        reference_audit={'schema':'vwc-customer-reference-audit/1','coverage_complete':False,
                            'required_control_ids':[item['control_id'] for item in required_controls],'resolved_control_ids':[],
                            'validation_issues':reference_feedback,'validation_issues_truncated':isinstance(error,ReferenceValidationError) and len(error.issues)>200,
                            'source_facts_preserved':True}
                        break
            else:
                reference_audit={'schema':'vwc-customer-reference-audit/1','coverage_complete':True,
                    'required_control_ids':[],'resolved_control_ids':[],'source_facts_preserved':True,
                    'reference_plan_requested':False}
            reference_history.append({'cycle':lease['number'],**reference_audit})
            save(f'cycle-{lease["number"]}-reference-audit.json',reference_audit)
            save(f'cycle-{lease["number"]}-reference-parameters.json',reference_parameters)
            emit('rendering_source_drawings',54 if cycle==0 else 84)
            rendered=[];format_proofs=[]
            for view in drawings:
                control();pdf=output/f'cycle-{lease["number"]}-{_key(view.id)}.pdf';pdf.write_bytes(render_pdf(view))
                png=pdf.with_suffix('.png');png.write_bytes(_saved_pdf_png(pdf))
                svg=pdf.with_suffix('.svg');svg.write_text(render_svg(view),encoding='utf-8')
                for path in (pdf,png,svg):
                    item={'artifact_id':path.name,'view_id':view.id,'path':str(path),'sha256':_sha(path)}
                    rendered.append(item);artifacts.append(item);artifact_pins[str(path)]=item['sha256']
                format_proofs.append({'view_id':view.id,'pdf_raster_reads_saved_bytes':True,'pdf_sha256':_sha(pdf),'raster_sha256':_sha(png),
                    'svg':_svg_proof(svg,view),'native_count':len(view.primitives),'source_region':view.region})
                format_proofs[-1].update(annotation_margin_points=view.annotation_margin,
                    source_review_notes=view.review_notes,
                    reference_graphics=reference_graphics(view),reference_annotation_count=len(view.reference_annotations),
                    annotation_authority='Original printed dimensions and source geometry are unchanged. Separate complete blue customer-reference dimensions use pale yellow behind numeric values only. Source uncertainties and derivation details remain in the separate audit, with no TBC/debug panel on customer sheets.')
            save(f'cycle-{lease["number"]}-working-result.json',{
                'schema':'formtopart-working-drawings/1','kind':'2d','cycle':lease['number'],'checked':False,
                'views':[{'view_id':view.id,'label':view.label} for view in drawings],
                'artifacts':[{**item,'path':Path(item['path']).name} for item in rendered
                    if item['path'].endswith(('.pdf','.png'))]})
            last_complete_output={'cycle':lease['number'],'model':model.model_copy(deep=True),
                'reference_parameters':copy.deepcopy(reference_parameters),'reference_audit':copy.deepcopy(reference_audit)}
            previous_candidate_images={item['view_id']:Path(item['path']).read_bytes() for item in rendered if item['path'].endswith('.png')}
            candidate_hash=content_hash({'inventory':inventory_identity(inventory),'plan':plan.model_dump(),'drawings':[drawing_hash(v) for v in drawings]})
            local_quality=assess_drawings(drawings,expected_views=[v.id for v in index.views])
            local_failures=[issue for record in local_quality['views'] if record['status'] in ('incomplete','stale') for issue in record['issues']]+reference_failures
            ledger.mark_candidate(lease['lease_id'],candidate_hash);candidate_before=content_hash(model.model_dump());last_review=[];passed=not local_failures
            source_views={v.id:v for v in index.views};decision_reasons={d.group_id:d.reason for d in decisions}
            held_group_context=[]
            for ident in held_ids:
                group=by_group[ident];source=source_views[group['view_id']]
                held_group_context.append({'group_id':ident,'view_id':group['view_id'],
                    'native_members_sha256':content_hash(sorted(group['native_ids'])),'native_count':len(group['native_ids']),
                    'bbox':group['bbox'],'document_id':source.document_id,'page':source.page,'region':source.region,
                    'classifier_reason':decision_reasons[ident],
                    'actual_artifact_ids':[a['artifact_id'] for a in rendered if a['view_id']==group['view_id'] and a['artifact_id'].endswith(('.pdf','.png'))]})
            resolved_held_ids=set();group_resolution_issues=[]
            overview=_checker_overview(rendered);original_cross_view=_original_cross_view_evidence(extraction)
            reference_review_evidence=_reference_review_evidence(drawings,reference_parameters,params)
            save(f'cycle-{lease["number"]}-reference-review-evidence.json',reference_review_evidence)
            for offset in range(0,len(drawings),2):
                requested=[v.id for v in drawings[offset:offset+2]];items=[a for a in rendered if a['view_id'] in requested]
                required_resolutions=[item for item in held_group_context if item['view_id'] in requested]
                manifest=[{k:v for k,v in a.items() if k!='path'} for a in items]
                full_manifest=[{k:v for k,v in a.items() if k!='path'} for a in rendered]
                bindings=ReviewBindings(project_id=project_id,run_id=run_id,source_set_sha256=source_hash,candidate_sha256=candidate_hash,
                    artifacts_sha256=content_hash(full_manifest),profile_sha256=content_hash({'prompts':prompt_pins,'customer_review_policy':CUSTOMER_REVIEW_POLICY}))
                emit('checking_drawings',(56 if cycle==0 else 87)+int(10*offset/max(1,len(drawings))))
                scoped=_scoped_checker_evidence(extraction,drawings,requested,reference_parameters,reference_audit)
                detail_groups=[{**by_group[item['group_id']],'native_members_sha256':item['native_members_sha256']} for item in required_resolutions]
                detail=build_held_group_inspections(groups=detail_groups,inventory=inventory,
                    drawings=[view for view in drawings if view.id in requested],documents=documents,rendered=items,
                    output_dir=output,prefix=f'cycle-{lease["number"]}-check-held-{offset//2}',check_control=control)
                artifact_pins[str(detail['manifest_path'])]=_sha(detail['manifest_path'])
                for path in detail['images']:artifact_pins[str(path)]=_sha(path)
                content=[_text({'instruction':instruction,'selection':selection,'bindings':bindings.model_dump(),'requested_view_ids':requested,
                    'allowed_finding_owner_ids':sorted(owners),'allowed_finding_parameter_ids':sorted(params),
                    'required_rule_ids':list(RULES),'rule_catalog':RULES,'all_required_source_views':{
                        'project_name':index.project_name,'views':[{key:value for key,value in view.model_dump().items() if key not in ('correspondence_notes',)} for view in index.views],
                        'scope':'Complete source identity/correspondence summary; detailed review is requested-view only.'},
                    'extracted_facts':scoped['extracted_facts'],'artifacts':manifest,
                    'original_cross_view_evidence':original_cross_view,
                    'full_group_correspondence':scoped['full_group_correspondence'],
                    'cross_view_context_artifacts':[{'view_id':view.id,'artifact_ids':[item['artifact_id'] for item in rendered if item['view_id']==view.id]} for view in drawings],
                    'current_cross_view_raster_scope':'Every other current saved-PDF PNG is attached at its full saved resolution for R09; requested-view review scope and detailed reference proofs remain unchanged.',
                    'original_scoped_native_words':[v for v in scoped_words if v['view_id'] in requested],
                    'host_format_proof':[p for p in format_proofs if p['view_id'] in requested],
                    'host_source_proof':{'source_set_sha256':source_hash,'inventory_sha256':inventory_identity(inventory),'source_mode':'Verified original-PDF crop rasters and native source records; full original file inspected at mapping, no fabricated/cropped PDF viewport',
                        'all_native_ids_covered_once':True,'protected_ids':{key:len(value) for key,value in protected.items()},
                        'required_source_coverage':{key:value for key,value in required_coverage.items() if key in requested}},
                    'local_completeness_issues':[issue for record in local_quality['views'] if record['id'] in requested and record['status'] in ('incomplete','stale') for issue in record['issues']],
                    'conservatively_retained_groups':[item['group_id'] for item in required_resolutions],
                    'required_group_resolutions':required_resolutions,
                    'held_group_inspection':{key:value for key,value in detail.items() if key not in ('images','manifest_path')},
                    'group_resolution_authority':'Fresh exact-membership checker dispositions clear transient classifier questions only. They never waive core/cosmetic defects, texture instructions, normal review findings/verdicts, pending issues or customer-reference validation.',
                    'customer_review_policy':dict(CUSTOMER_REVIEW_POLICY),
                    'customer_reference_proof':{'acceptance_scope':'customer_reference_2d',
                        'reference_evidence_parameter_ids':reference_review_evidence,
                        'coverage_complete':bool(reference_audit.get('coverage_complete')),
                        'required_control_ids':[item['control_id'] for item in required_controls],
                        'resolved_control_ids':sorted(reference_parameters),
                        'requested_reference_control_ids':scoped['requested_reference_control_ids'],
                        'requested_view_annotations':{view.id:[ref.model_dump() for ref in view.reference_annotations]
                            for view in drawings if view.id in requested},
                        'reference_parameters':scoped['reference_parameters'],'host_audit':scoped['host_audit'],
                        'dependency_reference_values':scoped['dependency_reference_values'],
                        'validation_issues':scoped['host_audit']['validation_issues'],
                        'scope':'Global coverage counts/IDs are background only; detailed numerical/endpoint review is restricted to requested_reference_control_ids and requested views.',
                        'source_parameters_owners_native_paths_unchanged':True,'source_approval':False,
                        'fabrication_approval':False}}),
                    *[block for source in index.views for block in
                        (_text({'SOURCE_VIEW':source.id,'document_id':source.document_id,'page':source.page,'region':source.region,
                            'review_scope':'requested_view' if source.id in requested else 'cross_view_source_context'}),_image(source_crops[source.id]))],*capture,
                    *[block for ident,image in baseline_images.items() if ident in requested for block in (_text({'SAVED_ACCEPTED_BASELINE_VIEW':ident}),_image(image))],
                    *[block for path in detail['images'] for block in (_text({'HELD_GROUP_DETAIL':path.name,'diagnostic_only':True,'authority':'Source/current native-PDF ROI and exact-member diagnostics; no semantic answer. Cite the current saved candidate PDF/PNG for final-artifact findings.'}),_image(path.read_bytes()))]]
                if overview is not None:content.extend([_text({'COMPLETE_GROUP_OVERVIEW':'Low-resolution correspondence overview only; detailed other-view reference checks belong to their own requested batch.'}),_image(overview)])
                for a in items:
                    if a['path'].endswith('.png'):content += [_text({'ACTUAL_SAVED_PDF_RASTER':a['artifact_id'],'view_id':a['view_id']}),_image(Path(a['path']).read_bytes())]
                    elif a['view_id'] in requested and a['path'].endswith('.pdf'):
                        content.append({'type':'input_file','filename':a['artifact_id'],'file_data':'data:application/pdf;base64,'+base64.b64encode(Path(a['path']).read_bytes()).decode()})
                for a in rendered:
                    if a['view_id'] not in requested and a['path'].endswith('.png'):
                        content += [_text({'CROSS_VIEW_ACTUAL_SAVED_PDF_RASTER':a['artifact_id'],
                            'view_id':a['view_id'],'sha256':a['sha256'],
                            'scope':'Full-resolution current candidate evidence for R09; not an additional requested-view report.'}),
                            _image(Path(a['path']).read_bytes())]
                request_content=content
                remaining=(len(drawings)-offset-1)//2
                while True:
                    try:
                        report=call(ReviewReport,'check',request_content)
                    except AIError as error:
                        eligible=(error.category=='incomplete' and error.completed_output_limit is True
                            and check_output_limit_retries<MAX_CHECK_OUTPUT_LIMIT_RETRIES and request_count+1+remaining<=MAX_REQUESTS)
                        if not eligible:raise
                        unchanged();check_output_limit_retries+=1
                        record={'retry':check_output_limit_retries,'reason':'completed_max_output_tokens',
                            'cycle':lease['number'],'requested_view_ids':requested,'candidate_sha256':candidate_hash,
                            'artifacts_sha256':bindings.artifacts_sha256,'source_set_sha256':source_hash,
                            'failed_request_count':request_count,'remaining_ordinary_checks_reserved':remaining,
                            'partial_answer_reused':False,'new_drawing_cycle':False,'max_requests':MAX_REQUESTS}
                        check_output_limit_retry_records.append(record)
                        save(f'cycle-{lease["number"]}-check-output-limit-retry-{check_output_limit_retries}.json',record)
                        continue
                    if content_hash(model.model_dump())!=candidate_before:raise _Hold('Candidate content changed during the fresh checker request.')
                    try:
                        okay=validate_review(report,bindings,'2d',requested,list(RULES),documents,{a['artifact_id'] for a in rendered},owners,params,
                            {v:{a['artifact_id'] for a in items if a['view_id']==v} for v in requested},
                            allow_customer_references=bool(reference_parameters) and not reference_failures
                                and bool(reference_audit.get('coverage_complete')),
                            reference_control_ids=set(reference_parameters),reference_evidence_parameter_ids=reference_review_evidence,
                            practical_customer_review=True)
                    except ReviewFindingReferenceError as error:
                        spare=MAX_REQUESTS-request_count-remaining
                        next_cycle=needed if cycle==0 and spare>=needed else 0
                        if len(check_finding_reference_retries)>=MAX_CHECK_FINDING_REFERENCE_RETRIES or spare<=next_cycle:
                            raise
                        record={'cycle':lease['number'],'failed_request_count':request_count,
                            'requested_view_ids':requested,'bindings':bindings.model_dump(),
                            'remaining_ordinary_checks_reserved':remaining,'next_cycle_requests_reserved':next_cycle,
                            'invalid_finding_references':error.issues,'new_drawing_cycle':False,'invalid_report_accepted':False}
                        check_finding_reference_retries.append(record)
                        save(f'cycle-{lease["number"]}-check-finding-reference-retry.json',record)
                        retry_context=json.loads(content[0]['text'])
                        retry_context['host_review_reference_feedback']=error.issues
                        request_content=[_text(retry_context),*content[1:]]
                        continue
                    break
                resolved,resolution_issues=_validate_group_resolutions(report,required_resolutions,rendered,documents)
                resolved_held_ids.update(resolved);group_resolution_issues.extend(resolution_issues)
                okay=okay and not resolution_issues
                for verdict in report.views:
                    if verdict.status!='PASS' and not okay:continue
                    source=source_views[verdict.view_id]
                    if not any(ref.document_id==source.document_id and ref.page==source.page and
                        (ref.region is None or (ref.region[0]<source.region[2] and source.region[0]<ref.region[2] and
                         ref.region[1]<source.region[3] and source.region[1]<ref.region[3])) for ref in verdict.source_refs):
                        raise _Hold('A passed source view must cite its own original document/page/region, not only a different reference view.')
                    if not any(a['view_id']==verdict.view_id and a['artifact_id'].endswith(('.png','.pdf')) and
                        any(ref.artifact_id==a['artifact_id'] for ref in verdict.artifact_refs) for a in items):
                        raise _Hold('A passed view must cite its own actual PDF or saved-PDF raster; SVG metadata alone is not visual evidence.')
                last_review.append(report.model_dump());reports.append(report.model_dump());passed=passed and okay
                save(f'cycle-{lease["number"]}-summary-{offset//2}.json',{'event':'summary_after_check','accepted':okay,'report':report.model_dump(),
                    'group_resolution_issues':resolution_issues,'lesson_status':'SKIP'})
                save(f'cycle-{lease["number"]}-group-resolutions-{offset//2}.json',{'bindings':bindings.model_dump(),
                    'required_group_ids':[item['group_id'] for item in required_resolutions],'resolved_group_ids':sorted(resolved),
                    'unresolved_group_ids':[item['group_id'] for item in required_resolutions if item['group_id'] not in resolved],
                    'issues':resolution_issues,'normal_review_and_all_other_gates_still_required':True})
            pending=[issue for view in model.drawings for issue in view.pending]
            if pending:passed=False;issues.extend(pending)
            if local_failures:issues.extend(local_failures)
            issues.extend(group_resolution_issues)
            held_ids=[ident for ident in held_ids if ident not in resolved_held_ids]
            prior_group_questions=[question for question in prior_group_questions if question['group_id'] in held_ids]
            if held_ids:
                passed=False;issues.append('Unresolved automatic source groups retained conservatively: '+', '.join(held_ids[:20]))
            combined_hash=content_hash(last_review);qualified=any(report['verdict']=='PASS_WITH_LIMITS' for report in last_review)
            ledger.note_review(lease['lease_id'],candidate_sha256=candidate_hash,
                artifacts_sha256=content_hash(rendered),report_sha256=combined_hash,
                verdict=('PASS_WITH_LIMITS' if qualified else 'PASS') if passed else 'REVISE',accepted=passed)
            if passed:
                qualifications=list(dict.fromkeys([text for report in last_review if report['verdict']=='PASS_WITH_LIMITS'
                    for text in [*report['limitations'],*[finding['observed'] for finding in report['findings'] if finding['kind'] in ('source_uncertainty','design_reference','cosmetic')]]]))
                model.warnings=list(dict.fromkeys([*model.warnings,*qualifications]))
                model.drawings=[stamp_review(v,True,[]) for v in model.drawings];accepted=True;issues=list(qualifications);break
            issues.extend(f.observed for report in last_review for f in ReviewReport.model_validate(report).findings)
            model.drawings=[stamp_review(v,False,['Current autonomous source/output review is not accepted.']) for v in model.drawings]
            if cycle==1:break
            emit('refining_source_groups',68)
            # Spend the remaining complete-group allowance on refinement. An
            # unsplit group remains intact and must receive a definitive API
            # decision; it never becomes accepted because a budget was reached.
            cap=min(MAX_GROUPS_PER_DRAWING_SET,(MAX_REQUESTS-request_count-(len(drawings)+1)//2-int(bool(required_controls) and not title_only_baseline))*BATCH_GROUPS)
            if cap<sum(len(c['groups']) for c in catalogs):
                raise _Hold('Remaining bounded requests cannot classify and check the complete repair group.')
            refinement_targets=_refinement_group_targets(last_review,groups,drawings,rendered,held_ids)
            save(f'cycle-{lease["number"]}-refinement-targets.json',{'unresolved_held_group_ids':held_ids,
                'fresh_checker_target_group_ids':sorted(refinement_targets-set(held_ids)),
                'refinement_group_ids':sorted(refinement_targets),'semantic_decision':'none; fresh API reclassification and complete final review still required'})
            refined=[]
            for n,c in enumerate(catalogs):
                targets=[g['group_id'] for g in c['groups'] if g['group_id'] in refinement_targets]
                capacity=cap-sum(len(other['groups']) for other in refined)-sum(len(other['groups']) for other in catalogs[n+1:])
                refined.append(refine_catalog(c,targets,catalog_parts[n],
                    max_groups=min(MAX_GROUPS_PER_VIEW,capacity),allow_partial=True) if targets else c)
            catalogs=refined
            number=0
            for catalog in catalogs:
                for group in catalog['groups']:number+=1;group['group_id']=f'G{number:06d}'
            if number>MAX_GROUPS_PER_DRAWING_SET:raise _Hold('Refined source groups exceed the bounded catalog; no groups were merged or omitted.')
        return result()
    except Exception as error:
        if error is control_error or 'cancel' in type(error).__name__.lower() or 'pause' in type(error).__name__.lower():
            if ledger and lease:
                try:
                    latest=ledger.snapshot()['latest_cycle']
                    if latest and latest['lease_id']==lease['lease_id'] and latest['state'] in ('reserved','candidate_ready'):
                        ledger.note_failure(lease['lease_id'],phase=stage,category='cancelled')
                except (ValueError,OSError):pass
            raise
        from .reference_layout import _NoLane
        layout_failure=isinstance(error,_NoLane)
        if layout_failure:
            incomplete_output_cycle=lease['number'] if lease else None
            if last_complete_output:
                model=last_complete_output['model'].model_copy(deep=True)
                reference_parameters=copy.deepcopy(last_complete_output['reference_parameters'])
                reference_audit=copy.deepcopy(last_complete_output['reference_audit'])
                recovered_complete_cycle=last_complete_output['cycle']
            else:
                # Keep source facts, but never pass unrenderable or unprocessed
                # source ink off as a completed design-output group.
                model=model.model_copy(update={'drawings':[]})
        local_message=''
        if isinstance(error,(ValueError,TypeError,KeyError,ArithmeticError)) and not hasattr(error,'errors') and not hasattr(error,'usage'):
            local_message=str(error)[:1600]
            local_message=re.sub(r'(?i)\bsk[-_][A-Za-z0-9_-]+\b','[redacted credential]',local_message)
            local_message=re.sub(r'(?i)\b(authorization|api[_ -]?key|secret|bearer)\s*[:=]\s*\S+',r'\1=[redacted]',local_message)
        if layout_failure:
            issue=('A reference dimension could not be placed clearly. The last complete working drawings are retained for review.'
                if last_complete_output else 'A reference dimension could not be placed clearly. No complete drawing group was saved; the original source is retained.')
        elif isinstance(error,ReviewFindingReferenceError):
            issue='The drawing checker cited unavailable source identifiers. The working drawings are retained for review.'
        elif local_message.startswith('Automatic grouping needs '):
            issue='The selected source area is too broad for safe processing. Focus on the requested room or object; no drawing was accepted.'
        elif isinstance(error,(_Hold,DrawingCycleError)):issue=str(error)
        elif getattr(error,'category',None):issue='The AI request could not complete safely ('+str(error.category)+'). The current 2D result still needs review.'
        else:issue='The source output did not meet a required validation check. Review the selected source scope.'
        issues.append('2D review is on hold: '+issue)
        validation=getattr(error,'validation_errors',None)
        if validation is None and hasattr(error,'errors'):
            validation=error.errors(include_input=False,include_context=False,include_url=False)
        safe=[{'loc':list(item.get('loc',[])),'type':item.get('type','invalid_output')} for item in (validation or [])]
        save('failure.json',{'phase':stage,'display_phase':display_phase,'category':'drawing_layout' if layout_failure else getattr(error,'category','local_validation'),'error_type':type(error).__name__,
            'local_error_message':local_message,'validation_errors':safe,'request_count':request_count,'accepted':False,
            **({'invalid_finding_references':error.issues} if isinstance(error,ReviewFindingReferenceError) else {})})
        if ledger and lease:
            try:
                latest=ledger.snapshot()['latest_cycle']
                if latest and latest['lease_id']==lease['lease_id'] and latest['state'] in ('reserved','candidate_ready'):
                    ledger.note_failure(lease['lease_id'],phase=stage,category=getattr(error,'category','local_gate'))
            except (ValueError,OSError):pass
        if model.drawings:model.drawings=[stamp_review(v,False,issues[-1:]) for v in model.drawings]
        return result()
