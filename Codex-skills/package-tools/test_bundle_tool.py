from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("bundle_tool", HERE / "bundle_tool.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bundle-test-", dir=HERE)
        self.base = Path(self.temporary.name)
        self.source = self.base / "canonical"
        self.snapshot = self.base / "frozen"
        self.target = self.base / "installed"
        self.names = ("drawing-workflow", "example-audit")
        for name in self.names:
            self.put(self.source / name / "SKILL.md", f"name: {name}\nnew instructions\n")
            self.put(self.source / name / "learning/records/current.json", '{"verified": true}\n')
            self.put(self.source / name / "learning/candidates/work.txt", "not managed")
            self.put(self.source / name / "learning/versions/old.txt", "not managed")
            self.put(self.source / name / "learning/update.lock", "not managed")
            self.put(self.source / name / "references/manifest.json", '{"nested": true}')
        self.put(self.snapshot / "README.md", "Restore and cleanup instructions\n")
        self.put(self.snapshot / "handbook/guide.md", "Portable handbook\n")
        self.put(self.snapshot / "evidence/manifest.json", '{"evidence": true}')
        self.spec = {"name": "Effective Version Test", "created": "2026-10-22", "canonical_skill_names": list(self.names)}

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def put(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def freeze(self):
        return tool.freeze(self.snapshot, self.source, self.spec)

    def old_install(self):
        for name in self.names:
            self.put(self.target / name / "SKILL.md", f"old {name}")
            self.put(self.target / name / "learning/records/prior.json", '{"prior": true}')
            self.put(self.target / name / "learning/candidates/local.txt", "local candidate")
            self.put(self.target / name / "learning/versions/local.txt", "local version")
            self.put(self.target / name / "__pycache__/old.pyc", "binary-like history")

    def test_freeze_hashes_docs_nested_manifests_and_managed_records(self):
        manifest = self.freeze()
        paths = {item["path"] for item in manifest["files"]}
        self.assertIn("evidence/manifest.json", paths)
        self.assertIn("skills/example-audit/references/manifest.json", paths)
        self.assertIn("skills/example-audit/learning/records/current.json", paths)
        self.assertIn("handbook/guide.md", paths)
        self.assertNotIn("manifest.json", paths)
        self.assertFalse(any("learning/candidates" in path or "learning/versions" in path or "update.lock" in path for path in paths))
        self.assertEqual(tool.verify(self.snapshot)["bundle_fingerprint"], manifest["bundle_fingerprint"])
        with self.assertRaises(ValueError):
            self.freeze()

    def test_fresh_install_accepts_null(self):
        manifest = self.freeze()
        expected = tool.current(self.snapshot, self.target)
        self.assertEqual(expected, {name: None for name in self.names})
        result = tool.apply(self.snapshot, self.target, expected, self.base / "backup")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(tool.current(self.snapshot, self.target), {name: manifest["skills"][name]["fingerprint"] for name in self.names})
        self.assertFalse(tool._lock_path(self.target).exists())

    def test_freeze_accepts_canonical_skills_and_snapshot_as_siblings(self):
        snapshot = self.source / "effective-version-test"
        self.put(snapshot / "RESTORE.md", "portable restore")
        result = tool.freeze(snapshot, self.source, self.spec)
        self.assertEqual(tool.verify(snapshot)["bundle_fingerprint"], result["bundle_fingerprint"])

    def test_freeze_rejects_actual_source_tree_overlap(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            tool.freeze(self.source / self.names[0] / "nested-package", self.source, self.spec)

    def test_upgrade_preserves_excluded_history_and_full_backup(self):
        self.freeze()
        self.old_install()
        expected = tool.current(self.snapshot, self.target)
        backup = self.base / "backup"
        tool.restore(self.snapshot, self.target, expected, backup)
        for name in self.names:
            self.assertEqual((self.target / name / "learning/candidates/local.txt").read_text(), "local candidate")
            self.assertEqual((self.target / name / "learning/versions/local.txt").read_text(), "local version")
            self.assertTrue((backup / name / "__pycache__/old.pyc").is_file())
            self.assertTrue((backup / name / "learning/records/prior.json").is_file())
            self.assertFalse((self.target / name / "learning/records/prior.json").exists())
            self.assertTrue((self.target / name / "learning/records/current.json").is_file())
            self.assertEqual(tool.fingerprint(backup / name), expected[name])

    def test_mixed_new_and_existing_skills(self):
        self.freeze()
        self.put(self.target / self.names[1] / "SKILL.md", "existing companion")
        expected = tool.current(self.snapshot, self.target)
        self.assertIsNone(expected[self.names[0]])
        self.assertIsNotNone(expected[self.names[1]])
        tool.apply(self.snapshot, self.target, expected, self.base / "backup")
        self.assertFalse((self.base / "backup" / self.names[0]).exists())
        self.assertTrue((self.base / "backup" / self.names[1] / "SKILL.md").exists())

    def test_stale_expected_rejected_before_backup(self):
        self.freeze()
        self.old_install()
        expected = tool.current(self.snapshot, self.target)
        self.put(self.target / self.names[0] / "SKILL.md", "concurrent edit")
        with self.assertRaisesRegex(ValueError, "Stale"):
            tool.apply(self.snapshot, self.target, expected, self.base / "backup")
        self.assertFalse((self.base / "backup").exists())
        self.assertEqual((self.target / self.names[0] / "SKILL.md").read_text(), "concurrent edit")

    def test_active_skill_lock_rejected(self):
        self.freeze()
        self.old_install()
        expected = tool.current(self.snapshot, self.target)
        self.put(self.target / self.names[0] / "learning/update.lock", "active")
        with self.assertRaisesRegex(ValueError, "skill update"):
            tool.apply(self.snapshot, self.target, expected, self.base / "backup")
        self.assertFalse((self.base / "backup").exists())

    def test_multi_bundle_lock_rejects_concurrent_apply(self):
        self.freeze()
        self.old_install()
        expected = tool.current(self.snapshot, self.target)
        self.put(tool._lock_path(self.target), '{"other": "transaction"}')
        with self.assertRaises(FileExistsError):
            tool.apply(self.snapshot, self.target, expected, self.base / "backup")
        self.assertFalse((self.base / "backup").exists())

    def test_tampered_doc_and_nested_manifest_rejected(self):
        self.freeze()
        for relative in ("handbook/guide.md", "evidence/manifest.json", "skills/example-audit/references/manifest.json"):
            path = self.snapshot / relative
            old = path.read_bytes()
            path.write_bytes(old + b"tampered")
            with self.assertRaisesRegex(ValueError, "hash/size"):
                tool.verify(self.snapshot)
            path.write_bytes(old)
        self.put(self.snapshot / "unlisted.txt", "extra")
        with self.assertRaisesRegex(ValueError, "file set"):
            tool.verify(self.snapshot)

    def test_externally_pinned_fingerprint_rejected(self):
        self.freeze()
        with self.assertRaisesRegex(ValueError, "externally expected"):
            tool.verify(self.snapshot, "0" * 64)

    def test_forced_swap_failure_restores_every_original(self):
        self.freeze()
        self.old_install()
        expected = tool.current(self.snapshot, self.target)
        before = {name: tool._entries(self.target / name) for name in self.names}
        real_move = tool._move
        count = 0

        def failing_move(source, destination):
            nonlocal count
            count += 1
            if count == 4:
                raise OSError("injected interrupted swap")
            real_move(source, destination)

        with mock.patch.object(tool, "_move", side_effect=failing_move):
            with self.assertRaisesRegex(OSError, "injected"):
                tool.apply(self.snapshot, self.target, expected, self.base / "backup")
        self.assertEqual(tool.current(self.snapshot, self.target), expected)
        self.assertEqual({name: tool._entries(self.target / name) for name in self.names}, before)
        self.assertFalse(tool._lock_path(self.target).exists())

    def test_forced_swap_failure_removes_fresh_install(self):
        self.freeze()
        expected = tool.current(self.snapshot, self.target)
        real_move = tool._move
        count = 0

        def failing_move(source, destination):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("fresh swap failure")
            real_move(source, destination)

        with mock.patch.object(tool, "_move", side_effect=failing_move):
            with self.assertRaises(OSError):
                tool.apply(self.snapshot, self.target, expected, self.base / "backup")
        self.assertEqual(tool.current(self.snapshot, self.target), expected)

    def interrupted_journal(self):
        manifest = self.freeze()
        self.old_install()
        expected = tool.current(self.snapshot, self.target)
        transaction = uuid.uuid4().hex
        stage = self.base / f".drawing-bundle-stage-{transaction}"
        swap = self.base / f".drawing-bundle-old-{transaction}"
        stage.mkdir()
        swap.mkdir()
        for name in self.names:
            shutil.copytree(self.snapshot / "skills" / name, stage / name)
        journal = {
            "schema_version": tool.SCHEMA, "transaction_id": transaction, "phase": "swapping",
            "owner_pid": 2147483647,
            "target_root": str(self.target), "backup_root": str(self.base / "backup"),
            "stage_root": str(stage), "swap_root": str(swap), "canonical_skill_names": list(self.names),
            "expected": expected, "wanted": {name: manifest["skills"][name]["fingerprint"] for name in self.names},
        }
        tool._write_json(tool._lock_path(self.target), journal)
        return journal, stage, swap

    def test_recover_actual_interrupted_multi_skill_swap(self):
        journal, stage, swap = self.interrupted_journal()
        first, second = self.names
        tool._move(self.target / first, swap / first)
        tool._move(stage / first, self.target / first)
        tool._move(self.target / second, swap / second)
        result = tool.recover(self.target)
        self.assertEqual(result["status"], "original-state-restored")
        self.assertEqual(tool.current(self.snapshot, self.target), journal["expected"])
        self.assertFalse(stage.exists())
        self.assertFalse(swap.exists())

    def test_recover_rejects_unsafe_journal(self):
        journal, stage, swap = self.interrupted_journal()
        journal["stage_root"] = str(self.base / "unrelated")
        self.put(self.base / "unrelated/keep.txt", "keep")
        tool._write_json(tool._lock_path(self.target), journal)
        with self.assertRaisesRegex(ValueError, "Unsafe transaction"):
            tool.recover(self.target)
        self.assertTrue((self.base / "unrelated/keep.txt").is_file())
        self.assertTrue(tool._lock_path(self.target).exists())

    def test_recover_rejects_live_transaction_owner(self):
        journal, stage, swap = self.interrupted_journal()
        journal["owner_pid"] = os.getpid()
        tool._write_json(tool._lock_path(self.target), journal)
        with self.assertRaisesRegex(ValueError, "still active"):
            tool.recover(self.target)
        self.assertTrue(tool._lock_path(self.target).exists())

    def test_recover_committed_swap_only_finishes_cleanup(self):
        journal, stage, swap = self.interrupted_journal()
        for name in self.names:
            tool._move(self.target / name, swap / name)
            tool._move(stage / name, self.target / name)
        journal["phase"] = "committed"
        tool._write_json(tool._lock_path(self.target), journal)
        result = tool.recover(self.target)
        self.assertEqual(result["status"], "committed-cleanup-finished")
        self.assertEqual(tool.current(self.snapshot, self.target), journal["wanted"])
        self.assertFalse(swap.exists())

    def test_reparse_point_defense_without_symlink_privilege(self):
        path = self.source / self.names[0] / "SKILL.md"
        fake = mock.Mock(st_file_attributes=0x400, st_mode=0o100644)
        original_lstat = Path.lstat

        def simulated_reparse(candidate, *args, **kwargs):
            return fake if candidate == path else original_lstat(candidate, *args, **kwargs)

        with mock.patch.object(Path, "lstat", simulated_reparse):
            with self.assertRaisesRegex(ValueError, "Linked/reparse"):
                tool.managed(self.source / self.names[0])

    def test_manifest_traversal_and_duplicate_paths_rejected(self):
        self.freeze()
        path = self.snapshot / "manifest.json"
        original = path.read_text()
        for unsafe in ("../escape.txt", "/absolute.txt", "C:/escape.txt", "skills\\evil.txt", "safe/../evil", "safe//evil", "NUL"):
            manifest = json.loads(original)
            manifest["files"][0]["path"] = unsafe
            self.put(path, json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                tool.verify(self.snapshot)
        manifest = json.loads(original)
        manifest["files"].append(manifest["files"][0])
        self.put(path, json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            tool.verify(self.snapshot)

    def test_invalid_and_duplicate_skill_names_rejected(self):
        for names in (["../escape"], ["Example"], ["example-audit", "example-audit"], ["con"], ["example_audit"], []):
            with self.subTest(names=names):
                self.spec["canonical_skill_names"] = names
                with self.assertRaises(ValueError):
                    self.freeze()

    def test_overlapping_snapshot_target_backup_rejected(self):
        self.freeze()
        expected = {name: None for name in self.names}
        for target, backup in ((self.snapshot / "inside", self.base / "backup"), (self.target, self.target / "backup"), (self.target, self.snapshot / "backup")):
            with self.assertRaisesRegex(ValueError, "overlap"):
                tool.apply(self.snapshot, target, expected, backup)

    def test_symlink_rejected_when_platform_allows_it(self):
        outside = self.base / "outside.txt"
        self.put(outside, "do not follow")
        linked = self.source / self.names[0] / "reference.txt"
        try:
            linked.symlink_to(outside)
        except OSError as error:
            if os.name != "nt":
                self.skipTest(f"Symlinks unavailable: {error}")
            # Windows directory junctions exercise the same native reparse guard
            # without requiring the privilege needed for file symbolic links.
            destination = self.base / "junction-destination"
            destination.mkdir()
            linked = self.source / self.names[0] / "linked-directory"
            environment = dict(os.environ, BUNDLE_TEST_JUNCTION=str(linked), BUNDLE_TEST_DESTINATION=str(destination))
            result = subprocess.run(
                ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                 "New-Item -ItemType Junction -Path $env:BUNDLE_TEST_JUNCTION -Target $env:BUNDLE_TEST_DESTINATION -ErrorAction Stop | Out-Null"],
                env=environment, capture_output=True, text=True, check=False,
            )
            if result.returncode:
                self.skipTest(f"Neither symlinks nor junctions available: {result.stderr}")
        with self.assertRaisesRegex(ValueError, "Linked/reparse"):
            self.freeze()

    def test_source_algorithm_matches_prior_managed_fingerprint(self):
        import hashlib
        expected = hashlib.sha256()
        root = self.source / self.names[0]
        records = {
            "SKILL.md": (root / "SKILL.md").read_bytes(),
            "learning/records/current.json": (root / "learning/records/current.json").read_bytes(),
            "references/manifest.json": (root / "references/manifest.json").read_bytes(),
        }
        for relative, content in sorted(records.items()):
            expected.update(relative.encode() + b"\0" + hashlib.sha256(content).digest())
        self.assertEqual(tool.fingerprint(root), expected.hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
