---
description: "The wend package: building, resolving, matching and discovering path expressions."
---

# wend

::: wend
    options:
      members: false

## Building expressions

::: wend.P
    options:
      show_root_heading: true
      heading_level: 3

::: wend.T
    options:
      show_root_heading: true
      heading_level: 3

::: wend.PathExpr
    options:
      show_root_heading: true
      heading_level: 3

::: wend.Text
    options:
      show_root_heading: true
      heading_level: 3

::: wend.bindings
    options:
      show_root_heading: true
      heading_level: 3


## Parameters

::: wend.Param
    options:
      show_root_heading: true
      heading_level: 3

::: wend.Segment
    options:
      show_root_heading: true
      heading_level: 3

::: wend.SubPath
    options:
      show_root_heading: true
      heading_level: 3

::: wend.AnyPath
    options:
      show_root_heading: true
      heading_level: 3

::: wend.Absolute
    options:
      show_root_heading: true
      heading_level: 3

::: wend.Kind
    options:
      show_root_heading: true
      heading_level: 3


## Unions

::: wend.U
    options:
      show_root_heading: true
      heading_level: 3

::: wend.Alt
    options:
      show_root_heading: true
      heading_level: 3

::: wend.PathUnion
    options:
      show_root_heading: true
      heading_level: 3


## Matching and discovery

::: wend.Match
    options:
      show_root_heading: true
      heading_level: 3

::: wend.Lens
    options:
      show_root_heading: true
      heading_level: 3

::: wend.NoMatchError
    options:
      show_root_heading: true
      heading_level: 3

::: wend.glob
    options:
      show_root_heading: true
      heading_level: 3


## Batch resolution

::: wend.compile_many
    options:
      show_root_heading: true
      heading_level: 3

::: wend.CompiledSet
    options:
      show_root_heading: true
      heading_level: 3


## Kinds and evidence

The type parameters that track what an expression declares (see
[`PathExpr`][wend.PathExpr]), and the evidence that
[`checked`][wend.PathExpr.checked] and [`confirmed`][wend.PathExpr.confirmed] return:
a record of what one check found of one rendered path, at the moment it ran, which is
not a path and carries nothing to paths derived from it.

::: wend.IsFile
    options:
      show_root_heading: true
      heading_level: 3

::: wend.NotFile
    options:
      show_root_heading: true
      heading_level: 3

::: wend.Unspecified
    options:
      show_root_heading: true
      heading_level: 3

::: wend.JoinBelowFile
    options:
      show_root_heading: true
      heading_level: 3

::: wend.Checked
    options:
      show_root_heading: true
      heading_level: 3

::: wend.Confirmed
    options:
      show_root_heading: true
      heading_level: 3


## Also exported from `wend`

[`Query`][wend.query.Query] (from [wend.query](query.md)), [`counter`][wend.templates.counter]
(from [wend.templates](templates.md)), the conditions of [wend.conditions](conditions.md) and
the exceptions of [wend.errors](errors.md).
