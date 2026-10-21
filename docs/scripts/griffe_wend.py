"""Griffe extension for wend's API reference: hide special methods that are not API.

With mkdocstrings' `filters = "public"` (which honours `__all__`), special methods count as
public; this marks the ones that only implement object protocols (repr, hashing,
pickling, slots) by removing them once the package is loaded, and keeps the operators that
are wend's API (/, |, -, &). (Setting `obj.public = False` is not enough: members reached
through an alias, `::: wend.Match` for `wend._match.Match`, ignore it.)
"""

import griffe


NOT_API = {
    "__repr__",
    "__str__",
    "__slots__",
    "__hash__",
    "__eq__",
    "__ne__",
    "__bool__",
    "__len__",
    "__iter__",
    "__contains__",
    "__format__",
    "__reduce__",
    "__reduce_ex__",
    "__getstate__",
    "__setstate__",
    "__post_init__",
    "__init_subclass__",
    "__set_name__",
    "__get__",
    "__get_pydantic_core_schema__",
    "__get_pydantic_json_schema__",
    "__all__",
}


class HideProtocolMethods(griffe.Extension):
    def on_package(self, *, pkg, **kwargs):
        def walk(obj):
            for name, member in list(obj.members.items()):
                if member.is_alias:
                    continue
                if obj.is_class and name in NOT_API:
                    del obj.members[name]
                elif member.is_module or member.is_class:
                    walk(member)

        walk(pkg)


# Workaround for griffe 2.3.2: a t-string nested in a t-string's interpolation
# (t"{Alt('', t'.{k}')}") fails with "_build() got multiple values for keyword argument
# 'in_joined_str'" and the value is dropped. _build_templatestr does not drop the flags it
# receives, as _build_joinedstr does. Remove once fixed upstream.
import ast as _ast  # noqa: E402

from griffe._internal import expressions as _expressions  # noqa: E402


if hasattr(_ast, "TemplateStr") and _ast.TemplateStr in _expressions._node_map:

    def _build_templatestr(
        node, parent, *, in_joined_str=False, in_formatted_str=False, **kwargs
    ):
        return _expressions.ExprTemplateStr(
            [
                _expressions._build(v, parent, in_joined_str=True, **kwargs)
                for v in node.values
            ]
        )

    _expressions._node_map[_ast.TemplateStr] = _build_templatestr
