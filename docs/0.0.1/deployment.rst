.. _deployment:

==========
Deployment
==========

This guide covers deploying OpenViper to a production environment.  The
recommendations below apply to any Linux server or container platform.

.. contents:: On this page
   :local:
   :depth: 2

----

Production Settings
--------------------

Always start with a settings class that overrides development defaults:

.. code-block:: python

   # myproject/settings_prod.py
   import os
   from datetime import timedelta
   from openviper.conf.settings import Settings


   class ProductionSettings(Settings):
       DEBUG        = False
       SECRET_KEY   = os.environ["SECRET_KEY"]           # must be set
       DATABASE_URL = os.environ["DATABASE_URL"]         # must be set
       ALLOWED_HOSTS = tuple(
           os.environ.get("ALLOWED_HOSTS", "").split(",")
       )

       # Redis for caching and tasks
       CACHE_BACKEND = "redis"
       CACHE_URL     = os.environ["REDIS_URL"]
       TASKS = {
           "broker_url": os.environ["REDIS_URL"],
       }

       # Secure cookies
       SESSION_COOKIE_SECURE  = True
       CSRF_COOKIE_SECURE     = True
       SESSION_COOKIE_SAMESITE = "Strict"

       # Tighten JWT expiry
       JWT_ACCESS_TOKEN_EXPIRE  = timedelta(hours=1)
       JWT_REFRESH_TOKEN_EXPIRE = timedelta(days=7)

       # CORS
       CORS_ALLOWED_ORIGINS = tuple(
           os.environ.get("CORS_ORIGINS", "").split(",")
       )

       # Disable debug docs in production
       OPENAPI_ENABLED = os.environ.get("OPENAPI_ENABLED", "false").lower() == "true"

       LOG_LEVEL  = "WARNING"
       LOG_FORMAT = "json"

Activate the production settings in ``asgi.py``:

.. code-block:: python

   # myproject/asgi.py
   import os
   from openviper.conf import configure

   if os.environ.get("ENVIRONMENT") == "production":
       from myproject.settings_prod import ProductionSettings
       configure(ProductionSettings())
   else:
       from myproject.settings import Settings
       configure(Settings())

   from openviper import OpenViper
   app = OpenViper(...)

----

Running with Uvicorn
---------------------

For production use 2 × CPU core workers and disable the reloader:

.. code-block:: bash

   uvicorn myproject.asgi:app \
       --host 0.0.0.0 \
       --port 8000 \
       --workers 4 \
       --no-access-log \
       --loop uvloop \
       --http h11

Or via the management command:

.. code-block:: bash

   python viperctl.py runserver 0.0.0.0:8000 --workers 4 --no-reload

----

Running Workers in Production
-------------------------------

Start one or more Dramatiq worker processes.  Each process can run multiple
threads:

.. code-block:: bash

   # Process 1 — general queues
   python viperctl.py runworker --queues default,emails --threads 8

   # Process 2 — high-priority queue
   python viperctl.py runworker --queues priority --threads 4

Supervise workers with **systemd** or your platform's process manager so they
restart on failure.

Example systemd unit (``/etc/systemd/system/myblog-worker.service``):

.. code-block:: ini

   [Unit]
   Description=MyBlog Dramatiq Worker
   After=network.target

   [Service]
   WorkingDirectory=/srv/myblog
   ExecStart=/srv/myblog/.venv/bin/python viperctl.py runworker --threads 8
   Restart=on-failure
   User=www-data
   Environment=ENVIRONMENT=production

   [Install]
   WantedBy=multi-user.target

----

Nginx Reverse Proxy
--------------------

Typical Nginx configuration that terminates TLS and proxies to Uvicorn:

.. code-block:: nginx

   server {
       listen 443 ssl http2;
       server_name example.com;

       ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

       location / {
           proxy_pass         http://127.0.0.1:8000;
           proxy_set_header   Host              $host;
           proxy_set_header   X-Real-IP         $remote_addr;
           proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
           proxy_set_header   X-Forwarded-Proto $scheme;
           proxy_http_version 1.1;
           proxy_set_header   Upgrade           $http_upgrade;
           proxy_set_header   Connection        "upgrade";
       }

       location /static/ {
           alias /srv/myblog/static/;
           expires 30d;
       }

       location /media/ {
           alias /srv/myblog/media/;
           expires 7d;
       }
   }

Collect static files before starting Nginx:

.. code-block:: bash

   python viperctl.py collectstatic --no-input

----

Docker Example
---------------

.. rubric:: Dockerfile

.. code-block:: dockerfile

   FROM python:3.14-slim

   WORKDIR /app

   # Install dependencies
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt

   # Copy project
   COPY . .

   # Collect static files
   RUN python viperctl.py collectstatic --no-input

   EXPOSE 8000

   CMD ["uvicorn", "myproject.asgi:app", \
        "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

.. rubric:: docker-compose.yml

.. code-block:: yaml

   version: "3.9"

   services:

     db:
       image: postgres:16
       environment:
         POSTGRES_DB:       myblog
         POSTGRES_USER:     myblog
         POSTGRES_PASSWORD: secret
       volumes:
         - db_data:/var/lib/postgresql/data

     redis:
       image: redis:7-alpine

     web:
       build: .
       command: >
         sh -c "python viperctl.py migrate &&
                uvicorn myproject.asgi:app
                  --host 0.0.0.0 --port 8000 --workers 2"
       env_file: .env.production
       ports:
         - "8000:8000"
       depends_on:
         - db
         - redis

     worker:
       build: .
       command: python viperctl.py runworker --threads 8
       env_file: .env.production
       depends_on:
         - db
         - redis

   volumes:
     db_data:

.. rubric:: .env.production

.. code-block:: bash

   ENVIRONMENT=production
   SECRET_KEY=your-very-secret-key
   DATABASE_URL=postgresql+asyncpg://myblog:secret@db:5432/myblog
   REDIS_URL=redis://redis:6379/0
   ALLOWED_HOSTS=example.com
   CORS_ORIGINS=https://example.com

----

Database Migrations at Deploy Time
------------------------------------

Run migrations before starting the application in a deployment pipeline:

.. code-block:: bash

   python viperctl.py migrate

In Docker Compose the ``web`` service command runs ``migrate`` as part of
``sh -c "..."`` so that it executes before Uvicorn starts.

----

Environment Configuration Checklist
--------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Setting
     - Production value
   * - ``DEBUG``
     - ``False``
   * - ``SECRET_KEY``
     - Long random string (minimum 50 chars)
   * - ``ALLOWED_HOSTS``
     - Your domain(s) only
   * - ``DATABASE_URL``
     - PostgreSQL or MariaDB URL
   * - ``SESSION_COOKIE_SECURE``
     - ``True``
   * - ``CSRF_COOKIE_SECURE``
     - ``True``
   * - ``CACHE_BACKEND``
     - ``"redis"``
   * - ``OPENAPI_ENABLED``
     - ``False`` (or protect with auth)
   * - ``LOG_FORMAT``
     - ``"json"``

.. seealso::

   :ref:`settings` — full configuration reference.
