"""The language oracle, now `wend._languages` (behind
``wend.relate(..., thorough=True)``).

This name is kept for the journal scripts that import it: it is the same
module object, so patching a name here patches it there.
"""

import sys

from .. import _languages


sys.modules[__name__] = _languages
