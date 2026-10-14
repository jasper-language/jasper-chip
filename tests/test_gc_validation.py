# tests/test_gc_validation.py
# 全面 GC 验证套件：gc_fire / WB / RB / stall / 压力
from amaranth import *
from amaranth.sim import Simulator, Tick
from rtl.rv12_core import RV12Core
from rtl.mem import SimpleIMem, SimpleDMem
from rtl.isa import *

NOP = lambda: enc_i(OP_IMM, 0, 0, 0, 0)
DONE = lambda: enc_i(OP_IMM, 31, 0, 0, 13)

class GcValidation(Elaboratable):
    def __init__(self, prog, profile="standard", rb_mode=1):
        self.results = {}
        c = RV12Core.with_gc_profile(profile)
        self.core = c
        self.imem = SimpleIMem(words=4096, init=prog + [NOP()]*(4096-len(prog)))
        self.dmem = SimpleDMem(words=256)
    def elaborate(self, platform):
        m = Module(); c=self.core; im=self.imem; dm=self.dmem
        m.submodules.core=c; m.submodules.imem=im; m.submodules.dmem=dm
        m.d.comb += [
            im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
            c.dmem_grant.eq(c.dmem_valid),
            dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata),
            c.gc_enq_ready.eq(1), c.gc_rsp_valid.eq(0),
            c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0), c.gc_rsp_data.eq(0),
            c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0), c.mv_rsp_data.eq(0),
        ]
        return m

def run_test(prog, name, profile="standard", rb_mode=1, maxc=2000):
    """Run a program and measure cycles + check gc_fire + stall."""
    v = GcValidation(prog, profile=profile, rb_mode=rb_mode)
    s = Simulator(v); s.add_clock(1e-6)
    c = v.core
    r = dict(fire_count=0, stall_count=0, max_stall_run=0, done_cyc=maxc, 
             cur_stall=0, wb_count=0, gc_wait_ever=0)

    def proc():
        for cyc in range(maxc):
            stall = (yield c.dbg_stall)
            gc_f = (yield c.dbg_gc_fire)
            gc_w = (yield c.dbg_gc_waiting) if hasattr(c,'dbg_gc_waiting') else 0
            if gc_f: r['fire_count'] += 1
            if stall:
                r['stall_count'] += 1
                r['cur_stall'] += 1
            else:
                r['max_stall_run'] = max(r['max_stall_run'], r['cur_stall'])
                r['cur_stall'] = 0
            if gc_w: r['gc_wait_ever'] = 1
            yield c.dbg_reg_addr.eq(31)
            yield Tick()
            if (yield c.dbg_reg_rdata) == 13:
                r['done_cyc'] = cyc
                for _ in range(8): yield Tick()
                return
    s.add_sync_process(proc); s.run()
    return r

def test_group(profile):
    print(f"\n{'='*65}")
    print(f"Profile: {profile.upper()}")
    print(f"{'='*65}")

    p = RV12Core.with_gc_profile(profile)
    print(f"  Config: slots={p.gc_slots} cache={p.rb_cache_ways} "
          f"rb={p.rb_slots} wb={p.wb_depth} mv={p.mv_depth}")
    
    all_ok = True

    # T1: gc_fire
    prog = [enc_gc_new(1,0,0), DONE()]
    r = run_test(prog, "gc_fire", profile)
    ok = r['fire_count'] >= 1
    print(f"  [T1] gc_fire: {'PASS' if ok else 'FAIL'} (fired {r['fire_count']}x)")
    all_ok &= ok

    # T2: WB zero cost (heap store CPI == non-heap store CPI)
    prog0 = [enc_i(OP_IMM,1,0,0,0)]
    for i in range(200):
        prog0 += [enc_s(STORE,2,1,0,i*4), enc_i(OP_IMM,1,0,1,4)]
    prog0 += [DONE()]; r0 = run_test(prog0,"store_base",profile)
    cpi0 = r0['done_cyc'] / 402

    prog1 = [enc_i(OP_IMM,1,0,0,0x80000000)]
    for i in range(200):
        prog1 += [enc_s(STORE,2,1,0,i*4), enc_i(OP_IMM,1,0,1,4)]
    prog1 += [DONE()]; r1 = run_test(prog1,"store_wb",profile)
    cpi1 = r1['done_cyc'] / 402
    wb_ok = abs(cpi1 - cpi0) < 0.1
    print(f"  [T2] WB zero cost: {'PASS' if wb_ok else 'FAIL'} "
          f"(non-heap CPI={cpi0:.3f}, heap CPI={cpi1:.3f}, diff={cpi1-cpi0:.4f})")
    all_ok &= wb_ok

    # T3: No GC stall
    prog = []
    for i in range(5):
        prog += [enc_gc_new(1,0,0), enc_i(OP_IMM,2,0,1,1)]
    prog += [DONE()]
    r = run_test(prog,"gc_nostall",profile)
    stall_ok = r['stall_count'] == 0
    print(f"  [T3] No GC stall: {'PASS' if stall_ok else 'FAIL'} "
          f"(stall={r['stall_count']} cyc, max_run={r['max_stall_run']})")
    all_ok &= stall_ok

    # T4: RB non-blocking (with MV response injection)
    for lat in [2, 5]:
        class RbTest(Elaboratable):
            def __init__(self):
                self.done_at = 999
                self.core = RV12Core.with_gc_profile(profile, rb_mode=0)
                self.imem = SimpleIMem(words=1024, init=[enc_i(LOAD,1,2,0,0x80000000),DONE()]+[NOP()]*1020)
                self.dmem = SimpleDMem(words=64)
            def elaborate(self, platform):
                m = Module(); c=self.core; im=self.imem; dm=self.dmem
                m.submodules.core=c; m.submodules.imem=im; m.submodules.dmem=dm
                m.d.comb += [
                    im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
                    c.dmem_grant.eq(c.dmem_valid),
                    dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
                    dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
                    c.dmem_rdata.eq(dm.rsp_rdata),
                    c.gc_enq_ready.eq(1),
                    c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
                ]
                return m
        rt = RbTest()
        s2 = Simulator(rt); s2.add_clock(1e-6)
        c2 = rt.core
        def proc2(ll=lat):
            for cyc in range(100):
                mv_v = (yield c2.mv_cmd_valid)
                if mv_v:
                    tag = (yield c2.mv_cmd_tag)
                    rd = (yield c2.mv_cmd_rd)
                    for w in range(ll): yield Tick()
                    yield c2.mv_rsp_valid.eq(1)
                    yield c2.mv_rsp_tag.eq(tag); yield c2.mv_rsp_rd.eq(rd)
                    yield c2.mv_rsp_data.eq(42)
                    yield Tick()
                    yield c2.mv_rsp_valid.eq(0)
                yield c2.dbg_reg_addr.eq(31); yield Tick()
                if (yield c2.dbg_reg_rdata) == 13:
                    rt.done_at = cyc; return
        s2.add_sync_process(proc2); s2.run()
        rb_ok = rt.done_at < 30
        print(f"  [T4] RB non-blocking (lat={lat}): {'PASS' if rb_ok else 'FAIL'} "
              f"(done@cyc {rt.done_at})")
        all_ok &= rb_ok

    # T5: 200× heap store stress
    r = run_test(prog1,"stress_200wb",profile)
    ok = r['done_cyc'] < 500
    print(f"  [T5] 200× heap store stress: {'PASS' if ok else 'FAIL'} "
          f"({r['done_cyc']} cyc)")
    all_ok &= ok

    print(f"  → {'✓ ALL PASS' if all_ok else '✗ SOME FAILED'}")
    return all_ok

if __name__ == "__main__":
    results = {}
    for prof in ["lite", "standard", "server"]:
        results[prof] = test_group(prof)
    
    print(f"\n{'='*65}")
    print("Summary")
    print(f"{'='*65}")
    for prof, ok in results.items():
        print(f"  {prof:10s}: {'ALL PASS' if ok else 'FAILED'}")
    
    import sys
    sys.exit(0 if all(results.values()) else 1)
