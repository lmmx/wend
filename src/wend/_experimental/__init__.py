"""Experimental analyses. Not part of wend's public API.

Nothing here is exported from ``wend``, documented in the API reference or
covered by the stability promise: names, signatures and results may change
or disappear in any release. See ``docs/journal/`` for what each module
investigates and what it has not established.

- `wend._experimental.overlap`: whether two expressions can render the same
  path (YES with a verified witness, NO by a sound argument, or MAYBE).
- `wend._experimental.effects`: a graph of what a set of steps
  (`wend.Step`) declare they read and write, built from `Step.effects` and overlap.
- `wend._experimental.choices`: prototypes of proposed rules for
  ``choices=``: reading members back, and faithful rendering.
"""
