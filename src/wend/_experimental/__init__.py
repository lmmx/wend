"""Experimental analyses. Not part of wend's public API.

Nothing here is exported from ``wend``, documented in the API reference or
covered by the stability promise: names, signatures and results may change
or disappear in any release. See ``docs/journal/`` for what each module
investigates and what it has not established.

- `wend._experimental.overlap`: whether two expressions can render the same
  path (YES with a verified witness, NO by a sound argument, or MAYBE). Now
  the private engine `wend._overlap` behind `wend.relate`; this name is an
  alias for it.
- `wend._experimental.effects`: a graph of what a set of steps
  (`wend.Step`) declare they read and write, built from `Step.effects` and overlap.
  Superseded by `wend.effects`, which relates the paths by `wend.relate`.
- `wend._experimental.choices`: prototypes of proposed rules for
  ``choices=``: reading members back, and faithful rendering.
- `wend._experimental.lang_oracle`: a decision procedure for
  ``relate(..., shared=False)``, exact where it answers, built from the
  interpreter alone, to check `wend.relate` against.
"""
