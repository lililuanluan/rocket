"""strategies package."""

import os
import sys

# Direct import for proper IDE integration (used in unit tests etc.)
from .byzzfuzz_baseline import ByzzFuzzBaseline
from .random_fuzzer import RandomFuzzer
from .strategy import Strategy

# The following block of code dynamically imports all classes created in the strategies module.
# https://stackoverflow.com/a/6246478
path = os.path.dirname(os.path.abspath(__file__))

for py in [
    f[:-3] for f in os.listdir(path) if f.endswith(".py") and f != "__init__.py"
]:
    mod = __import__(".".join([__name__, py]), fromlist=[py])
    classes = [getattr(mod, x) for x in dir(mod) if isinstance(getattr(mod, x), type)]
    for cls in classes:
        setattr(sys.modules[__name__], cls.__name__, cls)

__all__ = ["MutationExample", "RandomFuzzer", "Strategy"]
