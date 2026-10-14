# 注册仓库自带的极简 rfc3986 兼容 shim（自研代码，非上游 vendored 代码）。
# 若系统已安装官方 rfc3986，shim 会自动让位。
import _rfc3986_shim  # noqa: F401
