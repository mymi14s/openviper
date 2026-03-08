
import os
import sys
import asyncio
from pathlib import Path

# Mock an app structure
os.makedirs("repro_app", exist_ok=True)
with open("repro_app/__init__.py", "w") as f:
    f.write("")

with open("repro_app/models.py", "w") as f:
    f.write("""
from openviper.db.models import Model
from openviper.db import fields

class MyModel(Model):
    class Meta:
        table_name = "my_model"
    title = fields.CharField(max_length=100)
""")

with open("repro_app/events.py", "w") as f:
    f.write("""
from openviper.db.events import model_event

print("IMPORTING REPRO_APP.EVENTS")

@model_event.trigger("repro_app.models.MyModel.on_update")
async def my_handler(obj, *, event) -> None:
    print(f"EVENT TRIGGERED: {event} for {obj.title}")
""")

# Simulation
sys.path.insert(0, os.getcwd())

from openviper.app import OpenViper
from openviper.db.events import _decorator_registry
from repro_app.models import MyModel

async def test_repro():
    print("Step 1: Create OpenViper app (simulation of web server)")
    app = OpenViper()
    
    print(f"Decorator registry before: {list(_decorator_registry.keys())}")
    
    # Check if repro_app.models.MyModel is in registry
    model_path = "repro_app.models.MyModel"
    if model_path in _decorator_registry:
        print("FAIL: Handler already in registry (maybe imported elsewhere?)")
    else:
        print("SUCCESS: Handler NOT in registry as expected (discovery missing)")

    print("\nStep 2: Simulate model update")
    instance = MyModel(id=1, title="Test")
    # Manually trigger event as if save happened
    instance._trigger_event("on_update")
    
    # Now import it manually and see it works
    print("\nStep 3: Manually import repro_app.events")
    import importlib
    importlib.import_module("repro_app.events")
    
    print(f"Decorator registry after: {list(_decorator_registry.keys())}")
    if model_path in _decorator_registry:
        print("SUCCESS: Handler now in registry")
        instance._trigger_event("on_update")
    else:
        print("FAIL: Handler still NOT in registry")

if __name__ == "__main__":
    # Setup openviper settings
    os.environ["OPENVIPER_SETTINGS_MODULE"] = "repro_settings"
    with open("repro_settings.py", "w") as f:
        f.write(\"\"\"
from openviper.conf.settings import Settings
import dataclasses
@dataclasses.dataclass(frozen=True)
class ReproSettings(Settings):
    INSTALLED_APPS: tuple = ("repro_app",)
    TASKS: dict = dataclasses.field(default_factory=lambda: {"enabled": True})
\"\"\")
    
    import openviper
    openviper.setup(force=True)
    
    asyncio.run(test_repro())
