# tests/test_step41_profile_step40_joint_baseline.py
# -*- coding: utf-8 -*-
"""Step41：profile(step40_joint) 回归测试

目的：
  1) 确认 reports/step41_profile_step40_joint_baseline.json 存在；
  2) 校验 profile(step40_joint) 与 Step40 knee 一致；
  3) 校验 TopSoC.with_profile('step40_joint') 的默认参数注入正确。
"""

from __future__ import annotations

import json
from pathlib import Path
import warnings


def _squelch_amaranth_unused_warning() -> None:
    """Suppress UnusedElaboratable warning if the Amaranth internal module exists."""
    try:
        from amaranth.hdl._unused import UnusedElaboratable  # type: ignore
        warnings.filterwarnings('ignore', category=UnusedElaboratable)
    except Exception:
        warnings.filterwarnings('ignore')


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    p = repo / 'reports' / 'step41_profile_step40_joint_baseline.json'
    assert p.exists(), f"missing baseline: {p} (run python -m tools.generate_step41_profile_step40_joint_baseline)"
    data = json.loads(p.read_text(encoding='utf-8'))
    assert data['matches'] is True

    # profile 内容一致
    from rtl.gc_profile_params import get_profile
    prof = get_profile('step40_joint')
    assert int(prof['scan']['cardset_size']) == int(data['step40_knee']['scan']['cardset_size'])
    assert int(prof['scan']['fifo_depth']) == int(data['step40_knee']['scan']['fifo_depth'])
    assert int(prof['scan']['consume_every']) == int(data['step40_knee']['scan']['consume_every'])
    assert int(prof['scan']['batch_size']) == int(data['step40_knee']['scan']['batch_size'])
    assert int(prof['sweep']['sets']) == int(data['step40_knee']['sweep']['sets'])
    assert int(prof['sweep']['ways']) == int(data['step40_knee']['sweep']['ways'])
    assert int(prof['sweep']['index_mode']) == int(data['step40_knee']['sweep']['index_mode'])

    # TopSoC 注入一致（不需要跑仿真）
    _squelch_amaranth_unused_warning()
    from rtl.top_soc import TopSoC
    soc = TopSoC.with_profile('step40_joint')

    # scan
    assert int(soc.scan_cardset_size) == int(data['step40_knee']['scan']['cardset_size'])
    assert int(soc.scan_fifo_depth) == int(data['step40_knee']['scan']['fifo_depth'])
    assert int(soc.scan_consume_every) == int(data['step40_knee']['scan']['consume_every'])
    assert int(soc.scan_batch_size) == int(data['step40_knee']['scan']['batch_size'])
    # sweep
    assert int(soc.sweep_card_table_size) == int(data['step40_knee']['sweep']['sets'])
    assert int(soc.sweep_card_table_ways) == int(data['step40_knee']['sweep']['ways'])
    assert int(soc.sweep_card_index_mode) == int(data['step40_knee']['sweep']['index_mode'])

    print('OK: step41 profile(step40_joint) stable and TopSoC.with_profile injects correctly.')


if __name__ == '__main__':
    main()
