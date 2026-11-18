"""Per-customer immutable SQLite revisions and proposal transactions."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .paths import filesystem_path

ACTIVE_JOB_STATUSES = ("queued", "running", "pausing", "paused")
INTERRUPTED_JOB = {"status": "failed", "phase": "interrupted", "error_category": "interrupted",
                   "error": "The app closed before this task finished; saved design retained. / 应用在任务完成前关闭，已保存设计保留。"}


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value.model_dump(mode="json") if hasattr(value, "model_dump") else value,
                      ensure_ascii=False, separators=(",", ":"))


class Conflict(ValueError):
    pass


class NotFound(ValueError):
    pass


class JobInterrupted(Conflict):
    """A project control invalidated this worker's generation token."""


class JobPaused(Conflict):
    """A pause won the race with publication at a worker checkpoint."""


def is_empty_design(model):
    """Only an untouched empty model can accept approved source results."""
    from .geometry import empty_model, validate_model
    canonical = validate_model(model)
    return canonical.model_dump(mode="json") == empty_model(canonical.name).model_dump(mode="json")


class Repository:
    def __init__(self, root: Path):
        self.root = filesystem_path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, project_id):
        if not re.fullmatch(r"[a-f0-9]{32}", project_id):
            raise NotFound("Unknown project / 未找到项目")
        result = (self.root / project_id).resolve()
        if result.parent != self.root:
            raise NotFound("Invalid project path / 项目路径无效")
        return result

    def drawing_cycle_ledger_path(self, project_id):
        """Stable project-owned allowance, never an output/run/profile directory."""
        self.get(project_id)  # Reject unknown or deleted projects without creating state.
        return self.directory(project_id) / "workflow-state" / "2d-group-cycles.json"

    def grouped_2d_plan_path(self, project_id):
        return self.directory(project_id) / "workflow-state" / "grouped-2d-plan.json"

    @contextmanager
    def connect(self, project_id):
        directory = self.directory(project_id)
        if not (directory / "project.sqlite").is_file():
            raise NotFound("Unknown project / 未找到项目")
        connection = sqlite3.connect(directory / "project.sqlite", timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def create(self, name, model=None, *, project_id=None):
        from .geometry import empty_model, validate_model
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError("Enter a project name (1–120 characters) / 请输入项目名称（1–120 字符）")
        project_id = project_id or uuid4().hex
        directory = self.directory(project_id)
        directory.mkdir(exist_ok=False)
        connection = sqlite3.connect(directory / "project.sqlite")
        try:
            connection.executescript("""
                PRAGMA user_version=1;
                CREATE TABLE revisions(revision INTEGER PRIMARY KEY,model TEXT NOT NULL,summary TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE documents(id TEXT PRIMARY KEY,metadata TEXT NOT NULL);
                CREATE TABLE proposals(id TEXT PRIMARY KEY,base_revision INTEGER NOT NULL,model TEXT NOT NULL,summary TEXT NOT NULL,warnings TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE jobs(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE project_state(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
            """)
            canonical = validate_model(model) if model is not None else empty_model(name)
            connection.execute("INSERT INTO revisions VALUES(1,?,?,?)", (encode(canonical), "New project / 新建项目", now()))
            connection.commit()
        finally:
            connection.close()
        return self.get(project_id)

    def get(self, project_id):
        with self.connect(project_id) as connection:
            connection.execute("BEGIN")
            state = self._state(connection)
            if state.get("deleted_at"):
                raise NotFound("Unknown project / 未找到项目")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != 1:
                raise ValueError("Unsupported project version; original retained / 项目版本不受支持，原文件已保留")
            latest = connection.execute("SELECT * FROM revisions ORDER BY revision DESC LIMIT 1").fetchone()
            history = [dict(x) for x in connection.execute("SELECT revision,summary,created_at FROM revisions ORDER BY revision DESC")]
            documents = [json.loads(x[0]) for x in connection.execute("SELECT metadata FROM documents ORDER BY rowid")]
            pending = self._current_pending(connection, latest["revision"])
            jobs = [json.loads(x[0]) for x in connection.execute("SELECT data FROM jobs ORDER BY rowid DESC")]
            active = next((job for job in jobs if job["status"] in ACTIVE_JOB_STATUSES), None)
            can_retry_2d = not active and self._empty_2d_failure(connection, pending, jobs)
        model = json.loads(latest["model"])
        result = {"id": project_id, "name": state.get("display_name") or model["name"], "revision": latest["revision"],
                  "model": model, "documents": documents, "history": history, "updated_at": latest["created_at"],
                  "pending_proposal": {"id": pending["id"]} if pending else None, "active_job": active,
                  "can_retry_2d": can_retry_2d,
                  **{key: state.get(key) for key in ("lifecycle", "lifecycle_updated_at", "is_demo", "demo_key", "reference_source_key", "display_name")},
                  "can_delete": not state["is_demo"]}
        return result

    @staticmethod
    def _current_pending(connection, revision):
        return connection.execute("SELECT id FROM proposals WHERE status='pending' AND base_revision=? ORDER BY rowid DESC LIMIT 1",
                                  (revision,)).fetchone()

    @staticmethod
    def _empty_2d_failure(connection, pending, jobs):
        if pending is None:
            return False
        for job in jobs:
            if job.get("proposal_id") != pending["id"] or job.get("kind") != "analyze" or job.get("status") != "needs_review":
                continue
            receipt = job.get("workflow_2d") or {}
            if receipt.get("accepted") is False and receipt.get("status") == "NOT_REVIEWED" and receipt.get("view_count") == 0:
                row = connection.execute("SELECT model FROM proposals WHERE id=?", (pending["id"],)).fetchone()
                return not json.loads(row["model"]).get("drawings")
        return False

    def list(self):
        result = []
        for directory in self.root.iterdir():
            if not directory.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", directory.name):
                continue
            try:
                item = self.get(directory.name)
                result.append({key: item[key] for key in ("id", "name", "revision", "updated_at", "lifecycle", "lifecycle_updated_at", "is_demo", "demo_key", "can_delete", "reference_source_key", "display_name")}
                              | {"document_count": len(item["documents"])})
            except (ValueError, sqlite3.Error, OSError):
                continue
        return sorted(result, key=lambda x: x["updated_at"], reverse=True)

    @staticmethod
    def _state(connection):
        # Reading an old project must not migrate or otherwise change its bytes.
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_state'").fetchone()
        row = connection.execute("SELECT data FROM project_state WHERE id=1").fetchone() if exists else None
        defaults = {"lifecycle": "active", "lifecycle_epoch": 0, "lifecycle_updated_at": None,
                    "is_demo": False, "demo_key": None, "deleted_at": None}
        return defaults | (json.loads(row[0]) if row else {})

    @staticmethod
    def _save_state(connection, state):
        connection.execute("CREATE TABLE IF NOT EXISTS project_state(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)")
        connection.execute("INSERT OR REPLACE INTO project_state VALUES(1,?)", (encode(state),))

    def _require_active(self, connection):
        state = self._state(connection)
        if state.get("deleted_at"):
            raise NotFound("Unknown project / 未找到项目")
        if state["lifecycle"] != "active":
            raise Conflict("Resume this project before making changes / 请先恢复此项目再修改")
        return state

    def require_active(self, project_id):
        with self.connect(project_id) as connection:
            return self._require_active(connection)

    def rename(self, project_id, name, expected_revision):
        """Set the project title independently of its saved design revisions."""
        name = name.strip() if isinstance(name, str) else ""
        if not 1 <= len(name) <= 120:
            raise ValueError("Enter a project name (1–120 characters) / 请输入项目名称（1–120 字符）")
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection)
            if state.get("deleted_at"):
                raise NotFound("Unknown project / 未找到项目")
            current = connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
            if current != expected_revision:
                raise Conflict("Project changed; reload before renaming / 项目已更改，请重新加载后再重命名")
            if any(json.loads(row[0])["status"] in ACTIVE_JOB_STATUSES
                   for row in connection.execute("SELECT data FROM jobs")):
                raise Conflict("Finish the current task before renaming / 请先结束当前任务，再重命名项目")
            state["display_name"] = name
            self._save_state(connection, state)
            connection.commit()
        return self.get(project_id)

    def _require_job_active(self, connection, job_id):
        state = self._state(connection)
        row = connection.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFound("Job not found / 未找到任务")
        job = json.loads(row[0])
        paused_worker = (state["lifecycle"] == "paused" and self._holds_on_project_pause(job)
                         and job["status"] in ("pausing", "paused"))
        if (state.get("deleted_at") or (state["lifecycle"] != "active" and not paused_worker)
                or job["status"] not in ACTIVE_JOB_STATUSES
                or job.get("lifecycle_epoch", 0) != state["lifecycle_epoch"]):
            raise JobInterrupted("Project task was paused or stopped; saved design retained / 项目任务已暂停或停止，已保存设计保留")
        return job

    def require_job_active(self, job_id):
        with self.connect(job_id.split(".")[0]) as connection:
            connection.execute("BEGIN")
            return self._require_job_active(connection, job_id)

    def _require_job_unpaused(self, connection, job_id):
        job = self._require_job_active(connection, job_id)
        if job["status"] in ("pausing", "paused"):
            raise JobPaused("The task is paused / 任务已暂停")
        return job

    @staticmethod
    def _holds_on_project_pause(job):
        return job.get("kind") in ("analyze", "materials") or bool(job.get("draft_3d_group_id") or job.get("draft_3d_sequence"))

    def set_lifecycle(self, project_id, action, expected_revision):
        transitions = {"pause": "paused", "stop": "stopped", "resume": "active"}
        if action not in transitions:
            raise ValueError("Unknown project action / 未知项目操作")
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection)
            if state.get("deleted_at"):
                raise NotFound("Unknown project / 未找到项目")
            current = connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
            if current != expected_revision:
                raise Conflict("Project changed; reload before changing its status / 项目已更改，请重新加载后再更改状态")
            lifecycle = transitions[action]
            # Retained workers pause at their next checkpoint and resume with
            # the same task identity and any completed provider response.
            retained_job = None
            if (action == "pause" and state["lifecycle"] in ("active", "paused")) or (
                    action == "resume" and state["lifecycle"] == "paused"):
                jobs = (json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs"))
                retained_job = next((job for job in jobs if self._holds_on_project_pause(job)
                                     and job["status"] in ACTIVE_JOB_STATUSES
                                     and job.get("lifecycle_epoch", 0) == state["lifecycle_epoch"]), None)
            if lifecycle != state["lifecycle"]:
                state.update(lifecycle=lifecycle, lifecycle_updated_at=now())
                if retained_job is None:
                    state["lifecycle_epoch"] += 1
                else:
                    self._apply_job_control(retained_job, action)
                    connection.execute("UPDATE jobs SET data=? WHERE id=?", (encode(retained_job), retained_job["id"]))
                self._save_state(connection, state)
            if lifecycle != "active":
                self._cancel_jobs(connection, lifecycle, except_job_id=retained_job["id"] if retained_job else None)
            connection.commit()
        return self.get(project_id)

    @staticmethod
    def _settle_group_jobs(job):
        if job["status"] not in ("cancelled", "failed"):
            return
        for group in [*job.get("groups_2d", []), *job.get("draft_3d_sequence", [])]:
            if group["status"] in ("queued", "running"):
                group["status"] = job["status"]
                if job.get("error_category") == "interrupted":
                    group["error_category"] = "interrupted"

    @staticmethod
    def _cancel_jobs(connection, reason, *, except_job_id=None):
        for row in list(connection.execute("SELECT id,data FROM jobs")):
            if row["id"] == except_job_id:
                continue
            job = json.loads(row["data"])
            if job["status"] in ACTIVE_JOB_STATUSES:
                job.update(status="cancelled", phase=reason, updated_at=now(),
                           error="Task ended when this project was paused or stopped. Saved work and completed outputs are retained. / 此项目暂停或停止时，任务已结束。已保存的工作和已完成的输出均已保留。",
                           error_category="project_" + reason)
                Repository._settle_group_jobs(job)
                connection.execute("UPDATE jobs SET data=? WHERE id=?", (encode(job), row["id"]))

    def protect_demo(self, project_id, demo_key):
        """Set built-in provenance only from trusted server paths, never archive input."""
        if not isinstance(demo_key, str) or not demo_key or len(demo_key) > 160:
            raise ValueError("Invalid built-in demo key")
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection)
            if state.get("deleted_at"):
                raise NotFound("Unknown project / 未找到项目")
            state.update(is_demo=True, demo_key=demo_key)
            self._save_state(connection, state)
            connection.commit()
        return self.get(project_id)

    def find_demo(self, demo_key):
        return next((self.get(item["id"]) for item in self.list()
                     if item["is_demo"] and item["demo_key"] == demo_key), None)

    def attach_reference_source(self, project_id, source_key, display_name):
        """Attach ordinary asset metadata without changing saved design revisions.

        This trusted startup/import operation grants no deletion protection. A
        converted legacy reference project keeps its source files and history.
        """
        if not isinstance(source_key, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", source_key):
            raise ValueError("Invalid reference source key")
        if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 120:
            raise ValueError("Invalid project display name")
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection)
            if state.get("deleted_at"):
                raise NotFound("Unknown project / 未找到项目")
            already_attached = state.get("reference_source_key") == source_key
            if not (already_attached and not state.get("is_demo") and state.get("demo_key") is None and state.get("display_name")):
                state.update(reference_source_key=source_key, is_demo=False, demo_key=None)
                if not already_attached or not state.get("display_name"):
                    state["display_name"] = display_name.strip()
                self._save_state(connection, state)
                connection.commit()
        return self.get(project_id)

    def make_ordinary(self, project_id):
        """Remove obsolete protection metadata, preserving all design records."""
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection)
            if state.get("deleted_at"):
                raise NotFound("Unknown project / 未找到项目")
            if state.get("is_demo") or state.get("demo_key") is not None:
                state.update(is_demo=False, demo_key=None)
                self._save_state(connection, state)
                connection.commit()
        return self.get(project_id)

    def delete(self, project_id, expected_revision):
        # A tombstone removes the project from all public access while retaining
        # recoverable local data. No arbitrary paths or recursive deletes occur.
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._state(connection)
            if state.get("deleted_at"):
                raise NotFound("Unknown project / 未找到项目")
            if state["is_demo"]:
                raise Conflict("Built-in demo projects cannot be deleted / 内置演示项目不能删除")
            current = connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
            if current != expected_revision:
                raise Conflict("Project changed; reload before deleting / 项目已更改，请重新加载后再删除")
            state.update(deleted_at=now(), lifecycle="stopped", lifecycle_epoch=state["lifecycle_epoch"] + 1,
                         lifecycle_updated_at=now())
            self._save_state(connection, state)
            self._cancel_jobs(connection, "deleted")
            connection.commit()
        return {"deleted": True, "id": project_id}

    def add_document(self, project_id, metadata):
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active(connection)
            if any(job.get("grouped_2d") and job["status"] in ACTIVE_JOB_STATUSES
                   for job in (json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs"))):
                raise Conflict("Finish the drawing groups before adding another source. / 请先完成图纸组任务，再添加新原图。")
            connection.execute("INSERT INTO documents VALUES(?,?)", (metadata["id"], encode(metadata)))
            connection.commit()

    def install_reviewed_design(self, project_id, expected_revision, model, source_document, source_key):
        """Atomically import approved results into the same still-empty project."""
        from .geometry import validate_model
        model = validate_model(model)
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._require_active(connection)
            latest = connection.execute("SELECT * FROM revisions ORDER BY revision DESC LIMIT 1").fetchone()
            if latest["revision"] != expected_revision:
                raise Conflict("Project changed; reload before importing approved results")
            previous = json.loads(latest["model"])
            if state.get("reference_source_key") or not is_empty_design(previous):
                raise Conflict("Approved results can only be imported into an empty project; saved work is retained")
            if connection.execute("SELECT 1 FROM proposals WHERE status='pending' LIMIT 1").fetchone():
                raise Conflict("Resolve the pending preview before importing approved results")
            for row in connection.execute("SELECT data FROM jobs"):
                if json.loads(row[0]).get("status") in ACTIVE_JOB_STATUSES:
                    raise Conflict("Wait for the current task before importing approved results")
            stored = connection.execute("SELECT metadata FROM documents WHERE id=?", (source_document["id"],)).fetchone()
            if stored is None or json.loads(stored[0]) != source_document:
                raise Conflict("The attached source changed; reload before importing approved results")
            path = filesystem_path(source_document["local_path"])
            if not path.is_relative_to(self.directory(project_id)) or not path.is_file():
                raise ValueError("The attached original PDF is unavailable")
            with path.open("rb") as original:
                if hashlib.file_digest(original, "sha256").hexdigest() != source_document["sha256"]:
                    raise ValueError("The attached original PDF changed; upload the original file again")
            name = state.get("display_name") or previous["name"]
            if model.name != name:
                raise ValueError("Approved results must retain the project name")
            connection.execute("INSERT INTO revisions VALUES(?,?,?,?)", (expected_revision + 1, encode(model),
                "Import approved design results from attached PDF", now()))
            state.update(reference_source_key=source_key, display_name=name, is_demo=False, demo_key=None)
            self._save_state(connection, state)
            connection.commit()
        return self.get(project_id)

    def _check_group_review_inputs(self, connection, inputs, *, owning_job_id=None):
        jobs = [json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs")]
        latest = max((job for job in jobs if job.get("grouped_2d")),
                     key=lambda job: job.get("updated_at", ""), default=None)
        documents = [json.loads(row[0]) for row in connection.execute("SELECT metadata FROM documents ORDER BY rowid")]
        if (latest is None or latest["id"] != inputs["source_job_id"]
                or documents != inputs["documents"]
                or any(job["status"] in ACTIVE_JOB_STATUSES and job["id"] != owning_job_id for job in jobs)):
            raise Conflict("The drawing groups or their originals changed. Reopen Step 3 to review the current results.")

    def save_grouped_3d_design(self, project_id, expected_revision, model, summary, inputs,
                               *, owning_job_id=None, finish=None):
        from .geometry import validate_model
        candidate = validate_model(model)
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            active_job = self._require_job_unpaused(connection, owning_job_id) if owning_job_id else None
            self._require_active(connection)
            previous = connection.execute("SELECT revision,model FROM revisions ORDER BY revision DESC LIMIT 1").fetchone()
            if (previous["revision"] != expected_revision or not is_empty_design(json.loads(previous["model"]))
                    or self._current_pending(connection, expected_revision)):
                raise Conflict("The saved design or preview changed. Reopen the project before saving the grouped model.")
            self._check_group_review_inputs(connection, inputs, owning_job_id=owning_job_id)
            revision = expected_revision + 1
            connection.execute("INSERT INTO revisions VALUES(?,?,?,?)", (revision, encode(candidate), summary, now()))
            if active_job is not None:
                job = active_job | finish | {"updated_at": now(), "editable_design_revision": revision}
                connection.execute("UPDATE jobs SET data=? WHERE id=?", (encode(job), owning_job_id))
            connection.commit()
        return revision

    def proposal(self, project_id, base_revision, model, summary, warnings=None, *, replaces=None, job_id=None,
                 group_review_inputs=None, job_completion=None, require_idle=False):
        from .geometry import validate_model
        model = validate_model(model)
        proposal_id = uuid4().hex
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if job_id is not None:
                linked_job = self._require_job_unpaused(connection, job_id)
            else:
                self._require_active(connection)
            current = connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
            if current != base_revision:
                raise Conflict("Project changed; request a new preview / 项目已更改，请重新生成预览")
            if require_idle and (self._current_pending(connection, current) or any(
                    json.loads(row[0])["status"] in ACTIVE_JOB_STATUSES
                    for row in connection.execute("SELECT data FROM jobs"))):
                raise Conflict("Finish the current task or preview before preparing board specifications.")
            if job_completion is not None and self._current_pending(connection, current):
                raise Conflict("Finish the existing preview before opening the material suggestions.")
            if group_review_inputs:
                self._check_group_review_inputs(connection, group_review_inputs)
                if self._current_pending(connection, current):
                    raise Conflict("Finish the existing preview before reviewing the grouped 3D design.")
            if replaces:
                previous = connection.execute("SELECT status,base_revision FROM proposals WHERE id=?", (replaces,)).fetchone()
                if previous is None:
                    raise NotFound("Preview not found / 未找到预览")
                if previous["status"] != "pending" or previous["base_revision"] != current:
                    raise Conflict("The original preview changed; reopen the current preview / 原预览已改变，请重新打开当前预览")
                if job_id and linked_job.get("retry_proposal_id"):
                    latest_pending = self._current_pending(connection, current)
                    if latest_pending is None or latest_pending["id"] != replaces:
                        raise Conflict("The preview changed during retry; reopen the project. / 重试期间预览已改变，请重新打开项目。")
            connection.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?,?)", (
                proposal_id, base_revision, encode(model), summary, encode(warnings or []), "pending", now()))
            if job_id is not None:
                # Publish the task association in the same transaction as its
                # preview. Apply must see a running/unapproved 3D job even in
                # the short interval before the worker saves its final result.
                linked_job.update(job_completion or {}, proposal_id=proposal_id, updated_at=now())
                connection.execute("UPDATE jobs SET data=? WHERE id=?", (encode(linked_job), job_id))
            if group_review_inputs:
                review_id = f"{project_id}.{uuid4().hex}"
                record = {"id": review_id, "project_id": project_id, "base_revision": current,
                          "kind": "group_review_3d", "status": "ready", "phase": "review", "progress": 100,
                          "created_at": now(), "updated_at": now(), "proposal_id": proposal_id,
                          "group_review_inputs": group_review_inputs}
                connection.execute("INSERT INTO jobs VALUES(?,?)", (review_id, encode(record)))
            if replaces:
                connection.execute("UPDATE proposals SET status='superseded' WHERE id=?", (replaces,))
            connection.commit()
        return self.get_proposal(project_id, proposal_id)

    def get_proposal(self, project_id, proposal_id):
        from .geometry import build_scene
        self.get(project_id)
        with self.connect(project_id) as connection:
            row = connection.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            raise NotFound("Preview not found / 未找到预览")
        result = dict(row)
        result["model"] = json.loads(result["model"])
        result["warnings"] = json.loads(result["warnings"])
        result["scene"] = build_scene(result["model"], project_id, row["base_revision"] + 1)
        return result

    def apply(self, project_id, proposal_id, expected_revision, *, group_review_inputs=None):
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active(connection)
            current = connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
            row = connection.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
            if row is None:
                raise NotFound("Preview not found / 未找到预览")
            if current != expected_revision or row["base_revision"] != current or row["status"] != "pending":
                raise Conflict("This preview is stale or already applied / 此预览已过期或已应用")
            if group_review_inputs:
                self._check_group_review_inputs(connection, group_review_inputs)
            connection.execute("INSERT INTO revisions VALUES(?,?,?,?)", (current + 1, row["model"], row["summary"], now()))
            connection.execute("UPDATE proposals SET status='expired' WHERE status='pending'")
            connection.execute("UPDATE proposals SET status='applied' WHERE id=?", (proposal_id,))
            connection.commit()
        return self.get(project_id)

    def discard(self, project_id, proposal_id):
        with self.connect(project_id) as connection:
            self._require_active(connection)
            connection.execute("UPDATE proposals SET status='discarded' WHERE id=? AND status='pending'", (proposal_id,))
            connection.commit()

    def restore(self, project_id, expected_revision, target_revision):
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active(connection)
            current = connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
            row = connection.execute("SELECT model FROM revisions WHERE revision=?", (target_revision,)).fetchone()
            if current != expected_revision:
                raise Conflict("Project changed; reload before restoring / 项目已更改，请重新加载后恢复")
            if row is None:
                raise NotFound("Revision not found / 未找到版本")
            connection.execute("INSERT INTO revisions VALUES(?,?,?,?)", (
                current + 1, row[0], f"Restore revision {target_revision} / 恢复版本 {target_revision}", now()))
            connection.execute("UPDATE proposals SET status='expired' WHERE status='pending'")
            connection.commit()
        return self.get(project_id)

    def put_job(self, project_id, job):
        with self.connect(project_id) as connection:
            self._require_active(connection)
            connection.execute("INSERT OR REPLACE INTO jobs VALUES(?,?)", (job["id"], encode(job)))
            connection.commit()

    def start_job(self, project_id, job):
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            state = self._require_active(connection)
            job = dict(job, lifecycle_epoch=state["lifecycle_epoch"])
            current = connection.execute("SELECT MAX(revision) FROM revisions").fetchone()[0]
            if current != job["base_revision"]:
                raise Conflict("Project changed; reload before starting / 项目已更改，请重新加载后开始")
            if job.get("source_proposal_id"):
                pending = connection.execute("SELECT status,base_revision FROM proposals WHERE id=?", (job["source_proposal_id"],)).fetchone()
                if pending is None:
                    raise NotFound("Preview not found / 未找到预览")
                if pending["status"] != "pending" or pending["base_revision"] != current:
                    raise Conflict("This preview is stale or already applied / 此预览已过期或已应用")
            jobs = [json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs")]
            if any(previous["status"] in ACTIVE_JOB_STATUSES for previous in jobs):
                raise Conflict("This project already has an AI task running. Reopen it to follow progress. / 此项目已有 AI 任务运行，请重新打开项目查看进度。")
            group_draft = job.get("draft_3d_group_id") or job.get("draft_3d_sequence")
            if (job.get("grouped_2d") or group_draft) and self._current_pending(connection, current):
                raise Conflict("Finish the existing preview before drawing groups. / 请先处理当前预览，再绘制图纸组。")
            if job.get("rebuild_saved_groups") and not job.get("retry_from_job_id"):
                from .api_drawing_workflow import content_hash
                plan = self.grouped_2d_plan_path(project_id)
                if (plan.exists() or (plan.parent / "group-cycles").exists()
                        or any(previous.get("grouped_2d") and previous.get("groups_2d") for previous in jobs)):
                    raise Conflict("Drawing groups already exist. Reopen the group controls to rebuild them.")
                documents = [json.loads(row[0]) for row in connection.execute("SELECT metadata FROM documents ORDER BY rowid")]
                identity = content_hash([{"id": document["id"], "sha256": document["sha256"], "page_count": document["page_count"]}
                                         for document in documents])
                if identity != job["source_set_sha256"]:
                    raise Conflict("The original PDF set changed. Reopen the project before rebuilding groups.")
            group_source_job_id = job.get("draft_3d_source_job_id") or job.get("retry_from_job_id")
            latest_group = max((previous for previous in jobs if previous.get("grouped_2d")),
                               key=lambda previous: previous.get("updated_at", ""), default=None) if group_source_job_id else None
            if group_draft and (not latest_group or latest_group["id"] != group_source_job_id):
                raise Conflict("The source group has changed. Reopen the drawing group before creating its 3D draft.")
            if job.get("draft_3d_resume_from"):
                latest = max(jobs, key=lambda previous: previous.get("updated_at", ""), default=None)
                if not latest or latest["id"] != job["draft_3d_resume_from"]:
                    raise Conflict("The 3D sequence has changed. Reopen the project before resuming.")
            if job.get("retry_from_job_id"):
                from .api_drawing_workflow import _source_identity
                prior = latest_group
                documents = [json.loads(row[0]) for row in connection.execute("SELECT metadata FROM documents ORDER BY rowid")]
                eligible = ("ready", "needs_review", "failed", "cancelled") if job.get("rebuild_group_ids") else ("needs_review", "failed", "cancelled")
                if (not prior or prior["id"] != job["retry_from_job_id"] or prior["base_revision"] != current
                        or prior["status"] not in eligible
                        or not prior.get("grouped_2d") or _source_identity(documents) != job["retry_source_set_sha256"]):
                    raise Conflict("The previous drawing task changed. Reopen the group before retrying. / 上一次绘图任务已改变，请重新打开图纸组后重试。")
                if "recover_group_ids" in job:
                    from .grouped_2d import is_group_interruption
                    if not is_group_interruption(prior):
                        raise Conflict("Only an interrupted 2D task can continue from its checkpoint. / 只有中断的二维任务可以从检查点继续。")
            if job.get("retry_proposal_id"):
                pending = self._current_pending(connection, current)
                if (job["kind"] != "analyze" or pending is None or pending["id"] != job["retry_proposal_id"]
                        or not self._empty_2d_failure(connection, pending, jobs)):
                    raise Conflict("The empty preview is no longer eligible for retry. / 空白预览已无法重试。")
            connection.execute("INSERT INTO jobs VALUES(?,?)", (job["id"], encode(job)))
            connection.commit()

    def finish_3d_sequence_group(self, job_id, child):
        with self.connect(job_id.split(".")[0]) as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._require_job_unpaused(connection, job_id)
            group_id = child["draft_3d_group_id"]
            group = next(row for row in job["draft_3d_sequence"] if row["group_id"] == group_id)
            if (job["draft_3d_current_group_id"] != group_id or group["status"] != "running"
                    or child["project_id"] != job["project_id"] or child["base_revision"] != job["base_revision"]):
                raise Conflict("The 3D group is no longer the active sequence step.")
            completed_at = now()
            group.update(status=child["status"], job_id=child["id"])
            child = dict(child, updated_at=completed_at, lifecycle_epoch=job["lifecycle_epoch"])
            connection.execute("INSERT INTO jobs VALUES(?,?)", (child["id"], encode(child)))
            job.update(updated_at=now())
            connection.execute("UPDATE jobs SET data=? WHERE id=?", (encode(job), job_id))
            connection.commit()

    def get_job(self, job_id):
        project_id = job_id.split(".")[0]
        with self.connect(project_id) as connection:
            row = connection.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise NotFound("Job not found / 未找到任务")
        return json.loads(row[0])

    def latest_job(self, project_id, *, grouped_2d=False):
        with self.connect(project_id) as connection:
            jobs = [json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs")]
        return max((job for job in jobs if not grouped_2d or job.get("grouped_2d")),
                   key=lambda item: item.get("updated_at", ""), default=None)

    def control_job(self, job_id, action, expected_revision):
        """Control this worker cooperatively; keep its revision/run/cycle identity."""
        if action not in ('pause','resume','stop'):
            raise ValueError('Unknown task action / 未知任务操作')
        project_id=job_id.split('.')[0]
        with self.connect(project_id) as connection:
            connection.execute('BEGIN IMMEDIATE')
            self._require_active(connection)
            current=connection.execute('SELECT MAX(revision) FROM revisions').fetchone()[0]
            if current!=expected_revision:
                raise Conflict('Project changed; reload before controlling this task / 项目已更改，请重新加载后再操作任务')
            row=connection.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:raise NotFound('Job not found / 未找到任务')
            job=json.loads(row[0])
            if job['status'] not in ACTIVE_JOB_STATUSES:
                if action=='stop' and job['status']=='cancelled':return job
                raise Conflict('This task has already finished / 此任务已经结束')
            self._require_job_active(connection,job_id)
            self._apply_job_control(job, action)
            connection.execute('UPDATE jobs SET data=? WHERE id=?',(encode(job),job_id));connection.commit()
        return job

    @staticmethod
    def _apply_job_control(job, action):
        if action == "pause" and job["status"] in ("queued", "running"):
            job.update(resume_phase=job.get("phase", "queued"), resume_progress=job.get("progress", 0),
                       status="pausing", phase="pausing", pause_requested_at=now())
        elif action == "resume" and job["status"] in ("pausing", "paused"):
            job.update(status="running", phase=job.get("resume_phase", "running"),
                       progress=job.get("resume_progress", job.get("progress", 0)), resumed_at=now())
        elif action == "stop":
            job.update(status="cancelled", phase="stopped",
                       error="Task stopped; your saved design is retained. / 任务已停止，已保存的设计保留。",
                       error_category="job_stopped")
            Repository._settle_group_jobs(job)
        job["updated_at"] = now()

    def pause_at_checkpoint(self, job_id):
        """Atomically acknowledge only a still-pending cooperative pause."""
        with self.connect(job_id.split('.')[0]) as connection:
            connection.execute('BEGIN IMMEDIATE')
            job=self._require_job_active(connection,job_id)
            if job['status']=='pausing':
                job.update(status='paused',phase='paused',paused_at=now(),updated_at=now())
                connection.execute('UPDATE jobs SET data=? WHERE id=?',(encode(job),job_id))
            connection.commit()
        return job

    def update_job(self, job_id, *, require_unpaused=False, **changes):
        project_id = job_id.split(".")[0]
        with self.connect(project_id) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise NotFound("Job not found / 未找到任务")
            previous = json.loads(row[0])
            # Late progress/error/completion from an invalidated worker may never
            # revive it, even after a quick Pause -> Resume transition.
            if previous["status"] == "cancelled" or (previous['status']=='failed' and previous.get('error_category')=='interrupted'):
                return previous
            if require_unpaused:
                self._require_job_unpaused(connection, job_id)
            job = previous | changes | {"updated_at": now()}
            if changes.get("error_category") == "interrupted":
                job["interrupted_phase"] = self._phase_before_interruption(previous)
            self._settle_group_jobs(job)
            if previous['status'] in ('pausing','paused') and changes.get('status')=='running':
                if 'phase' in changes:job['resume_phase']=changes['phase']
                if 'progress' in changes:job['resume_progress']=changes['progress']
                job.update(status=previous['status'],phase=previous['status'])
            connection.execute("UPDATE jobs SET data=? WHERE id=?", (encode(job), job_id))
            connection.commit()
        return job

    @staticmethod
    def _phase_before_interruption(job):
        if job["status"] in ("pausing", "paused"):
            return job.get("resume_phase", job.get("phase"))
        return job.get("phase")

    def interrupt_jobs(self):
        for project in self.list():
            with self.connect(project["id"]) as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = list(connection.execute("SELECT id,data FROM jobs"))
                for row in rows:
                    data = json.loads(row["data"])
                    if data["status"] in ACTIVE_JOB_STATUSES:
                        data.update(INTERRUPTED_JOB, updated_at=now(),
                                    interrupted_phase=self._phase_before_interruption(data))
                        self._settle_group_jobs(data)
                        connection.execute("UPDATE jobs SET data=? WHERE id=?", (encode(data), row["id"]))
                connection.commit()
