# rtl/gc_params.py
# -*- coding: utf-8 -*-

"""GC 研究默认参数（Step30 自动生成）

该文件的目标是：让 SoC 默认参数不再靠手填，而是来自一个“可复现的推荐配置”。

生成方式：
  - 运行 `python -m tools.generate_step30_baseline`
  - 脚本会用固定种子/固定规模 workload 做一次小扫参
  - 取归一化全局 Top-1 作为默认 sweep 去重表配置

这套流程可作为研究阶段的“参数锁定 + 回归基线”。
"""

# Sweep(card) 去重表默认参数：
DEFAULT_SWEEP_CARD_TABLE_SIZE = 8
DEFAULT_SWEEP_CARD_TABLE_WAYS = 2
DEFAULT_SWEEP_CARD_INDEX_MODE = 1  # 0=lowbits, 1=xor-fold
