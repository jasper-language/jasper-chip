# -*- coding: utf-8 -*-
"""离线安装依赖（给无网环境用）。

重要说明（针对本工程的现实情况）
- Amaranth 0.5.x 依赖 jschon；jschon 依赖 rfc3986。
- 所需的 wheel 里没有 rfc3986，因此 pip 默认会报 "No matching distribution found for rfc3986"。
- 为了让工程在无网环境里也能跑起来，本仓库在根目录内自带了一个 **极简 rfc3986 兼容 shim**（`_rfc3986_shim/`，自研代码，非上游 vendored 代码）。
  它只覆盖 jschon 用到的最小 API，适合研究/验证使用。

用法
1) 把 wheel 放到 `third_party_wheels/` 目录（与本脚本同级）
2) 运行：
      python install_deps_offline.py

脚本策略
- 使用 `pip install --no-deps` 逐个安装：pyvcd / jschon / amaranth。
- 依赖解析不交给 pip（避免缺 rfc3986 时直接失败），由我们在仓库里提供的兼容层兜底。

若开发机可以联网或 wheel 齐全，建议直接安装官方 rfc3986 包并删除本仓库内的兼容层。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

WHEEL_DIR = Path(__file__).resolve().parent / "third_party_wheels"

# 只装我们确定需要的包
NEEDED = [
    "pyvcd",
    "jschon",
    "amaranth",
]


def main() -> None:
    if not WHEEL_DIR.exists():
        raise SystemExit(f"找不到目录：{WHEEL_DIR}\n请创建并把 .whl 放进去。")

    print(f"Using wheel dir: {WHEEL_DIR}")

    for name in NEEDED:
        print(f"\n== Installing {name} ==")
        cmd = [
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--find-links",
            str(WHEEL_DIR),
            name,
        ]
        subprocess.check_call(cmd)

    print("\nOK: offline deps installed.")


if __name__ == "__main__":
    main()
