# tools/gc_trace.py
# GC Trace: 标准 trace 格式 + 捕获 + 分析
# cycle,core_id,pc,source,op,addr,size,is_write,is_heap,is_metadata

TRACE_HEADER = "cycle,core_id,pc,source,op,addr,size,is_write,is_heap,is_metadata"

SOURCES = ["MUTATOR","GC_WB","GC_RB","GC_CARD","GC_MARK",
           "GC_SCAN","GC_FORWARD","GC_ROOT","GC_SWEEP","GC_OTHER"]

def format_trace(cycle, core_id=0, pc=0, source="MUTATOR", op="LOAD",
                 addr=0, size=4, is_write=False, is_heap=False, is_metadata=False):
    return f"{cycle},{core_id},{pc:#010x},{source},{op},{addr:#010x},{size},{int(is_write)},{int(is_heap)},{int(is_metadata)}"

class TraceCapture:
    """仿真/调试用 trace 捕获器"""
    def __init__(self, path="gc_trace.csv", enabled=True):
        self.enabled = enabled
        if enabled:
            self.f = open(path, "w")
            self.f.write(TRACE_HEADER + "\n")
        self.cycle = 0

    def tick(self):
        self.cycle += 1

    def log(self, core_id=0, pc=0, source="MUTATOR", op="LOAD",
            addr=0, size=4, is_write=False, is_heap=False, is_metadata=False):
        if self.enabled:
            self.f.write(format_trace(self.cycle, core_id, pc, source, op,
                                       addr, size, is_write, is_heap, is_metadata) + "\n")

    def close(self):
        if self.enabled:
            self.f.close()

# ─── 从 Amaranth 仿真捕获 trace ───────────────────────────────
class TraceBridge:
    """连接到 Amaranth 仿真器, 捕获 load/store 地址"""
    def __init__(self, core, capture):
        self.core = core
        self.cap = capture

    def sample(self, cyc):
        """在每个仿真周期调用, 捕获访存"""
        # 通过 Amaranth yield 读取信号, 在仿真器中调用
        pass

# ─── 微基准 trace 生成 ─────────────────────────────────────────
def gen_microbench_traces():
    """从现有测试生成微基准 trace"""
    import os
    os.makedirs("traces", exist_ok=True)

    # WB 200x: 200 次堆 store
    trace = []
    for i in range(200):
        trace.append((0, 0, "MUTATOR", "STORE", 0x80000000 + i*4, 4, 1, 1, 0))
        trace.append((0, 0, "GC_WB", "WRITE", 0x80000000 + i*4, 8, 1, 1, 1))
    with open("traces/micro_wb_200x.csv", "w") as f:
        f.write(TRACE_HEADER + "\n")
        for cyc, (core, pc, src, op, addr, sz, wr, hp, md) in enumerate(trace):
            f.write(format_trace(cyc, core, pc, src, op, addr, sz, wr, hp, md) + "\n")
    print(f"  micro_wb_200x: {len(trace)} events")

    # RB load: 50 次堆 load + MV
    trace = []
    for i in range(50):
        trace.append((0, 0, "MUTATOR", "LOAD", 0x80000000 + i*4, 4, 0, 1, 0))
        trace.append((0, 0, "GC_RB", "READ", 0x80000000 + i*4, 4, 0, 1, 1))
    with open("traces/micro_rb_50x.csv", "w") as f:
        f.write(TRACE_HEADER + "\n")
        for cyc, (core, pc, src, op, addr, sz, wr, hp, md) in enumerate(trace):
            f.write(format_trace(cyc, core, pc, src, op, addr, sz, wr, hp, md) + "\n")
    print(f"  micro_rb_50x:  {len(trace)} events")

    # gc_new 20x
    trace = []
    for i in range(20):
        trace.append((0, 0, "MUTATOR", "GC_NEW", 0, 4, 1, 0, 0))
        trace.append((0, 0, "GC_SCAN", "WRITE", 0x80001000 + i*16, 16, 1, 1, 1))
    with open("traces/micro_gc_new_20x.csv", "w") as f:
        f.write(TRACE_HEADER + "\n")
        for cyc, (core, pc, src, op, addr, sz, wr, hp, md) in enumerate(trace):
            f.write(format_trace(cyc, core, pc, src, op, addr, sz, wr, hp, md) + "\n")
    print(f"  micro_gc_new_20x: {len(trace)} events")

    # gc_new+dep 20x
    trace = []
    for i in range(20):
        trace.append((0, 0, "MUTATOR", "GC_NEW", 0, 4, 1, 0, 0))
        trace.append((0, 0, "MUTATOR", "LOAD", 0x80001000 + i*16, 4, 0, 1, 0))
        trace.append((0, 0, "GC_RB", "READ", 0x80001000 + i*16, 4, 0, 1, 1))
    with open("traces/micro_gc_new_dep_20x.csv", "w") as f:
        f.write(TRACE_HEADER + "\n")
        for cyc, (core, pc, src, op, addr, sz, wr, hp, md) in enumerate(trace):
            f.write(format_trace(cyc, core, pc, src, op, addr, sz, wr, hp, md) + "\n")
    print(f"  micro_gc_new_dep_20x: {len(trace)} events")

    print(f"\n  微基准 traces: traces/ 目录")
    return ["traces/micro_wb_200x.csv", "traces/micro_rb_50x.csv",
            "traces/micro_gc_new_20x.csv", "traces/micro_gc_new_dep_20x.csv"]

# ─── 加载 trace ───────────────────────────────────────────────
def load_trace(path):
    """加载标准 trace CSV, 返回 (addr, source) 列表"""
    trace = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = int(row["addr"], 16) if "addr" in row else int(row[3], 16)
            src_name = row.get("source", "MUTATOR").strip().upper()
            try:
                src = getattr(__import__("tools.gc_cache_pollution", fromlist=["AccessSource"]).AccessSource, src_name)
            except:
                from tools.gc_cache_pollution import AccessSource
                src = getattr(AccessSource, src_name, AccessSource.MUTATOR)
            trace.append((addr, src))
    return trace

if __name__ == "__main__":
    print("生成微基准 traces...")
    gen_microbench_traces()
    print("\nTrace 格式: " + TRACE_HEADER)
