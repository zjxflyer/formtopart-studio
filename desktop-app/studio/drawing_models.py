"""Safe source-coordinate 2D records; no arbitrary SVG, scripts or metric guesses."""
from __future__ import annotations

import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal["geometry", "dimension", "opening", "material", "view_reference", "context", "texture"]


class DrawingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class PathCommand(DrawingRecord):
    op: Literal["M", "L", "C", "Z"]
    points: list[float] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def shape(self):
        if len(self.points) != {"M": 2, "L": 2, "C": 6, "Z": 0}[self.op]:
            raise ValueError("Invalid safe path command")
        if any(not math.isfinite(p) or abs(p) > 100000 for p in self.points):
            raise ValueError("Invalid source coordinate")
        return self


class DrawingClip(DrawingRecord):
    commands: list[PathCommand] = Field(min_length=1, max_length=5000)
    fill_rule: Literal["nonzero", "evenodd"] = "nonzero"

    @model_validator(mode="after")
    def first_move(self):
        if self.commands[0].op!="M":raise ValueError("A clipping path must start with a move")
        return self


class DrawingPrimitive(DrawingRecord):
    id: str = Field(min_length=1, max_length=180)
    source_id: str = Field(min_length=1, max_length=180)
    source_ids: list[str] = Field(default_factory=list, max_length=5000)
    source_style_id: str = Field(default="", max_length=100)
    owner_id: str = Field(default="ROOT", min_length=1, max_length=160)
    role: Role = "geometry"
    kind: Literal["path", "text"]
    commands: list[PathCommand] = Field(default_factory=list, max_length=5000)
    text: str = Field(default="", max_length=3000)
    x: float = 0
    y: float = 0
    font_size: float = Field(default=10, gt=0, le=200)
    text_length: float | None = Field(default=None, gt=0, le=100000)
    rotation: float = Field(default=0, ge=-360, le=360)
    stroke_width: float = Field(default=.5, gt=0, le=20)
    stroke: bool = True
    stroke_color: Literal["ink", "white"] = "ink"
    dash: list[float] = Field(default_factory=list, max_length=32)
    fill: Literal["none", "white", "black"] = "none"
    fill_rgb: str | None = Field(default=None,pattern=r"^#[0-9a-f]{6}$")
    fill_rule: Literal["nonzero", "evenodd"] = "nonzero"
    clips: list[DrawingClip] = Field(default_factory=list, max_length=32)
    bbox: list[float] = Field(min_length=4, max_length=4)

    @field_validator("bbox")
    @classmethod
    def box(cls, v):
        if any(not math.isfinite(x) or abs(x) > 100000 for x in v) or v[2] < v[0] or v[3] < v[1]:
            raise ValueError("Invalid source primitive bounds")
        return v

    @field_validator("dash")
    @classmethod
    def dash_values(cls, v):
        if any(not math.isfinite(x) or x < 0 or x > 10000 for x in v):
            raise ValueError("Invalid dash values")
        return v

    @model_validator(mode="after")
    def content(self):
        if self.kind == "path" and (not self.commands or self.commands[0].op != "M"):
            raise ValueError("A source path needs a move and geometry")
        if self.kind == "text" and (not self.text or self.commands):
            raise ValueError("A source text record needs plain text only")
        return self


class TextFragment(DrawingRecord):
    """Readable source label fragments positioned relative to one native text record."""
    text: str = Field(min_length=1, max_length=3000)
    offset: list[float] = Field(min_length=2, max_length=2)
    font_size: float | None = Field(default=None, ge=1, le=200)
    text_length: float | None = Field(default=None, gt=0, le=100000)

    @field_validator("offset")
    @classmethod
    def finite_offset(cls,v):
        if any(not math.isfinite(x) or abs(x)>100000 for x in v):
            raise ValueError("Invalid source label fragment offset")
        return v


class DrawingRule(DrawingRecord):
    """Sparse source selection; matches IDs OR (region/style/kind predicates)."""
    primitive_ids: list[str] = Field(default_factory=list, max_length=20000)
    region: list[float] | None = None
    region_match: Literal["center", "contained", "intersects"] = "center"
    style_id: str | None = None
    kind: Literal["path", "text"] | None = None
    source_kind: Literal["line", "rect", "curve"] | None = None
    include: bool | None = None
    role: Role | None = None
    owner_id: str | None = None
    text_override: str | None = Field(default=None, max_length=3000)
    text_offset: list[float] | None = Field(default=None, min_length=2, max_length=2)
    font_size: float | None = Field(default=None, ge=1, le=200)
    text_length: float | None = Field(default=None, gt=0, le=100000)
    text_fragments: list[TextFragment] = Field(default_factory=list, max_length=20)

    @field_validator("text_offset")
    @classmethod
    def text_offset_values(cls,v):
        if v is not None and any(not math.isfinite(x) or abs(x)>100000 for x in v):
            raise ValueError("Invalid source text offset")
        return v

    @field_validator("region")
    @classmethod
    def region_values(cls, v):
        if v is not None and (len(v) != 4 or not 0 <= v[0] < v[2] <= 1 or not 0 <= v[1] < v[3] <= 1):
            raise ValueError("Rule regions use normalized crop coordinates")
        return v

    @model_validator(mode="after")
    def selector(self):
        adjusts_text=bool(self.text_fragments) or any(value is not None for value in (self.text_override,self.text_offset,self.font_size,self.text_length))
        if adjusts_text and (len(self.primitive_ids)!=1 or self.text_override==""):
            raise ValueError("A text correction must identify exactly one source primitive")
        if self.text_fragments and any(value is not None for value in (self.text_override,self.text_offset,self.font_size,self.text_length)):
            raise ValueError("Source fragments use their own offsets and font sizes")
        return self


class SourceEditGuard(DrawingRecord):
    """Source carriers shared with other owners need a coordinated edit."""
    owner_id: str = Field(min_length=1, max_length=160)
    related_owner_ids: list[str] = Field(min_length=1, max_length=1000)
    source_primitive_ids: list[str] = Field(min_length=1, max_length=20000)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("related_owner_ids", "source_primitive_ids")
    @classmethod
    def unique_references(cls, values):
        if len(set(values)) != len(values) or any(not value.strip() or len(value) > 180 for value in values):
            raise ValueError("Source edit guards need unique nonempty source/owner references")
        return values

    @model_validator(mode="after")
    def separate_owners(self):
        if not self.owner_id.strip() or not self.reason.strip() or self.owner_id in self.related_owner_ids:
            raise ValueError("A source edit guard must identify a distinct related owner and a reason")
        if any(len(value) > 160 for value in self.related_owner_ids):
            raise ValueError("Invalid related semantic owner identity")
        return self


class DrawingViewPlan(DrawingRecord):
    view_id: str = Field(min_length=1, max_length=80)
    default_include: bool = True
    default_owner_id: str = Field(default="ROOT", min_length=1, max_length=160)
    source_region: list[float] | None = None
    rules: list[DrawingRule] = Field(default_factory=list, max_length=1000)
    pending: list[str] = Field(default_factory=list, max_length=100)
    edit_guards: list[SourceEditGuard] = Field(default_factory=list, max_length=1000)

    @field_validator("source_region")
    @classmethod
    def region_values(cls, v):
        return DrawingRule.region_values(v)


class DrawingPlan(DrawingRecord):
    views: list[DrawingViewPlan] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=100)


from .reference_models import ReferenceAnnotation


class DrawingView(DrawingRecord):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=200)
    kind: Literal["plan", "elevation"]
    representation: Literal["source", "amended_design"] = "source"
    owner_ids: list[str] = Field(default_factory=list, max_length=1000)
    document_id: str = Field(min_length=1, max_length=120)
    page: int = Field(ge=1)
    region: list[float] = Field(min_length=4, max_length=4)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: float = Field(gt=0, le=10000)
    height: float = Field(gt=0, le=10000)
    primitives: list[DrawingPrimitive] = Field(default_factory=list, max_length=60000)
    pending: list[str] = Field(default_factory=list, max_length=200)
    edit_guards: list[SourceEditGuard] = Field(default_factory=list, max_length=1000)
    parameter_snapshot: dict[str, float | None] = Field(default_factory=dict, max_length=2000)
    semantic_snapshot: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    review_status: Literal["pending", "passed", "failed"] = "pending"
    review_issues: list[str] = Field(default_factory=list, max_length=200)
    review_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    annotation_margin: float = Field(default=0,ge=0,le=24)
    review_notes: list[str] = Field(default_factory=list,max_length=32)
    reference_annotations: list[ReferenceAnnotation] = Field(default_factory=list,max_length=3000)

    @field_validator("review_notes")
    @classmethod
    def bounded_notes(cls,values):
        if any(not item.strip() or len(item)>1600 for item in values):
            raise ValueError("Drawing review notes must be nonblank and bounded")
        return values

    @field_validator("region")
    @classmethod
    def region_values(cls, v):
        return DrawingRule.region_values(v)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [p.id for p in self.primitives]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate drawing primitive IDs")
        controls=[item.control_id for item in self.reference_annotations]
        if len(controls)!=len(set(controls)):
            raise ValueError("Duplicate reference dimension control in a drawing")
        for item in self.reference_annotations:
            if item.view_id!=self.id or any(not 0<=p[0]<=self.width or not 0<=p[1]<=self.height for p in (item.point_a,item.point_b)):
                raise ValueError("Reference dimension must cite anchors inside its own drawing")
        return self
