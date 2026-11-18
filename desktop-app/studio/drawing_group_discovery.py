"""Discover independent room/assembly drawing scopes from the imported originals."""
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .ai import AIError, BOUNDARY, IndexedView, SourceIndex, StudioAIGateway
from .api_drawing_workflow import _source_identity, content_hash
from .autonomous_2d import AutonomousIndexedView, MAX_VIEWS, _page_atlas, _sha, _text
from .drawing_workflow import _image

MAX_DRAWING_GROUPS = 4
PageDirection = Literal['page-up', 'page-down', 'page-left', 'page-right']
NormalizedCoordinate = Annotated[float, Field(ge=0, le=1)]
PagePoint = Annotated[list[NormalizedCoordinate], Field(min_length=2, max_length=2)]
PageRegion = Annotated[list[NormalizedCoordinate], Field(min_length=4, max_length=4)]


class _MappedView(AutonomousIndexedView):
    sheet: str | None = Field(max_length=40)
    view_number: str | None = Field(max_length=40)
    callout: str | None = Field(max_length=80)
    plan_view_id: str | None = Field(max_length=80)
    callout_point: PagePoint | None
    sight_direction: PageDirection | None
    correspondence_note: str = Field(max_length=600)


class _MappedGroup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str = Field(min_length=1, max_length=120)
    views: list[_MappedView] = Field(min_length=2, max_length=MAX_VIEWS)


class DrawingGroupDiscovery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    outcome: Literal['complete', 'unsupported', 'over_limit']
    groups: list[_MappedGroup] = Field(max_length=MAX_DRAWING_GROUPS)


class DrawingGroupSourceView(BaseModel):
    model_config = ConfigDict(extra='forbid')
    view_id: str
    label: str
    kind: Literal['plan', 'elevation']
    document_id: str
    source_name: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    page: int
    region: PageRegion
    sheet: str | None
    view_number: str | None
    callout: str | None
    plan_view_id: str | None
    callout_point: PagePoint | None
    sight_direction: PageDirection | None
    correspondence_note: str


class DrawingGroup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^G_[a-f0-9]{20}$')
    label: str = Field(min_length=1, max_length=120)
    index: SourceIndex
    instruction: str = Field(min_length=1, max_length=8000)
    source_views: list[DrawingGroupSourceView] = Field(min_length=2, max_length=MAX_VIEWS)


def _source_views(mapped, namespaced, documents_by_id):
    plans = {view.id: view for view in mapped.views if view.kind == 'plan'}
    records = []
    for view in mapped.views:
        document = documents_by_id[view.document_id]
        plan = plans.get(view.plan_view_id)
        point, direction, callout = view.callout_point, view.sight_direction, view.callout
        note = view.correspondence_note
        if view.kind == 'plan':
            plan = point = direction = callout = None
        elif (not plan or not callout or not view.sheet or not view.view_number
                or ''.join(callout.split()).casefold() != f'{view.view_number}/{view.sheet}'.casefold()):
            plan = point = direction = callout = None
            note = 'The source plan callout could not be linked to this numbered elevation.'
        elif point is not None and not (plan.region[0] <= point[0] <= plan.region[2] and plan.region[1] <= point[1] <= plan.region[3]):
            point = direction = None
            note = 'The proposed marker is outside the mapped source plan region.'
        records.append(DrawingGroupSourceView(view_id=namespaced[view.id], label=view.label, kind=view.kind,
            document_id=view.document_id, source_name=document.get('original_name') or document.get('name') or Path(document['local_path']).name,
            source_sha256=document['sha256'], page=view.page, region=view.region, sheet=view.sheet, view_number=view.view_number,
            callout=callout, plan_view_id=namespaced[plan.id] if plan else None,
            callout_point=point, sight_direction=direction, correspondence_note=note))
    return records


def _normalize_groups(mapping, documents, instruction):
    if mapping.outcome == 'over_limit':
        raise AIError('More than four complete drawing groups were found. Select a smaller drawing scope.', 'input')
    if mapping.outcome != 'complete' or not mapping.groups:
        raise AIError('A complete set of separate original-source plans and elevations could not be identified.', 'invalid_output')
    by_id = {doc['id']: doc for doc in documents}
    document_order = {doc['id']: position for position, doc in enumerate(documents)}
    group_ids = set()
    labels = set()
    elevations = set()
    elevation_numbers = set()
    ordered = []
    for mapped in mapping.groups:
        label = ' '.join(mapped.label.split())
        if not label or label.casefold() in labels:
            raise AIError('The source map contains blank or duplicate drawing-group names.', 'invalid_output')
        labels.add(label.casefold())
        views = [IndexedView.model_validate(view.model_dump(include=set(IndexedView.model_fields))) for view in mapped.views]
        index = SourceIndex(project_name=label, views=views, warnings=[])
        StudioAIGateway._check_index(index, documents)
        if {view.kind for view in index.views} != {'plan', 'elevation'} or any(view.region is None for view in index.views):
            raise AIError('Every drawing group needs its own supported plan and numbered elevation regions.', 'invalid_output')
        source_frames = [(by_id[view.document_id]['sha256'], view.page, tuple(view.region), view.kind) for view in index.views]
        if len(set(source_frames)) != len(source_frames):
            raise AIError('The source map repeats an original view inside one drawing group.', 'invalid_output')
        group_elevations = {frame for frame in source_frames if frame[-1] == 'elevation'}
        if elevations & group_elevations:
            raise AIError('The same original elevation was assigned to multiple drawing groups.', 'invalid_output')
        elevations.update(group_elevations)
        for view in mapped.views:
            if view.kind == 'elevation' and view.sheet and view.view_number:
                number = (by_id[view.document_id]['sha256'], view.sheet.casefold(), view.view_number.casefold())
                if number in elevation_numbers:
                    raise AIError('The same numbered source elevation was mapped more than once.', 'invalid_output')
                elevation_numbers.add(number)
        group_id = 'G_' + content_hash(sorted(source_frames))[:20]
        if group_id in group_ids:
            raise AIError('The source map repeats the same drawing group.', 'invalid_output')
        group_ids.add(group_id)
        namespaced = {view.id: f'{group_id}_V{position:02d}' for position, view in enumerate(index.views, 1)}
        source_views = _source_views(mapped, namespaced, by_id)
        index.views = [view.model_copy(update={'id': namespaced[view.id],
            'plan_reference': namespaced.get(view.plan_reference, view.plan_reference)}) for view in index.views]
        captions = [{'source_page': view.page, 'sheet': view.sheet, 'view_number': view.view_number,
            'caption': view.label, 'callout': view.callout, 'sight_direction': view.sight_direction} for view in source_views]
        scope = (_text({'selected_drawing_group': label, 'original_source_captions': captions})['text']
            + '\nVerify and draw only this complete group. Its names and captions are original-source evidence.')
        group_instruction = f'{instruction}\n\n{scope}' if instruction else scope
        if len(group_instruction) > 8000:
            raise AIError('The drawing instruction and original view captions exceed the supported length.', 'input')
        sheet_order = min((document_order[view.document_id], view.page, view.region[1], view.region[0])
            for view in index.views if view.kind == 'elevation')
        ordered.append((sheet_order, DrawingGroup(id=group_id, label=label, index=index,
            instruction=group_instruction, source_views=source_views)))
    return [group for _, group in sorted(ordered, key=lambda pair: (pair[0], pair[1].id))]


def discover_drawing_groups(gateway, documents, output, *, instruction='', check_control=None):
    """One typed app call. Every discovered crop still needs independent scope verification."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    def control(*_):
        if check_control:
            check_control()

    control()
    source_hash = _source_identity(documents)
    original_files = gateway._document_inputs(documents)
    atlas = _page_atlas(documents, output, control)
    atlas_manifest = [{key: value for key, value in item.items() if key != 'image_path'} for item in atlas]
    content = [_text({'instruction': instruction, 'source_set_sha256': source_hash,
        'page_atlas': atlas_manifest, 'max_groups': MAX_DRAWING_GROUPS, 'max_views_per_group': MAX_VIEWS}), *original_files]
    for page in atlas:
        control()
        content.extend([_text({'document_id': page['document_id'], 'original_page': page['page']}),
            _image(Path(page['image_path']).read_bytes())])
    prompt = Path(__file__).with_name('prompts') / 'autonomous_2d_groups.md'
    prompt_hash = _sha(prompt)
    answer, usage = gateway._request(DrawingGroupDiscovery, BOUNDARY + prompt.read_text(encoding='utf-8'), content, progress=control)
    control()
    if (_source_identity(documents) != source_hash or _sha(prompt) != prompt_hash
            or any(_sha(page['image_path']) != page['image_sha256'] for page in atlas)):
        raise AIError('Original source or discovery evidence changed during the drawing-group map.', 'invalid_output')
    mapping = DrawingGroupDiscovery.model_validate(answer)
    groups = _normalize_groups(mapping, documents, instruction)
    page_geometry = [{key: page[key] for key in ('document_id', 'page', 'width', 'height', 'rotation', 'image_sha256')}
        for page in atlas_manifest]
    coordinates = {'extent': 'full displayed PDF page', 'origin': 'top-left', 'x_positive': 'page-right',
        'y_positive': 'page-down', 'unit': 'normalized 0–1', 'region_order': ['left', 'top', 'right', 'bottom'],
        'point_order': ['x', 'y'], 'page_dimension_unit': 'PDF points'}
    record = _text({'schema': 'formtopart-drawing-group-discovery/1', 'source_set_sha256': source_hash,
        'coordinates': coordinates, 'page_geometry': page_geometry,
        'groups': [group.model_dump() for group in groups], 'usage': usage})['text']
    (output / 'drawing-groups.json').write_text(record + '\n', encoding='utf-8')
    return groups
