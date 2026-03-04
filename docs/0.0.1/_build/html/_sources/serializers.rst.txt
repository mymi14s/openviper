.. _serializers:

=================
Serializer System
=================

OpenViper serializers are built on top of **Pydantic v2**.  They provide field
validation, type coercion, nested serialization, and ORM-to-dict conversion
with a minimal, Django REST Framework-inspired API.

.. contents:: On this page
   :local:
   :depth: 2

----

Base Serializer
----------------

:class:`~openviper.serializers.base.Serializer` extends
:class:`pydantic.BaseModel` with ORM-specific helpers:

.. code-block:: python

   from openviper.serializers import Serializer


   class TagSerializer(Serializer):
       name:  str
       color: str = "#ffffff"

   # Validate incoming data
   tag = TagSerializer.validate({"name": "python", "color": "#3572A5"})
   print(tag.name)   # "python"

   # Serialize to dict
   data = tag.serialize()
   # {"name": "python", "color": "#3572A5"}

   # Exclude fields
   data = tag.serialize(exclude={"color"})

   # Many
   tags = TagSerializer.serialize_many([tag1, tag2])

----

ModelSerializer
----------------

:class:`~openviper.serializers.base.ModelSerializer` auto-generates fields
from a :class:`~openviper.db.models.Model`:

.. code-block:: python

   from openviper.serializers import ModelSerializer
   from blog.models import Post


   class PostSerializer(ModelSerializer):
       class Meta:
           model            = Post
           fields           = "__all__"       # or a list: ["id", "title", "body"]
           exclude          = []              # field names to exclude
           read_only_fields = ("id", "created_at", "updated_at")
           extra_kwargs     = {
               "slug": {"required": False},
           }

``fields = "__all__"`` includes every column defined on the model.

Partial Updates
~~~~~~~~~~~~~~~

For ``PATCH``-style endpoints pass ``partial=True`` to make all fields optional:

.. code-block:: python

   serializer = PostSerializer.validate(data, partial=True)

Read-Only and Write-Only Fields
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   class PostSerializer(ModelSerializer):
       class Meta:
           model             = Post
           fields            = "__all__"
           read_only_fields  = ("id", "slug", "created_at")   # never written to DB
           write_only_fields = ("raw_password",)               # never included in output

----

Field Validation
-----------------

Use :func:`~openviper.serializers.base.field_validator` (re-exported from
Pydantic) for per-field validation:

.. code-block:: python

   from openviper.serializers import ModelSerializer, field_validator
   from blog.models import Post


   class PostSerializer(ModelSerializer):
       class Meta:
           model  = Post
           fields = ["title", "body"]

       @field_validator("title")
       @classmethod
       def title_not_empty(cls, v: str) -> str:
           if len(v.strip()) < 3:
               raise ValueError("Title must be at least 3 characters.")
           return v.strip()

Use :func:`~openviper.serializers.base.model_validator` for cross-field
validation:

.. code-block:: python

   from openviper.serializers import Serializer, model_validator


   class PasswordSerializer(Serializer):
       password:         str
       confirm_password: str

       @model_validator(mode="after")
       def passwords_match(self) -> "PasswordSerializer":
           if self.password != self.confirm_password:
               raise ValueError("Passwords do not match.")
           return self

----

Nested Serializers
-------------------

Nest serializers by using one as a field type:

.. code-block:: python

   from openviper.serializers import Serializer, ModelSerializer
   from blog.models import Post
   from users.serializers import AuthorSerializer


   class PostSerializer(ModelSerializer):
       author: AuthorSerializer           # nested serializer

       class Meta:
           model  = Post
           fields = ["id", "title", "body", "author"]

When serializing a model instance that has a related object loaded, the nested
serializer is applied automatically:

.. code-block:: python

   post = await Post.objects.get(id=1)
   data = PostSerializer.from_orm(post).serialize()
   # data["author"] = {"id": 1, "username": "jane", ...}

----

Create and Update
------------------

``ModelSerializer`` provides async ``create()``, ``update()``, and ``save()``
methods:

.. code-block:: python

   from blog.serializers import PostSerializer

   # --- Create ---
   serializer = PostSerializer.validate(await request.json())
   post_data  = await serializer.save()            # calls create()
   # Returns the serialized dict of the new Post.

   # --- Update ---
   existing_post = await Post.objects.get(id=42)
   serializer    = PostSerializer.validate(await request.json())
   post_data     = await serializer.save(instance=existing_post)  # calls update()

Behind the scenes:

* ``save(instance=None)`` → calls ``create()`` which calls
  ``Post.objects.create(**validated_data)``.
* ``save(instance=post)`` → calls ``update()`` which applies
  ``validated_data`` to the instance and calls ``instance.save()``.

Override for custom behaviour:

.. code-block:: python

   class PostSerializer(ModelSerializer):

       async def create(self) -> Post:
           data = self.model_dump(exclude={"confirm_password"})
           return await Post.objects.create(**data)

       async def update(self, instance: Post) -> Post:
           for key, value in self.model_dump(exclude_unset=True).items():
               setattr(instance, key, value)
           await instance.save()
           return instance

----

ORM-to-Dict Helpers
--------------------

.. code-block:: python

   # Single instance
   data = PostSerializer.from_orm(post).serialize()

   # List of instances
   data = PostSerializer.serialize_many(posts)

   # Exclude specific fields from output
   data = PostSerializer.from_orm(post).serialize(exclude={"body"})

----

Role-Aware Serialization
-------------------------

Because ``Serializer`` and ``ModelSerializer`` are plain Python classes, you
can inspect ``request.user`` and conditionally include or exclude fields:

.. code-block:: python

   class PostSerializer(ModelSerializer):
       class Meta:
           model  = Post
           fields = "__all__"

   class PostAdminSerializer(PostSerializer):
       """Extended serializer for staff users — includes internal fields."""

       class Meta(PostSerializer.Meta):
           fields = "__all__"   # includes `author`, `internal_notes`

   # In the view:
   if request.user.is_staff:
       return JSONResponse(PostAdminSerializer.from_orm(post).serialize())
   return JSONResponse(PostSerializer.from_orm(post).serialize())

.. seealso::

   :ref:`authentication` for role and permission utilities.
