"""Strict local catalog, pinned project variants and explicit board-axis contracts."""
from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

BOARD_KINDS=frozenset({"panel","board","shelf","divider","back","side","top","bottom",
    "drawer_board","drawer_panel","carcass_panel","back_panel","side_panel","top_panel","bottom_panel"})


def board_kind(kind:str) -> bool:
    return kind.lower().replace("-","_").replace(" ","_") in BOARD_KINDS


class MaterialRecord(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False,strict=True)


class StockSize(MaterialRecord):
    length_mm: float=Field(gt=0,le=100000)
    width_mm: float=Field(gt=0,le=100000)


class MaterialVariant(MaterialRecord):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False,strict=True,frozen=True)
    id: str=Field(default_factory=lambda:uuid4().hex,min_length=1,max_length=120)
    version: int=Field(default=1,ge=1)
    code: str=Field(min_length=1,max_length=100)
    name: str=Field(min_length=1,max_length=200)
    color_hex: str=Field(default="#d9c8ad",pattern=r"^#[0-9A-Fa-f]{6}$")
    color_name: str=Field(default="",max_length=120)
    category: Literal["sheet","stone","metal","glass","finish","other"]="sheet"
    substrate: str=Field(default="",max_length=300)
    finish: str=Field(default="",max_length=300)
    thickness_mm: float|None=Field(default=None,gt=0,le=1000)
    stock_sizes: list[StockSize]=Field(default_factory=list,max_length=100)
    supplier: str=Field(default="",max_length=200)
    sku: str=Field(default="",max_length=120)
    stock_count: float|None=Field(default=None,ge=0,le=1e9)
    grain: Literal["none","length","width"]="none"
    active: bool=True


def snapshot_hash(variant: MaterialVariant|dict) -> str:
    record=MaterialVariant.model_validate(variant.model_dump() if isinstance(variant,MaterialVariant) else variant)
    def canonical(value):
        if isinstance(value,float) and value.is_integer():return int(value)
        if isinstance(value,list):return [canonical(item) for item in value]
        if isinstance(value,dict):return {key:canonical(item) for key,item in value.items()}
        return value
    return hashlib.sha256(json.dumps(canonical(record.model_dump(mode="json")),sort_keys=True,
        ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()


class MaterialSnapshot(MaterialRecord):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False,strict=True,frozen=True)
    snapshot_id: str=Field(pattern=r"^[a-f0-9]{64}$")
    variant: MaterialVariant

    @model_validator(mode="after")
    def bound_variant(self):
        if self.snapshot_id!=snapshot_hash(self.variant):
            raise ValueError("A pinned material snapshot does not match its content hash")
        return self


def make_material_snapshot(variant: MaterialVariant|dict) -> MaterialSnapshot:
    record=MaterialVariant.model_validate(variant.model_dump() if isinstance(variant,MaterialVariant) else variant)
    return MaterialSnapshot(snapshot_id=snapshot_hash(record),variant=record)


class BoardSpec(MaterialRecord):
    length_axis: Literal["X","Y","Z"]
    width_axis: Literal["X","Y","Z"]
    thickness_axis: Literal["X","Y","Z"]
    grain: Literal["none","length","width"]="none"
    allowance_length_mm: float=Field(default=0,ge=0,le=10000)
    allowance_width_mm: float=Field(default=0,ge=0,le=10000)
    edges: list[str]=Field(default_factory=lambda:["0","0","0","0"],min_length=4,max_length=4)
    profile: Literal["rectangle"]="rectangle"
    machining_notes: str=Field(default="",max_length=4000)

    @model_validator(mode="after")
    def explicit_axes_and_edges(self):
        if len({self.length_axis,self.width_axis,self.thickness_axis})!=3:
            raise ValueError("Board length, width and thickness axes must be distinct")
        if any(not edge.strip() or len(edge)>120 for edge in self.edges):
            raise ValueError("Provide four explicit edge codes, using 0 for no edge band")
        return self
