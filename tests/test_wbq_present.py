# -*- coding: utf-8 -*-
"""Step6-B/C：写屏障事件本地队列（wbq）存在性测试。

这不是功能仿真，而是一个“结构性”测试：
- 证明 RV12Core 里确实实例化了 wbq（SyncFIFO），且 elaboration 不会被它破坏。

运行：
  python -m tests.test_wbq_present
"""

from __future__ import annotations

from amaranth.back import rtlil

from rtl.rv12_core import RV12Core


def main() -> None:
    core = RV12Core(core_id=0)
    il = rtlil.convert(core, name="RV12Core", ports=[core.trap])

    # Amaranth RTLIL 输出中层级 module 名一般类似：RV12Core.wbq
    assert ("wbq" in il), "RTLIL 中未找到 wbq（写屏障本地队列）"

    print("OK: RV12Core contains wbq (write-barrier local FIFO).")


if __name__ == "__main__":
    main()
