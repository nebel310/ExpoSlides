import io
import uuid
from pathlib import Path

from aiobotocore.session import get_session

from .config import settings


class MinioStorage:
    """Класс для асинхронной работы с MinIO через S3 API"""

    @classmethod
    async def _get_client(cls):
        """Создать и вернуть клиент S3"""
        session = get_session()
        client = await session.create_client(
            "s3",
            endpoint_url=f"http://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            use_ssl=False,
        ).__aenter__()
        return client

    @classmethod
    async def ensure_bucket(cls) -> None:
        """Создать bucket если его нет"""
        client = await cls._get_client()
        try:
            await client.head_bucket(Bucket=settings.minio_bucket)
        except Exception:
            await client.create_bucket(Bucket=settings.minio_bucket)
        finally:
            await client.__aexit__(None, None, None)

    @classmethod
    async def save_file(cls, file_content: bytes, object_name: str, content_type: str) -> None:
        """Сохранить файл в MinIO"""
        client = await cls._get_client()
        try:
            await client.put_object(
                Bucket=settings.minio_bucket,
                Key=object_name,
                Body=file_content,
                ContentType=content_type,
            )
        finally:
            await client.__aexit__(None, None, None)

    @classmethod
    async def get_file(cls, object_name: str) -> tuple[bytes, str, str] | None:
        """Получить файл из MinIO, вернуть контент, content-type и оригинальное имя"""
        client = await cls._get_client()
        try:
            response = await client.get_object(Bucket=settings.minio_bucket, Key=object_name)
            async with response["Body"] as stream:
                data = await stream.read()
            content_type = response.get("ContentType", "application/octet-stream")
            metadata = response.get("Metadata", {})
            original_name = metadata.get("original_name", object_name)
            return data, content_type, original_name
        except Exception:
            return None
        finally:
            await client.__aexit__(None, None, None)

    @classmethod
    async def delete_file(cls, object_name: str) -> None:
        """Удалить файл из MinIO"""
        client = await cls._get_client()
        try:
            await client.delete_object(Bucket=settings.minio_bucket, Key=object_name)
        finally:
            await client.__aexit__(None, None, None)