from pydantic import BaseModel


class UploadFileResponse(BaseModel):
    """Ответ на загрузку файла"""
    file_id: str
    filename: str
    size: int
    content_type: str
    version: int