"""Verify sample source upgrades with ordinary saved profiles and older archives."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from studio.reference_demo import load_github_sample
from studio.repository import Repository
from studio.server import create_app


class GithubSampleUpgradeTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        scratch = Path(temporary.name)
        self.current_bundle = Path(__file__).resolve().parents[1] / "public-sample"
        self.legacy_bundle = scratch / "legacy"
        self.projects = scratch / "projects"
        self.repository = Repository(self.projects)
        manifest, seed = load_github_sample(self.current_bundle)
        self.current_digest = manifest["source_sha256"]
        (self.legacy_bundle / "showcase").mkdir(parents=True)
        shutil.copytree(self.current_bundle / "reference-demo", self.legacy_bundle / "reference-demo")

        writer = PdfWriter()
        for _ in range(3):
            writer.add_blank_page(width=810, height=540)
        stream = BytesIO()
        writer.write(stream)
        pdf = stream.getvalue()
        self.legacy_digest = sha256(pdf).hexdigest()
        fix_legacy_digest = patch("studio.reference_demo.GITHUB_ILLUSTRATIONS_SHA256", self.legacy_digest)
        fix_legacy_digest.start()
        self.addCleanup(fix_legacy_digest.stop)
        self.doc_id = "DOC_" + self.legacy_digest[:32]

        with ZipFile(seed) as archive:
            project = json.loads(archive.read("project.json"))
        document, = project["documents"]
        for version in project["history"]:
            version["model"] = version["model"].replace(document["id"], self.doc_id)
        document.update(id=self.doc_id, name="Legacy sample illustrations.pdf", sha256=self.legacy_digest,
                        asset=f"sources/{self.doc_id}.pdf")
        legacy_archive = self.legacy_bundle / "showcase" / manifest["archive"]
        with ZipFile(legacy_archive, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("project.json", json.dumps(project))
            archive.writestr(document["asset"], pdf)
        manifest.update(archive_sha256=sha256(legacy_archive.read_bytes()).hexdigest(), source_sha256=self.legacy_digest)
        (legacy_archive.parent / "showcase.json").write_text(json.dumps(manifest), encoding="utf-8")

    def app(self, bundle):
        return create_app(self.projects, github_distribution=True, github_sample_root=bundle, allow_ai=False)

    def test_upgrade_keeps_revisions_and_upgrades_legacy_archive(self):
        with TestClient(self.app(self.legacy_bundle)) as client:
            sample, = client.get("/api/studio/projects").json()
            base = f"/api/studio/projects/{sample['id']}"
            result = self.repository.restore(sample["id"], 1, 1)
            result = self.repository.rename(sample["id"], "My kitchen review", result["revision"])
            previous = client.get(base).json()
            preview = client.get(previous["documents"][0]["pages"][0]["preview_url"]).content
            old_archive = client.get(base + "/export").content
            scene = client.get(base + "/scene").json()
            bom = client.get(base + "/bom").json()
            other = self.repository.create("Another project")

        with TestClient(self.app(self.current_bundle)) as client:
            after = client.get(base).json()
            self.assertEqual((after["name"], after["revision"], after["history"]),
                             ("My kitchen review", 2, previous["history"]))
            self.assertEqual(self.repository.get(sample["id"])["model"], result["model"])
            self.assertEqual(self.repository.get(other["id"]), other)
            self.assertEqual(client.get(base + "/scene").json(), scene)
            self.assertEqual(client.get(base + "/bom").json(), bom)
            doc, = after["documents"]
            self.assertEqual((doc["id"], doc["sha256"], doc["page_count"]), (self.doc_id, self.current_digest, 3))
            self.assertNotEqual(doc["pages"][0]["preview_url"], previous["documents"][0]["pages"][0]["preview_url"])
            self.assertNotEqual(client.get(doc["pages"][0]["preview_url"]).content, preview)
            current_archive = client.post("/api/studio/import", files={"file": ("old-sample.vwc", old_archive)})
            self.assertEqual(current_archive.status_code, 200, current_archive.text[:500])
            self.assertEqual(current_archive.json()["documents"][0]["sha256"], self.current_digest)

        with TestClient(self.app(self.current_bundle)) as client:
            self.assertEqual(client.get(base).json()["documents"], after["documents"])

    def test_keeps_illustrations_for_saved_evidence_pinned_to_their_regions(self):
        with TestClient(self.app(self.legacy_bundle)) as client:
            sample, = client.get("/api/studio/projects").json()
            stored = self.repository.get(sample["id"])
            model = stored["model"]
            model["views"][0]["region"] = [0.1, 0.1, 0.9, 0.9]
            pending = self.repository.proposal(sample["id"], 1, model, "Save a crop from the original illustrations")
            saved = self.repository.apply(sample["id"], pending["id"], 1)

        base = f"/api/studio/projects/{sample['id']}"
        with TestClient(self.app(self.current_bundle)) as client:
            project = client.get(base).json()
            self.assertEqual([doc["sha256"] for doc in project["documents"]],
                             [self.current_digest, self.legacy_digest])
            self.assertEqual(project["documents"][1]["id"], self.doc_id)
            self.assertEqual(self.repository.get(sample["id"])["model"], saved["model"])
            self.assertEqual(client.get(base + "/export").status_code, 200)

        with TestClient(self.app(self.current_bundle)) as client:
            self.assertEqual(client.get(base).json()["documents"], project["documents"])
