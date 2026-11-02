"""Import pure modules without requiring Home Assistant in the offline environment."""

import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
for name, path in (("custom_components", ROOT / "custom_components"),
                   ("custom_components.orvibo_mixpad", ROOT / "custom_components/orvibo_mixpad")):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules.setdefault(name, module)
