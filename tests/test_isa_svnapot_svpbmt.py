from amaranth import Elaboratable, Module
from amaranth.sim import Settle, Simulator, Tick

from rtl.isa import OP_IMM, SYSTEM, enc_i
from rtl.isa_svnapot import Svnapot
from rtl.isa_svpbmt import Svpbmt
from rtl.mem import SimpleDMem, SimpleIMem
from rtl.rv12_core import RV12Core, normalize_extension_spec


def make_pte(ppn, *, napot=False, pbmt=0):
    return (int(napot) << 63) | (pbmt << 61) | (ppn << 10) | 0b111


def sample(dut, *, pte, vpn=0, leaf=1, level=0, pbmte=1):
    result = {}

    def process():
        yield dut.pte.eq(pte)
        yield dut.leaf.eq(leaf)
        if hasattr(dut, "vpn"):
            yield dut.vpn.eq(vpn)
        if hasattr(dut, "level"):
            yield dut.level.eq(level)
        if hasattr(dut, "pbmte"):
            yield dut.pbmte.eq(pbmte)
        yield Settle()
        for name in (
            "napot_valid", "page_fault", "translated_ppn", "region_base",
            "page_size", "pbmt", "pma", "noncacheable", "io",
        ):
            if hasattr(dut, name):
                result[name] = yield getattr(dut, name)

    sim = Simulator(dut)
    sim.add_process(process)
    sim.run()
    return result


def test_svnapot_64k_translation_and_reserved_encodings():
    ppn = 0x12348
    result = sample(Svnapot(64), pte=make_pte(ppn, napot=True), vpn=0x35)
    assert result == {
        "napot_valid": 1,
        "page_fault": 0,
        "translated_ppn": 0x12345,
        "region_base": 0x12340000,
        "page_size": 65536,
    }
    assert sample(Svnapot(64), pte=make_pte(0x12347, napot=True))["page_fault"] == 1
    assert sample(Svnapot(64), pte=make_pte(ppn, napot=True), leaf=0)["page_fault"] == 1
    assert sample(Svnapot(64), pte=make_pte(ppn, napot=True), level=1)["page_fault"] == 1
    normal = sample(Svnapot(64), pte=make_pte(0x12347), vpn=0x35)
    assert normal["translated_ppn"] == 0x12347
    assert normal["page_size"] == 4096


def test_svpbmt_leaf_classification_and_faults():
    assert sample(Svpbmt(64), pte=make_pte(1, pbmt=0))["pma"] == 1
    assert sample(Svpbmt(64), pte=make_pte(1, pbmt=1))["noncacheable"] == 1
    assert sample(Svpbmt(64), pte=make_pte(1, pbmt=2))["io"] == 1
    assert sample(Svpbmt(64), pte=make_pte(1, pbmt=3))["page_fault"] == 1
    assert sample(Svpbmt(64), pte=make_pte(1, pbmt=1), leaf=0)["page_fault"] == 1
    disabled = sample(Svpbmt(64), pte=make_pte(1, pbmt=1), pbmte=0)
    assert disabled["page_fault"] == 1
    assert disabled["noncacheable"] == 0


def test_svnapot_svpbmt_extension_parsing_and_star_coverage():
    explicit = normalize_extension_spec("RV64I+GC+SVNAPOT+SVPBMT")
    star = normalize_extension_spec("RV32I+GC+*")
    disabled = normalize_extension_spec("RV64I+GC")
    assert {"SVNAPOT", "SVPBMT"} <= explicit
    assert {"SVNAPOT", "SVPBMT"} <= star
    assert not ({"SVNAPOT", "SVPBMT"} & disabled)
    assert RV12Core(xlen=64, extensions="RV64I+GC+SVNAPOT+SVPBMT").enable_svnapot
    assert RV12Core(xlen=64, extensions="RV64I+GC+*").enable_svnapot
    assert RV12Core(xlen=64, extensions="RV64I+GC+*").enable_svpbmt
    assert not RV12Core(xlen=32, extensions="RV32I+GC+*").enable_svnapot
    assert not RV12Core(xlen=32, extensions="RV32I+GC+*").enable_svpbmt
    assert not RV12Core(xlen=64, extensions="RV64I+GC").enable_svnapot


def sample_svnapot_core(*, xlen, extensions, pte, vpn=0, leaf=1, level=0):
    dut = RV12Core(xlen=xlen, extensions=extensions)
    result = {}

    def process():
        yield dut.dbg_pte.eq(pte)
        yield dut.dbg_vpn.eq(vpn)
        yield dut.dbg_pte_leaf.eq(leaf)
        yield dut.dbg_pte_level.eq(level)
        yield Settle()
        result.update(
            translated_ppn=(yield dut.dbg_pte_translated_ppn),
            region_base=(yield dut.dbg_pte_region_base),
            page_size=(yield dut.dbg_pte_page_size),
            napot_valid=(yield dut.dbg_pte_napot_valid),
            page_fault=(yield dut.dbg_pte_page_fault),
        )

    sim = Simulator(dut)
    sim.add_process(process)
    sim.run()
    return result


def test_svnapot_core_explicit_star_and_rv32_non_applicability():
    pte = make_pte(0x12348, napot=True)
    expected = {
        "translated_ppn": 0x12345,
        "region_base": 0x12340000,
        "page_size": 65536,
        "napot_valid": 1,
        "page_fault": 0,
    }
    assert sample_svnapot_core(
        xlen=64, extensions="RV64I+GC+SVNAPOT", pte=pte, vpn=0x35) == expected
    assert sample_svnapot_core(
        xlen=64, extensions="RV64I+GC+*", pte=pte, vpn=0x35) == expected

    rv32 = sample_svnapot_core(
        xlen=32, extensions="RV32I+GC+*", pte=pte, vpn=0x35)
    assert rv32["napot_valid"] == 0
    assert rv32["page_size"] == 4096
    assert rv32["page_fault"] == 1


class _SvpbmtCoreBench(Elaboratable):
    def __init__(self, *, xlen, extensions, write_pbmte):
        program = [enc_i(OP_IMM, 1, 0, 0, 1)]
        if write_pbmte:
            program += [enc_i(OP_IMM, 1, 0b001, 1, 62),
                        (0x30A << 20) | (1 << 15) | (0b001 << 12) | SYSTEM]
        program += [enc_i(OP_IMM, 20, 0, 0, 0x55), 0x0000006F]
        program += [enc_i(OP_IMM, 0, 0, 0, 0)] * (32 - len(program))
        self.core = RV12Core(xlen=xlen, extensions=extensions)
        self.imem = SimpleIMem(words=len(program), init=program)
        self.dmem = SimpleDMem(words=8, init=[0] * 8)

    def elaborate(self, platform):
        m = Module()
        m.submodules.core = c = self.core
        m.submodules.imem = im = self.imem
        m.submodules.dmem = dm = self.dmem
        m.d.comb += [
            im.addr.eq(c.imem_addr), c.imem_rdata.eq(im.rdata),
            dm.req_valid.eq(c.dmem_valid), dm.req_we.eq(c.dmem_we),
            dm.req_addr.eq(c.dmem_addr), dm.req_wdata.eq(c.dmem_wdata),
            c.dmem_rdata.eq(dm.rsp_rdata), c.gc_enq_ready.eq(1),
            c.gc_rsp_valid.eq(0), c.gc_rsp_tag.eq(0), c.gc_rsp_rd.eq(0),
            c.gc_rsp_data.eq(0), c.wb_enq_ready.eq(1), c.mv_cmd_ready.eq(1),
            c.mv_rsp_valid.eq(0), c.mv_rsp_tag.eq(0), c.mv_rsp_rd.eq(0),
            c.mv_rsp_data.eq(0),
            c.dbg_pte.eq(make_pte(1, pbmt=1)), c.dbg_pte_leaf.eq(1),
        ]
        return m


def run_svpbmt_core(*, xlen, extensions, write_pbmte):
    dut = _SvpbmtCoreBench(
        xlen=xlen, extensions=extensions, write_pbmte=write_pbmte)
    result = {}
    sim = Simulator(dut)
    sim.add_clock(1e-6)

    def process():
        for _ in range(240):
            yield Tick()
        result.update(
            pbmte=(yield dut.core.dbg_pte_pbmte),
            noncacheable=(yield dut.core.dbg_pte_noncacheable),
            io=(yield dut.core.dbg_pte_io),
            page_fault=(yield dut.core.dbg_pte_page_fault),
        )

    sim.add_process(process)
    sim.run()
    return result


def test_svpbmt_core_menvcfg_explicit_star_and_rv32_non_applicability():
    enabled = {"pbmte": 1, "noncacheable": 1, "io": 0, "page_fault": 0}
    assert run_svpbmt_core(
        xlen=64, extensions="RV64I+GC+SVPBMT", write_pbmte=True) == enabled
    assert run_svpbmt_core(
        xlen=64, extensions="RV64I+GC+*", write_pbmte=True) == enabled
    assert run_svpbmt_core(
        xlen=64, extensions="RV64I+GC+SVPBMT", write_pbmte=False) == {
            "pbmte": 0, "noncacheable": 0, "io": 0, "page_fault": 1}
    assert run_svpbmt_core(
        xlen=32, extensions="RV32I+GC+*", write_pbmte=False) == {
            "pbmte": 0, "noncacheable": 0, "io": 0, "page_fault": 1}
