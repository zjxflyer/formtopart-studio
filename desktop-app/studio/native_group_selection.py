"""Bound sparse source selection; classification cannot author drawing geometry."""
from __future__ import annotations

from collections.abc import Mapping
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .drawing_models import DrawingPlan, DrawingRule


Category = Literal['appearance_texture', 'physical_boundary', 'functional_fixture',
                   'operation_symbol', 'annotation', 'out_of_scope_context', 'uncertain']


class NativeGroupDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    group_id: str = Field(pattern=r'^G[0-9]{3,6}$')
    view_id: str = Field(min_length=1, max_length=80)
    action: Literal['retain', 'omit', 'review']
    category: Category
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator('view_id', 'reason')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Group decisions need nonblank view identity and evidence reason')
        return value


class NativeGroupSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    groups: list[NativeGroupDecision] = Field(min_length=1, max_length=512)

    @model_validator(mode='after')
    def unique_groups(self):
        ids = [group.group_id for group in self.groups]
        if len(ids) != len(set(ids)):
            raise ValueError('Every group decision must have a unique group ID')
        return self


class NativeGroupSelectionHold(ValueError):
    """The response is retained for review; no candidate changes are returned."""
    def __init__(self, groups):
        self.groups = groups
        super().__init__('Native group review required: ' + ', '.join(group.group_id for group in groups))


def _record(value):
    return value.model_dump() if isinstance(value, BaseModel) else value


def _catalog(catalog):
    if not isinstance(catalog, Mapping) or not isinstance(catalog.get('source_sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', catalog['source_sha256']):
        raise ValueError('Catalog needs the bound original source SHA256')
    groups = catalog.get('groups')
    if not isinstance(groups, list) or not 1 <= len(groups) <= 512:
        raise ValueError('Catalog needs one to 512 source groups')
    seen, membership = set(), {}
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get('group_id'), str) or not re.fullmatch(r'G[0-9]{3,6}', group['group_id']):
            raise ValueError('Catalog group IDs must be neutral G plus three to six digits')
        group_id, view_id, ids = group['group_id'], group.get('view_id'), group.get('native_ids')
        if group_id in seen or not isinstance(view_id, str) or not view_id.strip() or len(view_id) > 80:
            raise ValueError('Catalog group/view identities must be unique and nonblank')
        seen.add(group_id)
        if not isinstance(ids, list) or not ids or len(ids) > 60000 or any(not isinstance(i, str) or not i.strip() or len(i) > 180 or i.startswith('B_') for i in ids):
            raise ValueError('Catalog groups require actual unbatched native IDs, never compiled B_ IDs')
        if len(ids) != len(set(ids)):
            raise ValueError('A group cannot repeat a native primitive')
        occupied = membership.setdefault(view_id, set())
        if occupied.intersection(ids):
            raise ValueError('Native groups must be disjoint within a source view')
        occupied.update(ids)
    return groups


def neutral_group_metadata(catalog):
    """Small API packet; full native IDs and audit/answer labels stay host-local."""
    groups = _catalog(catalog)
    result = []
    for group in groups:
        ids = group['native_ids']
        examples = list(dict.fromkeys(ids[:3] + ids[-3:]))
        metadata = {'group_id': group['group_id'], 'view_id': group['view_id'],
                    'native_count': len(ids), 'source_id_examples': examples}
        for name in ('bbox', 'region'):
            if name in group:
                values = group[name]
                if not isinstance(values, list) or len(values) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in values) or values[0] > values[2] or values[1] > values[3]:
                    raise ValueError('Group spatial metadata must be a finite ordered numeric box')
                if name == 'region' and any(not 0 <= x <= 1 for x in values):
                    raise ValueError('Source regions use normalized coordinates')
                metadata[name] = list(values)
        if 'page' in group:
            if type(group['page']) is not int or group['page'] < 1:
                raise ValueError('Source page must be a positive integer')
            metadata['page'] = group['page']
        result.append(metadata)
    return {'source_sha256': catalog['source_sha256'], 'groups': result}


def apply_group_selection(inventory, base_plan, catalog, response, protected_native_ids):
    """Validate first, then append only exact-ID exclusions to a copied DrawingPlan.

    `retain` preserves existing base selection; it does not restore excluded ink.
    The caller compiles against the same unbatched inventory and owns cycle/call
    accounting, source-byte binding, artifact checking and user Apply.
    """
    groups = _catalog(catalog)
    response = NativeGroupSelection.model_validate(_record(response))
    plan = DrawingPlan.model_validate(_record(base_plan)).model_copy(deep=True)
    raw_inventory = _record(inventory)
    if not isinstance(raw_inventory, Mapping) or not isinstance(raw_inventory.get('views'), list):
        raise ValueError('Use an unbatched source-native inventory')
    source_views = {}
    for raw_view in raw_inventory['views']:
        view = _record(raw_view)
        if not isinstance(view, Mapping) or not isinstance(view.get('id'), str) or view['id'] in source_views:
            raise ValueError('Source inventory views must have unique IDs')
        primitives = [_record(p) for p in view.get('primitives', [])]
        native_ids = set()
        for primitive in primitives:
            if not isinstance(primitive, Mapping):
                raise ValueError('Source primitives must be native records')
            identity = primitive.get('id')
            if not isinstance(identity, str) or identity.startswith('B_') or primitive.get('source_ids') or identity in native_ids:
                raise ValueError('Use unbatched native primitives with unique IDs, not compiled batches')
            native_ids.add(identity)
        source_views[view['id']] = (view, native_ids)
    plans = {view.view_id: view for view in plan.views}
    if len(plans) != len(plan.views):
        raise ValueError('Base drawing plan views must be unique')
    if not isinstance(protected_native_ids, Mapping):
        raise ValueError('Protected native IDs must be an explicit per-view mapping')
    protected = {}
    for view_id, identities in protected_native_ids.items():
        if view_id not in source_views or not isinstance(identities, (list, tuple, set, frozenset)) or any(not isinstance(i, str) for i in identities):
            raise ValueError('Protected IDs must belong to an exact source view')
        protected[view_id] = set(identities)
        if not protected[view_id].issubset(source_views[view_id][1]):
            raise ValueError('Protected IDs must exist in the unbatched source view')
    by_id = {group['group_id']: group for group in groups}
    if set(by_id) != {decision.group_id for decision in response.groups}:
        raise ValueError('Response must classify every catalog group exactly once, with no added groups')
    for group in groups:
        view_id = group['view_id']
        if view_id not in source_views or view_id not in plans:
            raise ValueError('Catalog source view must exist in inventory and base plan')
        view, identities = source_views[view_id]
        if view.get('source_sha256') != catalog['source_sha256']:
            raise ValueError('Catalog/source-view SHA256 binding changed')
        if not set(group['native_ids']).issubset(identities):
            raise ValueError('Catalog native IDs must exist in their exact unbatched source view')
    held = []
    for decision in response.groups:
        group = by_id[decision.group_id]
        if decision.view_id != group['view_id']:
            raise ValueError('Response group/source-view membership changed')
        if decision.action == 'review' or decision.category == 'uncertain':
            held.append(decision)
            continue
        if decision.action == 'omit':
            if decision.category not in ('appearance_texture', 'out_of_scope_context'):
                raise ValueError('Only appearance texture or out-of-scope context can be omitted')
            if protected.get(decision.view_id, set()).intersection(group['native_ids']):
                raise ValueError('An omission cannot remove a protected source primitive')
    if held:
        raise NativeGroupSelectionHold(held)
    for decision in response.groups:
        if decision.action == 'omit':
            ids = by_id[decision.group_id]['native_ids']
            for offset in range(0, len(ids), 20000):
                plans[decision.view_id].rules.append(DrawingRule(primitive_ids=ids[offset:offset+20000], include=False))
    return DrawingPlan.model_validate(plan.model_dump())
