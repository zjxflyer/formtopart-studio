"""Run independent, app-discovered drawing groups serially within one project task."""
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import uuid4

from .api_drawing_workflow import _source_identity
from .repository import encode


def _write_record(path, record):
    payload = (encode(record) + "\n").encode("utf-8")
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return sha256(payload).hexdigest()


def source_evidence_record(*, project_id, job_id, group_id, label, source_set_sha256, source_views, source_map_sha256):
    return {
        "schema": "formtopart-source-group-evidence/1", "project_id": project_id, "job_id": job_id,
        "group_id": group_id, "label": label, "source_set_sha256": source_set_sha256,
        "coordinate_convention": "Normalized displayed PDF page; origin top left, x right, y down. "
                                 "Crop boxes use left, top, right, bottom. Callout points use x, y.",
        "views": source_views,
        "source_map": {"file": "source-map.png", "sha256": source_map_sha256},
    }


def _read_plan(plan_path, project_id, documents):
    from .ai import AIError
    from .drawing_group_discovery import DrawingGroup

    try:
        if plan_path.stat().st_size > 2 * 1024 * 1024:
            return None, {}
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if (plan["schema"] != "formtopart-grouped-2d-plan/1" or plan["project_id"] != project_id
                or plan["source_set_sha256"] != _source_identity(documents)):
            return None, {}
        original_job_id = plan["job_id"]
        if not re.fullmatch(re.escape(project_id) + r"\.[a-f0-9]{32}", original_job_id):
            return None, {}
        parsed = [DrawingGroup.model_validate(value) for value in plan["groups"]]
        groups = {group.id: group for group in parsed}
        if len(groups) != len(parsed) or not 1 <= len(groups) <= 4:
            return None, {}
    except (AIError, OSError, KeyError, TypeError, ValueError):
        return None, {}
    return original_job_id, groups


def _plan_matches_row(group, row, original_job_id, job):
    source_run = row.get("source_run_id") or job["id"].split(".", 1)[1]
    return (original_job_id == f'{job["project_id"]}.{source_run}' and row.get("label") == group.label
            and row.get("source_views") == [view.model_dump() for view in group.source_views])


def _group_cycle_path(plan_path, group, row):
    attempt = row.get("attempt_run_id")
    if attempt is None:
        return plan_path.parent / "group-cycles" / f"{group.id}.json"
    if not re.fullmatch(r"[a-f0-9]{32}", attempt) or attempt not in row.get("artifact_run_ids", []):
        raise ValueError("Invalid drawing group attempt.")
    return plan_path.parent / "group-rebuild-cycles" / attempt / f"{group.id}.json"


def _pinned_group_ledger(plan_path, project_id, documents, group, row):
    from .autonomous_2d import _existing_scope

    path = _group_cycle_path(plan_path, group, row)
    frames, ledger = _existing_scope(path, project_id, documents)
    if ledger:
        planned = {(view.id, view.document_id, view.page, view.kind) for view in group.index.views}
        pinned = {(view.id, view.document_id, view.page, view.kind) for view in frames}
        if planned != pinned:
            raise ValueError("Saved drawing-cycle scope differs from the original group")
    return ledger


def group_retry_options(plan_path, project_id, documents, job):
    """Return held groups whose original plan and unfinished cycle allowance still match."""
    if not job or job.get("status") not in ("needs_review", "failed", "cancelled"):
        return {}
    held = [row for row in job.get("groups_2d", []) if row.get("status") in ("needs_review", "failed", "cancelled")
            and not row.get("accepted")]
    if not held:
        return {}
    original_job_id, groups = _read_plan(plan_path, project_id, documents)

    options = {}
    for row in held:
        group = groups.get(row.get("id"))
        if not group or not _plan_matches_row(group, row, original_job_id, job):
            continue
        try:
            ledger = _pinned_group_ledger(plan_path, project_id, documents, group, row)
            if not ledger:
                continue
            snapshot = ledger.snapshot()
            if snapshot["can_start_drawing"] and not snapshot["can_start_3d"]:
                options[group.id] = (group, snapshot["cycles_remaining"])
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return options


def _recovery_group(plan_path, project_id, documents, group, row, previous):
    ledger = _pinned_group_ledger(plan_path, project_id, documents, group, row)
    if not ledger:
        return True, None, None
    snapshot = ledger.snapshot()
    latest = snapshot["latest_cycle"]
    if snapshot["can_start_3d"] or not snapshot["cycles_remaining"]:
        return False, None, None
    if snapshot["can_start_drawing"]:
        return True, None, None
    # The provider may have received the request before the process was lost.
    # Keep that cycle charged and only continue if its lease belongs to this task.
    lease_run = latest["metadata"].get("run_id") if latest else None
    history = row.get("artifact_run_ids") or [previous["id"].split(".", 1)[1]]
    if lease_run in {f"{project_id}.{token}.{group.id}" for token in history}:
        return True, ledger, latest["lease_id"]
    return False, None, None


def is_group_interruption(job):
    return (job.get("status"), job.get("error_category")) in {
        ("failed", "interrupted"), ("cancelled", "project_paused"),
    }


def group_rebuild_options(plan_path, project_id, documents, job):
    """Return the stable, source-ordered scopes available for an explicit new attempt."""
    if not job or job.get("status") not in ("ready", "needs_review", "failed", "cancelled"):
        return {}
    original_job_id, groups = _read_plan(plan_path, project_id, documents)
    recorded = job.get("groups_2d", [])
    rows = {row["id"]: row for row in recorded}
    if len(rows) != len(recorded) or groups.keys() != rows.keys():
        return {}
    if any(not _plan_matches_row(group, rows[key], original_job_id, job) for key, group in groups.items()):
        return {}
    return groups


def group_recovery_options(plan_path, project_id, documents, job):
    """Find interrupted groups that can continue within their original allowance."""
    if not job or not is_group_interruption(job):
        return []
    original_job_id, groups = _read_plan(plan_path, project_id, documents)
    recorded_rows = job.get("groups_2d", [])
    rows = {row["id"]: row for row in recorded_rows}
    if not groups or len(rows) != len(recorded_rows) or groups.keys() != rows.keys():
        return []
    if any(not _plan_matches_row(group, rows[key], original_job_id, job) for key, group in groups.items()):
        return []
    retry_group = job.get("retry_group_id")
    scope = {retry_group} if retry_group else set(job.get("recover_group_ids") or job.get("rebuild_group_ids") or groups)
    allowed = []
    for key, group in groups.items():
        row = rows[key]
        unfinished = row["status"] in ("queued", "running", "paused", "pausing", "cancelled")
        # Older builds marked these unfinished rows failed without a group
        # error. A real drawing failure carried its own error category.
        legacy_interrupted = (job.get("interrupted_phase") is None and row["status"] == "failed"
                              and not row.get("error_category"))
        if key not in scope or row.get("accepted") or not (unfinished or legacy_interrupted or row.get("error_category") == "interrupted"):
            continue
        try:
            can_resume, _, _ = _recovery_group(plan_path, project_id, documents, group, row, job)
        except (OSError, KeyError, TypeError, ValueError):
            continue
        if can_resume:
            allowed.append(key)
    return allowed


def continued_group_states(previous, job_id, group_ids):
    old_run = previous["id"].split(".", 1)[1]
    new_run = job_id.split(".", 1)[1]
    states = []
    for row in previous["groups_2d"]:
        history = list(row.get("artifact_run_ids") or [old_run])
        state = row | {"source_run_id": row.get("source_run_id") or old_run, "artifact_run_ids": history}
        if row["id"] in group_ids:
            state["status"] = "queued"
            state.pop("error_category", None)
            history.append(new_run)
        states.append(state)
    return states


def retry_group_states(previous, job_id, group_id):
    return continued_group_states(previous, job_id, [group_id])


def rebuild_group_states(previous, job_id, group_ids):
    states = continued_group_states(previous, job_id, group_ids)
    attempt = job_id.split(".", 1)[1]
    for row in states:
        if row["id"] in group_ids:
            row.update(attempt_run_id=attempt, accepted=False, cycle_count=0, view_ids=[], failed_stage=None, issues=[])
    return states


def _save_states(output, project_id, job_id, states, publish):
    # The project database drives recovery. Commit the milestone there once
    # the group's source and drawing files have finished writing.
    publish(states)
    _write_record(output / "grouped-2d-result.json", {"project_id": project_id, "job_id": job_id, "groups": states})


def _draw_group(gateway, documents, folder, *, group, state, project_id, job_id, plan_path,
                check_control, progress):
    from .autonomous_2d import run_autonomous_2d

    ledger = _group_cycle_path(plan_path, group, state)
    try:
        result = run_autonomous_2d(gateway, documents, folder, project_id=project_id,
                                   run_id=f"{job_id}.{group.id}", instruction=group.instruction,
                                   initial_index=group.index, cycle_ledger_path=ledger,
                                   progress=progress, check_control=check_control)
    except Exception as error:
        # If a stop or restart invalidated the parent, this re-raises before
        # marking a group failed or starting the next group.
        check_control()
        state.update(status="failed", accepted=False, error_category=getattr(error, "category", "validation"))
    else:
        receipt = result["workflow_receipt"]
        accepted = receipt.get("accepted") is True
        view_ids = [view.id for view in result["model"].drawings]
        state.pop("error_category", None)
        state.update(status="ready" if accepted else "needs_review", accepted=accepted,
                     view_ids=view_ids or state["view_ids"], cycle_count=receipt["cycle_count"],
                     failed_stage=receipt.get("failed_stage"), issues=receipt.get("issues", [])[:12])


def run_group_retry(gateway, documents, output, *, job, previous, plan_path, check_control, progress, publish):
    from .repository import Conflict

    group_id = job["retry_group_id"]
    retry = group_retry_options(plan_path, job["project_id"], documents, previous).get(group_id)
    if not retry:
        raise Conflict("This drawing group can no longer be retried. / 此图纸组已无法重试。")
    group, _ = retry
    states = job["groups_2d"]
    state = next(row for row in states if row["id"] == group_id)
    check_control()
    state["status"] = "running"
    _save_states(output, job["project_id"], job["id"], states, publish)
    _draw_group(gateway, documents, output / "groups" / group_id, group=group, state=state,
                project_id=job["project_id"], job_id=job["id"], plan_path=plan_path,
                check_control=check_control, progress=progress)
    _save_states(output, job["project_id"], job["id"], states, publish)
    check_control()
    return states


def run_group_recovery(gateway, documents, output, *, job, previous, plan_path, check_control, progress, publish):
    from .repository import Conflict

    project_id, job_id = job["project_id"], job["id"]
    group_ids = job["recover_group_ids"]
    if group_ids != group_recovery_options(plan_path, project_id, documents, previous):
        raise Conflict("The saved drawing checkpoint changed. Reopen the project before resuming.")
    _, groups = _read_plan(plan_path, project_id, documents)
    previous_rows = {row["id"]: row for row in previous["groups_2d"]}
    states = job["groups_2d"]
    for position, group_id in enumerate(group_ids):
        check_control()
        group = groups[group_id]
        can_resume, ledger, lease_id = _recovery_group(plan_path, project_id, documents, group, previous_rows[group_id], previous)
        if not can_resume:
            raise Conflict("The saved drawing group is no longer eligible to resume.")
        if lease_id:
            ledger.note_failure(lease_id, phase="interrupted", category="interrupted")
        state = next(row for row in states if row["id"] == group_id)
        state["status"] = "running"
        _save_states(output, project_id, job_id, states, publish)

        def group_progress(phase, percent):
            progress(phase, 10 + int(89 * (position + max(0, min(100, percent)) / 100) / len(group_ids)))

        _draw_group(gateway, documents, output / "groups" / group_id, group=group, state=state,
                    project_id=project_id, job_id=job_id, plan_path=plan_path, check_control=check_control,
                    progress=group_progress)
        _save_states(output, project_id, job_id, states, publish)
        check_control()
    return states


def run_group_rebuild(gateway, documents, output, *, job, previous, plan_path, check_control, progress, publish):
    from .repository import Conflict

    project_id, job_id = job["project_id"], job["id"]
    group_ids = job["rebuild_group_ids"]
    groups = group_rebuild_options(plan_path, project_id, documents, previous)
    if not group_ids or group_ids != [key for key in groups if key in group_ids]:
        raise Conflict("The mapped drawing groups have changed. Reopen the project before rebuilding.")
    states = job["groups_2d"]
    for position, group_id in enumerate(group_ids):
        check_control()
        state = next(row for row in states if row["id"] == group_id)
        state["status"] = "running"
        _save_states(output, project_id, job_id, states, publish)

        def group_progress(phase, percent):
            progress(phase, 10 + int(89 * (position + max(0, min(100, percent)) / 100) / len(group_ids)))

        _draw_group(gateway, documents, output / "groups" / group_id, group=groups[group_id], state=state,
                    project_id=project_id, job_id=job_id, plan_path=plan_path,
                    check_control=check_control, progress=group_progress)
        _save_states(output, project_id, job_id, states, publish)
        check_control()
    return states


def run_grouped_2d(gateway, documents, output, *, project_id, job_id, plan_path,
                   instruction, check_control, progress, publish):
    from .drawing_group_discovery import discover_drawing_groups
    from .source_group_atlas import render_source_group_map

    output = Path(output)
    progress("mapping_drawing_groups", 5)
    groups = discover_drawing_groups(gateway, documents, output / "discovery",
                                     instruction=instruction, check_control=check_control)
    source_set_sha256 = _source_identity(documents)
    source_run_id = job_id.split(".", 1)[1]
    states = []
    for group in groups:
        check_control()
        folder = output / "groups" / group.id
        folder.mkdir(parents=True, exist_ok=False)
        source_views = [view.model_dump() for view in group.source_views]
        source_map_sha256 = render_source_group_map(documents, group.index, source_views,
                                                     folder / "source-map.png", group.label)
        crop_regions = {view.id: view.region for view in group.index.views}
        source_evidence_sha256 = _write_record(folder / "initial-source-evidence.json", source_evidence_record(
            project_id=project_id, job_id=job_id, group_id=group.id, label=group.label,
            source_set_sha256=source_set_sha256, source_views=[row | {"region": crop_regions[row["view_id"]]} for row in source_views],
            source_map_sha256=source_map_sha256,
        ))
        states.append({"id": group.id, "label": group.label, "run_id": uuid4().hex, "status": "queued",
                       "view_ids": [], "source_views": source_views, "source_map_sha256": source_map_sha256,
                       "source_evidence_sha256": source_evidence_sha256, "source_run_id": source_run_id,
                       "artifact_run_ids": [source_run_id]})

    def save_progress():
        _save_states(output, project_id, job_id, states, publish)

    check_control()
    save_progress()
    # One plan binds the group slots to this exact source set. A second Start
    # cannot discover new IDs to obtain additional cycles for the same source.
    _write_record(plan_path, {"schema": "formtopart-grouped-2d-plan/1", "project_id": project_id,
                              "job_id": job_id, "source_set_sha256": source_set_sha256,
                              "groups": [group.model_dump() for group in groups]})

    for position, (group, state) in enumerate(zip(groups, states), 1):
        check_control()
        state["status"] = "running"
        save_progress()
        folder = output / "groups" / group.id

        def group_progress(phase, percent):
            progress(phase, 10 + int(89 * (position - 1 + max(0, min(100, percent)) / 100) / len(groups)))

        _draw_group(gateway, documents, folder, group=group, state=state, project_id=project_id,
                    job_id=job_id, plan_path=plan_path, check_control=check_control, progress=group_progress)
        save_progress()
        check_control()
    return states
