"""Strict evidence-linked proposals shared by the local studio and AI gateway."""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, model_serializer
from .drawing_models import DrawingView
from .material_models import BoardSpec, MaterialSnapshot

Scalar = float | str
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")


def expression_names(value: Scalar) -> set[str]:
    """Inspect a limited arithmetic expression without executing Python."""
    if isinstance(value, bool):
        raise ValueError("A geometry value cannot be a boolean")
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or abs(value) > 100000:
            raise ValueError("Geometry values must be finite and within 100 metres")
        return set()
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError("Invalid arithmetic expression")
    try:
        tree = ast.parse(value, mode="eval")
    except (SyntaxError, RecursionError):
        raise ValueError("Invalid arithmetic expression") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > 160:
        raise ValueError("Arithmetic expression is too complex")
    permitted = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load,
                 ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd)
    names = set()
    for item in nodes:
        if not isinstance(item, permitted):
            raise ValueError("Only numbers, parameter names and + - * / are allowed")
        if isinstance(item, ast.Constant):
            if type(item.value) not in (int, float) or not math.isfinite(item.value) or abs(item.value) > 100000:
                raise ValueError("Invalid arithmetic constant")
        if isinstance(item, ast.Name):
            if not _IDENTIFIER.fullmatch(item.id):
                raise ValueError("Invalid parameter identifier")
            names.add(item.id)
    return names


def _finite_vector(values: list[float], length: int) -> list[float]:
    if len(values) != length or any(not math.isfinite(x) for x in values):
        raise ValueError(f"Expected {length} finite values")
    return values


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class EvidenceRef(StrictModel):
    document_id: str = Field(min_length=1, max_length=120)
    page: int = Field(ge=1, le=10000)
    text: str = Field(default="", max_length=3000)
    region: list[float] | None = None

    @field_validator("region")
    @classmethod
    def valid_region(cls, value):
        if value is not None:
            _finite_vector(value, 4)
            if not (0 <= value[0] < value[2] <= 1 and 0 <= value[1] < value[3] <= 1):
                raise ValueError("Evidence region must be normalized [left, top, right, bottom]")
        return value


class Parameter(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(default="", max_length=200)
    value_mm: float | None = None
    expression: str | None = None
    status: Literal["source", "inferred", "user", "designed", "tbc"] = "tbc"
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=50)
    observed_value_mm: float | None = None

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("Parameter IDs must be arithmetic-safe identifiers")
        return value

    @model_validator(mode="after")
    def check_value(self):
        if self.status == "tbc" and (self.value_mm is not None or self.expression is not None):
            raise ValueError("TBC parameters cannot contain a numeric fallback or expression")
        if self.value_mm is not None and self.expression is not None:
            raise ValueError("A parameter cannot contain both a value and an expression")
        if self.status != "tbc" and self.value_mm is None and self.expression is None:
            raise ValueError("A known parameter needs a value or expression")
        if self.value_mm is not None:
            expression_names(self.value_mm)
        if self.expression is not None:
            expression_names(self.expression)
        if self.observed_value_mm is not None:
            expression_names(self.observed_value_mm)
        return self


class OpeningSymbol(StrictModel):
    id: str = Field(min_length=1, max_length=160)
    points: list[list[float]] = Field(min_length=2, max_length=256)
    pattern: Literal["dashed", "source-dash-segment"] = "dashed"
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=50)
    views: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("points")
    @classmethod
    def valid_points(cls, value):
        for point in value:
            _finite_vector(point, 2)
            if any(x < 0 or x > 1 for x in point):
                raise ValueError("Operation marks use normalized owner-face coordinates")
        return value


class InteriorSpec(StrictModel):
    thickness_mm: float = Field(default=18, ge=1, le=100)
    back_mm: float = Field(default=6, ge=0, le=50)
    shelves: int = Field(default=2, ge=0, le=20)
    dividers: int = Field(default=0, ge=0, le=10)
    drawers: int = Field(default=0, ge=0, le=20)
    clearance_mm: float = Field(default=2, ge=0, le=50)


class SourceSurface(StrictModel):
    """A measured source contour with no claim about construction thickness."""
    plane: Literal["front", "plan"]
    width: Scalar
    span: Scalar

    @field_validator("width", "span")
    @classmethod
    def valid_expression(cls, value):
        expression_names(value)
        return value


class NormalizedMesh(StrictModel):
    """Bounded fixture geometry expressed in its owner's unit bounding box."""
    vertices: list[list[float]] = Field(min_length=3, max_length=4096)
    indices: list[int] = Field(min_length=3, max_length=24576)
    edges: list[list[int]] = Field(default_factory=list, max_length=8192)

    @model_validator(mode="after")
    def valid_geometry(self):
        for point in self.vertices:
            _finite_vector(point, 3)
            if any(value < 0 or value > 1 for value in point):
                raise ValueError("Fixture mesh vertices use normalized local XYZ coordinates")
        count = len(self.vertices)
        if len(self.indices) % 3 or any(index < 0 or index >= count for index in self.indices):
            raise ValueError("Fixture triangles require complete in-range vertex indices")
        if any(len(set(self.indices[start:start+3])) != 3 for start in range(0, len(self.indices), 3)):
            raise ValueError("Fixture triangles require three distinct indices")
        if any(len(edge) != 2 or edge[0] == edge[1]
               or any(index < 0 or index >= count for index in edge) for edge in self.edges):
            raise ValueError("Fixture edges require two distinct in-range vertex indices")
        return self


class Part(StrictModel):
    id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="assembly", min_length=1, max_length=60)
    description: str = Field(default="", max_length=2000)
    position: list[Scalar] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    rotation: Scalar = 0.0
    size: list[Scalar] | None = Field(default=None, min_length=3, max_length=3)
    physical: bool = False
    context: bool = False
    material: str = Field(default="WD01", min_length=1, max_length=80)
    material_assignment: str | None = Field(default=None,pattern=r"^[a-f0-9]{64}$")
    board_spec: BoardSpec | None = None
    children: list["Part"] = Field(default_factory=list, max_length=500)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=50)
    authority: Literal["source", "user", "designed"] = "user"
    symbols: list[OpeningSymbol] = Field(default_factory=list, max_length=100)
    interior: InteriorSpec | None = None
    profile: list[list[float]] | None = Field(default=None, min_length=3, max_length=256)
    mesh: NormalizedMesh | None = None
    surface: SourceSurface | None = None

    @field_validator("position", "size")
    @classmethod
    def valid_expressions(cls, values):
        if values is not None:
            for value in values:
                expression_names(value)
        return values

    @field_validator("rotation")
    @classmethod
    def valid_rotation(cls, value):
        expression_names(value)
        return value

    @model_validator(mode="after")
    def physical_needs_size(self):
        if self.mesh is not None and (not self.physical or self.size is None
                                      or self.profile is not None or self.surface is not None
                                      or self.board_spec is not None):
            raise ValueError("A fixture mesh requires a sized physical solid, separate from profiles, source surfaces and cut boards")
        if self.board_spec is not None and (not self.physical or self.children or self.surface is not None or self.context):
            raise ValueError("An explicit board specification requires a physical leaf, not a source surface/context/envelope")
        if self.surface is not None:
            if self.physical:
                raise ValueError("A source surface is a drawing representation, not a physical solid")
            if self.size is not None or self.profile is not None:
                raise ValueError("A source surface uses width/span only; put a sized envelope on its parent")
            if self.symbols and self.surface.plane != "front":
                raise ValueError("Opening symbols require a front surface, not a plan surface")
        if self.physical and self.size is None:
            raise ValueError("A physical part needs three size expressions")
        if self.symbols and self.size is None and not (self.surface and self.surface.plane == "front"):
            raise ValueError("Operation symbols need a sized owner")
        if self.profile is not None:
            for point in self.profile:
                _finite_vector(point, 2)
                if any(x < 0 or x > 1 for x in point):
                    raise ValueError("Profiles use normalized local XY coordinates")
        return self


class SourceView(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=200)
    kind: Literal["plan", "elevation"] = "elevation"
    page: int = Field(default=1, ge=1, le=10000)
    document_id: str = Field(default="", max_length=120)
    region: list[float] | None = None
    direction: list[float] = Field(default_factory=lambda: [0.0, 1.0, 0.0], min_length=3, max_length=3)
    right: list[float] = Field(default_factory=lambda: [1.0, 0.0, 0.0], min_length=3, max_length=3)
    up: list[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0], min_length=3, max_length=3)
    include: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("region")
    @classmethod
    def valid_region(cls, value):
        return EvidenceRef.valid_region(value)

    @model_validator(mode="after")
    def valid_basis(self):
        vectors = [self.direction, self.right, self.up]
        for vector in vectors:
            _finite_vector(vector, 3)
            if abs(sum(x*x for x in vector) - 1) > 0.001:
                raise ValueError("View directions must be unit vectors")
        if any(abs(sum(a*b for a, b in zip(vectors[i], vectors[j]))) > 0.001
               for i in range(3) for j in range(i+1, 3)):
            raise ValueError("View directions must be orthogonal")
        a, b = self.right, self.up
        cross = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
        if any(abs(cross[i] + self.direction[i]) > 0.001 for i in range(3)):
            raise ValueError("View basis would mirror the drawing")
        return self


class Relationship(StrictModel):
    """A source measurement between two explicit local-owner witness points.

    X/Y/Z measure world-axis separation; distance measures the actual point pair.
    Neither endpoint is inferred from an owner's bounding box.
    """
    id: str = Field(min_length=1, max_length=160)
    label: str = Field(default="Relationship", min_length=1, max_length=200)
    owner_a: str = Field(min_length=1, max_length=160)
    owner_b: str = Field(min_length=1, max_length=160)
    point_a: list[Scalar] = Field(min_length=3, max_length=3)
    point_b: list[Scalar] = Field(min_length=3, max_length=3)
    axis: Literal["X", "Y", "Z", "distance"] = "distance"
    parameter_id: str | None = None
    subjects: list[str] = Field(default_factory=list, max_length=500)
    views: list[str] = Field(default_factory=list, max_length=100)
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=50)

    @field_validator("point_a", "point_b")
    @classmethod
    def valid_points(cls, values):
        for value in values:
            expression_names(value)
        return values


class Source2DDrawingPin(StrictModel):
    view_id: str
    drawing_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    review_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Source2DDocumentPin(StrictModel):
    document_id: str
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    page_count: int = Field(ge=1)


class Reference3DAdoption(StrictModel):
    control_id: str
    parameter_id: str
    owner_id: str
    axis: Literal['width','depth','height']
    value_mm: float = Field(gt=0,le=100000)
    reference_provenance_sha256: list[str] = Field(min_length=1,max_length=100)


class Source2DBinding(StrictModel):
    """Host-owned immutable 2D semantics, separate from derived spatial design."""
    schema_version: Literal['formtopart-source-2d-binding/1'] = 'formtopart-source-2d-binding/1'
    semantic_model_json: str = Field(min_length=2,max_length=4000000)
    semantic_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    semantic_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    drawing_pins: list[Source2DDrawingPin] = Field(min_length=1,max_length=100)
    source_pins: list[Source2DDocumentPin] = Field(min_length=1,max_length=8)
    reference_adoptions: list[Reference3DAdoption] = Field(default_factory=list,max_length=2000)

    @model_validator(mode='after')
    def valid_snapshot(self):
        if hashlib.sha256(self.semantic_model_json.encode('utf-8')).hexdigest()!=self.semantic_sha256:
            raise ValueError('Original2D semantic binding hash changed')
        original=json.loads(self.semantic_model_json)
        if not isinstance(original,dict) or 'drawings' in original or 'source_2d_binding' in original:
            raise ValueError('Original2D binding must contain one nonrecursive semantic snapshot without drawings')
        if len({p.view_id for p in self.drawing_pins})!=len(self.drawing_pins) or len({p.document_id for p in self.source_pins})!=len(self.source_pins):
            raise ValueError('Original2D binding has duplicate identities')
        if len({p.control_id for p in self.reference_adoptions})!=len(self.reference_adoptions) or len({p.parameter_id for p in self.reference_adoptions})!=len(self.reference_adoptions):
            raise ValueError('Original2D reference adoptions must be unique')
        return self


class StudioModel(StrictModel):
    name: str = Field(default="Untitled design", min_length=1, max_length=200)
    parameters: list[Parameter] = Field(default_factory=list, max_length=2000)
    root: Part
    views: list[SourceView] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=300)
    relationships: list[Relationship] = Field(default_factory=list, max_length=1000)
    drawings: list[DrawingView] = Field(default_factory=list, max_length=100)
    requires_source_drawings: bool = False
    material_snapshots: list[MaterialSnapshot] = Field(default_factory=list,max_length=2000)
    source_2d_binding: Source2DBinding | None = None

    @model_serializer(mode='wrap')
    def serialize_optional_binding(self,handler):
        record=handler(self)
        if self.source_2d_binding is None:record.pop('source_2d_binding',None)
        return record

    @model_validator(mode="after")
    def valid_graph(self):
        snapshots={item.snapshot_id:item for item in self.material_snapshots}
        if len(snapshots)!=len(self.material_snapshots):
            raise ValueError("Duplicate pinned material snapshot IDs")
        parameters = {p.id: p for p in self.parameters}
        if len(parameters) != len(self.parameters):
            raise ValueError("Duplicate parameter IDs")
        references = {p.id: expression_names(p.expression) if p.expression is not None else set()
                      for p in self.parameters}
        all_names = set(parameters)
        for key, names in references.items():
            if names - all_names:
                raise ValueError(f"Parameter {key} references unknown parameters: {sorted(names-all_names)}")
        visited, active = set(), set()
        def visit(key):
            if key in active:
                raise ValueError(f"Cyclic parameter: {key}")
            if key in visited:
                return
            active.add(key)
            for other in references[key]:
                visit(other)
            active.remove(key)
            visited.add(key)
        for key in parameters:
            visit(key)
        seen, symbols = set(), set()
        mesh_vertices = mesh_indices = 0
        stack = [(self.root, 0)]
        while stack:
            part, depth = stack.pop()
            if part.id in seen:
                raise ValueError(f"Duplicate part ID: {part.id}")
            if len(seen) >= 1000 or depth > 40:
                raise ValueError("Assembly exceeds supported size or depth")
            seen.add(part.id)
            if part.mesh is not None:
                mesh_vertices += len(part.mesh.vertices)
                mesh_indices += len(part.mesh.indices)
                if mesh_vertices > 50000 or mesh_indices > 300000:
                    raise ValueError("Project fixture meshes exceed the supported geometry budget")
            if part.material_assignment is not None and part.material_assignment not in snapshots:
                raise ValueError(f"Part {part.id} references an unknown pinned material snapshot")
            source_expressions = [part.surface.width, part.surface.span] if part.surface else []
            for expression in [*part.position, part.rotation, *(part.size or []), *source_expressions]:
                missing = expression_names(expression) - all_names
                if missing:
                    raise ValueError(f"Part {part.id} references unknown parameters: {sorted(missing)}")
            for symbol in part.symbols:
                if symbol.id in symbols:
                    raise ValueError(f"Duplicate operation symbol ID: {symbol.id}")
                symbols.add(symbol.id)
            stack.extend((child, depth+1) for child in part.children)
        view_ids = [v.id for v in self.views]
        if len(set(view_ids)) != len(view_ids):
            raise ValueError("Duplicate source view IDs")
        for view in self.views:
            if set(view.include) - seen:
                raise ValueError(f"View {view.id} references unknown parts")
        relationships = set()
        known_views = set(view_ids) | {"AXON", "PLAN", "FRONT", "RIGHT", "BACK", "LEFT"}
        size_ids = {f"{owner}:{axis}" for owner in seen for axis in range(3)}
        for record in self.relationships:
            if record.id in relationships or record.id in size_ids:
                raise ValueError(f"Duplicate dimension ID: {record.id}")
            relationships.add(record.id)
            if record.owner_a not in seen or record.owner_b not in seen:
                raise ValueError(f"Relationship {record.id} references an unknown witness owner")
            if set(record.subjects) - seen:
                raise ValueError(f"Relationship {record.id} references unknown subjects")
            if set(record.views) - known_views:
                raise ValueError(f"Relationship {record.id} references unknown views")
            if record.parameter_id is not None and record.parameter_id not in parameters:
                raise ValueError(f"Relationship {record.id} references an unknown observed parameter")
            for expression in [*record.point_a, *record.point_b]:
                missing = expression_names(expression) - all_names
                if missing:
                    raise ValueError(f"Relationship {record.id} references unknown witness parameters: {sorted(missing)}")
        drawing_ids = set(); reference_controls={}
        parts_by_id={}
        def reference_owners(part):
            parts_by_id[part.id]=part
            for child in part.children:reference_owners(child)
        reference_owners(self.root)
        for drawing in self.drawings:
            if drawing.id in drawing_ids or drawing.id not in set(view_ids):
                raise ValueError("A source drawing needs a unique registered source view")
            drawing_ids.add(drawing.id)
            if set(drawing.owner_ids) - seen or any(p.owner_id not in seen for p in drawing.primitives):
                raise ValueError("A source drawing references an unknown semantic owner")
            if any(({guard.owner_id, *guard.related_owner_ids} - seen) for guard in drawing.edit_guards):
                raise ValueError("A source edit guard references an unknown semantic owner")
            if set(drawing.parameter_snapshot) - all_names:
                raise ValueError("A source drawing snapshot references unknown parameters")
            view = next(v for v in self.views if v.id == drawing.id)
            if drawing.document_id != view.document_id or drawing.page != view.page:
                raise ValueError("A source drawing and its registered view cite different source pages")
            for reference in drawing.reference_annotations:
                if reference.owner_id not in seen or reference.control_id not in parameters or parameters[reference.control_id].status!='tbc':
                    raise ValueError('Customer reference must remain separate from a known original TBC control and owner')
                if set(reference.source_parameter_ids)-all_names:
                    raise ValueError('Customer reference cites an unknown original source parameter')
                provenance=reference.provenance
                digest=hashlib.sha256(json.dumps(provenance,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
                if digest!=reference.provenance_digest or provenance.get('source_sha256')!=drawing.source_sha256 or provenance.get('source_parameter_id')!=reference.control_id:
                    raise ValueError('Customer reference provenance differs from its original source or control')
                estimate=provenance.get('estimate',{})
                if any(estimate.get(key)!=getattr(reference,key) for key in ('estimate_id','control_id','owner_id','axis','view_id','label','method','reason','confidence')):
                    raise ValueError('Customer reference differs from its recorded proposal')
                if provenance.get('arithmetic',{}).get('rounded_value_mm')!=reference.value_mm:
                    raise ValueError('Customer reference differs from its recorded calculation')
                previous=reference_controls.setdefault(reference.control_id,reference.value_mm)
                if previous!=reference.value_mm:
                    raise ValueError('Shared customer reference controls must agree across views')
        if self.source_2d_binding is not None:
            original=json.loads(self.source_2d_binding.semantic_model_json)
            for parameter in original.get('parameters',[]):
                if parameter['id'] not in parameters or parameters[parameter['id']].model_dump()!=parameter:
                    raise ValueError('Derived3D must preserve every original2D parameter and its evidence')
            def source_owners(node,parent=None):
                yield node,parent
                for child in node.get('children',[]):yield from source_owners(child,node['id'])
            parents={part['id']:parent for part,parent in source_owners(self.root.model_dump())}
            for owner,parent in source_owners(original['root']):
                current=parts_by_id.get(owner['id'])
                interior_conversion=(current is not None and owner['kind']=='assembly' and current.kind=='cabinet'
                    and current.authority=='user' and current.size is not None and current.interior is not None)
                if (current is None or parents.get(owner['id'])!=parent or
                        any(current.model_dump()[key]!=owner[key] for key in ('name','evidence')) or
                        current.kind!=owner['kind'] and not interior_conversion):
                    raise ValueError('Derived3D must preserve original2D owner identity, lineage and evidence')
            original_views={v['id']:v for v in original.get('views',[])}
            if set(original_views)!={v.id for v in self.views} or any(getattr(v,key)!=original_views[v.id][key]
                    for v in self.views for key in ('document_id','page','region','kind','label')):
                raise ValueError('Derived3D must preserve the original2D source-view identities')
            for adoption in self.source_2d_binding.reference_adoptions:
                parameter=parameters.get(adoption.parameter_id)
                if parameter is None or parameter.status!='designed' or parameter.value_mm!=adoption.value_mm or parameter.expression is not None:
                    raise ValueError('Derived3D reference aliases must preserve their adopted2D value and designed authority')
        return self
