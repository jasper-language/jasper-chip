"""Reusable low-resource RV12 V integration simulator."""

from amaranth import Array, Elaboratable, Module, Signal
from amaranth.sim import Simulator, Tick

from rtl.rv12_core import RV12Core
from rtl.vfadd_unit import VFAddUnit
from rtl.vfcvt_float_to_int_unit import VFFloatToIntRTZUnit
from rtl.vfcvt_unit import VFIntToFloatUnit
from rtl.vfdiv_unit import VFDivUnit
from rtl.vffma_unit import VFFMAUnit
from rtl.vfncvt_float_unit import VFNarrowFloatUnit
from rtl.vfsqrt_unit import VFSqrtUnit


_V_UNIT_CLASSES = {
    "vfadd": VFAddUnit,
    "vfcvt": VFIntToFloatUnit,
    "vfcvt_ftoi": VFFloatToIntRTZUnit,
    "vfdiv": VFDivUnit,
    "vffma": VFFMAUnit,
    "vfncvt": VFNarrowFloatUnit,
    "vfsqrt": VFSqrtUnit,
}


def _empty_elaborate(self, platform):
    return Module()


class _VBatchHarness(Elaboratable):
    def __init__(self, extensions, words=256):
        self.core = RV12Core(core_id=0, xlen=32, extensions=extensions)
        self.imem = Array(Signal(32, name=f"batch_imem_{index}")
                          for index in range(words))
        self.dmem = Array(Signal(32, name=f"batch_dmem_{index}")
                          for index in range(words))
        self.fault_enable = Signal()
        self.fault_addr = Signal(32)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.d.comb += [
            c.imem_rdata.eq(self.imem[c.imem_addr[2:10]]),
            c.dmem_rdata.eq(self.dmem[c.dmem_addr[2:10]]),
            c.dmem_error.eq(self.fault_enable & c.dmem_valid &
                            (c.dmem_addr == self.fault_addr)),
            c.gc_enq_ready.eq(1), c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0),
            c.gc_rsp_rd.eq(0), c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1),
            c.mv_cmd_ready.eq(1), c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0),
            c.mv_rsp_rd.eq(0), c.mv_rsp_data.eq(0),
        ]
        return m


class _VBatchSimulator:
    def __init__(self, extensions, v_units):
        disabled = (() if v_units is None else
                    tuple(name for name in _V_UNIT_CLASSES
                          if name not in v_units))
        originals = {name: _V_UNIT_CLASSES[name].elaborate
                     for name in disabled}
        for name in disabled:
            _V_UNIT_CLASSES[name].elaborate = _empty_elaborate
        try:
            self.dut = _VBatchHarness(extensions)
            self.sim = Simulator(self.dut)
        finally:
            for name, elaborate in originals.items():
                _V_UNIT_CLASSES[name].elaborate = elaborate
        self.sim.add_clock(1e-6)
        self.case = None
        self.result = None
        self.sim.add_process(self._process)

    def _process(self):
        case = self.case
        result = self.result
        for index, signal in enumerate(self.dut.imem):
            value = case["imem"][index] if index < len(case["imem"]) else 0
            yield signal.eq(value)
        for index, signal in enumerate(self.dut.dmem):
            value = case["dmem"][index] if index < len(case["dmem"]) else 0
            yield signal.eq(value)
        yield self.dut.fault_enable.eq(case["fault_addr"] is not None)
        yield self.dut.fault_addr.eq(case["fault_addr"] or 0)

        traps = 0
        trace = []
        control_trace = []
        for cycle in range(case["cycles"]):
            traps += (yield self.dut.core.trap)
            valid = yield self.dut.core.dmem_valid
            write = yield self.dut.core.dmem_we
            address = yield self.dut.core.dmem_addr
            write_data = yield self.dut.core.dmem_wdata
            if case["trace_dmem"] and valid:
                trace.append((write, address))
            if (case["control_from"] is not None and
                    cycle >= case["control_from"]):
                control_trace.append(((yield self.dut.core.pc_dbg),
                                      (yield self.dut.core.dbg_stall_front),
                                      (yield self.dut.core.dbg_is_valid)))
            yield Tick()
            if valid and write:
                yield self.dut.dmem[(address >> 2) & 0xFF].eq(write_data)

        for reg in case["vregs"]:
            yield self.dut.core.dbg_vreg_addr.eq(reg)
            yield Tick()
            result[reg] = yield self.dut.core.dbg_vreg_rdata
        for reg in case["xregs"]:
            yield self.dut.core.dbg_reg_addr.eq(reg)
            yield Tick()
            result[f"x{reg}"] = yield self.dut.core.dbg_reg_rdata
        result["flags"] = yield self.dut.core.dbg_fflags
        result["traps"] = traps
        result["trace"] = trace
        result["control_trace"] = control_trace

    def run(self, **case):
        self.case = case
        self.result = {}
        self.sim.reset()
        self.sim.run()
        return self.result


_SIMULATORS = {}


def run_v_program(extensions, imem, dmem, cycles, *, vregs=(), xregs=(),
                  fault_addr=None, trace_dmem=False, control_from=None,
                  v_units=None):
    """Run one program while reusing the compiled core for its ISA config."""
    unit_key = None if v_units is None else frozenset(v_units)
    cache_key = (extensions, unit_key)
    simulator = _SIMULATORS.get(cache_key)
    if simulator is None:
        simulator = _SIMULATORS[cache_key] = _VBatchSimulator(
            extensions, unit_key)
    return simulator.run(
        imem=list(imem), dmem=list(dmem), cycles=cycles,
        vregs=tuple(vregs), xregs=tuple(xregs), fault_addr=fault_addr,
        trace_dmem=trace_dmem, control_from=control_from,
    )
