from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass


logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


MAX_SIZE_MB = _env_int("FILE_EXTRACT_MAX_SIZE_MB", 25)
MAX_PAGES = _env_int("FILE_EXTRACT_MAX_PAGES", 15)


@dataclass
class ExtractionResult:
    text: str
    page_count: int | None
    status: str
    error: str | None = None


def compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def extract_text_from_file(file_bytes: bytes, mime_type: str) -> ExtractionResult:
    if len(file_bytes) > MAX_SIZE_MB * 1024 * 1024:
        return ExtractionResult(
            text="",
            page_count=None,
            status="failed",
            error=f"File too large (> {MAX_SIZE_MB} MB)",
        )

    if mime_type == "application/pdf":
        return _extract_pdf(file_bytes)

    if mime_type.startswith("image/"):
        return _ocr_image(file_bytes)

    return ExtractionResult(
        text="",
        page_count=None,
        status="failed",
        error=f"Unsupported mime_type: {mime_type}",
    )


def _extract_pdf(file_bytes: bytes) -> ExtractionResult:
    text, page_count, has_text = _extract_pdf_text(file_bytes)
    if has_text:
        return ExtractionResult(text=text, page_count=page_count, status="extracted")

    ocr_text, ocr_pages, err = _ocr_pdf(file_bytes)
    if err:
        return ExtractionResult(
            text="",
            page_count=ocr_pages,
            status="failed",
            error=err,
        )

    status = "extracted" if ocr_text else "partial"
    return ExtractionResult(text=ocr_text, page_count=ocr_pages, status=status)


def _extract_pdf_text(file_bytes: bytes) -> tuple[str, int | None, bool]:
    try:
        import io
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        text_parts = []
        page_count = len(reader.pages)
        for i, page in enumerate(reader.pages):
            if i >= MAX_PAGES:
                break
            parsed = page.extract_text()
            if parsed:
                text_parts.append(parsed)
        combined = "\n".join(text_parts).strip()
        return combined, page_count, bool(combined)
    except ImportError:
        logger.error("pypdf not installed, cannot extract PDF text")
        return "", None, False
    except Exception as e:
        logger.error(f"PDF text extraction failed: {e}")
        return "", None, False


def _ocr_pdf(file_bytes: bytes) -> tuple[str, int | None, str | None]:
    try:
        from pdf2image import convert_from_bytes
    except ImportError:
        return "", None, "pdf2image not installed for PDF OCR"

    try:
        images = convert_from_bytes(file_bytes, first_page=1, last_page=MAX_PAGES)
    except Exception as e:
        return "", None, f"pdf2image failed: {e}"

    if not images:
        return "", 0, "No pages rendered for OCR"

    text_parts = []
    for img in images:
        ocr_text, err = _ocr_image_pil(img)
        if err:
            return "", len(images), err
        if ocr_text:
            text_parts.append(ocr_text)
    return "\n".join(text_parts).strip(), len(images), None


def _ocr_image(file_bytes: bytes) -> ExtractionResult:
    try:
        from PIL import Image
    except ImportError:
        return ExtractionResult(
            text="",
            page_count=1,
            status="failed",
            error="Pillow not installed for OCR",
        )

    try:
        import io

        image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    except Exception as e:
        return ExtractionResult(
            text="",
            page_count=1,
            status="failed",
            error=f"Failed to load image: {e}",
        )

    text, err = _ocr_image_pil(image)
    if err:
        return ExtractionResult(text="", page_count=1, status="failed", error=err)
    return ExtractionResult(text=text, page_count=1, status="extracted")


def _ocr_image_pil(image) -> tuple[str, str | None]:
    try:
        import numpy as np
        from paddleocr import PaddleOCR
    except ImportError:
        return "", "paddleocr or numpy not installed for OCR"

    ocr = _get_ocr()
    img_array = np.array(image)
    try:
        result = ocr.ocr(img_array, cls=True)
    except Exception as e:
        return "", f"OCR failed: {e}"

    text_parts = []
    for line in result:
        if not line:
            continue
        for item in line:
            if len(item) >= 2:
                text_parts.append(str(item[1][0]))
    return "\n".join(text_parts).strip(), None


_OCR_INSTANCE = None


def _get_ocr():
    global _OCR_INSTANCE
    if _OCR_INSTANCE is None:
        from paddleocr import PaddleOCR

        _OCR_INSTANCE = PaddleOCR(use_angle_cls=True, lang="ch", use_gpu=False)
    return _OCR_INSTANCE
