"""Isolated portability and fault tests; no historical project dependency."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from urllib.parse import unquote
import re

spec = importlib.util.spec_from_file_location("workflow", Path(__file__).with_name("workflow.py"))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("DRAWING_WORKFLOW_TEST_TMP"))
        self.root = Path(self.temp.name) / "unrelated-new-customer"
        self.root.mkdir()
        (self.root / "source").mkdir()
        (self.root / "source/client.pdf").write_bytes(b"test-source")
        self.config = {"project_id": "other-customer", "sources": [{"path": "source/client.pdf"}],
                       "sheets": ["Room10", "Room2"], "output_dir": "deliverables",
                       "model": {"name": "gpt-6.1-sol", "effort": "medium"}}
        w.init(self.root, self.config)

    def tearDown(self):
        self.temp.cleanup()

    def event(self, action, sheet="Room2", stage="INITIAL", **kwargs):
        return w.apply_event(self.root, {"action": action, "sheet": sheet, "stage": stage, **kwargs},
                             w.digest(w.state_path(self.root)))

    def make_artifacts(self, sheet="Room2", revision="r1", mapping=False):
        folder = self.root / "deliverables" / sheet / revision
        folder.mkdir(parents=True, exist_ok=True)
        if mapping:
            path = folder / "mapping.json"
            path.write_text('{"views":[]}', encoding="utf-8")
            return {"mapping": path.relative_to(self.root).as_posix()}
        paths = [folder / "Plan.pdf", folder / "Elevation 1.pdf"]
        for i, path in enumerate(paths):
            path.write_bytes(f"independent-file-{revision}-{i}".encode())
        return {"plan": paths[0].relative_to(self.root).as_posix(),
                "elevations": [paths[1].relative_to(self.root).as_posix()]}

    def create(self, sheet="Room2", stage="INITIAL", revision="r1", **kwargs):
        return self.event("create", sheet, stage, creator="Create-" + sheet,
                          artifacts=self.make_artifacts(sheet, revision, mapping=stage == "PHASE1"), **kwargs)

    def check(self, sheet="Room2", stage="INITIAL", verdict="PASS", **kwargs):
        issue = kwargs.get("issue")
        return self.event("check", sheet, stage, checker="Check-" + sheet, verdict=verdict,
                          artifact_sha256=w.artifact_set_hash(self.root, sheet, stage, issue),
                          evidence=["source independently compared with actual export"],
                          findings=[] if verdict == "PASS" else ["bounded or core finding"], **kwargs)

    def summary(self, sheet="Room2", stage="INITIAL", **kwargs):
        return self.event("summarize", sheet, stage, decision="SKIP", note="No new reusable lesson", **kwargs)

    def mapping_pass(self, sheet="Room2"):
        self.create(sheet, "PHASE1", "mapping")
        self.check(sheet, "PHASE1")
        self.summary(sheet, "PHASE1")

    def initial_pass(self, sheet="Room2"):
        self.mapping_pass(sheet)
        self.create(sheet)
        self.check(sheet)
        self.summary(sheet)

    def add_todo(self, task_id, **fields):
        return w.todo_add(self.root, {"id": task_id, "title": f"Task {task_id}",
            "original_request": f"Original user request for {task_id}", **fields}, w.digest(w.state_path(self.root)))

    def update_todo(self, task_id, **changes):
        return w.todo_update(self.root, task_id, changes, w.digest(w.state_path(self.root)))

    def context_review(self, **changes):
        return {"state_hash": w.digest(w.state_path(self.root)), "decision": "PROCEED",
                "reason": "Latest user request and current progress still require this task.",
                "source_refs": ["latest-user-message", "current-project-progress"], **changes}

    def test_todo_midwork_immutable_original_deduplication_and_counter_separation(self):
        self.mapping_pass()
        self.create()
        before_jobs = w.read(self.root)[1]["jobs"]
        self.add_todo("new-user-issue", original_request="Keep this exact request.\n请保留原话。", sheet_ids=["Room2"],
                      stage="INITIAL", priority="P1", source_ref="user-message-12")
        self.assertEqual(w.read(self.root)[1]["jobs"], before_jobs)
        with self.assertRaisesRegex(w.WorkflowError, "Duplicate TODO"):
            self.add_todo("new-user-issue")
        with self.assertRaisesRegex(w.WorkflowError, "Equivalent"):
            self.add_todo("renamed-duplicate", original_request="Keep this exact request.\n请保留原话。", sheet_ids=["Room2"],
                          stage="INITIAL", priority="P0", source_ref="user-message-12")
        with self.assertRaisesRegex(w.WorkflowError, "immutable"):
            self.update_todo("new-user-issue", original_request="Rewritten")
        self.update_todo("new-user-issue", priority="P0", owner="Check-Room2", status="IN_PROGRESS", notes=["Triaged"],
                         context_review=self.context_review())
        task = w.todo_list(self.root)[0]
        self.assertEqual(task["original_request"], "Keep this exact request.\n请保留原话。")
        self.assertEqual((task["priority"], task["owner"], len(task["history"])), ("P0", "Check-Room2", 2))
        self.assertEqual(w.read(self.root)[1]["jobs"], before_jobs)
        self.assertIn("new-user-issue", Path(w.build_index(self.root)).read_text(encoding="utf-8"))

    def test_todo_dependency_completion_blocking_deferral_and_audit(self):
        self.add_todo("basis")
        self.add_todo("dependent", depends_on=["basis"])
        with self.assertRaisesRegex(w.WorkflowError, "completion evidence"):
            self.update_todo("basis", status="DONE")
        with self.assertRaisesRegex(w.WorkflowError, "dependency DONE"):
            self.update_todo("dependent", status="DONE", evidence=["final reviewed artifact receipt"])
        with self.assertRaisesRegex(w.WorkflowError, "blocker reason"):
            self.update_todo("basis", status="BLOCKED")
        self.update_todo("basis", status="BLOCKED", blocker_reason="Need exact source revision")
        with self.assertRaisesRegex(w.WorkflowError, "explicit reason"):
            self.update_todo("basis", status="DEFERRED")
        self.update_todo("basis", status="DEFERRED", reason="Source owner will respond later", notes=["Still open"])
        self.assertEqual(w.todo_list(self.root)[0]["status"], "DEFERRED")
        self.update_todo("basis", status="DONE", evidence=["source/reference revision verified"])
        self.update_todo("dependent", status="DONE", evidence=["actual output compared and receipt checked"])
        self.assertEqual(w.todo_list(self.root), [])
        all_tasks = w.todo_list(self.root, include_closed=True)
        self.assertEqual(len(all_tasks), 2)
        task = next(x for x in all_tasks if x["id"] == "basis")
        self.assertEqual(task["history"][-2]["changes"]["reason"], "Source owner will respond later")
        self.assertEqual(task["completion_evidence"], ["source/reference revision verified"])

    def test_todo_bad_scope_cycles_self_dependency_and_stale_state(self):
        for fields in ({"sheet_ids": ["unknown"]}, {"priority": "P9"}, {"depends_on": ["unknown"]},
                       {"status": "DONE", "evidence": ["worker finished"]}):
            with self.assertRaises(w.WorkflowError):
                self.add_todo("invalid", **fields)
        self.add_todo("A")
        old_hash = w.digest(w.state_path(self.root))
        self.add_todo("B", depends_on=["A"])
        with self.assertRaisesRegex(w.WorkflowError, "cycle"):
            self.update_todo("A", depends_on=["B"])
        with self.assertRaisesRegex(w.WorkflowError, "self-dependency"):
            self.update_todo("A", depends_on=["A"])
        with self.assertRaisesRegex(w.WorkflowError, "Stale state"):
            w.todo_update(self.root, "A", {"priority": "P0"}, old_hash)

    def test_todo_checkpoint_relocation_supersession_and_no_silent_deletion(self):
        self.add_todo("old")
        self.add_todo("replacement")
        with self.assertRaisesRegex(w.WorkflowError, "explicit reason"):
            self.update_todo("old", status="SUPERSEDED", superseded_by="replacement")
        self.update_todo("old", status="SUPERSEDED", superseded_by="replacement", reason="New request explicitly replaces old task",
                         evidence=["latest-user-request-replacement"])
        self.assertEqual([task["id"] for task in w.todo_list(self.root)], ["replacement"])
        self.assertEqual(len(w.todo_list(self.root, include_closed=True)), 2)
        self.update_todo("replacement", status="IN_PROGRESS", context_review=self.context_review())
        saved = w.checkpoint(self.root)
        target = Path(self.temp.name) / "todo-relocated"
        shutil.copytree(self.root, target, ignore=shutil.ignore_patterns(w.WORK))
        w.resume(target, saved)
        self.assertEqual(w.todo_list(target, include_closed=True), w.todo_list(self.root, include_closed=True))
        self.assertEqual(len(w.read(target)[1]["todo"]["replacement"]["context_reviews"]), 1)
        self.assertEqual(w.read(target)[1]["jobs"], {})
        self.assertIn("old", w.read(target)[1]["todo"])

    def test_todo_intake_preserved_even_when_an_artifact_is_broken(self):
        self.mapping_pass()
        self.create()
        (self.root / "deliverables/Room2/r1/Plan.pdf").write_bytes(b"damaged")
        with self.assertRaises(w.WorkflowError):
            w.validate(self.root)
        result = self.add_todo("repair-file", priority="P0", original_request="Repair the damaged file and recheck it.")
        self.assertEqual(result["status"], "TODO_RECORDED_NOT_A_DRAWING_VERDICT")
        self.assertEqual(w.todo_list(self.root)[0]["id"], "repair-file")
        self.assertEqual(w.read(self.root)[1]["jobs"]["Room2|INITIAL"]["status"], "AWAITING_CHECK")

    def test_todo_pre_dispatch_context_review_missing_invalid_and_stale(self):
        self.add_todo("context-task")
        with self.assertRaisesRegex(w.WorkflowError, "fresh context_review"):
            self.update_todo("context-task", status="IN_PROGRESS")
        stale = self.context_review()
        self.add_todo("new-user-request")
        with self.assertRaisesRegex(w.WorkflowError, "Stale context_review"):
            self.update_todo("context-task", status="IN_PROGRESS", context_review=stale)
        for change in ({"decision": "CANCEL"}, {"reason": " "}, {"source_refs": []},
                       {"source_refs": [True]}, {"source_refs": [" "]}):
            with self.assertRaises(w.WorkflowError):
                self.update_todo("context-task", status="IN_PROGRESS", context_review=self.context_review(**change))
        accepted = self.context_review()
        before_jobs = w.read(self.root)[1]["jobs"]
        self.update_todo("context-task", status="IN_PROGRESS", context_review=accepted)
        task = w.read(self.root)[1]["todo"]["context-task"]
        self.assertEqual(task["status"], "IN_PROGRESS")
        self.assertEqual(task["context_reviews"][0]["state_hash"], accepted["state_hash"])
        self.assertEqual(task["history"][-1]["changes"]["context_review"], accepted)
        self.assertEqual(w.read(self.root)[1]["jobs"], before_jobs)

    def test_todo_resume_and_running_reassignment_need_fresh_review_not_auto_cancel(self):
        self.add_todo("running")
        self.update_todo("running", status="IN_PROGRESS", context_review=self.context_review())
        self.add_todo("later-request")
        self.assertEqual(w.read(self.root)[1]["todo"]["running"]["status"], "IN_PROGRESS")
        with self.assertRaisesRegex(w.WorkflowError, "fresh context_review"):
            self.update_todo("running", owner="Different-Agent")
        self.update_todo("running", owner="Different-Agent", context_review=self.context_review())
        with self.assertRaisesRegex(w.WorkflowError, "fresh context_review"):
            self.update_todo("running", status="IN_PROGRESS")
        self.update_todo("running", status="IN_PROGRESS", context_review=self.context_review())
        task = w.read(self.root)[1]["todo"]["running"]
        self.assertEqual(len(task["context_reviews"]), 3)
        self.assertEqual(task["original_request"], "Original user request for running")

    def test_todo_dependent_dispatch_waits_and_boolean_evidence_rejected(self):
        self.add_todo("prerequisite")
        self.add_todo("dependent", depends_on=["prerequisite"])
        with self.assertRaisesRegex(w.WorkflowError, "IN_PROGRESS requires every explicit dependency DONE"):
            self.update_todo("dependent", status="IN_PROGRESS", context_review=self.context_review())
        self.update_todo("prerequisite", status="BLOCKED", blocker_reason="Await current source")
        with self.assertRaisesRegex(w.WorkflowError, "IN_PROGRESS requires every explicit dependency DONE"):
            self.update_todo("dependent", status="IN_PROGRESS", context_review=self.context_review())
        for evidence in ([{"path": True}], [{"ref": []}], [{"url": " "}]):
            with self.assertRaisesRegex(w.WorkflowError, "nonempty verification reference"):
                self.update_todo("prerequisite", status="DONE", evidence=evidence)
        self.update_todo("prerequisite", status="DONE", evidence=[{"path": "current-source-check.json"}])
        self.update_todo("dependent", status="IN_PROGRESS", context_review=self.context_review())
        self.assertEqual(w.read(self.root)[1]["todo"]["dependent"]["status"], "IN_PROGRESS")

    def test_todo_status_dispositions_require_fresh_context_reasons_and_proof(self):
        self.add_todo("obsolete")
        self.add_todo("replacement")
        self.update_todo("obsolete", status="DEFERRED", reason="Wait for source")
        with self.assertRaisesRegex(w.WorkflowError, "fresh explicit reason"):
            self.update_todo("obsolete", status="CANCELLED", evidence=["latest-context"])
        with self.assertRaisesRegex(w.WorkflowError, "fresh contextual evidence"):
            self.update_todo("obsolete", status="CANCELLED", reason="Latest instruction removes the requirement")
        self.update_todo("obsolete", status="BLOCKED", blocker_reason="Missing updated source")
        with self.assertRaisesRegex(w.WorkflowError, "fresh concrete blocker"):
            self.update_todo("obsolete", status="BLOCKED")
        with self.assertRaisesRegex(w.WorkflowError, "fresh explicit reason"):
            self.update_todo("obsolete", status="SUPERSEDED", superseded_by="replacement", evidence=["latest-context"])
        self.update_todo("obsolete", status="CANCELLED", reason="Latest user instruction removes this requirement",
                         evidence=["latest-user-message-42"])
        task = next(x for x in w.todo_list(self.root, True) if x["id"] == "obsolete")
        self.assertEqual(task["status"], "CANCELLED")
        self.assertEqual(task["history"][-1]["changes"]["reason"], "Latest user instruction removes this requirement")
        self.assertEqual(task["completion_evidence"], [])

    def test_arbitrary_ids_natural_order_and_paths(self):
        self.assertEqual(w.validate(self.root)["sheets"], ["Room2", "Room10"])
        for value in ["../bad", "a/b", "CON", "two words", "x:"]:
            with self.assertRaises(w.WorkflowError):
                w.safe_id(value)
        with self.assertRaises(w.WorkflowError):
            w.local(self.root, "../outside")

    def test_phase_gate_and_independent_check(self):
        with self.assertRaisesRegex(w.WorkflowError, "PHASE1"):
            self.create()
        self.mapping_pass()
        self.create()
        with self.assertRaisesRegex(w.WorkflowError, "independent"):
            self.event("check", checker="Create-Room2", verdict="PASS", evidence=["evidence"],
                       artifact_sha256=w.artifact_set_hash(self.root, "Room2", "INITIAL"))
        self.check()
        with self.assertRaisesRegex(w.WorkflowError, "Summarize"):
            self.event("release")
        with self.assertRaisesRegex(w.WorkflowError, "Summarize"):
            self.create(revision="r2")
        self.summary()
        self.event("release")

    def test_initial_two_total_rounds_exception_and_no_reset(self):
        self.mapping_pass()
        for r in (1, 2):
            self.create(revision=f"r{r}")
            self.check(verdict="REVISE")
            self.summary()
        job = w.read(self.root)[1]["jobs"]["Room2|INITIAL"]
        self.assertEqual((job["major_round"], job["repair_revision"], job["check_events"]), (2, 1, 2))
        with self.assertRaisesRegex(w.WorkflowError, "budget"):
            self.create(revision="renamed-folder")
        with self.assertRaisesRegex(w.WorkflowError, "substantial"):
            self.event("exception", checker="Check-Room2", category="cosmetic", reason="Pretty", evidence=["x"])
        self.event("exception", checker="Check-Room2", category="shape", reason="Substantial missing physical profile",
                   evidence=["source/output independent comparison"])
        self.create(revision="r3")
        self.check(verdict="HOLD")
        self.summary()
        with self.assertRaisesRegex(w.WorkflowError, "budget"):
            self.create(revision="r4")
        with self.assertRaisesRegex(w.WorkflowError, "Release"):
            self.event("release")
        with self.assertRaises(w.WorkflowError):
            w.init(self.root, self.config)

    def test_two_plus_one_plus_two_and_separate_issue_ids(self):
        self.initial_pass()
        for issue in ("I1", "I2"):
            self.create(stage="DOCUMENT_ISSUES", revision=issue, issue=issue)
            self.check(stage="DOCUMENT_ISSUES", issue=issue)
            self.summary(stage="DOCUMENT_ISSUES", issue=issue)
        current = w.read(self.root)[1]["jobs"]["Room2|DOCUMENT_ISSUES|I2"]
        values = {"plan": current["artifacts"]["plan"]["path"],
                  "elevations": [x["path"] for x in current["artifacts"]["elevations"]]}
        self.event("review", stage="FULL_REVIEW", creator=current["creator"], artifacts=values)
        self.check(stage="FULL_REVIEW", verdict="REVISE")
        self.summary(stage="FULL_REVIEW")
        self.create(stage="FULL_REVIEW", revision="full-r2")
        self.check(stage="FULL_REVIEW", verdict="REVISE")
        self.summary(stage="FULL_REVIEW")
        self.assertEqual(w.read(self.root)[1]["jobs"]["Room2|FULL_REVIEW"]["major_round"], 1)
        self.create(stage="FULL_REVIEW", revision="full-r3")
        self.check(stage="FULL_REVIEW")
        self.summary(stage="FULL_REVIEW")
        self.event("release", stage="FULL_REVIEW")
        jobs = w.read(self.root)[1]["jobs"]
        self.assertEqual(jobs["Room2|INITIAL"]["major_round"], 1)
        self.assertEqual(jobs["Room2|DOCUMENT_ISSUES|I1"]["major_round"], 1)
        self.assertEqual(jobs["Room2|DOCUMENT_ISSUES|I2"]["major_round"], 1)
        self.assertEqual(jobs["Room2|FULL_REVIEW"]["major_round"], 2)
        self.assertEqual(jobs["Room2|FULL_REVIEW"]["repair_revision"], 2)
        self.assertEqual(jobs["Room2|FULL_REVIEW"]["check_events"], 3)
        with self.assertRaisesRegex(w.WorkflowError, "superseded"):
            self.event("release", stage="INITIAL")

    def test_stale_state_artifact_source_and_writer_lock(self):
        old = w.digest(w.state_path(self.root))
        self.mapping_pass()
        with self.assertRaisesRegex(w.WorkflowError, "Stale state"):
            w.apply_event(self.root, {"action": "create", "sheet": "Room2", "stage": "INITIAL",
                          "creator": "creator", "artifacts": self.make_artifacts()}, old)
        self.create()
        with self.assertRaisesRegex(w.WorkflowError, "exact"):
            self.event("check", checker="Check-Room2", verdict="PASS", evidence=["evidence"], artifact_sha256="0" * 64)
        plan = self.root / "deliverables/Room2/r1/Plan.pdf"
        plan.write_bytes(b"changed")
        with self.assertRaisesRegex(w.WorkflowError, "Stale"):
            w.validate(self.root)
        plan.write_bytes(b"independent-file-r1-0")
        with w.writer(self.root):
            with self.assertRaisesRegex(w.WorkflowError, "lock"):
                w.checkpoint(self.root)
        (self.root / "source/client.pdf").write_bytes(b"changed-source")
        with self.assertRaisesRegex(w.WorkflowError, "Stale"):
            w.validate(self.root)

    def test_checkpoint_relocation_and_corruption(self):
        self.initial_pass()
        saved = w.checkpoint(self.root)
        target = Path(self.temp.name) / "relocated"
        shutil.copytree(self.root, target, ignore=shutil.ignore_patterns(w.WORK))
        result = w.resume(target, saved)
        self.assertEqual(result["sequence"], w.validate(self.root)["sequence"])
        self.assertNotIn(str(self.root), w.state_path(target).read_text(encoding="utf-8"))
        payload = json.loads(Path(saved).read_text(encoding="utf-8"))
        payload["state"]["sequence"] += 1
        bad = Path(self.temp.name) / "bad.json"
        bad.write_bytes(w.encoded(payload))
        with self.assertRaisesRegex(w.WorkflowError, "Damaged"):
            w.resume(Path(self.temp.name) / "new", bad)
        with self.assertRaisesRegex(w.WorkflowError, "overwrite"):
            w.resume(target, saved)

    def two_revision_initial_pass(self):
        self.mapping_pass()
        self.create(revision="r1")
        self.check(verdict="REVISE")
        self.summary()
        self.create(revision="r2")
        self.check()
        self.summary()

    def test_old_submitted_revision_is_immutable_after_new_pass(self):
        self.two_revision_initial_pass()
        old = self.root / "deliverables/Room2/r1/Plan.pdf"
        original = old.read_bytes()
        old.write_bytes(b"mutated old revision")
        with self.assertRaisesRegex(w.WorkflowError, "Stale"):
            w.validate(self.root)
        with self.assertRaisesRegex(w.WorkflowError, "Stale"):
            w.checkpoint(self.root)
        old.write_bytes(original)
        old.unlink()
        with self.assertRaisesRegex(w.WorkflowError, "Missing file"):
            w.validate(self.root)
        old.write_bytes(original)
        history = w.read(self.root)[1]["artifact_history"]
        self.assertEqual(len(history), 3)
        self.assertEqual(history[1]["artifacts"]["plan"]["sha256"], hashlib.sha256(original).hexdigest())
        w.validate(self.root)

    def test_relocated_checkpoint_requires_old_artifacts_and_exact_check_bindings(self):
        self.two_revision_initial_pass()
        saved = w.checkpoint(self.root)
        target = Path(self.temp.name) / "relocated-incomplete"
        shutil.copytree(self.root, target, ignore=shutil.ignore_patterns(w.WORK))
        old = target / "deliverables/Room2/r1/Plan.pdf"
        old.unlink()
        with self.assertRaisesRegex(w.WorkflowError, "Missing file"):
            w.resume(target, saved)
        self.assertFalse(w.state_path(target).exists())
        shutil.copy2(self.root / "deliverables/Room2/r1/Plan.pdf", old)
        w.resume(target, saved)
        state = json.loads(w.state_path(target).read_text(encoding="utf-8"))
        state["jobs"]["Room2|INITIAL"]["checks"][0]["artifact_sha256"] = "0" * 64
        w.atomic(w.state_path(target), w.encoded(state))
        with self.assertRaisesRegex(w.WorkflowError, "Historical job check"):
            w.validate(target)

    def test_state_without_history_is_not_silently_supported(self):
        state = w.read(self.root)[1]
        state.pop("artifact_history")
        w.atomic(w.state_path(self.root), w.encoded(state))
        with self.assertRaisesRegex(w.WorkflowError, "Unsupported state"):
            w.validate(self.root)

    def test_index_links_and_unreleased_status(self):
        self.initial_pass()
        self.event("release")
        index = Path(w.build_index(self.root))
        content = index.read_text(encoding="utf-8")
        self.assertIn("NOT_RELEASED", content)
        self.assertEqual(len(re.findall(r'href="([^"]+)"', content)), 2)
        for link in re.findall(r'href="([^"]+)"', content):
            self.assertTrue((index.parent / unquote(link)).is_file())
        self.assertIn("width:28%", content)

    def test_provisional_never_silent_pass_and_owned_artifacts(self):
        self.mapping_pass()
        with self.assertRaisesRegex(w.WorkflowError, "own output"):
            self.event("create", creator="creator", artifacts=self.make_artifacts("Room10"))
        self.create()
        with self.assertRaisesRegex(w.WorkflowError, "conceal"):
            self.event("check", checker="checker", verdict="PASS", findings=["unresolved"], evidence=["x"],
                       artifact_sha256=w.artifact_set_hash(self.root, "Room2", "INITIAL"))
        self.check(verdict="PROVISIONAL")
        self.summary()
        self.event("release")
        self.assertEqual(w.read(self.root)[1]["releases"]["Room2"]["status"], "PROVISIONAL")

    def test_cosmetic_notes_release_without_provisional_override(self):
        self.mapping_pass()
        self.create()
        artifact_hash = w.artifact_set_hash(self.root, "Room2", "INITIAL")
        for findings in ([], ["uncategorized"], [{"classification": "dimension", "note": "wrong"}],
                         [{"classification": "cosmetic", "note": "wrong core", "unresolved_core": True}]):
            with self.assertRaisesRegex(w.WorkflowError, "cosmetic"):
                self.event("check", checker="Check-Room2", verdict="PASS_WITH_NOTES", findings=findings,
                           evidence=["source/output core checks passed"], artifact_sha256=artifact_hash)
        self.event("check", checker="Check-Room2", verdict="PASS_WITH_NOTES",
                   findings=[{"classification": "cosmetic", "note": "Small harmless whitespace difference"}],
                   evidence=["source/output core checks passed"], artifact_sha256=artifact_hash)
        self.summary()
        self.event("release")
        self.assertEqual(w.read(self.root)[1]["releases"]["Room2"]["status"], "PASS_WITH_NOTES")

    def test_adoption_requires_verification(self):
        self.mapping_pass()
        self.create()
        self.check()
        with self.assertRaisesRegex(w.WorkflowError, "verification"):
            self.event("summarize", decision="ADOPT", note="A candidate rule")
        self.event("summarize", decision="CANDIDATE", note="Not yet verified")

    def test_issue_summary_cannot_be_bypassed_by_renaming_issue(self):
        self.initial_pass()
        self.create(stage="DOCUMENT_ISSUES", revision="issue-one", issue="I1")
        self.check(stage="DOCUMENT_ISSUES", issue="I1")
        with self.assertRaisesRegex(w.WorkflowError, "Summarize"):
            self.create(stage="DOCUMENT_ISSUES", revision="issue-two", issue="I2")
        self.summary(stage="DOCUMENT_ISSUES", issue="I1")
        self.create(stage="DOCUMENT_ISSUES", revision="issue-two", issue="I2")

    def test_explicit_hold_preserves_revise_evidence_and_counters(self):
        self.initial_pass()
        for revision in (1, 2):
            self.create(stage="DOCUMENT_ISSUES", revision=f"issue-{revision}", issue="I1")
            self.check(stage="DOCUMENT_ISSUES", verdict="REVISE", issue="I1")
            if revision == 2:
                with self.assertRaisesRegex(w.WorkflowError, "Summarize"):
                    self.event("hold", stage="DOCUMENT_ISSUES", issue="I1", checker="Check-Room2",
                               reason="Source unresolved", evidence=["independent evidence"])
            self.summary(stage="DOCUMENT_ISSUES", issue="I1")
        before = w.read(self.root)[1]["jobs"]["Room2|DOCUMENT_ISSUES|I1"]
        for kwargs in ({"checker": "wrong", "reason": "unresolved", "evidence": ["x"]},
                       {"checker": "Check-Room2", "reason": "", "evidence": ["x"]},
                       {"checker": "Check-Room2", "reason": "unresolved", "evidence": []}):
            with self.assertRaisesRegex(w.WorkflowError, "latest independent"):
                self.event("hold", stage="DOCUMENT_ISSUES", issue="I1", **kwargs)
        self.event("hold", stage="DOCUMENT_ISSUES", issue="I1", checker="Check-Room2",
                   reason="Substantial source uncertainty remains; defer explicitly", evidence=["source revision evidence"])
        after = w.read(self.root)[1]["jobs"]["Room2|DOCUMENT_ISSUES|I1"]
        self.assertEqual(after["status"], "HOLD")
        for field in ("major_round", "repair_revision", "check_events", "create_events", "checks"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after["checks"][-1]["verdict"], "REVISE")
        with self.assertRaisesRegex(w.WorkflowError, "Release"):
            self.event("release", stage="DOCUMENT_ISSUES", issue="I1")
        self.create(stage="DOCUMENT_ISSUES", revision="next-issue", issue="I2")
        self.check(stage="DOCUMENT_ISSUES", issue="I2")
        self.summary(stage="DOCUMENT_ISSUES", issue="I2")
        current = w.read(self.root)[1]["jobs"]["Room2|DOCUMENT_ISSUES|I2"]
        values = {"plan": current["artifacts"]["plan"]["path"],
                  "elevations": [x["path"] for x in current["artifacts"]["elevations"]]}
        self.event("review", stage="FULL_REVIEW", creator=current["creator"], artifacts=values)

    def test_hold_without_independent_revise_basis_rejected(self):
        with self.assertRaisesRegex(w.WorkflowError, "completed"):
            self.event("hold", stage="DOCUMENT_ISSUES", issue="I1", checker="Check-Room2",
                       reason="No check", evidence=["x"])
        self.initial_pass()
        with self.assertRaisesRegex(w.WorkflowError, "completed"):
            self.event("hold", checker="Check-Room2", reason="Already passed", evidence=["x"])

    def test_empty_check_and_early_full_review_are_rejected(self):
        self.mapping_pass()
        self.create()
        with self.assertRaisesRegex(w.WorkflowError, "explicit"):
            self.event("check", checker="checker", verdict="PASS", evidence=[],
                       artifact_sha256=w.artifact_set_hash(self.root, "Room2", "INITIAL"))
        self.check()
        self.summary()
        with self.assertRaisesRegex(w.WorkflowError, "Start full review"):
            self.create(stage="FULL_REVIEW", revision="premature-fix")

    def test_full_review_two_repairs_summary_gates_and_exception(self):
        self.initial_pass()
        current = w.read(self.root)[1]["jobs"]["Room2|INITIAL"]
        values = {"plan": current["artifacts"]["plan"]["path"],
                  "elevations": [x["path"] for x in current["artifacts"]["elevations"]]}
        self.event("review", stage="FULL_REVIEW", creator=current["creator"], artifacts=values)
        self.check(stage="FULL_REVIEW", verdict="REVISE")
        with self.assertRaisesRegex(w.WorkflowError, "Summarize"):
            self.create(stage="FULL_REVIEW", revision="full-1")
        self.summary(stage="FULL_REVIEW")
        for repair in (1, 2):
            self.create(stage="FULL_REVIEW", revision=f"full-{repair}")
            job = w.read(self.root)[1]["jobs"]["Room2|FULL_REVIEW"]
            self.assertEqual((job["major_round"], job["repair_revision"]), (repair, repair))
            self.check(stage="FULL_REVIEW", verdict="REVISE")
            with self.assertRaisesRegex(w.WorkflowError, "Summarize"):
                self.create(stage="FULL_REVIEW", revision=f"premature-{repair}")
            self.summary(stage="FULL_REVIEW")
        with self.assertRaisesRegex(w.WorkflowError, "budget"):
            self.create(stage="FULL_REVIEW", revision="full-3")
        self.event("exception", stage="FULL_REVIEW", checker="Check-Room2", category="dimension",
                   reason="Substantial wrong source-owned dimension", evidence=["independent source comparison"])
        self.create(stage="FULL_REVIEW", revision="full-3")
        self.check(stage="FULL_REVIEW", verdict="HOLD")
        self.summary(stage="FULL_REVIEW")
        with self.assertRaisesRegex(w.WorkflowError, "budget"):
            self.create(stage="FULL_REVIEW", revision="full-4")

    def test_pdf_merge_actual_page_order(self):
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError:
            self.skipTest("Optional pypdf is unavailable")
        expected = []
        for i, sheet in enumerate(["Room2", "Room10"]):
            self.mapping_pass(sheet)
            values = self.make_artifacts(sheet)
            for j, path in enumerate([values["plan"], *values["elevations"]]):
                pdf = PdfWriter()
                width = 200 + i * 20 + j
                pdf.add_blank_page(width=width, height=300)
                with (self.root / path).open("wb") as stream:
                    pdf.write(stream)
                pdf.close()
                expected.append(width)
            self.event("create", sheet, creator="Create-" + sheet, artifacts=values)
            self.check(sheet)
            self.summary(sheet)
            self.event("release", sheet)
        out = w.merge(self.root)
        self.assertEqual([float(p.mediabox.width) for p in PdfReader(out).pages], expected)
        manifest = json.loads(Path(out).with_suffix(".merge.json").read_text(encoding="utf-8"))
        self.assertEqual([x["sheet"] for x in manifest["order"]], ["Room2", "Room2", "Room10", "Room10"])
        with self.assertRaisesRegex(w.WorkflowError, "overwrite"):
            w.merge(self.root, "Room2/r1/Plan.pdf")

    @staticmethod
    def real_pdf(path, labels):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject
        writer = PdfWriter()
        for label in labels:
            page = writer.add_blank_page(width=200 + label, height=300)
            content = DecodedStreamObject()
            content.set_data(f"{label} 0 m {label + 10} 10 l S\n".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(content)
        with path.open("wb") as stream:
            writer.write(stream)
        writer.close()

    @staticmethod
    def page_fingerprints(path):
        from pypdf import PdfReader
        result = []
        for page in PdfReader(path).pages:
            content = page.get_contents()
            raw = content.get_data() if content is not None else b""
            if not raw:
                raise AssertionError("Fixture/page unexpectedly has empty decoded contents")
            result.append((tuple(float(x) for x in page.mediabox), hashlib.sha256(raw).hexdigest()))
        return result

    def test_packet_real_page_contents_order_notes_and_staleness(self):
        try:
            import pypdf
        except ImportError:
            self.skipTest("Optional pypdf is unavailable")
        for n, sheet in enumerate(["Room2", "Room10"]):
            self.mapping_pass(sheet)
            values = self.make_artifacts(sheet)
            self.real_pdf(self.root / values["plan"], [10 + n, 20 + n])
            self.real_pdf(self.root / values["elevations"][0], [30 + n])
            self.event("create", sheet, creator="Create-" + sheet, artifacts=values)
            if sheet == "Room2":
                self.event("check", sheet, checker="Check-" + sheet, verdict="PASS_WITH_NOTES",
                           findings=[{"classification": "cosmetic", "note": "Harmless whitespace"}],
                           evidence=["core source and export checks passed"],
                           artifact_sha256=w.artifact_set_hash(self.root, sheet, "INITIAL"))
            else:
                self.check(sheet)
            self.summary(sheet)
            self.event("release", sheet)
        index = Path(w.build_index(self.root))
        self.assertIn("Plan only", index.read_text(encoding="utf-8"))
        self.assertNotIn("PDF SET", index.read_text(encoding="utf-8"))
        built = w.packets(self.root)
        self.assertEqual(len(built), 2)
        all_expected = []
        for sheet, item in zip(["Room2", "Room10"], built):
            current = w.read(self.root)[1]["releases"][sheet]["artifacts"]
            expected = self.page_fingerprints(self.root / current["plan"]["path"])
            for elevation in current["elevations"]:
                expected += self.page_fingerprints(self.root / elevation["path"])
            self.assertEqual(self.page_fingerprints(self.root / item["path"]), expected)
            all_expected += expected
        combined = w.merge(self.root)
        self.assertEqual(self.page_fingerprints(combined), all_expected)
        index = Path(w.build_index(self.root))
        self.assertEqual(index.read_text(encoding="utf-8").count("PDF SET"), 2)
        for link in re.findall(r'href="([^"]+)"', index.read_text(encoding="utf-8")):
            self.assertTrue((index.parent / unquote(link)).is_file())
        packet = self.root / built[0]["path"]
        packet.write_bytes(packet.read_bytes() + b"\nchanged")
        with self.assertRaisesRegex(w.WorkflowError, "damaged sheet packet"):
            w.build_index(self.root)
        w.packets(self.root, sheet="Room2")
        w.build_index(self.root)
        values = self.make_artifacts("Room2", "r2")
        self.real_pdf(self.root / values["plan"], [80])
        self.real_pdf(self.root / values["elevations"][0], [90])
        self.event("create", creator="Create-Room2", artifacts=values)
        self.check()
        self.summary()
        self.event("release")
        with self.assertRaisesRegex(w.WorkflowError, "Stale sheet packet"):
            w.build_index(self.root)
        with self.assertRaisesRegex(w.WorkflowError, "pinned historical artifact"):
            w.merge(self.root, "Room2/r1/Plan.pdf")
        w.validate(self.root)
        w.packets(self.root, sheet="Room2")
        self.assertIn("PDF SET", Path(w.build_index(self.root)).read_text(encoding="utf-8"))
        self.assertEqual(self.page_fingerprints(packet), self.page_fingerprints(self.root / values["plan"]) +
                         self.page_fingerprints(self.root / values["elevations"][0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
