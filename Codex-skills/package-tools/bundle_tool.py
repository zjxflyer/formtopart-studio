"""Portable, guarded skill-bundle packaging and transactional installation.

Only Python's standard library is required. Managed fingerprints intentionally
match the established path/NUL/content-SHA256 algorithm. No registry is edited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA = 1
ALGORITHM = "managed-path-sha256-v1"
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
HEX = re.compile(r"[a-f0-9]{64}\Z")
IGNORE = {"__pycache__", ".git"}
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, value: Any) -> None:
    """Durably replace a journal; callers own its exclusive transaction lock."""
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _no_link(path: Path) -> None:
    """Reject symlinks, junctions, and other Windows reparse-point redirects."""
    if not _exists(path):
        return
    information = path.lstat()
    reparse = getattr(information, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(information.st_mode) or reparse:
        raise ValueError(f"Linked/reparse paths are not allowed: {path}")


def _absolute(path: Path) -> Path:
    candidate = Path(os.path.abspath(path))
    if os.name == "nt" and not str(candidate).startswith("\\\\?\\"):
        # Windows installations commonly contain long skill/reference paths.
        # Extended absolute paths avoid the legacy MAX_PATH restriction.
        value = str(candidate)
        candidate = Path("\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value)
    # Check before resolve(), which would otherwise hide an ancestor redirect.
    for ancestor in reversed((candidate, *candidate.parents)):
        _no_link(ancestor)
    return candidate.resolve(strict=False)


def _separate(*paths: Path) -> None:
    for index, left in enumerate(paths):
        for right in paths[index + 1:]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                raise ValueError(f"Paths must not overlap: {left} / {right}")


def _names(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("canonical_skill_names must be a nonempty list")
    if not all(isinstance(item, str) and NAME.fullmatch(item) and item.upper() not in RESERVED for item in value):
        raise ValueError("Skill names must be safe lowercase hyphenated identifiers")
    if len(value) != len(set(item.casefold() for item in value)):
        raise ValueError("Duplicate skill names are not allowed")
    return tuple(value)


def _relative(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError(f"Unsafe manifest path: {value!r}")
    parts = value.split("/")
    if any(not part or part in {".", ".."} or part.rstrip(" .") != part or part.split(".")[0].upper() in RESERVED for part in parts):
        raise ValueError(f"Unsafe manifest path: {value!r}")
    if PurePosixPath(value).is_absolute() or PurePosixPath(value).as_posix() != value:
        raise ValueError(f"Unsafe manifest path: {value!r}")
    return value


def _walk(root: Path, *, managed_only: bool = False, bundle: bool = False) -> dict[str, Path]:
    _no_link(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    result: dict[str, Path] = {}
    seen: set[str] = set()

    def visit(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda path: path.name):
            _no_link(child)
            relative = child.relative_to(root).as_posix()
            parts = relative.split("/")
            if (managed_only or bundle) and any(part in IGNORE for part in parts):
                continue
            if managed_only and parts[0] == "learning":
                if len(parts) > 1 and parts[1] in {"versions", "candidates"}:
                    continue
                if child.name == "update.lock":
                    continue
            if child.is_dir():
                visit(child)
            elif child.is_file():
                _relative(relative)
                if relative.casefold() in seen:
                    raise ValueError(f"Case-colliding paths are not portable: {relative}")
                seen.add(relative.casefold())
                result[relative] = child
            else:
                raise ValueError(f"Unsupported filesystem object: {child}")

    visit(root)
    return result


def managed(root: Path) -> dict[str, Path]:
    return _walk(root, managed_only=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative, path in sorted(managed(root).items()):
        digest.update(relative.encode("utf-8") + b"\0" + bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def bundle_fingerprint(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(entries, key=lambda entry: entry["path"]):
        digest.update(item["path"].encode("utf-8") + b"\0" + bytes.fromhex(item["sha256"]))
    return digest.hexdigest()


def _entries(root: Path, *, bundle: bool = False) -> list[dict[str, Any]]:
    return [
        {"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for relative, path in sorted(_walk(root, bundle=bundle).items())
        if not (bundle and relative == "manifest.json")
    ]


def _copy_managed(source: Path, target: Path) -> None:
    target.mkdir()
    for relative, source_file in managed(source).items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination)


def freeze(snapshot: Path, source_root: Path, spec: dict[str, Any]) -> dict[str, Any]:
    snapshot, source_root = _absolute(snapshot), _absolute(source_root)
    names = _names(spec.get("canonical_skill_names"))
    # Canonical skills and frozen packages commonly share one parent directory.
    # Guard actual source trees rather than rejecting that valid sibling layout.
    for name in names:
        _separate(snapshot, source_root / name)
    if not isinstance(spec.get("name"), str) or not spec["name"].strip():
        raise ValueError("A nonempty bundle name is required")
    if not isinstance(spec.get("created"), str) or not spec["created"].strip():
        raise ValueError("An explicit created date/time is required")
    if _exists(snapshot / "manifest.json") or _exists(snapshot / "skills"):
        raise ValueError("Snapshot is already frozen or contains reserved skills/; never overwrite it")
    # Validate every source before creating package files.
    for name in names:
        files = managed(source_root / name)
        if "SKILL.md" not in files:
            raise ValueError(f"Skill has no SKILL.md: {name}")
    snapshot.mkdir(parents=True, exist_ok=True)
    _walk(snapshot, bundle=True)
    freeze_lock = snapshot.parent / f".{snapshot.name}.freeze.lock"
    descriptor = os.open(freeze_lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    stage = snapshot.parent / f".{snapshot.name}.freeze-stage-{uuid.uuid4().hex}"
    installed = False
    try:
        # Recheck after acquiring the lock.
        if _exists(snapshot / "manifest.json") or _exists(snapshot / "skills"):
            raise ValueError("Snapshot became frozen concurrently")
        stage.mkdir()
        records: dict[str, Any] = {}
        for name in names:
            _copy_managed(source_root / name, stage / name)
            records[name] = {"fingerprint": fingerprint(stage / name), "managed_file_count": len(managed(stage / name))}
        stage.rename(snapshot / "skills")
        installed = True
        entries = _entries(snapshot, bundle=True)
        manifest = {
            "schema_version": SCHEMA,
            "name": spec["name"],
            "created": spec["created"],
            "status": "frozen-restoration-point",
            "fingerprint_algorithm": ALGORITHM,
            "canonical_skill_names": list(names),
            "skills": records,
            "files": entries,
            "bundle_fingerprint": bundle_fingerprint(entries),
        }
        # The manifest is the commit marker; exclusive creation forbids overwrite.
        with (snapshot / "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        verify(snapshot)
        return manifest
    except BaseException:
        # Once the commit marker exists, leave the failed snapshot for inspection.
        if installed and not _exists(snapshot / "manifest.json"):
            _remove_tree(snapshot / "skills")
        raise
    finally:
        if stage.exists():
            _remove_tree(stage)
        freeze_lock.unlink(missing_ok=True)


def verify(snapshot: Path, expected_bundle_fingerprint: str | None = None) -> dict[str, Any]:
    snapshot = _absolute(snapshot)
    _no_link(snapshot / "manifest.json")
    manifest = _json(snapshot / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA or manifest.get("fingerprint_algorithm") != ALGORITHM:
        raise ValueError("Unsupported bundle manifest/algorithm")
    names = _names(manifest.get("canonical_skill_names"))
    records, entries = manifest.get("skills"), manifest.get("files")
    if not isinstance(records, dict) or set(records) != set(names) or not isinstance(entries, list):
        raise ValueError("Invalid skills/files in bundle manifest")
    listed: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Invalid file record")
        relative = _relative(item.get("path"))
        if relative == "manifest.json" or relative.casefold() in seen:
            raise ValueError("Duplicate/reserved manifest file record")
        if not isinstance(item.get("sha256"), str) or not HEX.fullmatch(item["sha256"]):
            raise ValueError(f"Invalid file hash: {relative}")
        if type(item.get("bytes")) is not int or item["bytes"] < 0:
            raise ValueError(f"Invalid file size: {relative}")
        seen.add(relative.casefold())
        listed[relative] = item
    actual_entries = _entries(snapshot, bundle=True)
    actual = {item["path"]: item for item in actual_entries}
    if set(actual) != set(listed):
        raise ValueError(f"Bundle file set mismatch: missing={sorted(set(listed)-set(actual))}, extra={sorted(set(actual)-set(listed))}")
    for relative, item in listed.items():
        if actual[relative] != item:
            raise ValueError(f"Bundle file hash/size mismatch: {relative}")
    actual_fingerprint = bundle_fingerprint(entries)
    if manifest.get("bundle_fingerprint") != actual_fingerprint:
        raise ValueError("Bundle fingerprint mismatch")
    if expected_bundle_fingerprint is not None and actual_fingerprint != expected_bundle_fingerprint:
        raise ValueError("Bundle does not match the externally expected fingerprint")
    skill_root = snapshot / "skills"
    _no_link(skill_root)
    if not skill_root.is_dir() or {path.name for path in skill_root.iterdir()} != set(names):
        raise ValueError("Packaged skills differ from declared skill names")
    for name in names:
        record = records[name]
        if not isinstance(record, dict) or fingerprint(skill_root / name) != record.get("fingerprint"):
            raise ValueError(f"Skill fingerprint mismatch: {name}")
        if len(managed(skill_root / name)) != record.get("managed_file_count") or not (skill_root / name / "SKILL.md").is_file():
            raise ValueError(f"Skill file count/entrypoint mismatch: {name}")
    return manifest


def _current(names: tuple[str, ...], target_root: Path) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in names:
        root = target_root / name
        _no_link(root)
        result[name] = fingerprint(root) if root.exists() else None
    return result


def current(snapshot: Path, target_root: Path) -> dict[str, str | None]:
    manifest = verify(snapshot)
    target_root = _absolute(target_root)
    _separate(_absolute(snapshot), target_root)
    return _current(_names(manifest["canonical_skill_names"]), target_root)


def _lock_path(target_root: Path) -> Path:
    return target_root.parent / f".{target_root.name}.drawing-bundle-transaction.lock"


def _check_skill_locks(names: tuple[str, ...], target_root: Path) -> None:
    for name in names:
        if _exists(target_root / name / "learning" / "update.lock"):
            raise ValueError(f"Active/interrupted skill update: {name}")


def _remove_tree(path: Path) -> None:
    # Every recursive removal is limited to an explicitly validated tree.
    _walk(path)
    shutil.rmtree(path)


def _move(source: Path, destination: Path) -> None:
    """Same-parent filesystem rename; isolated for rollback fault-injection tests."""
    source.rename(destination)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return True
    if os.name == "nt":
        # os.kill(pid, 0) is not a portable read-only probe on Windows.
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            # Access denied is treated conservatively as a live owner.
            return ctypes.get_last_error() != 87  # INVALID_PARAMETER: no such PID
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _validated_journal(journal: Any, target_root: Path) -> tuple[dict[str, Any], tuple[str, ...], Path, Path, Path]:
    if not isinstance(journal, dict) or journal.get("schema_version") != SCHEMA:
        raise ValueError("Invalid transaction journal; preserve it for manual inspection")
    if _absolute(Path(journal.get("target_root", ""))) != target_root:
        raise ValueError("Transaction journal target mismatch")
    transaction = journal.get("transaction_id", "")
    if not isinstance(transaction, str) or not re.fullmatch(r"[a-f0-9]{32}", transaction):
        raise ValueError("Invalid transaction ID")
    if type(journal.get("owner_pid")) is not int or journal["owner_pid"] <= 0:
        raise ValueError("Invalid transaction owner PID")
    names = _names(journal.get("canonical_skill_names"))
    stage = _absolute(Path(journal.get("stage_root", "")))
    swap = _absolute(Path(journal.get("swap_root", "")))
    backup = _absolute(Path(journal.get("backup_root", "")))
    if stage != target_root.parent / f".drawing-bundle-stage-{transaction}" or swap != target_root.parent / f".drawing-bundle-old-{transaction}":
        raise ValueError("Unsafe transaction staging paths")
    _separate(target_root, stage, swap, backup)
    if set(journal.get("expected", {})) != set(names) or set(journal.get("wanted", {})) != set(names):
        raise ValueError("Incomplete transaction fingerprints")
    return journal, names, stage, swap, backup


def _rollback(journal: dict[str, Any], target_root: Path) -> None:
    journal, names, stage, swap, _ = _validated_journal(journal, target_root)
    for name in reversed(names):
        target, original = target_root / name, swap / name
        expected, wanted = journal["expected"][name], journal["wanted"][name]
        if original.exists():
            if fingerprint(original) != expected:
                raise ValueError(f"Rollback original was changed: {name}; transaction lock retained")
            if target.exists():
                if fingerprint(target) != wanted:
                    raise ValueError(f"Rollback target changed unexpectedly: {name}; transaction lock retained")
                _remove_tree(target)
            _move(original, target)
        elif expected is None:
            if target.exists():
                if fingerprint(target) != wanted:
                    raise ValueError(f"Fresh installation changed unexpectedly: {name}; transaction lock retained")
                _remove_tree(target)
        elif not target.exists() or fingerprint(target) != expected:
            raise ValueError(f"Cannot establish original state for {name}; backup and lock retained")
    if _current(names, target_root) != journal["expected"]:
        raise ValueError("Rollback fingerprints do not match original state")
    for temporary in (stage, swap):
        if temporary.exists():
            _remove_tree(temporary)


def apply(snapshot: Path, target_root: Path, expected: dict[str, str | None], backup_root: Path, *, expected_bundle_fingerprint: str | None = None) -> dict[str, Any]:
    snapshot, target_root, backup_root = _absolute(snapshot), _absolute(target_root), _absolute(backup_root)
    _separate(snapshot, target_root, backup_root)
    manifest = verify(snapshot, expected_bundle_fingerprint)
    names = _names(manifest["canonical_skill_names"])
    if not isinstance(expected, dict) or set(expected) != set(names) or any(value is not None and (not isinstance(value, str) or not HEX.fullmatch(value)) for value in expected.values()):
        raise ValueError("Expected fingerprints must exactly map declared skill names to SHA256 or null")
    if backup_root.exists():
        raise ValueError("Backup path already exists; choose a new path")
    if not target_root.parent.is_dir():
        raise ValueError("Target parent directory must already exist")
    _check_skill_locks(names, target_root)
    if _current(names, target_root) != expected:
        raise ValueError("Stale expected fingerprints; no installation performed")
    # Backup copies include all history, but never silently follow links.
    for name in names:
        if (target_root / name).exists():
            _walk(target_root / name)
    lock = _lock_path(target_root)
    transaction = uuid.uuid4().hex
    stage = target_root.parent / f".drawing-bundle-stage-{transaction}"
    swap = target_root.parent / f".drawing-bundle-old-{transaction}"
    _separate(snapshot, target_root, backup_root, stage, swap)
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    journal = {
        "schema_version": SCHEMA, "transaction_id": transaction, "phase": "preparing",
        "owner_pid": os.getpid(),
        "target_root": str(target_root), "snapshot": str(snapshot), "backup_root": str(backup_root),
        "stage_root": str(stage), "swap_root": str(swap), "canonical_skill_names": list(names),
        "expected": expected, "wanted": {name: manifest["skills"][name]["fingerprint"] for name in names},
    }
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(journal, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    mutation_started = False
    try:
        _check_skill_locks(names, target_root)
        if _current(names, target_root) != expected:
            raise ValueError("Concurrent change after transaction lock acquisition")
        backup_root.mkdir(parents=True)
        backup_entries: dict[str, Any] = {}
        stage.mkdir()
        swap.mkdir()
        for name in names:
            old = target_root / name
            if old.exists():
                shutil.copytree(old, backup_root / name)
                original_entries = _entries(old)
                if _entries(backup_root / name) != original_entries:
                    raise ValueError(f"Full backup verification failed: {name}")
                backup_entries[name] = original_entries
            shutil.copytree(snapshot / "skills" / name, stage / name)
            for folder in ("versions", "candidates"):
                history = backup_root / name / "learning" / folder
                if history.is_dir():
                    shutil.copytree(history, stage / name / "learning" / folder)
            if fingerprint(stage / name) != journal["wanted"][name]:
                raise ValueError(f"Staged fingerprint mismatch: {name}")
        _write_json(backup_root / "backup-manifest.json", {"transaction_id": transaction, "original_fingerprints": expected, "full_files": backup_entries})
        verify(snapshot, expected_bundle_fingerprint)
        _check_skill_locks(names, target_root)
        if _current(names, target_root) != expected:
            raise ValueError("Concurrent change immediately before replacement")
        journal["phase"] = "swapping"
        _write_json(lock, journal)
        target_root.mkdir(exist_ok=True)
        mutation_started = True
        for name in names:
            if (target_root / name).exists():
                _move(target_root / name, swap / name)
            _move(stage / name, target_root / name)
        if _current(names, target_root) != journal["wanted"]:
            raise ValueError("Installed fingerprints do not match frozen package")
        journal["phase"] = "committed"
        _write_json(lock, journal)
    except BaseException:
        if mutation_started:
            _rollback(journal, target_root)
        else:
            for temporary in (stage, swap):
                if temporary.exists():
                    _remove_tree(temporary)
        lock.unlink(missing_ok=True)
        raise
    # A verified commit never rolls back because of a cleanup failure.
    cleanup_warnings: list[str] = []
    for temporary in (stage, swap):
        try:
            if temporary.exists():
                _remove_tree(temporary)
        except OSError as error:
            cleanup_warnings.append(str(error))
    if not cleanup_warnings:
        lock.unlink()
    return {"status": "passed", "backup": str(backup_root), "fingerprints": journal["wanted"], "cleanup_warnings": cleanup_warnings}


restore = apply


def recover(target_root: Path) -> dict[str, Any]:
    target_root = _absolute(target_root)
    lock = _lock_path(target_root)
    _no_link(lock)
    if not lock.is_file():
        raise ValueError("No transaction journal exists")
    journal, names, stage, swap, backup = _validated_journal(_json(lock), target_root)
    if _process_alive(journal["owner_pid"]):
        raise ValueError("Transaction owner process is still active; recovery must not interrupt it")
    _check_skill_locks(names, target_root)
    if journal.get("phase") == "committed":
        if _current(names, target_root) != journal["wanted"]:
            raise ValueError("Committed installation has changed; preserve journal and backup")
        for temporary in (stage, swap):
            if temporary.exists():
                _remove_tree(temporary)
        outcome = "committed-cleanup-finished"
    else:
        _rollback(journal, target_root)
        outcome = "original-state-restored"
    lock.unlink()
    return {"status": outcome, "backup": str(backup), "fingerprints": _current(names, target_root)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "verify", "current", "apply", "restore", "recover"))
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--spec", type=Path, help="JSON declaring name, created, canonical_skill_names")
    parser.add_argument("--target-root", type=Path)
    parser.add_argument("--expected", type=Path, help="JSON map from current command, including null for absent skills")
    parser.add_argument("--expected-bundle-fingerprint")
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    required = {
        "freeze": ("snapshot", "source_root", "spec"), "verify": ("snapshot",),
        "current": ("snapshot", "target_root"), "apply": ("snapshot", "target_root", "expected", "backup_root"),
        "restore": ("snapshot", "target_root", "expected", "backup_root"), "recover": ("target_root",),
    }
    for key in required[args.command]:
        if getattr(args, key) is None:
            parser.error(f"{args.command} requires --{key.replace('_', '-')}")
    if args.command == "freeze":
        result = freeze(args.snapshot, args.source_root, _json(args.spec))
    elif args.command == "verify":
        result = verify(args.snapshot, args.expected_bundle_fingerprint)
    elif args.command == "current":
        result = current(args.snapshot, args.target_root)
    elif args.command == "recover":
        result = recover(args.target_root)
    else:
        result = apply(args.snapshot, args.target_root, _json(args.expected), args.backup_root, expected_bundle_fingerprint=args.expected_bundle_fingerprint)
    if args.output:
        _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, FileExistsError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
