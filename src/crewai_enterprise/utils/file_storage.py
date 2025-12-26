"""
File Storage Manager.

Handles downloading, storing, and managing files from WeCom messages.
Files are stored locally and tracked for LLM context.
"""

from __future__ import annotations

import logging
import os
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests


logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Information about a stored file."""

    file_id: str
    chat_id: str
    filename: str
    file_type: str
    file_path: str
    size_bytes: int
    created_at: datetime = field(default_factory=datetime.now)
    media_id: str | None = None

    @property
    def extension(self) -> str:
        """Get file extension."""
        return Path(self.filename).suffix.lower()

    @property
    def is_image(self) -> bool:
        """Check if file is an image."""
        return self.extension in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")

    @property
    def is_document(self) -> bool:
        """Check if file is a document."""
        return self.extension in (
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".txt",
            ".md",
        )


class FileStorageError(Exception):
    """Raised when file storage operation fails."""

    pass


class FileStorageManager:
    """
    Manages file storage for WeCom messages.

    Files are organized by chat_id and stored with unique identifiers.
    """

    def __init__(
        self,
        base_path: str = "./data/files",
        wecom_corp_id: str | None = None,
        wecom_secret: str | None = None,
    ):
        """
        Initialize file storage manager.

        Args:
            base_path: Base directory for file storage
            wecom_corp_id: WeCom Corp ID for downloading files
            wecom_secret: WeCom App Secret for downloading files
        """
        self.base_path: Path = Path(base_path)
        self.wecom_corp_id: str = wecom_corp_id or os.getenv("WECOM_CORP_ID", "")
        self.wecom_secret: str = wecom_secret or os.getenv("WECOM_SECRET", "")
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

        # Ensure base directory exists
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_access_token(self) -> str:
        """Get WeCom access token for downloading files."""
        # Check if token exists and is not expired
        if (
            self._access_token
            and self._token_expires_at
            and datetime.now() < self._token_expires_at
        ):
            return self._access_token

        if not self.wecom_corp_id or not self.wecom_secret:
            raise FileStorageError("WeCom credentials not configured")

        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.wecom_corp_id}&corpsecret={self.wecom_secret}"

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise FileStorageError(f"Failed to get access token: {e}") from e

        if data.get("errcode") == 0:
            self._access_token = data.get("access_token")
            # Token expires in expires_in seconds, refresh 5 minutes early
            expires_in = data.get("expires_in", 7200)
            from datetime import timedelta

            self._token_expires_at = datetime.now() + timedelta(
                seconds=expires_in - 300
            )
            logger.info(
                f"Got new WeCom access token, expires at {self._token_expires_at}"
            )
            return self._access_token
        else:
            raise FileStorageError(
                f"WeCom token error - Code: {data.get('errcode')}, Msg: {data.get('errmsg')}"
            )

    def _get_chat_dir(self, chat_id: str) -> Path:
        """Get directory for a specific chat."""
        safe_chat_id = self._sanitize_filename(chat_id)
        chat_dir = self.base_path / safe_chat_id
        chat_dir.mkdir(parents=True, exist_ok=True)
        return chat_dir

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as filename."""
        # Remove or replace unsafe characters
        unsafe_chars = '<>:"/\\|?*'
        for char in unsafe_chars:
            name = name.replace(char, "_")
        return name[:100]  # Limit length

    def _generate_file_id(self, chat_id: str, media_id: str) -> str:
        """Generate unique file ID."""
        content = f"{chat_id}:{media_id}:{datetime.now().isoformat()}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    def download_wecom_media(
        self,
        chat_id: str,
        media_id: str,
        filename: str | None = None,
    ) -> FileInfo:
        """
        Download a file from WeCom and save it.

        Args:
            chat_id: The chat/group ID
            media_id: WeCom media ID
            filename: Optional filename override

        Returns:
            FileInfo with saved file details
        """
        token = self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token={token}&media_id={media_id}"

        try:
            response = requests.get(url, timeout=60, stream=True)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise FileStorageError(f"Failed to download media: {e}") from e

        # Check if response is JSON error
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            data = response.json()
            raise FileStorageError(
                f"WeCom media error - Code: {data.get('errcode')}, Msg: {data.get('errmsg')}"
            )

        # Get filename from Content-Disposition or use provided
        if not filename:
            content_disp = response.headers.get("Content-Disposition", "")
            if "filename=" in content_disp:
                filename = content_disp.split("filename=")[-1].strip('"')
            else:
                # Generate filename based on content type
                ext = self._get_extension_from_content_type(content_type)
                filename = f"file_{media_id[:8]}{ext}"

        # Save file
        file_id = self._generate_file_id(chat_id, media_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = self._sanitize_filename(filename)
        final_filename = f"{timestamp}_{file_id}_{safe_filename}"

        chat_dir = self._get_chat_dir(chat_id)
        file_path = chat_dir / final_filename

        size_bytes = 0
        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                size_bytes += len(chunk)

        logger.info(f"Saved file: {file_path} ({size_bytes} bytes)")

        # Determine file type
        ext = Path(safe_filename).suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            file_type = "image"
        elif ext in (".pdf", ".doc", ".docx"):
            file_type = "document"
        elif ext in (".xls", ".xlsx"):
            file_type = "spreadsheet"
        elif ext in (".mp4", ".avi", ".mov"):
            file_type = "video"
        elif ext in (".mp3", ".wav", ".amr"):
            file_type = "audio"
        else:
            file_type = "file"

        return FileInfo(
            file_id=file_id,
            chat_id=chat_id,
            filename=safe_filename,
            file_type=file_type,
            file_path=str(file_path),
            size_bytes=size_bytes,
            media_id=media_id,
        )

    def save_file_from_bytes(
        self,
        chat_id: str,
        content: bytes,
        filename: str,
    ) -> FileInfo:
        """
        Save file content directly.

        Args:
            chat_id: The chat/group ID
            content: File content as bytes
            filename: Filename to save as

        Returns:
            FileInfo with saved file details
        """
        file_id = self._generate_file_id(chat_id, filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = self._sanitize_filename(filename)
        final_filename = f"{timestamp}_{file_id}_{safe_filename}"

        chat_dir = self._get_chat_dir(chat_id)
        file_path = chat_dir / final_filename

        with open(file_path, "wb") as f:
            f.write(content)

        ext = Path(safe_filename).suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            file_type = "image"
        else:
            file_type = "file"

        return FileInfo(
            file_id=file_id,
            chat_id=chat_id,
            filename=safe_filename,
            file_type=file_type,
            file_path=str(file_path),
            size_bytes=len(content),
        )

    def get_file_path(self, chat_id: str, file_id: str) -> str | None:
        """Find file path by file_id."""
        chat_dir = self._get_chat_dir(chat_id)
        for file_path in chat_dir.iterdir():
            if file_id in file_path.name:
                return str(file_path)
        return None

    def list_files(self, chat_id: str) -> list[str]:
        """List all files for a chat."""
        chat_dir = self._get_chat_dir(chat_id)
        return [str(f) for f in chat_dir.iterdir() if f.is_file()]

    def _get_extension_from_content_type(self, content_type: str) -> str:
        """Get file extension from Content-Type header."""
        mapping = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "application/pdf": ".pdf",
            "application/msword": ".doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/vnd.ms-excel": ".xls",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
            "text/plain": ".txt",
            "audio/amr": ".amr",
            "video/mp4": ".mp4",
        }
        return mapping.get(content_type.split(";")[0], ".bin")


# Global singleton with thread-safe access
_file_manager: FileStorageManager | None = None
_file_manager_lock = __import__("threading").Lock()


def get_file_manager(base_path: str = "./data/files") -> FileStorageManager:
    """Get or create global file storage manager (thread-safe)."""
    global _file_manager
    if _file_manager is None:
        with _file_manager_lock:
            # Double-check locking pattern
            if _file_manager is None:
                _file_manager = FileStorageManager(base_path=base_path)
    return _file_manager
