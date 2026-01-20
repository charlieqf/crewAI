from __future__ import annotations

import asyncio
import logging
import os

from src.crewai_enterprise.utils.file_content_store import FileContentStore
from src.crewai_enterprise.utils.file_extractor import (
    ExtractionResult,
    compute_file_hash,
    extract_text_from_file,
)


logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


EXTRACT_TIMEOUT_SEC = _env_int("FILE_EXTRACT_TIMEOUT_SEC", 60)
EXTRACT_CONCURRENCY = _env_int("FILE_EXTRACT_CONCURRENCY", 1)

_SEMAPHORE = asyncio.Semaphore(EXTRACT_CONCURRENCY)


def schedule_file_extraction(
    *,
    chat_id: str | None,
    wecom_msg_id: str | None,
    storage_key: str | None,
    filename: str | None,
    mime_type: str,
    file_bytes: bytes,
) -> str:
    file_hash = compute_file_hash(file_bytes)
    store = FileContentStore()
    store.upsert_pending(
        file_hash=file_hash,
        chat_id=chat_id,
        wecom_msg_id=wecom_msg_id,
        storage_key=storage_key,
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(file_bytes),
    )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[FILE_EXTRACT] No running event loop; skipping async extraction")
        return file_hash

    loop.create_task(
        _run_extraction(
            file_hash=file_hash,
            mime_type=mime_type,
            file_bytes=file_bytes,
        )
    )
    return file_hash


async def _run_extraction(
    *,
    file_hash: str,
    mime_type: str,
    file_bytes: bytes,
) -> None:
    async with _SEMAPHORE:
        loop = asyncio.get_running_loop()
        try:
            result: ExtractionResult = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: extract_text_from_file(file_bytes, mime_type)
                ),
                timeout=EXTRACT_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[FILE_EXTRACT] Timeout for hash={file_hash}")
            FileContentStore().mark_failed(
                file_hash=file_hash,
                error_message=f"Extraction timeout ({EXTRACT_TIMEOUT_SEC}s)",
            )
            return
        except Exception as e:
            logger.error(f"[FILE_EXTRACT] Unexpected error: {e}")
            FileContentStore().mark_failed(
                file_hash=file_hash,
                error_message=f"Extraction error: {e}",
            )
            return

        store = FileContentStore()
        if result.status == "extracted":
            store.mark_extracted(
                file_hash=file_hash,
                extracted_text=result.text,
                extracted_summary=None,
                page_count=result.page_count,
                status="extracted",
            )
        elif result.status == "partial":
            store.mark_extracted(
                file_hash=file_hash,
                extracted_text=result.text,
                extracted_summary=None,
                page_count=result.page_count,
                status="partial",
            )
        else:
            store.mark_failed(
                file_hash=file_hash,
                error_message=result.error or "Extraction failed",
            )
