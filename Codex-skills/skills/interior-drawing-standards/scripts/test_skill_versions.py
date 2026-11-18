import copy
import shutil
import tempfile
import unittest
from pathlib import Path

import skill_versions as versions


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "installed"
        self.stage = Path(self.temp.name) / "staged"
        shutil.copytree(Path(__file__).resolve().parents[1], self.root, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(self.root, self.stage)
        self.lesson = {
            "id": "test-interpretation",
            "scope": "interpretation",
            "observation": "A symbol was ambiguous",
            "cause": "No legend was available",
            "proposed_rule": "Keep appearance and meaning separate",
            "evidence": ["synthetic regression fixture"],
            "limitations": ["Not a universal symbol meaning"],
            "verification": {"regression": "passed", "visual": "not-applicable", "instruction_review": "passed"},
            "basis": "verified-correction",
            "status": "candidate",
            "behavioral_change": True,
            "visual_change": False
        }

    def test_update_snapshot_rollback_and_stale_writer(self):
        original = versions.fingerprint(self.root)
        path = self.stage / "references" / "drawing-language.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSynthetic addition.\n", encoding="utf-8")
        version = versions.update(self.root, self.stage, original, self.lesson)
        self.assertNotEqual(original, versions.fingerprint(self.root))
        with self.assertRaises(ValueError):
            versions.update(self.root, self.stage, original, self.lesson)
        restore = Path(self.temp.name) / "restore"
        shutil.copytree(self.root / "learning" / "versions" / version, restore)
        versions.update(self.root, restore, versions.fingerprint(self.root))
        self.assertEqual(original, versions.fingerprint(self.root))

    def test_reject_project_or_unverified_lessons(self):
        for change in (
            {"scope": "project"},
            {"verification": {"regression": "failed", "visual": "not-applicable", "instruction_review": "passed"}},
            {"visual_change": True},
        ):
            lesson = copy.deepcopy(self.lesson)
            lesson.update(change)
            with self.assertRaises(ValueError):
                versions.lesson_check(lesson)

    def test_invalid_stage_keeps_original(self):
        original = versions.fingerprint(self.root)
        (self.stage / "references" / "drawing-language.md").unlink()
        with self.assertRaises(ValueError):
            versions.update(self.root, self.stage, original, self.lesson)
        self.assertEqual(original, versions.fingerprint(self.root))

    def test_existing_lock_blocks_update(self):
        learning = self.root / "learning"
        learning.mkdir(exist_ok=True)
        (learning / "update.lock").write_text("other writer", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            versions.update(self.root, self.stage, versions.fingerprint(self.root), self.lesson)


if __name__ == "__main__":
    unittest.main()
