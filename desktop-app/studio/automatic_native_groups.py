"""Neutral automatic source partitions; no semantic decisions or drawing edits.

The only input is a caller-supplied unbatched inventory. Feature thresholds use
source-view proportions. They affect grouping, never visibility or authority.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import re


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def _box(records):
    return [min(p['bbox'][0] for p in records), min(p['bbox'][1] for p in records),
            max(p['bbox'][2] for p in records), max(p['bbox'][3] for p in records)]


def _views(inventory):
    if hasattr(inventory, 'model_dump'):
        inventory = inventory.model_dump()
    if not isinstance(inventory, dict) or not isinstance(inventory.get('views'), list) or not inventory['views']:
        raise ValueError('A nonempty original native inventory is required')
    seen, sources, result = set(), set(), []
    for view in inventory['views']:
        if not isinstance(view, dict):
            raise ValueError('Native source views must be records')
        ident = view.get('id')
        if not isinstance(ident, str) or not ident.strip() or len(ident) > 80 or ident in seen:
            raise ValueError('Native source views require unique IDs')
        seen.add(ident)
        digest = view.get('source_sha256')
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Every source view must bind its document SHA256')
        sources.add(digest)
        if any(type(view.get(k)) not in (int, float) or not math.isfinite(view[k]) or view[k] <= 0 for k in ('width', 'height')):
            raise ValueError('Native view dimensions must be finite and positive')
        region = view.get('region')
        if not isinstance(region, list) or len(region) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in region) or not 0 <= region[0] < region[2] <= 1 or not 0 <= region[1] < region[3] <= 1:
            raise ValueError('Native view must retain its exact normalized source region')
        if type(view.get('page')) is not int or view['page'] < 1:
            raise ValueError('Native source page must be a positive integer')
        records, ids = view.get('primitives'), set()
        if not isinstance(records, list) or len(records) > 60000:
            raise ValueError('Native primitive count exceeds the supported view limit')
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('Native primitives must be records')
            sid = record.get('id')
            if not isinstance(sid, str) or not sid.strip() or len(sid) > 180 or sid.startswith('B_') or sid in ids or record.get('source_ids'):
                raise ValueError('Grouping requires unique original IDs, never compiled batches')
            if not isinstance(record.get('source_id', sid), str) or not record.get('source_id', sid) or not isinstance(record.get('source_style_id', ''), str):
                raise ValueError('Source alias/style identities must remain strings')
            ids.add(sid)
            bbox = record.get('bbox')
            if not isinstance(bbox, list) or len(bbox) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in bbox) or bbox[0] > bbox[2] or bbox[1] > bbox[3]:
                raise ValueError('Native primitive bounds must be finite and ordered')
            if record.get('kind') not in ('path', 'text'):
                raise ValueError('Unsupported source primitive kind')
            if record['kind'] == 'path':
                commands = record.get('commands')
                if not isinstance(commands, list) or not commands or commands[0].get('op') != 'M':
                    raise ValueError('Native paths need source geometry beginning with a move')
                for command in commands:
                    if not isinstance(command, dict) or command.get('op') not in ('M', 'L', 'C', 'Z'):
                        raise ValueError('Unsupported native path operation')
                    points = command.get('points')
                    if not isinstance(points, list) or len(points) != {'M': 2, 'L': 2, 'C': 6, 'Z': 0}[command['op']] or any(type(x) not in (int, float) or not math.isfinite(x) for x in points):
                        raise ValueError('Malformed source command coordinates')
        result.append(view)
    if len(sources) != 1:
        raise ValueError('Build one catalog per source document SHA256')
    return result, next(iter(sources))


def _line(record, diagonal):
    commands = record.get('commands', [])
    if record['kind'] != 'path' or len(commands) != 2 or [c.get('op') for c in commands] != ['M', 'L']:
        return None
    if any(len(c.get('points', [])) != 2 for c in commands):
        raise ValueError('Malformed native line commands')
    x0, y0 = commands[0]['points']; x1, y1 = commands[1]['points']
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (x0, y0, x1, y1)):
        raise ValueError('Native commands must be finite coordinates')
    dx, dy = x1-x0, y1-y0
    tolerance = max(1e-7, diagonal*1e-8)
    if abs(dy) <= tolerance:
        return ('horizontal', (y0+y1)/2, min(x0, x1), max(x0, x1), math.hypot(dx, dy))
    if abs(dx) <= tolerance:
        return ('vertical', (x0+x1)/2, min(y0, y1), max(y0, y1), math.hypot(dx, dy))
    return ('oblique_positive' if dx*dy >= 0 else 'oblique_negative', None, None, None, math.hypot(dx, dy))


def _units(view):
    """Keep every native text paint run of a logical source word atomic."""
    grouped, order = {}, []
    for index, record in enumerate(view['primitives']):
        key = ('text', record.get('source_id', record['id'])) if record['kind'] == 'text' else ('path', record['id'])
        if key not in grouped:
            grouped[key] = {'records': [], 'index': index}; order.append(key)
        grouped[key]['records'].append(record)
    return [grouped[key] for key in order]


def _observed_line_bands(units, diagonal):
    """Refine carriers by observed gaps, without deciding what their ink means.

    At most two cuts per feature keep a dense source carrier bounded. Length
    gaps use ratios so uniformly scaling a source does not change membership.
    Bearings are undirected: reversing a native segment preserves its feature.
    Compound paths and logical text runs never enter this finer partition.
    """
    cohorts = defaultdict(list)
    for unit in units:
        if len(unit['records']) != 1:
            continue
        record = unit['records'][0]; line = _line(record, diagonal)
        if line is None or line[4] <= 0:
            continue
        if not math.isfinite(line[4]):
            raise ValueError('Native line length must remain finite')
        a, b = (command['points'] for command in record['commands'])
        angle = round(math.atan2(b[1]-a[1], b[0]-a[0]) % math.pi, 12)
        key = (record.get('source_style_id', ''), _hash(record.get('clips', [])))
        cohorts[key].append((unit['index'], line[4], angle))

    def cuts(values, minimum_gap):
        values = sorted(set(values))
        gaps = [(b-a, a, b) for a,b in zip(values, values[1:]) if b-a+1e-12 >= minimum_gap]
        chosen = sorted(gaps, key=lambda item: (-round(item[0],12), item[1]))[:2]
        return sorted((a+b)/2 for _,a,b in chosen)

    result = {}
    for samples in cohorts.values():
        length_cuts = cuts([math.log(length) for _,length,_ in samples], math.log(3.))
        angles = sorted({angle for _,_,angle in samples})
        # Unwrap after the largest empty angular interval. This keeps bearings
        # close to zero/pi together instead of treating them as opposites.
        gaps = [(angles[(index+1)%len(angles)]+(math.pi if index==len(angles)-1 else 0.)-angle, index)
                for index,angle in enumerate(angles)]
        _, split = max(gaps, key=lambda item: (item[0], -item[1]))
        start = angles[(split+1)%len(angles)]
        bearing = lambda angle: round((angle-start) % math.pi, 12)
        bearing_cuts = cuts([bearing(angle) for angle in angles], math.radians(15.))
        for index,length,angle in samples:
            result[index] = (sum(math.log(length)>cut for cut in length_cuts),
                             sum(bearing(angle)>cut for cut in bearing_cuts))
    return result


def _partitions(view, units, *, refined=False):
    diagonal = math.hypot(view['width'], view['height'])
    observed_bands = _observed_line_bands(units, diagonal) if refined else {}
    lanes = defaultdict(list)
    for unit in units:
        for record in unit['records']:
            line = _line(record, diagonal)
            if line and line[0] in ('horizontal', 'vertical'):
                key = (record.get('source_style_id', ''), _hash(record.get('clips', [])), line[0], round(line[1]/diagonal, 7))
                lanes[key].append(line[2:4])
    support = set()
    for key, intervals in lanes.items():
        union = []
        for left, right in sorted(intervals):
            if union and left <= union[-1][1]+diagonal*1e-7:
                union[-1][1] = max(right, union[-1][1])
            else:
                union.append([left, right])
        span = view['width'] if key[2] == 'horizontal' else view['height']
        if sum(b-a for a, b in union) >= span*.12:
            support.add(key)
    last, run = {}, defaultdict(int)
    buckets = defaultdict(list)
    for unit in units:
        records = unit['records']; first = records[0]
        styles = tuple(sorted({p.get('source_style_id', '') for p in records}))
        clips = tuple(sorted({_hash(p.get('clips', [])) for p in records}))
        base = (first['kind'], styles, clips)
        if first['kind'] == 'text':
            # All runs remain together even when their clips/paint positions differ.
            feature = ('text_runs', tuple(sorted({round(p.get('rotation', 0), 3) for p in records})))
            paint = 0
        else:
            if unit['index']-last.get(base, -100000) > 32:
                run[base] += 1
            paint = run[base]; last[base] = unit['index']
            line = _line(first, diagonal)
            if line:
                lane = (styles[0], clips[0], line[0], round(line[1]/diagonal, 7)) if line[1] is not None else None
                if lane in support:
                    feature = ('support_line', line[0], None)
                else:
                    length_class = 'small' if line[4] <= diagonal*.025 else 'larger'
                    orientation = 'oblique' if not refined and line[0].startswith('oblique') else line[0]
                    feature = ('line', orientation, length_class)
                if refined:
                    feature += ('observed_gaps', *observed_bands.get(unit['index'], (0, 0)))
            else:
                ops = [c.get('op') for c in first.get('commands', [])]
                feature = ('compound', 'curve' if 'C' in ops else 'polygon', bool(first.get('fill') not in (None, 'none')), bool(first.get('stroke', True)))
        spatial = None
        if refined:
            box = _box(records)
            # A repair separates distant source clusters without exploding
            # every collinear witness or source paint run into a new group.
            spatial = (min(1, max(0, int((box[0]+box[2])/2/view['width']*2))),
                       min(1, max(0, int((box[1]+box[3])/2/view['height']*2))))
        buckets[(base, paint, feature, spatial)].append(unit)
    return list(buckets.values())


def _emit(view, units, ident):
    records = [record for unit in sorted(units, key=lambda u: u['index']) for record in unit['records']]
    return {'group_id': ident, 'view_id': view['id'], 'native_ids': [p['id'] for p in records],
            'bbox': _box(records), 'page': view['page'], 'region': list(view['region'])}


def _budget(value):
    if type(value) is not int or not 1 <= value <= 512:
        raise ValueError('Group request budget must be between one and 512')


def build_automatic_catalog(inventory, *, max_groups=384, max_group_native_ids=60000):
    """Partition every input ID exactly once. No primitive is omitted/protected."""
    _budget(max_groups)
    if type(max_group_native_ids) is not int or not 1 <= max_group_native_ids <= 60000:
        raise ValueError('Invalid group native-ID bound')
    if hasattr(inventory, 'model_dump'):
        inventory = inventory.model_dump()
    views, digest = _views(inventory)
    groups = []
    for view in views:
        for bucket in _partitions(view, _units(view)):
            chunks, count = [], 0
            for unit in bucket:
                size = len(unit['records'])
                if size > max_group_native_ids:
                    raise ValueError('An atomic logical word exceeds the group bound')
                if chunks and count+size > max_group_native_ids:
                    groups.append(_emit(view, chunks, 'G'+str(len(groups)+1).zfill(3))); chunks, count = [], 0
                chunks.append(unit); count += size
            if chunks:
                groups.append(_emit(view, chunks, 'G'+str(len(groups)+1).zfill(3)))
    if not groups or len(groups) > max_groups:
        raise ValueError(f'Automatic grouping needs {len(groups)} groups; cap is {max_groups}. No incompatible groups merged or drawing changed.')
    return {'source_sha256': digest, 'groups': groups,
            'protected_native_ids': {view['id']: [] for view in views},
            'diagnostics': {'schema': 'vwc-automatic-native-groups/1', 'group_count': len(groups),
                            'primitive_count': sum(len(v['primitives']) for v in views),
                            'inventory_sha256': _hash(inventory), 'refinement_depth': 0,
                            'semantic_classifications': 0, 'visibility_changes': 0,
                            'method': 'style/clip/paint-block/topology/orientation/relative-length/support-line partitions; logical text runs atomic'}}


def refine_catalog(catalog, held_ids, inventory, *, max_groups=512, allow_partial=False):
    """One finer neutral partition of held groups; no authority to start a cycle."""
    _budget(max_groups)
    if hasattr(inventory, 'model_dump'):
        inventory = inventory.model_dump()
    views, digest = _views(inventory); by_view = {v['id']: v for v in views}
    if catalog.get('source_sha256') != digest or catalog.get('diagnostics', {}).get('inventory_sha256') != _hash(inventory):
        raise ValueError('Refinement source inventory binding changed')
    if catalog.get('diagnostics', {}).get('refinement_depth', 0) != 0:
        raise ValueError('Only one automatic refinement is supported; unresolved groups remain held')
    if not isinstance(held_ids, (list, tuple, set, frozenset)) or not held_ids or len(set(held_ids)) != len(held_ids):
        raise ValueError('Refinement requires unique held group IDs')
    groups = catalog.get('groups', []); group_ids = [g['group_id'] for g in groups]
    if len(group_ids) != len(set(group_ids)) or not set(held_ids).issubset(group_ids):
        raise ValueError('Unknown or duplicate source group')
    covered = defaultdict(set)
    for group in groups:
        view = by_view.get(group['view_id'])
        if not view or len(group['native_ids']) != len(set(group['native_ids'])) or covered[group['view_id']].intersection(group['native_ids']):
            raise ValueError('Catalog memberships overlap or name a missing source view')
        lookup = {p['id']: p for p in view['primitives']}
        if not group['native_ids'] or not set(group['native_ids']).issubset(lookup) or group['page'] != view['page'] or group['region'] != view['region'] or group['bbox'] != _box([lookup[s] for s in group['native_ids']]):
            raise ValueError('Catalog group source region, bounds or native identity changed')
        covered[group['view_id']].update(group['native_ids'])
    if any(covered[v['id']] != {p['id'] for p in v['primitives']} for v in views):
        raise ValueError('Catalog must preserve complete exact native membership')
    result = deepcopy(catalog); result['groups'] = []; next_id = max(int(g[1:]) for g in group_ids)+1
    remaining = max_groups-len(groups); refined_ids=[]; unrefined_ids=[]
    for group in groups:
        if group['group_id'] not in held_ids:
            result['groups'].append(deepcopy(group)); continue
        view = by_view[group['view_id']]; selected = set(group['native_ids'])
        units = [u for u in _units(view) if any(p['id'] in selected for p in u['records'])]
        if any(not all(p['id'] in selected for p in u['records']) for u in units):
            raise ValueError('Refinement cannot split a logical source word paint run')
        parts = _partitions(view, units, refined=True)
        if len(parts) == 1:
            result['groups'].append(deepcopy(group)); continue
        if len(parts)-1 > remaining and allow_partial:
            # Retain the complete original carrier, not a guessed subset or a
            # merge with another group. The API still must classify it, and an
            # unresolved decision still blocks acceptance after cycle two.
            result['groups'].append(deepcopy(group)); unrefined_ids.append(group['group_id']); continue
        remaining -= len(parts)-1; refined_ids.append(group['group_id'])
        for part in parts:
            result['groups'].append(_emit(view, part, 'G'+str(next_id).zfill(3))); next_id += 1
    if len(result['groups']) > max_groups:
        raise ValueError('Refinement would exceed the bounded group request; hold instead')
    result['diagnostics'].update(group_count=len(result['groups']), refinement_depth=1,
                                 refined_group_ids=sorted(held_ids), semantic_classifications=0, visibility_changes=0)
    result['diagnostics'].update(split_group_ids=refined_ids, unsplit_budget_group_ids=unrefined_ids,
                                 partial_refinement_allowed=bool(allow_partial),
                                 refinement_features={'simple_line_length_ratio_min':3.,
                                     'undirected_bearing_gap_degrees_min':15.,'max_cuts_per_feature':2})
    return result
