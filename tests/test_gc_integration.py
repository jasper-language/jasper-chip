# tests/test_gc_integration.py — GC 集成测试
from amaranth import *
from amaranth.sim import Simulator, Tick
from rtl.gc_root_scanner import GCRootScanner
from rtl.gc_scan_coproc import GCScanCoProc
from rtl.gc_cycle import GCCycleController

import sys

def test_root_to_scan():
    """RootScanner → ScanCoProc: root 经 scanner 进入 scan 协处理器"""
    class Harness(Elaboratable):
        def __init__(self):
            self.rs = GCRootScanner(fifo_depth=4)
            self.sc = GCScanCoProc(ncores=1, fifo_depth=4, consume_every=1)
        def elaborate(self, platform):
            m = Module()
            m.submodules.rs = rs = self.rs
            m.submodules.sc = sc = self.sc
            # 连接：root scanner 输出 → scan coproc core 0 输入
            m.d.comb += [
                sc.wb_valid[0].eq(rs.scan_valid),
                rs.scan_ready.eq(sc.wb_ready[0]),
                sc.wb_addr[0].eq(rs.scan_card),
                sc.wb_data[0].eq(rs.scan_obj),
            ]
            return m

    h = Harness(); sim = Simulator(h); sim.add_clock(1e-6)
    rs = h.rs; sc = h.sc
    roots_written = 0
    scan_events = 0

    def proc():
        nonlocal roots_written, scan_events
        # 写入 3 个根
        for ptr in [0x80001000, 0x80002000, 0x80003000]:
            yield rs.root_valid.eq(1); yield rs.root_ptr.eq(ptr)
            yield Tick(); yield rs.root_valid.eq(0); yield Tick()
            roots_written += 1
        # 启动根扫描
        yield rs.start.eq(1); yield Tick(); yield rs.start.eq(0)
        # 等待扫描完成
        for _ in range(50):
            sv = (yield sc.ev_count[0])
            if sv:
                scan_events = sv
            d = (yield rs.done)
            if d and scan_events >= 3:
                break
            yield Tick()
        print(f"  roots={roots_written}, scan_events={scan_events}")
        assert scan_events >= 3, f"Scan missed events: {scan_events}"
        print("  PASS")

    sim.add_sync_process(proc); sim.run()
    return True

def test_cycle_controller():
    """GCCycleController: 完整 GC 周期"""
    cc = GCCycleController()
    sim = Simulator(cc); sim.add_clock(1e-6)
    phases = [0]  # IDLE→ROOTS→HEAP→MARK→SWEEP→RELOC→DONE
    ph_names = ["IDLE","ROOTS","HEAP","MARK","SWEEP","RELOC","DONE"]
    
    def proc():
        yield cc.start_cycle.eq(1); yield Tick(); yield cc.start_cycle.eq(0)
        for cyc in range(40):
            ph = (yield cc.phase)
            if ph != phases[-1]:
                phases.append(ph)
                print(f"  phase: {ph_names[ph] if ph < 7 else '?'}")
            if ph == 1: yield cc.rs_done.eq(1)
            elif ph == 2: yield cc.hw_done.eq(1)
            elif ph == 3: yield cc.scan_done.eq(1)
            elif ph == 4: yield cc.sweep_done.eq(1)
            elif ph == 5: yield cc.mv_done.eq(1)
            elif ph == 6:
                ticks = (yield cc.cycle_ticks)
                print(f"  complete in {ticks} ticks")
                assert ph_names[ph] == "DONE"
                break
            yield Tick()
        assert phases[-1] == 6, f"Didn't reach DONE: {phases}"
        print("  PASS")

    sim.add_sync_process(proc); sim.run()
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("GC 集成测试")
    print("=" * 60)

    results = []
    print("\n[1] RootScanner → ScanCoProc")
    results.append(("root_to_scan", test_root_to_scan()))

    print("\n[2] Cycle Controller")
    results.append(("cycle_ctrl", test_cycle_controller()))

    print(f"\n{'='*60}")
    all_ok = all(r for _, r in results)
    for name, ok in results:
        print(f"  {name:20s}: {'PASS' if ok else 'FAIL'}")
    print(f"\n{'ALL PASS' if all_ok else 'SOME FAILED'}")
    sys.exit(0 if all_ok else 1)
