"""Canonical studio geometry and cabinet interiors, with no customer-specific imports.

The arithmetic, Z transform and convex extrusion follow the shared workbench's
backend/app/spatial.py. They are kept here because that module imports historical
A200 configuration at import time. This module never reads a customer file.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
from typing import Any

from .models import InteriorSpec, Parameter, Part, Scalar, StudioModel, expression_names
from .material_models import BoardSpec

MATERIALS = {"WD01": "#d9c8ad", "WD02": "#b99873", "ST01": "#e5e2dc", "ST02": "#f5f2eb",
             "ST03": "#bcb9b1", "MT": "#bbc9cd", "PL01": "#e8e5df", "PL02": "#44484a",
             "PL03": "#dfded9", "PT01": "#f5f4ef", "TL01": "#c9c7c2", "TL02": "#b8b6b1",
             "COORD": "#cbd0d0", "DESIGNED": "#d6dfd2"}
MATERIALS.update({"GL": "#c6d6d9", "AP": "#b7bec0", "CONTEXT": "#cbd0d0", "PAINT": "#f5f4ef"})

GENERIC_VIEWS = {
    "AXON": {"direction": [0.577350269, 0.577350269, -0.577350269], "right": [0.707106781, -0.707106781, 0],
             "up": [0.40824829, 0.40824829, 0.81649658], "detail": "Complete model / 完整模型"},
    "PLAN": {"direction": [0, 0, -1], "right": [1, 0, 0], "up": [0, 1, 0], "detail": "Plan / 平面"},
    "FRONT": {"direction": [0, 1, 0], "right": [1, 0, 0], "up": [0, 0, 1], "detail": "Front / 前立面"},
    "RIGHT": {"direction": [-1, 0, 0], "right": [0, 1, 0], "up": [0, 0, 1], "detail": "Right / 右立面"},
    "BACK": {"direction": [0, -1, 0], "right": [-1, 0, 0], "up": [0, 0, 1], "detail": "Back / 后立面"},
    "LEFT": {"direction": [1, 0, 0], "right": [0, -1, 0], "up": [0, 0, 1], "detail": "Left / 左立面"},
}


class Resolver:
    def __init__(self, model: StudioModel):
        self.parameters = {parameter.id: parameter for parameter in model.parameters}
        self.values: dict[str, float | None] = {}
        self.dependencies: dict[str, set[str]] = {}
        self.active: set[str] = set()

    def parameter(self, key: str) -> tuple[float | None, set[str]]:
        if key not in self.parameters:
            raise ValueError(f"Unknown parameter: {key}")
        if key in self.active:
            raise ValueError(f"Cyclic parameter: {key}")
        if key not in self.values:
            self.active.add(key)
            try:
                parameter = self.parameters[key]
                if parameter.status == "tbc":
                    value, dependencies = None, {key}
                elif parameter.expression is not None:
                    value, dependencies = self.expression(parameter.expression)
                else:
                    value, dependencies = parameter.value_mm, {key}
                self._check(value)
                self.values[key] = value
                self.dependencies[key] = dependencies | {key}
            finally:
                self.active.remove(key)
        return self.values[key], set(self.dependencies[key])

    @staticmethod
    def _check(value):
        if value is not None and (not math.isfinite(value) or abs(value) > 100000):
            raise ValueError("Geometry is outside the supported 100 metre envelope")

    def expression(self, value: Scalar) -> tuple[float | None, set[str]]:
        expression_names(value)
        if isinstance(value, (int, float)):
            return float(value), set()
        def evaluate(node):
            if isinstance(node, ast.Constant):
                return float(node.value), set()
            if isinstance(node, ast.Name):
                return self.parameter(node.id)
            if isinstance(node, ast.UnaryOp):
                item, dependencies = evaluate(node.operand)
                return (None if item is None else -item if isinstance(node.op, ast.USub) else item), dependencies
            if isinstance(node, ast.BinOp):
                a, first = evaluate(node.left)
                b, second = evaluate(node.right)
                if isinstance(node.op, ast.Div) and b == 0:
                    raise ValueError("A geometry expression divides by zero")
                if a is None or b is None:
                    return None, first | second
                if isinstance(node.op, ast.Add):
                    result = a + b
                elif isinstance(node.op, ast.Sub):
                    result = a - b
                elif isinstance(node.op, ast.Mult):
                    result = a * b
                else:
                    result = a / b
                self._check(result)
                return result, first | second
            raise ValueError("Unsupported geometry expression")
        return evaluate(ast.parse(value, mode="eval").body)


def _parts(root: Part):
    yield root
    for child in root.children:
        yield from _parts(child)


def find_part(model: StudioModel, part_id: str) -> Part:
    part = next((part for part in _parts(model.root) if part.id == part_id), None)
    if part is None:
        raise ValueError("Unknown component")
    return part


def _transform(point, origin, angle):
    c, s = math.cos(angle), math.sin(angle)
    return [round(origin[0] + point[0]*c - point[1]*s, 6),
            round(origin[1] + point[0]*s + point[1]*c, 6), round(origin[2] + point[2], 6)]


def _extrude(profile, size):
    w, d, h = size
    points = [[float(point[0])*w, float(point[1])*d] for point in profile]
    turns = [(points[i][0]-points[i-1][0])*(points[(i+1)%len(points)][1]-points[i][1])
             -(points[i][1]-points[i-1][1])*(points[(i+1)%len(points)][0]-points[i][0]) for i in range(len(points))]
    area = sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1]
               for i in range(len(points)))
    if area <= 0.000001 or any(turn < -0.000001 for turn in turns):
        raise ValueError("A physical profile must be convex and counter-clockwise")
    vertices = [[x, y, z] for z in (0, h) for x, y in points]
    count = len(points)
    indices, edges = [], []
    for i in range(1, count-1):
        indices.extend([0, i+1, i, count, count+i, count+i+1])
    for i in range(count):
        j = (i+1) % count
        indices.extend([i, j, count+j, i, count+j, count+i])
        edges.extend([[i, j], [count+i, count+j], [i, count+i]])
    return vertices, indices, edges


def validate_model(payload: dict | StudioModel) -> StudioModel:
    model = StudioModel.model_validate(payload.model_dump() if isinstance(payload, StudioModel) else payload)
    resolver = Resolver(model)
    for parameter in model.parameters:
        resolver.parameter(parameter.id)
    for part in _parts(model.root):
        if part.size:
            sizes = [resolver.expression(value)[0] for value in part.size]
            if any(value is not None and value <= 0 for value in sizes):
                raise ValueError(f"Component {part.id} has a non-positive size")
            if part.profile and all(value is not None for value in sizes):
                _extrude(part.profile, sizes)
        if part.surface is not None:
            sizes = [resolver.expression(part.surface.width)[0], resolver.expression(part.surface.span)[0]]
            if any(value is not None and value <= 0 for value in sizes):
                raise ValueError(f"Source surface {part.id} has a non-positive contour size")
        # Position expressions have the same arithmetic and finite-envelope rules.
        for expression in [*part.position, part.rotation]:
            resolver.expression(expression)
        if part.interior is not None:
            _validate_interior_envelope(part, part.interior, resolver)
    for relationship in model.relationships:
        for expression in [*relationship.point_a, *relationship.point_b]:
            resolver.expression(expression)
    return model


def empty_model(name: str = "New project") -> StudioModel:
    return StudioModel(name=name, root=Part(id="ROOT", name=name, kind="assembly"))


def build_scene(model: StudioModel | dict, project_id: str, revision: int, *, _local_root_id: str | None = None, _local_context: bool = False) -> dict[str, Any]:
    model = validate_model(model)
    if not project_id or not isinstance(project_id, str) or revision < 1:
        raise ValueError("A scene requires a project identity and positive revision")
    resolver = Resolver(model)
    for parameter in model.parameters:
        resolver.parameter(parameter.id)
    objects, meshes, dimensions, symbols, pending = [], [], [], [], []
    placements = {}
    pending_parts = []
    unknown_parameters = [parameter.id for parameter in model.parameters if resolver.values[parameter.id] is None]
    pending.extend(f"TBC parameter: {key}" for key in unknown_parameters)

    def editable(part):
        result = {}
        pairs = list(zip(("Width", "Depth", "Height"), part.size or []))
        if part.surface is not None:
            pairs += [("Width", part.surface.width),
                      ("Height" if part.surface.plane == "front" else "Depth", part.surface.span)]
        pairs += list(zip(("X", "Y", "Z"), part.position))
        for label, expression in pairs:
            parameter = resolver.parameters.get(expression) if isinstance(expression, str) else None
            if parameter is not None and parameter.expression is None:
                result[label] = parameter.id
        return result

    def raw_node(part):
        result = part.model_dump(exclude={"interior", "profile"})
        result["children"] = [raw_node(child) for child in part.children]
        result["editable"] = editable(part)
        if part.profile:
            result["profile"] = part.profile
        return result

    materials = dict(MATERIALS)
    pinned={snapshot.snapshot_id:snapshot.variant for snapshot in model.material_snapshots}
    def render_material(part):
        return "CATALOG_"+part.material_assignment if part.material_assignment is not None else part.material
    for part in _parts(model.root):
        materials.setdefault(part.material, "#dedbd4")
        if part.material_assignment is not None:
            materials[render_material(part)]=pinned[part.material_assignment].color_hex

    def walk(part, parent_origin, parent_angle, ancestors, inherited_dependencies, inherited_context=False):
        locations = [resolver.expression(value) for value in part.position]
        rotation, rotation_dependencies = resolver.expression(part.rotation)
        placement_dependencies = set(inherited_dependencies) | rotation_dependencies | set().union(*(value[1] for value in locations))
        dependencies = set(placement_dependencies)
        if rotation is None or any(value[0] is None for value in locations):
            pending.append(f"{part.name}: placement is TBC; its assembly is not drawn")
            pending_parts.append(part.id)
            return
        origin = _transform([value[0] for value in locations], parent_origin, parent_angle)
        angle = parent_angle + math.radians(rotation)
        placements[part.id] = {"origin": origin, "angle": angle, "dependencies": placement_dependencies}
        if part.surface is not None:
            expressions = [part.surface.width, 0.0, part.surface.span] if part.surface.plane == "front" else [part.surface.width, part.surface.span, 0.0]
            sizes = [resolver.expression(value) for value in expressions]
        else:
            sizes = [resolver.expression(value) for value in part.size] if part.size else []
        size_dependencies = set().union(*(item[1] for item in sizes))
        dependencies |= size_dependencies
        complete_size = sizes and all(item[0] is not None for item in sizes)
        size = [item[0] for item in sizes] if complete_size else []
        inferred = any(resolver.parameters[key].status == "inferred" for key in dependencies)
        context = inherited_context or part.context
        if sizes and not complete_size:
            pending.append(f"{part.name}: size is TBC; no fallback solid was drawn")
            pending_parts.append(part.id)
        obj = {"id": part.id, "name": part.name, "description": part.description,
               "ancestors": ancestors, "children": [child.id for child in part.children],
               "origin": origin, "rotation": math.degrees(angle), "size": size,
               "dependencies": sorted(dependencies), "inferred": inferred, "context": context,
               "evidence": [item.model_dump() for item in part.evidence], "material": part.material,
               "material_assignment":part.material_assignment,"render_material":render_material(part),
               "board_spec":part.board_spec.model_dump() if part.board_spec else None,"physical":part.physical,
               "editable": editable(part), "authority": part.authority,
               "provenance": {"kind": part.kind, "authority": part.authority,
                              "interior": part.interior.model_dump() if part.interior else None,
                              "surface": part.surface.model_dump() if part.surface else None}}
        objects.append(obj)
        if size:
            for axis, (axis_name, size_expression) in enumerate(zip(("Width", "Depth", "Height"), sizes)):
                if size[axis] <= 0:
                    continue
                first, second = [0, 0, 0], [0, 0, 0]
                second[axis] = size[axis]
                a, b = first[:], second[:]
                if axis == 0:
                    a[1] = b[1] = -100
                elif axis == 1:
                    a[0] = b[0] = -100
                else:
                    a[0] = b[0] = size[0]+100
                    a[1] = b[1] = size[1]
                dimensions.append({"id": f"{part.id}:{axis}", "owner": part.id, "axis": axis_name,
                    "value_mm": size[axis], "inferred": any(resolver.parameters[key].status == "inferred" for key in size_expression[1]),
                    "dependencies": sorted(size_expression[1]), "a": _transform(a, origin, angle), "b": _transform(b, origin, angle),
                    "structural_a": _transform(first, origin, angle), "structural_b": _transform(second, origin, angle)})
        if size and part.physical:
            if part.mesh is not None:
                vertices = [[point[axis] * size[axis] for axis in range(3)] for point in part.mesh.vertices]
                indices, edges = part.mesh.indices, part.mesh.edges
            else:
                vertices, indices, edges = _extrude(part.profile or [[0, 0], [1, 0], [1, 1], [0, 1]], size)
            meshes.append({"id": part.id, "vertices": [_transform(point, origin, angle) for point in vertices],
                           "indices": indices, "edges": edges, "material": render_material(part),
                           "context": context, "ancestors": ancestors, "inferred": inferred,
                           "physical": True, "representation": "solid"})
        elif size and part.surface is not None:
            width, depth, height = size
            vertices = ([[0, 0, 0], [width, 0, 0], [width, 0, height], [0, 0, height]]
                        if part.surface.plane == "front" else
                        [[0, 0, 0], [width, 0, 0], [width, depth, 0], [0, depth, 0]])
            meshes.append({"id": part.id, "vertices": [_transform(point, origin, angle) for point in vertices],
                           "indices": [0, 1, 2, 0, 2, 3], "edges": [[0, 1], [1, 2], [2, 3], [3, 0]],
                           "material": render_material(part), "context": context, "ancestors": ancestors,
                           "inferred": inferred, "physical": False, "representation": "source_surface",
                           "surface": part.surface.model_dump()})
        if size:
            for symbol in part.symbols:
                item = {"id": symbol.id, "owner": part.id, "kind": "opening_operation",
                    "points": [_transform([point[0]*size[0], -0.8, point[1]*size[2]], origin, angle) for point in symbol.points],
                    "pattern": symbol.pattern, "evidence": [item.model_dump() for item in symbol.evidence],
                    "owner_face": "front", "face_normal": [math.sin(angle), -math.cos(angle), 0]}
                if symbol.views:
                    item["views"] = symbol.views
                symbols.append(item)
        for child in part.children:
            walk(child, origin, angle, ancestors+[part.id], placement_dependencies, context)

    if _local_root_id is None:
        walk(model.root, [0, 0, 0], 0, [], set())
    else:
        # This is a viewport frame boundary, never an amendment to source placement.
        # The root's own axes define this local frame, independently of its
        # unresolved transform into its parent/building. Descendant transforms stay.
        frame_root=find_part(model,_local_root_id).model_copy(deep=True)
        frame_root.position=[0.,0.,0.];frame_root.rotation=0.
        walk(frame_root,[0.,0.,0.],0.,[],set(),_local_context)
    views = {key: dict(value) for key, value in GENERIC_VIEWS.items()}
    for view in model.views:
        if view.id == "AXON":
            pending.append("Source view AXON is reserved; use another source-view ID")
            continue
        record = {"direction": view.direction, "right": view.right, "up": view.up, "detail": view.label,
                  "source_document_id": view.document_id, "source_page": view.page, "source_region": view.region}
        if view.include:
            included = set(view.include)
            # Source ownership is recursive even when IDs are not path prefixes.
            for owner in view.include:
                included.update(part.id for part in _parts(find_part(model, owner)))
            record["include"] = sorted(included)
        views[view.id] = record
    for key, definition in views.items():
        eligible = set()
        toward_viewer = [-value for value in definition["direction"]]
        included = set(definition.get("include", []))
        for symbol in symbols:
            if symbol.get("views") and key != "AXON" and key not in symbol["views"]:
                continue
            if key != "AXON" and included and symbol["owner"] not in included:
                continue
            if key == "AXON" or sum(a*b for a, b in zip(symbol["face_normal"], toward_viewer)) > 0.000001:
                eligible.add(symbol["owner"])
        definition["symbols"] = sorted(eligible)
    for relationship in model.relationships:
        if _local_root_id is not None and (relationship.owner_a not in placements or relationship.owner_b not in placements):
            continue  # cross-frame witnesses have no shared known coordinate system
        if _local_root_id is not None and relationship.axis in ("X","Y"):
            continue  # global horizontal axes are not established by a local frame
        anchors = []
        dependencies = set()
        for owner, coordinates in ((relationship.owner_a, relationship.point_a),
                                   (relationship.owner_b, relationship.point_b)):
            placement = placements.get(owner)
            values = [resolver.expression(value) for value in coordinates]
            dependencies.update(set().union(*(item[1] for item in values)))
            if placement is None or any(item[0] is None for item in values):
                anchors = []
                break
            dependencies.update(placement["dependencies"])
            anchors.append(_transform([item[0] for item in values], placement["origin"], placement["angle"]))
        if len(anchors) != 2:
            pending.append(f"Relationship {relationship.label}: witness point is TBC; no substitute dimension was drawn")
            continue
        first, second = anchors
        if relationship.axis == "distance":
            value = math.dist(first, second)
            projected = second
        else:
            axis = {"X": 0, "Y": 1, "Z": 2}[relationship.axis]
            value = abs(second[axis] - first[axis])
            projected = first[:]
            projected[axis] = second[axis]
        if value <= 0.00001:
            pending.append(f"Relationship {relationship.label}: coincident or axis-normal witnesses; dimension is not drawn")
            continue
        source_value = None
        observed = resolver.parameters.get(relationship.parameter_id) if relationship.parameter_id else None
        if observed is not None:
            source_value = observed.observed_value_mm if observed.observed_value_mm is not None else resolver.parameter(observed.id)[0]
            if source_value is None:
                pending.append(f"Relationship {relationship.label}: source numeric value is TBC; current witness distance is derived")
        conflict = source_value is not None and abs(value - source_value) > 0.1
        if conflict:
            pending.append(f"Relationship {relationship.label}: source {source_value:g} mm conflicts with current witness distance {value:g} mm; geometry was not resized")
        subjects = relationship.subjects or list(dict.fromkeys([relationship.owner_a, relationship.owner_b]))
        eligible = relationship.views or ({"X": ["PLAN", "FRONT", "BACK"],
                                           "Y": ["PLAN", "RIGHT", "LEFT"],
                                           "Z": ["FRONT", "RIGHT", "BACK", "LEFT"],
                                           "distance": ["AXON"]}[relationship.axis])
        provisional = any(resolver.parameters[key].status == "inferred" for key in dependencies)
        provisional |= observed is not None and observed.status in {"inferred", "tbc"}
        dimensions.append({"id": relationship.id, "kind": "relationship", "owner": subjects[0],
                           "subjects": subjects, "views": eligible, "axis": relationship.label,
                           "measurement_axis": relationship.axis, "value_mm": round(value, 6),
                           "inferred": provisional, "dependencies": sorted(dependencies),
                           "a": first, "b": projected, "structural_a": first, "structural_b": second,
                           "anchors": {"a": {"owner": relationship.owner_a, "point": relationship.point_a},
                                       "b": {"owner": relationship.owner_b, "point": relationship.point_b}},
                           "evidence": [item.model_dump() for item in relationship.evidence],
                           "source_value_mm": source_value, "observed_value_mm": source_value,
                           "parameter_id": relationship.parameter_id, "amended": conflict})
    coordinates = [point for mesh in meshes for point in mesh["vertices"]]
    # Empty framing bounds are viewport metadata, never physical fallback geometry.
    bounds = {"min": [min(point[i] for point in coordinates) for i in range(3)] if coordinates else [0, 0, 0],
              "max": [max(point[i] for point in coordinates) for i in range(3)] if coordinates else [1, 1, 1]}
    raw_parameters = {}
    for parameter in model.parameters:
        item = parameter.model_dump()
        item["method"] = "Source observation" if parameter.status == "source" else parameter.status
        item["unit"] = "mm"
        if item["expression"] is None:
            item.pop("expression")
        raw_parameters[parameter.id] = item
    raw = {"schema": "vwc-spatial/1.0", "id": project_id, "revision": revision, "name": model.name,
           "status": "customer-review-design", "source": {"authority": "evidence-linked candidate; designed additions identified"},
           "root": raw_node(model.root), "parameters": raw_parameters, "materials": materials,
           "material_snapshots":[item.model_dump() for item in model.material_snapshots],
           "relationship_dimensions": [item.model_dump() for item in model.relationships],
           "pending": list(dict.fromkeys([*model.warnings, *pending]))}
    scene = {"project": raw, "objects": objects, "meshes": meshes, "dimensions": dimensions, "symbols": symbols,
            "views": views, "bounds": bounds, "resolved": {key: value for key, value in resolver.values.items() if value is not None},
            "pending_parts": pending_parts, "geometry_hash": hashlib.sha256(json.dumps(meshes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
    references={}
    for drawing in model.drawings:
        for reference in drawing.reference_annotations:
            references[reference.control_id]={'value_mm':reference.value_mm,'label':reference.label,
                'method':reference.method,'confidence':reference.confidence,'owner_id':reference.owner_id,'estimate_id':reference.estimate_id}
    if references:scene['reference_parameters']=references
    if _local_root_id is not None:
        return scene
    local_frames={}

    def collect_frames(part, ancestors, inherited_unknown, inherited_context=False, inherited_orientation_known=True):
        locations=[resolver.expression(value) for value in part.position]
        rotation,rotation_dependencies=resolver.expression(part.rotation)
        orientation_known=inherited_orientation_known and rotation is not None
        own_unknown=rotation is None or any(value[0] is None for value in locations)
        unknown=set(inherited_unknown)
        for value,dependencies in [*locations,(rotation,rotation_dependencies)]:
            if value is None:unknown.update(key for key in dependencies if resolver.parameter(key)[0] is None)
        if own_unknown:
            local=build_scene(model,project_id,revision,_local_root_id=part.id,_local_context=inherited_context)
            included={obj["id"] for obj in local["objects"]}
            unresolved_geometry=local["pending_parts"]
            issues=["Global placement is TBC. This preview uses the selected assembly's own origin and axes; it does not establish a building location."]
            if not local["meshes"]:issues.append("This local frame contains no fully specified solid or source surface.")
            if unresolved_geometry:issues.append("Some descendants still have unresolved size or placement and remain omitted: "+", ".join(unresolved_geometry[:20]))
            local_frames[part.id]={"root_id":part.id,"owner_id":part.id,"label":part.name,
                "coordinate_system":"assembly-local","origin":[0.,0.,0.],"global_placement_known":False,
                "orientation_known":orientation_known,"root_relative_orientation_known":rotation is not None,"ancestors":list(ancestors),
                "reason":"unresolved_global_placement","status":"available" if local["meshes"] else "incomplete",
                "omitted_parent_transform":{"position":list(part.position),"rotation":part.rotation,
                    "resolved_position":[value[0] for value in locations],"resolved_rotation":rotation,
                    "ancestor_ids":list(ancestors),"unresolved_parameter_ids":sorted(unknown)},
                "local_axes":"Root assembly axes; all ancestor transforms omitted.",
                "objects":local["objects"],"meshes":local["meshes"],"dimensions":local["dimensions"],
                "symbols":local["symbols"],"bounds":local["bounds"],"pending_parts":local["pending_parts"],
                "geometry_hash":local["geometry_hash"],"issues":issues,
                "excluded_relationship_ids":[r.id for r in model.relationships if r.owner_a not in included or r.owner_b not in included or r.axis in ("X","Y")]}
        for child in part.children:collect_frames(child,[*ancestors,part.id],unknown,inherited_context or part.context,orientation_known)

    collect_frames(model.root,[],set())
    scene["local_frames"]=local_frames
    from .drawing_quality import attach_drawings
    return attach_drawings(model, scene)


def set_parameter(model: StudioModel | dict, parameter_id: str, value: float) -> StudioModel:
    result = validate_model(model).model_copy(deep=True)
    parameter = next((item for item in result.parameters if item.id == parameter_id), None)
    if parameter is None:
        raise ValueError("Unknown parameter")
    if parameter.expression is not None:
        raise ValueError("A derived measurement is read-only; edit its controlling parameter")
    expression_names(value)
    # These are controls of an owned generated layout, not independent panel
    # measurements. Regenerate so conditional parts (for example a zero back)
    # and the recorded settings change together.
    for cabinet in _parts(result.root):
        if cabinet.interior is None:
            continue
        controls = _interior_parameter_ids(cabinet.id)
        field = next((field for field, key in controls.items() if key == parameter_id), None)
        if field is None:
            continue
        settings = cabinet.interior.model_dump()
        settings[field] = float(value)
        regenerated = design_interior(result, cabinet.id, settings)
        previous = {item.id: item for item in result.parameters}
        for item in regenerated.parameters:
            if item.id in controls.values():
                prior = previous[item.id]
                # Preserve earlier explicit edits and evidence without assigning
                # source authority to a designed construction dimension.
                item.status = "user" if item.id == parameter_id else prior.status
                item.evidence = prior.evidence
                item.observed_value_mm = prior.observed_value_mm
        return validate_model(regenerated)
    if parameter.observed_value_mm is None and parameter.status == "source":
        parameter.observed_value_mm = parameter.value_mm
    parameter.value_mm = float(value)
    parameter.status = "user"
    return validate_model(result)


def _interior_parameter_ids(cabinet_id: str) -> dict[str, str]:
    key = "IN_" + hashlib.sha256(cabinet_id.encode()).hexdigest()[:12]
    return {"thickness_mm": key + "_T", "back_mm": key + "_B", "clearance_mm": key + "_G"}


def _validate_interior_envelope(cabinet: Part, spec: InteriorSpec, resolver: Resolver):
    """Validate stored layout controls before using them to check its fit."""
    values = spec.model_dump()
    for field, key in _interior_parameter_ids(cabinet.id).items():
        parameter = resolver.parameters.get(key)
        if parameter is None or parameter.status not in {"designed", "user"}:
            raise ValueError(f"Interior control {key} must be an owned designed or user parameter")
        value = resolver.parameter(key)[0]
        if value is None or not math.isclose(value, values[field], rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"Interior control {key} is inconsistent with InteriorSpec.{field}; regenerate the interior")
        values[field] = value
    # Revalidate limits on the actual resolved controls. Do not repair a saved
    # payload during validation/rendering or fall back to stale settings.
    effective_spec = InteriorSpec.model_validate(values)
    return _validate_interior_fit(cabinet, effective_spec, resolver)


def _validate_interior_fit(cabinet: Part, spec: InteriorSpec, resolver: Resolver):
    if cabinet.size is None:
        raise ValueError("Choose a cabinet with width, depth and height")
    dimensions = [resolver.expression(value)[0] for value in cabinet.size]
    if any(value is None for value in dimensions):
        raise ValueError("Cabinet dimensions are TBC; resolve them before designing the interior")
    w, d, h = dimensions
    t, back, gap = spec.thickness_mm, spec.back_mm, spec.clearance_mm
    if min(w-2*t, d-back-gap, h-2*t) <= 0:
        raise ValueError("Panel thickness or clearance exceeds the cabinet envelope")
    if spec.drawers and (spec.shelves or spec.dividers):
        raise ValueError("Choose drawers or shelves/dividers in this initial interior layout")
    bay_width = (w-2*t-spec.dividers*t)/(spec.dividers+1)
    shelf_space = (h-2*t-spec.shelves*t)/(spec.shelves+1)
    if bay_width <= 2*gap or shelf_space <= gap:
        raise ValueError("The requested shelves or dividers leave no usable clear space")
    if spec.drawers:
        drawer_height = (h-2*t-(spec.drawers+1)*gap)/spec.drawers
        if drawer_height <= 2*t or w-2*t-2*gap <= 2*t or d-back-2*gap <= 2*t:
            raise ValueError("Drawer count, thickness or clearance leaves no usable drawer box")
    return dimensions


def design_interior(model: StudioModel | dict, cabinet_id: str, spec: dict | InteriorSpec) -> StudioModel:
    result = validate_model(model).model_copy(deep=True)
    cabinet = find_part(result, cabinet_id)
    kind = cabinet.kind.lower().replace("-", "_").replace(" ", "_")
    def is_context(part, inherited=False):
        context = inherited or part.context
        if part.id == cabinet_id:
            return context
        for child in part.children:
            found = is_context(child, context)
            if found is not None:
                return found
        return None
    if is_context(result.root):
        raise ValueError("Context geometry cannot be converted into a cabinet interior")
    converting_envelope = kind == "assembly" and cabinet.size is not None and cabinet.surface is None
    if kind not in {"cabinet", "vanity", "wardrobe", "cupboard", "base_cabinet", "wall_cabinet", "tall_cabinet"} and not converting_envelope:
        raise ValueError("Select a cabinet, vanity, wardrobe or cupboard assembly")
    settings = InteriorSpec.model_validate(spec.model_dump() if isinstance(spec, InteriorSpec) else spec)
    _validate_interior_fit(cabinet, settings, Resolver(result))
    prefix = cabinet.id + "/INTERIOR"
    old = next((child for child in cabinet.children if child.id == prefix), None)
    if old is not None and old.authority != "designed":
        raise ValueError("This ID belongs to source geometry and cannot be replaced by an interior design")
    # Generated dimensions remain linked to the cabinet envelope after edits.
    controls = _interior_parameter_ids(cabinet.id)
    generated_ids = set(controls.values())
    for parameter in result.parameters:
        if parameter.id in generated_ids and (old is None or parameter.status not in {"designed", "user"}):
            raise ValueError("An interior parameter ID belongs to existing source data and cannot be overwritten")
    result.parameters = [parameter for parameter in result.parameters if parameter.id not in generated_ids]
    result.parameters.extend(Parameter(id=key, label=f"{cabinet.name} interior {key[-1]}",
                                       value_mm=getattr(settings, field), status="designed")
                             for field, key in controls.items())
    t, b, g = (controls[field] for field in ("thickness_mm", "back_mm", "clearance_mm"))
    w, d, h = (f"({value})" for value in cabinet.size)
    children = []
    old_panels={part.id:part for part in _parts(old)} if old is not None else {}
    def panel(suffix, name, position, size):
        if suffix in {"LEFT","RIGHT"} or suffix.startswith("DIVIDER-") or suffix.endswith(("-LEFT","-RIGHT")):
            axes=("Z","Y","X")
        elif suffix=="BACK" or suffix.endswith(("-FRONT","-BACK")):
            axes=("X","Z","Y")
        else:axes=("X","Y","Z")
        board=BoardSpec(length_axis=axes[0],width_axis=axes[1],thickness_axis=axes[2])
        previous=old_panels.get(f"{prefix}/{suffix}")
        if previous is not None and previous.board_spec is not None:
            if previous.board_spec.thickness_axis!=board.thickness_axis:
                raise ValueError("Existing board thickness axes are incompatible with this generated layout")
            board=previous.board_spec.model_copy(deep=True)
        children.append(Part(id=f"{prefix}/{suffix}", name=name, kind="panel", position=position,
                             size=size, physical=True, material="DESIGNED", authority="designed",
                             material_assignment=previous.material_assignment if previous is not None else None,
                             board_spec=board,
                             description="User-designed interior; board dimensions are not a CNC machining specification."))
        if previous is not None:children[-1].material=previous.material
    panel("LEFT", "Left carcass panel / 左侧板", [0, 0, 0], [t, d, h])
    panel("RIGHT", "Right carcass panel / 右侧板", [f"{w}-{t}", 0, 0], [t, d, h])
    panel("BOTTOM", "Bottom panel / 底板", [t, 0, 0], [f"{w}-2*{t}", d, t])
    panel("TOP", "Top panel / 顶板", [t, 0, f"{h}-{t}"], [f"{w}-2*{t}", d, t])
    if settings.back_mm:
        panel("BACK", "Back panel / 背板", [t, f"{d}-{b}", t], [f"{w}-2*{t}", b, f"{h}-2*{t}"])
    bays = settings.dividers+1
    bay_width = f"({w}-2*{t}-{settings.dividers}*{t})/{bays}"
    for i in range(settings.dividers):
        x = f"{t}+({i+1})*({bay_width})+{i}*{t}"
        panel(f"DIVIDER-{i+1}", f"Divider {i+1} / 竖隔板 {i+1}", [x, 0, t], [t, f"{d}-{b}", f"{h}-2*{t}"])
    shelf_gap = f"({h}-2*{t}-{settings.shelves}*{t})/{settings.shelves+1}"
    for level in range(settings.shelves):
        z = f"{t}+({level+1})*({shelf_gap})+{level}*{t}"
        for bay in range(bays):
            x = f"{t}+{bay}*(({bay_width})+{t})+{g}"
            panel(f"SHELF-{level+1}-{bay+1}", f"Shelf {level+1}.{bay+1} / 层板 {level+1}.{bay+1}",
                  [x, 0, z], [f"({bay_width})-2*{g}", f"{d}-{b}-{g}", t])
    if settings.drawers:
        drawer_height = f"({h}-2*{t}-{settings.drawers+1}*{g})/{settings.drawers}"
        drawer_width = f"{w}-2*{t}-2*{g}"
        drawer_depth = f"{d}-{b}-2*{g}"
        for index in range(settings.drawers):
            x, y = f"{t}+{g}", g
            z = f"{t}+{g}+{index}*(({drawer_height})+{g})"
            stem = f"DRAWER-{index+1}"
            panel(stem+"-BASE", f"Drawer {index+1} bottom / 抽屉 {index+1} 底板", [x, y, z], [drawer_width, drawer_depth, t])
            panel(stem+"-LEFT", f"Drawer {index+1} left / 抽屉 {index+1} 左侧", [x, y, f"({z})+{t}"], [t, drawer_depth, f"({drawer_height})-{t}"])
            panel(stem+"-RIGHT", f"Drawer {index+1} right / 抽屉 {index+1} 右侧", [f"({x})+({drawer_width})-{t}", y, f"({z})+{t}"], [t, drawer_depth, f"({drawer_height})-{t}"])
            panel(stem+"-FRONT", f"Drawer {index+1} front / 抽屉 {index+1} 前板", [f"({x})+{t}", y, f"({z})+{t}"], [f"({drawer_width})-2*{t}", t, f"({drawer_height})-{t}"])
            panel(stem+"-BACK", f"Drawer {index+1} back / 抽屉 {index+1} 后板", [f"({x})+{t}", f"({y})+({drawer_depth})-{t}", f"({z})+{t}"], [f"({drawer_width})-2*{t}", t, f"({drawer_height})-{t}"])
    interior = Part(id=prefix, name="Designed interior / 设计的内部结构", kind="interior",
                    description="Explicit user design. Hardware, joints and machining allowances remain unspecified.",
                    authority="designed", children=children)
    cabinet.children = [child for child in cabinet.children if child.id != prefix] + [interior]
    cabinet.interior = settings
    cabinet.physical = False
    from .materials import _check_thickness
    snapshots={snapshot.snapshot_id:snapshot.variant for snapshot in result.material_snapshots}
    resolver=Resolver(result)
    for part in children:
        if part.material_assignment is not None:_check_thickness(part,snapshots[part.material_assignment],resolver)
    if converting_envelope:
        original_kind = cabinet.kind
        cabinet.kind = "cabinet"
        cabinet.authority = "user"
        cabinet.description += ("\nUser-designed cabinet envelope continued from original kind=" + original_kind
                                + "; source dimensions and evidence retained. / 用户将已有外形用于柜体设计，原始类型及尺寸证据保留。")
    warning = "Designed cabinet interiors require hardware/joinery review; they are not CNC-ready machining instructions."
    if warning not in result.warnings:
        result.warnings.append(warning)
    return validate_model(result)
