# tools/step31_mutator_report.py
# -*- coding: utf-8 -*-

"""Step31：更贴近真实 mutator 的多核写屏障压力模型（纯 Python 快速评估）

本工具的定位：
  - Step25~Step30 我们已经把 sweep(card) 去重表做成了“可扫参、可报告、可回归”。
  - 但这些 workload 仍然偏“表格/序列驱动”，缺少更像真实系统的 mutator 行为：
      * 多核并发写入
      * 热点/长尾（Zipf）分布
      * 分阶段（phase）热区迁移
      * scan(remembered-set) 的去重/epoch 生命周期
      * scan -> out_q -> sweep 的端到端联动

因此 Step31 增加一个纯 Python 模型（不依赖 RTL 仿真），用于：
  1) 以固定种子可复现地生成多核写入 card 流。
  2) 模拟 scan 的去重/epoch + 共享引擎消费（consume_every + batch_size）。
  3) 模拟 sweep 的 set-associative 去重表（含 xor-fold index）。
  4) 输出 JSON + Markdown 报告，便于参数/方向评估。

注意：
  - 这是“研究用模型”，目标是趋势正确 + 可复现 + 跑得快。
  - 它不替代 RTL 级功能验证（RTL 仍由 tests/test_elaborate 等覆盖）。

用法示例：
  python -m tools.step31_mutator_report --outdir reports --name step31_mutator

会生成：
  reports/step31_mutator.json
  reports/step31_mutator.md
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple


def xor_fold_index(card_id: int, idx_bits: int) -> int:
    """把 card_id 按 idx_bits 分块 XOR 折叠，降低低位冲突。"""
    if idx_bits <= 0:
        return 0
    mask = (1 << idx_bits) - 1
    x = card_id
    acc = 0
    while x:
        acc ^= (x & mask)
        x >>= idx_bits
    return acc & mask


def zipf_sample(rng: random.Random, n: int, s: float) -> int:
    """简单 Zipf 采样：返回 [0, n-1]。

    为了可控/可复现/不引入第三方依赖，我们用“离散 CDF + 线性搜索”的简化做法。
    n 在本工具里一般不大（几十~几百），性能足够。
    """
    assert n > 0
    # 预先计算 CDF 的开销在 step31 默认规模下可以接受。
    weights = [1.0 / ((k + 1) ** s) for k in range(n)]
    total = sum(weights)
    cdf = []
    acc = 0.0
    for w in weights:
        acc += w / total
        cdf.append(acc)
    u = rng.random()
    for i, p in enumerate(cdf):
        if u <= p:
            return i
    return n - 1


@dataclass
class ScanStats:
    in_count: int = 0
    uniq_enq: int = 0
    dup_drop: int = 0
    stall_in: int = 0
    out_emit: int = 0


@dataclass
class SweepStats:
    mark_total: int = 0
    dup_drop: int = 0
    hit: int = 0
    miss: int = 0
    replace: int = 0
    per_core_mark: List[int] = None


class ScanModel:
    """scan：每核去重集合 + 每核 FIFO + 共享引擎消费 -> out_q"""

    def __init__(
        self,
        ncores: int,
        cardset_size: int,
        fifo_depth: int,
        consume_every: int,
        batch_size: int,
        seed: int,
    ):
        self.ncores = ncores
        self.cardset_size = cardset_size
        self.fifo_depth = fifo_depth
        self.consume_every = consume_every
        self.batch_size = batch_size
        self.epoch = 0
        self.rng = random.Random(seed)

        # per-core: set entries (card_id, epoch) and FIFO of card_ids
        self.set_entries: List[List[Tuple[int, int]]] = [[] for _ in range(ncores)]
        self.fifos: List[List[int]] = [[] for _ in range(ncores)]
        self.stats: List[ScanStats] = [ScanStats() for _ in range(ncores)]

        # shared engine scheduling
        self.cycle = 0
        self.rr_ptr = 0
        self.credit = 0

        # out queue (unbounded for research model)
        self.out_records: List[Tuple[int, int, int]] = []  # (core, card_id, epoch)

    def advance_epoch(self):
        self.epoch ^= 1
        # 旧 epoch 的 set entries 在本模型里不需要显式清除：
        # 插入时允许覆盖旧 epoch 条目。

    def _set_contains(self, core: int, card_id: int) -> bool:
        for cid, ep in self.set_entries[core]:
            if ep == self.epoch and cid == card_id:
                return True
        return False

    def _set_insert(self, core: int, card_id: int) -> bool:
        """尝试插入去重集合。返回是否成功（集合有空位/可覆盖旧epoch）。"""
        # 优先覆盖旧 epoch 条目
        for i, (cid, ep) in enumerate(self.set_entries[core]):
            if ep != self.epoch:
                self.set_entries[core][i] = (card_id, self.epoch)
                return True
        if len(self.set_entries[core]) < self.cardset_size:
            self.set_entries[core].append((card_id, self.epoch))
            return True
        return False

    def _set_remove(self, core: int, card_id: int):
        # 仅删除当前 epoch 的条目
        self.set_entries[core] = [
            (cid, ep)
            for (cid, ep) in self.set_entries[core]
            if not (ep == self.epoch and cid == card_id)
        ]

    def push_event(self, core: int, card_id: int):
        st = self.stats[core]
        st.in_count += 1

        # FIFO 满则 backpressure（研究模型：记录 stall，不丢事件）
        if len(self.fifos[core]) >= self.fifo_depth:
            st.stall_in += 1
            return False

        # 去重：同 epoch 内已存在则直接接受但不入 FIFO
        if self._set_contains(core, card_id):
            st.dup_drop += 1
            return True

        # 插入集合（可能因为集合满失败）
        if not self._set_insert(core, card_id):
            st.stall_in += 1
            return False

        # 入 FIFO
        self.fifos[core].append(card_id)
        st.uniq_enq += 1
        return True

    def step(self, steps: int = 1):
        """推进 scan 模型若干 cycle，执行共享引擎消费并生成 out_records。"""
        for _ in range(steps):
            self.cycle += 1

            # tick 控制：consume_every==0 表示永不消费
            tick = False
            if self.consume_every > 0 and (self.cycle % self.consume_every == 0):
                tick = True

            if tick and self.credit == 0:
                self.credit = max(1, self.batch_size)

            if self.credit > 0:
                # 尝试消费 1 条
                consumed = False
                for k in range(self.ncores):
                    core = (self.rr_ptr + k) % self.ncores
                    if self.fifos[core]:
                        card_id = self.fifos[core].pop(0)
                        self.out_records.append((core, card_id, self.epoch))
                        self.stats[core].out_emit += 1
                        self._set_remove(core, card_id)
                        self.rr_ptr = (core + 1) % self.ncores
                        consumed = True
                        break
                if consumed:
                    self.credit -= 1
                else:
                    # 没有数据可消费，直接清 credit
                    self.credit = 0


class SweepModel:
    """sweep：消费 (core, card, epoch) 记录，做 set-associative 去重"""

    def __init__(
        self,
        ncores: int,
        sets: int,
        ways: int,
        index_mode: int,
    ):
        assert sets > 0 and (sets & (sets - 1) == 0), "sets 必须是 2 的幂"
        assert ways >= 1
        self.ncores = ncores
        self.sets = sets
        self.ways = ways
        self.index_mode = index_mode
        self.idx_bits = int(math.log2(sets))

        # table[set][way] = (valid, card_id, epoch)
        self.table = [[(False, 0, 0) for _ in range(ways)] for _ in range(sets)]
        self.repl_ptr = [0 for _ in range(sets)]

        self.stats = SweepStats(per_core_mark=[0 for _ in range(ncores)])

    def _index(self, card_id: int) -> int:
        if self.index_mode == 1:
            return xor_fold_index(card_id, self.idx_bits)
        return card_id & (self.sets - 1)

    def consume(self, core: int, card_id: int, epoch: int):
        s = self._index(card_id)
        # hit?
        for w in range(self.ways):
            v, cid, ep = self.table[s][w]
            if v and cid == card_id and ep == epoch:
                self.stats.hit += 1
                self.stats.dup_drop += 1
                return
        # miss
        self.stats.miss += 1
        self.stats.mark_total += 1
        self.stats.per_core_mark[core] += 1

        # find empty or stale(epoch!=epoch)
        for w in range(self.ways):
            v, cid, ep = self.table[s][w]
            if (not v) or (ep != epoch):
                self.table[s][w] = (True, card_id, epoch)
                return
        # replace
        self.stats.replace += 1
        ins = 0 if self.ways == 1 else self.repl_ptr[s]
        self.table[s][ins] = (True, card_id, epoch)
        if self.ways > 1:
            self.repl_ptr[s] = (self.repl_ptr[s] + 1) % self.ways


def run_step31(
    *,
    seed: int,
    ncores: int,
    epochs: int,
    events_per_core_per_epoch: int,
    card_space: int,
    zipf_s: float,
    phase_shift: int,
    scan_cardset_size: int,
    scan_fifo_depth: int,
    scan_consume_every: int,
    scan_batch_size: int,
    sweep_sets: int,
    sweep_ways: int,
    sweep_index_mode: int,
    workload_mode: str = "shared_hot_shift",
    global_share_p: float = 0.10,
) -> Dict:
    """跑一个“多核 mutator -> scan -> sweep”的端到端模型，返回统计。"""
    rng = random.Random(seed)
    scan = ScanModel(
        ncores=ncores,
        cardset_size=scan_cardset_size,
        fifo_depth=scan_fifo_depth,
        consume_every=scan_consume_every,
        batch_size=scan_batch_size,
        seed=seed ^ 0xA5A5,
    )
    sweep = SweepModel(
        ncores=ncores,
        sets=sweep_sets,
        ways=sweep_ways,
        index_mode=sweep_index_mode,
    )

    # 额外统计：每核触达的 card 分布（用于多核 workload 评估；不影响 scan/sweep 行为）
    per_core_cards = [set() for _ in range(ncores)]

    # 事件生成：每个 epoch 分两个 phase，热区右移 phase_shift。
    # 多核 interleave：每轮 round-robin 产生 1 条事件。
    per_epoch_total = events_per_core_per_epoch * ncores
    for ep in range(epochs):
        # phase0 / phase1
        half = per_epoch_total // 2
        for i in range(per_epoch_total):
            core = i % ncores
            phase = 0 if i < half else 1
            hot_offset = (ep + phase) * phase_shift

            if workload_mode == "shared_hot_shift":
                # 旧模型：全局共享热点 + phase_shift 迁移（保持与 Step31/Step32 baseline 完全一致）
                base = hot_offset % max(1, card_space)
                # 在 card_space 内做 Zipf 采样，然后加 base 偏移
                x = zipf_sample(rng, card_space, zipf_s)
                card_id = (base + x) % card_space
            elif workload_mode == "per_core_partition":
                # 新 workload：每核主要写自己的分区（local hot），但以一定概率写全局热点（模拟共享对象/全局结构）
                cs = max(1, card_space)
                local_space = max(1, cs // max(1, ncores))
                if rng.random() < float(global_share_p):
                    base = hot_offset % cs
                    x = zipf_sample(rng, cs, zipf_s)
                    card_id = (base + x) % cs
                else:
                    base = (core * local_space + hot_offset) % cs
                    x = zipf_sample(rng, local_space, zipf_s)
                    card_id = (base + x) % cs
            else:
                raise ValueError(f"unknown workload_mode={workload_mode!r}")
            per_core_cards[core].add(card_id)
            scan.push_event(core, card_id)
            # 每产生一条事件推进 1 cycle，模拟并发写入
            scan.step(1)

        # epoch 结束：尽量 drain scan
        scan.step(scan_consume_every * max(1, scan_batch_size) * 4)

        # sweep 消费 scan 输出
        while scan.out_records:
            core, card_id, epoch = scan.out_records.pop(0)
            sweep.consume(core, card_id, epoch)

        # 进入下一轮 GC epoch
        if ep != epochs - 1:
            scan.advance_epoch()

    # 汇总
    scan_totals = {
        "in_count": sum(s.in_count for s in scan.stats),
        "uniq_enq": sum(s.uniq_enq for s in scan.stats),
        "dup_drop": sum(s.dup_drop for s in scan.stats),
        "stall_in": sum(s.stall_in for s in scan.stats),
        "out_emit": sum(s.out_emit for s in scan.stats),
        "per_core": [asdict(s) for s in scan.stats],
    }
    # card 分布统计（union/shared/jaccard）
    union_cards = set()
    for s in per_core_cards:
        union_cards |= s
    shared_cards = set()
    for c in union_cards:
        owners = 0
        for s in per_core_cards:
            if c in s:
                owners += 1
                if owners >= 2:
                    shared_cards.add(c)
                    break
    # 平均 Jaccard（两两 core）
    j_sum = 0.0
    j_cnt = 0
    for i in range(ncores):
        for j in range(i + 1, ncores):
            a = per_core_cards[i]
            b = per_core_cards[j]
            u = len(a | b)
            inter = len(a & b)
            j_sum += (inter / u) if u else 0.0
            j_cnt += 1
    avg_jaccard = (j_sum / j_cnt) if j_cnt else 0.0

    card_dist = {
        "per_core_unique": [len(s) for s in per_core_cards],
        "union_unique": len(union_cards),
        "shared_unique": len(shared_cards),
        "shared_ratio": (len(shared_cards) / len(union_cards)) if union_cards else 0.0,
        "avg_jaccard": avg_jaccard,
    }

    sweep_totals = asdict(sweep.stats)
    return {
        "seed": seed,
        "ncores": ncores,
        "epochs": epochs,
        "events_per_core_per_epoch": events_per_core_per_epoch,
        "card_space": card_space,
        "zipf_s": zipf_s,
        "phase_shift": phase_shift,
        "workload": {"mode": workload_mode, "global_share_p": float(global_share_p)},
        "card_dist": card_dist,
        "scan": {
            "cardset_size": scan_cardset_size,
            "fifo_depth": scan_fifo_depth,
            "consume_every": scan_consume_every,
            "batch_size": scan_batch_size,
            "stats": scan_totals,
        },
        "sweep": {
            "sets": sweep_sets,
            "ways": sweep_ways,
            "index_mode": sweep_index_mode,
            "stats": sweep_totals,
        },
        "cycle": scan.cycle,
    }


def _md_report(d: Dict) -> str:
    scan = d["scan"]
    sweep = d["sweep"]
    sst = scan["stats"]
    wst = sweep["stats"]
    lines = []
    lines.append("# Step31 Mutator→Scan→Sweep Report\n")
    lines.append("## Config\n")
    lines.append(f"- seed={d['seed']} ncores={d['ncores']} epochs={d['epochs']}\n")
    lines.append(f"- events/core/epoch={d['events_per_core_per_epoch']} card_space={d['card_space']} zipf_s={d['zipf_s']} phase_shift={d['phase_shift']}\n")
    lines.append(
        f"- scan: cardset={scan['cardset_size']} fifo={scan['fifo_depth']} consume_every={scan['consume_every']} batch={scan['batch_size']}\n"
    )
    lines.append(
        f"- sweep: sets={sweep['sets']} ways={sweep['ways']} index_mode={sweep['index_mode']}\n"
    )
    lines.append("\n## Summary\n")
    lines.append(f"- cycles={d['cycle']}\n")
    lines.append(
        f"- scan: in={sst['in_count']} uniq={sst['uniq_enq']} dup={sst['dup_drop']} stall={sst['stall_in']} out={sst['out_emit']}\n"
    )
    lines.append(
        f"- sweep: mark={wst['mark_total']} dup_drop={wst['dup_drop']} hit={wst['hit']} miss={wst['miss']} replace={wst['replace']}\n"
    )
    lines.append("\n## Per-core scan stats\n")
    lines.append("|core|in|uniq|dup|stall|out|\n|---:|---:|---:|---:|---:|---:|\n")
    for i, s in enumerate(sst["per_core"]):
        lines.append(
            f"|{i}|{s['in_count']}|{s['uniq_enq']}|{s['dup_drop']}|{s['stall_in']}|{s['out_emit']}|\n"
        )
    lines.append("\n## Per-core sweep marks\n")
    lines.append("|core|mark|\n|---:|---:|\n")
    for i, v in enumerate(wst["per_core_mark"]):
        lines.append(f"|{i}|{v}|\n")
    return "".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--name", default="step31_mutator")
    ap.add_argument("--seed", type=int, default=20260102)
    ap.add_argument("--ncores", type=int, default=4)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--events-per-core-per-epoch", type=int, default=128)
    ap.add_argument("--card-space", type=int, default=64)
    ap.add_argument("--zipf-s", type=float, default=1.15)
    ap.add_argument("--phase-shift", type=int, default=16)

    ap.add_argument("--workload", choices=["shared_hot_shift", "per_core_partition"], default="shared_hot_shift")
    ap.add_argument("--global-share-p", type=float, default=0.10, help="only for per_core_partition: probability of choosing global hot region")
    ap.add_argument("--scan-cardset", type=int, default=16)
    ap.add_argument("--scan-fifo", type=int, default=4)
    ap.add_argument("--scan-consume-every", type=int, default=4)
    ap.add_argument("--scan-batch", type=int, default=4)
    ap.add_argument("--sweep-sets", type=int, default=None)
    ap.add_argument("--sweep-ways", type=int, default=None)
    ap.add_argument("--sweep-index", type=int, default=None)
    args = ap.parse_args()

    # 默认使用 Step30 固化的推荐配置
    from rtl import gc_params

    sets = args.sweep_sets if args.sweep_sets is not None else gc_params.DEFAULT_SWEEP_CARD_TABLE_SIZE
    ways = args.sweep_ways if args.sweep_ways is not None else gc_params.DEFAULT_SWEEP_CARD_TABLE_WAYS
    idxm = args.sweep_index if args.sweep_index is not None else gc_params.DEFAULT_SWEEP_CARD_INDEX_MODE

    d = run_step31(
        seed=args.seed,
        ncores=args.ncores,
        epochs=args.epochs,
        events_per_core_per_epoch=args.events_per_core_per_epoch,
        card_space=args.card_space,
        zipf_s=args.zipf_s,
        phase_shift=args.phase_shift,
        scan_cardset_size=args.scan_cardset,
        scan_fifo_depth=args.scan_fifo,
        scan_consume_every=args.scan_consume_every,
        scan_batch_size=args.scan_batch,
        sweep_sets=sets,
        sweep_ways=ways,
        sweep_index_mode=idxm,
    )

    os.makedirs(args.outdir, exist_ok=True)
    jpath = os.path.join(args.outdir, f"{args.name}.json")
    mpath = os.path.join(args.outdir, f"{args.name}.md")

    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

    with open(mpath, "w", encoding="utf-8") as f:
        f.write(_md_report(d))

    print(f"OK: wrote {jpath} and {mpath}")


if __name__ == "__main__":
    main()
