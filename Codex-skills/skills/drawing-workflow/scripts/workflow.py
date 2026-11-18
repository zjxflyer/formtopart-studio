"""Portable drawing workflow bookkeeping; Python standard library except PDF merge.

This is a deterministic record/gate helper, not an autonomous drawing engine.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone
from urllib.parse import quote

SCHEMA = 1
STAGES = ("PHASE1", "INITIAL", "DOCUMENT_ISSUES", "FULL_REVIEW")
VERDICTS = {"PASS", "PASS_WITH_NOTES", "PROVISIONAL", "REVISE", "HOLD"}
ACCEPTED = {"PASS", "PASS_WITH_NOTES"}
CORE = {"position", "shape", "dimension"}
TODO_STATUSES = {"PENDING", "IN_PROGRESS", "BLOCKED", "DONE", "DEFERRED", "CANCELLED", "SUPERSEDED"}
TODO_CLOSED = {"DONE", "CANCELLED", "SUPERSEDED"}
TODO_PRIORITIES = {"P0", "P1", "P2", "P3"}
WORK = ".drawing-workflow"


class WorkflowError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def natural(value):
    return [int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", value)]


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value):
        raise WorkflowError("ID must be a safe single path component")
    if value.endswith((".", " ")) or value.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]
    }:
        raise WorkflowError("Reserved path component")
    return value


def local(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise WorkflowError("Paths must be project-relative forward-slash paths")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise WorkflowError("Path escapes project")
    result = (Path(root).resolve() / path).resolve()
    if not result.is_relative_to(Path(root).resolve()):
        raise WorkflowError("Resolved path escapes project")
    return result


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".workflow-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def writer(root):
    folder = Path(root) / WORK
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "writer.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise WorkflowError("Writer lock exists; reconcile its owner before retrying") from exc
    try:
        os.write(fd, encoded({"pid": os.getpid(), "created_utc": now()}))
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def manifest_path(root):
    return Path(root) / WORK / "project.json"


def state_path(root):
    return Path(root) / WORK / "state.json"


def read(root):
    manifest = json.loads(manifest_path(root).read_text(encoding="utf-8"))
    state = json.loads(state_path(root).read_text(encoding="utf-8"))
    if state["manifest_sha256"] != digest(manifest_path(root)):
        raise WorkflowError("Manifest changed; migration requires an explicit reviewed operation")
    require_history_contract(state)
    return manifest, state


def pin(root, relative):
    path = local(root, relative)
    if not path.is_file():
        raise WorkflowError(f"Missing file: {relative}")
    return {"path": relative, "sha256": digest(path)}


def check_pin(root, item):
    if not isinstance(item, dict) or not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", "")):
        raise WorkflowError("Missing or invalid SHA-256")
    if pin(root, item["path"]) != item:
        raise WorkflowError(f"Stale or changed file: {item['path']}")


def init(root, config):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    config = copy.deepcopy(config)
    safe_id(config["project_id"])
    sheets = [safe_id(x) for x in config["sheets"]]
    if not sheets or len(set(x.casefold() for x in sheets)) != len(sheets):
        raise WorkflowError("Sheet IDs must be nonempty and case-insensitively unique")
    order = config.setdefault("order", "natural")
    if order not in {"natural", "manifest"}:
        raise WorkflowError("order must be natural or manifest")
    config["sheets"] = sorted(sheets, key=natural) if order == "natural" else sheets
    out = config.setdefault("output_dir", "results")
    local(root, out)
    if Path(out).parts[0] == WORK or out in {".", ""}:
        raise WorkflowError("Output must have its own project subdirectory")
    if not config.get("model", {}).get("name") or not config["model"].get("effort"):
        raise WorkflowError("Record the requested model name and effort")
    config.setdefault("workflow_version", "Effective Version 7")
    config["schema_version"] = SCHEMA
    policy = config.setdefault("policy", {})
    for key, default in {"phase1_rounds": 2, "initial_rounds": 2, "manual_issue_passes": 1,
                         "full_review_rounds": 2}.items():
        policy.setdefault(key, default)
        if type(policy[key]) is not int or policy[key] < 1:
            raise WorkflowError("Cycle budgets must be positive integers")
    if policy["manual_issue_passes"] != 1:
        raise WorkflowError("This contract records one manual pass with multiple issue IDs")
    sources = []
    for value in config["sources"]:
        item = pin(root, value["path"])
        if value.get("sha256") and value["sha256"] != item["sha256"]:
            raise WorkflowError("Provided source hash does not match")
        if local(root, item["path"]).is_relative_to(local(root, out)):
            raise WorkflowError("Sources must not be stored under the output directory")
        sources.append(item)
    if not sources:
        raise WorkflowError("At least one source is required")
    config["sources"] = sources
    with writer(root):
        if state_path(root).exists() or manifest_path(root).exists():
            raise WorkflowError("Already initialized; renaming output folders does not reset budgets")
        atomic(manifest_path(root), encoded(config))
        state = {"schema_version": SCHEMA, "project_id": config["project_id"],
                 "manifest_sha256": digest(manifest_path(root)), "sequence": 0,
                 "jobs": {}, "events": [], "releases": {}, "current_jobs": {},
                 "artifact_history_version": 1, "artifact_history": [], "todo": {}}
        atomic(state_path(root), encoded(state))
    return validate(root)


def job_key(event):
    sheet, stage = safe_id(event["sheet"]), event["stage"]
    if stage not in STAGES:
        raise WorkflowError("Unknown stage")
    issue = safe_id(event["issue"]) if stage == "DOCUMENT_ISSUES" else None
    return "|".join([sheet, stage] + ([issue] if issue else []))


def new_job():
    return {"major_round": 0, "repair_revision": 0, "check_events": 0,
            "status": "NOT_STARTED", "summary_due": False, "awaiting_check": False,
            "creator": None, "artifacts": None, "exception": None,
            "create_events": 0, "checks": []}


def require_summary(job):
    if job["summary_due"]:
        raise WorkflowError("Summarize or SKIP is required after the last completed check")


def artifacts(root, manifest, sheet, stage, values):
    if stage == "PHASE1":
        if set(values) != {"mapping"}:
            raise WorkflowError("PHASE1 requires a mapping artifact")
        result = {"mapping": pin(root, values["mapping"])}
    else:
        if set(values) != {"plan", "elevations"} or not values["elevations"]:
            raise WorkflowError("Each sheet requires its own Plan and elevation list")
        result = {"plan": pin(root, values["plan"]),
                  "elevations": [pin(root, x) for x in values["elevations"]]}
    for item in flatten(result):
        if not local(root, item["path"]).is_relative_to(local(root, manifest["output_dir"] + "/" + sheet)):
            raise WorkflowError("Artifacts must belong to this sheet's own output directory")
    paths = [x["path"] for x in flatten(result)]
    if len(set(paths)) != len(paths):
        raise WorkflowError("Plan and elevations must reference separate files")
    return result


def flatten(values):
    for value in values.values():
        yield from value if isinstance(value, list) else [value]


def require_history_contract(state):
    if state.get("artifact_history_version") != 1 or not isinstance(state.get("artifact_history"), list):
        raise WorkflowError("Unsupported state: immutable artifact history is required; explicit reviewed migration only")


def validate_pins(root, manifest, state):
    """Validate current and historical submitted artifacts, including exact check bindings."""
    require_history_contract(state)
    validate_todos(manifest, state)
    for source in manifest["sources"]:
        check_pin(root, source)
    submissions = {event["sequence"]: event for event in state["events"]
                   if event["action"] in {"create", "review"}}
    historical = {}
    bindings = set()
    for submission in state["artifact_history"]:
        sequence, key = submission["sequence"], submission["job"]
        if sequence in historical or sequence not in submissions or job_key(submissions[sequence]) != key:
            raise WorkflowError("Artifact history submission identity does not match event history")
        expected = hashlib.sha256(encoded(submission["artifacts"])).hexdigest()
        if submission["artifact_sha256"] != expected or submission["manifest_sha256"] != state["manifest_sha256"]:
            raise WorkflowError("Artifact history lost its exact artifact/source binding")
        for item in flatten(submission["artifacts"]):
            check_pin(root, item)
        historical[sequence] = submission
        bindings.add((key, expected))
    if set(historical) != set(submissions):
        raise WorkflowError("Missing immutable artifact submission history")
    for event in state["events"]:
        if event["action"] == "check" and not any(
            entry["sequence"] < event["sequence"] and entry["job"] == job_key(event)
            and entry["artifact_sha256"] == event["artifact_sha256"]
            for entry in historical.values()
        ):
            raise WorkflowError("Historical check is not bound to an earlier exact submitted revision")
    for key, job in state["jobs"].items():
        if job["artifacts"]:
            expected = hashlib.sha256(encoded(job["artifacts"])).hexdigest()
            if (key, expected) not in bindings:
                raise WorkflowError("Current job artifacts have no immutable submission record")
            for item in flatten(job["artifacts"]):
                check_pin(root, item)
        if any((key, check["artifact_sha256"]) not in bindings for check in job["checks"]):
            raise WorkflowError("Historical job check lost its artifact binding")
    for release in state["releases"].values():
        expected = hashlib.sha256(encoded(release["artifacts"])).hexdigest()
        if (release["job"], expected) not in bindings:
            raise WorkflowError("Release has no immutable artifact submission")
        for item in flatten(release["artifacts"]):
            check_pin(root, item)


def validate(root):
    manifest, state = read(root)
    validate_pins(root, manifest, state)
    return {"project_id": manifest["project_id"], "state_sha256": digest(state_path(root)),
            "sequence": state["sequence"], "sheets": manifest["sheets"],
            "published_sheets": list(state["releases"]), "status": "VALID_RECORDS"}


def guard_pinned_outputs(root, state, *paths):
    pinned = {local(root, item["path"]) for submission in state["artifact_history"]
              for item in flatten(submission["artifacts"])}
    if any(Path(path).resolve() in pinned for path in paths):
        raise WorkflowError("Output must not overwrite a pinned historical artifact")


def todo_dedupe(task):
    value = {"original_request": " ".join(task["original_request"].split()).casefold(),
             "source_ref": task.get("source_ref", ""), "stage": task["stage"],
             "sheet_ids": sorted(task["sheet_ids"], key=natural)}
    return hashlib.sha256(encoded(value)).hexdigest()


def validate_todos(manifest, state):
    tasks = state.get("todo", {})
    if not isinstance(tasks, dict):
        raise WorkflowError("TODO register must be keyed by stable task ID")
    dedupes = set()
    for task_id, task in tasks.items():
        safe_id(task_id)
        if task.get("id") != task_id or not isinstance(task.get("title"), str) or not task["title"].strip() or not task.get("original_request"):
            raise WorkflowError("TODO requires stable ID, title and original request")
        if not isinstance(task.get("owner"), str) or not task["owner"].strip() or not isinstance(task.get("source_ref"), str):
            raise WorkflowError("TODO requires an owner and a string source reference")
        if any(not isinstance(task.get(field), list) for field in ("notes", "evidence", "completion_evidence", "history")):
            raise WorkflowError("TODO notes, evidence and history must be lists")
        for field in ("evidence", "completion_evidence"):
            if any(not ((isinstance(entry, str) and entry.strip()) or (
                isinstance(entry, dict) and any(isinstance(entry.get(key), str) and entry[key].strip()
                                              for key in ("ref", "path", "url")))) for entry in task[field]):
                raise WorkflowError("TODO evidence entries must contain a nonempty verification reference")
        if not isinstance(task.get("context_reviews", []), list):
            raise WorkflowError("TODO context review history must be a list")
        if task.get("priority") not in TODO_PRIORITIES or task.get("status") not in TODO_STATUSES:
            raise WorkflowError("Unsupported TODO priority or status")
        if task.get("stage") not in {*STAGES, "PROJECT", "DELIVERY"}:
            raise WorkflowError("Unsupported TODO stage")
        sheets = task.get("sheet_ids", [])
        if not isinstance(sheets, list) or len(set(sheets)) != len(sheets) or any(x not in manifest["sheets"] for x in sheets):
            raise WorkflowError("TODO sheet IDs must be unique known sheets; empty means all/project-wide")
        dependencies = task.get("depends_on", [])
        if not isinstance(dependencies, list) or len(set(dependencies)) != len(dependencies):
            raise WorkflowError("TODO dependencies must be a unique list")
        if task_id in dependencies or any(x not in tasks for x in dependencies):
            raise WorkflowError("TODO has a self-dependency or unknown dependency")
        if task["status"] == "DONE" and (not task.get("completion_evidence") or any(
            tasks[x]["status"] != "DONE" for x in dependencies
        )):
            raise WorkflowError("DONE requires completion evidence and every explicit dependency DONE")
        if task["status"] == "IN_PROGRESS" and any(tasks[x]["status"] != "DONE" for x in dependencies):
            raise WorkflowError("IN_PROGRESS requires every explicit dependency DONE")
        if task["status"] == "BLOCKED" and not task.get("blocker_reason"):
            raise WorkflowError("BLOCKED requires a concrete blocker reason")
        if task["status"] in {"DEFERRED", "CANCELLED", "SUPERSEDED"} and not task.get("status_reason"):
            raise WorkflowError("Deferral/cancellation/supersession needs an explicit reason")
        if task["status"] == "SUPERSEDED" and (task.get("superseded_by") not in tasks or task["superseded_by"] == task_id):
            raise WorkflowError("SUPERSEDED requires a different existing replacement task")
        key = todo_dedupe(task)
        if key in dedupes:
            raise WorkflowError("Equivalent request/scope is already registered; update its existing stable ID")
        dedupes.add(key)
    visited, visiting = set(), set()

    def visit(task_id):
        if task_id in visiting:
            raise WorkflowError("TODO dependency cycle")
        if task_id not in visited:
            visiting.add(task_id)
            for other in tasks[task_id]["depends_on"]:
                visit(other)
            visiting.remove(task_id)
            visited.add(task_id)
    for task_id in tasks:
        visit(task_id)


def todo_result(root, state):
    return {"state_sha256": digest(state_path(root)), "sequence": state["sequence"],
            "todo_count": len(state.get("todo", {})), "status": "TODO_RECORDED_NOT_A_DRAWING_VERDICT"}


def todo_add(root, task, expected_hash):
    with writer(root):
        manifest, state = read(root)
        if digest(state_path(root)) != expected_hash:
            raise WorkflowError("Stale state hash; refresh before updating TODO register")
        tasks = state.setdefault("todo", {})
        task = copy.deepcopy(task)
        task_id = safe_id(task["id"])
        if task_id in tasks:
            raise WorkflowError("Duplicate TODO ID; update existing task without replacing its original request")
        if task.get("status", "PENDING") != "PENDING":
            raise WorkflowError("New TODO starts PENDING; completion needs a separate evidenced update")
        if not isinstance(task.get("original_request"), str) or not task["original_request"].strip():
            raise WorkflowError("Record the original user request without rewriting it")
        timestamp = now()
        item = {"id": task_id, "title": task["title"], "original_request": task["original_request"],
                "source_ref": task.get("source_ref", ""), "sheet_ids": task.get("sheet_ids", []),
                "stage": task.get("stage", "PROJECT"), "priority": task.get("priority", "P2"),
                "owner": task.get("owner", "Coordinate"), "depends_on": task.get("depends_on", []),
                "status": "PENDING", "evidence": task.get("evidence", []), "completion_evidence": [],
                "context_reviews": [],
                "notes": task.get("notes", []), "created_utc": timestamp, "updated_utc": timestamp,
                "history": [{"time_utc": timestamp, "action": "ADD", "status": "PENDING"}]}
        tasks[task_id] = item
        validate_todos(manifest, state)
        state["sequence"] += 1
        state["events"].append({"action": "todo-add", "task_id": task_id,
                                "sequence": state["sequence"], "time_utc": timestamp})
        atomic(state_path(root), encoded(state))
    return todo_result(root, state)


def todo_update(root, task_id, changes, expected_hash):
    with writer(root):
        manifest, state = read(root)
        if digest(state_path(root)) != expected_hash:
            raise WorkflowError("Stale state hash; refresh before updating TODO register")
        tasks = state.get("todo", {})
        if task_id not in tasks:
            raise WorkflowError("Unknown TODO ID")
        changes = copy.deepcopy(changes)
        requested_changes = copy.deepcopy(changes)
        allowed = {"title", "sheet_ids", "stage", "priority", "owner", "depends_on", "status",
                   "evidence", "notes", "reason", "blocker_reason", "superseded_by", "context_review"}
        if set(changes) - allowed:
            raise WorkflowError("Original request, source reference, ID and audit history are immutable")
        old = copy.deepcopy(tasks[task_id])
        item = tasks[task_id]
        target_status = changes.get("status")
        if target_status in {"DEFERRED", "CANCELLED", "SUPERSEDED"} and (
            not isinstance(changes.get("reason"), str) or not changes["reason"].strip()
        ):
            raise WorkflowError("Deferral/cancellation/supersession requires a fresh explicit reason in this update")
        if target_status == "BLOCKED" and (
            not isinstance(changes.get("blocker_reason"), str) or not changes["blocker_reason"].strip()
        ):
            raise WorkflowError("BLOCKED requires a fresh concrete blocker reason in this update")
        if target_status in {"CANCELLED", "SUPERSEDED"} and (
            not isinstance(changes.get("evidence"), list) or not changes["evidence"]
        ):
            raise WorkflowError("Cancellation/supersession requires fresh contextual evidence references")
        needs_review = changes.get("status") == "IN_PROGRESS" or (
            old["status"] == "IN_PROGRESS" and changes.get("owner", old["owner"]) != old["owner"])
        if needs_review and "context_review" not in changes:
            raise WorkflowError("Starting, resuming or reassigning IN_PROGRESS needs a fresh context_review")
        if "context_review" in changes:
            review = changes.pop("context_review")
            if not isinstance(review, dict) or set(review) != {"state_hash", "decision", "reason", "source_refs"}:
                raise WorkflowError("context_review requires state_hash, decision, reason and source_refs")
            if review["state_hash"] != expected_hash:
                raise WorkflowError("Stale context_review state hash; reassess against current context")
            if review["decision"] != "PROCEED" or not isinstance(review["reason"], str) or not review["reason"].strip():
                raise WorkflowError("context_review needs PROCEED and a nonempty current-context reason")
            if not isinstance(review["source_refs"], list) or not review["source_refs"] or any(
                not isinstance(ref, str) or not ref.strip() for ref in review["source_refs"]
            ):
                raise WorkflowError("context_review source_refs must be nonempty reference strings")
            item.setdefault("context_reviews", []).append({**review, "time_utc": now()})
        if changes.get("status") == "DONE":
            if not isinstance(changes.get("evidence"), list) or not changes["evidence"]:
                raise WorkflowError("DONE update requires explicit nonempty completion evidence")
            item["completion_evidence"] = copy.deepcopy(changes["evidence"])
        if old["status"] in TODO_CLOSED and changes.get("status", old["status"]) != old["status"] and not changes.get("reason"):
            raise WorkflowError("Reopening a closed TODO needs an explicit reason")
        for field in ("evidence", "notes"):
            if field in changes:
                if not isinstance(changes[field], list):
                    raise WorkflowError("TODO notes/evidence must be append-only lists")
                item[field].extend(changes.pop(field))
        if "reason" in changes:
            item["status_reason"] = changes.pop("reason")
        item.update(changes)
        validate_todos(manifest, state)
        timestamp = now()
        item["updated_utc"] = timestamp
        item["history"].append({"time_utc": timestamp, "action": "UPDATE", "before_status": old["status"],
                                "after_status": item["status"], "changes": requested_changes,
                                "evidence_added": item["evidence"][len(old["evidence"]):],
                                "notes_added": item["notes"][len(old["notes"]):]})
        state["sequence"] += 1
        state["events"].append({"action": "todo-update", "task_id": task_id,
                                "sequence": state["sequence"], "time_utc": timestamp})
        atomic(state_path(root), encoded(state))
    return todo_result(root, state)


def todo_list(root, include_closed=False):
    manifest, state = read(root)
    validate_todos(manifest, state)
    values = [item for item in state.get("todo", {}).values()
              if include_closed or item["status"] not in TODO_CLOSED]
    return sorted(values, key=lambda x: (x["priority"], x["created_utc"], x["id"]))


def apply_event(root, event, expected_hash):
    with writer(root):
        validate(root)
        if expected_hash != digest(state_path(root)):
            raise WorkflowError("Stale state hash; refresh before updating shared records")
        manifest, state = read(root)
        key = job_key(event)
        sheet, stage, action = event["sheet"], event["stage"], event["action"]
        if sheet not in manifest["sheets"]:
            raise WorkflowError("Sheet not in initialized manifest")
        job = state["jobs"].setdefault(key, new_job())
        if action in {"create", "review"}:
            require_summary(job)
            if job["awaiting_check"]:
                raise WorkflowError("Current submitted revision needs an independent check")
            current_key = state["current_jobs"].get(sheet)
            if current_key and current_key != key:
                current_job = state["jobs"][current_key]
                require_summary(current_job)
                if current_job["awaiting_check"]:
                    raise WorkflowError("Complete this sheet's current independent check before changing jobs")
                if "|DOCUMENT_ISSUES|" in current_key and current_job["status"] == "REVISE":
                    raise WorkflowError("Complete or explicitly hold the current issue before starting another")
            if stage != "PHASE1":
                phase1 = state["jobs"].get(f"{sheet}|PHASE1", new_job())
                if phase1["status"] not in ACCEPTED or phase1["summary_due"]:
                    raise WorkflowError("PHASE1 mapping must pass and be summarized first")
            if stage in {"DOCUMENT_ISSUES", "FULL_REVIEW"}:
                initial = state["jobs"].get(f"{sheet}|INITIAL", new_job())
                if initial["check_events"] == 0:
                    raise WorkflowError("Initial production must have a completed independent check")
                require_summary(initial)
            if stage == "FULL_REVIEW":
                for other_key, other in state["jobs"].items():
                    if other_key.startswith(f"{sheet}|DOCUMENT_ISSUES|"):
                        require_summary(other)
                        if other["awaiting_check"] or other["status"] == "REVISE":
                            raise WorkflowError("Complete or explicitly hold manual issues before full review")
            if action == "review" and stage != "FULL_REVIEW":
                raise WorkflowError("Unchanged-artifact review is a FULL_REVIEW event")
            if action == "review" and job["major_round"]:
                raise WorkflowError("Use create for a corrective full-review revision")
            submitted = artifacts(root, manifest, sheet, stage, event["artifacts"])
            if action == "review":
                current_key = state["current_jobs"].get(sheet)
                current = state["jobs"].get(current_key, {})
                if submitted != current.get("artifacts") or event["creator"] != current.get("creator"):
                    raise WorkflowError("First full review must bind the actual current artifacts and their creator")
            previous = job["create_events"]
            if stage == "DOCUMENT_ISSUES":
                next_round, limit = 1, None
            else:
                next_round = (job["repair_revision"] + 1 if stage == "FULL_REVIEW" and action == "create"
                              else job["major_round"] + 1)
                limit = manifest["policy"][{"PHASE1": "phase1_rounds", "INITIAL": "initial_rounds",
                                            "FULL_REVIEW": "full_review_rounds"}[stage]]
            if limit is not None and next_round > limit:
                exception = job["exception"]
                if next_round != limit + 1 or not exception or exception["used"]:
                    raise WorkflowError("Round budget exhausted; no false PASS or naming reset")
                exception["used"] = True
            repair_increment = 1 if action == "create" and (previous or stage in {"DOCUMENT_ISSUES", "FULL_REVIEW"}) else 0
            if stage == "FULL_REVIEW" and action == "create" and not job["major_round"]:
                raise WorkflowError("Start full review with review; check unchanged current artifacts before repair")
            job.update(major_round=next_round, repair_revision=job["repair_revision"] + repair_increment,
                       create_events=previous + 1, status="AWAITING_CHECK", awaiting_check=True,
                       creator=safe_id(event["creator"]), artifacts=submitted)
            state["artifact_history"].append({"sequence": state["sequence"] + 1, "job": key,
                "major_round": next_round, "repair_revision": job["repair_revision"],
                "creator": job["creator"], "manifest_sha256": state["manifest_sha256"],
                "artifacts": copy.deepcopy(submitted),
                "artifact_sha256": hashlib.sha256(encoded(submitted)).hexdigest()})
            state["current_jobs"][sheet] = key
            state["releases"].pop(sheet, None)
        elif action == "check":
            if not job["awaiting_check"]:
                raise WorkflowError("No submitted revision awaiting check")
            checker = safe_id(event["checker"])
            if checker.casefold() == job["creator"].casefold():
                raise WorkflowError("Checker must be independent of the creator")
            if not isinstance(event.get("evidence"), list) or not event["evidence"]:
                raise WorkflowError("Completed checking requires explicit source/output evidence references")
            if not isinstance(event.get("findings", []), list):
                raise WorkflowError("Findings must be a list")
            if event.get("artifact_sha256") != hashlib.sha256(encoded(job["artifacts"])).hexdigest():
                raise WorkflowError("Check must bind the exact submitted artifact-set hash")
            verdict = event["verdict"]
            if verdict not in VERDICTS:
                raise WorkflowError("Unsupported verdict")
            if verdict in {"HOLD", "PROVISIONAL", "REVISE"} and not event.get("findings"):
                raise WorkflowError("Non-PASS statuses require explicit findings or bounded uncertainty")
            if verdict == "PASS" and event.get("findings"):
                raise WorkflowError("PASS cannot conceal unresolved findings; use PROVISIONAL or HOLD")
            if verdict == "PASS_WITH_NOTES" and (not event.get("findings") or any(
                not isinstance(finding, dict) or finding.get("classification") != "cosmetic"
                or finding.get("unresolved_core") or not finding.get("note")
                for finding in event["findings"]
            )):
                raise WorkflowError("PASS_WITH_NOTES requires only nonempty cosmetic-classified notes, never unresolved core")
            job["checks"].append({"checker": checker, "major_round": job["major_round"],
                                  "artifact_sha256": event["artifact_sha256"], "verdict": verdict,
                                  "findings": event.get("findings", []), "evidence": event.get("evidence", [])})
            job.update(status=verdict, awaiting_check=False, summary_due=True,
                       check_events=job["check_events"] + 1)
        elif action == "summarize":
            if not job["summary_due"]:
                raise WorkflowError("No completed check awaiting summary")
            if event.get("decision") not in {"ADOPT", "CANDIDATE", "SKIP"} or not event.get("note"):
                raise WorkflowError("Record ADOPT, CANDIDATE or SKIP with a concise reason")
            if event["decision"] == "ADOPT" and not event.get("verification"):
                raise WorkflowError("Adoption requires explicit verification evidence")
            job["summary_due"] = False
        elif action == "hold":
            require_summary(job)
            latest = job["checks"][-1] if job["checks"] else {}
            if job["status"] != "REVISE" or job["awaiting_check"] or latest.get("verdict") != "REVISE":
                raise WorkflowError("Hold requires a completed, summarized independent REVISE result")
            if event.get("checker") != latest.get("checker") or not event.get("reason") or not event.get("evidence"):
                raise WorkflowError("Hold needs the latest independent checker, a reason and evidence")
            job["status"] = "HOLD"
            job["hold"] = {"checker": event["checker"], "reason": event["reason"], "evidence": event["evidence"],
                           "check_events": job["check_events"], "repair_revision": job["repair_revision"]}
        elif action == "exception":
            require_summary(job)
            if stage == "DOCUMENT_ISSUES":
                raise WorkflowError("Manual issue passes are not a two-round stage")
            limit = manifest["policy"][{"PHASE1": "phase1_rounds", "INITIAL": "initial_rounds",
                                        "FULL_REVIEW": "full_review_rounds"}[stage]]
            latest = job["checks"][-1] if job["checks"] else {}
            if job["major_round"] != limit or job["awaiting_check"] or job["status"] != "REVISE":
                raise WorkflowError("Exceptional round follows an exhausted, checked REVISE result")
            if event.get("category") not in CORE or not event.get("reason") or not event.get("evidence"):
                raise WorkflowError("Third round needs substantial position, shape or dimension evidence")
            if event.get("checker") != latest.get("checker"):
                raise WorkflowError("Independent latest checker must substantiate exceptional round")
            job["exception"] = {"used": False, "category": event["category"],
                                 "reason": event["reason"], "evidence": event["evidence"]}
        elif action == "release":
            require_summary(job)
            if state["current_jobs"].get(sheet) != key:
                raise WorkflowError("Cannot release a superseded job while a newer stage is current")
            if stage == "PHASE1" or job["status"] not in ACCEPTED | {"PROVISIONAL"} or job["awaiting_check"]:
                raise WorkflowError("Release needs independently checked PASS or explicitly bounded PROVISIONAL")
            state["releases"][sheet] = {"job": key, "status": job["status"],
                                       "findings": job["checks"][-1]["findings"],
                                       "artifacts": job["artifacts"]}
        else:
            raise WorkflowError("Unknown action")
        state["sequence"] += 1
        state["events"].append({**event, "sequence": state["sequence"], "time_utc": now()})
        atomic(state_path(root), encoded(state))
    return validate(root)


def artifact_set_hash(root, sheet, stage, issue=None):
    _, state = read(root)
    key = job_key({"sheet": sheet, "stage": stage, "issue": issue})
    return hashlib.sha256(encoded(state["jobs"][key]["artifacts"])).hexdigest()


def checkpoint(root):
    with writer(root):
        report = validate(root)
        manifest, state = read(root)
        payload = {"schema_version": SCHEMA, "manifest": manifest, "state": state,
                   "state_sha256": report["state_sha256"]}
        path = Path(root) / WORK / "checkpoints" / f"checkpoint-{state['sequence']:06d}.json"
        atomic(path, encoded(payload))
    return str(path)


def resume(root, checkpoint_file):
    """Restore bookkeeping into an otherwise uninitialized relocated project copy."""
    payload = json.loads(Path(checkpoint_file).read_text(encoding="utf-8"))
    if hashlib.sha256(encoded(payload["state"])).hexdigest() != payload["state_sha256"]:
        raise WorkflowError("Damaged checkpoint state")
    if hashlib.sha256(encoded(payload["manifest"])).hexdigest() != payload["state"]["manifest_sha256"]:
        raise WorkflowError("Damaged checkpoint manifest")
    validate_pins(root, payload["manifest"], payload["state"])
    with writer(root):
        if manifest_path(root).exists() or state_path(root).exists():
            raise WorkflowError("Resume refuses to overwrite active project records")
        atomic(manifest_path(root), encoded(payload["manifest"]))
        atomic(state_path(root), encoded(payload["state"]))
    return validate(root)


def _build_index(root):
    validate(root)
    manifest, state = read(root)
    dest = local(root, manifest["output_dir"]) / "index.html"
    rows = []
    for sheet in manifest["sheets"]:
        release = state["releases"].get(sheet)
        status = release["status"] if release else "NOT_RELEASED"
        links = []
        if release:
            packet = current_packet(root, manifest, sheet, release)
            items = ([("PDF SET — Plan + own elevations / 平面＋自身立面整套", packet)] if packet else [])
            items += [("Plan only / 仅平面", release["artifacts"]["plan"])] + [
                (f"Elevation {i} / 立面 {i}", item) for i, item in enumerate(release["artifacts"]["elevations"], 1)]
            for label, item in items:
                relative = os.path.relpath(local(root, item["path"]), dest.parent).replace(os.sep, "/")
                links.append(f'<a href="{quote(relative, safe="/")}">{html.escape(label)}</a>')
        notes = html.escape(json.dumps(release["findings"], ensure_ascii=False)) if release and release["findings"] else ""
        rows.append(f"<tr><td>{html.escape(sheet)}</td><td>{status}<br>{notes}</td><td>{' · '.join(links)}</td></tr>")
    body = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Drawing results / 图纸成果</title>'
            '<style>body{font:16px sans-serif;margin:2rem}table{border-collapse:collapse;width:100%;table-layout:fixed}'
            'td,th{border:1px solid #ccd;padding:12px;text-align:left;vertical-align:top;overflow-wrap:anywhere}'
            'th:first-child{width:12%}th:nth-child(2){width:28%}a{line-height:1.8}</style>'
            f'<h1>{html.escape(manifest["project_id"])} — Drawing results / 图纸成果</h1>'
            '<p>Each sheet owns its Plan and elevations. Statuses preserve unresolved conditions.<br>'
            '每张图独立平面与立面；状态保留未解决条件。</p><table><tr><th>Sheet / 图号</th>'
            '<th>Status / 状态</th><th>Results / 成果</th></tr>' + ''.join(rows) + '</table>')
    active = sorted((task for task in state.get("todo", {}).values() if task["status"] not in TODO_CLOSED),
                    key=lambda task: (task["priority"], task["created_utc"], task["id"]))
    body += '<h2>Open coordinator tasks / 协调待办</h2><p>Task status does not certify drawing quality. / 待办状态不代表图纸质量通过。</p>'
    if active:
        body += '<ul>' + ''.join('<li>' + html.escape(f"{task['priority']} {task['id']} — {task['title']} [{task['status']}]" +
            (" — " + task.get("blocker_reason", "") if task["status"] == "BLOCKED" else "")) + '</li>' for task in active) + '</ul>'
    else:
        body += '<p>No open tasks recorded. / 当前无已登记未结待办。</p>'
    body += '</html>'
    guard_pinned_outputs(root, state, dest)
    atomic(dest, body.encode("utf-8"))
    return str(dest)


def build_index(root):
    with writer(root):
        return _build_index(root)


def packet_receipt(root, manifest, sheet):
    return local(root, manifest["output_dir"] + "/" + sheet + "/packet.json")


def current_packet(root, manifest, sheet, release):
    receipt = packet_receipt(root, manifest, sheet)
    if not receipt.exists():
        return None
    value = json.loads(receipt.read_text(encoding="utf-8"))
    expected = hashlib.sha256(encoded(release["artifacts"])).hexdigest()
    if value.get("sheet") != sheet or value.get("artifact_sha256") != expected:
        raise WorkflowError(f"Stale sheet packet for {sheet}; regenerate packets before publishing index")
    try:
        check_pin(root, value["packet"])
    except WorkflowError as exc:
        raise WorkflowError(f"Stale or damaged sheet packet for {sheet}; regenerate packets") from exc
    if not local(root, value["packet"]["path"]).is_relative_to(
        local(root, manifest["output_dir"] + "/" + sheet)
    ):
        raise WorkflowError("Packet must remain inside its own sheet output directory")
    return value["packet"]


def packets(root, sheet=None, allow_provisional=False):
    """Build current, hash-pinned per-sheet PDF sets, with Plan pages first."""
    with writer(root):
        validate(root)
        manifest, state = read(root)
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError as exc:
            raise WorkflowError("Sheet packets require optional pypdf") from exc
        if sheet and sheet not in manifest["sheets"]:
            raise WorkflowError("Unknown sheet")
        built = []
        for item_sheet in ([sheet] if sheet else manifest["sheets"]):
            release = state["releases"].get(item_sheet)
            if not release:
                if sheet:
                    raise WorkflowError("Sheet packet needs a checked release")
                continue
            if release["status"] not in ACCEPTED and not allow_provisional:
                raise WorkflowError("PROVISIONAL packet inclusion requires explicit opt-in")
            dest_relative = f"{manifest['output_dir']}/{item_sheet}/{item_sheet}-SET.pdf"
            dest = local(root, dest_relative)
            guard_pinned_outputs(root, state, dest, packet_receipt(root, manifest, item_sheet))
            inputs = [release["artifacts"]["plan"], *release["artifacts"]["elevations"]]
            if any(dest == local(root, item["path"]) for item in inputs):
                raise WorkflowError("Sheet packet must not overwrite an input")
            pdf = PdfWriter()
            try:
                page_order = []
                for item in inputs:
                    reader = PdfReader(str(local(root, item["path"])))
                    if not reader.pages:
                        raise WorkflowError("Cannot include an empty PDF in a sheet packet")
                    pdf.append(reader, import_outline=False)
                    page_order.append({**item, "pages": len(reader.pages)})
                import io
                stream = io.BytesIO()
                pdf.write(stream)
                validate(root)
                atomic(dest, stream.getvalue())
                receipt = {"schema_version": SCHEMA, "sheet": item_sheet, "status": release["status"],
                           "artifact_sha256": hashlib.sha256(encoded(release["artifacts"])).hexdigest(),
                           "packet": pin(root, dest_relative), "order": page_order,
                           "pages": len(pdf.pages), "allow_provisional": allow_provisional}
                atomic(packet_receipt(root, manifest, item_sheet), encoded(receipt))
                built.append(receipt["packet"])
            finally:
                pdf.close()
        return built


def _merge(root, output="combined.pdf", allow_provisional=False):
    validate(root)
    manifest, state = read(root)
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise WorkflowError("PDF merge requires optional pypdf; bookkeeping is standard-library only") from exc
    writer_pdf, order = PdfWriter(), []
    try:
        for sheet in manifest["sheets"]:
            release = state["releases"].get(sheet)
            if not release or (release["status"] not in ACCEPTED and not allow_provisional):
                raise WorkflowError("Every sheet must be released; PROVISIONAL inclusion requires explicit opt-in")
            for item in [release["artifacts"]["plan"], *release["artifacts"]["elevations"]]:
                reader = PdfReader(str(local(root, item["path"])))
                if not reader.pages:
                    raise WorkflowError("Cannot include empty PDF")
                writer_pdf.append(reader, import_outline=False)
                order.append({"sheet": sheet, **item, "pages": len(reader.pages)})
        dest = local(root, manifest["output_dir"] + "/" + output)
        guard_pinned_outputs(root, state, dest, dest.with_suffix(".merge.json"))
        if any(dest == local(root, item["path"]) for release in state["releases"].values()
               for item in flatten(release["artifacts"])):
            raise WorkflowError("Combined PDF must not overwrite an input")
        import io
        stream = io.BytesIO()
        writer_pdf.write(stream)
        validate(root)
        atomic(dest, stream.getvalue())
        atomic(dest.with_suffix(".merge.json"), encoded({"schema_version": SCHEMA, "order": order,
                "pages": len(writer_pdf.pages), "sha256": digest(dest), "allow_provisional": allow_provisional}))
        return str(dest)
    finally:
        writer_pdf.close()


def merge(root, output="combined.pdf", allow_provisional=False):
    with writer(root):
        return _merge(root, output, allow_provisional)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Project root; never stored as an absolute dependency")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init").add_argument("--manifest", required=True)
    commands.add_parser("validate")
    command = commands.add_parser("event")
    command.add_argument("--file", required=True)
    command.add_argument("--expected-state", required=True)
    command = commands.add_parser("artifact-hash")
    command.add_argument("--sheet", required=True)
    command.add_argument("--stage", required=True, choices=STAGES)
    command.add_argument("--issue")
    commands.add_parser("checkpoint")
    commands.add_parser("index")
    commands.add_parser("resume").add_argument("--checkpoint", required=True)
    command = commands.add_parser("todo-add")
    command.add_argument("--file", required=True)
    command.add_argument("--expected-state", required=True)
    command = commands.add_parser("todo-update")
    command.add_argument("--id", required=True)
    command.add_argument("--file", required=True)
    command.add_argument("--expected-state", required=True)
    commands.add_parser("todo-list").add_argument("--all", action="store_true")
    command = commands.add_parser("packets")
    command.add_argument("--sheet")
    command.add_argument("--allow-provisional", action="store_true")
    command = commands.add_parser("merge")
    command.add_argument("--output", default="combined.pdf")
    command.add_argument("--allow-provisional", action="store_true")
    args = parser.parse_args()
    if args.command == "init":
        result = init(args.root, json.loads(Path(args.manifest).read_text(encoding="utf-8-sig")))
    elif args.command == "event":
        result = apply_event(args.root, json.loads(Path(args.file).read_text(encoding="utf-8-sig")), args.expected_state)
    elif args.command == "artifact-hash":
        result = artifact_set_hash(args.root, args.sheet, args.stage, args.issue)
    elif args.command == "merge":
        result = merge(args.root, args.output, args.allow_provisional)
    elif args.command == "packets":
        result = packets(args.root, args.sheet, args.allow_provisional)
    elif args.command == "todo-add":
        result = todo_add(args.root, json.loads(Path(args.file).read_text(encoding="utf-8-sig")), args.expected_state)
    elif args.command == "todo-update":
        result = todo_update(args.root, args.id, json.loads(Path(args.file).read_text(encoding="utf-8-sig")), args.expected_state)
    elif args.command == "todo-list":
        result = {"state_sha256": digest(state_path(args.root)), "tasks": todo_list(args.root, args.all)}
    elif args.command == "resume":
        result = resume(args.root, args.checkpoint)
    else:
        result = {"validate": validate, "checkpoint": checkpoint, "index": build_index}[args.command](args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (WorkflowError, OSError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
