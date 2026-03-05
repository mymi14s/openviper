.. _authentication:

==============
Authentication
==============

OpenViper ships a complete authentication system covering users, password
hashing, sessions, JWT tokens, roles, permissions, and view-level guards.

.. contents:: On this page
   :local:
   :depth: 2

----

User Model
----------

The built-in user model is :class:`~openviper.auth.models.User` (concrete
subclass of :class:`~openviper.auth.models.AbstractUser`).

Fields
~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Field
     - Type
     - Notes
   * - ``id``
     - int
     - Auto-incrementing primary key
   * - ``username``
     - str
     - Unique, max 150 chars
   * - ``email``
     - str
     - Unique email address
   * - ``password``
     - str
     - Hashed value; never stored in plain text
   * - ``first_name``
     - str?
     - Optional given name
   * - ``last_name``
     - str?
     - Optional family name
   * - ``is_active``
     - bool
     - ``False`` disables login (default ``True``)
   * - ``is_superuser``
     - bool
     - Bypasses all permission checks
   * - ``is_staff``
     - bool
     - Can access admin panel
   * - ``role_profile``
     - FK → RoleProfile
     - Optional role bundle assignment
   * - ``created_at``
     - datetime
     - Set on insert
   * - ``updated_at``
     - datetime
     - Updated on every save
   * - ``last_login``
     - datetime?
     - Updated by the login backend

Custom User Model
~~~~~~~~~~~~~~~~~

Point ``USER_MODEL`` in ``settings.py`` to your own subclass:

.. code-block:: python

   # myapp/users/models.py
   from openviper.auth.models import AbstractUser
   from openviper.db.fields import CharField

   class CustomUser(AbstractUser):
       bio = CharField(max_length=500, null=True)

       class Meta:
           table_name = "users"

   # myproject/settings.py
   USER_MODEL = "myapp.users.models.CustomUser"

----

Password Hashing
-----------------

Passwords are hashed on assignment using Argon2id (primary) with bcrypt as
a fallback hasher.

.. code-block:: python

   from openviper.auth.hashers import make_password, check_password

   hashed = make_password("mysecretpassword")    # Argon2id hash string
   ok     = check_password("mysecretpassword", hashed)   # True

On the user model:

.. code-block:: python

   user = await User.objects.get(username="john")
   user.set_password("new-password")
   await user.save()

   user.check_password("new-password")   # True

Configure hashers via ``PASSWORD_HASHERS`` in settings (ordered list,
first entry is the primary hasher):

.. code-block:: python

   PASSWORD_HASHERS = ("argon2", "bcrypt")

----

Authentication Backends
------------------------

:func:`~openviper.auth.backends.authenticate` accepts username + password and
returns the user if credentials are valid:

.. code-block:: python

   from openviper.auth.backends import authenticate, login, logout
   from openviper import JSONResponse

   async def login_view(request):
       data     = await request.json()
       user     = await authenticate(
           username=data["username"],
           password=data["password"]
       )
       if user is None:
           return JSONResponse({"error": "Invalid credentials"}, status_code=401)

       session_key = await login(request, user)
       response    = JSONResponse({"detail": "Logged in."})
       response.set_cookie("sessionid", session_key, httponly=True)
       return response

   async def logout_view(request):
       await logout(request)
       return JSONResponse({"detail": "Logged out."})

----

Sessions
---------

Sessions are server-side by default, keyed by a random token stored in
the ``sessionid`` cookie.

Configuration:

.. code-block:: python

   SESSION_COOKIE_NAME    = "sessionid"
   SESSION_TIMEOUT        = timedelta(hours=1)
   SESSION_COOKIE_SECURE  = True    # HTTPS only in production
   SESSION_COOKIE_HTTPONLY = True
   SESSION_COOKIE_SAMESITE = "Lax"

----

JWT Authentication
-------------------

Create tokens:

.. code-block:: python

   from openviper.auth.jwt import create_access_token, create_refresh_token

   access_token  = create_access_token(user.pk)
   refresh_token = create_refresh_token(user.pk)

   # With custom claims
   access_token = create_access_token(
       user.pk,
       extra_claims={"role": "admin", "org": "acme"}
   )

Decode tokens:

.. code-block:: python

   from openviper.auth.jwt import decode_access_token
   from openviper.exceptions import TokenExpired, Unauthorized

   try:
       payload  = decode_access_token(token)
       user_id  = payload["sub"]         # subject = user pk
   except TokenExpired:
       return JSONResponse({"error": "Token expired"}, status_code=401)
   except Unauthorized:
       return JSONResponse({"error": "Invalid token"}, status_code=401)

Configuration:

.. code-block:: python

   JWT_ALGORITHM             = "HS256"
   JWT_ACCESS_TOKEN_EXPIRE   = timedelta(hours=24)
   JWT_REFRESH_TOKEN_EXPIRE  = timedelta(days=7)

The :class:`~openviper.middleware.auth.AuthenticationMiddleware` automatically
reads ``Authorization: Bearer <token>`` from incoming requests and sets
``request.user``.

----

Roles and Permissions
----------------------

.. rubric:: Permission

A :class:`~openviper.auth.models.Permission` is a named capability:

.. code-block:: python

   perm = await Permission.objects.create(
       codename="post.create",
       name="Can create blog posts"
   )

.. rubric:: Role

A :class:`~openviper.auth.models.Role` bundles permissions together:

.. code-block:: python

   role = await Role.objects.create(name="editor")
   # Assign a permission to the role
   # (via the RolePermission junction table)

.. rubric:: Assigning Roles

.. code-block:: python

   editor_role = await Role.objects.get(name="editor")
   await user.assign_role(editor_role)
   await user.remove_role(editor_role)

.. rubric:: Checking Permissions

.. code-block:: python

   if await request.user.has_perm("post.create"):
       ...

   if await request.user.has_role("editor"):
       ...

   if await request.user.has_model_perm("blog.Post", "delete"):
       ...

   # Returns set[str] of all codenames
   perms = await request.user.get_permissions()

Superusers (``is_superuser=True``) pass every permission check.

----

Securing Routes with Decorators
---------------------------------

:mod:`openviper.auth.decorators` provides view guards:

``@login_required``
~~~~~~~~~~~~~~~~~~~~

Raises :class:`~openviper.exceptions.Unauthorized` (HTTP 401) if the user is
not authenticated:

.. code-block:: python

   from openviper.auth.decorators import login_required

   @login_required
   async def my_view(request):
       return JSONResponse({"user": request.user.username})

``@permission_required``
~~~~~~~~~~~~~~~~~~~~~~~~~

Raises :class:`~openviper.exceptions.PermissionDenied` (HTTP 403) if the
user lacks the named permission:

.. code-block:: python

   from openviper.auth.decorators import permission_required

   @permission_required("post.publish")
   async def publish_post(request, post_id: int):
       ...

``@role_required``
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from openviper.auth.decorators import role_required

   @role_required("editor")
   async def editor_dashboard(request):
       ...

``@superuser_required`` / ``@staff_required``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from openviper.auth.decorators import superuser_required, staff_required

   @superuser_required
   async def admin_only(request): ...

   @staff_required
   async def staff_panel(request): ...

----

Anonymous Users
----------------

Unauthenticated requests have ``request.user`` set to an
:class:`~openviper.auth.models.AnonymousUser` instance.  It is safe to call
all permission-check methods on it; they always return ``False``:

.. code-block:: python

   request.user.is_authenticated   # False
   request.user.is_anonymous       # True
   await request.user.has_perm("anything")  # False

----

Creating a Superuser
----------------------

.. code-block:: bash

   python viperctl.py createsuperuser
   # prompts for username, email, password

   # Non-interactive
   python viperctl.py createsuperuser --username admin --email admin@example.com --noinput

Change a password:

.. code-block:: bash

   python viperctl.py changepassword admin

----

Integration with the Protected ORM
------------------------------------

Because ``request.user`` is always available in the async scope, you can
inject it into ORM queries or lifecycle hooks to enforce row-level access:

.. code-block:: python

   @login_required
   async def my_posts(request):
       # Only return the requesting user's own posts
       posts = await Post.objects.filter(author=request.user.pk).all()
       return JSONResponse(PostSerializer.serialize_many(posts))

.. seealso::

   :ref:`orm` — Protected ORM section for ``ignore_permissions`` usage.
