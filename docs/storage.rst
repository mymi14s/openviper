.. _storage:

File Storage
============

The ``openviper.storage`` package provides a pluggable file storage API for
handling uploaded files.  The default :class:`~openviper.storage.FileSystemStorage`
persists files under ``MEDIA_ROOT`` and builds public URLs from ``MEDIA_URL``.

Overview
--------

All storage operations are coroutine-based and run file I/O in thread pools
via ``aiofiles``.  The ``default_storage`` singleton is configured from
settings and used automatically by :class:`~openviper.db.fields.FileField`
and :class:`~openviper.db.fields.ImageField`.

Key Classes
-----------

.. py:class:: openviper.storage.Storage

   Abstract base class for all storage backends.

   .. py:method:: save(name, content) -> Awaitable[str]

      Persist *content* (bytes, file-like, or async iterator) under *name*.
      Returns the final relative path (may differ from *name* to avoid
      collisions).

   .. py:method:: delete(name) -> Awaitable[None]

      Delete the file at *name*.

   .. py:method:: exists(name) -> Awaitable[bool]

      Return ``True`` if *name* exists in the storage.

   .. py:method:: url(name) -> str

      Return the public URL for *name*.

   .. py:method:: size(name) -> Awaitable[int]

      Return the size in bytes of *name*.

.. py:class:: openviper.storage.FileSystemStorage(location=None, base_url=None)

   Concrete storage that persists files to the local filesystem.

   - ``location`` — base directory for files (defaults to ``settings.MEDIA_ROOT``).
   - ``base_url`` — URL prefix for generated URLs (defaults to ``settings.MEDIA_URL``).

   File names are sanitized to remove unsafe characters, and duplicate names
   are disambiguated by appending a UUID suffix.

.. py:data:: openviper.storage.default_storage

   The configured storage singleton, instantiated from
   ``settings.DEFAULT_FILE_STORAGE`` (defaults to
   ``FileSystemStorage``).

Example Usage
-------------

Using ``default_storage`` Directly
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from openviper.storage import default_storage
    from openviper.http.request import Request
    from openviper.http.response import JSONResponse
    from openviper.routing.router import Router

    router = Router()

    @router.post("/upload")
    async def upload_file(request: Request) -> JSONResponse:
        files = await request.files()
        file = files.get("file")
        if file is None:
            return JSONResponse({"error": "No file provided"}, status_code=400)

        content = await file.read()
        saved_path = await default_storage.save(f"uploads/{file.filename}", content)
        url = default_storage.url(saved_path)

        return JSONResponse({"path": saved_path, "url": url})

FileField on a Model
~~~~~~~~~~~~~~~~~~~~~

When a model has a :class:`~openviper.db.fields.FileField`, the framework
automatically uses ``default_storage`` to persist the file on ``save()``:

.. code-block:: python

    from openviper.db.models import Model
    from openviper.db import fields

    class Document(Model):
        class Meta:
            table_name = "documents"

        title = fields.CharField(max_length=255)
        file = fields.FileField(upload_to="documents/")

    # In a view:
    @router.post("/documents")
    async def upload_doc(request: Request) -> JSONResponse:
        form = await request.form()
        uploaded = (await request.files()).get("file")
        doc = Document(title=form["title"], file=uploaded)
        await doc.save()
        return JSONResponse({"url": default_storage.url(doc.file)}, status_code=201)

Custom Storage Backend
~~~~~~~~~~~~~~~~~~~~~~

Subclass :class:`Storage` to integrate any cloud or third-party storage:

.. code-block:: python

    from openviper.storage.base import Storage

    class S3Storage(Storage):
        def __init__(self, bucket: str) -> None:
            self.bucket = bucket

        async def save(self, name: str, content: bytes) -> str:
            # Upload to S3 ...
            return name

        async def delete(self, name: str) -> None:
            # Delete from S3 ...
            pass

        def url(self, name: str) -> str:
            return f"https://{self.bucket}.s3.amazonaws.com/{name}"

        async def exists(self, name: str) -> bool:
            # Check S3 ...
            return False

        async def size(self, name: str) -> int:
            return 0

Configuration
-------------

.. code-block:: python

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        MEDIA_ROOT: str = "media"
        MEDIA_URL: str = "/media/"
        DEFAULT_FILE_STORAGE: str = "myproject.storage.S3Storage"
