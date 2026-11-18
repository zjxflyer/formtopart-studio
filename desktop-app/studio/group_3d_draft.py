"""Verify group-owned 2D evidence and read isolated 3D review drafts."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

from .api_drawing_workflow import _source_identity, content_hash
from .drafting import drawing_hash
from .drawing_state import semantic_fingerprint
from .drawing_workflow import inventory_identity
from .generate_3d import _checked_source, _owner_identity, build_review_draft_scene
from .geometry import _parts, build_scene, validate_model
from .grouped_2d import _pinned_group_ledger, _plan_matches_row, _read_plan
from .models import StudioModel
from .paths import extended_windows_path
from .repository import NotFound
from .working_results import read_working_artifact


@dataclass(frozen=True)
class GroupDraftSource:
    model: StudioModel
    label: str
    checked: bool
    correspondence: list[dict]
    sha256: str


def verify_group_draft_match(destination, destination_documents, donor, donor_documents):
    """Compare original evidence across projects without remapping view IDs."""
    def document_set(documents):
        return sorted((doc["sha256"], doc["page_count"], doc["media_type"]) for doc in documents)

    def view_identity(view):
        return (view["source_sha256"], view["page"], view["kind"], view.get("sheet"), view.get("view_number"),
                view.get("callout"), view.get("sight_direction"), " ".join(view["label"].casefold().split()))

    def view_records(source):
        identities = {view["view_id"]: view_identity(view) for view in source.correspondence}
        actual = {drawing.id: drawing.region for drawing in source.model.drawings}
        result = {identities[view["view_id"]]: (identities.get(view.get("plan_view_id")), view["region"], actual[view["view_id"]])
                  for view in source.correspondence}
        if len(result) != len(source.correspondence):
            raise ValueError("The selected groups have ambiguous source view identities")
        return result

    def crops_match(a, b):
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
        return intersection > 0 and intersection >= (area_a + area_b - intersection) / 2

    if (document_set(destination_documents) != document_set(donor_documents)
            or not any(doc["media_type"] == "application/pdf" for doc in donor_documents)):
        raise ValueError("The two groups must use the same original customer PDF")
    target_views, donor_views = view_records(destination), view_records(donor)
    if target_views.keys() != donor_views.keys():
        raise ValueError("The two groups must show the same plan and numbered elevations on the original PDF")
    for key, (plan, source_crop, drawing_crop) in target_views.items():
        donor_plan, donor_source_crop, donor_drawing_crop = donor_views[key]
        if (plan != donor_plan or not crops_match(source_crop, donor_source_crop)
                or not crops_match(drawing_crop, donor_drawing_crop)):
            raise ValueError("The selected group crops do not cover the same area of the original PDF")


def _path_identity(path):
    return Path(extended_windows_path(str(path))) if os.name == "nt" else path


def _resolve(path):
    return _path_identity(_path_identity(path).resolve())


def _owned_file(directory, filename, limit):
    path = _resolve(directory / filename)
    if path.parent != directory or path.name != filename or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("A drawing review file is missing or outside the project run")
    return path.read_bytes()


def _owned_run(repository, project_id, token, *parts):
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise ValueError("Invalid project run ID")
    root = repository.directory(project_id)
    path = _path_identity((root / "workflow-runs" / token).joinpath(*parts))
    directory = _resolve(path)
    if directory != path:
        raise ValueError("Drawing review run is outside its owned directory")
    return directory


def group_draft_source(repository, project, source_job, group_id):
    project_id, documents = project["id"], project["documents"]
    if (source_job.get("project_id") != project_id or not source_job.get("grouped_2d")
            or source_job.get("status") not in ("ready", "needs_review", "failed", "cancelled")):
        raise ValueError("Select a completed 2D drawing group")
    row = next((row for row in source_job.get("groups_2d", []) if row["id"] == group_id), None)
    if not row or row["status"] not in ("ready", "needs_review") or not row.get("view_ids"):
        raise ValueError("A complete 2D drawing group is required for a 3D review draft")
    project_root = _path_identity(repository.directory(project_id))
    if not documents or any(not _resolve(Path(doc["local_path"])).is_relative_to(project_root) for doc in documents):
        raise ValueError("The selected group does not own its original PDF")
    source_hash = _source_identity(documents)
    plan_path = repository.grouped_2d_plan_path(project_id)
    original_job_id, groups = _read_plan(plan_path, project_id, documents)
    group = groups.get(group_id)
    if group is None or not _plan_matches_row(group, row, original_job_id, source_job):
        raise ValueError("The saved group no longer matches the original PDF mapping")

    ledger = _pinned_group_ledger(plan_path, project_id, documents, group, row)
    cycle = ledger.snapshot()["latest_cycle"] if ledger else None
    if not cycle or cycle["state"] != "reviewed" or cycle["number"] != row.get("cycle_count"):
        raise ValueError("The selected 2D group has no complete recorded drawing cycle")
    cycle_number = cycle["number"]
    run_id = cycle["metadata"].get("run_id", "")
    history = row.get("artifact_run_ids") or [source_job["id"].split(".", 1)[1]]
    token = next((token for token in history if run_id == f"{project_id}.{token}.{group_id}"), None)
    if token is None:
        raise ValueError("The drawing cycle belongs to a different group run")
    folder = _owned_run(repository, project_id, token, "groups", group_id)
    model_blob = _owned_file(folder, "candidate-model.json", 32 * 1024 * 1024)
    model = validate_model(json.loads(model_blob))
    receipt = json.loads(_owned_file(folder, "workflow-receipt.json", 8 * 1024 * 1024))
    checked = row.get("accepted") is True
    if (receipt.get("schema") != "vwc-autonomous2d/1" or receipt.get("source_set_sha256") != source_hash
            or receipt.get("accepted") is not checked or cycle["review"].get("accepted") is not checked
            or receipt.get("latest_complete_output_cycle") != cycle_number or model.source_2d_binding is not None):
        raise ValueError("The complete drawing receipt no longer agrees with the group")
    planned = {v.id: (v.document_id, v.page, v.kind) for v in group.index.views}
    modeled = {v.id: (v.document_id, v.page, v.kind) for v in model.views}
    drawn = {v.id: (v.document_id, v.page, v.kind) for v in model.drawings}
    document_pins = {doc["id"]: doc["sha256"] for doc in documents}
    fingerprint = semantic_fingerprint(model)
    hashes = [drawing_hash(view) for view in model.drawings]
    if (not planned or planned != modeled or planned != drawn or len(drawn) != len(model.drawings)
            or set(drawn) != set(row["view_ids"]) or len(drawn) != receipt.get("view_count")
            or any(view.representation != "source" or view.semantic_snapshot != fingerprint
                   or view.source_sha256 != document_pins.get(view.document_id)
                   or view.review_hash != digest or (view.review_status == "passed") != checked
                   for view, digest in zip(model.drawings, hashes))):
        raise ValueError("The group model or drawing identities differ from the reviewed set")
    inventory = json.loads(_owned_file(folder, "native-inventory.json", 128 * 1024 * 1024))
    plan = json.loads(_owned_file(folder, f"cycle-{cycle_number}-plan.json", 8 * 1024 * 1024))
    candidate = content_hash({"inventory": inventory_identity(inventory), "plan": plan, "drawings": hashes})
    reports = [report for report in receipt.get("reports", [])
               if report.get("bindings", {}).get("candidate_sha256") == candidate]
    if (candidate != cycle["candidate_sha256"] or not reports or content_hash(reports) != cycle["review"]["report_sha256"]
            or any(report["bindings"].get("project_id") != project_id or report["bindings"].get("run_id") != run_id
                   or report["bindings"].get("source_set_sha256") != source_hash for report in reports)):
        raise ValueError("The group candidate no longer matches its independent review")

    manifest = json.loads(_owned_file(folder, f"cycle-{cycle_number}-working-result.json", 1024 * 1024))
    artifacts = manifest.get("artifacts", [])
    published = {(artifact["artifact_id"], artifact["view_id"], artifact["sha256"]) for artifact in receipt["artifacts"]}
    available = set()
    for artifact in artifacts:
        name, view_id, digest = artifact["artifact_id"], artifact["view_id"], artifact["sha256"]
        match = re.fullmatch(rf"cycle-{cycle_number}-[a-f0-9]{{20}}\.(pdf|png)", name)
        if not match or artifact["path"] != name or (name, view_id, digest) not in published:
            raise ValueError("The working drawing files differ from the recorded review")
        blob = _owned_file(folder, name, 32 * 1024 * 1024)
        if hashlib.sha256(blob).hexdigest() != digest:
            raise ValueError("A working drawing file changed after review")
        available.add((view_id, match[1]))
    expected = {(view_id, suffix) for view_id in drawn for suffix in ("pdf", "png")}
    if manifest.get("cycle") != cycle_number or available != expected or len(artifacts) != len(expected):
        raise ValueError("The selected group has an incomplete working drawing set")

    correspondence = [view.model_dump() for view in group.source_views]
    if {view["view_id"] for view in correspondence} != set(drawn):
        raise ValueError("The original correspondence map does not cover the group drawings")
    # The original correspondence data is separately pinned by the grouped job.
    source_folder = _owned_run(repository, project_id, original_job_id.split(".", 1)[1], "groups", group_id)
    if (source_folder / "initial-source-evidence.json").is_file():
        evidence_blob = _owned_file(source_folder, "initial-source-evidence.json", 2 * 1024 * 1024)
        if hashlib.sha256(evidence_blob).hexdigest() != row.get("source_evidence_sha256"):
            raise ValueError("The original group source correspondence has changed")
    else:
        evidence_blob, _ = read_working_artifact(repository, source_job, group_id + "--source-evidence.json")
    evidence = json.loads(evidence_blob)
    if (evidence.get("project_id") != project_id or evidence.get("job_id") != original_job_id
            or evidence.get("group_id") != group_id or evidence.get("source_set_sha256") != source_hash
            or evidence.get("views") != correspondence):
        raise ValueError("The original group source correspondence has changed")
    pin = content_hash({"model": hashlib.sha256(model_blob).hexdigest(), "candidate": candidate,
                        "review": cycle["review"], "evidence": hashlib.sha256(evidence_blob).hexdigest(),
                        "working_artifacts": artifacts})
    return GroupDraftSource(model, group.label, checked, correspondence, pin)


def draft_receipt(repository, job):
    if not job.get("draft_3d_group_id"):
        return None
    try:
        project_id, token = job["id"].split(".", 1)
        if project_id != job["project_id"]:
            return None
        folder = _owned_run(repository, project_id, token, "3d")
        value = json.loads(_owned_file(folder, "workflow-3d.json", 8 * 1024 * 1024))
        if (value.get("schema") == "formtopart-generate-3d/1" and value.get("project_id") == project_id
                and value.get("run_id") == job["id"] and value.get("preview_only") is True
                and value.get("accepted") is False and value.get("can_apply") is False):
            return value
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return None


def draft_model(repository, job, receipt):
    pin = receipt.get("preview_model") if receipt else None
    if not pin or not re.fullmatch(r"draft-model-[12]\.json", pin.get("file", "")):
        raise ValueError("This 3D review draft has no saved model yet")
    project_id, token = job["id"].split(".", 1)
    folder = _owned_run(repository, project_id, token, "3d")
    blob = _owned_file(folder, pin["file"], 32 * 1024 * 1024)
    if hashlib.sha256(blob).hexdigest() != pin.get("sha256"):
        raise ValueError("The saved 3D review draft changed after rendering")
    return validate_model(json.loads(blob))


def editable_draft_model(repository, project, job, source, documents):
    """Use a saved physical model while preserving its review as advisory evidence."""
    receipt = draft_receipt(repository, job)
    if (job.get("project_id") != project["id"] or job.get("base_revision") != project["revision"]
            or not receipt or receipt != job.get("workflow_3d") or receipt.get("preview_ready") is not True
            or receipt.get("status") not in ("draft_ready", "draft_needs_review")
            or receipt.get("fabrication_approval") is not False):
        raise ValueError("The saved 3D geometry is missing or does not match the project run.")
    source_model = _checked_source(source.model, documents, preview_only=True, verify_files=False)
    if receipt.get("source_2d_sha256") != content_hash(source_model.model_dump()):
        raise ValueError("The saved 3D geometry no longer matches its source drawings.")
    model = draft_model(repository, job, receipt)
    source_owners = _owner_identity(source_model.root)
    draft_owners = _owner_identity(model.root)
    parameters = {parameter.id: parameter for parameter in model.parameters}
    views = {view.id: view for view in model.views}
    if (model.drawings or model.source_2d_binding or model.requires_source_drawings
            or any(part.board_spec for part in _parts(model.root))
            or any(draft_owners.get(ident) != owner for ident, owner in source_owners.items())
            or any(parameters.get(parameter.id) != parameter for parameter in source_model.parameters)
            or set(views) != {view.id for view in source_model.views}
            or any(any(getattr(views[view.id], key) != getattr(view, key)
                       for key in ("document_id", "page", "region", "kind", "label")) for view in source_model.views)):
        raise ValueError("The 3D model changed source identities or contains unverified cutting details.")
    notices = list(receipt.get("draft_assumptions", []))
    if not source.checked:
        notices.insert(0, "The source drawings need review. Confirm provisional dimensions against the original PDF.")
    if receipt["status"] == "draft_needs_review":
        notices.insert(0, "The 3D check requested review. Verify the room geometry before relying on it.")
    return model.model_copy(update={"warnings": list(dict.fromkeys([*model.warnings, *notices]))})


def checked_draft_model(repository, project, job, source):
    """Reopen the exact geometry that passed the independent draft check."""
    receipt = draft_receipt(repository, job)
    if (not source.checked or job.get("draft_3d_source_checked") is not True
            or job.get("draft_3d_donor_job_id") or job.get("draft_3d_source_pin") != source.sha256
            or job.get("project_id") != project["id"] or job.get("base_revision") != project["revision"]
            or not receipt or receipt != job.get("workflow_3d") or receipt.get("status") != "draft_ready"
            or receipt.get("fabrication_approval") is not False):
        raise ValueError("This group needs a passed 3D check based on its own current checked 2D drawings.")
    documents = project["documents"]
    source_model = _checked_source(source.model, documents, verify_files=False)
    model = draft_model(repository, job, receipt)
    attempts, reports = receipt.get("attempts", []), receipt.get("reports", [])
    if not attempts or not reports:
        raise ValueError("The independent 3D review is missing.")
    attempt, report = attempts[-1], reports[-1]
    candidate_hash = content_hash(model.model_dump())
    bindings = report.get("bindings", {})
    if (receipt.get("source_2d_sha256") != content_hash(source_model.model_dump())
            or attempt.get("accepted") is not True or attempt.get("candidate_sha256") != candidate_hash
            or report.get("verdict") not in ("PASS", "PASS_WITH_LIMITS") or report.get("target") != "3d"
            or bindings.get("candidate_sha256") != candidate_hash or bindings.get("run_id") != job["id"]
            or bindings.get("project_id") != project["id"]
            or bindings.get("source_set_sha256") != content_hash({doc["id"]: doc["sha256"] for doc in documents})):
        raise ValueError("The saved 3D model no longer matches its independent review.")
    rendered = set(attempt.get("actual_render_ids", []))
    artifacts = [item for item in receipt.get("artifacts", [])
                 if item.get("artifact_id") in rendered or item.get("kind") in (
                     "source_2d_pdf", "source_2d_png", "original_source_crop")]
    manifest = [{key: value for key, value in item.items() if key != "path"} for item in artifacts]
    if not rendered or bindings.get("artifacts_sha256") != content_hash(manifest):
        raise ValueError("The rendered views no longer match their 3D check.")
    folder = _owned_run(repository, project["id"], job["id"].split(".", 1)[1], "3d")
    for item in artifacts:
        blob = _owned_file(folder, item["artifact_id"], 32 * 1024 * 1024)
        if hashlib.sha256(blob).hexdigest() != item["sha256"]:
            raise ValueError("A reviewed 3D evidence file changed after checking.")
    if (model.drawings or model.source_2d_binding or model.requires_source_drawings
            or any(part.board_spec for part in _parts(model.root))):
        raise ValueError("A review draft cannot carry source-drawing approval or cutting specifications.")
    return model


def rebind_draft_documents(model, original_documents, project_documents):
    """Keep evidence on the current project's byte-identical originals."""
    target_ids = {doc["sha256"]: doc["id"] for doc in project_documents}
    if len(target_ids) != len(project_documents):
        raise ValueError("The matching original PDFs have ambiguous duplicate identities.")
    ids = {doc["id"]: target_ids[doc["sha256"]] for doc in original_documents}
    record = model.model_dump()
    def replace(value):
        if isinstance(value, dict):
            if "document_id" in value:
                value["document_id"] = ids[value["document_id"]]
            for item in value.values():
                replace(item)
        elif isinstance(value, list):
            for item in value:
                replace(item)
    replace(record)
    return validate_model(record)


def combine_group_drafts(project, groups):
    """Compose separate room models without changing their local geometry or source values."""
    model = validate_model(project["model"]).model_dump()
    root = model["root"]
    cursor = 0
    for index, (label, draft) in enumerate(groups, 1):
        scene = build_scene(draft, project["id"], project["revision"])
        if not any(mesh.get("physical") for mesh in scene["meshes"]):
            raise ValueError("A checked draft has no physical geometry to save.")
        prefix = f"R{index}_"
        room_id = prefix + "ROOM"
        part_ids = {part.id: f"{prefix}P{i}" for i, part in enumerate(_parts(draft.root))}
        param_ids = {param.id: f"{prefix}D{i}" for i, param in enumerate(draft.parameters)}
        view_ids = {view.id: f"{prefix}V{i}" for i, view in enumerate(draft.views)}

        def expression(value):
            if isinstance(value, str):
                return re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", lambda m: param_ids.get(m[0], m[0]), value)
            return value

        def part_record(part):
            record = part.model_dump(exclude={"children"})
            record.update(id=part_ids[part.id], position=[expression(value) for value in part.position],
                          rotation=expression(part.rotation),
                          size=[expression(value) for value in part.size] if part.size else None,
                          material_assignment=None, interior=None,
                          children=[part_record(child) for child in part.children])
            if part.surface:
                record["surface"].update(width=expression(part.surface.width), span=expression(part.surface.span))
            for ordinal, symbol in enumerate(record["symbols"]):
                symbol.update(id=f'{record["id"]}_S{ordinal}',
                              views=[view_ids.get(view, view) for view in symbol["views"]])
            return record

        bounds = scene["bounds"]
        offset = cursor - bounds["min"][0] if len(groups) > 1 else 0
        cursor += bounds["max"][0] - bounds["min"][0] + 500
        root["children"].append({"id": room_id, "name": label, "kind": "assembly", "authority": "designed",
                                 "position": [offset, 0, 0], "children": [part_record(draft.root)]})
        model["parameters"].extend(param.model_dump() | {"id": param_ids[param.id], "expression": expression(param.expression)}
                                   for param in draft.parameters)
        model["views"].extend(view.model_dump() | {"id": view_ids[view.id],
            "include": [part_ids[owner] for owner in view.include] or [room_id]} for view in draft.views)
        model["relationships"].extend(record.model_dump() | {
            "id": f"{prefix}L{i}", "owner_a": part_ids[record.owner_a], "owner_b": part_ids[record.owner_b],
            "subjects": [part_ids[owner] for owner in record.subjects],
            "views": [view_ids.get(view, view) for view in record.views],
            "parameter_id": param_ids.get(record.parameter_id),
            "point_a": [expression(value) for value in record.point_a],
            "point_b": [expression(value) for value in record.point_b],
        } for i, record in enumerate(draft.relationships))
        model["warnings"].extend(draft.warnings)
    model["warnings"] = list(dict.fromkeys(model["warnings"]))
    return validate_model(model)


def draft_scene(repository, job):
    project_id = job["project_id"]
    model = draft_model(repository, job, draft_receipt(repository, job))
    scene = build_review_draft_scene(model, project_id, job["base_revision"])
    if not any(mesh.get("physical") for mesh in scene["meshes"]):
        raise ValueError("The saved 3D review draft has no physical geometry")
    scene["draft_3d"] = {"group_id": job["draft_3d_group_id"], "label": job["draft_3d_group_label"],
                         "source_2d_checked": job["draft_3d_source_checked"], "fabrication_approval": False}
    if job.get("draft_3d_donor_job_id"):
        scene["draft_3d"].update(source_2d_project_id=job["draft_3d_donor_project_id"],
                                 source_2d_project_name=job["draft_3d_donor_project_name"],
                                 source_2d_job_id=job["draft_3d_donor_job_id"],
                                 source_2d_group_id=job["draft_3d_donor_group_id"],
                                 source_2d_evidence_url=job["draft_3d_donor_source_evidence_url"])
    try:
        source_job = repository.get_job(job.get("draft_3d_donor_job_id") or job["draft_3d_source_job_id"])
        group = job.get("draft_3d_donor_group_id") or job["draft_3d_group_id"]
        evidence, _ = read_working_artifact(repository, source_job, group + "--source-evidence.json")
        source = json.loads(evidence)
        source_project = job.get("draft_3d_donor_project_id") or project_id
        if source["project_id"] == source_project and source["group_id"] == group:
            scene["draft_3d"]["source_views"] = [view for view in source["views"] if view["view_id"] in scene["views"]]
    except (NotFound, OSError, KeyError, TypeError, ValueError):
        # Retained draft geometry and generic cameras remain available even if
        # the original source correspondence cannot be opened.
        pass
    return scene
