"""Low-resource execution closure for the reusable V memory engine."""

from amaranth.sim import Settle, Simulator, Tick

from rtl.rv12_core import normalize_extension_spec
from rtl.vmemory_unit import VMemoryUnit


def run_case(*, memory, vregs=None, fault_addr=None, **start):
    dut = VMemoryUnit()
    sim = Simulator(dut)
    sim.add_clock(1e-6)
    registers = [0] * 32
    for reg, value in (vregs or {}).items():
        registers[reg] = value
    result = {"trap": 0, "vl": None, "addresses": []}

    def process():
        for reg, value in enumerate(registers):
            yield dut.vregs[reg].eq(value)
        for name, value in start.items():
            yield getattr(dut, f"start_{name}").eq(value)
        yield dut.start.eq(1)
        yield Tick()
        yield dut.start.eq(0)
        seen_active = False
        pending_address = None
        for _ in range(512):
            active = yield dut.active
            seen_active |= bool(active)
            address = yield dut.dmem_addr
            valid = yield dut.dmem_valid
            if valid:
                result["addresses"].append(address)
                grant = pending_address == address
                if not grant:
                    word = int.from_bytes(
                        memory[address & ~3:(address & ~3) + 4], "little")
                    yield dut.dmem_rdata.eq(word)
                    pending_address = address
                yield dut.dmem_grant.eq(grant)
                yield dut.dmem_error.eq(grant and address == fault_addr)
            else:
                grant = False
                yield dut.dmem_grant.eq(0)
                yield dut.dmem_error.eq(0)
                pending_address = None
            yield Settle()
            write_valid = yield dut.write_valid
            write_reg = yield dut.write_reg
            write_byte = yield dut.write_byte
            write_data = yield dut.write_data
            is_store = valid and grant and (yield dut.dmem_we)
            store_data = yield dut.dmem_wdata
            result["trap"] += (yield dut.trap)
            if (yield dut.vl_write_valid):
                result["vl"] = yield dut.vl_write_value
            yield Tick()
            if grant:
                pending_address = None
            if write_valid:
                mask = 0xff << (write_byte * 8)
                registers[write_reg] = ((registers[write_reg] & ~mask) |
                                        (write_data << (write_byte * 8)))
                yield dut.vregs[write_reg].eq(registers[write_reg])
            if is_store:
                base = address & ~3
                memory[base:base + 4] = store_data.to_bytes(4, "little")
            if seen_active and not active:
                break
        result["vregs"] = tuple(registers)

    sim.add_process(process)
    sim.run()
    return result


def params(**overrides):
    values = dict(load=1, indexed=0, strided=0, fof=0, whole=0, mask=0,
                  vm=1, vma=0, vta=0, base=1, stride=0, vreg=1,
                  index_vreg=0, eew_bytes=1, index_bytes=1, fields=1,
                  field_stride=1, element=0, evl=4, tail_limit=4)
    values.update(overrides)
    return values


def packed(values):
    values = bytes(values)
    return int.from_bytes(values + b"\x00" * (16 - len(values)),
                          "little")


def test_vmemory_addressing_writeback_store_tail_mask_and_fof():
    source = bytearray((index * 3 + 1) & 0xff for index in range(128))

    unit = run_case(memory=bytearray(source), **params())
    assert unit["vregs"][1] == packed(source[1:5])

    strided = run_case(memory=bytearray(source),
                       **params(strided=1, stride=2, vreg=2))
    assert strided["vregs"][2] == packed(source[index]
                                         for index in (1, 3, 5, 7))

    indexes = packed((0, 2, 5, 7))
    indexed = run_case(memory=bytearray(source), vregs={3: indexes},
                       **params(indexed=1, index_vreg=3, vreg=4))
    assert indexed["vregs"][4] == packed(source[index]
                                         for index in (1, 3, 6, 8))

    segmented = run_case(memory=bytearray(source),
                         **params(vreg=6, fields=2, field_stride=1))
    assert segmented["vregs"][6] == packed(source[index]
                                           for index in (1, 3, 5, 7))
    assert segmented["vregs"][7] == packed(source[index]
                                           for index in (2, 4, 6, 8))

    whole = run_case(memory=bytearray(source),
                     **params(whole=1, vreg=8, evl=16, tail_limit=16))
    assert whole["vregs"][8] == int.from_bytes(source[1:17], "little")

    masked = run_case(memory=bytearray(source), vregs={0: 0b0101},
                      **params(vm=0, vma=1, vreg=10))
    assert masked["vregs"][10] == packed((source[1], 0xff, source[3], 0xff))

    stored_memory = bytearray(source)
    stored = run_case(memory=stored_memory, vregs={11: packed((9, 8, 7, 6))},
                      **params(load=0, base=64, vreg=11))
    assert stored_memory[64:68] == bytes((9, 8, 7, 6))
    assert stored["trap"] == 0

    fof = run_case(memory=bytearray(source), fault_addr=3,
                   **params(fof=1, vreg=12))
    assert fof["vregs"][12] == packed(source[1:3])
    assert fof["vl"] == 2
    assert fof["trap"] == 0

    precise = run_case(memory=bytearray(source), fault_addr=1,
                       **params(vreg=13))
    assert precise["trap"] == 1


def test_vmemory_explicit_wildcard_and_disabled_extension_configs():
    assert "V" in normalize_extension_spec("RV32I+GC+V")
    assert "V" in normalize_extension_spec("RV32I+GC+*")
    assert "V" not in normalize_extension_spec("RV32I+GC")
