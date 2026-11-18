"""Versioned standards-skill updates; evidence truth remains a review duty."""
import argparse
import hashlib
import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path


def managed(root):
    result = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in {"__pycache__", ".git"} for part in relative.parts):
            continue
        if relative.parts[0] == "learning" and (len(relative.parts) < 2 or relative.parts[1] != "records"):
            continue
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in managed files")
        if path.is_file():
            result[relative.as_posix()] = path.read_bytes()
    return result


def fingerprint(root):
    digest = hashlib.sha256()
    for name, content in sorted(managed(root).items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def lesson_check(lesson):
    required = ("id", "scope", "observation", "cause", "proposed_rule", "evidence", "limitations", "verification", "basis", "status", "behavioral_change", "visual_change")
    for key in required:
        if key not in lesson:
            raise ValueError("Missing lesson field: " + key)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", lesson["id"]):
        raise ValueError("Invalid lesson ID")
    if lesson["scope"] not in {"interpretation", "preference"}:
        raise ValueError("Project facts cannot enter shared learning")
    for key in ("evidence", "limitations"):
        if not isinstance(lesson[key], list) or not lesson[key] or not all(isinstance(x, str) and x.strip() for x in lesson[key]):
            raise ValueError(f"Non-empty {key} required")
    for key in ("observation", "cause", "proposed_rule"):
        if not isinstance(lesson[key], str) or not lesson[key].strip():
            raise ValueError("Empty lesson field: " + key)
    if lesson["status"] not in {"candidate", "adopted"} or lesson["basis"] not in {"verified-correction", "explicit-user-preference"}:
        raise ValueError("Invalid lesson status/basis")
    if any(type(lesson[key]) is not bool for key in ("behavioral_change", "visual_change")):
        raise ValueError("Change flags must be boolean")
    checks = lesson["verification"]
    if any(checks.get(key) not in {"passed", "pending", "failed", "not-applicable"} for key in ("regression", "visual", "instruction_review")):
        raise ValueError("Invalid verification status")
    if checks["instruction_review"] != "passed":
        raise ValueError("Instruction review required")
    if lesson["behavioral_change"] and checks["regression"] != "passed":
        raise ValueError("Behavioral regression evidence required")
    if lesson["visual_change"] and checks["visual"] != "passed":
        raise ValueError("Rendered visual evidence required")


def validate(root):
    files = managed(root)
    entry = files.get("SKILL.md", b"").decode("utf-8").replace("\r\n", "\n")
    if not entry.startswith("---\n") or "name: interior-drawing-standards" not in entry or "description:" not in entry:
        raise ValueError("Invalid skill frontmatter")
    for name, content in files.items():
        if name.endswith(".md"):
            for target in re.findall(r"\]\(([^)]+)\)", content.decode("utf-8")):
                if "://" in target or target.startswith("#"):
                    continue
                linked = (root / name).parent.joinpath(target.split("#")[0]).resolve()
                if not linked.is_relative_to(root.resolve()) or not linked.is_file():
                    raise ValueError("Broken or external local link: " + target)
        if name.startswith("learning/records/") and name.endswith(".json"):
            lesson_check(json.loads(content))
    return len(files)


def replace_files(root, files):
    for name in set(managed(root)) - set(files):
        (root / name).unlink()
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def update(root, staged, expected, lesson=None):
    root, staged = root.resolve(), staged.resolve()
    if root == staged or staged.is_relative_to(root) or root.is_relative_to(staged):
        raise ValueError("Staging must be separate from installed skill")
    learning = root / "learning"
    learning.mkdir(exist_ok=True)
    lock = learning / "update.lock"
    with lock.open("x") as handle:
        handle.write("Inspect snapshot before recovering an interrupted update.\n")
    try:
        if fingerprint(root) != expected:
            raise ValueError("Concurrent change: stale fingerprint")
        validate(staged)
        if lesson is not None:
            lesson_check(lesson)
        previous = managed(root)
        following = managed(staged)
        if lesson is not None:
            for name, content in previous.items():
                if name.startswith("learning/records/"):
                    if name in following and following[name] != content:
                        raise ValueError("Existing evidence record cannot be rewritten")
                    following[name] = content
            adopted = dict(lesson, status="adopted")
            key = "learning/records/" + adopted["id"] + ".json"
            if key in following:
                raise ValueError("Lesson ID already exists")
            following[key] = (json.dumps(adopted, ensure_ascii=False, indent=2) + "\n").encode()
        version = uuid.uuid4().hex
        snapshot = learning / "versions" / version
        snapshot.mkdir(parents=True)
        for name, content in previous.items():
            path = snapshot / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        try:
            replace_files(root, following)
            validate(root)
        except BaseException:
            replace_files(root, previous)
            raise
        return version
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["fingerprint", "validate", "apply", "rollback"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--staged", type=Path)
    parser.add_argument("--expected")
    parser.add_argument("--lesson", type=Path)
    parser.add_argument("--version")
    args = parser.parse_args()
    if args.command == "fingerprint":
        print(fingerprint(args.root))
    elif args.command == "validate":
        print("Validated files:", validate(args.root))
    elif args.command == "apply":
        if not all((args.staged, args.expected, args.lesson)):
            parser.error("apply requires --staged, --expected and --lesson")
        print("Previous version:", update(args.root, args.staged, args.expected, json.loads(args.lesson.read_text(encoding="utf-8"))))
    else:
        if not args.expected or not args.version or not re.fullmatch("[a-f0-9]{32}", args.version):
            parser.error("rollback requires --expected and a valid --version")
        source = args.root / "learning" / "versions" / args.version
        if not source.is_dir():
            raise ValueError("Unknown version")
        with tempfile.TemporaryDirectory() as directory:
            staged = Path(directory) / "restore"
            shutil.copytree(source, staged)
            print("Pre-rollback version:", update(args.root, staged, args.expected))


if __name__ == "__main__":
    main()
