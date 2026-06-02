from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterator, Optional


@dataclass(frozen=True)
class PDFPageData:
    index: int
    width: float
    height: float
    text: str
    image_count: int


class PDFInspector:
    def __init__(self, pdf_path: Path) -> None:
        self.pdf_path = pdf_path
        self._reader: Optional[object] = None
        self._load_reader()

    def _has_eof_marker(self) -> bool:
        try:
            with self.pdf_path.open("rb") as handle:
                try:
                    handle.seek(-2048, os.SEEK_END)
                except OSError:
                    handle.seek(0)
                tail = handle.read()
            return b"%%EOF" in tail
        except OSError:
            return False

    def _load_reader(self) -> None:
        if not self._has_eof_marker():
            self._reader = None
            return
        reader = None
        for module_name in ("pypdf", "PyPDF2"):
            try:
                module = __import__(module_name, fromlist=["PdfReader"])
                reader = module.PdfReader(str(self.pdf_path), strict=False)
                break
            except Exception:
                reader = None
        self._reader = reader

    def page_count(self) -> int:
        if self._reader is None:
            return 1
        try:
            return len(self._reader.pages)
        except Exception:
            return 1

    def iter_pages(self) -> Iterator[PDFPageData]:
        if self._reader is None:
            yield PDFPageData(index=0, width=612.0, height=792.0, text="", image_count=0)
            return
        for idx, page in enumerate(self._reader.pages):
            width = 612.0
            height = 792.0
            try:
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
            except Exception:
                pass
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            image_count = 0
            try:
                images = getattr(page, "images", None)
                if images is not None:
                    image_count = len(images)
                else:
                    resources = page.get("/Resources", {}) if hasattr(page, "get") else {}
                    x_objects = resources.get("/XObject", {}) if isinstance(resources, dict) else {}
                    if hasattr(x_objects, "items"):
                        for _, obj in x_objects.items():
                            try:
                                subtype = obj.get("/Subtype") if hasattr(obj, "get") else None
                                if subtype == "/Image":
                                    image_count += 1
                            except Exception:
                                continue
            except Exception:
                image_count = 0
            yield PDFPageData(
                index=idx,
                width=width,
                height=height,
                text=text,
                image_count=image_count,
            )
