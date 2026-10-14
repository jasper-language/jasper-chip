# -*- coding: utf-8 -*-
"""rfc3986.exceptions 的极简兼容实现。

jschon 只需要 ValidationError 这个异常类型。
"""

class ValidationError(ValueError):
    """URI 校验失败。"""
