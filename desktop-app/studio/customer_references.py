"""Host-resolved customer reference values, isolated from immutable source facts.

No customer IDs, coordinates, normal sizes, credentials or external services occur
here.  A ReferencePlan is an untrusted proposal.  Its values are never installed
into Parameter records or used to reshape source-owned geometry.
"""
from __future__ import annotations

import ast
from collections import Counter
import copy
from fractions import Fraction
import hashlib
import json
import math
import re
from typing import Any

from pydantic import ValidationError

from .reference_models import ReferenceAnnotation, ReferencePlan


class ReferenceValidationError(ValueError):
    """Atomic proposal rejection with bounded, actionable per-control issues."""
    issues: list[dict[str,Any]]

    def __init__(self, issues: list[dict[str,Any]]):
        self.issues=copy.deepcopy(issues)
        details=[]
        for issue in self.issues:
            identity={key:issue.get(key) for key in ('control_id','owner_id','view_id','anchor_a_id','anchor_b_id')}
            details.append(json.dumps(identity,ensure_ascii=False,separators=(',',':'))+': '+issue['message'])
        super().__init__('Reference validation failed: '+'; '.join(details))


def _reference_issue(estimate, message, *, code='invalid_reference_estimate', phase='validation'):
    value=estimate.model_dump() if hasattr(estimate,'model_dump') else estimate if isinstance(estimate,dict) else {}
    keys=('estimate_id','control_id','owner_id','view_id','anchor_a_id','anchor_b_id',
          'calibration_anchor_a_id','calibration_anchor_b_id')
    result={key:value.get(key)[:180] if isinstance(value.get(key),str) else None for key in keys}
    result.update(code=code,phase=phase,message=str(message)[:1200])
    return result


def _plain(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump()
    return copy.deepcopy(value)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _unique(records, label, key='id'):
    if not isinstance(records, list) or any(not isinstance(item, dict) or key not in item for item in records):
        raise ValueError(f'Invalid reference {label} registry')
    result = {item[key]: item for item in records}
    if len(result) != len(records):
        raise ValueError(f'Duplicate reference {label} identities')
    return result


def _extraction(value):
    value = _plain(value)
    if not isinstance(value, dict):
        raise ValueError('A complete original extraction is required')
    parameters = _unique(value.get('parameters'), 'parameter')
    owners = _unique(value.get('owners'), 'owner')
    for parameter in parameters.values():
        if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', parameter['id'])
                or parameter.get('status') not in ('source', 'inferred', 'user', 'designed', 'tbc')):
            raise ValueError('Invalid original source parameter identity or status')
        if parameter['status'] == 'tbc' and (parameter.get('value_mm') is not None or parameter.get('expression') is not None):
            raise ValueError('Original TBC parameters cannot contain invented numeric values or expressions')
    bindings = value.get('dimension_bindings')
    if not isinstance(bindings, list):
        raise ValueError('Original dimension bindings are required')
    pairs = set()
    for item in bindings:
        pair = (item.get('owner_id'), item.get('axis'))
        if (item.get('owner_id') not in owners or item.get('parameter_id') not in parameters
                or item.get('axis') not in ('width', 'depth', 'height') or pair in pairs):
            raise ValueError('Invalid or duplicate original dimension binding')
        pairs.add(pair)
    for owner in owners.values():
        seen = set()
        current = owner
        while current.get('parent_id') is not None:
            if current['id'] in seen or current['parent_id'] not in owners:
                raise ValueError('Invalid original owner hierarchy')
            seen.add(current['id'])
            current = owners[current['parent_id']]
    return value, parameters, owners, bindings


def required_reference_controls(extraction):
    """Exactly the original TBC parameters bound to positive object size axes.

    Shared parameters are one control with all allowed owner/axis bindings.
    Unrelated coordinate, offset and relationship TBC records stay background.
    """
    _, parameters, owners, bindings = _extraction(extraction)
    controls = {}
    for binding in bindings:
        parameter = parameters[binding['parameter_id']]
        if parameter.get('status') != 'tbc':
            continue
        ident = parameter['id']
        if ident not in controls:
            controls[ident] = dict(control_id=ident, parameter_id=ident,
                label=parameter.get('label') or ident, owner_id=binding['owner_id'], axis=binding['axis'], bindings=[])
        controls[ident]['bindings'].append(dict(owner_id=binding['owner_id'], axis=binding['axis']))
    return [controls[key] for key in sorted(controls)]


def _commands(value):
    commands = value.get('commands', [])
    if not commands or commands[0].get('op') != 'M':
        return []
    for command in commands:
        points = command.get('points', [])
        if command.get('op') not in ('M', 'L', 'C', 'Z') or len(points) != {'M':2, 'L':2, 'C':6, 'Z':0}[command['op']]:
            raise ValueError('Invalid original native path command')
        if any(type(x) not in (float, int) or not math.isfinite(x) or abs(x) > 100000 for x in points):
            raise ValueError('Invalid original native path coordinates')
    return commands


def _flatten(commands):
    """Polyline approximation is used only for visibility, never as anchor geometry."""
    paths = []
    path = []
    for command in commands:
        p = command['points']
        if command['op'] == 'M':
            if path:
                paths.append(path)
            path = [tuple(p)]
        elif command['op'] == 'L' and path:
            path.append(tuple(p))
        elif command['op'] == 'C' and path:
            a = path[-1]
            for step in range(1, 33):
                t = step / 32; s = 1 - t
                path.append(tuple(s*s*s*a[i]+3*s*s*t*p[i]+3*s*t*t*p[2+i]+t*t*t*p[4+i] for i in (0, 1)))
        elif command['op'] == 'Z' and path:
            path.append(path[0])
    if path:
        paths.append(path)
    return paths


def _on_segment(point, a, b, tolerance=1e-7):
    dx, dy = b[0]-a[0], b[1]-a[1]
    return (abs(dx*(point[1]-a[1])-dy*(point[0]-a[0])) <= tolerance*max(1, math.hypot(dx,dy))
        and min(a[0],b[0])-tolerance <= point[0] <= max(a[0],b[0])+tolerance
        and min(a[1],b[1])-tolerance <= point[1] <= max(a[1],b[1])+tolerance)


def _inside(point, paths, fill_rule='nonzero', boundary=True):
    winding = 0
    crossings = 0
    for path in paths:
        for a, b in zip(path, path[1:]+path[:1]):
            if _on_segment(point, a, b):
                return boundary
            if (a[1] <= point[1] < b[1]) or (b[1] <= point[1] < a[1]):
                x = a[0] + (point[1]-a[1])*(b[0]-a[0])/(b[1]-a[1])
                if x > point[0]:
                    crossings += 1
                    winding += 1 if b[1] > a[1] else -1
    return bool(crossings % 2) if fill_rule == 'evenodd' else winding != 0


def _visible(point, primitive, masks, width, height):
    if not (0 <= point[0] <= width and 0 <= point[1] <= height):
        return False
    for clip in primitive.get('clips', []):
        if not _inside(point, _flatten(_commands(clip)), clip.get('fill_rule', 'nonzero')):
            return False
    for mask in masks:
        if not all(_inside(point, _flatten(_commands(c)), c.get('fill_rule', 'nonzero')) for c in mask.get('clips', [])):
            continue
        # Every supported path fill is opaque (fill_rgb changes colour only;
        # DrawingPrimitive has no alpha). Keep exposed boundary/corner points.
        if mask.get('fill') in ('white','black') and _inside(point, _flatten(_commands(mask)),
                mask.get('fill_rule', 'nonzero'),boundary=False):
            return False
        if mask.get('stroke') and mask.get('stroke_color') == 'white':
            radius = float(mask.get('stroke_width', .5))/2
            for path in _flatten(_commands(mask)):
                for a, b in zip(path, path[1:]):
                    dx, dy = b[0]-a[0], b[1]-a[1]
                    t = 0 if dx*dx+dy*dy == 0 else max(0, min(1, ((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
                    if math.hypot(point[0]-a[0]-t*dx, point[1]-a[1]-t*dy) <= radius:
                        return False
    return True


def _path_endpoints(commands):
    result = []
    current = None
    for index, command in enumerate(commands):
        if command['op'] == 'Z':
            continue
        point = tuple(command['points'][-2:])
        span = 0. if current is None or command['op'] == 'M' else max(abs(point[0]-current[0]), abs(point[1]-current[1]))
        result.append((index, point, span))
        if len(result) > 1 and command['op'] != 'M':
            prior = result[-2]
            result[-2] = (prior[0], prior[1], max(prior[2], span))
        current = point
    return result


def _same_geometry(original, retained):
    # Coalesced unfilled paths retain exact contiguous original command runs.
    wanted = original['commands']; actual = retained.get('commands', [])
    if len(wanted) > len(actual):
        return False
    return any(actual[start:start+len(wanted)] == wanted for start in range(len(actual)-len(wanted)+1))


def _owner_lineage(owners, owner_id):
    result=set()
    while owner_id is not None and owner_id in owners:
        result.add(owner_id);owner_id=owners[owner_id].get('parent_id')
    return result


def _page_point(anchor, view):
    x,y=anchor['normalized_point'];left,top,right,bottom=view['region']
    return [left+x*(right-left),top+y*(bottom-top)]


def _view_local_evidence(refs, view, *, precise_only=False):
    """Evidence priority is local to a source view, not merely its PDF page."""
    return [ref for ref in refs if ref.get('document_id')==view['document_id'] and ref.get('page')==view['page']
        and ((ref.get('region') is None and not precise_only)
             or (ref.get('region') is not None and _overlap(ref['region'],view['region'])))]


def _target_anchor_problem(anchor, view, owner_id, lineages, owner_regions):
    if any(owner_id in lineages.get(known, ()) for known in anchor['owner_ids']):
        return None
    if not any(known in lineages[owner_id] for known in anchor['owner_ids']):
        return 'Reference structural anchor belongs to a different semantic owner assembly'
    x, y = _page_point(anchor, view)
    if not any(region[0]-1e-8 <= x <= region[2]+1e-8 and region[1]-1e-8 <= y <= region[3]+1e-8
            for region in owner_regions):
        return 'Ancestor-only reference structural anchor lies outside the original owner/control source region'
    return None


def _target_owner_regions(owner, parameter, view):
    owner_refs = _view_local_evidence(owner.get('evidence', []), view, precise_only=True)
    control_refs = _view_local_evidence(parameter.get('evidence', []), view, precise_only=True)
    return [ref['region'] for ref in owner_refs or control_refs]


def _target_anchor_eligibility(view, controls, owners, parameters, lineages):
    """Report which displayed anchors pass the same owner gate as resolution."""
    result = []
    for control in controls:
        parameter = parameters[control['parameter_id']]
        for binding in control['bindings']:
            owner = owners[binding['owner_id']]
            refs = owner.get('evidence', []) + parameter.get('evidence', [])
            if refs and not _view_local_evidence(refs, view):
                continue
            regions = _target_owner_regions(owner, parameter, view)
            eligible = [anchor['id'] for anchor in view['anchors']
                if _target_anchor_problem(anchor, view, owner['id'], lineages, regions) is None]
            result.append(dict(control_id=control['control_id'], **binding, eligible_target_anchor_ids=eligible))
    return result


def _required_owner_pairs(candidates, view, controls, owners, parameters):
    """Reserve real endpoints near each required owner, without inventing bounds.

    These are catalogue coverage candidates, not automatically approved object
    dimensions. The proposal and final reviewer still choose/verify real limits.
    """
    targets={}
    for control in controls:
        for binding in control['bindings']:
            target=targets.setdefault(binding['owner_id'],{'control_ids':set(),'axes':set(),'parameter_ids':set()})
            target['control_ids'].add(control['control_id']);target['axes'].add(binding['axis'])
            target['parameter_ids'].add(control['parameter_id'])
    reserved={};coverage=[];lineages={key:_owner_lineage(owners,key) for key in owners}
    def pair(pool, axis):
        if not pool:return None
        low=min(pool,key=lambda item:(item['point'][axis],-item['_score'],item['id']))
        maximum=max(item['point'][axis] for item in pool)
        high=min((item for item in pool if item['point'][axis]==maximum),key=lambda item:(-item['_score'],item['id']))
        return (low,high) if high['point'][axis]-low['point'][axis]>1e-9 else None
    for owner_id,target in sorted(targets.items()):
        owner=owners[owner_id];owner_refs=owner.get('evidence',[])
        parameter_refs=[ref for ident in target['parameter_ids'] for ref in parameters[ident].get('evidence',[])]
        refs=owner_refs+parameter_refs
        relevant=_view_local_evidence(refs,view)
        if refs and not relevant:continue
        structural=_view_local_evidence(owner_refs,view,precise_only=True)
        control_refs=_view_local_evidence(parameter_refs,view,precise_only=True)
        regions=[ref['region'] for ref in structural or control_refs]
        ancestry=lineages[owner_id];direct=[];compatible=[]
        for anchor in candidates:
            point=_page_point(anchor,view)
            direct_match=any(owner_id in lineages.get(known,set()) for known in anchor['owner_ids'])
            inside=any(region[0]-1e-8<=point[0]<=region[2]+1e-8
                and region[1]-1e-8<=point[1]<=region[3]+1e-8 for region in regions)
            # A source citation window may locate a number, not the physical
            # envelope. Explicit classified ownership is separate evidence.
            ancestor_match=inside and any(known in ancestry for known in anchor['owner_ids'])
            if direct_match:direct.append(anchor)
            if direct_match or ancestor_match:compatible.append(anchor)
        row={'owner_id':owner_id,'control_ids':sorted(target['control_ids']),'bound_axes':sorted(target['axes']),
            'eligible_endpoint_count':len(compatible),'direct_owner_endpoint_count':len(direct),'pairs':{}}
        for axis,name in ((0,'horizontal'),(1,'vertical')):
            chosen=pair(direct,axis)
            source='classified_owner_or_descendant'
            if chosen is None:
                chosen=pair(compatible,axis);source='compatible_assembly_inside_original_owner_evidence'
            if chosen is None:
                row['pairs'][name]={'available':False,'anchor_ids':[],'projected_span_pdf_points':0.}
                continue
            for anchor in chosen:reserved[anchor['id']]=anchor
            row['pairs'][name]={'available':True,'anchor_ids':[item['id'] for item in chosen],
                'projected_span_pdf_points':chosen[1]['point'][axis]-chosen[0]['point'][axis],
                'selection_basis':source,'semantic_limits_confirmed':False}
        coverage.append(row)
    return list(reserved.values()),coverage


def build_anchor_catalog(inventory, drawings, max_per_view=256, *, extraction=None):
    """Bounded real retained contour endpoints, namespaced by source SHA/view.

    Only native M/L/C endpoints qualify.  Bezier handles, bounding-box corners,
    text, discarded paths, operation/dimension marks and visibility masks do not.
    Classification comes from the retained drawing, never source ID heuristics.
    Optional original extraction evidence reserves nonzero endpoint pairs near
    each required owner before the cap; it never certifies semantic size limits.
    """
    if type(max_per_view) is not int or not 2 <= max_per_view <= 256:
        raise ValueError('Reference anchor cap must be an integer from 2 through 256')
    context=None;controls=[];owners={};parameters={}
    if extraction is not None:
        context,parameters,owners,_=_extraction(extraction)
        controls=required_reference_controls(context)
    lineages = {key: _owner_lineage(owners, key) for key in owners}
    inventory = _plain(inventory)
    sources = _unique(inventory.get('views'), 'native view')
    outputs = _unique([_plain(v) for v in drawings], 'retained view')
    if set(sources) != set(outputs):
        raise ValueError('Reference anchors require the full retained native view set')
    views = []
    for view_id in sorted(sources):
        source, drawing = sources[view_id], outputs[view_id]
        for key in ('document_id', 'page', 'source_sha256', 'region', 'width', 'height'):
            if source.get(key) != drawing.get(key):
                raise ValueError('Reference anchors belong to a different retained source view')
        width, height = source['width'], source['height']
        if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0
                and re.fullmatch(r'[a-f0-9]{64}', source.get('source_sha256', ''))):
            raise ValueError('Reference anchor views require finite positive native bounds')
        originals = _unique(source.get('primitives'), 'native primitive')
        selected = drawing.get('primitives', [])
        retained = {}
        for order, primitive in enumerate(selected):
            ids = primitive.get('source_ids') or [primitive.get('source_id')]
            for ident in ids:
                if ident in originals:
                    retained.setdefault(ident, []).append((order, primitive))
        candidates = []
        for ident, original in originals.items():
            commands = _commands(original) if original.get('kind') == 'path' else []
            if (not commands or original.get('fill') == 'white' or original.get('stroke_color') == 'white'
                    or original.get('kind') != 'path'):
                continue
            for order, primitive in retained.get(ident, []):
                if (primitive.get('kind') != 'path' or primitive.get('role') not in ('geometry', 'context')
                        or primitive.get('fill') == 'white' or primitive.get('stroke_color') == 'white'
                        or primitive.get('dash') or not (primitive.get('stroke', True) or primitive.get('fill') == 'black')):
                    continue
                if not _same_geometry(original, primitive) or original.get('clips', []) != primitive.get('clips', []):
                    raise ValueError('Reference anchors require unchanged original physical geometry and clips')
                masks = [p for p in selected[order+1:] if p.get('kind') == 'path' and p.get('role') != 'texture'
                    and (p.get('fill') in ('white','black') or (p.get('stroke') and p.get('stroke_color') == 'white'))]
                for command_index, point, score in _path_endpoints(commands):
                    if score <= 1e-9 or not _visible(point, primitive, masks, width, height):
                        continue
                    namespace = _digest([source['source_sha256'], view_id, ident, command_index])[:32]
                    candidates.append(dict(id='A_'+namespace, point=list(point),
                        normalized_point=[point[0]/width, point[1]/height], source_id=ident,
                        command_index=command_index, owner_ids=[primitive.get('owner_id', 'ROOT')],
                        provenance=dict(source_sha256=source['source_sha256'], view_id=view_id,
                            document_id=source['document_id'], page=source['page'],
                            source_primitive_id=ident, command_index=command_index,
                            command_op=commands[command_index]['op'], coordinate_units='native_crop_pdf_points',
                            retained_primitive_id=primitive['id']), _score=score))
        # De-duplicate identical endpoint identities; keep ownership/provenance.
        by_id = {}
        for item in candidates:
            if item['id'] in by_id:
                by_id[item['id']]['owner_ids'] = sorted(set(by_id[item['id']]['owner_ids']+item['owner_ids']))
            else:
                by_id[item['id']] = item
        candidates = sorted(by_id.values(), key=lambda item: (-item['_score'], item['source_id'], item['command_index']))
        # Required semantic-owner pairs take priority over long source strokes.
        # This does not classify a point pair as a measured object size.
        reserved,required_coverage=_required_owner_pairs(candidates,source,controls,owners,parameters) if context is not None else ([],[])
        if len(reserved)>max_per_view:
            raise ValueError('Required owner endpoint pairs exceed the bounded reference catalogue; select a smaller source scope')
        chosen = list(reserved); chosen_ids = {item['id'] for item in chosen}
        covered_owners = {owner for item in chosen for owner in item['owner_ids']}
        cells = {tuple(min(15,int(x*16)) for x in item['normalized_point']) for item in chosen}
        for item in candidates:
            if len(chosen) >= max_per_view:
                break
            if item['id'] not in chosen_ids and set(item['owner_ids']) - covered_owners:
                chosen.append(item); chosen_ids.add(item['id']); covered_owners.update(item['owner_ids'])
        for item in candidates:
            cell = tuple(min(15, int(x*16)) for x in item['normalized_point'])
            if len(chosen) < max_per_view and item['id'] not in chosen_ids and cell not in cells:
                chosen.append(item); chosen_ids.add(item['id']); cells.add(cell)
        for item in candidates:
            if len(chosen) < max_per_view and item['id'] not in chosen_ids:
                chosen.append(item); chosen_ids.add(item['id'])
        anchors = [{key:value for key,value in item.items() if key != '_score'} for item in chosen]
        all_owners = {owner for item in candidates for owner in item['owner_ids']}
        views.append(dict(view_id=view_id, document_id=source['document_id'], page=source['page'],
            source_sha256=source['source_sha256'], region=source['region'], width=width, height=height,
            anchors=anchors, candidate_count=len(candidates), omitted_count=len(candidates)-len(anchors),
            omitted_owner_ids=sorted(all_owners-covered_owners)))
        if context is not None:
            views[-1]['required_owner_pair_coverage'] = required_coverage
            views[-1]['target_anchor_eligibility'] = _target_anchor_eligibility(views[-1], controls, owners, parameters, lineages)
    result = dict(schema='vwc-customer-reference-anchors/1', max_per_view=max_per_view, views=views,
        selection_policy='Visible retained native contour endpoints; long-axis priority, owner coverage, spatial diversity; not exhaustive')
    if context is not None:
        result['required_control_context_sha256']=_digest(context)
        result['selection_policy']='Required semantic-owner endpoint pairs before long-axis/owner/spatial fill; original native endpoints only; proposed semantic limits still require review'
    result['digest'] = _digest(result)
    return result


def _expression(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError('Invalid reference arithmetic expression')
    try:
        tree = ast.parse(value, mode='eval')
    except (SyntaxError, RecursionError):
        raise ValueError('Invalid reference arithmetic expression') from None
    nodes = list(ast.walk(tree))
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.UAdd, ast.USub)
    if len(nodes) > 160 or any(not isinstance(node, allowed) for node in nodes):
        raise ValueError('Reference arithmetic permits only parameters, numbers and + - * /')
    names = set()
    for node in nodes:
        if isinstance(node, ast.Name):
            if not node.id.isascii() or not node.id.isidentifier() or len(node.id) > 80:
                raise ValueError('Invalid reference expression parameter identity')
            names.add(node.id)
        if isinstance(node, ast.Constant) and (type(node.value) not in (int, float)
                or not math.isfinite(node.value) or abs(node.value) > 100000):
            raise ValueError('Reference arithmetic constants must be finite and bounded')
    return tree.body, names


def _finite(value, positive=False):
    try:
        valid = math.isfinite(float(value)) and abs(value) <= 100000 and (not positive or value > 0)
    except (OverflowError, ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Reference values must be finite positive lengths within 100 metres' if positive
                         else 'Reference arithmetic exceeds the finite 100 metre envelope')
    return value


def _round(value, step):
    # Decimal rational half-up, independent of binary floats/bankers rounding.
    quantum = Fraction(str(step)); quotient = value / quantum
    rounded = ((quotient.numerator*2+quotient.denominator)//(2*quotient.denominator))*quantum
    return _finite(rounded, True)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def resolve_reference_plan(plan, *, extraction, documents, inventory, drawings, anchor_catalog):
    """Resolve all required controls once, or reject the entire proposal safely."""
    raw_plan=_plain(plan)
    try:
        plan = ReferencePlan.model_validate(raw_plan)
    except ValidationError as error:
        rows=raw_plan.get('estimates',[]) if isinstance(raw_plan,dict) else []
        issues=[]
        for detail in error.errors(include_input=False,include_context=False,include_url=False):
            loc=detail.get('loc',())
            row=rows[loc[1]] if len(loc)>1 and loc[0]=='estimates' and type(loc[1]) is int and isinstance(rows,list) and 0<=loc[1]<len(rows) else {}
            issue=_reference_issue(row,detail['msg'],code='invalid_reference_schema',phase='schema')
            issue['field_path']=list(loc);issues.append(issue)
        raise ReferenceValidationError(issues) from None
    original, parameters, owners, bindings = _extraction(extraction)
    immutable_before = _digest(dict(extraction=original, inventory=_plain(inventory), drawings=[_plain(v) for v in drawings]))
    controls = {item['control_id']:item for item in required_reference_controls(original)}
    estimates = {item.control_id:item for item in plan.estimates}
    if len(estimates) != len(plan.estimates) or set(estimates) != set(controls):
        counts=Counter(item.control_id for item in plan.estimates);issues=[]
        for ident in sorted(set(controls)-set(estimates)):
            issues.append(_reference_issue(controls[ident],
                'Reference plan must cover every required original TBC control exactly once; this control is missing',
                code='missing_required_reference',phase='coverage'))
        for item in plan.estimates:
            if item.control_id not in controls or counts[item.control_id]!=1:
                issues.append(_reference_issue(item,
                    'Reference plan must cover every required original TBC control exactly once; control is unbound or duplicated',
                    code='unbound_or_duplicate_reference',phase='coverage'))
        raise ReferenceValidationError(issues)
    if len({item.estimate_id for item in plan.estimates}) != len(plan.estimates):
        counts=Counter(item.estimate_id for item in plan.estimates)
        raise ReferenceValidationError([_reference_issue(item,'Reference estimate identities must be unique',
            code='duplicate_estimate_identity',phase='coverage') for item in plan.estimates if counts[item.estimate_id]>1])
    docs = _unique([_plain(item) for item in documents], 'document')
    source_views = _unique(original.get('source_index', {}).get('views', []), 'indexed view')
    supplied_catalog = _plain(anchor_catalog)
    context_bound='required_control_context_sha256' in supplied_catalog
    if context_bound and supplied_catalog['required_control_context_sha256']!=_digest(original):
        raise ValueError('Reference anchor catalogue belongs to different original required-control evidence')
    rebuilt = build_anchor_catalog(inventory, drawings, max_per_view=supplied_catalog.get('max_per_view', 256),
        extraction=original if context_bound else None)
    if _digest(supplied_catalog) != _digest(rebuilt):
        raise ValueError('Reference anchor catalogue changed or belongs to another retained source candidate')
    catalog_views = {item['view_id']:item for item in rebuilt['views']}
    lineages = {key: _owner_lineage(owners, key) for key in owners}
    validated = {};validation_issues=[]
    def validate_estimate(ident,estimate):
        if dict(owner_id=estimate.owner_id, axis=estimate.axis) not in controls[ident]['bindings']:
            raise ValueError('Reference estimate owner and axis do not match the original dimension binding')
        if estimate.view_id not in source_views or estimate.view_id not in catalog_views:
            raise ValueError('Reference estimate cites an unavailable source view')
        view = catalog_views[estimate.view_id]; indexed = source_views[estimate.view_id]
        if (view['document_id'] != indexed['document_id'] or view['page'] != indexed['page']
                or (indexed.get('region') is not None and view['region'] != indexed['region'])):
            raise ValueError('Reference view differs from its original indexed source region')
        document = docs.get(view['document_id'])
        if document is None or document.get('sha256') != view['source_sha256']:
            raise ValueError('Reference source SHA does not match its registered original document')
        refs = [item.model_dump() for item in estimate.source_refs]
        for ref in refs:
            doc = docs.get(ref['document_id'])
            if doc is None or ref['page'] > doc.get('page_count', 1):
                raise ValueError('Reference source evidence cites an unavailable original document or page')
        if not any(ref['document_id'] == view['document_id'] and ref['page'] == view['page']
                   and _overlap(ref['region'], view['region']) for ref in refs):
            raise ValueError('Reference source evidence must overlap its own selected source view')
        # The owner must have evidence on the selected source page. Ancestor
        # evidence may establish assembly identity but cannot invent a new view.
        owner_refs = owners[estimate.owner_id].get('evidence', []) + parameters[ident].get('evidence', [])
        if owner_refs and not _view_local_evidence(owner_refs,view):
            raise ValueError('Reference view is not linked to the original owner or control evidence')
        anchors = {item['id']:item for item in view['anchors']}
        a, b = anchors.get(estimate.anchor_a_id), anchors.get(estimate.anchor_b_id)
        if a is None or b is None:
            raise ValueError('Reference endpoints must resolve to host-provided anchors in the selected view')
        owner_regions = _target_owner_regions(owners[estimate.owner_id], parameters[ident], view)
        for anchor in (a,b):
            problem = _target_anchor_problem(anchor, view, estimate.owner_id, lineages, owner_regions)
            if problem:
                raise ValueError(problem)
        axis_index = 0 if estimate.orientation == 'horizontal' else 1
        span = abs(Fraction(str(b['point'][axis_index]))-Fraction(str(a['point'][axis_index])))
        if span <= Fraction('0.000000001'):
            raise ValueError('Reference anchor pair has a zero projected axis span')
        calibration = None
        if estimate.method == 'calibrated_ratio':
            ca, cb = anchors.get(estimate.calibration_anchor_a_id), anchors.get(estimate.calibration_anchor_b_id)
            if ca is None or cb is None:
                raise ValueError('Calibration endpoints must be host anchors from the same source view')
            calibration_span = abs(Fraction(str(cb['point'][axis_index]))-Fraction(str(ca['point'][axis_index])))
            if calibration_span <= Fraction('0.000000001'):
                raise ValueError('Reference calibration has a zero projected axis span')
            calibration = dict(anchor_a_id=ca['id'], anchor_b_id=cb['id'], point_a=ca['point'], point_b=cb['point'],
                target_span_pdf_points=float(span), calibration_span_pdf_points=float(calibration_span),
                ratio_numerator=(span/calibration_span).numerator, ratio_denominator=(span/calibration_span).denominator)
        return dict(view=view, a=a, b=b, span=span, calibration=calibration)

    for ident,estimate in estimates.items():
        try:
            validated[ident]=validate_estimate(ident,estimate)
        except ValueError as error:
            validation_issues.append(_reference_issue(estimate,str(error),phase='binding_anchors_evidence'))

    values = {}; proofs = {}; active = set(); trees = {}
    # Check all original expression identities and cycles, including unused
    # background records. An estimate does not sanitize a broken source graph.
    dependencies = {}
    for ident, parameter in parameters.items():
        if parameter.get('expression') is not None:
            tree, names = _expression(parameter['expression']); trees[('source', ident)] = tree
            if names - set(parameters):
                raise ValueError('Original source expression cites an unknown parameter')
            dependencies[ident] = names
        else:
            dependencies[ident] = set()
    seen = set(); walking = set()
    def graph(ident):
        if ident in walking:
            raise ValueError('Cyclic original source parameter expression')
        if ident in seen:
            return
        if len(walking) >= 128:
            raise ValueError('Original source expression dependency graph exceeds the supported depth')
        walking.add(ident)
        for other in dependencies[ident]:
            graph(other)
        walking.remove(ident); seen.add(ident)
    for ident in parameters:
        graph(ident)

    def arithmetic(node, dimension_check):
        if isinstance(node, ast.Constant):
            return Fraction(str(node.value)), 0, set(), set()
        if isinstance(node, ast.Name):
            value, evidence_ids, design_ids = resolve(node.id)
            return value, 1, evidence_ids | {node.id}, design_ids
        if isinstance(node, ast.UnaryOp):
            value, dimension, deps, designs = arithmetic(node.operand, dimension_check)
            return _finite(-value if isinstance(node.op, ast.USub) else value), dimension, deps, designs
        a, da, deps_a, designs_a = arithmetic(node.left, dimension_check)
        b, db, deps_b, designs_b = arithmetic(node.right, dimension_check)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            dimension=da if da==db else max(da,db)
            if dimension_check and da != db:
                # Only a dimensionless zero is an additive identity. Numeric
                # cancellation does not erase length/area/reciprocal units.
                if da==0 and a==0:dimension=db
                elif db==0 and b==0:dimension=da
                else:raise ValueError('Exact reference calculations cannot add an unsupported dimensional constant')
            result = a+b if isinstance(node.op, ast.Add) else a-b
        elif isinstance(node.op, ast.Mult):
            result = a*b; dimension = da+db
        else:
            if b == 0:
                raise ValueError('Reference expression divides by zero')
            result = a/b; dimension = da-db
        return _finite(result), dimension, deps_a | deps_b, designs_a | designs_b

    def resolve(ident):
        if ident not in parameters:
            raise ValueError('Reference expression cites an unknown original parameter')
        if ident in active:
            raise ValueError('Cyclic reference expression dependency')
        if ident in values:
            return values[ident]
        if len(active) >= 64:
            raise ValueError('Reference expression dependency graph exceeds the supported depth')
        active.add(ident)
        try:
            parameter = parameters[ident]
            if parameter.get('status') != 'tbc':
                if parameter.get('expression') is not None:
                    value, _, refs, designs = arithmetic(trees[('source', ident)], False)
                elif type(parameter.get('value_mm')) in (int, float):
                    value = _finite(Fraction(str(parameter['value_mm']))); refs = {ident}; designs = set()
                else:
                    raise ValueError('Known source parameters require a finite value or valid expression')
            else:
                estimate = estimates.get(ident)
                if estimate is None:
                    raise ValueError('Reference calculation depends on an unresolved background TBC parameter')
                if ident not in validated:
                    raise ValueError('Reference calculation depends on a control with invalid binding/anchors/evidence: '+ident)
                calibration = validated[ident]['calibration']
                if estimate.method == 'design_reference':
                    value = Fraction(str(estimate.design_value_mm)); refs = set(); designs = {ident}
                elif estimate.method in ('source_choice', 'calibrated_ratio'):
                    source_id = estimate.source_parameter_id
                    if source_id not in parameters or parameters[source_id].get('status') == 'tbc':
                        raise ValueError('Source choice and calibration require an original known source parameter')
                    value, refs, designs = resolve(source_id); refs = refs | {source_id}
                    _finite(value, True)
                    if designs:
                        raise ValueError('Source choice and calibration cannot treat a designed reference as an original source fact')
                    # Cite at least one original source observation behind the
                    # numeric calibration, rather than merely a nearby contour.
                    source_evidence = [ref for key in refs for ref in parameters[key].get('evidence', [])]
                    if not source_evidence or not any(a.get('document_id') == b.document_id and a.get('page') == b.page
                            and (a.get('region') is None or _overlap(a['region'], b.region))
                            for a in source_evidence for b in estimate.source_refs):
                        raise ValueError('Reference source choice/calibration requires overlapping original numeric evidence')
                    if estimate.method == 'calibrated_ratio':
                        value *= Fraction(calibration['ratio_numerator'], calibration['ratio_denominator'])
                        calibration.update(source_parameter_id=source_id, source_value_mm=float(resolve(source_id)[0]),
                            equation='source_value_mm * target_span_pdf_points / calibration_span_pdf_points')
                else:
                    tree, names = _expression(estimate.expression)
                    if not names:
                        raise ValueError('Exact reference calculations must depend on original parameter identities')
                    value, dimension, refs, designs = arithmetic(tree, True)
                    if dimension != 1:
                        raise ValueError('Exact reference calculations must resolve to one length dimension')
                _finite(value, True)
                rounded = _round(value, estimate.rounding_mm)
                proofs[ident] = dict(unrounded_value_mm=float(value), rounded_value_mm=float(rounded),
                    exact_value_numerator=value.numerator, exact_value_denominator=value.denominator,
                    source_parameter_ids=sorted(refs), design_reference_control_ids=sorted(designs),
                    rounding_policy='nearest quantum, rational half-up', rounding_mm=estimate.rounding_mm)
                # Dependency arithmetic uses the unrounded value; display rounding
                # never introduces an accumulating dimension-chain residual.
            values[ident] = (_finite(value), refs, designs)
            return values[ident]
        finally:
            active.remove(ident)

    for ident,estimate in estimates.items():
        if ident not in validated:continue
        try:
            resolve(ident)
        except ValueError as error:
            validation_issues.append(_reference_issue(estimate,str(error),phase='arithmetic_dependencies'))
    parent_checks = []
    binding_map = {(item['owner_id'], item['axis']):item['parameter_id'] for item in bindings}
    def validate_parent_bounds(ident,control):
        for binding in control['bindings']:
            parent = owners[binding['owner_id']].get('parent_id')
            while parent is not None:
                parent_id = binding_map.get((parent, binding['axis']))
                if parent_id and parent_id != ident:
                    if parameters[parent_id].get('status') != 'tbc' or parent_id in estimates:
                        try:
                            limit = resolve(parent_id)[0]
                        except ValueError as error:
                            if 'unresolved background TBC' not in str(error):
                                raise
                            limit = None
                        if limit is not None:
                            _finite(limit, True)
                            if values[ident][0] > limit or Fraction(str(proofs[ident]['rounded_value_mm'])) > limit:
                                raise ValueError('Reference component dimension exceeds its known parent axis bound')
                            parent_checks.append(dict(control_id=ident, owner_id=binding['owner_id'], axis=binding['axis'],
                                parent_owner_id=parent, parent_parameter_id=parent_id, limit_mm=float(limit), passed=True))
                    break
                parent = owners[parent].get('parent_id')

    for ident,control in controls.items():
        if ident not in values:continue
        try:
            validate_parent_bounds(ident,control)
        except ValueError as error:
            validation_issues.append(_reference_issue(estimates[ident],str(error),phase='parent_bounds'))
    if validation_issues:
        raise ReferenceValidationError(validation_issues)

    annotations = {view_id:[] for view_id in catalog_views}; reference_parameters = {}
    for ident in sorted(estimates):
        estimate = estimates[ident]; record = validated[ident]; proof = proofs[ident]
        provenance = dict(role='user_authorized_customer_reference_only', source_status='tbc', source_parameter_id=ident,
            source_parameter_snapshot=_plain(parameters[ident]), original_extraction_sha256=_digest(original),
            original_control_bindings=controls[ident]['bindings'],
            original_parent_bound_checks=[item for item in parent_checks if item['control_id']==ident],
            anchor_catalog_sha256=rebuilt['digest'], source_sha256=record['view']['source_sha256'],
            anchors=[record['a']['provenance'], record['b']['provenance']], arithmetic=proof,
            estimate=estimate.model_dump(), not_source_fact=True, not_fabrication_approval=True)
        annotation = ReferenceAnnotation(estimate_id=estimate.estimate_id, control_id=ident, owner_id=estimate.owner_id,
            axis=estimate.axis, view_id=estimate.view_id, orientation=estimate.orientation, label=estimate.label,
            value_mm=proof['rounded_value_mm'], unrounded_value_mm=proof['unrounded_value_mm'], rounding_mm=estimate.rounding_mm,
            point_a=record['a']['point'], point_b=record['b']['point'], anchor_a_id=estimate.anchor_a_id,
            anchor_b_id=estimate.anchor_b_id, method=estimate.method, source_parameter_ids=proof['source_parameter_ids'],
            expression=estimate.expression, calibration_proof=record['calibration'], confidence=estimate.confidence,
            reason=estimate.reason, evidence=estimate.source_refs, provenance=provenance, provenance_digest=_digest(provenance))
        annotations[estimate.view_id].append(annotation)
        reference_parameters[ident] = dict(value_mm=annotation.value_mm, label=annotation.label, method=estimate.method,
            confidence=estimate.confidence, owner_id=estimate.owner_id, estimate_id=estimate.estimate_id,
            control_id=ident, axis=estimate.axis, source_status='tbc', provenance_digest=annotation.provenance_digest,
            bindings=controls[ident]['bindings'])
    immutable_after = _digest(dict(extraction=_plain(extraction), inventory=_plain(inventory), drawings=[_plain(v) for v in drawings]))
    if immutable_after != immutable_before:
        raise ValueError('Reference resolution changed original source data')
    return dict(annotations_by_view=annotations, reference_parameters=reference_parameters,
        audit=dict(schema='vwc-customer-reference-audit/1', required_control_ids=sorted(controls),
            resolved_control_ids=sorted(reference_parameters), coverage_complete=True,
            source_facts_preserved=True, original_source_data_sha256=immutable_before,
            anchor_catalog_sha256=rebuilt['digest'], plan_sha256=_digest(plan.model_dump()),
            derivations=proofs, parent_bound_checks=parent_checks,
            limitations=['References express user-authorized design choices or estimates, not confirmed source facts.',
                'A ratio uses selected native projected endpoints; it does not establish document scale or fabrication accuracy.',
                'Labels and methods retain uncertainty in this audit; displayed numeric values remain references.']))
