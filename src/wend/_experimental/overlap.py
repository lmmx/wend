"""The overlap engine, now `wend._overlap` (the analysis behind `wend.relate`).

This name is kept for the research tests, benchmarks and journal scripts that
import it: it is the same module object, so patching a name here patches it
there.
"""

import sys

from .. import _overlap


sys.modules[__name__] = _overlap
