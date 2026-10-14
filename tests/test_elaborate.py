# -*- coding: utf-8 -*-
"""Step3: 最小 elaboration 测试（纯 Python）。

目标
- 证明：在无网环境下，只要 wheel 齐全（或使用仓库自带的 `_rfc3986_shim/` 兼容 shim），
  就能成功 `import amaranth`，并把 TopSoC 转换为 RTLIL。

运行：
  python -m tests.test_elaborate

说明
- 这里不依赖 yosys/verilator，只做 Amaranth 的 rtlil.convert。
"""

from __future__ import annotations

from amaranth.back import rtlil

from rtl.top_soc import TopSoC


def main() -> None:
    top = TopSoC(ncores=2)
    il = rtlil.convert(top, name="TopSoC", ports=[top.trap])
    # 兼容 RTLIL 输出中 module 名的两种写法：
    #   module \TopSoC
    #   module TopSoC
    assert ("module \\TopSoC" in il) or ("module TopSoC" in il), "RTLIL 输出中未找到 TopSoC 模块"

    # Step4：验证 3 个 GC 协处理器“实例”都在 RTLIL 里出现（说明接口拆分已落地）。
    # 注意：Amaranth RTLIL 会用层级命名（例如 \TopSoC.gc_scan），而不是 class 名。
    def has_mod(name: str) -> bool:
        return (f"module \\{name}" in il) or (f"module {name}" in il)

    assert has_mod("TopSoC.gc_scan"), "RTLIL 输出中未找到 TopSoC.gc_scan 模块"
    assert has_mod("TopSoC.gc_sweep"), "RTLIL 输出中未找到 TopSoC.gc_sweep 模块"
    assert has_mod("TopSoC.gc_mv"), "RTLIL 输出中未找到 TopSoC.gc_mv 模块"

    print("OK: TopSoC elaboration + rtlil.convert succeeded (with 3 GC coprocessors).")


if __name__ == "__main__":
    main()
