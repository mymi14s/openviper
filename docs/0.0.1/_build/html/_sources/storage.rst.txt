.. _storage:

===============
File Storage
===============

The ``openviper.storage`` package provides a pluggable storage API for
persisting uploaded files.  The default backend
(:class:`~openviper.storage.base.FileSystemStorage`) saves files to
``MEDIA_ROOT`` and serves them at ``MEDIA_URL``.

.. contents:: On this page
   :local:
   :depth: 2

----

Configuration
--------------

Set ``MEDIA_ROOT`` and ``MEDIA_URL`` in ``settings.py``:

.. code-block:: python

   MEDIA_ROOT = "/var/app/media"     # absolute path; files are stored here
   MEDIA_URL  = "/media/"            # URL prefix for public access

----

Using default_storage
----------------------

The ``default_storage`` singleton is ready to use anywhere in your project:

.. code-block:: python

   from openviper.storage import default_storage

   # Save bytes or a file-like object
   path = await default_storage.save("uploads/photo.jpg", content)
   # Returns the relative path, e.g. "uploads/photo_ab12cd34.jpg"
   # (a UUID suffix is added to avoid name collisions)

   # Get the public URL  →  e.g. "/media/uploads/photo_ab12cd34.jpg"
   url = default_storage.url(path)

   # Check if a file exists
   exists = await default_storage.exists("uploads/photo.jpg")

   # Get file size in bytes
   size = await default_storage.size(path)

   # Delete a file (no error if it doesn't exist)
   await default_storage.delete(path)

``Storage`` API:

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Method
     - Description
   * - ``await save(name, content)``
     - Save *content* (bytes or file-like) and return the stored path
   * - ``.url(name)``
     - Return the public URL for the file
   * - ``await exists(name)``
     - Return ``True`` if a file exists at *name*
   * - ``await size(name)``
     - Return the file size in bytes
   * - ``await delete(name)``
     - Delete the file at *name*; silent if it doesn't exist

----

Handling File Uploads
----------------------

The typical pattern for an upload endpoint:

.. code-block:: python

   from openviper.http.request import Request
   from openviper.storage import default_storage

   @router.post("/posts/{post_id}/image")
   async def upload_post_image(request: Request, post_id: int):
       post = await Post.objects.get_or_none(id=post_id)
       if post is None:
           raise NotFound()

       form  = await request.form()
       photo = form["image"]           # UploadFile instance
       data  = await photo.read()
       await photo.close()

       # Save to storage
       path = await default_storage.save(f"posts/{post_id}/{photo.filename}", data)

       # Persist the URL on the model
       post.image_url = default_storage.url(path)
       await post.save()

       return {"image_url": post.image_url}

----

Custom Storage Backend
-----------------------

Subclass :class:`~openviper.storage.base.Storage` to implement a custom
backend (e.g. Amazon S3, Google Cloud Storage):

.. code-block:: python

   # myapp/storage.py
   from openviper.storage.base import Storage

   class S3Storage(Storage):
       def __init__(self, bucket: str, prefix: str = "") -> None:
           import boto3
           self._client = boto3.client("s3")
           self._bucket = bucket
           self._prefix = prefix

       async def save(self, name: str, content: bytes) -> str:
           import asyncio
           key = f"{self._prefix}{name}"
           await asyncio.to_thread(
               self._client.put_object,
               Bucket=self._bucket, Key=key, Body=content,
           )
           return key

       def url(self, name: str) -> str:
           return f"https://{self._bucket}.s3.amazonaws.com/{name}"

       async def delete(self, name: str) -> None:
           import asyncio
           await asyncio.to_thread(
               self._client.delete_object,
               Bucket=self._bucket, Key=name,
           )

       async def exists(self, name: str) -> bool:
           import asyncio
           try:
               await asyncio.to_thread(
                   self._client.head_object,
                   Bucket=self._bucket, Key=name,
               )
               return True
           except Exception:
               return False

       async def size(self, name: str) -> int:
           import asyncio
           resp = await asyncio.to_thread(
               self._client.head_object,
               Bucket=self._bucket, Key=name,
           )
           return resp["ContentLength"]

To use your custom backend, point ``DEFAULT_STORAGE`` in settings to its
import path:

.. code-block:: python

   DEFAULT_STORAGE = "myapp.storage.S3Storage"

   # Pass constructor kwargs via DEFAULT_STORAGE_OPTIONS
   DEFAULT_STORAGE_OPTIONS = {
       "bucket": "my-media-bucket",
       "prefix": "uploads/",
   }

.. seealso::

   :ref:`http` — ``UploadFile`` API for reading multipart form uploads.
