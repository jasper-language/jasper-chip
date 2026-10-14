# tests/test_step31_mutator_report.py
# -*- coding: utf-8 -*-

"""Step31 实际效果：更贴近真实 mutator 的多核写屏障模型可生成报告。

这不是 RTL 功能验证，而是“研究用快速评估模型”是否可复现 & 输出结构正确。
重点断言：
  - 工具能生成 json/md
  - 基本不变量成立：uniq<=in，mark<=out
  - 默认 sweep 参数来自 rtl/gc_params.py（Step30 固化）
"""

import json
import os
import tempfile


def main():
    from rtl import gc_params
    from tools.step31_mutator_report import run_step31

    # 用很小规模保证单测快速
    d = run_step31(
        seed=123,
        ncores=4,
        epochs=2,
        events_per_core_per_epoch=16,
        card_space=32,
        zipf_s=1.2,
        phase_shift=8,
        scan_cardset_size=8,
        scan_fifo_depth=2,
        scan_consume_every=2,
        scan_batch_size=2,
        sweep_sets=gc_params.DEFAULT_SWEEP_CARD_TABLE_SIZE,
        sweep_ways=gc_params.DEFAULT_SWEEP_CARD_TABLE_WAYS,
        sweep_index_mode=gc_params.DEFAULT_SWEEP_CARD_INDEX_MODE,
    )

    scan = d["scan"]["stats"]
    sweep = d["sweep"]["stats"]

    assert scan["uniq_enq"] <= scan["in_count"]
    assert sweep["mark_total"] <= scan["out_emit"]
    assert sum(sweep["per_core_mark"]) == sweep["mark_total"]

    # 生成文件，验证 json/md 输出
    from tools.step31_mutator_report import _md_report

    with tempfile.TemporaryDirectory() as td:
        jpath = os.path.join(td, "r.json")
        mpath = os.path.join(td, "r.md")
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        with open(mpath, "w", encoding="utf-8") as f:
            f.write(_md_report(d))
        assert os.path.getsize(jpath) > 50
        assert os.path.getsize(mpath) > 50

    print("OK: step31 mutator report model runs and outputs are consistent.")


if __name__ == "__main__":
    main()
