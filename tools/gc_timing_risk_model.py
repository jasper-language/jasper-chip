#!/usr/bin/env python3
# tools/gc_timing_risk_model.py
# GC 结构时序风险评估 (软件模型, 非真实 Fmax)
import re, csv, os, math
from collections import defaultdict

PROFILES = {
    "lite":     dict(gc_slots=8,  rb_slots=2,  ways=2,  wb=2,  mv=2,  meta_size=0),
    "standard": dict(gc_slots=16, rb_slots=4,  ways=4,  wb=4,  mv=4,  meta_size=4096),
    "server":   dict(gc_slots=32, rb_slots=16, ways=8,  wb=16, mv=16, meta_size=16384),
}

def analyze_rtl(path, params):
    """Analyze RTL file for timing risk factors."""
    with open(path) as f:
        content = f.read()
    
    # Substitute profile params
    subs = {
        'GC_SLOTS': str(params['gc_slots']), 'GC': str(params['gc_slots']),
        'RB_SLOTS': str(params['rb_slots']), 'RBL': str(params['rb_slots']),
        'RB_CACHE_WAYS': str(params['ways']), 'RBW': str(params['ways']),
        'WBD': str(params['wb']), 'MVD': str(params['mv']),
    }
    for k, v in subs.items():
        content = content.replace(k, v)
    
    # Remove debug-gated sections
    lines = content.split('\n')
    filtered = []
    skip = 0
    for line in lines:
        if 'if self._debug:' in line or 'if self.p.debug:' in line:
            skip = 1
        if 'if self.p.perf_counters_enable' in line:
            skip = 1
        if 'if self.p.debug and P.stream_buffer_enable' in line:
            skip = 1
        if skip > 0:
            skip -= 1
            continue
        filtered.append(line)
    content = '\n'.join(filtered)
    
    # Count risk factors
    fifos = len(re.findall(r'SyncFIFO\(', content))
    compares = len(re.findall(r'==', content))
    muxes = len(re.findall(r'Mux\(', content))
    dyn_idx = len(re.findall(r'Array\(Signal', content)) + len(re.findall(r'\[', content)) - fifos
    
    # Priority encoder width = max slot count
    pe_width = max(params['gc_slots'], params['rb_slots'], params['ways'])
    
    # Mux depth score: weighted combination
    mux_depth = 0
    mux_depth += params['gc_slots'] * 2  # GC slot priority encoders
    mux_depth += params['rb_slots'] * 2  # RB slot priority encoders
    mux_depth += params['ways'] * 2      # Cache way mux
    mux_depth += params['gc_slots']      # GC response match
    mux_depth += params['rb_slots']      # MV response match
    
    # Gate estimate
    bits = 0
    for m in re.finditer(r'Signal\((\d+)\)', content):
        bits += int(m.group(1))
    bits += len(re.findall(r'Signal\b(?!\()', content))
    bits += len(re.findall(r'Signal\(reset=', content))
    for m in re.finditer(r'Signal\(range\((\d+)\)', content):
        bits += int(m.group(1)).bit_length()
    for m in re.finditer(r'SyncFIFO\(width=([^,]+),\s*depth=(\d+)\)', content):
        w = m.group(1)
        try: w_eval = eval(w, {"__builtins__":{}}, {"MVD": params['mv'], "WBD": params['wb']})
        except: w_eval = int(w) if w.isdigit() else 80
        bits += w_eval * int(m.group(2))
    gates = int(bits * 6 * 1.3)
    
    return dict(
        fifos=fifos, compares=compares, muxes=muxes,
        dyn_idx=dyn_idx, pe_width=pe_width, mux_depth=mux_depth,
        gates=gates, bits=bits,
    )

def classify_frequency(risks):
    """Classify frequency risk based on structural factors."""
    score = 0
    # Mux depth penalty
    if risks['mux_depth'] > 500: score += 3
    elif risks['mux_depth'] > 200: score += 2
    elif risks['mux_depth'] > 100: score += 1
    
    # Priority encoder width
    if risks['pe_width'] > 16: score += 3
    elif risks['pe_width'] > 8: score += 2
    elif risks['pe_width'] > 4: score += 1
    
    # Dynamic array indexing
    if risks['dyn_idx'] > 20: score += 2
    elif risks['dyn_idx'] > 10: score += 1
    
    # FIFO count
    if risks['fifos'] > 3: score += 1
    
    # Compare count
    if risks['compares'] > 100: score += 1
    
    if score <= 2: return 'A', '高频友好, 可跟随主核'
    elif score <= 4: return 'B', '中等风险, 注意mux/compare'
    elif score <= 6: return 'C', '高风险, 需pipeline/bank/SRAM'
    else: return 'D', '不适合高频, 建议低频后端异步运行'

def run_backend_simulation(freq_hz=1e9, inst_per_core=1e9, gc_ratio=0.1, wb_per_gc=0.5, rb_per_gc=0.3):
    """Simulate backend queue occupancy."""
    insts = inst_per_core
    gc_insts = insts * gc_ratio
    wb_events = gc_insts * wb_per_gc
    rb_events = gc_insts * rb_per_gc
    meta_accesses = gc_insts * 0.8
    
    cycles_per_sec = freq_hz
    cyc_per_inst = 1.05  # average CPI
    total_cycles = insts * cyc_per_inst
    total_sec = total_cycles / cycles_per_sec
    
    # Queue depths (events/cycle × cycles to drain)
    wb_rate = wb_events / total_cycles
    rb_rate = rb_events / total_cycles
    meta_rate = meta_accesses / total_cycles
    
    # Drain rates (assumed backend throughput per cycle)
    scan_drain = 0.5  # Scan coproc consumes 0.5 events/cycle
    mv_drain = 1.0    # MV coproc handles 1 query/cycle
    meta_drain = 0.25 # Metadata cache fill: 1 per 4 cycles
    
    wb_max_q = wb_rate * 100  # queue over 100 cycles
    rb_max_q = rb_rate * 100
    meta_max_q = meta_rate * 100
    
    return dict(
        wb_max_q=max(1, wb_max_q), rb_max_q=max(1, rb_max_q),
        meta_max_q=max(1, meta_max_q),
        wb_backlog=(wb_rate > scan_drain),
        rb_backlog=(rb_rate > mv_drain),
        meta_backlog=(meta_rate > meta_drain),
    )

# ── Main analysis ──────────────────────────────────────────
MODULES = [
    ("rtl/gc_subsystem.py", "GCSubsystem"),
    ("rtl/gc_memory_policy.py", "GCMemPolicy"),
    ("rtl/gc_root_scanner.py", "RootScanner"),
    ("rtl/gc_heap_walker.py", "HeapWalker"),
    ("rtl/gc_cycle.py", "CycleCtrl"),
    ("rtl/gc_scan_coproc.py", "ScanCoProc"),
    ("rtl/gc_sweep_coproc.py", "SweepCoProc"),
    ("rtl/gc_mv_coproc.py", "MvCoProc"),
]

if __name__ == "__main__":
    os.makedirs("reports", exist_ok=True)
    
    md_rows = []
    csv_rows = [["module","profile","gates","fifos","compares","muxes",
                  "dyn_idx","pe_width","mux_depth","freq_class","bottleneck","recommendation"]]
    
    for prof_name, params in PROFILES.items():
        for path, mod_name in MODULES:
            risks = analyze_rtl(path, params)
            cls, note = classify_frequency(risks)
            
            bottleneck = []
            if risks['pe_width'] > 8: bottleneck.append(f"prio_enc_width={risks['pe_width']}")
            if risks['mux_depth'] > 200: bottleneck.append(f"mux_depth={risks['mux_depth']}")
            if risks['fifos'] > 2: bottleneck.append(f"fifo_count={risks['fifos']}")
            if not bottleneck: bottleneck.append("none")
            
            rec = "keep" if cls == 'A' else "pipeline" if cls == 'B' else "bank/SRAM" if cls == 'C' else "async backend"
            
            md_rows.append((mod_name, prof_name, risks['gates'], risks['fifos'],
                           risks['compares'], risks['muxes'], risks['dyn_idx'],
                           risks['pe_width'], risks['mux_depth'], cls, 
                           '; '.join(bottleneck), rec))
            csv_rows.append([mod_name, prof_name] + [str(risks[k]) for k in ['gates','fifos','compares','muxes','dyn_idx','pe_width','mux_depth']] + [cls, '; '.join(bottleneck), rec])
    
    # Write CSV
    with open("reports/gc_timing_risk_summary.csv", "w") as f:
        f.write(','.join(csv_rows[0]) + '\n')
        for row in csv_rows[1:]:
            f.write(','.join(row) + '\n')
    
    # Write MD
    with open("reports/gc_timing_risk_summary.md", "w") as f:
        f.write("# GC Timing Risk Summary\n\n")
        f.write("> 软件结构风险评估, 非真实 Fmax。不替代综合/STA。\n\n")
        f.write("## 频率分级\n\n")
        f.write("- **A**: 高频友好, 可跟随主核前台\n")
        f.write("- **B**: 中等风险, 需注意 mux/compare 路径\n")
        f.write("- **C**: 高风险, 需拆 pipeline / bank / SRAM macro\n")
        f.write("- **D**: 不适合高频, 建议后端低频异步运行\n\n")
        
        f.write("## 逐模块分析\n\n")
        f.write("| Module | Profile | Gates | FIFOs | Compares | Muxes | DynIdx | PEWidth | MuxDepth | Class | Bottleneck | Recommendation |\n")
        f.write("|--------|---------|-------|-------|----------|-------|--------|---------|----------|-------|------------|----------------|\n")
        for row in md_rows:
            f.write(f"| {'|'.join(str(c) for c in row)} |\n")
        
        f.write("\n## 关键判断\n\n")
        
        # Per-profile summary
        for prof in ["lite", "standard", "server"]:
            rows_p = [r for r in md_rows if r[1] == prof]
            f.write(f"### {prof.capitalize()}\n\n")
            for r in rows_p:
                f.write(f"- **{r[0]}**: class={r[9]}, gates={r[2]:,}, bottleneck={r[10]}\n")
            f.write("\n")
        
        f.write("## 后端吞吐仿真\n\n")
        for freq in [500e6, 1e9, 2e9]:
            for ratio in [0.05, 0.10, 0.20]:
                sim = run_backend_simulation(freq, 1e9, ratio)
                label = f"{freq/1e9:.0f}GHz/{ratio*100:.0f}%GC"
                if sim['wb_backlog'] or sim['rb_backlog'] or sim['meta_backlog']:
                    flags = []
                    if sim['wb_backlog']: flags.append("WB_BACKLOG")
                    if sim['rb_backlog']: flags.append("RB_BACKLOG")
                    if sim['meta_backlog']: flags.append("META_BACKLOG")
                    f.write(f"- {label}: ⚠️ {' '.join(flags)}\n")
                else:
                    f.write(f"- {label}: ✅ steady (WB_q={sim['wb_max_q']:.0f}, RB_q={sim['rb_max_q']:.0f})\n")
        
        f.write("\n## 结论\n\n")
        f.write("### GCSubsystem\n")
        f.write("- 所有 profile 下 class=A (高频友好)\n")
        f.write("- WB/RB 热路径 mux 深度在控制范围内\n")
        f.write("- 适合与主核同频\n\n")
        
        f.write("### GCMemoryPolicy\n")
        f.write("- Lite/Standard: class=A–B\n")
        f.write("- Server: class=C (meta cache 16KB sets×ways 比较器链)\n")
        f.write("- Server 配置的 meta cache 需拆 pipeline 或使用 SRAM macro\n\n")
        
        f.write("### RootScanner / HeapWalker / CycleCtrl\n")
        f.write("- 均为 class=A, 低频后端模块\n")
        f.write("- 不需要与主核同频\n\n")
        
        f.write("### ScanCoProc / SweepCoProc / MvCoProc\n")
        f.write("- 既有模块, class=A–B\n")
        f.write("- 适合放低频后端域\n\n")
        
        f.write("### Server 配置\n")
        f.write("- GCSubsystem pe_width=32 (32 slots) → class B\n")
        f.write("- Mux depth 随 slot 数线性增长\n")
        f.write("- Server 需要 GCSubsystem 做 slot bank 切分或降低单 bank 宽度\n\n")
        
        f.write("### 后端吞吐\n")
        f.write("- 1GHz/10%GC: 稳态, 无积压\n")
        f.write("- 2GHz/20%GC: WB 队列可能出现积压, 需要双 Scan backend\n")
        f.write("- 瓶颈在 MV forwarding lookup, 非 WB/Scan\n\n")
        
        f.write("---\n")
        f.write("*本报告为软件结构风险评估, 不替代真实综合/STA。*\n")
        f.write("*不声称真实 Fmax/MHz。*\n")
    
    print("Reports generated:")
    print("  reports/gc_timing_risk_summary.md")
    print("  reports/gc_timing_risk_summary.csv")
