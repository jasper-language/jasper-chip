# tests/test_step33_scan_defaults.py
# -*- coding: utf-8 -*-

"""Step33：scan 默认参数固化（研究用）。

覆盖：
  1) rtl/gc_scan_params.py 存在且 TopSoC 默认值与之匹配。
  2) tools.step33_scan_recommend.recommend() 能在一个很小的网格上运行并输出 Top-1。

说明：此测试只依赖 Step31 的纯 Python 模型，运行应当很快。
"""

from __future__ import annotations

from rtl.top_soc import TopSoC
from rtl import gc_scan_params

from tools.step33_scan_recommend import ScanCfg, recommend


def main():
    # 1) TopSoC 默认值必须等于 gc_scan_params。
    soc = TopSoC()
    assert soc.scan_cardset_size == int(gc_scan_params.SCAN_CARDSET_SIZE)
    assert soc.scan_fifo_depth == int(gc_scan_params.SCAN_FIFO_DEPTH)
    assert soc.scan_consume_every == int(gc_scan_params.SCAN_CONSUME_EVERY)
    assert soc.scan_batch_size == int(gc_scan_params.SCAN_BATCH_SIZE)

    # 2) recommend() 在小网格上可运行。
    base_cfg = {
        "seed": 123,
        "ncores": 2,
        "epochs": 1,
        "events_per_core_per_epoch": 16,
        "card_space": 16,
        "zipf_s": 1.07,
        "phase_shift": 5,
    }
    grid = [
        ScanCfg(cardset_size=8, fifo_depth=1, consume_every=4, batch_size=1),
        ScanCfg(cardset_size=16, fifo_depth=2, consume_every=2, batch_size=2),
    ]
    rep = recommend(
        base_cfg=base_cfg,
        scan_grid=grid,
        topn=1,
        w_cycle=1.0,
        w_stall=8.0,
        w_replace=4.0,
    )
    assert "top" in rep and len(rep["top"]) == 1
    best = rep["top"][0]
    # sanity keys
    for k in ("score", "cardset_size", "fifo_depth", "consume_every", "batch_size", "cycle"):
        assert k in best

    print(
        f"best scan: cardset={best['cardset_size']} fifo={best['fifo_depth']} consume={best['consume_every']} batch={best['batch_size']} score={best['score']:.2f} cycle={best['cycle']}"
    )
    print("OK: step33 scan defaults wired and recommend runs.")


if __name__ == "__main__":
    main()
