# -*- coding: utf-8 -*-
"""rfc3986.validators 的极简兼容实现。

jschon 仅用到了：
- Validator()
- require_presence_of('scheme')
- validate(uriref) -> 若失败抛 ValidationError

这里不做完整 RFC3986 规则校验，只检查必要字段是否存在。
"""

from __future__ import annotations

from .exceptions import ValidationError


class Validator:
    def __init__(self):
        self._require = set()

    def require_presence_of(self, component: str):
        # 原版会返回一个新的 Validator；这里直接在自身记录并返回 self。
        self._require.add(component)
        return self

    def validate(self, uriref) -> None:
        # 最小检查：如果要求 scheme，则必须存在 scheme
        if "scheme" in self._require and not getattr(uriref, "scheme", None):
            raise ValidationError("scheme is required")
        return
