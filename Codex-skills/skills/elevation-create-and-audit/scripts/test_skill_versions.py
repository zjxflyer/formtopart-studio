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
        self.root = Path(self.temp.name) / 'installed'
        self.stage = Path(self.temp.name) / 'staged'
        shutil.copytree(Path(__file__).resolve().parents[1], self.root, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(self.root, self.stage)
        self.lesson = dict(id='test-correction', scope='invariant', observation='Missing annotation', cause='Separate schedule', proposed_rule='Share dimension records', evidence=['synthetic regression fixture'], verification=dict(regression='passed', visual='not-applicable', instruction_review='passed'), basis='verified-correction', status='candidate', behavioral_change=True, visual_change=False)

    def test_update_snapshot_rollback_and_stale_writer(self):
        original = versions.fingerprint(self.root)
        path = self.stage / 'references' / 'lessons.md'
        path.write_text(path.read_text(encoding='utf-8') + '\nSynthetic test addition.\n', encoding='utf-8')
        version = versions.update(self.root, self.stage, original, self.lesson)
        self.assertNotEqual(original, versions.fingerprint(self.root))
        with self.assertRaises(ValueError):
            versions.update(self.root, self.stage, original, self.lesson)
        restore = Path(self.temp.name) / 'restore'
        shutil.copytree(self.root / 'learning' / 'versions' / version, restore)
        versions.update(self.root, restore, versions.fingerprint(self.root))
        self.assertEqual(original, versions.fingerprint(self.root))

    def test_reject_unverified_or_project_rules(self):
        for change in [dict(scope='project'), dict(visual_change=True), dict(verification=dict(regression='failed', visual='not-applicable', instruction_review='passed'))]:
            lesson = copy.deepcopy(self.lesson)
            lesson.update(change)
            with self.assertRaises(ValueError):
                versions.lesson_check(lesson)

    def test_invalid_stage_keeps_original(self):
        original = versions.fingerprint(self.root)
        (self.stage / 'references' / 'structure.md').unlink()
        with self.assertRaises(ValueError):
            versions.update(self.root, self.stage, original, self.lesson)
        self.assertEqual(original, versions.fingerprint(self.root))

    def test_existing_lock_blocks_update(self):
        learning = self.root / 'learning'
        learning.mkdir(exist_ok=True)
        (learning / 'update.lock').write_text('other writer')
        with self.assertRaises(FileExistsError):
            versions.update(self.root, self.stage, versions.fingerprint(self.root), self.lesson)


if __name__ == '__main__':
    unittest.main()
