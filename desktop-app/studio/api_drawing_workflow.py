"""Experimental, injected API workflow: source -> reviewed native2D -> reviewed3D.

Nothing here loads credentials, applies a project, calls a shell, or runs model code.
Production entry points opt in only after independent pilot acceptance.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ai import BOUNDARY, MODEL_PROMPT, IndexedView, SourceIndex
from .models import EvidenceRef, Parameter, Part, SourceView, StudioModel, expression_names
from .geometry import Resolver, build_scene, validate_model
from .drawing_models import DrawingPlan, DrawingRule, SourceEditGuard
from .drawing_workflow import _image, _source_crops, inventory_identity, NativePathRule, NativeViewRepair, NativeRepairs
from .source_vectors import build_inventory, compact_inventory
from .drafting import compile_drawings, drawing_hash, render_pdf, render_png, render_svg
from .drawing_cycle_budget import DrawingCycleBudget, DrawingCycleError, MAX_GROUP_CYCLES


def content_hash(value):
    def canonical(item):
        if isinstance(item, float) and item.is_integer(): return int(item)
        if isinstance(item, dict): return {key: canonical(value) for key, value in item.items()}
        if isinstance(item, list): return [canonical(value) for value in item]
        return item
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class EvidenceOwner(Record):
    id: str
    parent_id: str | None
    name: str
    kind: str
    evidence: list[EvidenceRef]


class DimensionBinding(Record):
    owner_id: str
    axis: Literal['width', 'depth', 'height']
    parameter_id: str


PARAMETER_ID_PATTERN=r'^[A-Za-z_][A-Za-z0-9_]{0,79}$'
MACHINE_EXPRESSION_PATTERN=r'^[A-Za-z0-9_+*/(). \t-]+$'


class ExtractedParameter(Parameter):
    """The local extraction schema exposes constraints omitted by legacy validators."""
    id: str = Field(pattern=PARAMETER_ID_PATTERN)
    expression: str | None = Field(default=None,pattern=MACHINE_EXPRESSION_PATTERN)


class ObservedSourceParameter(ExtractedParameter):
    status: Literal['source']
    value_mm: float
    expression: None


class UnknownSourceParameter(ExtractedParameter):
    status: Literal['tbc']
    value_mm: None
    expression: None


class InferredSourceParameter(ExtractedParameter):
    status: Literal['inferred']
    value_mm: None
    expression: str = Field(pattern=MACHINE_EXPRESSION_PATTERN,min_length=1)


class EvidenceExtraction(Record):
    source_index: SourceIndex
    owners: list[EvidenceOwner] = Field(min_length=1, max_length=1000)
    parameters: list[ObservedSourceParameter | UnknownSourceParameter | InferredSourceParameter] = Field(max_length=5000)
    dimension_bindings: list[DimensionBinding] = Field(max_length=3000)
    warnings: list[str]

    @model_validator(mode='after')
    def graph(self):
        owners = {owner.id: owner for owner in self.owners}
        parameters = {parameter.id: parameter for parameter in self.parameters}
        if len(owners) != len(self.owners) or len(parameters) != len(self.parameters):
            raise ValueError('Extraction identities must be unique')
        if sum(owner.parent_id is None for owner in self.owners) != 1:
            raise ValueError('Extraction needs exactly one owner root')
        for owner in self.owners:
            seen = set(); current = owner
            while current.parent_id is not None:
                if current.id in seen or current.parent_id not in owners:
                    raise ValueError('Extraction owner graph has a cycle or missing parent')
                seen.add(current.id); current = owners[current.parent_id]
        bindings = [(item.owner_id, item.axis) for item in self.dimension_bindings]
        if len(set(bindings)) != len(bindings):
            raise ValueError('Conflicting dimensions must remain observations, not duplicate axis bindings')
        if any(item.owner_id not in owners or item.parameter_id not in parameters for item in self.dimension_bindings):
            raise ValueError('Dimension binding cites an unavailable owner or observation')
        return self


class ParameterStructureRepair(Record):
    old_parameter_id: str
    new_parameter_id: str = Field(pattern=PARAMETER_ID_PATTERN)
    expression: str | None = Field(pattern=MACHINE_EXPRESSION_PATTERN)


class ExtractionStructureRepairs(Record):
    repairs: list[ParameterStructureRepair] = Field(min_length=1,max_length=5000)


def repair_extraction_structure(raw,repair):
    """Explicit aliases and proved equivalent formulas only; never parse prose heuristically."""
    import copy
    repair=ExtractionStructureRepairs.model_validate(repair.model_dump() if isinstance(repair,BaseModel) else repair)
    payload=copy.deepcopy(raw);parameters=payload['parameters']
    original_ids=[item['id'] for item in parameters]
    old=[item.old_parameter_id for item in repair.repairs];new=[item.new_parameter_id for item in repair.repairs]
    if len(set(original_ids))!=len(original_ids) or len(set(old))!=len(old) or set(old)!=set(original_ids) or len(set(new))!=len(new):
        raise ValueError('Structural repair must bijectively cover every original parameter exactly once')
    changes={item.old_parameter_id:item for item in repair.repairs};aliases={key:item.new_parameter_id for key,item in changes.items()}
    proofs=[]
    for parameter in parameters:
        patch=changes[parameter['id']];parameter['id']=patch.new_parameter_id
        if parameter['status']=='inferred':
            value=parameter.get('value_mm')
            if value is None or isinstance(value,bool) or not math.isfinite(value) or patch.expression is None:
                raise ValueError('Inferred structural repair requires its original finite numeric result and explicit machine formula')
            if not expression_names(patch.expression):raise ValueError('An inferred repair must reference an existing observation, not echo a constant result')
            proofs.append({'parameter_id':patch.new_parameter_id,'original_id':patch.old_parameter_id,
                'recorded_numeric_result_mm':value,'original_expression':parameter.get('expression'),'machine_expression':patch.expression})
            parameter['value_mm']=None;parameter['expression']=patch.expression
        elif patch.expression!=parameter.get('expression'):
            raise ValueError('Source and TBC facts cannot receive an invented expression')
    for binding in payload['dimension_bindings']:
        if binding['parameter_id'] not in aliases:raise ValueError('Original dimension binding references a missing observation')
        binding['parameter_id']=aliases[binding['parameter_id']]
    extraction=EvidenceExtraction.model_validate(payload)
    # The standard resolver supplies the same finite arithmetic and dependency rules.
    root=Part(id='REPAIR_CHECK',name='Structural proof')
    resolver=Resolver(StudioModel(name='Structural proof',root=root,
        parameters=[Parameter.model_validate(item.model_dump()) for item in extraction.parameters]))
    for parameter in extraction.parameters:resolver.parameter(parameter.id)
    for proof in proofs:
        actual=resolver.parameter(proof['parameter_id'])[0];expected=proof['recorded_numeric_result_mm']
        tolerance=min(1e-8,16*max(math.ulp(actual) if actual is not None else 0.,math.ulp(float(expected))))
        if actual is None or abs(actual-expected)>tolerance:raise ValueError('Repaired expression differs from the recorded inferred result')
        proof.update(resolved_mm=actual,absolute_difference_mm=abs(actual-expected),tolerance_mm=tolerance)
    # Prove immutable facts, not merely the totals or a model's assurance.
    restored=copy.deepcopy(extraction.model_dump());inverse={value:key for key,value in aliases.items()}
    for parameter,original in zip(restored['parameters'],raw['parameters']):
        parameter['id']=inverse[parameter['id']]
        if original['status']=='inferred':parameter['value_mm']=original.get('value_mm');parameter['expression']=original.get('expression')
    for binding in restored['dimension_bindings']:binding['parameter_id']=inverse[binding['parameter_id']]
    normalized_raw=copy.deepcopy(raw)
    # Legacy payload defaults are compared through the original record keys.
    def project(value,template):
        if isinstance(template,dict):return {key:project(value[key],item) for key,item in template.items()}
        if isinstance(template,list):return [project(item,base) for item,base in zip(value,template)]
        return value
    if content_hash(project(restored,normalized_raw))!=content_hash(normalized_raw):
        raise ValueError('Structural repair changed an original value,status,evidence,owner,view,label or warning')
    return extraction,{'id_aliases':aliases,'expression_equivalence':proofs,'original_facts_preserved':True,
                       'raw_extraction_sha256':content_hash(raw),'repairs_sha256':content_hash(repair.model_dump())}


class ReviewBindings(Record):
    project_id: str
    run_id: str
    source_set_sha256: str
    candidate_sha256: str
    artifacts_sha256: str
    profile_sha256: str


class SourceRef(Record):
    document_id: str
    page: int = Field(ge=1)
    region: list[float] | None
    text: str


class ArtifactRef(Record):
    artifact_id: str
    region: list[float] | None


ReviewStatus = Literal['PASS', 'FAIL', 'NOT_REVIEWED', 'NOT_APPLICABLE']


class ViewReview(Record):
    view_id: str
    status: ReviewStatus
    source_refs: list[SourceRef]
    artifact_refs: list[ArtifactRef]
    finding_ids: list[str]
    notes: str


class CriterionReview(Record):
    rule_id: str
    status: ReviewStatus
    supporting_finding_ids: list[str]
    notes: str


class Finding(Record):
    id: str
    rule_id: str
    severity: Literal['blocker', 'major', 'minor']
    kind: Literal['core', 'cosmetic', 'source_uncertainty', 'design_reference', 'unperformed']
    view_ids: list[str]
    owner_ids: list[str]
    parameter_ids: list[str]
    source_refs: list[SourceRef]
    artifact_refs: list[ArtifactRef]
    observed: str
    expected: str
    repair: str
    repairable: bool


class SourceGroupResolution(Record):
    group_id: str = Field(pattern=r'^G[0-9]{3,6}$')
    view_id: str = Field(min_length=1, max_length=80)
    native_members_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    disposition: Literal['retain_required', 'retain_nonblocking_context', 'unresolved']
    source_refs: list[SourceRef] = Field(max_length=50)
    artifact_refs: list[ArtifactRef] = Field(max_length=50)
    reason: str = Field(min_length=1, max_length=3000)


class ReviewReport(Record):
    schema_version: Literal['vwc-drawing-review/1']
    target: Literal['2d', '3d']
    bindings: ReviewBindings
    verdict: Literal['PASS', 'PASS_WITH_LIMITS', 'REVISE', 'SOURCE_HOLD', 'NOT_REVIEWED']
    views: list[ViewReview]
    criteria: list[CriterionReview]
    findings: list[Finding]
    limitations: list[str]
    group_resolutions: list[SourceGroupResolution] = Field(default_factory=list, max_length=512)


class CorrectiveNativePathRule(NativePathRule):
    primitive_ids: list[str] = Field(default_factory=list,max_length=8)


class CorrectiveNativeViewRepair(NativeViewRepair):
    rules: list[CorrectiveNativePathRule] = Field(max_length=12)
    source_region: None = None
    pending: list[str] = Field(max_length=12)
    edit_guards: list[SourceEditGuard] = Field(default_factory=list,max_length=0)

    @model_validator(mode='after')
    def no_guard_revision(self):
        if self.edit_guards:raise ValueError('A bounded visual correction cannot revise source edit guards')
        return self


class CorrectiveNativeRepairs(NativeRepairs):
    views: list[CorrectiveNativeViewRepair] = Field(max_length=12)


@dataclass
class CallBudget:
    max_calls: int = 9
    used: int = 0

    def reserve(self):
        if self.used >= self.max_calls:
            raise ValueError('Actual request budget exhausted; no automatic retry is authorized')
        self.used += 1


def load_profile(directory):
    directory = Path(directory).resolve(strict=True)
    payload = json.loads((directory/'profile.json').read_text(encoding='utf-8'))
    paths = [directory/'profile.json', directory/'schemas/review-report.schema.json']
    prompts = {}
    for phase, relative in payload['prompts'].items():
        path = (directory/relative).resolve(strict=True)
        if not path.is_relative_to(directory): raise ValueError('Profile prompt escapes its package')
        prompts[phase] = path.read_text(encoding='utf-8'); paths.append(path)
    for contract in payload.get('phase_contracts',{}).values():
        if contract.get('schema'):
            path=(directory/contract['schema']).resolve(strict=True)
            if not path.is_relative_to(directory):raise ValueError('Profile schema escapes its package')
            paths.append(path)
    paths=list(dict.fromkeys(paths))
    snapshot = {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    return payload, prompts, content_hash(snapshot), paths


def _bound_profile(directory,style_images):
    profile,prompts,fingerprint,paths=load_profile(directory);pins={}
    for item in style_images or []:
        if item.get('role')!='style_only':raise ValueError('Reference role must be style_only')
        actual=hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()
        if actual!=item['sha256']:raise ValueError('Pinned reference bytes changed')
        pins[str(item['path'])]=actual
    return profile,prompts,content_hash({'profile':fingerprint,'style_references':pins}),paths


def repair_extraction_checkpoint(gateway,documents,raw_response_path,input_binding_path,output_dir,profile_dir,*,
                                 origin_profile_dir,project_id,run_id,style_images=None,budget=None,progress=None):
    """ONE explicitly invoked format repair; not extraction or source reinterpretation."""
    profile,prompts,target_hash,paths=_bound_profile(profile_dir,style_images)
    if profile['phase_call_caps'].get('extract_structure_repair')!=1:
        raise ValueError('Profile does not authorize exactly one explicit structural repair')
    _,_,origin_hash,origin_paths=_bound_profile(origin_profile_dir,style_images)
    source_hash=_source_identity(documents);raw_path=Path(raw_response_path).resolve(strict=True)
    binding_path=Path(input_binding_path).resolve(strict=True)
    raw=json.loads(raw_path.read_text(encoding='utf-8'));binding=json.loads(binding_path.read_text(encoding='utf-8'))
    if (binding['project_id'],binding['run_id'],binding['source_set_sha256'],binding['profile_sha256'])!=(project_id,run_id,source_hash,origin_hash):
        raise ValueError('Original failed extraction belongs to another project/run/source/profile')
    original_scope=[IndexedView.model_validate(view) for view in binding['required_views']]
    actual_scope={view['id']:(view['document_id'],view['page'],view['kind']) for view in raw['source_index']['views']}
    if len(raw['source_index']['views'])!=len(original_scope) or actual_scope!={view.id:(view.document_id,view.page,view.kind) for view in original_scope}:
        raise ValueError('Format repair cannot rescue an omitted or changed source scope')
    output=Path(output_dir).resolve();output.mkdir(parents=True,exist_ok=True)
    checkpoint_path=output/'extraction-checkpoint.json'
    if checkpoint_path.exists():raise ValueError('A structural repair already exists; validate and resume it without another paid request')
    pinned={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [raw_path,binding_path,*paths,*origin_paths]}
    def unchanged():
        if _source_identity(documents)!=source_hash or any(hashlib.sha256(Path(path).read_bytes()).hexdigest()!=value for path,value in pinned.items()):
            raise ValueError('Extraction repair source/profile/raw binding changed during the request')
        _bound_profile(profile_dir,style_images);_bound_profile(origin_profile_dir,style_images)
    budget=budget or CallBudget(max_calls=1);unchanged();budget.reserve()
    content=[{'type':'input_text','text':json.dumps({'purpose':'STRUCTURAL FORMAT REPAIR ONLY; no new source reading or fact changes',
        'raw_extraction':raw,'requirements':'Every original parameter exactly once; bijective safe aliases; source/TBC expression unchanged; inferred formula references existing aliased facts and proves the recorded numeric result. No guessing,source amendments or dropped facts.'},ensure_ascii=False)}]
    try:
        repair,usage=gateway._request(ExtractionStructureRepairs,BOUNDARY+prompts['extract_structure_repair'],content,progress=progress)
    except Exception as error:
        (output/'repair-failure.json').write_text(json.dumps({'category':getattr(error,'category','local_gate'),
            'calls_used':budget.used,'usage':getattr(error,'usage',{}),'accepted':False},indent=2),encoding='utf-8')
        unchanged();raise
    (output/'structure-repairs.json').write_text(repair.model_dump_json(indent=2),encoding='utf-8')
    (output/'structure-repair-usage.json').write_text(json.dumps(usage,indent=2),encoding='utf-8');unchanged()
    try:
        extraction,proof=repair_extraction_structure(raw,repair)
    except Exception as error:
        (output/'equivalence-failure.json').write_text(json.dumps({'accepted':False,'category':'structural_equivalence',
            'error_type':type(error).__name__,'calls_used':budget.used},indent=2),encoding='utf-8')
        raise
    checkpoint={'schema':'vwc-extraction-checkpoint/1','project_id':project_id,'run_id':run_id,
        'source_set_sha256':source_hash,'profile_sha256':target_hash,'origin_profile_sha256':origin_hash,
        'required_views_sha256':content_hash([view.model_dump() for view in original_scope]),
        'raw_response':{'path':str(raw_path),'sha256':pinned[str(raw_path)]},
        'original_input_binding':{'path':str(binding_path),'sha256':pinned[str(binding_path)]},
        'repairs':repair.model_dump(),'extraction':extraction.model_dump(),'proof':proof,
        'review_passes_transferred':0,'structure_repair_usage':usage}
    checkpoint['checkpoint_sha256']=content_hash(checkpoint)
    checkpoint_path.write_text(json.dumps(checkpoint,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'equivalence-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    return checkpoint


def validate_extraction_checkpoint(checkpoint,*,documents,project_id,run_id,profile_sha256,required_views):
    checkpoint=json.loads(json.dumps(checkpoint))
    digest=checkpoint.pop('checkpoint_sha256',None)
    if digest!=content_hash(checkpoint):raise ValueError('Extraction checkpoint content hash changed')
    if (checkpoint.get('schema'),checkpoint['project_id'],checkpoint['run_id'],checkpoint['source_set_sha256'],checkpoint['profile_sha256'])!=(
            'vwc-extraction-checkpoint/1',project_id,run_id,_source_identity(documents),profile_sha256):
        raise ValueError('Extraction checkpoint belongs to another source/project/run/profile')
    expected_scope=content_hash([IndexedView.model_validate(view).model_dump() for view in required_views])
    if checkpoint['required_views_sha256']!=expected_scope or checkpoint['review_passes_transferred']!=0:
        raise ValueError('Extraction resume cannot change scope or import a prior checker pass')
    for field in ('raw_response','original_input_binding'):
        ref=checkpoint[field]
        if hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()!=ref['sha256']:
            raise ValueError('Original failed extraction artifact changed')
    original_binding=json.loads(Path(checkpoint['original_input_binding']['path']).read_text(encoding='utf-8'))
    if ((original_binding['project_id'],original_binding['run_id'],original_binding['source_set_sha256'],original_binding['profile_sha256'])
            !=(project_id,run_id,checkpoint['source_set_sha256'],checkpoint['origin_profile_sha256'])
            or content_hash(original_binding['required_views'])!=checkpoint['required_views_sha256']):
        raise ValueError('Extraction checkpoint lost its original source/profile/run/scope binding')
    raw=json.loads(Path(checkpoint['raw_response']['path']).read_text(encoding='utf-8'))
    extraction,proof=repair_extraction_structure(raw,checkpoint['repairs'])
    if content_hash(extraction.model_dump())!=content_hash(checkpoint['extraction']) or proof!=checkpoint['proof']:
        raise ValueError('Extraction checkpoint no longer proves unchanged source facts')
    for rebind in checkpoint.get('profile_rebindings',[]):
        if rebind['source_set_sha256']!=checkpoint['source_set_sha256'] or rebind['unchanged_extraction_sha256']!=content_hash(extraction.model_dump()):
            raise ValueError('Extraction profile rebind changed source facts')
        if rebind['native_plans_transferred']!=0 or rebind['review_passes_transferred']!=0:
            raise ValueError('Extraction profile rebind cannot transfer native plans or checker passes')
        for ref in rebind['origin_profile_files']:
            if _artifact_ref(ref['path'])['sha256']!=ref['sha256']:raise ValueError('Extraction origin profile changed after rebind')
    if checkpoint.get('profile_rebindings') and checkpoint['profile_rebindings'][-1]['target_profile_sha256']!=profile_sha256:
        raise ValueError('Extraction profile rebind does not match the requested target')
    return extraction


def rebind_extraction_checkpoint(checkpoint,*,documents,origin_profile_dir,target_profile_dir,project_id,run_id,required_views,style_images=None):
    """Explicit local profile upgrade; reuse proved facts, never native plans/reviews."""
    if isinstance(checkpoint,(str,Path)):checkpoint=json.loads(Path(checkpoint).read_text(encoding='utf-8'))
    checkpoint=json.loads(json.dumps(checkpoint))
    _,_,origin_hash,origin_paths=_bound_profile(origin_profile_dir,style_images)
    _,_,target_hash,_=_bound_profile(target_profile_dir,style_images)
    extraction=validate_extraction_checkpoint(checkpoint,documents=documents,project_id=project_id,run_id=run_id,
        profile_sha256=origin_hash,required_views=required_views)
    previous_hash=checkpoint.pop('checkpoint_sha256')
    checkpoint.setdefault('profile_rebindings',[]).append({'previous_checkpoint_sha256':previous_hash,
        'origin_profile_sha256':origin_hash,'target_profile_sha256':target_hash,
        'origin_profile_files':[_artifact_ref(path) for path in origin_paths],
        'source_set_sha256':checkpoint['source_set_sha256'],'unchanged_extraction_sha256':content_hash(extraction.model_dump()),
        'native_plans_transferred':0,'review_passes_transferred':0})
    checkpoint['profile_sha256']=target_hash;checkpoint['checkpoint_sha256']=content_hash(checkpoint)
    validate_extraction_checkpoint(checkpoint,documents=documents,project_id=project_id,run_id=run_id,
        profile_sha256=target_hash,required_views=required_views)
    return checkpoint


def _source_identity(documents):
    identities = []
    for document in documents:
        actual = hashlib.sha256(Path(document['local_path']).read_bytes()).hexdigest()
        if actual != document['sha256']: raise ValueError('Imported source bytes differ from their recorded hash')
        identities.append({'id': document['id'], 'sha256': actual, 'page_count': document['page_count']})
    if len({item['id'] for item in identities}) != len(identities): raise ValueError('Duplicate source identity')
    return content_hash(identities)


def _native_2d_candidate(documents, extraction, plan, inventory=None):
    """One deterministic scope/owner/visible-ink gate used by creation and resume."""
    inventory=inventory if inventory is not None else build_inventory(documents,extraction.source_index)
    if not inventory['views']:raise ValueError('Selected source has no supported native vector views')
    plan=DrawingPlan.model_validate(plan)
    if {item.view_id for item in plan.views}!={item['id'] for item in inventory['views']} or len(plan.views)!=len(inventory['views']):
        raise ValueError('2D plan changed the requested native scope')
    if any(item.source_region is not None for item in plan.views):
        raise ValueError('Experimental pilot crop changes require a fresh extraction, not silent selector rebasing')
    drawings=compile_drawings(inventory,plan)
    owner_ids={owner.id for owner in extraction.owners}
    if any(set(view.owner_ids)-owner_ids for view in drawings):raise ValueError('2D cites an unextracted owner')
    if any(not any(p.kind=='path' and p.stroke and p.stroke_color=='ink' and p.role in ('geometry','context') for p in view.primitives) for view in drawings):
        raise ValueError('A required2D view has no visible native geometry')
    return inventory,drawings


def _artifact_ref(path):
    path=Path(path).resolve(strict=True)
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def _validate_refs(refs, documents):
    imported = {item['id']: item for item in documents}
    for reference in refs:
        if reference.document_id not in imported or reference.page > imported[reference.document_id]['page_count']:
            raise ValueError('Evidence cites a page outside the imported source set')
        region = reference.region
        if region is not None and (len(region) != 4 or not all(math.isfinite(v) for v in region)
                                  or not 0 <= region[0] < region[2] <= 1 or not 0 <= region[1] < region[3] <= 1):
            raise ValueError('Evidence region is not normalized display coordinates')


def evidence_model(extraction, documents):
    extraction = EvidenceExtraction.model_validate(extraction.model_dump())
    for owner in extraction.owners: _validate_refs(owner.evidence, documents)
    for parameter in extraction.parameters: _validate_refs(parameter.evidence, documents)
    owners = {owner.id: owner for owner in extraction.owners}
    def part(ident):
        owner = owners[ident]
        return Part(id=owner.id, name=owner.name, kind=owner.kind, authority='source', physical=False,
                    evidence=owner.evidence, children=[part(child.id) for child in extraction.owners if child.parent_id == ident])
    views = []
    for view in extraction.source_index.views:
        if view.kind not in ('plan', 'elevation'): continue
        top = view.kind == 'plan'
        views.append(SourceView(id=view.id, label=view.label, kind=view.kind, document_id=view.document_id,
            page=view.page, region=view.region, direction=[0., 0., -1.] if top else [0., 1., 0.],
            right=[1., 0., 0.], up=[0., 1., 0.] if top else [0., 0., 1.]))
    root = next(owner.id for owner in extraction.owners if owner.parent_id is None)
    return validate_model(StudioModel(name=extraction.source_index.project_name, root=part(root),
        parameters=extraction.parameters, views=views, warnings=extraction.warnings))


def validate_geometry_candidate(candidate, extraction, documents):
    candidate = validate_model(candidate)
    if candidate.drawings: raise ValueError('3D creator cannot manufacture or transfer accepted native drawing stamps')
    before = evidence_model(extraction, documents)
    expected_views={view.id:(view.document_id,view.page,view.kind) for view in before.views}
    if ({view.id:(view.document_id,view.page,view.kind) for view in candidate.views}!=expected_views
            or len(candidate.views)!=len(expected_views)):
        raise ValueError('3D must retain every independently required source-view identity')
    def parts(root):
        result = {root.id: root}
        for child in root.children: result.update(parts(child))
        return result
    old_parts = parts(before.root); new_parts = parts(candidate.root)
    parameters = {parameter.id: parameter for parameter in candidate.parameters}
    for parameter in before.parameters:
        if parameter.id not in parameters or parameters[parameter.id] != parameter:
            raise ValueError('3D changed a frozen extracted source observation')
    for parameter in candidate.parameters:
        _validate_refs(parameter.evidence, documents)
        if parameter.id not in {item.id for item in before.parameters} and parameter.status not in ('tbc', 'inferred'):
            raise ValueError('Additional measured/designed facts require explicit extraction or user authorization')
        if parameter.status == 'inferred' and (not parameter.expression or not parameter.evidence):
            raise ValueError('An inferred dimension needs an exact expression and source evidence')
    for ident, owner in old_parts.items():
        if ident not in new_parts or new_parts[ident].evidence != owner.evidence:
            raise ValueError('3D removed an extracted owner or its source evidence')
    for part in new_parts.values():
        _validate_refs(part.evidence, documents)
        if (part.physical or part.surface is not None) and (part.authority != 'source' or not part.evidence):
            raise ValueError('Visible source geometry needs source authority and evidence')
    resolver = Resolver(candidate)
    for binding in extraction.dimension_bindings:
        owner = new_parts[binding.owner_id]
        axis = {'width': 0, 'depth': 1, 'height': 2}[binding.axis]
        expression = owner.size[axis] if owner.size else None
        if owner.surface is not None:
            if axis == 0: expression = owner.surface.width
            elif axis == (2 if owner.surface.plane == 'front' else 1): expression = owner.surface.span
        # A nonphysical container may retain a TBC envelope while children carry faces.
        if expression is not None:
            actual = resolver.expression(expression)[0]; observed = resolver.parameter(binding.parameter_id)[0]
            if actual != observed: raise ValueError('3D dimension disagrees with its extracted owner/axis binding')
    scene=build_scene(candidate,'validation',1)
    meshes=[*scene['meshes'],*[mesh for frame in scene.get('local_frames',{}).values() for mesh in frame['meshes']]]
    for mesh in meshes:
        vertices = mesh['vertices']
        for start in range(0, len(mesh['indices']), 3):
            a, b, c = [vertices[index] for index in mesh['indices'][start:start+3]]
            u = [b[i]-a[i] for i in range(3)]; v = [c[i]-a[i] for i in range(3)]
            cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
            if sum(value*value for value in cross) <= 1e-16:
                raise ValueError('Rendered3D contains a zero-area triangle')
    return candidate


def render_scene_png(scene, right, up, label, size=1000, *, hide_occluded_edges=False):
    """Actual canonical triangles/edges, fixed camera, no stock/example geometry."""
    from PIL import Image, ImageDraw
    meshes = scene['meshes']
    if not meshes: raise ValueError('No known geometry in the selected3D scope')
    direction = [right[1]*up[2]-right[2]*up[1], right[2]*up[0]-right[0]*up[2], right[0]*up[1]-right[1]*up[0]]
    projected = [(mesh, [[sum(p[i]*basis[i] for i in range(3)) for basis in (right, up, direction)]
                        for p in mesh['vertices']]) for mesh in meshes]
    points = [p for _, vertices in projected for p in vertices]
    xmin=min(p[0] for p in points);xmax=max(p[0] for p in points);ymin=min(p[1] for p in points);ymax=max(p[1] for p in points)
    scale=(size-100)/max(xmax-xmin,ymax-ymin,1.)
    def xy(p): return (50+(p[0]-xmin)*scale, size-50-(p[1]-ymin)*scale)
    image = Image.new('RGB',(size,size),'white'); draw=ImageDraw.Draw(image)
    faces=[]
    for mesh, vertices in projected:
        outline = {tuple(sorted(edge)) for edge in mesh['edges']} if hide_occluded_edges else set()
        for start in range(0,len(mesh['indices']),3):
            triangle = mesh['indices'][start:start+3]
            face=[vertices[index] for index in triangle]
            edges = [(vertices[a], vertices[b]) for a,b in zip(triangle,triangle[1:]+triangle[:1])
                     if tuple(sorted((a,b))) in outline] if outline else ()
            faces.append((sum(p[2] for p in face)/3,face,edges))
    for _, face, edges in sorted(faces,key=lambda item:item[0]):
        draw.polygon([xy(p) for p in face],fill='#e4e9e7')
        for a,b in edges: draw.line([xy(a),xy(b)],fill='#172f31',width=2)
    if not hide_occluded_edges:
        for mesh, vertices in projected:
            for a,b in mesh['edges']: draw.line([xy(vertices[a]),xy(vertices[b])],fill='#172f31',width=2)
    draw.text((20,15),label+' / canonical mm; source uncertainty retained',fill='#172f31')
    output=io.BytesIO();image.save(output,format='PNG');return output.getvalue()


class ReviewFindingReferenceError(ValueError):
    """A typed report used finding IDs outside the host registries."""

    def __init__(self, issues):
        super().__init__('Review finding cites an unavailable owner,parameter,view or rule')
        self.issues = issues


def validate_review(report, bindings, target, view_ids, rule_ids, documents, artifact_ids, owner_ids, parameter_ids,view_artifacts=None, *, allow_customer_references=False,reference_control_ids=(),reference_evidence_parameter_ids=None,practical_customer_review=False):
    report = ReviewReport.model_validate(report.model_dump())
    if report.target != target or report.bindings != bindings: raise ValueError('Review belongs to different source/candidate/render/profile content')
    if len({v.view_id for v in report.views}) != len(report.views) or {v.view_id for v in report.views} != set(view_ids):
        raise ValueError('Review must cover exactly every requested view')
    if len({r.rule_id for r in report.criteria}) != len(report.criteria) or {r.rule_id for r in report.criteria} != set(rule_ids):
        raise ValueError('Review must cover exactly the applicable rules')
    findings={finding.id:finding for finding in report.findings}
    if len(findings)!=len(report.findings): raise ValueError('Duplicate finding identity')
    finding_issues = []
    allowed_views, allowed_owners, allowed_parameters = set(view_ids), set(owner_ids), set(parameter_ids)
    for finding in report.findings:
        unavailable = {'rule_id': [] if finding.rule_id in rule_ids else [finding.rule_id],
            'view_ids': sorted(set(finding.view_ids)-allowed_views),
            'owner_ids': sorted(set(finding.owner_ids)-allowed_owners),
            'parameter_ids': sorted(set(finding.parameter_ids)-allowed_parameters)}
        if any(unavailable.values()):
            finding_issues.append({'finding_id': finding.id[:120],
                'unavailable': {field: [ident[:120] for ident in identities[:20]]
                    for field, identities in unavailable.items() if identities}})
    if finding_issues:
        raise ReviewFindingReferenceError(finding_issues[:40])
    def refs(sources,artifacts):
        _validate_refs(sources,documents)
        if any(item.artifact_id not in artifact_ids for item in artifacts): raise ValueError('Review cites an unavailable artifact')
        for item in artifacts:
            if item.region is not None and (len(item.region)!=4 or not 0<=item.region[0]<item.region[2]<=1 or not 0<=item.region[1]<item.region[3]<=1):
                raise ValueError('Invalid rendered artifact region')
    for finding in report.findings:
        if finding.kind=='design_reference':
            controls=set(finding.parameter_ids)&set(reference_control_ids)
            supporting=set().union(*(set((reference_evidence_parameter_ids or {}).get(ident,())) for ident in controls))
            if (not allow_customer_references or target!='2d' or not controls
                    or set(finding.parameter_ids)-controls-supporting):
                raise ValueError('Design-reference limits require validated controls and their host-linked source evidence')
        if finding.kind=='design_reference' and finding.repairable:
            raise ValueError('A repairable reference defect must be core/cosmetic and cannot be waived as a reference limitation')
        refs(finding.source_refs,finding.artifact_refs)
    for view in report.views:
        refs(view.source_refs,view.artifact_refs)
        if set(view.finding_ids)-findings.keys(): raise ValueError('View references a missing finding')
        if view.status=='PASS' and (not view.source_refs or not view.artifact_refs): raise ValueError('A passed view needs source and actual-render evidence')
        if view.status=='PASS' and view_artifacts is not None and not any(ref.artifact_id in view_artifacts[view.view_id] for ref in view.artifact_refs):
            raise ValueError('A passed view must cite its own actual rendered artifact')
    for rule in report.criteria:
        if set(rule.supporting_finding_ids)-findings.keys(): raise ValueError('Rule references a missing finding')
    for item in [*report.views,*report.criteria]:
        ids=item.finding_ids if isinstance(item,ViewReview) else item.supporting_finding_ids
        if report.verdict in ('PASS','PASS_WITH_LIMITS') and item.status=='FAIL' and any(findings[ident].kind=='design_reference' for ident in ids):
            raise ValueError('A failed drawing check cannot be waived as a design-reference limitation')
    accepted=report.verdict in ('PASS','PASS_WITH_LIMITS')
    if accepted:
        practical_2d=practical_customer_review and target=='2d'
        if any(v.status=='NOT_REVIEWED' for v in [*report.views,*report.criteria]): raise ValueError('Unperformed review cannot pass')
        if any(view.status=='NOT_APPLICABLE' for view in report.views):raise ValueError('An independently required view cannot be waived as inapplicable')
        if any(rule.status=='NOT_APPLICABLE' and not rule.notes.strip() for rule in report.criteria):raise ValueError('Inapplicable rule needs an explicit source-based reason')
        if report.verdict=='PASS' and (report.findings or any(v.status=='FAIL' for v in [*report.views,*report.criteria])):
            raise ValueError('Unresolved findings cannot be an unqualified pass')
        if report.verdict=='PASS_WITH_LIMITS':
            allowed={'source_uncertainty','design_reference'} if allow_customer_references and target=='2d' else {'source_uncertainty'}
            if practical_2d:
                # This is an explicit customer-review policy, not a promotion
                # of a REVISE report or a waiver of an actually failed check.
                if any(v.status=='FAIL' for v in [*report.views,*report.criteria]):
                    raise ValueError('Practical customer review cannot waive a failed drawing check')
                for finding in report.findings:
                    if finding.kind=='cosmetic':
                        if finding.rule_id not in {'R07','R08'}:
                            raise ValueError('Practical cosmetic notes belong to readability or presentation only')
                        if finding.severity!='minor' or not finding.view_ids or not finding.source_refs or not finding.artifact_refs:
                            raise ValueError('Practical cosmetic notes need minor severity and actual source/output evidence')
                        if view_artifacts is not None and any(not any(ref.artifact_id in view_artifacts.get(view_id,set())
                            for ref in finding.artifact_refs) for view_id in finding.view_ids):
                            raise ValueError('Practical cosmetic notes must cite each affected view actual output')
                allowed=allowed|{'cosmetic'}
            if not report.limitations or any(f.kind not in allowed or f.severity=='blocker' for f in report.findings):
                raise ValueError('Qualified pass permits recorded source uncertainty only')
            for item in [*report.views,*report.criteria]:
                ids=item.finding_ids if isinstance(item,ViewReview) else item.supporting_finding_ids
                if item.status=='FAIL' and not ids: raise ValueError('A qualified failed criterion needs an explicit uncertainty finding')
    return accepted


def run_2d_corrective_patch(gateway,documents,output_dir,profile_dir,instruction,*,prior_output_dir,origin_profile_dir,
                            extraction_checkpoint,project_id,run_id,required_views,findings,style_images=None,
                            budget=None,progress=None,on_event=None,cycle_ledger_path=None):
    """ONE small selection patch + ONE fresh full review; never recreate the plan."""
    prior=Path(prior_output_dir).resolve(strict=True)
    if (prior/'plan-2d-1.json').exists():raise ValueError('The existing2D corrective patch allowance was already consumed')
    checkpoint=rebind_extraction_checkpoint(extraction_checkpoint,documents=documents,origin_profile_dir=origin_profile_dir,
        target_profile_dir=profile_dir,project_id=project_id,run_id=run_id,required_views=required_views,style_images=style_images)
    refs=[_artifact_ref(prior/name) for name in ('input-binding.json','extraction.json','plan-2d-0.json')]
    binding=json.loads(Path(refs[0]['path']).read_text(encoding='utf-8'))
    if cycle_ledger_path is not None and binding.get('source_decoder_sha256')!=hashlib.sha256(Path(__file__).with_name('source_vectors.py').read_bytes()).hexdigest():
        raise DrawingCycleError('A changed or untracked source decoder needs a separately reserved recompile/check cycle, not a hidden correction')
    _,_,old_profile_hash,_=_bound_profile(origin_profile_dir,style_images)
    expected_views=[IndexedView.model_validate(item) for item in required_views]
    if (binding['project_id'],binding['run_id'],binding['source_set_sha256'],binding['profile_sha256'])!=(
            project_id,run_id,_source_identity(documents),old_profile_hash) or binding['required_views']!=[item.model_dump() for item in expected_views]:
        raise ValueError('Existing2D plan belongs to another project/run/source/profile/scope')
    extraction=EvidenceExtraction.model_validate(checkpoint['extraction']);extraction.source_index.views=expected_views
    if content_hash(json.loads(Path(refs[1]['path']).read_text(encoding='utf-8')))!=content_hash(extraction.model_dump()):
        raise ValueError('Existing2D plan lost its protected extracted facts')
    plan=DrawingPlan.model_validate_json(Path(refs[2]['path']).read_text(encoding='utf-8'))
    if len(plan.views)!=len(expected_views) or {item.view_id for item in plan.views}!={item.id for item in expected_views}:
        raise ValueError('Existing2D plan does not cover the exact required views')
    old_artifacts=[]
    for view in expected_views:
        for extension in ('png','pdf','svg'):
            ident='2d-0-'+view.id+'.'+extension
            ref=_artifact_ref(prior/(hashlib.sha256(ident.encode()).hexdigest()[:20]+'.'+extension))
            old_artifacts.append({'artifact_id':ident,'view_id':view.id,**ref});refs.append(ref)
    request={'plan':plan.model_dump(),'plan_sha256':content_hash(plan.model_dump()),'prior_artifacts':old_artifacts,
        'pinned_files':refs,'finite_findings':json.loads(json.dumps(findings)),
        'source_set_sha256':_source_identity(documents),'origin_profile_sha256':old_profile_hash,
        'source_decoder_sha256':hashlib.sha256(Path(__file__).with_name('source_vectors.py').read_bytes()).hexdigest(),
        'native_plans_generated_by_api':0,'review_passes_transferred':0}
    return run_api_drawing_workflow(gateway,documents,output_dir,profile_dir,instruction,project_id=project_id,run_id=run_id,
        style_images=style_images,required_views=required_views,budget=budget or CallBudget(max_calls=2),progress=progress,
        on_event=on_event,stop_after='2d',extraction_checkpoint=checkpoint,_corrective_context=request,cycle_ledger_path=cycle_ledger_path)


def run_api_drawing_workflow(gateway, documents, output_dir, profile_dir, instruction, *, project_id, run_id,
                            style_images=None, required_views=None, geometry_view_ids=None, budget=None,
                            progress=None, on_event=None, stop_after='2d',extraction_checkpoint=None,_corrective_context=None,cycle_ledger_path=None):
    output_dir=Path(output_dir).resolve();output_dir.mkdir(parents=True,exist_ok=True)
    if stop_after not in ('2d','3d'):raise ValueError('Choose an explicit supported stop stage')
    budget=budget or CallBudget(max_calls=5 if stop_after=='2d' else 9)
    cycles=None
    try:
        profile,_,_,_=load_profile(profile_dir)
        policy=profile.get('group_cycle_policy',{})
        if policy and (policy.get('max_cycles')!=MAX_GROUP_CYCLES or not policy.get('require_persistent_ledger')):
            raise DrawingCycleError('Guarded profiles must use the fixed TWO-cycle persistent group policy')
        if policy.get('require_persistent_ledger') and cycle_ledger_path is None:
            raise DrawingCycleError('A canonical project-level cycle_ledger_path is required before any request')
        if cycle_ledger_path is not None:
            if Path(cycle_ledger_path).resolve().is_relative_to(output_dir):
                raise DrawingCycleError('The persistent project cycle ledger must be outside the run output directory')
            cycles=DrawingCycleBudget(cycle_ledger_path,project_id=project_id,documents=documents,required_views=required_views)
            snapshot=cycles.snapshot()
            if not snapshot['can_start_drawing']:
                raise DrawingCycleError('The group is exhausted or awaiting its current check; no extraction or drawing request is permitted')
        return _run_api_drawing_workflow(gateway,documents,output_dir,profile_dir,instruction,
            project_id=project_id,run_id=run_id,style_images=style_images,required_views=required_views,
            geometry_view_ids=geometry_view_ids,budget=budget,progress=progress,on_event=on_event,stop_after=stop_after,
            extraction_checkpoint=extraction_checkpoint,corrective_context=_corrective_context,cycles=cycles)
    except Exception as error:
        cycle_state=None
        if cycles is not None:
            try:
                state=cycles.snapshot()['latest_cycle']
                if state and state['lease_id']==cycles.active_lease_id and state['state'] in ('reserved','candidate_ready'):
                    cycles.note_failure(cycles.active_lease_id,phase='workflow',category=getattr(error,'category','local_gate'))
                cycle_state=cycles.snapshot()
            except (DrawingCycleError,OSError):
                cycle_state={'status':'ledger_invalid_or_unavailable','can_start_3d':False,'max_cycles':MAX_GROUP_CYCLES,
                    'group_key':cycles.group_key,'ledger_path':str(cycles.path)}
        details=getattr(error,'validation_errors',[])
        failure={'status':'FAILED_NOT_ACCEPTED','category':getattr(error,'category','local_gate'),
                 'error_type':type(error).__name__,'calls_used':budget.used,'can_apply':False,
                 'validation_errors':[{'loc':item.get('loc',[]),'type':item.get('type','invalid_model')} for item in details]}
        if cycles is not None:failure['group_cycles']=cycle_state
        (output_dir/'failure.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
        raise


def _run_api_drawing_workflow(gateway, documents, output_dir, profile_dir, instruction, *, project_id, run_id,
                            style_images, required_views, geometry_view_ids, budget, progress, on_event,stop_after,extraction_checkpoint,corrective_context,cycles):
    """Bounded experiment; reviews are sidecars and never imported across stages/runs."""
    profile,prompts,profile_hash,profile_paths=load_profile(profile_dir)
    for target in ('2d','3d'):
        if any(not profile.get('rule_catalog',{}).get(ident,{}).get('criterion') for ident in profile['review_rules'][target]):
            raise ValueError('Review profile omits an applicable rule definition')
    if not required_views:raise ValueError('An independently established required source-view manifest is mandatory')
    required=[IndexedView.model_validate(view) for view in required_views]
    if len({view.id for view in required})!=len(required):raise ValueError('Duplicate required source view')
    gateway._check_index(SourceIndex(project_name='Required source scope',views=required,warnings=[]),documents)
    active={view.id for view in required if view.kind in ('plan','elevation')}
    geometry_view_ids=list(geometry_view_ids) if geometry_view_ids is not None else sorted(active)
    if not geometry_view_ids or len(set(geometry_view_ids))!=len(geometry_view_ids) or set(geometry_view_ids)-active:
        raise ValueError('3D view subset must be explicit unique members of the required source views')
    source_hash=_source_identity(documents);budget=budget or CallBudget();output_dir=Path(output_dir).resolve()
    output_dir.mkdir(parents=True,exist_ok=True);usage=[];reports=[];artifacts=[]
    profile_snapshot={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in profile_paths}
    style_snapshot={};artifact_seals=[];phase_calls={}
    if corrective_context is not None:
        if stop_after!='2d' or corrective_context['source_set_sha256']!=source_hash or corrective_context['review_passes_transferred']!=0:
            raise ValueError('Corrective native patch has a different source or attempts to transfer acceptance')
        artifact_seals.extend((item['path'],item['sha256']) for item in corrective_context['pinned_files'])
        artifact_seals.append((str(Path(__file__).with_name('source_vectors.py')),corrective_context['source_decoder_sha256']))
    active_cycle=None
    def persist(name,value):
        if cycles is not None and isinstance(value,dict) and name in ('workflow-receipt.json','phase-state.json'):
            value={**value,'group_cycles':cycles.snapshot()}
        (output_dir/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    def unchanged():
        if _source_identity(documents)!=source_hash or any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=value for p,value in profile_snapshot.items()):
            raise ValueError('Source or profile changed during a request')
        if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=value for p,value in [*style_snapshot.items(),*artifact_seals]):
            raise ValueError('A pinned style reference or rendered artifact changed during a request')
    def call(schema,phase,content):
        nonlocal active_cycle
        unchanged()
        phase_calls[phase]=phase_calls.get(phase,0)+1
        if phase_calls[phase]>profile['phase_call_caps'][phase]:raise ValueError('Phase request cap exhausted')
        if cycles is not None and phase in ('create_3d','check_3d','repair_3d'):
            current=cycles.snapshot()
            if (not current['can_start_3d'] or active_cycle is None or current['latest_cycle']['lease_id']!=active_cycle['lease_id']
                    or current['latest_cycle']['review']['candidate_sha256']!=accepted_2d['candidate_sha256']):
                raise DrawingCycleError('3D requires the current complete2D group to retain its bound accepted review')
        if budget.used>=budget.max_calls:raise ValueError('Actual request budget exhausted; no automatic retry is authorized')
        if cycles is not None and phase in ('create_2d','repair_2d','corrective_2d'):
            active_cycle=cycles.reserve(phase,{'run_id':run_id,'profile_sha256':profile_hash,'output_dir':str(output_dir)})
        budget.reserve();persist('phase-state.json',{'phase':phase,'status':'REQUEST_RESERVED','calls_used':budget.used,
            'source_set_sha256':source_hash,'profile_sha256':profile_hash,'phase_calls':phase_calls})
        try:
            value,run=gateway._request(schema,BOUNDARY+prompts[phase],content,progress=progress)
        except Exception as error:
            if getattr(error,'usage',None):usage.append({**error.usage,'kind':phase,'failed':True})
            persist('usage.json',usage)
            unchanged();raise
        usage.append({**run,'kind':phase});persist('usage.json',usage)
        value=schema.model_validate(value.model_dump() if isinstance(value,BaseModel) else value)
        persist(f'typed-response-{budget.used:02d}-{phase}.json',value.model_dump())
        unchanged();return value
    def text(value):return {'type':'input_text','text':json.dumps(value,ensure_ascii=False)}
    source_inputs=gateway._document_inputs(documents)
    style_content=[]
    for item in style_images or []:
        if item.get('role')!='style_only':raise ValueError('Only explicitly style-only reference images are permitted')
        raw=Path(item['path']).read_bytes()
        if item.get('sha256')!=hashlib.sha256(raw).hexdigest():raise ValueError('Style reference bytes differ from their pin')
        style_snapshot[str(item['path'])]=item['sha256']
        style_content += [text({'style_reference_id':item['id'],'authority':'style only; no geometry/dimensions/source facts'}),_image(raw)]
    profile_hash=content_hash({'profile':profile_hash,'style_references':style_snapshot})
    persist('input-binding.json',{'project_id':project_id,'run_id':run_id,'source_set_sha256':source_hash,
        'profile_sha256':profile_hash,'required_views':[view.model_dump() for view in required],
        'geometry_view_ids':geometry_view_ids,'style_reference_hashes':style_snapshot,
        'source_decoder_sha256':hashlib.sha256(Path(__file__).with_name('source_vectors.py').read_bytes()).hexdigest()})
    if extraction_checkpoint is not None:
        if isinstance(extraction_checkpoint,(str,Path)):
            extraction_checkpoint=json.loads(Path(extraction_checkpoint).read_text(encoding='utf-8'))
        extraction=validate_extraction_checkpoint(extraction_checkpoint,documents=documents,project_id=project_id,
            run_id=run_id,profile_sha256=profile_hash,required_views=[view.model_dump() for view in required])
        persist('extraction-resume.json',{'checkpoint_sha256':extraction_checkpoint['checkpoint_sha256'],
            'source_set_sha256':source_hash,'profile_sha256':profile_hash,'reused_extraction':True,
            'review_passes_transferred':0,'new_extraction_calls':0})
    else:
        extraction=call(EvidenceExtraction,'extract',[text({'instruction':instruction,'stage':'source evidence only; no3D construction',
            'independently_required_views':[view.model_dump() for view in required]}),*source_inputs])
    extraction=EvidenceExtraction.model_validate(extraction.model_dump());gateway._check_index(extraction.source_index,documents)
    actual={view.id:(view.document_id,view.page,view.kind) for view in extraction.source_index.views}
    expected={view.id:(view.document_id,view.page,view.kind) for view in required}
    if actual!=expected or len(extraction.source_index.views)!=len(required):raise ValueError('Extractor omitted,duplicated or added a required source view')
    # Crop authority is the independently inspected displayed-page manifest.
    extraction.source_index.views=[view.model_copy(deep=True) for view in required]
    skeleton=evidence_model(extraction,documents)
    persist('extraction.json',extraction.model_dump());persist('evidence-owner-skeleton.json',skeleton.model_dump())
    if len(skeleton.views)>profile['max_views']:raise ValueError('Selected scope exceeds the explicit view cap')
    inventory=build_inventory(documents,extraction.source_index)
    if not inventory['views']:raise ValueError('Selected source has no supported native vector views')
    source_crop_manifest=[];source_crop_images={}
    for view in extraction.source_index.views:
        if view.id not in active:continue
        raw=_source_crops(documents,[view])[view.id]
        path=output_dir/('source-'+hashlib.sha256(view.id.encode()).hexdigest()[:20]+'.png');path.write_bytes(raw)
        item={'source_crop_id':'original-source:'+view.id,'view_id':view.id,'document_id':view.document_id,
              'page':view.page,'region':view.region,**_artifact_ref(path)}
        source_crop_manifest.append(item);source_crop_images[view.id]=raw;artifact_seals.append((item['path'],item['sha256']))
    persist('source-crops.json',source_crop_manifest)
    def crop_content(view_ids):
        selected=set(view_ids)
        if 'AXON' in selected:selected|=active
        return [block for item in source_crop_manifest if item['view_id'] in selected for block in
                (text({**{key:value for key,value in item.items() if key!='path'},'authority':'ORIGINAL SOURCE; normalized display crop, not a generated output'}),
                 _image(source_crop_images[item['view_id']]))]
    context={'instruction':instruction,'extraction':extraction.model_dump(),'native_inventory':compact_inventory(inventory,path_limit=400,per_view_limit=150)}
    if corrective_context is None:
        plan=call(DrawingPlan,'create_2d',[text(context),*source_inputs,*crop_content(active),*style_content])
    else:
        plan=DrawingPlan.model_validate(corrective_context['plan'])
        if content_hash(plan.model_dump())!=corrective_context['plan_sha256']:raise ValueError('Corrective base plan changed')
        _,base_drawings=_native_2d_candidate(documents,extraction,plan,inventory)
        base_hashes=[drawing_hash(view) for view in base_drawings];base_plan_hash=content_hash(plan.model_dump())
        base_artifacts=[];recompiled=[]
        old_artifacts={item['artifact_id']:item for item in corrective_context['prior_artifacts']}
        for view in base_drawings:
            for extension,raw in [('png',render_png(view)),('pdf',render_pdf(view)),('svg',render_svg(view).encode())]:
                ident='2d-0-'+view.id+'.'+extension
                path=output_dir/('base-'+hashlib.sha256(ident.encode()).hexdigest()[:20]+'.'+extension);path.write_bytes(raw)
                item={'artifact_id':'recompiled-base:'+ident,'view_id':view.id,**_artifact_ref(path)}
                base_artifacts.append(item);artifact_seals.append((item['path'],item['sha256']))
                recompiled.append({'view_id':view.id,'format':extension,'old_sha256':old_artifacts[ident]['sha256'],
                    'recompiled_sha256':item['sha256'],'identical':old_artifacts[ident]['sha256']==item['sha256']})
        if cycles is not None:
            current=cycles.snapshot();base_digest=content_hash({'inventory':inventory_identity(inventory),'plan':plan.model_dump()})
            if (not current['latest_cycle'] or current['latest_cycle']['candidate_sha256']!=base_digest
                    or any(not item['identical'] for item in recompiled)):
                raise DrawingCycleError('A correction must start from the last tracked unchanged candidate; an untracked recompile/update cannot be hidden in this cycle')
        persist('source-decoder-upgrade.json',{'source_set_sha256':source_hash,'origin_profile_sha256':corrective_context['origin_profile_sha256'],
            'current_profile_sha256':profile_hash,'source_decoder_sha256':corrective_context['source_decoder_sha256'],
            'unchanged_plan_sha256':base_plan_hash,'protected_extraction_sha256':content_hash(extraction.model_dump()),
            'exports':recompiled,'review_passes_transferred':0,'base_not_accepted':True})
        persist('corrective-base-plan.json',plan.model_dump())
        persist('finite-correction-findings.json',corrective_context['finite_findings'])
        patch_context={'instruction':instruction,'requested_view_ids':[view.id for view in base_drawings],
            'extracted_facts':extraction.model_dump(),'native_inventory':compact_inventory(inventory,path_limit=0,per_view_limit=0),
            'finite_findings':corrective_context['finite_findings'],
            'base_views':[{'view_id':view.view_id,'default_include':view.default_include,'default_owner_id':view.default_owner_id,
                'existing_rule_count':len(view.rules),'pending':view.pending} for view in plan.views],
            'contract':'Return ONLY additional selection/role/owner rules, max12 per view/max8 IDs per rule. Exact requested views once. source_region=null; edit_guards=[]; preserve established dimensions, material names/leaders, operation marks and real fixtures. No old-rule copies, full-plan recreation, text/geometry amendments, source facts or crop changes.'}
        patch=call(CorrectiveNativeRepairs,'corrective_2d',[text(patch_context),*source_inputs,*crop_content(active),*style_content,
            *[block for item in base_artifacts if item['path'].endswith('.png') for block in
                (text({'recompiled_base_artifact_id':item['artifact_id'],'view_id':item['view_id'],'authority':'UNACCEPTED CURRENT RENDER; source decoder corrected, old source plan unchanged'}),_image(Path(item['path']).read_bytes()))]])
        if content_hash(plan.model_dump())!=base_plan_hash or [drawing_hash(view) for view in base_drawings]!=base_hashes:
            raise ValueError('Corrective base candidate changed during request')
        if len(patch.views)!=len(base_drawings) or {item.view_id for item in patch.views}!={view.id for view in base_drawings}:
            raise ValueError('Corrective patch must cover exactly every requested source view')
        updated=plan.model_copy(deep=True);decisions={item.view_id:item for item in updated.views}
        for item in patch.views:
            decision=decisions[item.view_id]
            decision.rules.extend(DrawingRule.model_validate(rule.model_dump()) for rule in item.rules)
            decision.pending=list(dict.fromkeys([*decision.pending,*item.pending]))
        _,corrected=_native_2d_candidate(documents,extraction,updated,inventory)
        def protected(view):
            texts={};paths=set()
            for primitive in view.primitives:
                if primitive.role not in ('dimension','opening','material'):continue
                if primitive.kind=='text':texts[primitive.id]=primitive.model_dump()
                else:
                    paths.update((primitive.role,primitive.owner_id,ident) for ident in
                        (primitive.source_ids or [primitive.source_id]))
            return texts,paths
        for old,new in zip(base_drawings,corrected):
            old_text,old_paths=protected(old);new_text,new_paths=protected(new)
            if any(new_text.get(ident)!=value for ident,value in old_text.items()) or not old_paths<=new_paths:
                raise ValueError('A bounded visual correction changed a protected dimension,opening mark or material annotation')
        plan=updated;persist('corrective-patch.json',patch.model_dump())
    def store(ident,raw,extension,view_id):
        name=hashlib.sha256(ident.encode()).hexdigest()[:20]+'.'+extension
        path=output_dir/name;path.write_bytes(raw)
        item={'artifact_id':ident,'view_id':view_id,'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()};artifacts.append(item);artifact_seals.append((str(path),item['sha256']));return item
    def review(target,candidate_hash,views,rendered,extra,candidate_guard,additional_images=()):
        manifest=[{'artifact_id':item['artifact_id'],'view_id':item['view_id'],'sha256':item['sha256']} for item in rendered]
        bindings=ReviewBindings(project_id=project_id,run_id=run_id,source_set_sha256=source_hash,
            candidate_sha256=candidate_hash,artifacts_sha256=content_hash(manifest),profile_sha256=profile_hash)
        body={'bindings':bindings.model_dump(),'requested_view_ids':views,'required_rule_ids':profile['review_rules'][target],
              'rule_catalog':{ident:profile['rule_catalog'][ident] for ident in profile['review_rules'][target]},
              'source_crops':[{key:value for key,value in item.items() if key!='path'} for item in source_crop_manifest if item['view_id'] in views or 'AXON' in views],
              'extracted_facts':extraction.model_dump(),'artifacts':manifest,**extra}
        content=[text(body),*source_inputs,*crop_content(views),*style_content]
        for item in rendered:
            if item['path'].endswith('.png'):content += [text({'artifact_id':item['artifact_id']}),_image(Path(item['path']).read_bytes())]
        for item in additional_images:content += [text({'accepted_2d_artifact_id':item['artifact_id']}),_image(Path(item['path']).read_bytes())]
        before=content_hash(extra);candidate_before=candidate_guard()
        report=call(ReviewReport,'check_'+target,content)
        if content_hash(extra)!=before or candidate_guard()!=candidate_before or any(hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()!=item['sha256'] for item in rendered):
            raise ValueError('Candidate or actual rendered artifact changed during review')
        report_number=len(reports)+1
        persist('review-'+target+'-'+str(report_number)+'.json',report.model_dump())
        try:
            accepted=validate_review(report,bindings,target,views,profile['review_rules'][target],documents,
                {item['artifact_id'] for item in rendered},{owner.id for owner in extraction.owners},
                {parameter.id for parameter in extraction.parameters},
                {ident:{item['artifact_id'] for item in rendered if item['view_id']==ident} for ident in views})
        except ValueError as error:
            summary={'event':'summary_after_check','target':target,'verdict':report.verdict,
                'report_sha256':content_hash(report.model_dump()),'finding_ids':[finding.id for finding in report.findings],
                'accepted_by_local_gates':False,'next':'hold_invalid_review_contract','error_type':type(error).__name__,
                'lesson_status':'SKIP','lesson_reason':'Unaccepted review retained; no finding remapping or prior pass transfer.'}
            persist('summary-'+target+'-'+str(report_number)+'.json',summary)
            if on_event:on_event(dict(summary))
            raise
        reports.append(report.model_dump());persist('review-'+target+'-'+str(len(reports))+'.json',report.model_dump())
        if target=='2d' and cycles is not None:
            if active_cycle is None:raise DrawingCycleError('The candidate has no persistent drawing-cycle reservation')
            cycles.note_review(active_cycle['lease_id'],candidate_sha256=candidate_hash,
                artifacts_sha256=bindings.artifacts_sha256,report_sha256=content_hash(report.model_dump()),
                verdict=report.verdict,accepted=accepted)
        summary={'event':'summary_after_check','target':target,'verdict':report.verdict,
                 'report_sha256':content_hash(report.model_dump()),'finding_ids':[f.id for f in report.findings],
                 'accepted_by_local_gates':accepted,'next':'next_stage' if accepted else 'one_bounded_repair_or_hold',
                 'lesson_status':'SKIP','lesson_reason':'Run-local findings recorded; no verified reusable skill changes authorized here.'}
        persist('summary-'+target+'-'+str(len(reports))+'.json',summary)
        if on_event:on_event(dict(summary))
        return accepted,report
    drawings=[]
    for attempt in range(1 if corrective_context is not None else 2):
        plan=DrawingPlan.model_validate(plan.model_dump())
        _,drawings=_native_2d_candidate(documents,extraction,plan,inventory)
        persist('plan-2d-'+str(attempt)+'.json',plan.model_dump())
        rendered=[]
        for view in drawings:
            prefix='2d-'+str(attempt)+'-'+view.id
            rendered += [store(prefix+'.png',render_png(view),'png',view.id),store(prefix+'.pdf',render_pdf(view),'pdf',view.id),store(prefix+'.svg',render_svg(view).encode(),'svg',view.id)]
        digest=content_hash({'inventory':inventory_identity(inventory),'plan':plan.model_dump()})
        if cycles is not None:
            if active_cycle is None:raise DrawingCycleError('The native candidate has no drawing-cycle reservation')
            cycles.mark_candidate(active_cycle['lease_id'],digest)
        accepted,report=review('2d',digest,[view.id for view in drawings],rendered,
            {'actual_native_views':[{'view_id':view.id,'owner_ids':view.owner_ids,'primitive_count':len(view.primitives)} for view in drawings]},
            lambda:content_hash({'plan':plan.model_dump(),'drawings':[drawing_hash(view) for view in drawings]}))
        if accepted:break
        if report.verdict!='REVISE' or attempt==1 or corrective_context is not None or (cycles is not None and not cycles.snapshot()['can_start_drawing']):
            persist('workflow-receipt.json',{'status':'2d_needs_review','source_set_sha256':source_hash,'profile_sha256':profile_hash,
                'reports':reports,'calls_used':budget.used,'stopped_after':'2d','3d_requested':False,'can_apply':False})
            return {'status':'2d_needs_review','extraction':extraction,'drawings_2d':drawings,'evidence_model':skeleton,
                'drawing_plan':plan,'model_3d':None,'scene_3d':None,'reports':reports,'usage':usage,'artifacts':artifacts,'calls_used':budget.used,'can_apply':False}
        plan=call(DrawingPlan,'repair_2d',[text({**context,'previous_plan':plan.model_dump(),'review':report.model_dump(),
            'rule_catalog':{ident:profile['rule_catalog'][ident] for ident in profile['review_rules']['2d']}}),*source_inputs,*crop_content(active),*style_content,
            *[block for item in rendered if item['path'].endswith('.png') for block in (text({'actual_artifact_id':item['artifact_id']}),_image(Path(item['path']).read_bytes()))]])
    accepted_2d={'candidate_sha256':digest,'drawing_hashes':{view.id:drawing_hash(view) for view in drawings},'review_bindings':report.bindings.model_dump()}
    if stop_after=='2d':
        status='2d_accepted_with_limits' if report.verdict=='PASS_WITH_LIMITS' else '2d_accepted'
        persist('workflow-receipt.json',{'status':status,'source_set_sha256':source_hash,'profile_sha256':profile_hash,
            'accepted_2d':accepted_2d,'reports':reports,'usage':usage,'calls_used':budget.used,
            'stopped_after':'2d','3d_requested':False,'can_apply':False})
        return {'status':status,'extraction':extraction,'drawings_2d':drawings,'evidence_model':skeleton,
            'drawing_plan':plan,'model_3d':None,'scene_3d':None,'reports':reports,'usage':usage,
            'artifacts':artifacts,'calls_used':budget.used,'can_apply':False}
    geometry_context={'instruction':instruction,'extraction':extraction.model_dump(),'accepted_2d':accepted_2d,
                      'drawing_plan':plan.model_dump(),'protected_source_facts':extraction.parameters and [p.model_dump() for p in extraction.parameters]}
    geometry_images=[item for item in rendered if item['path'].endswith('.png')]
    model=call(StudioModel,'create_3d',[text(geometry_context),text({'canonical_contract':MODEL_PROMPT}),*source_inputs,
        *[block for item in geometry_images for block in (text({'artifact_id':item['artifact_id']}),_image(Path(item['path']).read_bytes()))]])
    scene=None
    for attempt in range(2):
        model=validate_geometry_candidate(model,extraction,documents);scene=build_scene(model,project_id,1)
        persist('model-3d-'+str(attempt)+'.json',model.model_dump())
        scope=scene
        if not scope['meshes']:
            frames=[frame for frame in scene.get('local_frames',{}).values() if frame['meshes']]
            if not frames:raise ValueError('3D has no known world or local assembly geometry')
            scope=max(frames,key=lambda frame:len(frame['meshes']))
        rendered=[];view_ids=[]
        cameras=[('AXON',[.707106781,-.707106781,0.],[.40824829,.40824829,.81649658])]
        cameras += [(view.id,view.right,view.up) for view in model.views if view.id in geometry_view_ids]
        for ident,right,up in cameras:
            if ident in view_ids:raise ValueError('Duplicate3D review camera identity')
            view_ids.append(ident);rendered.append(store('3d-'+str(attempt)+'-'+ident+'.png',render_scene_png(scope,right,up,ident),'png',ident))
        digest=content_hash(model.model_dump());frozen=model.model_dump_json()
        accepted,report=review('3d',digest,view_ids,rendered,{'candidate_model':model.model_dump(exclude={'warnings'}),'accepted_2d':accepted_2d,
             'render_scope':'world' if scope is scene else 'explicit local assembly; global placement remains TBC',
             'pending_geometry':scene['pending']},lambda:content_hash(model.model_dump()),geometry_images)
        if model.model_dump_json()!=frozen:raise ValueError('3D model changed during review')
        if accepted:break
        if report.verdict!='REVISE' or attempt==1:return {'status':'3d_needs_review','extraction':extraction,'drawings_2d':drawings,'model_3d':model,'scene_3d':scene,'reports':reports,'usage':usage,'artifacts':artifacts,'calls_used':budget.used,'can_apply':False}
        model=call(StudioModel,'repair_3d',[text({**geometry_context,'candidate_model':model.model_dump(),'review':report.model_dump()}),*source_inputs,
            *[block for item in rendered for block in (text({'artifact_id':item['artifact_id']}),_image(Path(item['path']).read_bytes()))]])
    result={'status':'accepted_with_limits' if any(r['verdict']=='PASS_WITH_LIMITS' for r in reports) else 'accepted_experimental',
        'extraction':extraction,'drawings_2d':drawings,'model_3d':model,'scene_3d':scene,'reports':reports,'usage':usage,
        'artifacts':artifacts,'calls_used':budget.used,'can_apply':False}
    (output_dir/'workflow-receipt.json').write_text(json.dumps({'status':result['status'],'source_set_sha256':source_hash,
        'profile_sha256':profile_hash,'accepted_2d':accepted_2d,'candidate_3d_sha256':content_hash(model.model_dump()),
        'reports':reports,'usage':usage,'calls_used':budget.used,'can_apply':False},ensure_ascii=False,indent=2),encoding='utf-8')
    return result
