"""Local material library and immutable, revision-owned assignments; no AI calls."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
from contextlib import contextmanager

from .material_models import BoardSpec, MaterialVariant, board_kind, make_material_snapshot
from .repository import Conflict, NotFound


class MaterialLibrary:
    def __init__(self,path:Path):
        from .paths import filesystem_path
        self.path=filesystem_path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS variants(id TEXT PRIMARY KEY,version INTEGER NOT NULL,data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS sample_variants(thickness INTEGER PRIMARY KEY,material_id TEXT NOT NULL)")

    @contextmanager
    def _connect(self):
        db=sqlite3.connect(self.path,timeout=15)
        try:
            with db:yield db
        finally:db.close()

    def list(self,search="",include_inactive=False):
        with self._connect() as db:rows=db.execute("SELECT data FROM variants ORDER BY id").fetchall()
        variants=[MaterialVariant.model_validate(json.loads(row[0])) for row in rows]
        needle=search.casefold().strip()
        return sorted([v for v in variants if (include_inactive or v.active) and
            (not needle or needle in " ".join([v.code,v.name,v.color_name,v.supplier,v.sku,v.substrate,v.finish]).casefold())],
            key=lambda v:(v.code.casefold(),v.id))

    def get(self,material_id):
        with self._connect() as db:row=db.execute("SELECT data FROM variants WHERE id=?",(material_id,)).fetchone()
        if row is None:raise NotFound("Material not found / 未找到材料")
        return MaterialVariant.model_validate(json.loads(row[0]))

    def create(self,payload):
        data=payload.model_dump() if isinstance(payload,MaterialVariant) else dict(payload)
        data.pop("id",None);data.pop("version",None)
        variant=MaterialVariant.model_validate(data)
        try:
            with self._connect() as db:db.execute("INSERT INTO variants VALUES(?,?,?)",(variant.id,variant.version,variant.model_dump_json()))
        except sqlite3.IntegrityError:raise Conflict("Material ID already exists / 材料 ID 已存在") from None
        return variant

    def update(self,material_id,payload,expected_version):
        changes=payload.model_dump() if isinstance(payload,MaterialVariant) else dict(payload)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT version,data FROM variants WHERE id=?",(material_id,)).fetchone()
            if row is None:raise NotFound("Material not found / 未找到材料")
            if row[0]!=expected_version:raise Conflict("Material changed; reload before saving / 材料已更改，请重新加载后保存")
            if changes.get("id",material_id)!=material_id or changes.get("version",expected_version)!=expected_version:
                raise ValueError("Material identity/version cannot be overwritten")
            merged={**json.loads(row[1]),**changes,"id":material_id,"version":expected_version+1}
            variant=MaterialVariant.model_validate(merged)
            db.execute("UPDATE variants SET version=?,data=? WHERE id=?",(variant.version,variant.model_dump_json(),material_id))
        return variant

    def seed_sample_materials(self):
        result=[]
        for thickness in (18,16,6):
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row=db.execute("SELECT v.data FROM sample_variants s JOIN variants v ON v.id=s.material_id WHERE s.thickness=?",(thickness,)).fetchone()
                if row:variant=MaterialVariant.model_validate(json.loads(row[0]))
                else:
                    variant=MaterialVariant(code=f"SAMPLE-PLY-{thickness}",
                    name=f"Sample plywood {thickness} mm / 示例夹板 {thickness} 毫米",
                    color_name="Sample natural / 示例原木色",substrate="Sample plywood; not an identified customer product",
                    thickness_mm=float(thickness),stock_sizes=[{"length_mm":2440.,"width_mm":1220.}],grain="length")
                    db.execute("INSERT INTO variants VALUES(?,?,?)",(variant.id,variant.version,variant.model_dump_json()))
                    db.execute("INSERT INTO sample_variants VALUES(?,?)",(thickness,variant.id))
            result.append(variant)
        return result

    def seed_prepared_materials(self, variants):
        """Install trusted bundled examples once, retaining all local edits."""
        records = [MaterialVariant.model_validate(value) for value in variants]
        with self._connect() as db:
            for variant in records:
                db.execute("INSERT OR IGNORE INTO variants VALUES(?,?,?)",
                           (variant.id, variant.version, variant.model_dump_json()))
        return [self.get(variant.id) for variant in records]


def _context_ids(root):
    result=set()
    def walk(part,inherited=False):
        context=inherited or part.context
        if context:result.add(part.id)
        for child in part.children:walk(child,context)
    walk(root);return result


def _check_thickness(part,variant,resolver):
    if part.board_spec is None:return
    if variant.thickness_mm is None:raise ValueError("Choose a material variant with an explicit board thickness")
    thickness=resolver.expression(part.size[{"X":0,"Y":1,"Z":2}[part.board_spec.thickness_axis]])[0]
    if thickness is not None and not math.isclose(thickness,variant.thickness_mm,rel_tol=0,abs_tol=1e-6):
        raise ValueError(f"Material thickness is incompatible with board {part.id}; change the board layout explicitly")


def assign_material(model,part_ids,variant):
    from .geometry import validate_model,find_part,Resolver
    result=validate_model(model).model_copy(deep=True)
    selected=list(part_ids)
    if not selected or len(selected)!=len(set(selected)) or len(selected)>1000:
        raise ValueError("Choose unique explicit target parts")
    variant=MaterialVariant.model_validate(variant.model_dump() if isinstance(variant,MaterialVariant) else variant)
    if not variant.active:raise ValueError("An archived material cannot be newly assigned")
    parts=[find_part(result,part_id) for part_id in selected]
    context=_context_ids(result.root);resolver=Resolver(result)
    for part in parts:
        if part.id in context:raise ValueError("Room context is not a material assignment target")
        _check_thickness(part,variant,resolver)
    snapshot=make_material_snapshot(variant)
    if snapshot.snapshot_id not in {s.snapshot_id for s in result.material_snapshots}:result.material_snapshots.append(snapshot)
    for part in parts:
        if part.material_assignment is None and part.board_spec is not None and part.board_spec.grain=="none":
            part.board_spec=part.board_spec.model_copy(update={"grain":variant.grain})
        part.material_assignment=snapshot.snapshot_id
    return validate_model(result)


def set_board_spec(model,part_id,spec):
    return set_board_specs(model, {part_id: spec})


def set_board_specs(model, specs, *, check_stock=True):
    from .geometry import _parts, validate_model, Resolver
    result = validate_model(model).model_copy(deep=True)
    parts = {part.id: part for part in _parts(result.root)}
    context = _context_ids(result.root)
    snapshots = {snapshot.snapshot_id: snapshot.variant for snapshot in result.material_snapshots}
    resolver = Resolver(result)
    for part_id, spec in specs.items():
        part = parts.get(part_id)
        if part is None:
            raise ValueError("Unknown component")
        if not part.physical or part.children or part.surface is not None or part.id in context:
            raise ValueError("Choose an explicit physical leaf board")
        if part.board_spec is None and not board_kind(part.kind):
            raise ValueError("A generic physical solid is not an explicit board")
        if part.profile is not None:
            raise ValueError("Only rectangular boards are supported by this cutting list")
        part.board_spec = BoardSpec.model_validate(spec.model_dump() if isinstance(spec, BoardSpec) else spec)
        variant = snapshots.get(part.material_assignment)
        if check_stock and variant is not None and variant.category != "finish":
            _check_thickness(part, variant, resolver)
    return validate_model(result)


def clear_material(model,part_ids):
    """Explicitly unassign only named parts, retaining source codes/specs/snapshots."""
    from .geometry import validate_model,find_part
    result=validate_model(model).model_copy(deep=True);selected=list(part_ids)
    if not selected or len(selected)!=len(set(selected)) or len(selected)>1000:
        raise ValueError("Choose unique explicit target parts")
    parts=[find_part(result,part_id) for part_id in selected];context=_context_ids(result.root)
    if any(part.id in context for part in parts):raise ValueError("Room context is not a material assignment target")
    for part in parts:part.material_assignment=None
    return validate_model(result)
