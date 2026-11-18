"""Isolated customer-reference proposals; never source parameters or path edits.

This module deliberately does not import drawing_models/models.  Native drawings
can therefore use ReferenceAnnotation without an import cycle.
"""
from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReferenceMethod = Literal['source_choice', 'exact_calculation', 'calibrated_ratio', 'design_reference']
ReferenceAxis = Literal['width', 'depth', 'height']
ReferenceOrientation = Literal['horizontal', 'vertical']


class ReferenceRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, strict=True)


class ReferenceSourceRef(ReferenceRecord):
    document_id: str = Field(min_length=1, max_length=120)
    page: int = Field(ge=1, le=10000)
    region: list[float] = Field(min_length=4, max_length=4)
    text: str = Field(min_length=1, max_length=3000)

    @field_validator('region')
    @classmethod
    def normalized_region(cls, values):
        if not (all(math.isfinite(x) for x in values) and
                0 <= values[0] < values[2] <= 1 and 0 <= values[1] < values[3] <= 1):
            raise ValueError('Reference evidence requires a nonempty normalized source region')
        return values

    @field_validator('text', 'document_id')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Reference evidence must be nonblank')
        return value


class ReferenceEstimate(ReferenceRecord):
    estimate_id: str = Field(min_length=1, max_length=160)
    control_id: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,79}$')
    owner_id: str = Field(min_length=1, max_length=160)
    axis: ReferenceAxis
    view_id: str = Field(min_length=1, max_length=80)
    orientation: ReferenceOrientation
    label: str = Field(min_length=1, max_length=80)
    method: ReferenceMethod
    anchor_a_id: str = Field(min_length=1, max_length=180)
    anchor_b_id: str = Field(min_length=1, max_length=180)
    source_parameter_id: str | None = Field(default=None, max_length=80)
    expression: str | None = Field(default=None, max_length=500)
    design_value_mm: float | None = Field(default=None, gt=0, le=100000)
    calibration_anchor_a_id: str | None = Field(default=None, max_length=180)
    calibration_anchor_b_id: str | None = Field(default=None, max_length=180)
    rounding_mm: Literal[0.1, 0.5, 1, 5, 10] = 1
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=3000)
    source_refs: list[ReferenceSourceRef] = Field(min_length=1, max_length=50)

    @field_validator('rounding_mm', mode='before')
    @classmethod
    def numeric_rounding(cls, value):
        if type(value) not in (float, int):
            raise ValueError('Reference rounding must be a numeric quantum')
        return value

    @field_validator('label')
    @classmethod
    def customer_label(cls, value):
        if (not re.search(r'[A-Za-z]', value) or any(ord(c) < 32 or ord(c) > 126 for c in value)
                or len(value.split()) > 12 or re.search(r'\b(?:TBC|INF|unresolved)\b', value, re.I)):
            raise ValueError('Reference labels require concise customer English without uncertainty/debug tokens')
        return value.strip()

    @field_validator('estimate_id', 'owner_id', 'view_id', 'anchor_a_id', 'anchor_b_id', 'reason')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Reference identities and reasons must be nonblank')
        return value

    @model_validator(mode='after')
    def method_fields(self):
        if self.anchor_a_id == self.anchor_b_id:
            raise ValueError('A reference needs two distinct structural anchors')
        expected = {
            'source_choice': {'source_parameter_id'},
            'exact_calculation': {'expression'},
            'calibrated_ratio': {'source_parameter_id', 'calibration_anchor_a_id', 'calibration_anchor_b_id'},
            'design_reference': {'design_value_mm'},
        }[self.method]
        optional = {'source_parameter_id', 'expression', 'design_value_mm',
                    'calibration_anchor_a_id', 'calibration_anchor_b_id'}
        actual = {name for name in optional if getattr(self, name) is not None}
        if actual != expected:
            raise ValueError('Reference method fields must match the declared derivation method')
        if self.method == 'calibrated_ratio' and self.calibration_anchor_a_id == self.calibration_anchor_b_id:
            raise ValueError('Calibration requires distinct structural anchors')
        return self


class ReferencePlan(ReferenceRecord):
    estimates: list[ReferenceEstimate] = Field(max_length=3000)


class ReferenceAnnotation(ReferenceRecord):
    """A fully resolved, host-validated dimension; coordinates are native PDF points."""
    estimate_id: str
    control_id: str
    owner_id: str
    axis: ReferenceAxis
    view_id: str
    orientation: ReferenceOrientation
    label: str
    value_mm: float = Field(gt=0, le=100000)
    unrounded_value_mm: float = Field(gt=0, le=100000)
    rounding_mm: Literal[0.1, 0.5, 1, 5, 10]
    point_a: list[float] = Field(min_length=2, max_length=2)
    point_b: list[float] = Field(min_length=2, max_length=2)
    anchor_a_id: str
    anchor_b_id: str
    method: ReferenceMethod
    source_parameter_ids: list[str]
    expression: str | None
    calibration_proof: dict[str, Any] | None
    confidence: float = Field(ge=0, le=1)
    reason: str
    evidence: list[ReferenceSourceRef]
    provenance: dict[str, Any]
    provenance_digest: str = Field(pattern=r'^[a-f0-9]{64}$')

    @field_validator('point_a', 'point_b')
    @classmethod
    def finite_points(cls, values):
        if any(not math.isfinite(x) or abs(x) > 100000 for x in values):
            raise ValueError('Reference endpoints require finite native coordinates')
        return values
