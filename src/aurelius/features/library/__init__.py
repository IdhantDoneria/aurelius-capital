"""Importing this package registers every built-in feature.

Feature modules self-register via the `@feature` decorator at import time.
Import them here so `import aurelius.features` populates the registry.
"""

from aurelius.features.library import (  # noqa: F401  (import for side effects)
    price,
    statistical,
    technical,
    volatility,
    volume,
)
