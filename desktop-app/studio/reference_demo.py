"""Trusted reference assets and a recoverable, once-per-generation app-project reset."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import zipfile
from uuid import uuid4

from .repository import NotFound, encode, now

DEMO_KEY = "fde-reference-demo"
REFERENCE_SOURCE_KEY = "west15-reviewed-v1"
REFERENCE_PROJECT_NAME = "West 15th Avenue — Kitchen & Powder Room"
REFERENCE_DOCUMENT_SHA256 = "5aaabf04cefcd5553aee184bb76cac54db9f0a84a2258995e3de09dd6d4421b9"
GITHUB_ILLUSTRATIONS_SHA256 = "6d1e443eae943847f74a42c34603a594ea2046d2968be87fb3c7df7e71a6b756"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, payload):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def assert_regular(path, *, directory=False):
    info = path.stat(follow_symlinks=False)
    if path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("Reference reset does not follow linked project paths")
    if directory != stat.S_ISDIR(info.st_mode):
        raise ValueError("Unexpected project file type")


def load_manifest(app_root):
    root = (app_root / "reference-demo").resolve()
    path = root / "reference-demo.json"
    assert_regular(path)
    if path.stat().st_size > 128 * 1024:
        raise ValueError("Reference manifest is too large")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "vwc-reference-demo/1" or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", manifest.get("generation", "")):
        raise ValueError("Invalid reference manifest")
    if [section.get("id") for section in manifest.get("sections", [])] != ["A200", "A202"]:
        raise ValueError("Reference sections must be A200 and A202")
    assets = set()
    for section in manifest["sections"]:
        if len(section.get("views", [])) != 5:
            raise ValueError("Each reference packet must have five actual sheets")
        for name in [section["pdf"], section["viewer_html"], *[view["image"] for view in section["views"]]]:
            if not isinstance(name, str) or not re.fullmatch(r"A20[02]-[A-Za-z0-9.-]+\.(pdf|html|png)", name):
                raise ValueError("Invalid reference asset")
            asset = root / name
            assert_regular(asset)
            if asset.resolve().parent != root:
                raise ValueError("Reference asset outside bundle")
            assets.add(name)
    if set(manifest.get("assets", [])) != assets:
        raise ValueError("Reference asset whitelist differs from the displayed views")
    public = {**manifest, "id": REFERENCE_SOURCE_KEY, "title": REFERENCE_PROJECT_NAME,
              "reference_source_key": REFERENCE_SOURCE_KEY}
    public["sections"] = []
    prefix = "/api/studio/reference-demo/assets/"
    for section in manifest["sections"]:
        public["sections"].append({**section, "pdf_url": prefix + section["pdf"],
            "viewer_url": prefix + section["viewer_html"],
            "views": [{**view, "image_url": prefix + view["image"]} for view in section["views"]]})
    return public, root, assets


def load_github_sample(app_root):
    """Use only the intentionally staged public seed and its exact source PDF."""
    root = (app_root / "showcase").resolve()
    manifest_path = root / "showcase.json"
    assert_regular(manifest_path)
    if manifest_path.stat().st_size > 128 * 1024:
        raise ValueError("The public sample manifest is too large")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if (manifest.get("schema") != "formtopart-github-sample/1"
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.vwc", manifest.get("archive", ""))
            or not re.fullmatch(r"[a-f0-9]{64}", manifest.get("source_sha256", ""))
            or manifest["source_sha256"] == REFERENCE_DOCUMENT_SHA256
            or not isinstance(manifest.get("material_catalog"), list)
            or len(manifest["material_catalog"]) > 100):
        raise ValueError("The public sample must declare a sanitized source and a bounded material catalog")
    path = root / manifest["archive"]
    assert_regular(path)
    if path.stat().st_size > 50 * 1024 * 1024 or sha(path.read_bytes()) != manifest.get("archive_sha256"):
        raise ValueError("The public sample archive differs from its release manifest")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) != 2 or sum(item.file_size for item in entries) > 100 * 1024 * 1024:
            raise ValueError("The public sample must contain only its project and one source PDF")
        payload = json.loads(archive.read("project.json"))
        documents = payload.get("documents", [])
        if payload.get("schema") != "vwc-studio-project/1" or len(documents) != 1:
            raise ValueError("The public sample must contain exactly one project source")
        document = documents[0]
        document_id = document.get("id", "")
        asset = document.get("asset", "")
        if (not re.fullmatch(r"DOC_[a-f0-9]{32}", document_id)
                or asset != f"sources/{document_id}.pdf"
                or set(archive.namelist()) != {"project.json", asset}
                or document.get("sha256") != manifest["source_sha256"]
                or sha(archive.read(asset)) != manifest["source_sha256"]):
            raise ValueError("The public sample source differs from its sanitized release source")
    return manifest, path


def legacy_github_sample_document(documents):
    return next((doc for doc in documents if doc.get("sha256") == GITHUB_ILLUSTRATIONS_SHA256
                 and doc.get("id") == "DOC_" + GITHUB_ILLUSTRATIONS_SHA256[:32]
                 and doc.get("media_type") == "application/pdf" and doc.get("page_count") == 3), None)


def _uses_illustration_region(value, document_id):
    if isinstance(value, dict):
        return ((value.get("document_id") == document_id and value.get("region") is not None)
                or any(_uses_illustration_region(child, document_id) for child in value.values()))
    if isinstance(value, list):
        return any(_uses_illustration_region(child, document_id) for child in value)
    return False


def upgrade_github_sample_source(repository, item, github_seed):
    """Refresh the illustrative seed document, preserving every saved revision."""
    from .documents import prepare_document_assets, source_suffix
    from .paths import filesystem_path

    manifest, archive_path = github_seed
    new_digest = manifest["source_sha256"]
    legacy = legacy_github_sample_document(item["documents"])
    if legacy is None or any(doc["sha256"] == new_digest for doc in item["documents"]):
        return item

    project_id = item["id"]
    root = repository.directory(project_id)
    original = filesystem_path(legacy["local_path"])
    with repository.connect(project_id) as connection:
        connection.execute("BEGIN IMMEDIATE")
        documents = [json.loads(row[0]) for row in connection.execute("SELECT metadata FROM documents")]
        if legacy not in documents or any(doc["sha256"] == new_digest for doc in documents):
            return repository.get(project_id)
        if (not original.is_relative_to(root) or not original.is_file()
                or sha(original.read_bytes()) != legacy["sha256"]):
            return item

        # User-generated drawings may rely on the old PDF bytes or coordinate
        # regions. Keep that document reachable when saved evidence needs it.
        retained = any((root / folder).exists() for folder in ("workflow-state", "workflow-runs"))
        if not retained:
            rows = connection.execute("SELECT model FROM revisions UNION ALL SELECT model FROM proposals "
                                      "UNION ALL SELECT data FROM jobs")
            retained = any(legacy["sha256"] in row[0] or _uses_illustration_region(json.loads(row[0]), legacy["id"])
                           for row in rows)

        with zipfile.ZipFile(archive_path) as archive:
            descriptor, = json.loads(archive.read("project.json"))["documents"]
            content = archive.read(descriptor["asset"])
        if sha(content) != new_digest:
            raise ValueError("The replacement PDF differs from its release manifest")
        doc_id = "DOC_" + uuid4().hex if retained else legacy["id"]
        directory = root / "sources" / f"{doc_id}-{uuid4().hex}"
        if not directory.resolve().is_relative_to(root):
            raise ValueError("The replacement source folder is outside the local project")
        name = descriptor["name"]
        suffix = source_suffix(name, content)
        with prepare_document_assets(directory, doc_id, name, content, suffix, new_digest) as metadata:
            if metadata["page_count"] != legacy["page_count"]:
                raise ValueError("The PDF page count changed and would invalidate saved references")
            if retained:
                connection.execute("INSERT INTO documents (rowid, id, metadata) VALUES "
                                   "((SELECT MIN(rowid)-1 FROM documents), ?, ?)", (doc_id, encode(metadata)))
            else:
                connection.execute("UPDATE documents SET metadata=? WHERE id=?", (encode(metadata), doc_id))
            connection.commit()
    return repository.get(project_id)


def saved_rows(connection):
    return {"revisions": connection.execute("SELECT revision,model,summary,created_at FROM revisions ORDER BY revision").fetchall(),
            "documents": connection.execute("SELECT id,metadata FROM documents ORDER BY id").fetchall()}


def rows_hash(rows):
    return sha(json.dumps({key: [tuple(row) for row in values] for key, values in rows.items()},
                          ensure_ascii=False, separators=(",", ":")).encode())


class OrdinaryReferenceProfile:
    """One-time ordinary project seeding/adoption; never retires other projects.

    The old reset journal is read only as provenance. A separate durable marker
    prevents deletion from becoming an implicit instruction to recreate a project.
    A fresh seed reserves its ID before import, so interrupted publication can be
    resumed without duplicate projects or replacing a deletion tombstone.
    """
    def __init__(self, repository, generation):
        self.repository = repository
        self.generation = generation
        self.control = None
        self.record = None

    def __enter__(self):
        assert_regular(self.repository.root, directory=True)
        database = self.repository.root / "_profile.sqlite"
        if database.exists():
            assert_regular(database)
        self.control = sqlite3.connect(database, timeout=90)
        self.control.execute("CREATE TABLE IF NOT EXISTS ordinary_reference_projects(source_key TEXT PRIMARY KEY,data TEXT NOT NULL)")
        self.control.commit()
        self.control.execute("BEGIN IMMEDIATE")
        self._reload()
        return self

    def __exit__(self, kind, error, traceback):
        if self.control is not None:
            self.control.rollback()
            self.control.close()

    def _reload(self):
        row = self.control.execute("SELECT data FROM ordinary_reference_projects WHERE source_key=?", (REFERENCE_SOURCE_KEY,)).fetchone()
        self.record = json.loads(row[0]) if row else None
        if self.record is not None:
            if (not isinstance(self.record, dict)
                    or self.record.get("status") not in {"seed-pending", "complete"}
                    or self.record.get("source_key") != REFERENCE_SOURCE_KEY
                    or self.record.get("generation") != self.generation
                    or (self.record.get("project_id") is not None
                        and (not isinstance(self.record["project_id"], str)
                             or not re.fullmatch(r"[a-f0-9]{32}", self.record["project_id"])))):
                raise ValueError("Invalid ordinary reference project record")

    def _save(self, *, durable=False):
        self.control.execute("INSERT OR REPLACE INTO ordinary_reference_projects VALUES(?,?)",
                             (REFERENCE_SOURCE_KEY, encode(self.record)))
        if durable:
            self.control.commit()
            self.control.execute("BEGIN IMMEDIATE")
            # Another startup may have completed the same reserved seed while
            # the transaction lock was reacquired. Always use its latest record.
            self._reload()

    def existing(self, project_id):
        if not project_id:
            return None
        directory = self.repository.directory(project_id)
        if not directory.exists():
            return None
        assert_regular(directory, directory=True)
        assert_regular(directory / "project.sqlite")
        try:
            return self.repository.get(project_id)
        except NotFound:
            return None

    def legacy_project_id(self):
        table = self.control.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reference_resets'").fetchone()
        candidate = None
        if table:
            row = self.control.execute("SELECT data FROM reference_resets WHERE generation=?", (self.generation,)).fetchone()
            if row:
                data = json.loads(row[0])
                if data.get("status") == "complete":
                    candidate = data.get("canonical_id")
        journal = self.repository.root / "_reference-demo-reset.json"
        if candidate is None and journal.is_file():
            assert_regular(journal)
            data = json.loads(journal.read_text(encoding="utf-8"))
            if data.get("generation") == self.generation and data.get("status") == "complete":
                candidate = data.get("canonical_id")
        if candidate is not None and (not isinstance(candidate, str) or not re.fullmatch(r"[a-f0-9]{32}", candidate)):
            raise ValueError("Invalid previous reference project identity")
        return candidate

    def plan(self):
        if self.record is not None:
            return self.record
        # Prefer a completed older generation's identity, including a tombstone.
        # Deletion of that project never makes this profile eligible for seeding.
        candidate_id = self.legacy_project_id()
        if candidate_id is None:
            candidate = next((item for item in self.repository.list()
                              if item.get("reference_source_key") == REFERENCE_SOURCE_KEY
                              or (item.get("is_demo") and item.get("demo_key") == DEMO_KEY)), None)
            candidate_id = candidate["id"] if candidate else None
        if candidate_id:
            self.record = {"source_key": REFERENCE_SOURCE_KEY, "generation": self.generation,
                           "project_id": candidate_id, "status": "complete", "outcome": "existing-project",
                           "handled_at": now()}
            return self.record
        has_projects = any(re.fullmatch(r"[a-f0-9]{32}", path.name) for path in self.repository.root.iterdir())
        self.record = {"source_key": REFERENCE_SOURCE_KEY, "generation": self.generation,
                       "project_id": None if has_projects else uuid4().hex,
                       "status": "complete" if has_projects else "seed-pending",
                       "outcome": "existing-profile-preserved" if has_projects else "fresh-profile-seed",
                       "handled_at": now()}
        # Fresh seed intent must survive a crash before/after import publication.
        # Nonempty profiles simply get a marker and are otherwise untouched.
        self._save(durable=True)
        return self.record

    def complete(self, project_id):
        if self.record.get("status") == "complete" and self.record.get("project_id") == project_id and self.record.get("completed_at"):
            self.control.commit()
            return self.record
        self.record.update(project_id=project_id, status="complete", completed_at=now())
        self._save()
        self.control.commit()
        return self.record


class ProfileReset:
    """Serializes startup resets; backups/journal persist before any retirement."""
    def __init__(self, repository, generation):
        self.repository = repository
        self.generation = generation
        self.journal = repository.root / "_reference-demo-reset.json"
        self.control = None
        self.state = None
        self.completed = None

    def __enter__(self):
        assert_regular(self.repository.root, directory=True)
        self.control = sqlite3.connect(self.repository.root / "_profile.sqlite", timeout=90)
        self.control.execute("CREATE TABLE IF NOT EXISTS reference_resets(generation TEXT PRIMARY KEY,data TEXT NOT NULL)")
        self.control.commit()
        self.control.execute("BEGIN IMMEDIATE")
        row = self.control.execute("SELECT data FROM reference_resets WHERE generation=?", (self.generation,)).fetchone()
        if row:
            self.completed = json.loads(row[0])
        return self

    def __exit__(self, kind, error, traceback):
        if self.control is not None:
            self.control.rollback()
            self.control.close()

    def directories(self):
        result = []
        for path in self.repository.root.iterdir():
            if re.fullmatch(r"[a-f0-9]{32}", path.name):
                assert_regular(path, directory=True)
                assert_regular(path / "project.sqlite")
                result.append(path)
        return sorted(result)

    def backup_project(self, path, recovery):
        target = recovery / "projects" / path.name
        if target.exists():
            # A crash may leave an unjournaled partial or complete copy. Keep it
            # intact and record a new verified copy instead of getting stuck or
            # overwriting possible recovery material.
            target = recovery / "supplemental" / uuid4().hex / "projects" / path.name
        target.mkdir(parents=True, exist_ok=False)
        # Consistent SQLite copy, including any committed WAL pages, rather than
        # copying a live database file and silently losing its recent changes.
        with self.repository.connect(path.name) as source:
            before = saved_rows(source)
            with closing(sqlite3.connect(target / "project.sqlite")) as destination:
                source.backup(destination)
                if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise ValueError("Project recovery copy failed its SQLite check")
                if rows_hash(saved_rows(destination)) != rows_hash(before):
                    raise ValueError("Project recovery data does not match the original")
        files = []
        queue = [path]
        while queue:
            directory = queue.pop()
            assert_regular(directory, directory=True)
            for child in directory.iterdir():
                if child.name in {"project.sqlite", "project.sqlite-wal", "project.sqlite-shm", "project.sqlite-journal"} and child.parent == path:
                    continue
                assert_regular(child, directory=child.is_dir())
                if child.is_dir():
                    queue.append(child)
                else:
                    relative = child.relative_to(path)
                    copied = target / relative
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    before_hash = sha(child.read_bytes())
                    shutil.copy2(child, copied)
                    if sha(copied.read_bytes()) != before_hash or sha(child.read_bytes()) != before_hash:
                        raise ValueError("Project assets changed during the recovery snapshot")
                    files.append({"path": relative.as_posix(), "sha256": before_hash, "bytes": child.stat().st_size})
        return {"id": path.name, "backup_relative": str(target.relative_to(recovery)),
                "saved_rows_sha256": rows_hash(before),
                "latest_model_sha256": sha(before["revisions"][-1][1].encode()),
                "backup_database_sha256": sha((target / "project.sqlite").read_bytes()), "assets": files}

    def prepare(self):
        if self.journal.is_file():
            assert_regular(self.journal)
            candidate = json.loads(self.journal.read_text(encoding="utf-8"))
            if candidate.get("generation") == self.generation:
                recovery = (self.repository.root.parent / candidate["recovery_relative"]).resolve()
                expected = (self.repository.root.parent / "profile-recovery" / self.generation).resolve()
                if not recovery.is_relative_to(expected):
                    raise ValueError("Invalid reference recovery location")
                assert_regular(recovery, directory=True)
                self.state = candidate
        if self.state is None:
            recovery = self.repository.root.parent / "profile-recovery" / self.generation / uuid4().hex
            recovery.mkdir(parents=True)
            # Do not change any old database until every old project is backed up.
            projects = [self.backup_project(path, recovery) for path in self.directories()]
            self.state = {"generation": self.generation, "started_at": now(),
                "recovery_relative": str(recovery.relative_to(self.repository.root.parent)),
                "projects": projects, "canonical_id": None, "status": "backed-up"}
            atomic_json(recovery / "snapshot.json", self.state)
            atomic_json(self.journal, self.state)
        return self.state

    def finish(self, canonical):
        recovery = (self.repository.root.parent / self.state["recovery_relative"]).resolve()
        canonical_id = canonical["id"]
        self.state["canonical_id"] = canonical_id
        atomic_json(self.journal, self.state)
        # An interrupted prior seed or an older concurrently open app may have
        # created another project. Back it up before including it in this reset.
        original_ids = {item["id"] for item in self.state["projects"]}
        for path in self.directories():
            if path.name != canonical_id and path.name not in original_ids:
                self.state["projects"].append(self.backup_project(path, recovery))
        atomic_json(recovery / "snapshot.json", self.state)
        atomic_json(self.journal, self.state)
        # Validate all prior snapshots before retiring even the first project.
        for item in self.state["projects"]:
            if item["id"] == canonical_id:
                continue
            backup_directory = (recovery / item.get("backup_relative", "projects/" + item["id"])).resolve()
            if not backup_directory.is_relative_to(recovery):
                raise ValueError("Recovery project outside its snapshot")
            backup = backup_directory / "project.sqlite"
            assert_regular(backup)
            if sha(backup.read_bytes()) != item["backup_database_sha256"]:
                raise ValueError("Recovery database identity changed; reset stopped")
            with self.repository.connect(item["id"]) as connection:
                if rows_hash(saved_rows(connection)) != item["saved_rows_sha256"]:
                    raise ValueError("Project changed after its recovery snapshot; reset stopped")
        for item in self.state["projects"]:
            if item["id"] == canonical_id:
                continue
            with self.repository.connect(item["id"]) as connection:
                connection.execute("BEGIN IMMEDIATE")
                state = self.repository._state(connection)
                if not state.get("deleted_at"):
                    state.update(deleted_at=now(), lifecycle="stopped", lifecycle_epoch=state["lifecycle_epoch"] + 1,
                                 lifecycle_updated_at=now(), retired_by_reset=self.generation)
                    self.repository._save_state(connection, state)
                    self.repository._cancel_jobs(connection, "deleted")
                connection.commit()
        self.state.update(status="complete", completed_at=now())
        atomic_json(recovery / "snapshot.json", self.state)
        atomic_json(self.journal, self.state)
        self.control.execute("INSERT OR REPLACE INTO reference_resets VALUES(?,?)", (self.generation, encode(self.state)))
        self.control.commit()
        return self.state
