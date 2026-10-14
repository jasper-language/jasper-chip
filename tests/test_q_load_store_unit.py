from amaranth.sim import Settle, Simulator, Tick

from rtl.q_load_store_unit import QLoadStoreUnit


def enc_flq(rd, rs1, imm):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (0b100 << 12) | (rd << 7) | 0x07


def enc_fsq(rs2, rs1, imm):
    uimm = imm & 0xFFF
    return (
        ((uimm >> 5) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (0b100 << 12)
        | ((uimm & 0x1F) << 7)
        | 0x27
    )


def run_case(process):
    dut = QLoadStoreUnit(xlen=32)
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    def wrapper():
        yield from process(dut)
    sim.add_process(wrapper)
    sim.run()


def test_flq_four_beats_commit_only_after_complete_transfer():
    words = [0x01234567, 0x89ABCDEF, 0x0BADCAFE, 0xFEDCBA98]

    def process(dut):
        yield dut.enable.eq(1)
        yield dut.insn.eq(enc_flq(9, 3, -16))
        yield dut.rs1_value.eq(0x110)
        yield dut.request_valid.eq(1)
        yield Tick()
        yield Settle()
        yield dut.request_valid.eq(0)
        for beat, word in enumerate(words):
            assert (yield dut.busy)
            assert (yield dut.mem_valid)
            assert (yield dut.mem_write) == 0
            assert (yield dut.mem_addr) == 0x100 + beat * 4
            assert (yield dut.fpr_write_valid) == 0
            yield dut.mem_rdata.eq(word)
            yield dut.mem_ready.eq(1)
            yield Tick()
            yield Settle()
            yield dut.mem_ready.eq(0)
        assert (yield dut.done)
        assert (yield dut.trap) == 0
        assert (yield dut.fpr_write_valid)
        assert (yield dut.fpr_write_addr) == 9
        assert (yield dut.fpr_write_data) == sum(word << (32 * i) for i, word in enumerate(words))

    run_case(process)


def test_fsq_preserves_all_128_payload_bits_and_backpressure():
    payload = 0x7FFF800000000001_0123456789ABCDEF

    def process(dut):
        yield dut.enable.eq(1)
        yield dut.insn.eq(enc_fsq(7, 2, 12))
        yield dut.rs1_value.eq(0x200)
        yield dut.fs2_value.eq(payload)
        yield dut.request_valid.eq(1)
        yield Tick()
        yield Settle()
        yield dut.request_valid.eq(0)
        for beat in range(4):
            assert (yield dut.mem_addr) == 0x20C + beat * 4
            assert (yield dut.mem_write)
            assert (yield dut.mem_wdata) == ((payload >> (32 * beat)) & 0xFFFFFFFF)
            yield Tick()
            yield Settle()
            assert (yield dut.mem_addr) == 0x20C + beat * 4
            yield dut.mem_ready.eq(1)
            yield Tick()
            yield Settle()
            yield dut.mem_ready.eq(0)
        assert (yield dut.done)
        assert (yield dut.trap) == 0
        assert (yield dut.fpr_write_valid) == 0

    run_case(process)


def test_flq_fault_discards_partial_register_result():
    def process(dut):
        yield dut.enable.eq(1)
        yield dut.insn.eq(enc_flq(4, 1, 0))
        yield dut.rs1_value.eq(0x80)
        yield dut.request_valid.eq(1)
        yield Tick()
        yield Settle()
        yield dut.request_valid.eq(0)
        yield dut.mem_rdata.eq(0xDEADBEEF)
        yield dut.mem_ready.eq(1)
        yield Tick()
        yield Settle()
        yield dut.mem_fault.eq(1)
        yield Tick()
        yield Settle()
        assert (yield dut.done)
        assert (yield dut.trap)
        assert (yield dut.busy) == 0
        assert (yield dut.fpr_write_valid) == 0

    run_case(process)


def test_disabled_and_word_misaligned_q_accesses_trap_without_bus_request():
    def process(dut):
        yield dut.insn.eq(enc_flq(1, 1, 0))
        yield dut.rs1_value.eq(0x100)
        yield dut.request_valid.eq(1)
        yield Tick()
        yield Settle()
        assert (yield dut.done)
        assert (yield dut.trap)
        assert (yield dut.mem_valid) == 0
        yield dut.request_valid.eq(0)
        yield Tick()
        yield Settle()
        yield dut.enable.eq(1)
        yield dut.rs1_value.eq(0x102)
        yield dut.request_valid.eq(1)
        yield Tick()
        yield Settle()
        assert (yield dut.done)
        assert (yield dut.trap)
        assert (yield dut.mem_valid) == 0

    run_case(process)
