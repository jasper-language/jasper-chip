# -*- coding: utf-8 -*-
"""rfc3986.misc 的极简兼容实现。

jschon 用 UseExisting 作为 copy_with 的哨兵值。
"""

class _UseExisting:
    def __repr__(self) -> str:
        return "UseExisting"

# 哨兵：表示“沿用原组件”
UseExisting = _UseExisting()
