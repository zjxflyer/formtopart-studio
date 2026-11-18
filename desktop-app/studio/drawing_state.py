"""Semantic exterior identity used to invalidate source 2D after design edits."""
from __future__ import annotations

import hashlib
import json

from .models import StudioModel, expression_names
from .paths import filesystem_path

_CABINET_KINDS = {"assembly", "cabinet", "vanity", "wardrobe", "cupboard", "base_cabinet", "wall_cabinet", "tall_cabinet"}


def _canonical_numbers(value):
    # Pydantic defaults and JSON reconstruction may spell the same number as
    # integer or float. This identity concerns geometry, not that spelling.
    if isinstance(value, dict):
        return {key: _canonical_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_numbers(item) for item in value]
    if type(value) in (int, float):
        return float(value) if value else 0.0
    return value


def semantic_fingerprint(model: StudioModel | dict) -> str:
    """Hash geometry, source mapping, ownership and material while ignoring prose.

    Generated interior geometry and its private controls do not change the
    exterior observations. A sized cabinet/assembly remains the same logical
    envelope when the interior workflow changes its solid representation.
    """
    model = StudioModel.model_validate(model.model_dump() if isinstance(model, StudioModel) else model)
    referenced = set()

    def scalar(value):
        referenced.update(expression_names(value))
        return value

    def part(node, parent=None):
        if parent and node.id == parent + "/INTERIOR" and node.authority == "designed" and node.kind == "interior":
            return None
        envelope = node.kind in _CABINET_KINDS and node.size is not None and node.surface is None and not node.context
        record = {"id": node.id, "kind": "cabinet_envelope" if envelope else node.kind,
                "position": [scalar(value) for value in node.position], "rotation": scalar(node.rotation),
                "size": [scalar(value) for value in node.size] if node.size else None,
                "physical": False if envelope else node.physical, "context": node.context,
                "material": node.material, "profile": node.profile,
                "surface": ({"plane": node.surface.plane, "width": scalar(node.surface.width), "span": scalar(node.surface.span)} if node.surface else None),
                "symbols": [symbol.model_dump(exclude={"evidence"}) for symbol in sorted(node.symbols, key=lambda item: item.id)],
                "children": [item for child in sorted(node.children, key=lambda item: item.id) if (item := part(child, node.id)) is not None]}
        # Absent mesh keeps historical source-review fingerprints byte-compatible.
        if node.mesh is not None:
            record["mesh"] = node.mesh.model_dump()
        return record

    root = part(model.root)
    relationships = []
    for relation in sorted(model.relationships, key=lambda item: item.id):
        record = relation.model_dump(exclude={"label", "evidence"})
        for value in [*relation.point_a, *relation.point_b]:
            scalar(value)
        if relation.parameter_id:
            referenced.add(relation.parameter_id)
        relationships.append(record)
    by_id = {parameter.id: parameter for parameter in model.parameters}
    # Include ordinary observation controls. An IN_* value referenced by exterior
    # geometry or an ordinary derived parameter is not an ignorable private knob.
    referenced.update(parameter.id for parameter in model.parameters if not parameter.id.startswith("IN_"))
    queue = list(referenced)
    while queue:
        parameter = by_id.get(queue.pop())
        if parameter is not None and parameter.expression is not None:
            dependencies = expression_names(parameter.expression) - referenced
            referenced.update(dependencies)
            queue.extend(dependencies)
    parameters = [{"id": parameter.id, "value_mm": parameter.value_mm, "expression": parameter.expression,
                   "unresolved": parameter.status == "tbc"}
                  for parameter in sorted(model.parameters, key=lambda item: item.id) if parameter.id in referenced]
    views = [view.model_dump(exclude={"label"}) for view in sorted(model.views, key=lambda item: item.id)]
    state = _canonical_numbers({"root": root, "parameters": parameters, "views": views, "relationships": relationships})
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_2d_model(model: StudioModel | dict, documents=None, *, verify_files=True) -> StudioModel:
    """Recover/check host-pinned original2D facts without reverting the3D design."""
    model=StudioModel.model_validate(model.model_dump() if isinstance(model,StudioModel) else model)
    binding=model.source_2d_binding
    if binding is None:return model.model_copy(deep=True)
    from .drafting import drawing_hash
    pins={pin.view_id:pin for pin in binding.drawing_pins}
    if set(pins)!={view.id for view in model.drawings}:
        raise ValueError('Original2D binding does not match the complete saved drawing group')
    for view in model.drawings:
        pin=pins[view.id]
        if drawing_hash(view)!=pin.drawing_sha256 or view.review_hash!=pin.review_sha256 or view.review_status!='passed':
            raise ValueError('Original2D drawing or its checked review changed after spatial generation')
    references={}
    for view in model.drawings:
        for ref in view.reference_annotations:
            row=references.setdefault(ref.control_id,{'owner_id':ref.owner_id,'axis':ref.axis,'value_mm':ref.value_mm,'digests':[]})
            if any(row[key]!=getattr(ref,key) for key in ('owner_id','axis','value_mm')):
                raise ValueError('Shared original2D reference identity disagrees')
            row['digests'].append(ref.provenance_digest)
    if {a.control_id for a in binding.reference_adoptions}!=set(references):
        raise ValueError('Original2D reference adoption coverage changed')
    for adoption in binding.reference_adoptions:
        expected=references[adoption.control_id]
        if any(getattr(adoption,key)!=expected[key] for key in ('owner_id','axis','value_mm')) or sorted(adoption.reference_provenance_sha256)!=sorted(expected['digests']):
            raise ValueError('Original2D reference adoption differs from its exact drawn provenance')
    original=StudioModel.model_validate({**json.loads(binding.semantic_model_json),'drawings':[v.model_dump() for v in model.drawings]})
    if semantic_fingerprint(original)!=binding.semantic_fingerprint:
        raise ValueError('Original2D semantic identity changed')
    if documents is not None:
        docs={item['id']:item for item in documents}
        if len(docs)!=len(documents) or set(docs)!={pin.document_id for pin in binding.source_pins}:
            raise ValueError('Original2D complete source document set changed')
        for pin in binding.source_pins:
            document=docs.get(pin.document_id)
            if document is None or document['sha256']!=pin.sha256 or document['page_count']!=pin.page_count:
                raise ValueError('Original2D source document identity changed')
            if verify_files and hashlib.sha256(filesystem_path(document['local_path']).read_bytes()).hexdigest()!=pin.sha256:
                raise ValueError('Original2D source PDF bytes changed')
    return original
