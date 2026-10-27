import hashlib
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings


class StoredFile:
    def __init__(self, storage_key: str, size_bytes: int, file_hash: str) -> None:
        self.storage_key = storage_key
        self.size_bytes = size_bytes
        self.file_hash = file_hash


class LocalStorage:
    def __init__(self, base_path: str | None = None) -> None:
        self.base_path = Path(base_path or get_settings().document_storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def resolve(self, storage_key: str) -> Path:
        path = (self.base_path / storage_key).resolve()
        if self.base_path.resolve() not in path.parents and path != self.base_path.resolve():
            raise ValueError("Invalid storage key")
        return path

    async def save_upload(self, upload: UploadFile, storage_key: str) -> StoredFile:
        target = self.resolve(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with target.open("wb") as file:
            while chunk := await upload.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                file.write(chunk)
        await upload.seek(0)
        return StoredFile(storage_key=storage_key, size_bytes=size, file_hash=digest.hexdigest())
