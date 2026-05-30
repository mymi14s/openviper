.. _storage:

File Storage
============

The ``openviper.storage`` package provides a pluggable file storage API
for handling uploaded files.  The default
:class:`~openviper.storage.FileSystemStorage` persists files under
``MEDIA_ROOT`` and builds public URLs from ``MEDIA_URL``.

Overview
--------

All storage operations are coroutine-based and run file I/O in thread
pools via ``aiofiles``.  The ``default_storage`` singleton is configured
from settings and used automatically by
:class:`~openviper.db.fields.FileField` and
:class:`~openviper.db.fields.ImageField`.

Key Classes
-----------

.. py:class:: openviper.storage.Storage
   :no-index:

   Protocol defining the interface for all storage backends.

   .. py:attribute:: CHUNK_SIZE
      :no-index:

      Size of chunks for streaming I/O (class-level ``int``).

   .. py:method:: save(name, content) -> Awaitable[str]
      :no-index:

      Persist *content* (bytes, file-like, or async iterator) under
      *name*.  Returns the final relative path (may differ from *name*
      to avoid collisions).

   .. py:method:: delete(name) -> Awaitable[None]
      :no-index:

      Delete the file at *name*.

   .. py:method:: exists(name) -> Awaitable[bool]
      :no-index:

      Return ``True`` if *name* exists in the storage.

   .. py:method:: url(name) -> str
      :no-index:

      Return the public URL for *name*.

   .. py:method:: size(name) -> Awaitable[int]
      :no-index:

      Return the size in bytes of *name*.

   .. py:method:: read(name) -> Awaitable[bytes]
      :no-index:

      Return the full file content.  Raises ``ValueError`` when the
      file exceeds ``MAX_READ_SIZE``.

   .. py:method:: listdir(path="") -> Awaitable[list[str]]
      :no-index:

      List entries under *path* in storage.

.. py:class:: openviper.storage.FileSystemStorage(location=None, base_url=None, chunk_size=1048576)
   :no-index:

   Concrete storage that persists files to the local filesystem.

   - ``location`` - directory for files (defaults to
     ``settings.MEDIA_ROOT``).
   - ``base_url`` - URL prefix for generated URLs (defaults to
     ``settings.MEDIA_URL``).
   - ``chunk_size`` - chunk size for streaming uploads (default: 1 MiB).

   File names are sanitised to remove unsafe characters, and duplicate
   names are disambiguated by appending a UUID suffix.

   .. py:method:: save(name, content) -> Awaitable[str]
      :no-index:

      Persist *content* using an atomic write pattern (temp file +
      rename).  Re-verifies path containment after temp file creation
      to mitigate TOCTOU.

   .. py:method:: delete(name) -> Awaitable[None]
      :no-index:

      Delete the file at *name*.  No error if it does not exist.

   .. py:method:: exists(name) -> Awaitable[bool]
      :no-index:

      Return ``True`` if *name* exists in the storage.

   .. py:method:: url(name) -> str
      :no-index:

      Return the public URL with percent-encoded path segments.

   .. py:method:: size(name) -> Awaitable[int]
      :no-index:

      Return the size in bytes.  Raises ``FileNotFoundError`` if the
      file does not exist.

   .. py:method:: read(name) -> Awaitable[bytes]
      :no-index:

      Return the full file content.  Raises ``ValueError`` when the
      file exceeds ``MAX_READ_SIZE`` (100 MiB).

   .. py:method:: listdir(path="") -> Awaitable[list[str]]
      :no-index:

      List entries under *path* in storage.

Utilities
---------

.. py:function:: openviper.storage.generate_unique_name(name) -> str
   :no-index:

   Generate a collision-resistant file name by appending a full UUID
   hex suffix.  Used internally by :meth:`FileSystemStorage.save` when
   the target name already exists.

Module Constants
----------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Name
     - Description
   * - ``UNSAFE_FILENAME_RE``
     - Compiled regex matching characters disallowed in file names.
   * - ``HIDDEN_FILENAME_RE``
     - Compiled regex matching leading-dot (hidden) file names.
   * - ``MAX_COMPONENT_LEN``
     - Maximum length of a single path component (255).
   * - ``MAX_READ_SIZE``
     - Maximum file size for :meth:`FileSystemStorage.read` (100 MiB).

Type Aliases
------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Name
     - Type
   * - ``StorageContent``
     - ``bytes | bytearray | AsyncIterator[bytes] | IO``

Default Storage Proxy
---------------------

.. py:class:: openviper.storage.DefaultStorage
   :no-index:

   Thread-safe lazy proxy that creates a
   :class:`FileSystemStorage` on first access.

   .. py:method:: configure(storage) -> None
      :no-index:

      Programmatically override the default storage backend.

   Delegates all :class:`Storage` methods (``save``, ``delete``,
   ``exists``, ``url``, ``size``, ``read``, ``listdir``) to the
   underlying instance.

.. py:data:: openviper.storage.default_storage
   :no-index:

   Module-level :class:`DefaultStorage` singleton.

Example Usage
-------------

Using ``default_storage`` Directly
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
~~~~~~~~~~~~~~~~~~~~~~~

Implement the :class:`Storage` protocol to integrate any cloud or
third-party storage:

.. code-block:: python

    from openviper.storage.base import Storage

    class S3Storage:
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

        async def read(self, name: str) -> bytes:
            # Fetch from S3 ...
            return b""

        async def listdir(self, path: str = "") -> list[str]:
            return []

Configuration
-------------

.. code-block:: python

    @dataclasses.dataclass(frozen=True)
    class MySettings(Settings):
        MEDIA_ROOT: str = "media"
        MEDIA_URL: str = "/media/"
        DEFAULT_FILE_STORAGE: str = "myproject.storage.S3Storage"

API Reference
-------------

.. automodule:: openviper.storage
   :members:

.. automodule:: openviper.storage.base
   :members:
