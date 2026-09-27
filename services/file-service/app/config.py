import os
from dataclasses import dataclass


@dataclass
class Settings:
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    minio_bucket: str = os.getenv("MINIO_BUCKET", "files")
    max_upload_size: int = int(os.getenv("MAX_UPLOAD_SIZE", 50 * 1024 * 1024))
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:123456@localhost:5432/files")


settings = Settings()