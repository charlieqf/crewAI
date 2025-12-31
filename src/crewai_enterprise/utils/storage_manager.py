"""
Storage Manager - Unified Cloud Storage abstraction layer.

Provides pluggable storage providers (Qiniu, S3, Local) for WeCom bot files.
Replaces the Base64-in-DB approach with cloud URLs for cross-bot accessibility.
"""

from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    """Result of a file upload operation."""
    
    url: str  # Public or signed URL to access the file
    key: str  # Storage key/path for the file
    provider: str  # Provider name (qiniu, s3, local)
    uploaded_at: datetime
    expires_at: datetime | None = None  # For temporary URLs


class StorageProvider(ABC):
    """Abstract base class for storage providers."""
    
    @abstractmethod
    def upload(
        self,
        data: bytes,
        filename: str,
        content_type: str | None = None,
        ttl_days: int | None = None,
    ) -> UploadResult:
        """
        Upload file data to storage.
        
        Args:
            data: File bytes
            filename: Original filename (used for extension/type detection)
            content_type: MIME type (optional, will be guessed if not provided)
            ttl_days: Time-to-live in days (for auto-deletion, if supported)
        
        Returns:
            UploadResult with URL and metadata
        """
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Delete a file from storage.
        
        Args:
            key: Storage key returned from upload
        
        Returns:
            True if deleted successfully
        """
        pass
    
    @abstractmethod
    def get_url(self, key: str, expires_in_seconds: int | None = None) -> str:
        """
        Get a URL to access the file.
        
        Args:
            key: Storage key
            expires_in_seconds: Generate a signed URL valid for this duration
        
        Returns:
            Public or signed URL
        """
        pass


class LocalStorageProvider(StorageProvider):
    """
    Local disk storage provider (for development/testing).
    
    NOT recommended for production due to:
    - No redundancy/backup
    - Limited by Kamatera disk space
    - No CDN acceleration
    """
    
    def __init__(self, base_path: str = "data/storage"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)
        logger.info(f"LocalStorageProvider initialized: {base_path}")
    
    def upload(
        self,
        data: bytes,
        filename: str,
        content_type: str | None = None,
        ttl_days: int | None = None,
    ) -> UploadResult:
        # Generate unique key
        ext = os.path.splitext(filename)[1]
        key = f"{uuid.uuid4().hex}{ext}"
        filepath = os.path.join(self.base_path, key)
        
        # Write to disk
        with open(filepath, "wb") as f:
            f.write(data)
        
        logger.info(f"Uploaded {filename} to local storage: {key}")
        
        return UploadResult(
            url=f"file://{os.path.abspath(filepath)}",
            key=key,
            provider="local",
            uploaded_at=datetime.now(),
        )
    
    def delete(self, key: str) -> bool:
        filepath = os.path.join(self.base_path, key)
        try:
            os.remove(filepath)
            return True
        except Exception as e:
            logger.error(f"Failed to delete {key}: {e}")
            return False
    
    def get_url(self, key: str, expires_in_seconds: int | None = None) -> str:
        filepath = os.path.join(self.base_path, key)
        return f"file://{os.path.abspath(filepath)}"


class QiniuProvider(StorageProvider):
    """
    Qiniu Cloud storage provider (七牛云).
    
    Best for:
    - Servers in China mainland
    - Fast CDN for WeCom users
    - Cost-effective storage
    
    Requires:
        pip install qiniu
        
    Environment variables:
        QINIU_ACCESS_KEY
        QINIU_SECRET_KEY
        QINIU_BUCKET
        QINIU_DOMAIN (CDN domain)
    """
    
    def __init__(
        self,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        domain: str | None = None,
    ):
        try:
            from qiniu import Auth, put_data, BucketManager
        except ImportError:
            raise ImportError(
                "Qiniu SDK not installed. Run: pip install qiniu"
            )
        
        self.access_key = access_key or os.getenv("QINIU_ACCESS_KEY")
        self.secret_key = secret_key or os.getenv("QINIU_SECRET_KEY")
        self.bucket = bucket or os.getenv("QINIU_BUCKET")
        self.domain = domain or os.getenv("QINIU_DOMAIN")
        
        if not all([self.access_key, self.secret_key, self.bucket, self.domain]):
            raise ValueError(
                "Missing Qiniu credentials. Set QINIU_ACCESS_KEY, "
                "QINIU_SECRET_KEY, QINIU_BUCKET, QINIU_DOMAIN"
            )
        
        self.auth = Auth(self.access_key, self.secret_key)
        self.bucket_manager = BucketManager(self.auth)
        self.protocol = os.getenv("STORAGE_QINIU_PROTOCOL", "https")
        
        logger.info(f"QiniuProvider initialized: bucket={self.bucket}, protocol={self.protocol}")
    
    def upload(
        self,
        data: bytes,
        filename: str,
        content_type: str | None = None,
        ttl_days: int | None = None,
    ) -> UploadResult:
        from qiniu import put_data
        
        # Generate unique key with timestamp
        ext = os.path.splitext(filename)[1]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        key = f"wecom/{timestamp}/{uuid.uuid4().hex}{ext}"
        
        # Generate upload token
        token = self.auth.upload_token(self.bucket, key, 3600)
        
        # Upload
        ret, info = put_data(token, key, data)
        
        if info.status_code != 200:
            raise Exception(f"Qiniu upload failed: {info}")
        
        # Generate URL
        url = f"{self.protocol}://{self.domain}/{key}"
        
        logger.info(f"Uploaded {filename} to Qiniu: {key}")
        
        # Note: Qiniu lifecycle rules should be configured in console
        # for auto-deletion based on ttl_days
        
        return UploadResult(
            url=url,
            key=key,
            provider="qiniu",
            uploaded_at=datetime.now(),
            expires_at=None,  # Permanent unless lifecycle rules apply
        )
    
    def delete(self, key: str) -> bool:
        try:
            ret, info = self.bucket_manager.delete(self.bucket, key)
            return info.status_code == 200
        except Exception as e:
            logger.error(f"Failed to delete from Qiniu {key}: {e}")
            return False
    
    def get_url(self, key: str, expires_in_seconds: int | None = None) -> str:
        base_url = f"{self.protocol}://{self.domain}/{key}"
        
        if expires_in_seconds:
            # Generate private signed URL
            return self.auth.private_download_url(base_url, expires_in_seconds)
        
        return base_url


class S3Provider(StorageProvider):
    """
    AWS S3 storage provider.
    
    Best for:
    - Global deployment
    - Enterprise-grade reliability
    - Advanced features (versioning, encryption)
    
    Requires:
        pip install boto3
        
    Environment variables:
        AWS_ACCESS_KEY_ID
        AWS_SECRET_ACCESS_KEY
        AWS_REGION
        S3_BUCKET
    """
    
    def __init__(
        self,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
        bucket: str | None = None,
    ):
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 not installed. Run: pip install boto3"
            )
        
        self.access_key = access_key or os.getenv("AWS_ACCESS_KEY_ID")
        self.secret_key = secret_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self.bucket = bucket or os.getenv("S3_BUCKET")
        
        if not all([self.access_key, self.secret_key, self.bucket]):
            raise ValueError(
                "Missing S3 credentials. Set AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY, S3_BUCKET"
            )
        
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )
        
        logger.info(f"S3Provider initialized: bucket={self.bucket}")
    
    def upload(
        self,
        data: bytes,
        filename: str,
        content_type: str | None = None,
        ttl_days: int | None = None,
    ) -> UploadResult:
        # Generate unique key
        ext = os.path.splitext(filename)[1]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        key = f"wecom/{timestamp}/{uuid.uuid4().hex}{ext}"
        
        # Upload
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        
        if ttl_days:
            # Set lifecycle expiration metadata
            expires = datetime.now() + timedelta(days=ttl_days)
            extra_args["Metadata"] = {"ttl-days": str(ttl_days)}
        
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            **extra_args,
        )
        
        # Generate URL
        url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"
        
        logger.info(f"Uploaded {filename} to S3: {key}")
        
        return UploadResult(
            url=url,
            key=key,
            provider="s3",
            uploaded_at=datetime.now(),
        )
    
    def delete(self, key: str) -> bool:
        try:
            self.s3_client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete from S3 {key}: {e}")
            return False
    
    def get_url(self, key: str, expires_in_seconds: int | None = None) -> str:
        if expires_in_seconds:
            # Generate presigned URL
            return self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in_seconds,
            )
        
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"


class StorageManager:
    """
    Main entry point for storage operations.
    
    Automatically selects the appropriate provider based on environment variables.
    """
    
    def __init__(self, provider: StorageProvider | None = None):
        if provider:
            self.provider = provider
        else:
            # Auto-detect from environment
            provider_name = os.getenv("STORAGE_PROVIDER", "local").lower()
            
            if provider_name == "qiniu":
                self.provider = QiniuProvider()
            elif provider_name == "s3":
                self.provider = S3Provider()
            else:
                # Default to local for development
                self.provider = LocalStorageProvider()
                logger.warning(
                    "Using LocalStorageProvider. Set STORAGE_PROVIDER=qiniu or s3 for production."
                )
    
    def upload_file(
        self,
        data: bytes,
        filename: str,
        content_type: str | None = None,
        ttl_days: int | None = 7,  # Default 7 days auto-deletion
    ) -> UploadResult:
        """
        Upload a file to cloud storage.
        
        Args:
            data: File bytes
            filename: Original filename
            content_type: MIME type
            ttl_days: Auto-delete after N days (if provider supports)
        
        Returns:
            UploadResult with public URL
        """
        return self.provider.upload(data, filename, content_type, ttl_days)
    
    def delete_file(self, key: str) -> bool:
        """Delete a file from storage."""
        return self.provider.delete(key)
    
    def get_url(self, key: str, expires_in_seconds: int | None = None) -> str:
        """Get URL to access a file."""
        return self.provider.get_url(key, expires_in_seconds)


# Global singleton
_storage_manager: StorageManager | None = None
_storage_lock = __import__("threading").Lock()


def get_storage_manager() -> StorageManager:
    """Get or create global storage manager (thread-safe)."""
    global _storage_manager
    if _storage_manager is None:
        with _storage_lock:
            if _storage_manager is None:
                _storage_manager = StorageManager()
    return _storage_manager
