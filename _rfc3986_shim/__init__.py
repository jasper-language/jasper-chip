# -*- coding: utf-8 -*-
"""一个极简版 rfc3986 兼容 shim（研究/离线环境用）。

> **自研代码**：本目录**不是**上游 `python-rfc3986` 的 vendored 副本，也不附带上游许可证文本。
> 目录名刻意使用 `_rfc3986_shim`（而非 `rfc3986`），以免遮蔽 PyPI 上的官方 `rfc3986` 包。

用途
- Amaranth 0.5.x 依赖 jschon；jschon 依赖 rfc3986。
- 在无网环境里如果缺 rfc3986，会导致 `import amaranth` 失败。

覆盖范围
- 仅实现 jschon/uri.py 用到的最小 API：
  - uri_reference(str) -> URIReference
  - URIReference.unsplit/is_absolute/resolve_with/copy_with/normalize
  - rfc3986.exceptions.ValidationError
  - rfc3986.misc.UseExisting
  - rfc3986.validators.Validator

限制
- 不是完整 RFC3986 解析/校验器；这里用 urllib.parse 做“够用”的分解/拼接。
- 建议最终仍安装官方 rfc3986 包。

装载方式
- 本模块被 import 时，如果解释器里还没有 `rfc3986`，就把自身注册到 `sys.modules["rfc3986"]`
  （含子模块 exceptions / misc / validators），从而让 `import rfc3986` 与
  `from rfc3986.exceptions import ValidationError` 这类写法继续可用。
- 若官方 `rfc3986` 已安装，则**不会**覆盖它。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit, urljoin


@dataclass(frozen=True)
class URIReference:
    scheme: str | None
    authority: str | None
    path: str | None
    query: str | None
    fragment: str | None

    def unsplit(self) -> str:
        # urlunsplit 需要 5 元组：(scheme, netloc, path, query, fragment)
        return urlunsplit((self.scheme or "", self.authority or "", self.path or "", self.query or "", self.fragment or ""))

    def is_absolute(self) -> bool:
        return bool(self.scheme)

    def resolve_with(self, base: "URIReference") -> "URIReference":
        # 用 urljoin 做粗略 resolve
        joined = urljoin(base.unsplit(), self.unsplit())
        return uri_reference(joined)

    def copy_with(self, scheme=None, authority=None, path=None, query=None, fragment=None) -> "URIReference":
        # 兼容 jschon: UseExisting 表示沿用；None 表示删除；字符串表示替换
        from .misc import UseExisting

        def pick(old, new):
            if new is UseExisting:
                return old
            return new

        return URIReference(
            scheme=pick(self.scheme, scheme),
            authority=pick(self.authority, authority),
            path=pick(self.path, path),
            query=pick(self.query, query),
            fragment=pick(self.fragment, fragment),
        )

    def normalize(self) -> "URIReference":
        # 极简 normalize：scheme 小写；authority 原样（不做 punycode 等）
        sch = self.scheme.lower() if self.scheme else None
        return URIReference(scheme=sch, authority=self.authority, path=self.path, query=self.query, fragment=self.fragment)


def uri_reference(value: str) -> URIReference:
    sp = urlsplit(value)
    # urlsplit 返回 netloc，我们映射到 authority
    scheme = sp.scheme or None
    authority = sp.netloc or None
    path = sp.path or None
    query = sp.query or None
    fragment = sp.fragment or None
    return URIReference(scheme=scheme, authority=authority, path=path, query=query, fragment=fragment)


def _install_as_rfc3986() -> None:
    """若官方 rfc3986 不可用，则把本 shim 注册为顶层包 `rfc3986`。"""
    import sys

    if "rfc3986" in sys.modules:
        return
    try:  # 官方包优先：已安装则不覆盖
        import rfc3986  # noqa: F401
        return
    except ImportError:
        pass

    from . import exceptions, misc, validators

    pkg = sys.modules[__name__]
    sys.modules["rfc3986"] = pkg
    sys.modules["rfc3986.exceptions"] = exceptions
    sys.modules["rfc3986.misc"] = misc
    sys.modules["rfc3986.validators"] = validators


_install_as_rfc3986()

