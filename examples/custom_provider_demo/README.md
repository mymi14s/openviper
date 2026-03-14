# Custom Provider Demo

A working example that shows how to write, register, and use a **third-party AI
provider** with openviper — without modifying any core code.

## What's included

```
custom_provider_demo/
├── echo_provider/            # A self-contained mock provider package
│   ├── __init__.py
│   ├── provider.py           # EchoProvider implementation
│   └── tests/
│       └── test_echo_provider.py
├── demo.py                   # End-to-end demonstration script
└── README.md                 # This file
```

## Quick start

```bash
# From the repository root
pip install -e .

# Run the demo
cd examples/custom_provider_demo
python demo.py
```

## What the demo covers

| Step | What it demonstrates |
|------|----------------------|
| 1 | Programmatic `register_provider()` |
| 2 | Module auto-discovery via `register_from_module()` |
| 3 | Runtime model switching with `ModelRouter.set_model()` |
| 4 | Token-by-token streaming via `router.stream()` |
| 5 | Two providers coexisting in the same `ProviderRegistry` |
| 6 | Collision detection — `allow_override=True` vs `False` |
| 7 | `ModelNotFoundError` for unregistered model IDs |

## Run the tests

```bash
cd examples/custom_provider_demo
pytest echo_provider/tests/ -v
```

## How the EchoProvider works

`EchoProvider` exposes two model IDs:

| Model ID | Behaviour |
|----------|-----------|
| `echo-v1` | Echoes the prompt back with a `[EchoProvider/echo]` prefix |
| `reverse-v1` | Returns the reversed prompt text |

No API key or network access is required.

## Distributing your provider as a package

Add an entry-point to your `pyproject.toml` so any project that installs your
package and calls `provider_registry.discover_entrypoints()` will automatically
register it:

```toml
[project.entry-points."openviper.ai.providers"]
echo = "echo_provider.provider:get_providers"
```

See `docs/extending_providers.md` for the full guide.
