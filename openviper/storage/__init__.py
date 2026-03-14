"""OpenViper file storage backends."""

from openviper.storage.base import FileSystemStorage, Storage, default_storage

__all__ = [
    "FileSystemStorage",
    "Storage",
    "default_storage",
]
