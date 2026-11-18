"""Local-only application service. AI proposes; validated revisions change on Apply."""
from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import io
import json
import hashlib
import os
from pathlib import Path
import re
import sys
import sqlite3
import threading
import time
from typing import Callable, Literal
from uuid import uuid4
import zipfile

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from credentials import CredentialError, CredentialStore, MODELS
from .documents import MAX_UPLOAD, import_document, public_document
from .geometry import build_scene, design_interior, set_parameter, validate_model
from .material_models import BoardSpec, MaterialVariant
from .materials import MaterialLibrary, assign_material, set_board_spec, set_board_specs
from .bom import build_bom, export_bom_xlsx, export_review_bom_xlsx
from .paths import filesystem_path
from .repository import INTERRUPTED_JOB, Conflict, JobInterrupted, JobPaused, NotFound, Repository, encode, is_empty_design, now

VERSION = "0.8.29"
APPLICATION = "vwc-personal-cabinet-studio"
APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
DRAWING_CHECKPOINT_LIMIT = 15 * 1024 * 1024
BOARD_SPECS_PREVIEW_SUMMARY = "Proposed board axes from modeled dimensions"


def _drawing_retry_identity(project, instruction, agent, build_id):
    from .ai import INDEX_PROMPT, MODEL_PROMPT, SourceIndex, strict_schema
    from .models import StudioModel
    from .drawing_models import DrawingPlan
    from .drawing_workflow import CLASSIFY, CHECK, NATIVE_REPAIR, DrawingReview, NativeRepairs
    if getattr(sys,"frozen",False):
        code = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    else:
        code = hashlib.sha256(b"".join(path.name.encode()+b"\0"+path.read_bytes()
            for path in sorted(Path(__file__).parent.glob("*.py")))).hexdigest()
    material = {"project_id":project["id"],"base_revision":project["revision"],
        "saved_model_sha256":hashlib.sha256(json.dumps(project["model"],sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest(),
        "documents":sorted((doc["id"],doc["sha256"],doc["page_count"]) for doc in project["documents"]),
        "instruction":instruction,"model":agent.model,"effort":agent.effort,"build_id":build_id,"code_sha256":code,
        "prompts":[INDEX_PROMPT,MODEL_PROMPT,CLASSIFY,CHECK,NATIVE_REPAIR],
        "schemas":[strict_schema(schema) for schema in (SourceIndex,StudioModel,DrawingPlan,DrawingReview,NativeRepairs)]}
    return hashlib.sha256(json.dumps(material,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class NewProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)


class RenameProject(Command):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)


class LifecycleCommand(Command):
    action: Literal["pause", "stop", "resume"]


class AnalysisCommand(Command):
    instruction: str = Field(default="", max_length=12000)


class AnalyzeCommand(AnalysisCommand):
    retry_proposal_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class AnalyzeGroupsCommand(AnalyzeCommand):
    rebuild_saved: bool = False


class GroupRetryCommand(Command):
    previous_job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}\.[a-f0-9]{32}$")


class Resume2DCommand(Command):
    previous_job_id: str = Field(pattern=r"^[a-f0-9]{32}\.[a-f0-9]{32}$")


class Rebuild2DCommand(Command):
    source_job_id: str = Field(pattern=r"^[a-f0-9]{32}\.[a-f0-9]{32}$")
    group_id: str | None = Field(default=None, pattern=r"^G_[a-f0-9]{20}$")


class GroupDraft3DCommand(AnalysisCommand):
    source_job_id: str = Field(pattern=r"^[a-f0-9]{32}\.[a-f0-9]{32}$")
    donor_source_job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}\.[a-f0-9]{32}$")
    donor_group_id: str | None = Field(default=None, pattern=r"^G_[a-f0-9]{20}$")


class GroupDraft3DSequenceCommand(AnalysisCommand):
    source_job_id: str = Field(pattern=r"^[a-f0-9]{32}\.[a-f0-9]{32}$")
    resume_job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}\.[a-f0-9]{32}$")


class CopyWorkingElevationCommand(Command):
    source_job_id: str = Field(pattern=r"^[a-f0-9]{32}\.[a-f0-9]{32}$")
    view_id: str = Field(min_length=1, max_length=160)
    donor_job_id: str = Field(pattern=r"^[a-f0-9]{32}\.[a-f0-9]{32}$")
    donor_group_id: str = Field(min_length=1, max_length=64)
    donor_view_id: str = Field(min_length=1, max_length=160)


class JobControlCommand(Command):
    action: Literal["pause", "resume", "stop"]


class ParameterCommand(Command):
    parameter_id: str = Field(max_length=100)
    value_mm: float = Field(allow_inf_nan=False)


class InteriorCommand(Command):
    cabinet_id: str
    thickness_mm: float = Field(default=18, gt=0, le=100)
    back_mm: float = Field(default=6, gt=0, le=100)
    shelves: int = Field(default=2, ge=0, le=20)
    dividers: int = Field(default=0, ge=0, le=10)
    drawers: int = Field(default=0, ge=0, le=12)
    clearance_mm: float = Field(default=3, ge=0, le=100)


class RestoreCommand(Command):
    target_revision: int = Field(ge=1)


class MaterialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    material: MaterialVariant


class MaterialCommand(Command):
    part_ids: list[str] = Field(min_length=1, max_length=1000)
    material_id: str = Field(min_length=1, max_length=120)
    expected_material_version: int = Field(ge=1)


class MaterialClearCommand(Command):
    part_ids: list[str] = Field(min_length=1, max_length=1000)

class MaterialSuggestionCommand(Command):
    instruction: str = Field(default="", max_length=4000)
    selection: str = Field(default="", max_length=160)
    replace_existing: bool = False
    mode: Literal["api", "prepared", "source"] = "api"


class BoardSpecCommand(Command):
    part_id: str = Field(min_length=1, max_length=120)
    spec: BoardSpec


class BomExportCommand(Command):
    bom_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scope_id: str | None = Field(default=None, min_length=1, max_length=160)


def create_app(data_root: Path | None = None, gateway_factory: Callable | None = None,
               on_shutdown: Callable | None = None, instance_id: str = "development",
               build_id: str = "development", on_key_setup: Callable | None = None,
               on_import_diagnostic: Callable | None = None, allow_ai: bool = True,
               reference_demo_mode: bool = False, native_drafting: bool = False,
               autonomous_2d: bool = False, github_distribution: bool = False,
               github_sample_root: Path | None = None, credential_directory: Path | None = None):
    from .reference_demo import (REFERENCE_DOCUMENT_SHA256, legacy_github_sample_document,
                                 load_github_sample, upgrade_github_sample_source)
    reference_root = Path(github_sample_root or APP_ROOT) if github_distribution else APP_ROOT
    if github_distribution:
        reference_demo_mode = True
        data_root = Path(data_root or CredentialStore().directory.parent / "CabinetStudioGitHub" / "projects")
        credential_directory = credential_directory or data_root.parent / "credentials"
        github_seed = load_github_sample(reference_root)
    else:
        github_seed = None
    store = CredentialStore(credential_directory) if credential_directory is not None else CredentialStore()
    data_root = Path(data_root or store.directory.parent / "CabinetStudio" / "projects")
    reference_document_sha256 = github_seed[0]["source_sha256"] if github_seed is not None else REFERENCE_DOCUMENT_SHA256
    repository = Repository(data_root)
    material_library = MaterialLibrary(data_root / "_materials" / "catalog.sqlite")
    material_library.seed_sample_materials()
    stopping = threading.Event()
    active_gateways = {}
    gateway_lock = threading.Lock()
    demo_lock = asyncio.Lock()
    key_settings_lock = threading.Lock()

    class StopRequested(Exception):
        pass

    @asynccontextmanager
    async def lifespan(app):
        if reference_demo_mode:
            await ensure_reference_project()
        repository.interrupt_jobs()
        yield

    app = FastAPI(title="Cabinet Studio", version=VERSION, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    app.state.repository = repository
    app.state.material_library = material_library
    app.state.ai_enabled = bool(allow_ai)
    app.state.ai_design_mode = "autonomous_2d" if autonomous_2d else "native" if native_drafting else "model"
    app.state.canonical_demo_id = None
    app.state.prepared_project_id = None

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
            from urllib.parse import urlsplit
            parsed = urlsplit(origin)
            if parsed.hostname not in ("127.0.0.1", "localhost") or parsed.netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Open this action in Cabinet Studio / 请在本应用中执行此操作"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(Conflict)
    async def conflict_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(NotFound)
    async def not_found_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        # Model/geometry validation contains only project identifiers and values.
        return JSONResponse({"detail": str(error)[:3000]}, status_code=422)

    @app.exception_handler(CredentialError)
    async def credential_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.exception_handler(OSError)
    async def storage_error(request, error):
        code = getattr(error, "winerror", None) or error.errno
        return JSONResponse({"detail": "The local project could not be read or saved. Check disk space and folder access. / 无法读取或保存本地项目，请检查磁盘空间和目录权限。",
                             "code": code}, status_code=503)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, error):
        return JSONResponse({"detail": "The project could not be saved. Reopen it and retry; earlier revisions are retained. / 无法保存项目，请重新打开后重试；此前版本已保留。"}, status_code=503)

    def reviewed_source(project):
        for document in project["documents"]:
            if (document.get("sha256") != reference_document_sha256
                    or document.get("media_type") != "application/pdf" or document.get("page_count") != 3):
                continue
            path = filesystem_path(document["local_path"])
            if not path.is_relative_to(repository.directory(project["id"])):
                continue
            try:
                with path.open("rb") as source:
                    if hashlib.file_digest(source, "sha256").hexdigest() == reference_document_sha256:
                        return document
            except OSError:
                continue
        return None

    def workflow_summary(project, empty):
        scene = None if empty else build_scene(project["model"], project["id"], project["revision"])
        report = build_bom(project["model"], project["id"], project["revision"])
        reviewed_drawings = sum(view.get("status") == "ready" and view.get("review_status") == "passed"
                                for view in (scene or {}).get("drawing_quality", {}).get("views", []))
        if project.get("reference_source_key") == "west15-reviewed-v1":
            from .reference_demo import load_manifest
            manifest, _, _ = load_manifest(reference_root)
            reviewed_drawings = sum(len(section["views"]) for section in manifest["sections"])
        return {"source_documents": len(project["documents"]),
                "source_pages": sum(document["page_count"] for document in project["documents"]),
                "reviewed_drawings": reviewed_drawings, "model_objects": len(scene["objects"]) if scene else 0,
                "model_meshes": len(scene["meshes"]) if scene else 0, "bom_status": report["status"],
                "bom_rows": len(report["rows"]), "bom_boards": sum(row["quantity"] for row in report["rows"]),
                "bom_missing_material": any("missing_material" in row["reason_codes"] for row in report["blocked"]),
                "bom_blocked_panels": len(report["blocked"]),
                "revision": project["revision"]}

    def available_group_retries(project, job):
        from .grouped_2d import group_retry_options
        if (not allow_ai or not autonomous_2d or project.get("lifecycle") != "active"
                or project.get("pending_proposal") or project.get("active_job")
                or not job or not job.get("grouped_2d") or job["base_revision"] != project["revision"]):
            return {}
        return group_retry_options(repository.grouped_2d_plan_path(project["id"]), project["id"], project["documents"], job)

    def available_group_rebuilds(project, job):
        from .grouped_2d import group_rebuild_options
        if (not allow_ai or not autonomous_2d or project.get("lifecycle") != "active"
                or project.get("pending_proposal") or project.get("active_job")
                or not job or not job.get("grouped_2d") or job["base_revision"] != project["revision"]):
            return {}
        return group_rebuild_options(repository.grouped_2d_plan_path(project["id"]), project["id"], project["documents"], job)

    def available_group_recovery(project, job):
        # None means unavailable. An empty list means discovery can resume
        # before a group plan or any drawing-cycle allowance was committed.
        from .grouped_2d import group_recovery_options, is_group_interruption
        if (not allow_ai or not autonomous_2d or project.get("lifecycle") != "active"
                or project.get("pending_proposal") or project.get("active_job")
                or not job or not job.get("grouped_2d") or job["base_revision"] != project["revision"]
                or not is_group_interruption(job)):
            return None
        from .api_drawing_workflow import _source_identity
        documents = project["documents"]
        if not documents or any(document["media_type"] != "application/pdf" for document in documents):
            return None
        try:
            source_identity = _source_identity(documents)
        except (OSError, KeyError, TypeError, ValueError):
            return None
        if job.get("source_set_sha256", source_identity) != source_identity:
            return None
        plan_path = repository.grouped_2d_plan_path(project["id"])
        if plan_path.exists():
            return group_recovery_options(plan_path, project["id"], documents, job) or None
        if (job.get("source_set_sha256") == source_identity
                and isinstance(job.get("group_instruction"), str) and len(job["group_instruction"]) <= 8000
                and job.get("interrupted_phase") in ("queued", "resuming_2d", "reading_sources", "mapping_drawing_groups")
                and not (plan_path.parent / "group-cycles").exists()
                and (job.get("rebuild_saved_groups") or not repository.drawing_cycle_ledger_path(project["id"]).exists())):
            return []
        return None

    def public_job(job):
        from .working_results import source_group_links, working_result
        if "group_review_inputs" in job:
            job = {key: value for key, value in job.items() if key != "group_review_inputs"}
        if "groups_2d" in job:
            retries = {}
            rebuilds = {}
            can_resume = False
            can_draft = False
            if job["status"] in ("ready", "needs_review", "failed", "cancelled"):
                latest = repository.latest_job(job["project_id"], grouped_2d=True)
                if latest and latest["id"] == job["id"]:
                    project = repository.get(job["project_id"])
                    can_resume = available_group_recovery(project, latest) is not None
                    if not can_resume:
                        retries = available_group_retries(project, latest)
                    rebuilds = available_group_rebuilds(project, latest)
                    can_draft = bool(allow_ai and autonomous_2d and project["lifecycle"] == "active"
                                     and not project["active_job"] and not project["pending_proposal"])
            groups = source_group_links(job)
            for row in groups:
                option = retries.get(row["id"])
                row["can_retry"] = option is not None
                row["can_rebuild"] = row["id"] in rebuilds
                row["can_generate_3d_draft"] = bool(can_draft and row["status"] in ("ready", "needs_review")
                    and row.get("cycle_count") in (1, 2) and row.get("view_ids") and row.get("source_evidence_url"))
                if option:
                    row["cycles_remaining"] = option[1]
            job = {key: value for key, value in job.items() if key != "group_instruction"}
            job.update(groups_2d=groups, can_resume_2d=can_resume, can_rebuild_2d=bool(rebuilds))
        if job.get("draft_3d_group_id"):
            from .group_3d_draft import draft_receipt
            job = {key: value for key, value in job.items()
                   if key not in ("draft_3d_source_pin", "draft_3d_donor_pin", "workflow_3d")}
            receipt = draft_receipt(repository, job)
            if receipt:
                job["workflow_3d"] = {key: value for key, value in receipt.items() if key != "artifacts"}
                if receipt.get("preview_model"):
                    job["draft_3d_scene_url"] = f'/api/studio/jobs/{job["id"]}/draft-3d/scene'
        if job.get("draft_3d_sequence"):
            job = {key: value for key, value in job.items()
                   if key not in ("draft_3d_sequence_pins", "draft_3d_sequence_instruction", "draft_3d_resume_from")}
        result, _ = working_result(repository, job)
        return job | {"working_result": result}

    def conversion_ledger(project_id, rebuild_attempt=None):
        path = repository.drawing_cycle_ledger_path(project_id)
        if rebuild_attempt is None:
            return path
        if not re.fullmatch(r"[a-f0-9]{32}", rebuild_attempt):
            raise ValueError("Invalid 2D rebuild attempt.")
        return path.parent / "source-rebuild-cycles" / f"{rebuild_attempt}.json"

    def require_conversion_budget(project, rebuild_attempt=None):
        from .autonomous_2d import _existing_scope
        try:
            _, ledger = _existing_scope(conversion_ledger(project["id"], rebuild_attempt), project["id"], project["documents"])
            if ledger and not ledger.snapshot()["can_start_drawing"] and not ledger.is_legacy_source_fallback():
                raise Conflict("This source conversion has no drawing cycles remaining or still needs its current check. Review the existing result; your saved project is unchanged. / 此次源图转换已无剩余绘图次数，或仍需完成当前检查。请查看现有结果，已保存项目保持不变。")
        except Conflict:
            raise
        except (OSError, KeyError, TypeError, ValueError):
            raise Conflict("The saved 2D conversion record needs review; it cannot be reset by starting again. / 已保存的二维转换记录需要复核，重新开始不能重置记录。") from None

    def can_discover_groups(project):
        plan_path = repository.grouped_2d_plan_path(project["id"])
        return bool(autonomous_2d and project["documents"]
                    and all(document["media_type"] == "application/pdf" for document in project["documents"])
                    and project.get("lifecycle") == "active" and not project.get("pending_proposal")
                    and not project.get("active_job")
                    and not plan_path.exists() and not (plan_path.parent / "group-cycles").exists()
                    and available_group_recovery(project, repository.latest_job(project["id"], grouped_2d=True)) is None)

    def can_analyze_groups(project, *, empty):
        return (allow_ai and empty and not repository.drawing_cycle_ledger_path(project["id"]).exists()
                and can_discover_groups(project))

    def can_rebuild_2d_from_originals(project, *, empty):
        # Structural capability also identifies the action in offline builds.
        # Starting it still requires the assistant and an active workspace.
        if empty or not can_discover_groups(project):
            return False
        latest = repository.latest_job(project["id"], grouped_2d=True)
        if latest and latest.get("groups_2d"):
            return False
        try:
            check_owned_3d_sources(project)
        except (OSError, ValueError):
            return False
        return True

    def grouped_3d_design_readiness(project, source_job, jobs, *, saved=False, eligible=True, require_checks=False):
        rows = (source_job or {}).get("groups_2d", [])
        current = bool(rows and (saved or source_job["base_revision"] == project["revision"]))
        usable = {row["id"] for row in rows if current and row.get("status") in ("ready", "needs_review") and row.get("view_ids")}
        checked = {row["id"] for row in rows if row["id"] in usable and row.get("status") == "ready"
                   and row.get("accepted") is True and row.get("view_ids")}
        drafts = {}
        for job in jobs:
            ident = job.get("draft_3d_group_id")
            receipt = job.get("workflow_3d") or {}
            if (ident in usable and ident not in drafts and job.get("base_revision") == source_job["base_revision"]
                    and job.get("draft_3d_source_job_id") == source_job["id"]
                    and job.get("status") in ("ready", "needs_review") and receipt.get("preview_model")
                    and receipt.get("status") in ("draft_ready", "draft_needs_review")):
                drafts[ident] = job
        passed_drafts = {ident: job for ident, job in drafts.items()
                         if job["workflow_3d"]["status"] == "draft_ready"}
        state = {"status": "unavailable", "group_count": len(rows),
                 "checked_2d_count": len(checked), "checked_3d_count": len(passed_drafts)}
        if require_checks:
            drafts = {ident: job for ident, job in passed_drafts.items() if ident in checked
                      and job.get("draft_3d_source_checked") is True and not job.get("draft_3d_donor_job_id")}
        if saved:
            state["status"] = "saved"
        elif eligible and require_checks and rows and len(checked) != len(rows):
            state.update(status="needs_2d_review", blocking_group_id=next(row["id"] for row in rows if row["id"] not in checked))
        elif eligible and rows and len(drafts) != len(rows):
            state.update(status="needs_3d_review" if require_checks else "needs_3d_draft",
                         blocking_group_id=next(row["id"] for row in rows if row["id"] not in drafts))
        elif eligible and rows:
            state["status"] = "ready"
        return state, drafts

    def public(project):
        empty = is_empty_design(project["model"])
        workflow_2d = None
        workflow_3d = None
        # Reopening a preview must retain its check result, not just its pictures.
        with repository.connect(project["id"]) as connection:
            jobs = [json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs")]
        pending_id = (project.get("pending_proposal") or {}).get("id")
        jobs.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        latest = next((job for job in jobs if job.get("kind") != "group_review_3d"), None)
        grouped = next((job for job in jobs if job.get("grouped_2d")), None)
        last_job = public_job({key:value for key,value in latest.items() if key in (
            "id","project_id","base_revision","kind","status","phase","progress","proposal_id",
            "error","error_category","created_at","updated_at","resume_phase","resume_progress","interrupted_phase",
            "grouped_2d","groups_2d","draft_3d_group_id","draft_3d_group_label",
            "draft_3d_source_job_id","draft_3d_source_checked","draft_3d_donor_project_id","draft_3d_donor_project_name",
            "draft_3d_donor_job_id","draft_3d_donor_group_id","draft_3d_donor_group_label",
            "draft_3d_donor_source_evidence_url","draft_3d_sequence","draft_3d_current_group_id",
            "draft_3d_group_progress","material_suggestions","editable_design_revision","editable_design_error")}) if latest else None
        grouped_2d_job = last_job if grouped is latest else public_job(grouped) if grouped else None
        grouped_3d_jobs = {}
        for job in jobs:
            group_id = job.get("draft_3d_group_id")
            if group_id and not grouped_3d_jobs.get(group_id, {}).get("draft_3d_scene_url"):
                entry = last_job if job is latest else public_job(job)
                if group_id not in grouped_3d_jobs or entry.get("draft_3d_scene_url"):
                    grouped_3d_jobs[group_id] = entry
        for job in jobs:
            if not job.get("workflow_3d") or not job.get("proposal_id"):
                continue
            if job["proposal_id"] == pending_id:
                workflow_3d = job["workflow_3d"]
                break
            if not pending_id and job["base_revision"] == project["revision"] - 1:
                prior = repository.get_proposal(project["id"], job["proposal_id"])
                if prior["status"] == "applied":
                    workflow_3d = job["workflow_3d"]
                    break
        for job in jobs:
            if not job.get("workflow_2d") or not job.get("proposal_id"):
                continue
            if job["proposal_id"] == pending_id:
                workflow_2d = job["workflow_2d"]
                break
            if not pending_id and job["base_revision"] == project["revision"] - 1:
                prior = repository.get_proposal(project["id"], job["proposal_id"])
                if prior["status"] == "applied":
                    workflow_2d = job["workflow_2d"]
                    break
        if workflow_2d and workflow_2d.get("source_set_sha256"):
            from .api_drawing_workflow import content_hash
            source_identity = content_hash([{"id": doc["id"], "sha256": doc["sha256"], "page_count": doc["page_count"]} for doc in project["documents"]])
            if source_identity != workflow_2d["source_set_sha256"]:
                workflow_2d = None
        can_retry_2d = False
        if allow_ai and autonomous_2d and pending_id and workflow_2d and project.get("can_retry_2d") and project.get("lifecycle") == "active":
            try:
                owner = next((job for job in jobs if job.get("proposal_id") == pending_id), {})
                require_conversion_budget(project, owner.get("rebuild_2d_attempt"))
                can_retry_2d = True
            except Conflict:
                pass
        summary = workflow_summary(project, empty)
        grouped_design, _ = grouped_3d_design_readiness(project, grouped, jobs, saved=summary["model_meshes"] > 0, eligible=empty)
        return project | {"documents": [public_document(project["id"], doc) for doc in project["documents"]],
                          "workflow_2d": workflow_2d,
                          "workflow_3d": workflow_3d,
                          "last_job": last_job,
                          "grouped_2d_job": grouped_2d_job,
                          "grouped_3d_jobs": grouped_3d_jobs,
                          "grouped_3d_design_status": grouped_design,
                          "active_job": public_job(project["active_job"]) if project.get("active_job") else None,
                          "can_retry_2d": can_retry_2d,
                          "can_analyze_groups": can_analyze_groups(project, empty=empty),
                          "can_rebuild_2d_from_originals": can_rebuild_2d_from_originals(project, empty=empty),
                          "three_d_source_status": three_d_source_status(project),
                          "reference_demo": project.get("is_demo", False) and project.get("demo_key") == "fde-reference-demo",
                          "reference_project": project.get("reference_source_key") == "west15-reviewed-v1",
                          "reviewed_design_available": bool(empty and not project.get("reference_source_key")
                              and project.get("lifecycle") == "active" and not project.get("active_job")
                              and not project.get("pending_proposal") and reviewed_source(project)),
                          "workflow_summary": summary}

    def existing_prepared_project():
        project_id = app.state.prepared_project_id
        if not project_id:
            return None
        try:
            item = repository.get(project_id)
        except NotFound:
            app.state.prepared_project_id = None
            app.state.canonical_demo_id = None
            return None
        return item if item.get("reference_source_key") == "west15-reviewed-v1" else None

    def current(project_id, expected_revision, *, writable=True):
        project = repository.get(project_id)
        if project["revision"] != expected_revision:
            raise Conflict("Project changed; reload the current revision / 项目已更改，请重新加载当前版本")
        if writable:
            repository.require_active(project_id)
        return project

    def close_project_gateways(project_id):
        with gateway_lock:
            agents = [(job_id, agent) for job_id, agent in active_gateways.items() if job_id.startswith(project_id + ".")]
        for job_id, agent in agents:
            # A concurrent explicit Resume may already have started a new job.
            # Close only workers invalidated by this lifecycle transaction.
            if repository.get_job(job_id)["status"] != "cancelled":
                continue
            client = getattr(agent, "client", None)
            if client is not None and callable(getattr(client, "close", None)):
                try:
                    client.close()
                except Exception:
                    pass

    def validate_drawing_sources(model, documents, *, project_id=None, verify_files=False):
        canonical = validate_model(model)
        sources = {doc["id"]: doc for doc in documents}
        checked = set()
        for drawing in canonical.drawings:
            document = sources.get(drawing.document_id)
            if document is None or drawing.page > document["page_count"]:
                raise ValueError("Drawing refers to a missing source page / 图纸引用了缺失的原图页面")
            if drawing.source_sha256 != document["sha256"]:
                raise ValueError("Drawing source hash does not match / 图纸与原图校验值不匹配")
            if verify_files and drawing.document_id not in checked:
                path = filesystem_path(document["local_path"])
                if project_id is None or not path.is_relative_to(repository.directory(project_id)):
                    raise ValueError("Invalid drawing source path / 图纸原图路径无效")
                with path.open("rb") as source:
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                if digest != drawing.source_sha256:
                    raise ValueError("Drawing source file changed; re-import the original / 图纸原图文件已变化，请重新导入原图")
                checked.add(drawing.document_id)
        return canonical

    def drawing_set_ready(scene):
        quality = scene.get("drawing_quality")
        return bool(quality and quality.get("status") == "ready"
                    and all(view.get("status") == "ready" for view in quality.get("views", [])))

    def has_original_3d_pdf(item):
        return any(document.get("media_type") == "application/pdf"
                   or str(document.get("local_path", "")).lower().endswith(".pdf")
                   for document in item["documents"])

    def check_owned_3d_sources(item):
        root = repository.directory(item["id"])
        for document in item["documents"]:
            path = filesystem_path(document["local_path"])
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError("The original source is unavailable. Re-import it before creating 3D.")

    def three_d_source_status(item):
        """Advertise 3D readiness without reading original file contents on project open."""
        from .generate_3d import _checked_source
        if not has_original_3d_pdf(item):
            return "missing_original_pdf"
        try:
            check_owned_3d_sources(item)
        except (OSError, ValueError):
            return "source_unavailable"
        if not item["model"].get("drawings") and item.get("reference_source_key"):
            return "prepared_needs_checked_2d"
        try:
            _checked_source(item["model"], item["documents"], verify_files=False)
        except ValueError:
            return "missing_checked_2d"
        return "ready"

    def validate_3d_input(item):
        """An explicit 3D action consumes saved, current 2D and owned PDF bytes."""
        from .generate_3d import bind_source_2d
        if not has_original_3d_pdf(item):
            raise ValueError("Upload the original customer PDF before creating 3D.")
        check_owned_3d_sources(item)
        canonical = validate_drawing_sources(item["model"], item["documents"])
        if not canonical.drawings and item.get("reference_source_key"):
            raise ValueError("The reviewed sheets are display copies. Build, review and save the project's 2D drawings in Step 2 before rebuilding 3D.")
        bind_source_2d(canonical, item["documents"])
        return canonical

    def verified_group_3d_input(item, source_job, group_id, donor_job_id, donor_group_id):
        from .group_3d_draft import group_draft_source, verify_group_draft_match

        destination = group_draft_source(repository, item, source_job, group_id)
        if not donor_job_id:
            return destination, destination, item
        donor_project = repository.get(donor_job_id.split(".", 1)[0])
        donor_job = repository.get_job(donor_job_id)
        baseline = group_draft_source(repository, donor_project, donor_job, donor_group_id)
        verify_group_draft_match(destination, item["documents"], baseline, donor_project["documents"])
        return destination, baseline, donor_project

    def proposal_can_apply(scene):
        quality = scene.get("drawing_quality", {})
        return drawing_set_ready(scene) or bool(quality.get("model_preview") and quality.get("can_apply"))

    def gateway():
        if gateway_factory is not None:
            return gateway_factory()
        from .ai import StudioAIGateway
        key = store.load_key()
        if not key:
            raise CredentialError("Save an API key in Key Setup first / 请先通过密钥工具保存 API 密钥")
        settings = store.load_settings()
        return StudioAIGateway(key, model=settings["model"], effort=settings["reasoning"],
                               enable_drafting=bool(native_drafting))

    @app.get("/api/studio/health")
    def health():
        import hashlib
        prepared = existing_prepared_project()
        return {"application": APPLICATION, "version": VERSION, "instance_id": instance_id,
                "build_id": build_id, "project_store": hashlib.sha256(str(repository.root).encode()).hexdigest(),
                "prepared_demo": not github_distribution and any(path.is_file() for path in (APP_ROOT / "demo" / "A202-Vanity-Pilot.vwc", APP_ROOT / "examples" / "A202-Vanity-Pilot.vwc")),
                "reviewed_demo": not github_distribution and any(path.is_file() for path in (APP_ROOT / "demo" / "A200-A202-Reviewed.vwc", APP_ROOT / "examples" / "A200-A202-Reviewed.vwc")),
                "showcase_demo": not github_distribution and (APP_ROOT / "showcase" / "showcase.json").is_file(),
                "github_distribution": github_distribution,
                "reference_demo_mode": bool(reference_demo_mode),
                "reference_project_mode": bool(reference_demo_mode),
                "canonical_demo_id": prepared["id"] if prepared else None,
                "prepared_project_id": prepared["id"] if prepared else None,
                "ai_enabled": bool(allow_ai),
                "grouped_2d": bool(allow_ai and autonomous_2d),
                "ai_design_mode": app.state.ai_design_mode,
                "key_available": store.has_key(), **store.load_settings()}

    def key_settings_status():
        # Existing secrets stay encrypted. Settings never need to unlock them.
        return {"key_available": store.has_key(), **store.load_settings(), "models": list(MODELS)}

    def private_settings_response(payload):
        return JSONResponse(payload, headers={"Cache-Control": "no-store", "Pragma": "no-cache",
                                              "X-Content-Type-Options": "nosniff"})

    @app.get("/api/studio/key-settings")
    def key_settings():
        return private_settings_response(key_settings_status())

    @app.post("/api/studio/key-settings")
    async def save_key_settings(request: Request):
        # Parse this endpoint explicitly: ordinary request-validation responses
        # may echo an invalid input field, which must never happen for a key.
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > 16 * 1024:
                raise HTTPException(413, "The settings input is too large. Paste one API key only.")
            content.extend(chunk)
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeError, RecursionError):
            raise HTTPException(422, "Use a valid settings request.") from None
        if not isinstance(payload, dict) or set(payload) - {"model", "api_key"}:
            raise HTTPException(422, "Use the model and optional new-key fields only.")
        model = payload.get("model")
        if not isinstance(model, str) or model not in MODELS:
            raise HTTPException(422, "Choose Terra High, Sol High or Astra High.")
        key = payload.get("api_key")
        if key is not None and not isinstance(key, str):
            raise HTTPException(422, "Paste the new API key as text, or leave it blank to keep the saved key.")
        typed = key.strip() if key is not None else ""
        if typed and (len(typed) < 20 or len(typed) > 4096 or any(value.isspace() for value in typed)):
            raise HTTPException(422, "Enter a complete API key without spaces, or leave the field blank to keep the saved key.")
        with key_settings_lock:
            if typed:
                store.save_key(typed)
            try:
                store.save_settings(model, "high")
            except CredentialError:
                if typed:
                    raise CredentialError("Your new key was saved locally, but the model setting could not be saved. Reopen settings and try again.") from None
                raise
            return private_settings_response({**key_settings_status(), "saved": True})

    @app.get("/api/studio/projects")
    def projects():
        return [item | {"reference_demo": item.get("is_demo", False) and item.get("demo_key") == "fde-reference-demo",
                        "reference_project": item.get("reference_source_key") == "west15-reviewed-v1"}
                for item in repository.list()]

    @app.post("/api/studio/projects")
    def new_project(command: NewProject):
        return public(repository.create(command.name))

    @app.get("/api/studio/projects/{project_id}")
    def project(project_id: str):
        return public(repository.get(project_id))

    @app.patch("/api/studio/projects/{project_id}/name")
    def rename_project(project_id: str, command: RenameProject):
        return public(repository.rename(project_id, command.name, command.expected_revision))

    @app.post("/api/studio/projects/{project_id}/lifecycle")
    def lifecycle(project_id: str, command: LifecycleCommand):
        item = repository.set_lifecycle(project_id, command.action, command.expected_revision)
        if command.action != "resume":
            close_project_gateways(project_id)
        return public(item)

    @app.delete("/api/studio/projects/{project_id}")
    def delete_project(project_id: str, expected_revision: int = Query(ge=1)):
        result = repository.delete(project_id, expected_revision)
        close_project_gateways(project_id)
        return result

    @app.get("/api/studio/projects/{project_id}/scene")
    def scene(project_id: str):
        item = repository.get(project_id)
        return build_scene(item["model"], project_id, item["revision"])

    @app.post("/api/studio/projects/{project_id}/documents")
    async def upload_document(project_id: str, file: UploadFile = File(...)):
        repository.require_active(project_id)
        if repository.get(project_id).get("active_job"):
            raise Conflict("Wait for the current analysis before importing more sources / 请等待当前分析完成后再导入原图")
        content = await file.read(MAX_UPLOAD + 1)
        document_id, cache = None, None
        from .reference_demo import REFERENCE_DOCUMENT_SHA256
        if not github_distribution and hashlib.sha256(content).hexdigest() == REFERENCE_DOCUMENT_SHA256:
            # Only this exact known PDF can reuse the server's hashed previews.
            # The PDF reader still checks actual page count and dimensions.
            document_id = "DOC_" + uuid4().hex
            try:
                manifest, root, _ = showcase_manifest()
                bundled = prepared_showcase_cache(root, manifest["archive"])
                records = [record for record in bundled["documents"]
                           if record.get("source_sha256") == REFERENCE_DOCUMENT_SHA256] if bundled else []
                if len(records) == 1:
                    cache = {**bundled, "documents": [{**records[0], "document_id": document_id}]}
            except (HTTPException, OSError, ValueError, TypeError, KeyError):
                pass  # An unavailable optional cache uses the ordinary reader.
        try:
            document = import_document(repository, project_id, file.filename or "source.pdf", content, document_id,
                                       prepared_cache=cache)
        except (ValueError, OSError):
            raise
        except Exception:
            raise HTTPException(422, "The source could not be read; saved design retained / 无法读取原图，已保存设计保留") from None
        return public(repository.get(project_id)) | {"imported_document_id": document["id"]}

    @app.post("/api/studio/projects/{project_id}/prepare-design")
    def prepare_design(project_id: str, command: Command):
        """Import the shipped approved results only for their exact original PDF."""
        from pypdf import PdfReader
        from .reference_demo import REFERENCE_SOURCE_KEY
        item = current(project_id, command.expected_revision)
        if item.get("reference_source_key") or not is_empty_design(item["model"]):
            raise Conflict("Approved results can only be imported into an empty project; saved work is retained")
        document = reviewed_source(item)
        if document is None:
            raise ValueError("Approved results are available only for the matching original A200 + A202 PDF")
        original = filesystem_path(document["local_path"]).read_bytes()
        reader = PdfReader(io.BytesIO(original))
        if reader.is_encrypted or len(reader.pages) != 3:
            raise ValueError("The attached original PDF does not match the approved source pages")
        path, catalog, _ = reference_seed_assets()
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > 100 or sum(asset.file_size for asset in archive.infolist()) > 200 * 1024 * 1024:
                raise ValueError("The bundled approved results are invalid")
            payload = json.loads(archive.read("project.json"))
            if payload.get("schema") != "vwc-studio-project/1" or len(payload.get("documents", [])) != 1:
                raise ValueError("The bundled approved results are invalid")
            source = payload["documents"][0]
            if (source.get("sha256") != reference_document_sha256
                    or hashlib.sha256(archive.read(source["asset"])).hexdigest() != reference_document_sha256):
                raise ValueError("The bundled approved results do not match the attached original PDF")
            history = payload.get("history", [])
            if not history:
                raise ValueError("The bundled approved design is missing")
            candidate = json.loads(history[-1]["model"])
        def relink(value):
            if isinstance(value, dict):
                return {key: document["id"] if key == "document_id" and child == source["id"] else relink(child)
                        for key, child in value.items()}
            if isinstance(value, list):return [relink(child) for child in value]
            return value
        candidate = relink(candidate)
        candidate["name"] = item["name"]
        canonical = validate_drawing_sources(candidate, item["documents"], project_id=project_id, verify_files=True)
        counts = {source["id"]: source["page_count"] for source in item["documents"]}
        references = [reference for parameter in canonical.parameters for reference in parameter.evidence]
        references.extend(reference for relation in canonical.relationships for reference in relation.evidence)
        stack = [canonical.root]
        while stack:
            part = stack.pop()
            references.extend(part.evidence)
            references.extend(reference for symbol in part.symbols for reference in symbol.evidence)
            stack.extend(part.children)
        if any(reference.document_id not in counts or reference.page > counts[reference.document_id]
               for reference in [*references, *canonical.views]):
            raise ValueError("Approved results refer to a missing attached source page")
        build_scene(canonical, project_id, command.expected_revision + 1)
        material_library.seed_prepared_materials(catalog)
        result = repository.install_reviewed_design(project_id, command.expected_revision, canonical, document, REFERENCE_SOURCE_KEY)
        return public(result)

    @app.get("/api/studio/projects/{project_id}/documents/{document_id}/pages/{number}")
    def preview_page(project_id: str, document_id: str, number: int):
        item = repository.get(project_id)
        document = next((d for d in item["documents"] if d["id"] == document_id), None)
        if document is None or not 1 <= number <= document["page_count"]:
            raise NotFound("Source page not found / 未找到原图页")
        path = filesystem_path(Path(document["local_path"]).parent / f"page-{number}.png")
        if not path.is_relative_to(repository.directory(project_id)):
            raise NotFound("Invalid source page / 原图页无效")
        return FileResponse(path, media_type="image/png")

    @app.post("/api/studio/demo")
    async def demo():
        if reference_demo_mode:
            return await reference_project()
        source = APP_ROOT / "demo" / "sources" / "Original-customer-design_A200+A202.pdf"
        if not source.is_file():
            raise HTTPException(503, "Demo source is missing / 缺少演示原图")
        async with demo_lock:
            existing = repository.find_demo("original-customer-source-v1")
            if existing:
                return public(existing)
            item = repository.create("A200 + A202 · Customer demo")
            import_document(repository, item["id"], source.name, source.read_bytes())
            return public(repository.protect_demo(item["id"], "original-customer-source-v1"))

    async def open_builtin_archive(path, demo_key, *, prepared_cache=None):
        async with demo_lock:
            existing = repository.find_demo(demo_key)
            if existing:
                return public(existing)
            item = await _import_project(UploadFile(file=io.BytesIO(path.read_bytes()), filename=path.name),
                                         prepared_cache=prepared_cache)
            return public(repository.protect_demo(item["id"], demo_key))

    @app.post("/api/studio/prepared-demo")
    async def prepared_demo():
        if reference_demo_mode:
            return await reference_project()
        candidates = [APP_ROOT / "demo" / "A202-Vanity-Pilot.vwc", APP_ROOT / "examples" / "A202-Vanity-Pilot.vwc"]
        path = next((value for value in candidates if value.is_file()), None)
        if path is None:
            raise HTTPException(503, "Prepared example is not included in this build / 此构建未包含已准备的演示")
        return await open_builtin_archive(path, "prepared-vanity-pilot-v1")

    @app.post("/api/studio/reviewed-demo")
    async def reviewed_demo():
        if reference_demo_mode:
            return await reference_project()
        candidates = [APP_ROOT / "demo" / "A200-A202-Reviewed.vwc", APP_ROOT / "examples" / "A200-A202-Reviewed.vwc"]
        path = next((value for value in candidates if value.is_file()), None)
        if path is None:
            raise HTTPException(503, "Reviewed drawing example is not included in this build / 此构建未包含已审查图纸演示")
        return await open_builtin_archive(path, "reviewed-a200-a202-v3")

    def showcase_manifest():
        if github_distribution:
            raise NotFound("Additional showcase projects are unavailable in this edition")
        root = (APP_ROOT / "showcase").resolve()
        path = root / "showcase.json"
        if not path.is_file():
            raise HTTPException(503, "The prepared interview showcase is not included in this build")
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("The bundled showcase manifest is too large")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if payload.get("schema") != "vwc-interview-showcase/1":
            raise ValueError("Unsupported showcase manifest")
        def text(key, maximum=2000, default=""):
            value = payload.get(key, default)
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError("Invalid showcase description")
            return value
        def asset(value, extensions):
            if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,150}", value)
                    or Path(value).suffix.lower() not in extensions):
                raise ValueError("Invalid showcase asset name")
            target = (root / value).resolve()
            if target.parent != root or not target.is_file():
                raise ValueError("A bundled showcase asset is missing")
            return value
        archive = asset(payload.get("archive"), {".vwc"})
        pdf = asset(payload.get("reviewed_pdf"), {".pdf"})
        assets = {archive, pdf}
        def quarter_turn(value):
            if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 90, 180, 270):
                raise ValueError("Invalid showcase image rotation")
            return value
        public_manifest = {"schema": payload["schema"], "id": text("id", 160),
            "title": text("title", 200), "description": text("description"),
            "default_selection": text("default_selection", 160), "prepared": True, "api_required": False,
            "archive": archive, "reviewed_pdf": pdf, "hero_rotation": quarter_turn(payload.get("hero_rotation", 0)),
            "archive_url": "/api/studio/showcase/assets/" + archive,
            "reviewed_pdf_url": "/api/studio/showcase/assets/" + pdf}
        if payload.get("hero_image") is not None:
            hero = asset(payload["hero_image"], {".png", ".jpg", ".jpeg", ".webp"})
            assets.add(hero)
            public_manifest.update(hero_image=hero, hero_image_url="/api/studio/showcase/assets/" + hero)
        for key in ("sheets", "textures", "reference_photos"):
            values = payload.get(key, [])
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError("Invalid showcase gallery")
            result = []
            for item in values:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("title"), str):
                    raise ValueError("Invalid showcase gallery item")
                image = asset(item.get("image"), {".png", ".jpg", ".jpeg", ".webp"})
                assets.add(image)
                record = {"id": item["id"][:160], "title": item["title"][:200], "image": image,
                          "image_url": "/api/studio/showcase/assets/" + image}
                if "rotation" in item:
                    record["rotation"] = quarter_turn(item["rotation"])
                for name in ("material_codes", "material_ids"):
                    if name in item:
                        if not isinstance(item[name], list) or any(not isinstance(value, str) or len(value) > 160 for value in item[name]):
                            raise ValueError("Invalid showcase material mapping")
                        record[name] = item[name]
                for name in ("roughness", "metalness"):
                    if name in item:
                        value = item[name]
                        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                            raise ValueError("Invalid showcase material appearance")
                        record[name] = value
                if "pattern" in item:
                    if not isinstance(item["pattern"], str) or len(item["pattern"]) > 160:
                        raise ValueError("Invalid showcase material pattern")
                    record["pattern"] = item["pattern"]
                result.append(record)
            public_manifest[key] = result
        variants = payload.get("material_catalog", [])
        if not isinstance(variants, list) or len(variants) > 100:
            raise ValueError("Invalid showcase materials")
        public_manifest["material_catalog"] = [MaterialVariant.model_validate(value).model_dump(mode="json") for value in variants]
        return public_manifest, root, assets

    @app.get("/api/studio/showcase")
    def showcase():
        manifest, _, _ = showcase_manifest()
        return manifest

    @app.get("/api/studio/showcase/assets/{asset_name}")
    def showcase_asset(asset_name: str):
        _, root, assets = showcase_manifest()
        if asset_name not in assets:
            raise NotFound("Showcase asset not found")
        return FileResponse(root / asset_name,
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})

    @app.post("/api/studio/projects/showcase")
    async def open_showcase():
        if reference_demo_mode:
            return await reference_project()
        manifest, root, _ = showcase_manifest()
        material_library.seed_prepared_materials(manifest["material_catalog"])
        return await open_builtin_archive(root / manifest["archive"], manifest["id"],
                                           prepared_cache=prepared_showcase_cache(root, manifest["archive"]))

    def reference_seed_assets():
        if github_seed is not None:
            manifest, path = github_seed
            return path, manifest["material_catalog"], None
        manifest, root, _ = showcase_manifest()
        archive = manifest["archive"]
        return root / archive, manifest["material_catalog"], prepared_showcase_cache(root, archive)

    async def ensure_reference_project():
        from .reference_demo import OrdinaryReferenceProfile, REFERENCE_SOURCE_KEY, REFERENCE_PROJECT_NAME, load_manifest
        async with demo_lock:
            manifest, _, _ = load_manifest(reference_root)
            with OrdinaryReferenceProfile(repository, manifest["generation"]) as profile:
                record = profile.plan()
                project_id = record.get("project_id")
                item = profile.existing(project_id)
                if record["status"] == "seed-pending":
                    # A deleted reserved project is never recreated. An absent
                    # target, however, resumes an interrupted unpublished seed.
                    if item is None and not repository.directory(project_id).exists():
                        path, catalog, cache = reference_seed_assets()
                        material_library.seed_prepared_materials(catalog)
                        item = await _import_project(UploadFile(file=io.BytesIO(path.read_bytes()), filename=path.name),
                            prepared_cache=cache, project_id=project_id)
                if item is not None:
                    if github_seed is not None:
                        item = upgrade_github_sample_source(repository, item, github_seed)
                    item = repository.attach_reference_source(item["id"], REFERENCE_SOURCE_KEY, REFERENCE_PROJECT_NAME)
                profile.complete(project_id)
                # The current normal-project policy supersedes old built-in
                # protection without deleting or renaming any other project.
                for previous in repository.list():
                    if previous.get("is_demo") or previous.get("demo_key") is not None:
                        repository.make_ordinary(previous["id"])
                app.state.prepared_project_id = item["id"] if item else None
                app.state.canonical_demo_id = app.state.prepared_project_id
                return item

    @app.post("/api/studio/projects/prepared")
    @app.post("/api/studio/projects/reference-demo")
    async def reference_project():
        if not reference_demo_mode:
            raise NotFound("The prepared project is unavailable in this workspace")
        item = existing_prepared_project()
        if item is None:
            raise NotFound("This project has been removed. Create a new project to continue.")
        return public(item)

    @app.get("/api/studio/reference-demo")
    def reference_manifest():
        from .reference_demo import load_manifest
        manifest, _, _ = load_manifest(reference_root)
        return manifest

    @app.get("/api/studio/reference-demo/assets/{asset_name}")
    def reference_asset(asset_name: str):
        from .reference_demo import load_manifest
        _, root, assets = load_manifest(reference_root)
        if asset_name not in assets:
            raise NotFound("Reference asset not found")
        return FileResponse(root / asset_name, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})

    def prepared_showcase_cache(root, archive_name):
        """Only the bundled showcase can supply a hashed source extraction cache."""
        try:
            manifest = json.loads((root / "showcase.json").read_text(encoding="utf-8-sig"))
            name, expected = manifest.get("source_cache"), manifest.get("source_cache_sha256")
            if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.json", name)
                    or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)):
                return None
            path = (root / name).resolve()
            if path.parent != root or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                return None
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                return None
            cache = json.loads(content)
            if (not isinstance(cache, dict) or cache.get("schema") != "vwc-prepared-source-cache/1"
                    or cache.get("archive_sha256") != hashlib.sha256((root / archive_name).read_bytes()).hexdigest()
                    or not isinstance(cache.get("documents"), list) or not 1 <= len(cache["documents"]) <= 8):
                return None
            return {**cache, "root": str(root)}
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def assert_owned_drawing_sources(project_id, documents):
        from .ai import AIError
        directory = repository.directory(project_id)
        for doc in documents:
            source = filesystem_path(doc["local_path"])
            if not source.is_relative_to(directory) or hashlib.sha256(source.read_bytes()).hexdigest() != doc["sha256"]:
                raise AIError("An imported source changed. Re-import it before analysis; saved design retained.", "input")

    def run_3d_sequence(job, item, agent, check_job_control, publish_at_checkpoint):
        from .ai import AIError
        from .generate_3d import generate_3d_from_2d
        from .group_3d_draft import group_draft_source

        job_id, project_id = job["id"], job["project_id"]
        source_job = repository.get_job(job["draft_3d_source_job_id"])
        sequence = job["draft_3d_sequence"]
        completed = sum(row["status"] in ("ready", "needs_review") for row in sequence)
        for row in sequence:
            if row["status"] in ("ready", "needs_review"):
                continue
            check_job_control()
            group_id = row["group_id"]
            source = group_draft_source(repository, item, source_job, group_id)
            if source.sha256 != job["draft_3d_sequence_pins"][group_id]:
                raise Conflict("The saved 2D group changed before the 3D sequence reached it.")
            row["status"] = "running"
            publish_at_checkpoint(repository.update_job, job_id, require_unpaused=True,
                status="running", phase="preparing_3d_sources", progress=completed * 100 // len(sequence),
                draft_3d_sequence=sequence, draft_3d_current_group_id=group_id,
                draft_3d_group_label=row["label"], draft_3d_group_progress=0)

            child_id = project_id + "." + uuid4().hex
            child = {"id": child_id, "project_id": project_id, "base_revision": job["base_revision"],
                     "kind": "generate3d", "created_at": now(), "phase": "review", "progress": 100,
                     "draft_3d_group_id": group_id, "draft_3d_group_label": row["label"],
                     "draft_3d_source_job_id": source_job["id"], "draft_3d_source_checked": source.checked,
                     "draft_3d_source_pin": source.sha256}

            def report_group_progress(phase, percent):
                check_job_control()
                repository.update_job(job_id, status="running", phase=phase,
                    progress=(completed * 100 + percent) // len(sequence), draft_3d_group_progress=percent)

            error = None
            try:
                result = generate_3d_from_2d(agent, source.model, item["documents"],
                    repository.directory(project_id) / "workflow-runs" / child_id.split(".", 1)[1] / "3d",
                    project_id=project_id, run_id=child_id, instruction=job["draft_3d_sequence_instruction"],
                    progress=report_group_progress, check_control=check_job_control, preview_only=True,
                    source_correspondence=source.correspondence)
                receipt = result["workflow_3d"]
                status = ("ready" if receipt.get("status") == "draft_ready" else "needs_review"
                          if receipt.get("preview_ready") else "failed")
                child.update(status=status, workflow_3d=receipt, usage=result.get("usage"))
                if status == "failed":
                    child.update(error="This group did not produce a usable 3D draft in two cycles.",
                                 error_category="invalid_output")
            except AIError as failure:
                error = failure
                child.update(status="failed", error=str(failure), error_category=failure.category,
                             usage=getattr(failure, "usage", {}))
            publish_at_checkpoint(repository.finish_3d_sequence_group, job_id, child)
            row.update(status=child["status"], job_id=child_id)
            completed += 1
            if error is not None and error.category not in ("invalid_output", "invalid_response"):
                raise error

        statuses = {row["status"] for row in sequence}
        status = "ready" if statuses == {"ready"} else "failed" if statuses == {"failed"} else "needs_review"
        finish_grouped_generation(job, item, publish_at_checkpoint, status=status,
            phase="review", progress=100, draft_3d_current_group_id=None, draft_3d_group_label=None,
            draft_3d_group_progress=None)

    def run_job(job_id, instruction, selection="", screenshot=None, screenshot_type="image/png",
                replace_existing=False, material_mode="api"):
        from .ai import AIError
        from .job_control import JobControl
        job = repository.get_job(job_id)
        project_id = job["project_id"]
        material_job = job["kind"] == "materials"
        controller = JobControl(repository, job_id, stopping)
        agent = None
        original_request = None
        def check_job_control():
            if stopping.is_set():
                raise StopRequested()
            controller.check()

        def publish_at_checkpoint(publish, *args, **kwargs):
            while True:
                check_job_control()
                try:
                    return publish(*args, **kwargs)
                except JobPaused:
                    # The project or task paused before the write locked.
                    # Hold the candidate in this worker until it resumes.
                    continue

        def publish_failure(**changes):
            if material_job and not stopping.is_set():
                try:
                    publish_at_checkpoint(repository.update_job, job_id, require_unpaused=True, **changes)
                except (StopRequested, JobInterrupted):
                    if stopping.is_set():
                        repository.update_job(job_id, **INTERRUPTED_JOB)
            else:
                repository.update_job(job_id, **changes)

        try:
            check_job_control()
            item = current(project_id, job["base_revision"], writable=False)
            draft_source = None
            draft_documents = item["documents"]
            if job.get("draft_3d_group_id"):
                source_job = repository.get_job(job["draft_3d_source_job_id"])
                destination, draft_source, input_project = verified_group_3d_input(item, source_job, job["draft_3d_group_id"],
                    job.get("draft_3d_donor_job_id"), job.get("draft_3d_donor_group_id"))
                if (destination.sha256 != job["draft_3d_source_pin"]
                        or draft_source.sha256 != job.get("draft_3d_donor_pin", job["draft_3d_source_pin"])):
                    raise Conflict("The selected drawing group changed before 3D generation began.")
                draft_documents = input_project["documents"]
            if job.get("retry_proposal_id") and (item.get("pending_proposal") or {}).get("id") != job["retry_proposal_id"]:
                raise Conflict("The preview changed before retry; reopen the project. / 重试前预览已改变，请重新打开项目。")
            recovering = "recover_group_ids" in job
            recovered_percent = job["progress"] if recovering else 0
            def progress(phase, percent):
                nonlocal recovered_percent
                check_job_control()
                if recovering:
                    percent = recovered_percent = max(recovered_percent, percent)
                repository.update_job(job_id, status="running", phase=phase, progress=percent)
            if not job.get("draft_3d_sequence"):
                progress("reading_materials" if material_job else "reading_sources", 10 if material_job else 5)
            prepared_materials = material_job and material_mode == "prepared"
            source_materials = material_job and material_mode == "source"
            agent = None if prepared_materials or source_materials else gateway()
            if agent is not None:
                original_request = getattr(agent, "_request", None)
                if callable(original_request):
                    agent._request = controller.wrap_request(original_request)
                with gateway_lock:
                    active_gateways[job_id] = agent
            check_job_control()
            suggestion_receipt = None
            receipt_3d = None
            if job.get("draft_3d_sequence"):
                run_3d_sequence(job, item, agent, check_job_control, publish_at_checkpoint)
                return
            if job.get("grouped_2d"):
                from .grouped_2d import run_group_rebuild, run_group_retry, run_grouped_2d
                assert_owned_drawing_sources(project_id, item["documents"])
                output = repository.directory(project_id) / "workflow-runs" / job_id.split(".", 1)[1]
                options = {"plan_path": repository.grouped_2d_plan_path(project_id), "check_control": check_job_control,
                           "progress": progress, "publish": lambda states: repository.update_job(job_id, groups_2d=states)}
                if job.get("recover_group_ids"):
                    from .grouped_2d import run_group_recovery
                    previous = repository.get_job(job["retry_from_job_id"])
                    groups = run_group_recovery(agent, item["documents"], output, job=job, previous=previous, **options)
                elif job.get("retry_group_id"):
                    previous = repository.get_job(job["retry_from_job_id"])
                    groups = run_group_retry(agent, item["documents"], output, job=job, previous=previous, **options)
                elif job.get("rebuild_group_ids"):
                    previous = repository.get_job(job["retry_from_job_id"])
                    groups = run_group_rebuild(agent, item["documents"], output, job=job, previous=previous, **options)
                else:
                    groups = run_grouped_2d(agent, item["documents"], output, project_id=project_id, job_id=job_id,
                                            instruction=instruction, **options)
                status = "ready" if all(group.get("accepted") for group in groups) else "needs_review"
                if all(group["status"] == "failed" for group in groups):
                    status = "failed"
                publish_at_checkpoint(repository.update_job, job_id, require_unpaused=True,
                                      status=status, phase="review", progress=100, groups_2d=groups)
                return
            if material_job:
                from .material_suggestions import (MaterialSuggestionPlan, apply_material_plan, material_context,
                    material_receipt, material_source_context, prepared_material_plan, source_material_plan)
                context = material_context(item["model"], material_library.list(), selection=selection,
                                           replace_existing=replace_existing, require_compatible=not source_materials)
                unresolved = None
                if prepared_materials:
                    if item.get("reference_source_key") != "west15-reviewed-v1" or reviewed_source(item) is None:
                        raise ValueError("Prepared material suggestions require the matching original reference project")
                    if instruction.strip():raise ValueError("Use AI mode for a custom material request; the prepared palette does not interpret language")
                    progress("matching_materials", 50)
                    plan,usage=prepared_material_plan(context),None
                else:
                    progress("reading_material_sources", 25)
                    try:
                        page_text, images = material_source_context(context, item["documents"],
                            repository.directory(project_id), render=not source_materials)
                    except (OSError, ValueError, TypeError, KeyError) as error:
                        message = str(error) if isinstance(error, ValueError) else "A cited original source could not be read. Reimport it and try again."
                        raise AIError(message, "input") from None
                    progress("matching_materials" if source_materials else "choosing_materials", 50)
                    if source_materials:
                        plan, unresolved = source_material_plan(context, page_text)
                        usage = None
                    else:
                        suggested = agent.suggest_materials(context, instruction, progress=progress, source_images=images)
                        plan, usage = suggested["plan"], suggested.get("usage")
                progress("validating_materials", 80)
                plan = MaterialSuggestionPlan.model_validate(plan)
                if not plan.assignments:
                    publish_at_checkpoint(repository.update_job, job_id, require_unpaused=True, status="failed",
                        phase="failed", progress=100, error_category="empty_suggestions", usage=usage,
                        error="No compatible material assignment was proposed. " + "; ".join(plan.notes)[:1500],
                        material_suggestions={"origin": material_mode, **material_receipt(plan, context, unresolved)})
                    return
                try:
                    candidate,suggestion_receipt=apply_material_plan(item["model"],material_library.list(),plan,
                        selection=selection,replace_existing=replace_existing,source_context=context)
                    if unresolved is not None:
                        suggestion_receipt["unresolved"] = [*context["unavailable"], *unresolved]
                except (ValueError,TypeError,KeyError) as error:
                    raise AIError("Suggested materials did not pass validation. "+str(error),"invalid_output",usage=usage) from None
                suggestion_receipt["origin"] = material_mode
                result={"model":candidate,"summary":f'Material suggestions prepared for {suggestion_receipt["assignment_count"]} part(s). Review before applying.',
                    "warnings":suggestion_receipt["notes"],"usage":usage}
            elif job["kind"] in ("generate3d", "edit3d"):
                from .generate_3d import generate_3d_from_2d
                source_model = draft_source.model if draft_source else validate_3d_input(item)
                run_output = repository.directory(project_id) / "workflow-runs" / job_id.split(".", 1)[1] / "3d"
                draft_options = {"preview_only": True, "source_correspondence": draft_source.correspondence} if draft_source else {}
                result = generate_3d_from_2d(agent, source_model, draft_documents, run_output,
                    project_id=project_id, run_id=job_id, instruction=instruction,
                    selection=selection, screenshot=screenshot, screenshot_type=screenshot_type,
                    progress=progress, check_control=check_job_control, **draft_options)
                receipt_3d = result["workflow_3d"]
                if draft_source:
                    status = "needs_review" if receipt_3d.get("preview_ready") else "failed"
                    finish_grouped_generation(job, item, publish_at_checkpoint,
                                          status=status, phase="review", progress=100, workflow_3d=receipt_3d,
                                          usage=result.get("usage"))
                    return
            elif autonomous_2d and (job["kind"] in ("analyze", "redraw", "edit2d") or
                    (job["kind"] == "edit" and not build_scene(validate_model(item["model"]), project_id, item["revision"])["meshes"])):
                from .autonomous_2d import run_autonomous_2d
                # Every runtime input belongs to this imported project. No reference
                # packet, development experiment or Codex-prepared catalog is used.
                assert_owned_drawing_sources(project_id, item["documents"])
                source_model = validate_model(item["model"])
                if source_model.source_2d_binding is not None:
                    from .drawing_state import source_2d_model
                    source_model = source_2d_model(source_model, item["documents"])
                if job.get("source_proposal_id"):
                    pending = repository.get_proposal(project_id, job["source_proposal_id"])
                    if pending["status"] != "pending" or pending["base_revision"] != item["revision"]:
                        raise Conflict("This preview is stale or already applied / 此预览已过期或已应用")
                    source_model = validate_model(pending["model"])
                rebuild_attempt = job.get("rebuild_2d_attempt")
                ledger_path = conversion_ledger(project_id, rebuild_attempt)
                scope_kind = "source_rebuild" if rebuild_attempt else "source_conversion"
                prior_receipt = public(item | {"pending_proposal": None}).get("workflow_2d")
                # A standard archive preserves checked models, not the local job
                # database. Verify the saved source group itself so portable
                # projects keep the same amendment workflow after reopening.
                verified_saved_baseline = False
                if job["kind"] in ("edit", "edit2d", "redraw") and instruction.strip() and not job.get("source_proposal_id"):
                    from .autonomous_2d import _verified_baseline
                    try:
                        _verified_baseline(source_model, item["documents"])
                        verified_saved_baseline = True
                    except ValueError:
                        pass
                if (job["kind"] in ("edit", "edit2d", "redraw") and instruction.strip() and
                        ((prior_receipt and prior_receipt.get("accepted") is True) or verified_saved_baseline) and
                        drawing_set_ready(build_scene(validate_model(item["model"]), project_id, item["revision"]))):
                    from .drafting import drawing_hash
                    from .api_drawing_workflow import _source_identity
                    amendment = {"base_revision": item["revision"],
                        "baseline_drawings": [drawing_hash(view) for view in validate_model(item["model"]).drawings],
                        "source_identity": (prior_receipt or {}).get("source_set_sha256") or _source_identity(item["documents"]),
                        "instruction": instruction, "selection": selection,
                        "capture_sha256": hashlib.sha256(screenshot).hexdigest() if screenshot else None}
                    amendment_id = hashlib.sha256(encode(amendment).encode()).hexdigest()
                    ledger_path = ledger_path.parent / "amendments" / (amendment_id + ".json")
                    scope_kind = "user_amendment"
                run_output = repository.directory(project_id) / "workflow-runs" / job_id.split(".", 1)[1]
                run_output.mkdir(parents=True, exist_ok=True)
                previous_sink = getattr(agent, "diagnostic_sink", None)
                response_count = 0
                def record_response(kind, payload):
                    nonlocal response_count
                    check_job_control()
                    data = encode(payload)
                    if len(data.encode("utf-8")) > 10 * 1024 * 1024:
                        raise ValueError("The structured response exceeds the local diagnostic limit")
                    response_count += 1
                    name = re.sub(r"[^A-Za-z0-9_-]", "_", str(kind))[:80]
                    (run_output / f"raw-response-{response_count:02d}-{name}.json").write_text(data, encoding="utf-8")
                agent.diagnostic_sink = record_response
                try:
                    result = run_autonomous_2d(agent, item["documents"], run_output,
                        project_id=project_id, run_id=job_id, instruction=instruction,
                        current_model=source_model, progress=progress, check_control=check_job_control,
                        cycle_ledger_path=ledger_path,
                        selection=selection, screenshot=screenshot, screenshot_type=screenshot_type,
                        preserve_baseline=scope_kind == "user_amendment" or bool(rebuild_attempt and source_model.drawings))
                finally:
                    agent.diagnostic_sink = previous_sink
                result["workflow_receipt"].update(scope_kind=scope_kind)
                if rebuild_attempt and (item["model"].get("source_2d_binding") or item.get("reference_source_key")):
                    result["warnings"] = [*result.get("warnings", []),
                        "Applying the rebuilt 2D starts a new source revision. Rebuild 3D from that revision. The previous 3D design and its materials are available in Revision History."]
            elif job["kind"] == "redraw":
                from .ai import StudioAIGateway
                from .drawing_edits import regenerate_drawings
                pending = repository.get_proposal(project_id, job["source_proposal_id"])
                if pending["status"] != "pending" or pending["base_revision"] != item["revision"]:
                    raise Conflict("This preview is stale or already applied / 此预览已过期或已应用")
                original = validate_drawing_sources(item["model"], item["documents"], project_id=project_id, verify_files=True)
                candidate = validate_drawing_sources(pending["model"], item["documents"], project_id=project_id, verify_files=True)
                started = time.perf_counter()
                candidate, runs = regenerate_drawings(agent, original, candidate, instruction, item["documents"], progress)
                result = {"model": candidate, "summary": "Regenerate linked drawings / 重新生成联动图纸",
                          "warnings": list(dict.fromkeys([*pending["warnings"], *candidate.warnings])),
                          "usage": StudioAIGateway._combined_usage(runs, started) if runs else None}
            elif job["kind"] == "analyze":
                from .ai import INDEX_PROMPT, SourceIndex, StudioAIGateway
                cached_index = None
                cached_drawing = None
                if isinstance(agent, StudioAIGateway):
                    cache_material = {"documents": [(doc["id"], doc["sha256"], doc["page_count"]) for doc in item["documents"]],
                                      "model": agent.model, "instruction": instruction,
                                      "index_prompt": INDEX_PROMPT, "schema": SourceIndex.model_json_schema()}
                    cache_id = hashlib.sha256(encode(cache_material).encode()).hexdigest()
                    cache_path = repository.directory(project_id) / "source-index-cache.json"
                    drawing_cache_path = repository.directory(project_id) / "drawing-plan-cache.json"
                    drawing_cache_id = None
                    if agent.enable_drafting:
                        for doc in item["documents"]:
                            path = Path(doc["local_path"]).resolve()
                            if not path.is_relative_to(repository.directory(project_id)) or hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
                                raise AIError("An imported source changed. Re-import it before analysis; saved design retained. / 已导入的原图发生变化，请重新导入后分析；已保存设计保留。", "input")
                        drawing_cache_id = _drawing_retry_identity(item,instruction,agent,build_id)
                        cache_id = drawing_cache_id
                        try:
                            if drawing_cache_path.stat().st_size <= DRAWING_CHECKPOINT_LIMIT:
                                cached = json.loads(drawing_cache_path.read_text(encoding="utf-8"))
                                if cached.get("identity") == drawing_cache_id:
                                    candidate, index, classification = agent._validate_drawing_checkpoint(cached["checkpoint"],item["documents"],validate_model(item["model"]))
                                    cached_drawing = {"model":candidate.model_dump(exclude={"drawings"}),"source_index":index.model_dump(),**classification}
                        except (OSError,ValueError,TypeError,KeyError,AIError):
                            cached_drawing = None
                    try:
                        if cache_path.stat().st_size <= 1024 * 1024:
                            cache = json.loads(cache_path.read_text(encoding="utf-8"))
                            if cache.get("identity") == cache_id:
                                cached_index = SourceIndex.model_validate(cache["index"])
                                agent._check_index(cached_index, item["documents"])
                    except (OSError, ValueError, KeyError, AIError):
                        cached_index = None
                    def cache_index(kind, payload):
                        if kind == "DrawingPlanCheckpoint" and drawing_cache_id is not None:
                            try:
                                candidate,index,classification = agent._validate_drawing_checkpoint(payload,item["documents"],validate_model(item["model"]))
                                clean = {"model":candidate.model_dump(exclude={"drawings"}),"source_index":index.model_dump(),**classification}
                                data = encode({"identity":drawing_cache_id,"checkpoint":clean})
                                if len(data.encode("utf-8")) > DRAWING_CHECKPOINT_LIMIT:
                                    return
                                temporary = drawing_cache_path.with_suffix("."+uuid4().hex+".tmp")
                                try:
                                    temporary.write_text(data,encoding="utf-8");os.replace(temporary,drawing_cache_path)
                                finally:temporary.unlink(missing_ok=True)
                            except (OSError,ValueError,TypeError,KeyError,AIError):
                                pass
                            return
                        if kind != "SourceIndex":
                            return
                        index = SourceIndex.model_validate(payload)
                        agent._check_index(index, item["documents"])
                        temporary = cache_path.with_suffix("." + uuid4().hex + ".tmp")
                        try:
                            temporary.write_text(encode({"identity": cache_id, "index": index.model_dump()}), encoding="utf-8")
                            os.replace(temporary, cache_path)
                        finally:
                            temporary.unlink(missing_ok=True)
                    agent.diagnostic_sink = cache_index
                options = ({"drawing_checkpoint":cached_drawing} if cached_drawing is not None else
                           {"source_index": cached_index} if cached_index is not None else {})
                result = agent.analyze(item["documents"], current_model=validate_model(item["model"]),
                                       instruction=instruction, progress=progress, **options)
            else:
                result = agent.edit(validate_model(item["model"]), instruction,
                                    documents=item["documents"], selection=selection,
                                    screenshot=screenshot, screenshot_type=screenshot_type, progress=progress)
            check_job_control()
            candidate = validate_drawing_sources(result["model"], item["documents"], project_id=project_id, verify_files=True)
            # Design generation/editing does not authorize renaming the project.
            # Keep raw API diagnostics intact; the saved title owns this boundary.
            if not material_job:candidate = candidate.model_copy(update={"name": item["name"]})
            receipt = result.get("workflow_receipt")
            if receipt is not None and receipt.get("accepted") is not True:
                from .drafting import stamp_review
                issues = list(receipt.get("issues") or ["The complete 2D drawing group has not passed its independent check."])
                candidate = candidate.model_copy(update={"drawings": [stamp_review(view, False, issues[:200]) for view in candidate.drawings]})
            # Resolve before storing any proposal. Geometry failure never touches saved revisions.
            if material_job:
                progress("preparing_material_preview", 95)
            candidate_scene = build_scene(candidate, project_id, item["revision"] + 1)
            ready = (proposal_can_apply(candidate_scene) and (receipt is None or receipt.get("accepted") is True)
                     and (receipt_3d is None or receipt_3d.get("accepted") is True))
            completion = dict(status="ready" if ready else "needs_review", phase="review", progress=100, usage=result.get("usage"),
                                  source_index=result.get("source_index"), drawing_quality=candidate_scene.get("drawing_quality"),
                                  **({"workflow_2d": receipt} if receipt is not None else {}),
                                  **({"workflow_3d": receipt_3d} if receipt_3d is not None else {}),
                                  **({"material_suggestions":suggestion_receipt} if suggestion_receipt is not None else {}))
            proposal = publish_at_checkpoint(repository.proposal, project_id, item["revision"], candidate,
                                             result["summary"], result.get("warnings", []),
                                             replaces=job.get("source_proposal_id") or job.get("retry_proposal_id"), job_id=job_id,
                                             **({"job_completion": completion} if material_job else {}))
            if not material_job:
                repository.update_job(job_id, proposal_id=proposal["id"], **completion)
        except (StopRequested, JobInterrupted):
            if stopping.is_set() and repository._holds_on_project_pause(job):
                repository.update_job(job_id, **INTERRUPTED_JOB)
            else:
                repository.update_job(job_id, status="failed", phase="stopped", progress=100,
                                      error="Stopped by the user; saved design retained / 用户已停止任务，已保存设计保留")
        except AIError as error:
            was_stopped = stopping.is_set()
            if was_stopped and repository._holds_on_project_pause(job):
                repository.update_job(job_id, **INTERRUPTED_JOB, usage=getattr(error, "usage", {}))
            else:
                publish_failure(status="failed", phase="stopped" if was_stopped else "failed", progress=100,
                                      error="Stopped by the user; saved design retained / 用户已停止任务，已保存设计保留" if was_stopped else str(error),
                                      error_category="stopped" if was_stopped else getattr(error, "category", "api"),
                                      usage=getattr(error, "usage", {}))
        except CredentialError as error:
            publish_failure(status="failed", phase="failed", progress=100, error=str(error))
        except Conflict as error:
            publish_failure(status="failed", phase="stale", progress=100, error=str(error))
        except Exception as error:
            publish_failure(status="failed", phase="validation", progress=100,
                                  error="The proposed model could not be validated. Saved design retained. / 提案未通过验证，已保存设计保留。",
                                  error_category=type(error).__name__)
        finally:
            if agent is not None and callable(original_request):
                agent._request = original_request
            with gateway_lock:
                active_gateways.pop(job_id, None)

    def require_ai():
        if not allow_ai:
            raise HTTPException(403, "Assistant actions are unavailable in this workspace.")

    def start_job(project_id, expected_revision, kind, instruction, background, *, source_proposal_id=None,
                  retry_proposal_id=None, grouped_2d=False, retry_group_id=None, previous_job_id=None,
                  recover_2d=False, rebuild_2d=False, rebuild_group_id=None, draft_3d_group_id=None, draft_3d_source_job_id=None,
                  draft_3d_donor_job_id=None, draft_3d_donor_group_id=None, rebuild_single_2d=False,
                  rebuild_saved_groups=False, **kwargs):
        if not (kind == "materials" and kwargs.get("material_mode") in ("prepared", "source")):
            require_ai()
        if stopping.is_set():
            raise HTTPException(503, "The application is closing / 应用正在关闭")
        item = current(project_id, expected_revision)
        previous_group_job = None
        recovery_ids = None
        rebuild_ids = None
        draft_source = None
        rebuild_attempt = None
        if rebuild_single_2d:
            if not autonomous_2d or item.get("pending_proposal") or item.get("active_job"):
                raise Conflict("Finish the current task or preview before rebuilding 2D.")
            plan_path = repository.grouped_2d_plan_path(project_id)
            if plan_path.exists() or (plan_path.parent / "group-cycles").exists():
                raise Conflict("Rebuild the mapped drawing groups from the group controls.")
            model = validate_drawing_sources(item["model"], item["documents"], project_id=project_id, verify_files=True)
            if model.drawings:
                from .drawing_state import source_2d_model
                from .autonomous_2d import _verified_baseline
                _verified_baseline(source_2d_model(model, item["documents"]), item["documents"])
            elif item.get("reference_source_key") != "west15-reviewed-v1" or reviewed_source(item) is None:
                raise Conflict("Save a checked 2D result before rebuilding.")
        if recover_2d:
            from .ai import AIError
            previous_group_job = repository.latest_job(project_id, grouped_2d=True)
            if previous_group_job and previous_group_job["id"] == previous_job_id:
                recovery_ids = available_group_recovery(item, previous_group_job)
            if recovery_ids is None:
                raise Conflict("This 2D checkpoint can no longer be resumed. Open the project to see its available results. / 此二维检查点已无法继续。请打开项目查看已有成果。")
            try:
                assert_owned_drawing_sources(project_id, item["documents"])
            except (AIError, OSError):
                raise Conflict("The original PDF changed or is unavailable. This 2D checkpoint cannot resume. / 原始 PDF 已改变或无法读取，此二维检查点无法继续。") from None
            instruction = previous_group_job.get("group_instruction", "")
        elif retry_group_id is not None:
            previous_group_job = repository.latest_job(project_id, grouped_2d=True)
            if (not previous_group_job or previous_job_id and previous_group_job["id"] != previous_job_id
                    or retry_group_id not in available_group_retries(item, previous_group_job)):
                raise Conflict("This drawing group can no longer be retried. / 此图纸组已无法重试。")
            assert_owned_drawing_sources(project_id, item["documents"])
        elif rebuild_2d:
            previous_group_job = repository.latest_job(project_id, grouped_2d=True)
            groups = available_group_rebuilds(item, previous_group_job)
            if (not groups or previous_group_job["id"] != previous_job_id
                    or rebuild_group_id is not None and rebuild_group_id not in groups):
                raise Conflict("This drawing group cannot rebuild from the current source map. Reopen the project.")
            rebuild_ids = [rebuild_group_id] if rebuild_group_id is not None else list(groups)
            assert_owned_drawing_sources(project_id, item["documents"])
        elif rebuild_saved_groups:
            from .ai import AIError
            if retry_proposal_id or not can_rebuild_2d_from_originals(item, empty=is_empty_design(item["model"])):
                raise Conflict("This saved project cannot start a fresh group rebuild. Reopen its drawing groups to review available actions.")
            try:
                assert_owned_drawing_sources(project_id, item["documents"])
            except (AIError, OSError, ValueError):
                raise Conflict("The original PDF changed or is unavailable. Re-import it before rebuilding groups.") from None
        elif grouped_2d and (retry_proposal_id or not can_analyze_groups(item, empty=is_empty_design(item["model"]))):
            raise Conflict("Start separate drawing groups on an empty project without an existing drawing-group record. Use Retry 2D for an earlier empty preview. / 请在尚无绘图组记录的空白项目中依次绘制图纸组。较早的空白预览请使用‘重试二维绘图’。")
        if retry_proposal_id and (not autonomous_2d or kind != "analyze" or not item.get("can_retry_2d")
                or (item.get("pending_proposal") or {}).get("id") != retry_proposal_id):
            raise Conflict("The empty preview is no longer eligible for retry. / 空白预览已无法重试。")
        if retry_proposal_id:
            with repository.connect(project_id) as connection:
                jobs = [json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs ORDER BY rowid DESC")]
                owner = next((job for job in jobs if job.get("proposal_id") == retry_proposal_id), {})
            rebuild_attempt = owner.get("rebuild_2d_attempt")
        if kind == "analyze" and not item["documents"]:
            raise ValueError("Import customer sources first / 请先导入客户原图")
        if kind in ("generate3d", "edit3d"):
            if len(instruction) > 8000:
                raise ValueError("Keep the 3D instruction under 8,000 characters.")
            if item.get("pending_proposal") or item.get("active_job"):
                raise Conflict("Finish or discard the current preview/task before creating 3D.")
            if draft_3d_group_id:
                source_job = repository.latest_job(project_id, grouped_2d=True)
                if not autonomous_2d or not source_job or source_job["id"] != draft_3d_source_job_id:
                    raise Conflict("The source group has changed. Reopen the drawing group before creating its 3D draft.")
                try:
                    draft_destination, draft_source, draft_input_project = verified_group_3d_input(item, source_job,
                        draft_3d_group_id, draft_3d_donor_job_id, draft_3d_donor_group_id)
                except (OSError, KeyError, TypeError, ValueError) as error:
                    raise Conflict(str(error) if isinstance(error, ValueError) else
                                   "The original drawings for this group are incomplete or unavailable.") from None
            else:
                validate_3d_input(item)
        if autonomous_2d and kind in ("analyze", "edit", "edit2d", "redraw"):
            if len(instruction) > 8000:
                raise ValueError("Keep the 2D instruction under 8,000 characters. / 请将二维图纸要求控制在 8000 字符以内。")
            if kind in ("analyze", "edit", "edit2d") and item.get("pending_proposal") and not retry_proposal_id:
                raise Conflict("Apply or discard the current preview before requesting another drawing change. / 请求下一次图纸修改前，请应用或放弃当前预览。")
            prior = public(item | {"pending_proposal": None}).get("workflow_2d")
            saved_baseline_ready = prior and prior.get("accepted") is True and drawing_set_ready(
                build_scene(validate_model(item["model"]), project_id, item["revision"]))
            if (not saved_baseline_ready and kind in ("edit", "edit2d", "redraw")
                    and instruction.strip() and not source_proposal_id):
                # Accepted source2D remains an amendment baseline after a 3D
                # revision or portable import, even without its local job row.
                from .drawing_state import source_2d_model
                from .autonomous_2d import _verified_baseline
                try:
                    baseline = source_2d_model(item["model"], item["documents"])
                    _verified_baseline(baseline, item["documents"])
                    saved_baseline_ready = drawing_set_ready(build_scene(baseline, project_id, item["revision"]))
                except ValueError:
                    pass
            if not grouped_2d and (kind == "analyze" or not saved_baseline_ready):
                plan_path = repository.grouped_2d_plan_path(project_id)
                if (plan_path.exists() or (plan_path.parent / "group-cycles").exists() or
                        available_group_recovery(item, repository.latest_job(project_id, grouped_2d=True)) is not None):
                    raise Conflict("This project already has separate drawing groups. Open those results to review them. / 此项目已有独立图纸组，请打开成果审阅。")
                if not rebuild_single_2d:
                    require_conversion_budget(item, rebuild_attempt)
        job_id = project_id + "." + uuid4().hex
        job = {"id": job_id, "project_id": project_id, "base_revision": expected_revision,
               "kind": kind, "status": "queued", "phase": "queued", "progress": 0,
               "created_at": now(), "updated_at": now()}
        if source_proposal_id:
            job["source_proposal_id"] = source_proposal_id
        if draft_source:
            job.update(draft_3d_group_id=draft_3d_group_id, draft_3d_group_label=draft_destination.label,
                       draft_3d_source_job_id=draft_3d_source_job_id, draft_3d_source_checked=draft_source.checked,
                       draft_3d_source_pin=draft_destination.sha256)
            if draft_3d_donor_job_id:
                job.update(draft_3d_donor_project_id=draft_input_project["id"], draft_3d_donor_project_name=draft_input_project["name"],
                           draft_3d_donor_job_id=draft_3d_donor_job_id, draft_3d_donor_group_id=draft_3d_donor_group_id,
                           draft_3d_donor_group_label=draft_source.label, draft_3d_donor_pin=draft_source.sha256,
                           draft_3d_donor_source_evidence_url=f"/api/studio/jobs/{draft_3d_donor_job_id}/working-results/{draft_3d_donor_group_id}--source-evidence.json")
        if retry_proposal_id:
            job["retry_proposal_id"] = retry_proposal_id
        if rebuild_single_2d or rebuild_attempt:
            job["rebuild_2d_attempt"] = rebuild_attempt or job_id.split(".", 1)[1]
        if grouped_2d:
            from .api_drawing_workflow import _source_identity
            job.update(grouped_2d=True, groups_2d=[], group_instruction=instruction,
                       source_set_sha256=_source_identity(item["documents"]))
            if rebuild_saved_groups:
                job["rebuild_saved_groups"] = True
        if previous_group_job:
            job.update(retry_from_job_id=previous_group_job["id"], retry_source_set_sha256=job["source_set_sha256"])
            if recover_2d:
                if recovery_ids:
                    from .grouped_2d import continued_group_states
                    groups = continued_group_states(previous_group_job, job_id, recovery_ids)
                else:
                    groups = previous_group_job["groups_2d"]
                saved_percent = next((value for value in (previous_group_job.get("progress"),
                                                            previous_group_job.get("resume_progress"))
                                      if isinstance(value, (int, float)) and 0 <= value < 100), 0)
                job.update(recover_group_ids=recovery_ids, groups_2d=groups, phase="resuming_2d", progress=saved_percent)
                if previous_group_job.get("rebuild_saved_groups"):
                    job["rebuild_saved_groups"] = True
                if previous_group_job.get("retry_group_id"):
                    job["retry_group_id"] = previous_group_job["retry_group_id"]
            elif rebuild_2d:
                from .grouped_2d import rebuild_group_states
                job.update(rebuild_group_ids=rebuild_ids, groups_2d=rebuild_group_states(previous_group_job, job_id, rebuild_ids))
            else:
                from .grouped_2d import retry_group_states
                job.update(retry_group_id=retry_group_id, groups_2d=retry_group_states(previous_group_job, job_id, retry_group_id))
        repository.start_job(project_id, job)
        background.add_task(run_job, job_id, instruction, **kwargs)
        return {"job_id": job_id}

    def default_2d_instruction(instruction):
        if len(instruction) <= 8000 and not instruction.strip():
            return (
                "Create a 2D drawing set for customer review from the uploaded originals. "
                "Choose one clearly supported room or cabinet assembly and identify its numbered elevations and controlling plans. "
                "When several complete groups are available, use the first complete group in source sheet order. "
                "Bound each plan crop to its subject, including relevant dimensions and complete opening marks. "
                "Use wider architectural plans only as locating context; never map an additional full-floor output. "
                "Preserve the original observations. If no complete group is clear, record the reason for review."
            )
        return instruction

    @app.post("/api/studio/projects/{project_id}/analyze")
    def analyze(project_id: str, command: AnalyzeCommand, background: BackgroundTasks):
        require_ai()
        instruction = default_2d_instruction(command.instruction)
        return start_job(project_id, command.expected_revision, "analyze", instruction, background,
                         retry_proposal_id=command.retry_proposal_id)

    @app.post("/api/studio/projects/{project_id}/rebuild-2d")
    def rebuild_2d(project_id: str, command: AnalysisCommand, background: BackgroundTasks):
        return start_job(project_id, command.expected_revision, "analyze", default_2d_instruction(command.instruction),
                         background, rebuild_single_2d=True)

    @app.post("/api/studio/projects/{project_id}/analyze-groups")
    def analyze_groups(project_id: str, command: AnalyzeGroupsCommand, background: BackgroundTasks):
        return start_job(project_id, command.expected_revision, "analyze", command.instruction, background,
                         retry_proposal_id=command.retry_proposal_id, grouped_2d=True,
                         rebuild_saved_groups=command.rebuild_saved)

    @app.post("/api/studio/projects/{project_id}/resume-2d")
    def resume_2d(project_id: str, command: Resume2DCommand, background: BackgroundTasks):
        return start_job(project_id, command.expected_revision, "analyze", "", background,
                         grouped_2d=True, recover_2d=True, previous_job_id=command.previous_job_id)

    @app.post("/api/studio/projects/{project_id}/drawing-groups/{group_id}/retry")
    def retry_group(project_id: str, group_id: str, command: GroupRetryCommand, background: BackgroundTasks):
        return start_job(project_id, command.expected_revision, "analyze", "", background,
                         grouped_2d=True, retry_group_id=group_id, previous_job_id=command.previous_job_id)

    @app.post("/api/studio/projects/{project_id}/rebuild-2d-groups")
    def rebuild_2d_groups(project_id: str, command: Rebuild2DCommand, background: BackgroundTasks):
        return start_job(project_id, command.expected_revision, "analyze", "", background,
                         grouped_2d=True, rebuild_2d=True, rebuild_group_id=command.group_id,
                         previous_job_id=command.source_job_id)

    @app.post("/api/studio/projects/{project_id}/generate-3d")
    def generate_3d(project_id: str, command: AnalysisCommand, background: BackgroundTasks):
        return start_job(project_id, command.expected_revision, "generate3d", command.instruction, background)

    def grouped_design_candidate(item, jobs, *, require_checks=False, owning_job_id=None):
        from .api_drawing_workflow import content_hash
        from .group_3d_draft import (checked_draft_model, combine_group_drafts, editable_draft_model,
                                     group_draft_source, rebind_draft_documents)
        from .grouped_2d import _read_plan

        source_job = next((job for job in jobs if job.get("grouped_2d")), None)
        state, drafts = grouped_3d_design_readiness(item, source_job, jobs, require_checks=require_checks)
        active_id = (item.get("active_job") or {}).get("id")
        if not is_empty_design(item["model"]) or active_id and active_id != owning_job_id:
            raise Conflict("The editable design or active task must be resolved before saving grouped 3D drafts.")
        if state["status"] != "ready":
            if not require_checks:
                raise Conflict("Build a usable 3D model for every mapped drawing group before saving the editable design.")
            if state["status"] in ("unavailable", "needs_2d_review"):
                raise Conflict("Complete the 2D review for every drawing group in Step 2 before saving the 3D design.")
            raise Conflict("Complete the 3D check for every drawing group in Step 3 before saving the design.")
        group_ids = [row["id"] for row in source_job["groups_2d"]]
        groups = []
        try:
            plan = repository.grouped_2d_plan_path(item["id"])
            _, planned = _read_plan(plan, item["id"], item["documents"])
            if len(group_ids) != len(planned) or set(group_ids) != set(planned):
                raise ValueError("The 3D models must cover every mapped drawing group.")
            for ident in group_ids:
                job = drafts[ident]
                if require_checks:
                    source = group_draft_source(repository, item, source_job, ident)
                    draft = checked_draft_model(repository, item, job, source)
                else:
                    source, baseline, origin = verified_group_3d_input(item, source_job, ident,
                        job.get("draft_3d_donor_job_id"), job.get("draft_3d_donor_group_id"))
                    if (source.sha256 != job.get("draft_3d_source_pin")
                            or baseline.sha256 != job.get("draft_3d_donor_pin", source.sha256)):
                        raise ValueError("A room's original drawing evidence changed after its 3D run.")
                    draft = editable_draft_model(repository, item, job, baseline, origin["documents"])
                    if origin["id"] != item["id"]:
                        draft = rebind_draft_documents(draft, origin["documents"], item["documents"])
                groups.append((source.label, draft))
            candidate = combine_group_drafts(item, groups)
            if not require_checks:
                notices = ["Rooms are arranged separately for review. Confirm relative placement and provisional dimensions.",
                           "Materials and cutting details require explicit panel specifications and compatible stock."]
                candidate = validate_model(candidate.model_dump() | {"warnings": [*notices, *candidate.warnings]})
        except (NotFound, OSError, KeyError, TypeError, ValueError) as error:
            raise Conflict(str(error) if isinstance(error, ValueError)
                           else "The reviewed source or 3D evidence is unavailable. Reopen the affected group.") from None
        inputs = {"source_job_id": source_job["id"], "draft_job_ids": [drafts[ident]["id"] for ident in group_ids],
                  "documents": item["documents"], "candidate_sha256": content_hash(candidate.model_dump())}
        return candidate, inputs

    def group_design_jobs(project_id, *, completing=None):
        with repository.connect(project_id) as connection:
            jobs = [json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs")]
        if completing:
            jobs = [completing if job["id"] == completing["id"] else job for job in jobs]
        return sorted(jobs, key=lambda job: job.get("updated_at", ""), reverse=True)

    def finish_grouped_generation(job, item, publish, **finish):
        if is_empty_design(item["model"]) and not item.get("pending_proposal") and finish["status"] != "failed":
            jobs = group_design_jobs(item["id"], completing=job | finish | {"updated_at": now()})
            source = next((entry for entry in jobs if entry.get("grouped_2d")), None)
            status, _ = grouped_3d_design_readiness(item, source, jobs)
            if status["status"] == "ready":
                try:
                    model, inputs = grouped_design_candidate(item, jobs, owning_job_id=job["id"])
                    publish(repository.save_grouped_3d_design, item["id"], item["revision"], model,
                        "Editable 3D design from grouped room geometry", inputs,
                        owning_job_id=job["id"], finish=finish)
                    return
                except Conflict as error:
                    finish["editable_design_error"] = str(error)
        publish(repository.update_job, job["id"], require_unpaused=True, **finish)

    @app.post("/api/studio/projects/{project_id}/save-3d-design")
    def save_3d_design(project_id: str, command: Command):
        item = current(project_id, command.expected_revision)
        if item.get("pending_proposal"):
            raise Conflict("Finish the existing preview before saving the grouped 3D design.")
        model, inputs = grouped_design_candidate(item, group_design_jobs(project_id))
        repository.save_grouped_3d_design(project_id, item["revision"], model,
            "Editable 3D design from grouped room geometry", inputs)
        return public(repository.get(project_id))

    @app.post("/api/studio/projects/{project_id}/review-3d-design")
    def review_3d_design(project_id: str, command: Command):
        item = current(project_id, command.expected_revision)
        if item.get("pending_proposal"):
            raise Conflict("Finish the existing preview before reviewing the grouped 3D design.")
        model, inputs = grouped_design_candidate(item, group_design_jobs(project_id), require_checks=True)
        warnings = [
            "Rooms are positioned separately for review. Verify their relative placement and provisional dimensions.",
            "This editable design is for customer review. Cutting requires separately specified boards and compatible stock.",
        ]
        return repository.proposal(project_id, item["revision"], model, "Grouped 3D design for customer review",
                                   warnings, group_review_inputs=inputs)

    @app.post("/api/studio/projects/{project_id}/drawing-groups/{group_id}/generate-3d")
    def generate_group_3d(project_id: str, group_id: str, command: GroupDraft3DCommand, background: BackgroundTasks):
        if bool(command.donor_source_job_id) != bool(command.donor_group_id):
            raise ValueError("Select both the earlier 2D task and its matching drawing group.")
        return start_job(project_id, command.expected_revision, "generate3d", command.instruction, background,
                         draft_3d_group_id=group_id, draft_3d_source_job_id=command.source_job_id,
                         draft_3d_donor_job_id=command.donor_source_job_id, draft_3d_donor_group_id=command.donor_group_id)

    @app.post("/api/studio/projects/{project_id}/generate-3d-groups")
    def generate_3d_groups(project_id: str, command: GroupDraft3DSequenceCommand, background: BackgroundTasks):
        from .group_3d_draft import group_draft_source

        require_ai()
        if stopping.is_set():
            raise HTTPException(503, "The application is closing / 应用正在关闭")
        item = current(project_id, command.expected_revision)
        source_job = repository.latest_job(project_id, grouped_2d=True)
        if not autonomous_2d or not source_job or source_job["id"] != command.source_job_id:
            raise Conflict("The source groups have changed. Reopen the project before creating 3D.")
        if item.get("active_job") or item.get("pending_proposal"):
            raise Conflict("Finish or discard the current preview/task before creating 3D.")
        if len(command.instruction) > 8000:
            raise ValueError("Keep the 3D instruction under 8,000 characters.")

        groups = [row for row in source_job["groups_2d"]
                  if row["status"] in ("ready", "needs_review") and row.get("view_ids")]
        if not groups:
            raise Conflict("Complete a 2D drawing group before creating 3D.")
        try:
            sources = [group_draft_source(repository, item, source_job, row["id"]) for row in groups]
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise Conflict("A saved 2D group could not be verified. Reopen the source drawings.") from error
        pins = {row["id"]: source.sha256 for row, source in zip(groups, sources)}
        sequence = [{"group_id": row["id"], "label": source.label, "status": "queued"}
                    for row, source in zip(groups, sources)]
        instruction = command.instruction
        if command.resume_job_id:
            previous = repository.latest_job(project_id)
            if (not previous or previous["id"] != command.resume_job_id
                    or previous["status"] not in ("cancelled", "failed")
                    or previous["base_revision"] != command.expected_revision
                    or previous.get("draft_3d_source_job_id") != source_job["id"]
                    or previous.get("draft_3d_sequence_pins") != pins):
                raise Conflict("The 3D sequence cannot resume from this checkpoint.")
            completed = {row["group_id"]: row for row in previous["draft_3d_sequence"]
                         if row["status"] in ("ready", "needs_review")}
            sequence = [completed.get(row["group_id"], row) for row in sequence]
            if all(row["status"] != "queued" for row in sequence):
                raise Conflict("All groups in that 3D sequence already have a result.")
            instruction = previous["draft_3d_sequence_instruction"]
        elif len(groups) < 2:
            raise Conflict("Use the individual 3D action when only one drawing group is complete.")

        job_id = project_id + "." + uuid4().hex
        completed = sum(row["status"] in ("ready", "needs_review") for row in sequence)
        job = {"id": job_id, "project_id": project_id, "base_revision": command.expected_revision,
               "kind": "generate3d", "status": "queued", "phase": "queued", "progress": completed * 100 // len(sequence),
               "created_at": now(), "updated_at": now(), "draft_3d_source_job_id": source_job["id"],
               "draft_3d_sequence": sequence, "draft_3d_sequence_pins": pins,
               "draft_3d_sequence_instruction": instruction, "draft_3d_resume_from": command.resume_job_id}
        repository.start_job(project_id, job)
        background.add_task(run_job, job_id, "")
        return {"job_id": job_id}

    @app.post("/api/studio/projects/{project_id}/drawing-groups/{group_id}/copy-working-elevation")
    def copy_working_elevation(project_id: str, group_id: str, command: CopyWorkingElevationCommand):
        from .group_3d_draft import group_draft_source
        from .working_results import copy_working_view

        project = current(project_id, command.expected_revision)
        job = repository.latest_job(project_id, grouped_2d=True)
        if not job or job['id'] != command.source_job_id or job['base_revision'] != command.expected_revision:
            raise Conflict('The destination drawings changed. Reopen the project before copying.')
        donor_id = command.donor_job_id.split('.')[0]
        donor = repository.get(donor_id)
        donor_job = repository.get_job(command.donor_job_id)
        if donor_id == project_id or donor_job['base_revision'] != donor['revision']:
            raise Conflict('Select a current drawing from another project.')
        source = group_draft_source(repository, project, job, group_id)
        donor_source = group_draft_source(repository, donor, donor_job, command.donor_group_id)
        destination_view = next((view for view in source.correspondence if view['view_id'] == command.view_id), None)
        donor_view = next((view for view in donor_source.correspondence if view['view_id'] == command.donor_view_id), None)
        match_keys = ('source_sha256', 'page', 'sheet', 'view_number', 'callout', 'kind')
        if (not destination_view or not donor_view or destination_view['kind'] != 'elevation'
                or not destination_view['callout'] or any(donor_view[key] != destination_view[key] for key in match_keys)):
            raise Conflict('The two previews must show the same elevation on the same original PDF.')
        return copy_working_view(repository, job, group_id, command.view_id, donor_job, command.donor_group_id,
                                 command.donor_view_id, donor['name'], donor_view)

    @app.post("/api/studio/projects/{project_id}/material-suggestions")
    def material_suggestions(project_id: str, command: MaterialSuggestionCommand, background: BackgroundTasks):
        from .material_suggestions import material_context
        if command.mode == "api":require_ai()
        item=current(project_id,command.expected_revision)
        if item.get("pending_proposal"):
            raise Conflict("Apply or discard the current preview before requesting material suggestions")
        if item.get("active_job"):
            raise Conflict("Wait for the current project task before requesting material suggestions")
        if command.mode == "prepared" and (item.get("reference_source_key") != "west15-reviewed-v1" or reviewed_source(item) is None):
            raise ValueError("Prepared material suggestions require the matching original reference project")
        if command.mode == "prepared" and command.instruction.strip():
            raise ValueError("Use AI mode for a custom material request; the prepared palette does not interpret language")
        if command.mode == "source" and command.instruction.strip():
            raise ValueError("Use AI suggestions for a custom material request. Source matching reads the original callouts.")
        material_context(item["model"],material_library.list(),selection=command.selection,
                         replace_existing=command.replace_existing, require_compatible=command.mode != "source")
        return start_job(project_id,command.expected_revision,"materials",command.instruction,background,
            selection=command.selection,replace_existing=command.replace_existing,material_mode=command.mode)

    @app.post("/api/studio/projects/{project_id}/ai-edit")
    async def ai_edit(project_id: str, background: BackgroundTasks,
                      expected_revision: int = Form(...), instruction: str = Form(...),
                      selection: str = Form(""), screenshot: UploadFile | None = File(None),
                      target: Literal["auto", "2d", "3d"] = Form("auto")):
        require_ai()
        if not instruction.strip() or len(instruction) > 12000:
            raise ValueError("Enter an edit request under 12,000 characters / 请输入少于 12000 字符的修改要求")
        content = None
        media = "image/png"
        if screenshot:
            content = await screenshot.read(10 * 1024 * 1024 + 1)
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("Screenshot must be under 10 MB / 截图须小于 10 MB")
            from PIL import Image
            try:
                with Image.open(io.BytesIO(content)) as image:
                    if image.format not in ("PNG", "JPEG") or image.width * image.height > 30_000_000:
                        raise ValueError()
                    media = "image/png" if image.format == "PNG" else "image/jpeg"
                    image.verify()
            except Exception:
                raise ValueError("Use a valid PNG or JPEG screenshot / 请使用有效的 PNG 或 JPEG 截图") from None
        kind = "edit3d" if target == "3d" else "edit2d" if target == "2d" and autonomous_2d else "edit"
        if target == "auto" and current(project_id, expected_revision)["model"].get("source_2d_binding"):
            kind = "edit3d"
        return start_job(project_id, expected_revision, kind, instruction, background,
                         selection=selection, screenshot=content, screenshot_type=media)

    @app.get("/api/studio/jobs/{job_id}")
    def job(job_id: str):
        repository.get(job_id.split(".")[0])
        return public_job(repository.get_job(job_id))

    @app.get("/api/studio/jobs/{job_id}/draft-3d/scene")
    def group_draft_scene(job_id: str):
        from .group_3d_draft import draft_scene
        repository.get(job_id.split(".")[0])
        job = repository.get_job(job_id)
        if not job.get("draft_3d_group_id"):
            raise NotFound("No 3D review draft belongs to this task")
        return JSONResponse(draft_scene(repository, job), headers={"Cache-Control": "no-store"})

    @app.post("/api/studio/jobs/{job_id}/control")
    def control_job(job_id: str, command: JobControlCommand):
        changed = repository.control_job(job_id, command.action, command.expected_revision)
        if command.action == "stop":
            close_project_gateways(changed["project_id"])
        return public_job(changed)

    @app.get("/api/studio/jobs/{job_id}/working-results/{artifact_id}")
    def working_artifact(job_id: str, artifact_id: str):
        from .working_results import read_working_artifact
        repository.get(job_id.split(".")[0])
        content, media = read_working_artifact(repository, repository.get_job(job_id), artifact_id)
        drawing_status = "source-evidence" if artifact_id.endswith(("--source-map.png", "--source-evidence.json")) else "working-preview"
        return Response(content, media_type=media,
            headers={"X-Content-Type-Options":"nosniff","Cache-Control":"no-store",
                "Content-Disposition":'inline; filename="'+artifact_id+'"',"X-Drawing-Status":drawing_status})

    @app.get("/api/studio/projects/{project_id}/proposals/{proposal_id}")
    def proposal(project_id: str, proposal_id: str):
        item = repository.get_proposal(project_id, proposal_id)
        if item["summary"] == BOARD_SPECS_PREVIEW_SUMMARY:
            item["board_specs_preview"] = True
        return item

    @app.post("/api/studio/projects/{project_id}/proposals/{proposal_id}/redraw")
    def redraw(project_id: str, proposal_id: str, command: AnalysisCommand, background: BackgroundTasks):
        require_ai()
        item = current(project_id, command.expected_revision)
        pending = repository.get_proposal(project_id, proposal_id)
        if pending["status"] != "pending" or pending["base_revision"] != item["revision"]:
            raise Conflict("This preview is stale or already applied / 此预览已过期或已应用")
        original = validate_drawing_sources(item["model"], item["documents"], project_id=project_id, verify_files=True)
        validate_drawing_sources(pending["model"], item["documents"], project_id=project_id, verify_files=True)
        if not original.drawings:
            raise ValueError("Analyze the sources to create the original drawings first / 请先分析原图以创建初始图纸")
        instruction = command.instruction.strip() or ("Update the linked drawings to match all changes in this pending design preview. "
                                                      "Preserve unchanged source details and review the actual amended drawings.")
        return start_job(project_id, command.expected_revision, "redraw", instruction, background,
                         source_proposal_id=proposal_id)

    @app.post("/api/studio/projects/{project_id}/proposals/{proposal_id}/apply")
    def apply(project_id: str, proposal_id: str, command: Command):
        item = current(project_id, command.expected_revision)
        pending = repository.get_proposal(project_id, proposal_id)
        if pending["status"] != "pending" or pending["base_revision"] != item["revision"]:
            raise Conflict("This preview is stale or already applied / 此预览已过期或已应用")
        validate_drawing_sources(pending["model"], item["documents"], project_id=project_id, verify_files=True)
        with repository.connect(project_id) as connection:
            linked_jobs = [json.loads(row[0]) for row in connection.execute("SELECT data FROM jobs")]
        if any(job.get("proposal_id") == proposal_id
               and (job.get("status") != "ready" or job.get("kind") in ("generate3d", "edit3d")
                    and (job.get("workflow_3d") or {}).get("accepted") is not True)
               for job in linked_jobs):
            raise Conflict("The AI task has not completed its checks; review or repair this preview before applying.")
        if not proposal_can_apply(pending["scene"]):
            raise Conflict("Drawing checks are incomplete or outdated; saved design retained / 图纸检查尚未完成或已过期，已保存设计保留")
        inputs = next((job["group_review_inputs"] for job in linked_jobs
                       if job.get("proposal_id") == proposal_id and job.get("kind") == "group_review_3d"), None)
        if inputs:
            from .api_drawing_workflow import content_hash
            linked_jobs.sort(key=lambda job: job.get("updated_at", ""), reverse=True)
            _, current_inputs = grouped_design_candidate(item, linked_jobs, require_checks=True)
            if inputs != current_inputs or content_hash(pending["model"]) != inputs["candidate_sha256"]:
                raise Conflict("The grouped 3D design changed after preview. Review the current results again.")
        return public(repository.apply(project_id, proposal_id, command.expected_revision, group_review_inputs=inputs))

    @app.get("/api/studio/projects/{project_id}/drawings/export-set")
    def export_drawing_set(project_id: str, proposal_id: str | None = None):
        item = repository.get(project_id)
        model, revision = item["model"], item["revision"]
        if proposal_id:
            pending = repository.get_proposal(project_id, proposal_id)
            if pending["status"] != "pending" or pending["base_revision"] != revision:
                raise Conflict("This drawing preview is stale / 此图纸预览已过期")
            model, revision = pending["model"], revision + 1
        canonical = validate_drawing_sources(model, item["documents"], project_id=project_id, verify_files=True)
        scene = build_scene(canonical, project_id, revision)
        if not canonical.drawings or not drawing_set_ready(scene):
            raise Conflict("Every drawing in the group must pass its checks before PDF export. / 图纸组中的全部图纸均需通过检查后才能导出 PDF。")
        from pypdf import PdfReader, PdfWriter
        from .drafting import render_pdf
        writer = PdfWriter()
        for view in canonical.drawings:
            writer.append(PdfReader(io.BytesIO(render_pdf(view))))
        writer.add_metadata({"/Title": canonical.name + " - Checked 2D Drawings"})
        content = io.BytesIO()
        writer.write(content)
        return Response(content.getvalue(), media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="FormToPart-Drawings-R{revision}.pdf"',
                     "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @app.get("/api/studio/projects/{project_id}/drawings/{view_id}/export")
    def export_drawing(project_id: str, view_id: str, format: str = "pdf", proposal_id: str | None = None):
        if format not in ("pdf", "svg", "png"):
            raise ValueError("Choose PDF, SVG or PNG / 请选择 PDF、SVG 或 PNG")
        item = repository.get(project_id)
        revision = item["revision"]
        if proposal_id:
            pending = repository.get_proposal(project_id, proposal_id)
            if pending["status"] != "pending" or pending["base_revision"] != revision:
                raise Conflict("This drawing preview is stale / 此图纸预览已过期")
            model, drawing_scene = pending["model"], pending["scene"]
            revision += 1
        else:
            model = item["model"]
            drawing_scene = build_scene(model, project_id, revision)
        canonical = validate_drawing_sources(model, item["documents"], project_id=project_id, verify_files=True)
        drawing = next((view for view in canonical.drawings if view.id == view_id), None)
        if drawing is None:
            raise NotFound("Source drawing view not found / 未找到原图二维视图")
        record = drawing_scene.get("drawings", {}).get(view_id)
        if not record or record.get("status") != "ready" or record.get("geometry_count", 0) < 1:
            raise Conflict("This drawing has not passed its checks; export is unavailable / 此图纸尚未通过检查，暂不能导出")
        from .drafting import render_pdf, render_png, render_svg
        content = {"pdf": render_pdf, "png": render_png, "svg": render_svg}[format](drawing)
        filename = f"Cabinet-Studio-{re.sub(r'[^A-Za-z0-9_.-]', '_', view_id)[:80]}-R{revision}.{format}"
        return Response(content, media_type={"pdf": "application/pdf", "png": "image/png", "svg": "image/svg+xml"}[format],
                        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                 "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @app.post("/api/studio/projects/{project_id}/proposals/{proposal_id}/discard")
    def discard(project_id: str, proposal_id: str):
        repository.discard(project_id, proposal_id)
        return {"ok": True}

    @app.post("/api/studio/projects/{project_id}/parameter-preview")
    def parameter_preview(project_id: str, command: ParameterCommand):
        item = current(project_id, command.expected_revision)
        model = set_parameter(item["model"], command.parameter_id, command.value_mm)
        build_scene(model, project_id, item["revision"] + 1)
        return repository.proposal(project_id, item["revision"], model,
                                   f"Edit {command.parameter_id} / 修改参数 {command.parameter_id}")

    @app.post("/api/studio/projects/{project_id}/interior-preview")
    def interior_preview(project_id: str, command: InteriorCommand):
        item = current(project_id, command.expected_revision)
        spec = command.model_dump(exclude={"expected_revision", "cabinet_id"})
        model = design_interior(item["model"], command.cabinet_id, spec)
        build_scene(model, project_id, item["revision"] + 1)
        return repository.proposal(project_id, item["revision"], model,
                                   "Design cabinet interior / 设计柜体内部结构",
                                   ["User-designed interior; board specifications can be exported to Excel. Joinery and machine toolpaths are not specified. / 用户设计的内部结构；板件规格可导出为 Excel，尚未指定连接工艺及机器刀路。"])

    @app.post("/api/studio/projects/{project_id}/restore")
    def restore(project_id: str, command: RestoreCommand):
        return public(repository.restore(project_id, command.expected_revision, command.target_revision))

    @app.get("/api/studio/materials")
    def list_materials(search: str = "", include_inactive: bool = False):
        return material_library.list(search=search, include_inactive=include_inactive)

    @app.post("/api/studio/materials", status_code=201)
    def create_material(material: MaterialVariant):
        return material_library.create(material.model_dump(exclude={"id", "version"}))

    @app.put("/api/studio/materials/{material_id}")
    def update_material(material_id: str, command: MaterialUpdate):
        return material_library.update(material_id,
            command.material.model_dump(exclude={"id", "version"}), command.expected_version)

    @app.post("/api/studio/projects/{project_id}/material-preview")
    def material_preview(project_id: str, command: MaterialCommand):
        item = current(project_id, command.expected_revision)
        variant = material_library.get(command.material_id)
        if variant.version != command.expected_material_version:
            raise Conflict("Material changed; reload the library before assigning / 材料已更改，请重新加载材料库后再指定")
        model = assign_material(item["model"], command.part_ids, variant)
        build_scene(model, project_id, item["revision"] + 1)
        return repository.proposal(project_id, item["revision"], model,
            f"Assign {variant.code} to {len(command.part_ids)} selected part(s) / 为 {len(command.part_ids)} 个所选构件指定材料 {variant.code}")

    @app.post("/api/studio/projects/{project_id}/board-spec-preview")
    def board_spec_preview(project_id: str, command: BoardSpecCommand):
        item = current(project_id, command.expected_revision)
        model = set_board_spec(item["model"], command.part_id, command.spec)
        build_scene(model, project_id, item["revision"] + 1)
        return repository.proposal(project_id, item["revision"], model,
            f"Update board specification {command.part_id} / 更新板件规格 {command.part_id}")

    @app.post("/api/studio/projects/{project_id}/board-specs-preview")
    def board_specs_preview(project_id: str, command: BomExportCommand):
        item = current(project_id, command.expected_revision)
        if item.get("active_job") or item.get("pending_proposal"):
            raise Conflict("Finish the current task or preview before preparing board specifications.")
        report = build_bom(item["model"], project_id, item["revision"], scope_id=command.scope_id)
        if report["bom_sha256"] != command.bom_sha256:
            raise Conflict("The panel list changed. Refresh Step 4 before previewing specifications.")
        specs = {}
        for issue in report["blocked"]:
            suggested = issue.get("suggested_board")
            if suggested:
                specs[issue["part_id"]] = BoardSpec(length_axis=suggested["length_axis"],
                    width_axis=suggested["width_axis"], thickness_axis=suggested["thickness_axis"])
        if not specs:
            raise ValueError("No eligible rectangular panels have unambiguous modeled axes in this scope.")
        model = set_board_specs(item["model"], specs, check_stock=False)
        build_scene(model, project_id, item["revision"] + 1)
        result = repository.proposal(project_id, item["revision"], model, BOARD_SPECS_PREVIEW_SUMMARY,
            ["Axes follow the modeled dimensions. Confirm grain, edging and allowances.",
             "Finish assignments are retained. Confirm compatible board stock before exporting a cutting list."],
            require_idle=True)
        return result | {"board_specs_preview": True}

    @app.post("/api/studio/projects/{project_id}/material-clear-preview")
    def material_clear_preview(project_id: str, command: MaterialClearCommand):
        from .materials import clear_material
        item = current(project_id, command.expected_revision)
        model = clear_material(item["model"], command.part_ids)
        build_scene(model, project_id, item["revision"] + 1)
        return repository.proposal(project_id, item["revision"], model,
            f"Clear material assignment from {len(command.part_ids)} selected part(s) / 清除 {len(command.part_ids)} 个所选构件的材料指定")

    @app.get("/api/studio/projects/{project_id}/bom")
    def bom(project_id: str, scope_id: str | None = None):
        item = repository.get(project_id)
        return build_bom(item["model"], project_id, item["revision"], scope_id=scope_id)

    def checked_bom_export(project_id, command):
        item = current(project_id, command.expected_revision, writable=False)
        report = build_bom(item["model"], project_id, item["revision"], scope_id=command.scope_id)
        if report["bom_sha256"] != command.bom_sha256:
            raise Conflict("The cutting list changed; refresh before exporting / 板件清单已更改，请刷新后再导出")
        return report

    @app.post("/api/studio/projects/{project_id}/bom/export")
    def export_bom(project_id: str, command: BomExportCommand):
        report = checked_bom_export(project_id, command)
        return Response(export_bom_xlsx(report),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":f'attachment; filename="Cabinet-Boards-R{report["revision"]}.xlsx"',
                "X-Content-Type-Options":"nosniff", "Cache-Control":"no-store"})

    @app.post("/api/studio/projects/{project_id}/bom/review-export")
    def export_review_bom(project_id: str, command: BomExportCommand):
        report = checked_bom_export(project_id, command)
        return Response(export_review_bom_xlsx(report),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":f'attachment; filename="Panel-Review-R{report["revision"]}.xlsx"',
                "X-Content-Type-Options":"nosniff", "Cache-Control":"no-store"})

    @app.get("/api/studio/projects/{project_id}/export")
    def export(project_id: str):
        item = repository.get(project_id)
        with repository.connect(project_id) as connection:
            history = [dict(r) for r in connection.execute("SELECT * FROM revisions ORDER BY revision")]
        for revision in history:
            validate_drawing_sources(json.loads(revision["model"]), item["documents"])
        payload = {"schema": "vwc-studio-project/1", "name": item["name"],
                   "history": history, "documents": []}
        if item.get("display_name") or item.get("reference_source_key"):
            payload["project_metadata"] = {"display_name": item["name"]}
            if item.get("reference_source_key"):
                payload["project_metadata"]["reference_source_key"] = item["reference_source_key"]
        folder = repository.directory(project_id) / "exports"
        folder.mkdir(exist_ok=True)
        destination = folder / f"project-R{item['revision']}-{uuid4().hex[:8]}.vwc"
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for document in item["documents"]:
                source = Path(document["local_path"]).resolve()
                if not source.is_relative_to(repository.directory(project_id)):
                    raise ValueError("Invalid project source path / 项目原图路径无效")
                with source.open("rb") as asset_file:
                    if hashlib.file_digest(asset_file, "sha256").hexdigest() != document["sha256"]:
                        raise ValueError("Source hash does not match / 原图校验值不匹配")
                asset = f"sources/{document['id']}{source.suffix}"
                archive.write(source, asset)
                payload["documents"].append({"id": document["id"], "name": document["name"],
                                              "asset": asset, "sha256": document["sha256"]})
            archive.writestr("project.json", encode(payload))
        return FileResponse(destination, media_type="application/zip", filename=f"Cabinet-Studio-R{item['revision']}.vwc")

    async def _import_project(file, *, prepared_cache=None, project_id=None):
        content = await file.read(100 * 1024 * 1024 + 1)
        if len(content) > 100 * 1024 * 1024:
            raise ValueError("Project archive must be under 100 MB / 项目文件须小于 100 MB")
        if prepared_cache is not None and prepared_cache.get("archive_sha256") != hashlib.sha256(content).hexdigest():
            prepared_cache = None
        stage = "open_archive"
        def diagnose(error):
            if on_import_diagnostic is None:
                return
            frames, traceback = [], error.__traceback__
            while traceback is not None and len(frames) < 15:
                frames.append({"file": Path(traceback.tb_frame.f_code.co_filename).name,
                               "line": traceback.tb_lineno,
                               "function": traceback.tb_frame.f_code.co_name})
                traceback = traceback.tb_next
            report = {"stage": stage, "error_type": type(error).__name__,
                      "errno": getattr(error, "errno", None), "winerror": getattr(error, "winerror", None),
                      "traceback": frames}
            try:
                on_import_diagnostic(report)
            except Exception:
                pass
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
            if len(archive.infolist()) > 100 or sum(x.file_size for x in archive.infolist()) > 200 * 1024 * 1024:
                raise ValueError("Project archive is too large / 项目文件解压后过大")
            stage = "read_manifest"
            payload = json.loads(archive.read("project.json"))
            if payload.get("schema") != "vwc-studio-project/1":
                raise ValueError("Unsupported project version / 项目版本不受支持")
            history = payload["history"]
            if not 1 <= len(history) <= 1000:
                raise ValueError("Invalid project history / 项目历史无效")
            stage = "validate_history"
            normalized = []
            for index, revision in enumerate(history, 1):
                if revision["revision"] != index:
                    raise ValueError("Invalid project revision order / 项目版本顺序无效")
                canonical = validate_model(json.loads(revision["model"]))
                normalized.append(revision | {"model": encode(canonical)})
            history = normalized
            stage = "create_staging"
            staging = Repository(repository.root / "_imports" / uuid4().hex)
            created = staging.create(payload["name"], json.loads(history[0]["model"]), project_id=project_id)
            for document in payload["documents"]:
                stage = "read_document"
                data = archive.read(document["asset"])
                if hashlib.sha256(data).hexdigest() != document["sha256"]:
                    raise ValueError("Source hash does not match / 原图校验值不匹配")
                stage = "import_document"
                import_document(staging, created["id"], document["name"], data, document["id"],
                                prepared_cache=prepared_cache)
            stage = "validate_evidence"
            counts = {doc["id"]: doc["page_count"] for doc in staging.get(created["id"])["documents"]}
            staged_documents = staging.get(created["id"])["documents"]
            for revision in history:
                canonical = validate_model(json.loads(revision["model"]))
                validate_drawing_sources(canonical, staged_documents)
                references = [reference for parameter in canonical.parameters for reference in parameter.evidence]
                references.extend(reference for relation in canonical.relationships for reference in relation.evidence)
                stack = [canonical.root]
                while stack:
                    part = stack.pop()
                    references.extend(part.evidence)
                    references.extend(reference for symbol in part.symbols for reference in symbol.evidence)
                    stack.extend(part.children)
                for reference in [*references, *canonical.views]:
                    if reference.document_id not in counts or reference.page > counts[reference.document_id]:
                        raise ValueError("Project evidence refers to a missing source page / 项目证据引用了缺失的原图页面")
            stage = "write_history"
            with staging.connect(created["id"]) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM revisions")
                connection.executemany("INSERT INTO revisions VALUES(?,?,?,?)", [
                    (r["revision"], r["model"], r["summary"], r["created_at"]) for r in history])
                connection.commit()
            # Archive metadata carries the project title and verified bundled
            # reference asset access. Protection and lifecycle are local state.
            project_metadata = payload.get("project_metadata", {})
            if not isinstance(project_metadata, dict):
                raise ValueError("Invalid project metadata")
            if project_metadata.get("reference_source_key") is not None:
                from .reference_demo import REFERENCE_SOURCE_KEY
                if project_metadata["reference_source_key"] != REFERENCE_SOURCE_KEY:
                    raise ValueError("Unsupported reference source key")
                imported_sources = staging.get(created["id"])["documents"]
                matched_source = any(document.get("sha256") == reference_document_sha256
                                     and document.get("media_type") == "application/pdf"
                                     and document.get("page_count") == 3 for document in imported_sources)
                if not matched_source and not (github_seed is not None and legacy_github_sample_document(imported_sources)):
                    raise ValueError("This reference source does not match the attached original PDF")
                if github_seed is not None:
                    upgrade_github_sample_source(staging, staging.get(created["id"]), github_seed)
                staging.attach_reference_source(created["id"], REFERENCE_SOURCE_KEY,
                                                project_metadata.get("display_name", payload["name"]))
            elif "display_name" in project_metadata:
                staging.rename(created["id"], project_metadata["display_name"], len(history))
            stage = "prepare_destination"
            source = staging.directory(created["id"])
            destination = repository.directory(created["id"])
            if source.parent != staging.root or destination.parent != repository.root or destination.exists():
                raise ValueError("Import destination is invalid / 导入目标无效")
            stage = "rebase_sources"
            with staging.connect(created["id"]) as connection:
                for row in list(connection.execute("SELECT id,metadata FROM documents")):
                    metadata = json.loads(row["metadata"])
                    relative = Path(metadata["local_path"]).resolve().relative_to(source)
                    metadata["local_path"] = str(destination / relative)
                    connection.execute("UPDATE documents SET metadata=? WHERE id=?", (encode(metadata), row["id"]))
                connection.commit()
            stage = "publish_project"
            source.rename(destination)
            stage = "read_published_project"
            return public(repository.get(created["id"]))
        except ValueError as error:
            diagnose(error)
            raise
        except Exception as error:
            diagnose(error)
            raise ValueError("This is not a valid Cabinet Studio project / 这不是有效的 Cabinet Studio 项目") from None
        finally:
            if "archive" in locals():
                archive.close()

    @app.post("/api/studio/import")
    async def import_project(file: UploadFile = File(...)):
        # External archives cannot opt into a bundled extraction cache.
        return await _import_project(file)

    @app.get("/api/studio/portable-runtime")
    def portable_runtime():
        candidates = [APP_ROOT / "assets" / "portable.js", APP_ROOT / "portable-dist" / "portable.js"]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise HTTPException(503, "Portable viewer resource is missing / 缺少便携查看器资源")
        return FileResponse(path, media_type="application/javascript")

    @app.post("/api/studio/shutdown")
    def shutdown(background: BackgroundTasks):
        stopping.set()
        def finish():
            if on_shutdown is not None:
                on_shutdown()
            with gateway_lock:
                agents = list(active_gateways.values())
            for agent in agents:
                client = getattr(agent, "client", None)
                if client is not None and callable(getattr(client, "close", None)):
                    try:
                        client.close()
                    except Exception:
                        pass
        background.add_task(finish)
        return {"ok": True}

    @app.post("/api/studio/key-setup")
    def key_setup(background: BackgroundTasks):
        if on_key_setup is None:
            raise HTTPException(503, "Open the separate Key Setup tool / 请打开独立密钥设置工具")
        background.add_task(on_key_setup)
        return {"ok": True}

    assets = APP_ROOT / "ui-dist"
    if assets.is_dir():
        @app.get("/")
        def index():
            return FileResponse(assets / "studio.html")
        if (assets / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=assets / "assets"), name="assets")
    return app
