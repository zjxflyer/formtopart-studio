"""Bounded local source import and PDFium previews; no external renderer needed."""
from __future__ import annotations

import hashlib
import io
import math
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
import pypdfium2 as pdfium

MAX_UPLOAD = 50 * 1024 * 1024
_PDF_RENDER_LOCK = threading.Lock()


def _prepared_pdf_pages(content, digest, document_id, prepared_cache):
    """Read only a server-supplied, bundled cache; ordinary imports never set it."""
    if prepared_cache is None:
        return None
    try:
        root = Path(prepared_cache["root"]).resolve()
        record = next(item for item in prepared_cache["documents"] if item["document_id"] == document_id)
        if record["source_sha256"] != digest:
            return None
        records = record["pages"]
        if (not isinstance(records, list) or not 1 <= len(records) <= 40
                or type(record["page_count"]) is not int or record["page_count"] != len(records)):
            return None
        pages, images = [], []
        # Check the original PDF's actual page count and rotated dimensions,
        # without rerendering it or repeating expensive text extraction.
        with _PDF_RENDER_LOCK, pdfium.PdfDocument(content) as document:
            if len(document) != len(records):
                return None
            for number, item in enumerate(records, 1):
                if type(item["number"]) is not int or item["number"] != number:
                    return None
                page = document[number - 1]
                try:
                    width, height = page.get_size()
                finally:
                    page.close()
                for key, actual in (("width_pt", width), ("height_pt", height)):
                    value = item[key]
                    if (type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 20000
                            or not math.isclose(value, actual, abs_tol=1e-6, rel_tol=0)):
                        return None
                text = item["text"]
                filename = item["image"]
                if not isinstance(text, str) or len(text) > 100000:
                    return None
                if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}\.png", filename):
                    return None
                path = (root / filename).resolve()
                if path.parent != root or not path.is_file() or path.stat().st_size > 12 * 1024 * 1024:
                    return None
                data = path.read_bytes()
                if not isinstance(item["sha256"], str) or hashlib.sha256(data).hexdigest() != item["sha256"]:
                    return None
                with Image.open(io.BytesIO(data)) as image:
                    if (image.format != "PNG" or not 1 <= image.width <= 1800 or not 1 <= image.height <= 1800
                            or type(item["width_px"]) is not int or type(item["height_px"]) is not int
                            or (image.width, image.height) != (item["width_px"], item["height_px"])
                            or abs(image.width / width - image.height / height) > 2 / max(width, height)):
                        return None
                    image.verify()
                pages.append({"number": number, "width_pt": width, "height_pt": height,
                              "text": text, "preview": f"page-{number}.png"})
                images.append(data)
        return pages, images
    except (OSError, ValueError, TypeError, KeyError, StopIteration, OverflowError,
            pdfium.PdfiumError, Image.DecompressionBombError):
        # A missing/stale/corrupt optional cache always uses the ordinary reader.
        return None


def import_document(repository, project_id: str, name: str, content: bytes, document_id: str | None = None,
                    *, prepared_cache=None):
    suffix = source_suffix(name, content)
    digest = hashlib.sha256(content).hexdigest()
    for document in repository.get(project_id)["documents"]:
        if document["sha256"] == digest:
            return document
    document_id = document_id or "DOC_" + uuid4().hex
    if not re.fullmatch(r"DOC_[a-f0-9]{32}", document_id):
        raise ValueError("Invalid source identity / 原图标识无效")
    directory = repository.directory(project_id) / "sources" / document_id
    with prepare_document_assets(directory, document_id, name, content, suffix, digest,
                                 prepared_cache=prepared_cache) as metadata:
        repository.add_document(project_id, metadata)
    return metadata


def source_suffix(name, content):
    if not content or len(content) > MAX_UPLOAD:
        raise ValueError("Source must be nonempty and under 50 MB / 原图不能为空，且须小于 50 MB")
    suffix = Path(name).suffix.lower()
    if suffix not in (".pdf", ".png", ".jpg", ".jpeg"):
        raise ValueError("Use PDF, PNG or JPEG / 请使用 PDF、PNG 或 JPEG")
    return suffix


@contextmanager
def prepare_document_assets(directory, document_id, name, content, suffix, digest, *, prepared_cache=None):
    """Write a source and its pages, releasing the files if metadata publication fails."""
    directory.mkdir(parents=True, exist_ok=False)
    original = directory / ("original" + suffix)
    pages = []
    try:
        original.write_bytes(content)
        if suffix == ".pdf":
            if not content.startswith(b"%PDF"):
                raise ValueError("The source is not a valid PDF / 原图不是有效的 PDF")
            prepared = _prepared_pdf_pages(content, digest, document_id, prepared_cache)
            if prepared is not None:
                pages, images = prepared
                for page, data in zip(pages, images):
                    (directory / page["preview"]).write_bytes(data)
            else:
                reader = PdfReader(io.BytesIO(content))
                if reader.is_encrypted or not 1 <= len(reader.pages) <= 40:
                    raise ValueError("Use an unlocked PDF with 1–40 pages / 请使用 1–40 页的未加密 PDF")
                with _PDF_RENDER_LOCK, pdfium.PdfDocument(content) as document:
                    for index in range(len(document)):
                        page = document[index]
                        try:
                            width, height = page.get_size()
                            scale = min(2.0, 1800 / max(width, height))
                            bitmap = page.render(scale=scale)
                            try:
                                image = bitmap.to_pil()
                                preview = directory / f"page-{index + 1}.png"
                                image.save(preview, format="PNG")
                            finally:
                                bitmap.close()
                        finally:
                            page.close()
                        pages.append({"number": index + 1, "width_pt": width, "height_pt": height,
                                      "text": (reader.pages[index].extract_text() or "")[:100000],
                                      "preview": preview.name})
            media_type = "application/pdf"
        else:
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > 60_000_000:
                    raise ValueError("Image is too large; use a smaller crop / 图像过大，请裁剪后重试")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((1800, 1800))
                preview = directory / "page-1.png"
                image.save(preview, format="PNG")
                pages.append({"number": 1, "text": "", "preview": preview.name,
                              "width_pt": image.width, "height_pt": image.height})
            media_type = "image/png" if suffix == ".png" else "image/jpeg"
        metadata = {"id": document_id, "name": Path(name).name, "original_name": Path(name).name,
                    "sha256": digest, "media_type": media_type, "page_count": len(pages),
                    "local_path": str(original), "pages": pages}
        yield metadata
    except Exception:
        # Only known files inside this uniquely created import area are removed.
        for path in directory.iterdir():
            if path.is_file() and path.parent == directory:
                path.unlink(missing_ok=True)
        directory.rmdir()
        raise


def public_document(project_id, document):
    source_url = f"/api/studio/projects/{project_id}/documents/{document['id']}/pages"
    return {key: value for key, value in document.items() if key not in ("local_path", "pages")} | {
        "pages": [{key: value for key, value in page.items() if key != "preview"} | {
            "preview_url": f"{source_url}/{page['number']}?source={document['sha256']}"
        } for page in document["pages"]]}
