# -*- coding: utf-8 -*-
"""环境自检脚本（离线也能跑）。

默认开发环境可能没有 amaranth/yosys/verilator/iverilog 等工具。
在开发机上先运行本脚本，可快速确认缺失项。

运行：
    python tool_check.py
"""

import importlib
import shutil

# 仓库自带的极简 rfc3986 兼容 shim（自研代码，非上游 vendored 代码）。
# 导入后若系统未安装官方 rfc3986，会在 sys.modules 中把自身注册为 `rfc3986`。
import _rfc3986_shim  # noqa: F401


def check_import(name: str):
    try:
        importlib.import_module(name)
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    print("== Python package checks ==")
    # Amaranth 0.5.x 需要额外依赖，否则连 import 都会失败（本仓库自带一个极简 rfc3986 兼容层）
    for pkg in ["amaranth", "jschon", "pyvcd", "rfc3986"]:
        ok, err = check_import(pkg)
        print(f"{pkg:10s}: {'OK' if ok else 'MISSING'}")
        if err and not ok:
            print(f"  reason: {err}")

    print("\n== External tool checks ==")
    for exe in ["yosys", "verilator", "iverilog", "slang"]:
        path = shutil.which(exe)
        print(f"{exe:10s}: {'OK' if path else 'MISSING'}" + (f" ({path})" if path else ""))

    print("\n== Suggestions ==")
    print("- 只跑纯 Python 自检：\n  python -m tests.test_isa")
    print("- 导出 Verilog：需要安装 amaranth + yosys")
    print("- lint/仿真：推荐 verilator 或 slang/iverilog")


if __name__ == "__main__":
    main()
