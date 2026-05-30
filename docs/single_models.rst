.. _single_models:

Single Models
=============

Overview
--------

A Single Model is a model with ``Meta.single = True``. It represents one
logical record and is intended for application-wide settings such as site
branding, email configuration, payment settings, feature flags, or
maintenance mode.

Defining a Single Model
-----------------------

.. code-block:: python

   from openviper.db import Model
   from openviper.db.fields import BooleanField, CharField


   class SiteSettings(Model):
       site_name = CharField(max_length=255)
       maintenance_mode = BooleanField(default=False)

       class Meta:
           single = True

``Meta.single`` defaults to ``False``. It must be a boolean.

When To Use Single Models
-------------------------

Use a Single Model when multiple rows would not make sense for the data.
Common examples include global settings, brand settings, integration
credentials, and system toggles.

Storage Behavior
----------------

SQL-backed Single Models use a normal model table. The singleton record uses
primary key ``1`` so the ORM and database primary-key constraint both protect
against duplicate records. ``single=True`` does not skip table creation.

Single Models can also be virtual models:

.. code-block:: python

   class RemoteSettings(Model):
       maintenance_mode = BooleanField(default=False)

       class Meta:
           single = True
           virtual = True
           backend = "settings_api"

In that case, normal virtual backend behavior applies.

get_single And get_or_create_single
-----------------------------------

Single Model managers expose helpers for singleton access:

.. code-block:: python

   settings = await SiteSettings.objects.get_or_create_single()
   settings.site_name = "Docs"
   await settings.save()

``get_single()`` returns the existing instance and raises
``SingleModelDoesNotExist`` if it has not been created yet.

``get_or_create_single()`` returns the existing instance or creates it with
field defaults.

Updating Single Models
----------------------

Use ``update_single()`` for direct updates:

.. code-block:: python

   settings = await SiteSettings.objects.update_single(
       site_name="OpenViper",
       maintenance_mode=False,
   )

Validation, field conversion, permissions, and lifecycle hooks follow normal
model update behavior.

Delete Is Forbidden
-------------------

Single Model data cannot be deleted. The ORM raises
``SingleModelDeleteForbiddenError`` for ``instance.delete()`` and
``QuerySet.delete()``. Delete hooks are not called because the delete operation
is rejected before the lifecycle delete flow starts.

Admin Behavior
--------------

The admin API marks Single Models with ``single: true`` and exposes
capabilities that disable list, create, duplicate, bulk delete, and delete
actions. The admin frontend opens a settings-style detail form directly.

The single admin endpoints are:

* ``GET /admin/api/models/{app_label}/{model_name}/single/``
* ``PATCH /admin/api/models/{app_label}/{model_name}/single/``
* ``PUT /admin/api/models/{app_label}/{model_name}/single/``

Permissions
-----------

View permission allows reading the singleton record. Change permission allows
updating it. Add and delete permissions do not create extra capabilities for
Single Models.

Single Models With Virtual Models
---------------------------------

``single=True`` and ``virtual=True`` are independent. ``single=True`` controls
record cardinality and admin behavior. ``virtual=True`` controls storage and
uses the configured virtual backend.

See :ref:`Virtual Models <db>` in the Database & ORM documentation for the
full ``VirtualBackend`` and ``VirtualBackendCapabilities`` API reference.

Limitations
-----------

Single Models are not list resources in the admin UI. They are view/update
resources. They are not suitable for historical settings rows or data that
needs more than one active record.
