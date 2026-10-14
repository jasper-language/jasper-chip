# rtl/gc_scan_params.py
# -*- coding: utf-8 -*-

"""Step33 自动推荐的 scan 默认参数（研究用）。

来源：tools/step33_scan_recommend.py 输出的 Top-1。
注意：这是趋势模型推荐，不等于 RTL 级最优。
"""

SCAN_CARDSET_SIZE = 8
SCAN_FIFO_DEPTH   = 1
SCAN_CONSUME_EVERY = 2
SCAN_BATCH_SIZE    = 2
