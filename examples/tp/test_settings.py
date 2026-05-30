import os
import sys

# Setup environment variables for tp project
os.environ.setdefault("OPENVIPER_SETTINGS_MODULE", "tp.settings")

# Add project directory to python path
project_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_dir)

import openviper  # noqa: E402

openviper.setup()

from tp.settings import ProjectSettings  # noqa: E402

from openviper.conf import settings  # noqa: E402

openviper_url = settings.DATABASE_URL
project_url = ProjectSettings.DATABASE_URL

print(f"openviper.conf.settings.DATABASE_URL: {openviper_url}")
print(f"ProjectSettings.DATABASE_URL: {project_url}")

if openviper_url == project_url:
    print("Test passed! They are equal.")
else:
    print("Test failed! They are not equal.")
    sys.exit(1)
