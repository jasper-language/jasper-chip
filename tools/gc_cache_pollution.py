#!/usr/bin/env python3
# tools/gc_cache_pollution.py
# GC 缓存污染分析工具链
# 算法: Trace Cache + Shadow Cache + Victim Attribution + MRC + Bypass + CPI

"""
用法:
  python3 tools/gc_cache_pollution.py --trace gc_trace.csv
  python3 tools/gc_cache_pollution.py --gen-trace  # 生成模拟trace
  python3 tools/gc_cache_pollution.py --trace gc_trace.csv --analyze
"""

import csv, sys, math, random, argparse
from collections import defaultdict, OrderedDict
from enum import Enum, auto

# ─── 缓存配置 ───────────────────────────────────────────────────
class CacheConfig:
    def __init__(self, size=32768, ways=4, line_size=64, hit_latency=2, miss_latency=10):
        self.size = size          # bytes
        self.ways = ways          # associativity (0 = fully associative)
        self.line_size = line_size
        self.hit_latency = hit_latency
        self.miss_latency = miss_latency
        self.sets = size // (ways * line_size) if ways > 0 else 1
        self.tag_bits = 32 - int(math.log2(line_size)) - int(math.log2(max(self.sets, 1)))

    def __str__(self):
        return f"{self.size//1024}KB {self.ways}-way, line={self.line_size}B"

# ─── 访问来源标记 ───────────────────────────────────────────────
class AccessSource(Enum):
    MUTATOR      = auto()
    GC_MARK      = auto()
    GC_SCAN      = auto()
    GC_CARD      = auto()
    GC_FORWARD   = auto()
    GC_ROOT      = auto()
    GC_SWEEP     = auto()
    GC_OTHER     = auto()

SRC_NAMES = {s: s.name.lower() for s in AccessSource}

# ─── Cache Line ─────────────────────────────────────────────────
class CacheLine:
    def __init__(self):
        self.tag = None
        self.valid = False
        self.source = AccessSource.MUTATOR
        self.last_access = 0      # for LRU
        self.owner_tag = "mutator"

    def __repr__(self):
        return f"tag=0x{self.tag:08x}" if self.valid else "invalid"

# ─── 1. Trace-driven Cache Simulation ──────────────────────────
class TraceCache:
    """基础 Cache 模拟器: direct-mapped / N-way / LRU / FIFO / Random"""
    def __init__(self, config: CacheConfig, policy="lru"):
        self.cfg = config
        self.policy = policy
        self.sets = config.sets if config.ways > 0 else 1
        self.ways = config.ways if config.ways > 0 else 1
        self.lines = [[CacheLine() for _ in range(self.ways)] for _ in range(self.sets)]
        self.hits = 0
        self.misses = 0
        self.accesses = 0
        self.evictions = 0
        self.victim_log = []  # (victim_source, evictor_source)

    def access(self, addr: int, source=AccessSource.MUTATOR):
        """访问一个地址, 返回 hit/miss"""
        self.accesses += 1
        idx = (addr >> int(math.log2(self.cfg.line_size))) % self.sets
        tag = addr >> int(math.log2(self.cfg.line_size)) >> int(math.log2(max(self.sets, 1)))
        set_lines = self.lines[idx]

        # 查找 hit
        for line in set_lines:
            if line.valid and line.tag == tag:
                self.hits += 1
                line.last_access = self.accesses
                line.source = source
                return True

        # Miss: 选择 victim
        victim = self._select_victim(set_lines)
        self.misses += 1

        # 记录驱逐
        if victim.valid:
            self.evictions += 1
            self.victim_log.append((victim.source, source))

        # 加载新行
        victim.valid = True
        victim.tag = tag
        victim.source = source
        victim.last_access = self.accesses
        victim.owner_tag = source.name.lower()
        return False

    def _select_victim(self, lines):
        if self.policy == "lru":
            return min(lines, key=lambda l: l.last_access if l.valid else -1)
        elif self.policy == "fifo":
            return lines[0]  # simplified
        elif self.policy == "random":
            return random.choice(lines)
        elif self.policy == "rrrip":
            # RRIP: prefer invalid lines, then high re-reference interval
            invalid = [l for l in lines if not l.valid]
            return invalid[0] if invalid else lines[0]
        elif self.policy == "protect-mutator":
            # Protect mutator: prefer evict GC lines over mutator
            invalid = [l for l in lines if not l.valid]
            if invalid:
                return invalid[0]
            gc_lines = [l for l in lines if l.source != AccessSource.MUTATOR]
            return gc_lines[0] if gc_lines else lines[0]
        return lines[0]

    def stats(self):
        hr = self.hits / max(self.accesses, 1)
        return dict(hits=self.hits, misses=self.misses, accesses=self.accesses,
                    hit_rate=hr, miss_rate=1-hr, evictions=self.evictions)

# ─── 2. Shadow Cache ──────────────────────────────────────────
class ShadowCacheModel:
    """RealCache + ShadowMutatorCache 判断 GC 污染"""
    def __init__(self, config: CacheConfig):
        self.real = TraceCache(config, "lru")
        self.shadow = TraceCache(config, "lru")  # only mutator accesses
        self.pollution_misses = 0  # RealCache miss but ShadowCache hit
        self.pollution_events = []

    def access(self, addr, source):
        real_hit = self.real.access(addr, source)
        if source == AccessSource.MUTATOR:
            self.shadow.access(addr, source)
            if not real_hit:
                # RealCache miss, check ShadowCache
                idx = (addr >> 6) % self.shadow.sets
                tag = addr >> 6 >> int(math.log2(max(self.shadow.sets, 1)))
                for line in self.shadow.lines[idx]:
                    if line.valid and line.tag == tag:
                        self.pollution_misses += 1
                        self.pollution_events.append((addr, self.real.accesses))
                        break
        return real_hit

# ─── 3. Victim Attribution ────────────────────────────────────
class VictimAttribution:
    """驱逐归因: 记录每条 cache line 的来源和驱逐原因"""
    def __init__(self):
        self.evictions = []  # (victim_src, evictor_src, cycle)
        self.counts = defaultdict(int)  # "victim→evictor" counts

    def record(self, victim, evictor, cycle=0):
        pair = (victim.name, evictor.name)
        self.evictions.append((victim, evictor, cycle))
        self.counts[pair] += 1

    def report(self):
        print(f"\n  Victim Attribution:")
        total = sum(self.counts.values())
        for pair, cnt in sorted(self.counts.items(), key=lambda x: -x[1]):
            print(f"    {pair[0]:12s} → {pair[1]:12s}: {cnt:5d}  ({cnt/total*100:.1f}%)")

# ─── 4. Reuse Distance ────────────────────────────────────────
def compute_reuse_distances(trace):
    """计算每个地址的 reuse distance (两次访问之间的独有地址数)"""
    last_access = {}
    reuse_dists = []
    window = OrderedDict()
    for cyc, (addr, src) in enumerate(trace):
        if addr in last_access:
            # count unique addresses between accesses
            rd = len(window)
            reuse_dists.append(rd)
        last_access[addr] = cyc
        # maintain window (sliding, simplified)
        window[addr] = cyc
        if len(window) > 10000:
            window.pop(next(iter(window)))
    return reuse_dists

# ─── 5. MRC (Miss Ratio Curve) ───────────────────────────────
def compute_mrc(reuse_dists, max_size=1024*1024):
    """从 reuse distance 推导 MRC: cache_size → miss_rate"""
    if not reuse_dists:
        return {}
    max_dist = max(reuse_dists)
    line_size = 64
    total = len(reuse_dists)
    mrc = {}
    for size_bytes in [1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576]:
        if size_bytes > max_size:
            break
        lines = size_bytes // line_size
        misses = sum(1 for d in reuse_dists if d >= lines)
        mrc[size_bytes // 1024] = misses / max(total, 1)
    return mrc

# ─── 6. AMAT / CPI Penalty ────────────────────────────────────
def compute_amat(cfg: CacheConfig, hit_rate):
    """Average Memory Access Time"""
    return cfg.hit_latency + (1 - hit_rate) * cfg.miss_latency

def compute_cpi_penalty(base_cpi, hit_rate, mem_access_per_inst, cfg):
    """CPI 增量: extra cycles from cache misses"""
    amat = compute_amat(cfg, hit_rate)
    base_amat = cfg.hit_latency  # ideal: all hits
    extra_cycles_per_access = (amat - base_amat) * (1 - hit_rate)
    return extra_cycles_per_access * mem_access_per_inst

# ─── Trace 生成 (模拟 GC workload) ─────────────────────────────
def gen_gc_trace(mutator_insts=10000, gc_ratio=0.15, working_set_kb=64):
    """生成模拟的 mutator + GC 访问 trace"""
    random.seed(42)
    trace = []
    ws_words = (working_set_kb * 1024) // 4
    gc_sources = [AccessSource.GC_MARK, AccessSource.GC_SCAN,
                  AccessSource.GC_CARD, AccessSource.GC_FORWARD]

    for cyc in range(mutator_insts):
        if random.random() < gc_ratio:
            # GC access
            addr = random.randint(0x80000000, 0x80000000 + ws_words * 4) & ~3
            src = random.choice(gc_sources)
        else:
            # Mutator access (working set)
            if random.random() < 0.8:
                addr = random.randint(0x1000, 0x1000 + ws_words * 4) & ~3
            else:
                addr = random.randint(0x20000000, 0x20000000 + random.randint(1, 100) * 4) & ~3
            src = AccessSource.MUTATOR
        trace.append((addr, src))
    return trace

# ─── 完整分析 ──────────────────────────────────────────────────
def full_analysis(trace, cache_cfg=CacheConfig(), label=""):
    """运行全套缓存污染分析"""
    print(f"\n{'='*60}")
    print(f"Cache Pollution Analysis: {label}")
    print(f"  Cache: {cache_cfg}")
    print(f"  Trace: {len(trace)} accesses")
    print(f"{'='*60}")

    # 1. Trace Cache (baseline)
    tc = TraceCache(cache_cfg)
    va = VictimAttribution()
    for addr, src in trace:
        hit = tc.access(addr, src)
        if not hit:
            for v, e in tc.victim_log[-1:]:
                va.record(v, e)
    s = tc.stats()
    print(f"\n  1. Baseline Cache:")
    print(f"     Hits: {s['hits']}, Misses: {s['misses']}, Rate: {s['hit_rate']*100:.1f}%")

    # 2. Shadow Cache
    sc = ShadowCacheModel(cache_cfg)
    for addr, src in trace:
        sc.access(addr, src)
    print(f"\n  2. Shadow Cache (GC Pollution):")
    print(f"     Pollution misses: {sc.pollution_misses} ")
    if s['misses'] > 0:
        print(f"     Pct of total misses: {sc.pollution_misses/s['misses']*100:.1f}%")

    # 3. Victim Attribution
    total_ev = len(va.evictions)
    print(f"\n  3. Victim Attribution:")
    print(f"     Total evictions: {total_ev}")
    for pair, cnt in sorted(va.counts.items(), key=lambda x: -x[1])[:8]:
        print(f"     {pair[0]:12s} → {pair[1]:12s}: {cnt:5d} ({cnt/total_ev*100:.1f}%)")

    # 4. Reuse Distance
    rds = compute_reuse_distances(trace)
    if rds:
        print(f"\n  4. Reuse Distance:")
        print(f"     Min: {min(rds)}, Max: {max(rds)}, Avg: {sum(rds)/len(rds):.0f}")

    # 5. MRC
    mrc = compute_mrc(rds)
    print(f"\n  5. MRC (Miss Ratio Curve):")
    for size_kb, mr in sorted(mrc.items()):
        print(f"     {size_kb:6}KB: miss_rate={mr*100:.1f}%")

    # 6. CPI Penalty
    mem_per_inst = 0.4  # typical: 40% of insts access memory
    base_cpi = 1.0
    penalty = compute_cpi_penalty(cache_cfg, s['hit_rate'], mem_per_inst, cache_cfg)
    print(f"\n  6. CPI Penalty (AMAT):")
    print(f"     AMAT: {compute_amat(cache_cfg, s['hit_rate']):.2f} cycles")
    print(f"     CPI penalty: {penalty:.3f}")

    # 7. Compare: with vs without GC
    mut_trace = [(a, s) for a, s in trace if s == AccessSource.MUTATOR]
    if len(mut_trace) > len(trace) * 0.1:
        only_mut = [(a, s) for a, s in trace if s == AccessSource.MUTATOR]
        if only_mut:
            tc_mut = TraceCache(cache_cfg)
            for addr, src in only_mut:
                tc_mut.access(addr, src)
            sm = tc_mut.stats()
            print(f"\n  7. Without GC (mutator only):")
            print(f"     Hit rate: {sm['hit_rate']*100:.1f}% → No GC baseline")
            print(f"     GC pollution delta: {(s['hit_rate']-sm['hit_rate'])*100:.1f}%")

    return {
        "baseline_hit_rate": s['hit_rate'],
        "pollution_misses": sc.pollution_misses,
        "cpi_penalty": penalty,
    }

# ─── 主入口 ──────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GC Cache Pollution Analyzer")
    parser.add_argument("--gen-trace", action="store_true", help="生成模拟 trace")
    parser.add_argument("--trace", help="trace CSV 文件 (addr,source)")
    parser.add_argument("--cache-size", type=int, default=32768, help="cache size (bytes)")
    parser.add_argument("--ways", type=int, default=4, help="associativity")
    parser.add_argument("--line-size", type=int, default=64, help="cache line size (bytes)")
    args = parser.parse_args()

    cfg = CacheConfig(size=args.cache_size, ways=args.ways, line_size=args.line_size)

    # 生成模拟 trace
    if args.gen_trace or not args.trace:
        print("Generating synthetic GC trace...")
        trace = gen_gc_trace(mutator_insts=20000, gc_ratio=0.15)
        full_analysis(trace, cfg, "Synthetic GC Workload")
    elif args.trace:
        trace = []
        with open(args.trace) as f:
            reader = csv.reader(f)
            for row in reader:
                addr = int(row[0], 16)
                src = AccessSource[row[1].strip().upper()]
                trace.append((addr, src))
        full_analysis(trace, cfg, f"Trace: {args.trace}")
    else:
        print("Use --gen-trace to generate a sample trace, or --trace <file.csv>")
