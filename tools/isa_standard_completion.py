#!/usr/bin/env python3
"""Generate the Jasper CPU standard ISA completion ledger.

The ledger is intentionally conservative: an instruction is CLOSED only when
there is an executable runtime closure in the local tests for the relevant
RV32I+GC / RV32I+GC+* path. PARTIAL means decode/parser/parity or stub coverage
exists but full architectural execution is not claimed. GAP means no complete
local executable closure is claimed yet.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
CSV_PATH = REPORTS / "isa_standard_completion.csv"
MD_PATH = REPORTS / "isa_standard_completion.md"

CLOSED = "CLOSED"
PARTIAL = "PARTIAL"
GAP = "GAP"
NON_INSTRUCTION = "NON_INSTRUCTION"

ROWS = []

def add(ext: str, instruction: str, status: str, closure: str, evidence: str) -> None:
    ROWS.append({
        "extension": ext,
        "instruction": instruction,
        "status": status,
        "closure": closure,
        "evidence": evidence,
    })

# RV32I base integer instruction set.
for insn in ["LUI", "AUIPC", "JAL", "JALR"]:
    add("RV32I", insn, CLOSED, "runtime", "tests/test_extension_star_runtime.py::test_rv32i_standard_*")
for insn in ["BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU"]:
    add("RV32I", insn, CLOSED, "runtime", "test_rv32i_standard_branch_conditions_execute_taken_and_not_taken")
for insn in ["LB", "LH", "LW", "LBU", "LHU"]:
    add("RV32I", insn, CLOSED, "runtime", "test_rv32i_standard_load_signed_widths_and_unsigned_byte_execute / test_rv32i_standard_lhu_zero_extends_low_and_high_halfwords")
for insn in ["SB", "SH", "SW"]:
    add("RV32I", insn, CLOSED, "runtime", "test_rv32i_standard_store_widths_execute_byte_halfword_and_word_lanes")
for insn in ["ADDI", "SLTI", "SLTIU", "XORI", "ORI", "ANDI", "SLLI", "SRLI", "SRAI"]:
    add("RV32I", insn, CLOSED, "runtime", "RV32I immediate ALU standard tests")
for insn in ["ADD", "SUB", "SLL", "SLT", "SLTU", "XOR", "SRL", "SRA", "OR", "AND"]:
    add("RV32I", insn, CLOSED, "runtime", "RV32I register ALU standard tests")
add("RV32I", "FENCE", CLOSED, "runtime", "test_rv32i_standard_fence_executes_as_ordering_barrier")
add("RV32I", "ECALL", CLOSED, "runtime", "test_rv32i_standard_ecall_and_ebreak_raise_trap")
add("RV32I", "EBREAK", CLOSED, "runtime", "test_rv32i_standard_ecall_and_ebreak_raise_trap")
add("RV32I", "x0 invariant", CLOSED, "runtime", "test_rv32i_standard_x0_remains_zero_across_writeback_paths")

# RV32M standard multiplication/division extension.
for insn in ["MUL", "MULH", "MULHSU", "MULHU", "DIV", "DIVU", "REM", "REMU"]:
    add("M", insn, CLOSED, "runtime", "test_rv32m_standard_all_multiply_divide_remainder_forms_execute")

# RV32A standard atomic extension.
for insn in ["LR.W", "SC.W", "AMOSWAP.W", "AMOADD.W", "AMOXOR.W", "AMOAND.W", "AMOOR.W", "AMOMIN.W", "AMOMAX.W", "AMOMINU.W", "AMOMAXU.W"]:
    add("A", insn, CLOSED, "runtime", "test_rv32a_standard_all_lr_sc_and_amo_word_forms_execute_with_aq_rl")

# RV32F standard single-precision floating point extension.
for insn in [
    "FLW", "FSW", "FMADD.S", "FMSUB.S", "FNMSUB.S", "FNMADD.S", "FADD.S", "FSUB.S",
    "FMUL.S", "FDIV.S", "FSQRT.S", "FSGNJ.S", "FSGNJN.S", "FSGNJX.S", "FMIN.S", "FMAX.S",
    "FCVT.W.S", "FCVT.WU.S", "FMV.X.W", "FEQ.S", "FLT.S", "FLE.S", "FCLASS.S",
    "FCVT.S.W", "FCVT.S.WU", "FMV.W.X",
]:
    closed_f = {"FLW", "FSW", "FMADD.S", "FMSUB.S", "FNMSUB.S", "FNMADD.S", "FADD.S", "FSUB.S", "FMUL.S", "FDIV.S", "FSQRT.S", "FSGNJ.S", "FSGNJN.S", "FSGNJX.S", "FMIN.S", "FMAX.S", "FCVT.W.S", "FCVT.WU.S", "FMV.X.W", "FMV.W.X", "FCLASS.S", "FEQ.S", "FLT.S", "FLE.S", "FCVT.S.W", "FCVT.S.WU"}
    add(
        "F",
        insn,
        CLOSED if insn in closed_f else PARTIAL if insn in {"FLW", "FSW"} else GAP,
        "runtime" if insn in closed_f else "execute-pending",
        "test_rv32f_standard_fsgnj_sign_injection_execute_on_rv32_f_and_star"
        if insn in {"FSGNJ.S", "FSGNJN.S", "FSGNJX.S"}
        else "test_rv32f_standard_fused_madd_family_execute_on_rv32_f_and_star"
        if insn in {"FMADD.S", "FMSUB.S", "FNMSUB.S", "FNMADD.S"}
        else "test_rv32f_standard_fmv_bit_moves_execute_on_rv32_f_and_star"
        if insn in {"FMV.X.W", "FMV.W.X"}
        else "test_rv32f_standard_fclass_execute_on_rv32_f_and_star"
        if insn == "FCLASS.S"
        else "test_rv32f_standard_compare_execute_on_rv32_f_and_star"
        if insn in {"FEQ.S", "FLT.S", "FLE.S"}
        else "test_rv32f_standard_min_max_execute_on_rv32_f_and_star"
        if insn in {"FMIN.S", "FMAX.S"}
        else "test_rv32f_standard_flw_fsw_execute_on_rv32_f_and_star"
        if insn in {"FLW", "FSW"}
        else "test_rv32f_standard_add_sub_execute_on_rv32_f_and_star"
        if insn in {"FADD.S", "FSUB.S"}
        else "test_rv32f_standard_mul_execute_on_rv32_f_and_star"
        if insn == "FMUL.S"
        else "test_rv32f_standard_div_execute_on_rv32_f_and_star"
        if insn == "FDIV.S"
        else "test_rv32f_standard_sqrt_execute_on_rv32_f_and_star"
        if insn == "FSQRT.S"
        else "test_rv32f_standard_fcvt_w_execute_on_rv32_f_and_star"
        if insn in {"FCVT.W.S", "FCVT.WU.S"}
        else "test_rv32f_standard_fcvt_s_execute_on_rv32_f_and_star"
        if insn in {"FCVT.S.W", "FCVT.S.WU"}
        else "Full FP arithmetic/compare/convert closure pending",
    )

# RV32D standard double-precision floating point extension.
for insn in [
    "FLD", "FSD", "FMADD.D", "FMSUB.D", "FNMSUB.D", "FNMADD.D", "FADD.D", "FSUB.D",
    "FMUL.D", "FDIV.D", "FSQRT.D", "FSGNJ.D", "FSGNJN.D", "FSGNJX.D", "FMIN.D", "FMAX.D",
    "FCVT.S.D", "FCVT.D.S", "FEQ.D", "FLT.D", "FLE.D", "FCLASS.D", "FCVT.W.D", "FCVT.WU.D",
    "FCVT.D.W", "FCVT.D.WU",
]:
    closed_d = {"FLD", "FSD", "FSGNJ.D", "FSGNJN.D", "FSGNJX.D", "FMIN.D", "FMAX.D", "FEQ.D", "FLT.D", "FLE.D", "FCLASS.D", "FCVT.S.D", "FCVT.D.S", "FCVT.W.D", "FCVT.WU.D", "FCVT.D.W", "FCVT.D.WU", "FMADD.D", "FMSUB.D", "FNMSUB.D", "FNMADD.D", "FADD.D", "FSUB.D", "FMUL.D", "FDIV.D", "FSQRT.D"}
    add(
        "D",
        insn,
        CLOSED if insn in closed_d else PARTIAL if insn in {"FLD", "FSD"} else GAP,
        "runtime" if insn in closed_d else "parser/runtime-partial" if insn in {"FLD", "FSD"} else "execute-pending",
        "test_rv32d_standard_fsgnj_sign_injection_execute_on_rv64_d_and_star"
        if insn in {"FSGNJ.D", "FSGNJN.D", "FSGNJX.D"}
        else "test_rv32d_standard_fused_madd_family_execute_on_rv64_d_and_star"
        if insn in {"FMADD.D", "FMSUB.D", "FNMSUB.D", "FNMADD.D"}
        else "test_rv32d_standard_min_max_execute_on_rv64_d_and_star"
        if insn in {"FMIN.D", "FMAX.D"}
        else "test_rv32d_standard_compare_execute_on_rv64_d_and_star"
        if insn in {"FEQ.D", "FLT.D", "FLE.D"}
        else "test_rv32d_standard_fclass_execute_on_rv64_d_and_star"
        if insn == "FCLASS.D"
        else "test_rv32d_standard_fcvt_d_from_word_execute_on_rv64_d_and_star"
        if insn in {"FCVT.D.W", "FCVT.D.WU"}
        else "test_rv32d_standard_fcvt_word_from_d_execute_on_rv64_d_and_star"
        if insn in {"FCVT.W.D", "FCVT.WU.D"}
        else "test_rv32d_standard_fcvt_single_double_execute_on_rv64_d_and_star"
        if insn in {"FCVT.S.D", "FCVT.D.S"}
        else "test_rv32d_standard_mul_execute_on_rv64_d_and_star"
        if insn == "FMUL.D"
        else "test_rv32d_standard_div_execute_on_rv64_d_and_star"
        if insn == "FDIV.D"
        else "test_rv32d_standard_add_sub_execute_on_rv64_d_and_star"
        if insn in {"FADD.D", "FSUB.D"}
        else "test_rv32d_standard_sqrt_execute_on_rv64_d_and_star"
        if insn == "FSQRT.D"
        else "test_rv32d_standard_fld_fsd_execute_on_rv64_d_and_star"
        if insn in {"FLD", "FSD"}
        else "Full FP64 arithmetic/compare/convert closure pending",
    )

# RV32C compressed extension. Use canonical RV32C mnemonics; RV64-only forms are intentionally omitted.
for insn in [
    "C.ADDI4SPN", "C.LW", "C.SW", "C.NOP", "C.ADDI", "C.JAL", "C.LI", "C.ADDI16SP", "C.LUI",
    "C.SRLI", "C.SRAI", "C.ANDI", "C.SUB", "C.XOR", "C.OR", "C.AND", "C.J", "C.BEQZ", "C.BNEZ",
    "C.SLLI", "C.LWSP", "C.JR", "C.MV", "C.EBREAK", "C.JALR", "C.ADD", "C.SWSP",
]:
    closed_c = {"C.ADDI4SPN", "C.LW", "C.SW", "C.NOP", "C.ADDI", "C.JAL", "C.LI", "C.ADDI16SP", "C.LUI", "C.SRLI", "C.SRAI", "C.ANDI", "C.SUB", "C.XOR", "C.OR", "C.AND", "C.J", "C.BEQZ", "C.BNEZ", "C.SLLI", "C.LWSP", "C.JR", "C.MV", "C.EBREAK", "C.JALR", "C.ADD", "C.SWSP"}
    add(
        "C",
        insn,
        CLOSED if insn in closed_c else GAP,
        "runtime" if insn in closed_c else "compressed-expand-pending",
        "test_rv32c_standard_c_lui_and_c_slli_expand_and_execute"
        if insn in {"C.LUI", "C.SLLI"}
        else "test_rv32c_standard_c_addi4spn_expands_and_executes"
        if insn == "C.ADDI4SPN"
        else "test_rv32c_standard_c_lw_expands_and_executes"
        if insn == "C.LW"
        else "test_rv32c_standard_c_sw_expands_and_executes"
        if insn == "C.SW"
        else "test_rv32c_standard_c_lwsp_expands_and_executes"
        if insn == "C.LWSP"
        else "test_rv32c_standard_c_swsp_expands_and_executes"
        if insn == "C.SWSP"
        else "test_rv32c_standard_c_ebreak_expands_and_traps"
        if insn == "C.EBREAK"
        else "test_rv32c_standard_c_j_expands_and_executes"
        if insn == "C.J"
        else "test_rv32c_standard_c_jal_expands_and_executes"
        if insn == "C.JAL"
        else "test_rv32c_standard_c_jr_expands_and_executes"
        if insn == "C.JR"
        else "test_rv32c_standard_c_jalr_expands_and_executes"
        if insn == "C.JALR"
        else "test_rv32c_standard_c_beqz_expands_and_executes"
        if insn == "C.BEQZ"
        else "test_rv32c_standard_c_bnez_expands_and_executes"
        if insn == "C.BNEZ"
        else "test_rv32c_standard_c_srli_expands_and_executes"
        if insn == "C.SRLI"
        else "test_rv32c_standard_c_srai_expands_and_executes"
        if insn == "C.SRAI"
        else "test_rv32c_standard_c_andi_expands_and_executes"
        if insn == "C.ANDI"
        else "test_rv32c_standard_c_sub_expands_and_executes"
        if insn == "C.SUB"
        else "test_rv32c_standard_c_xor_expands_and_executes"
        if insn == "C.XOR"
        else "test_rv32c_standard_c_or_expands_and_executes"
        if insn == "C.OR"
        else "test_rv32c_standard_c_and_expands_and_executes"
        if insn == "C.AND"
        else "test_rv32c_standard_c_add_expands_and_executes"
        if insn == "C.ADD"
        else "test_rv32c_standard_c_mv_expands_and_executes"
        if insn == "C.MV"
        else "test_rv32c_standard_c_addi16sp_expands_and_executes"
        if insn == "C.ADDI16SP"
        else "test_rv32c_standard_c_nop_c_li_and_c_addi_expand_and_execute"
        if insn in closed_c
        else "Complete compressed expansion/runtime matrix pending",
    )

# Zbb basic bit-manipulation extension, RV32 forms.
for insn in [
    "ANDN", "ORN", "XNOR", "CLZ", "CTZ", "CPOP", "MAX", "MAXU", "MIN", "MINU",
    "SEXT.B", "SEXT.H", "ZEXT.H", "ROL", "ROR", "RORI", "ORC.B", "REV8",
]:
    closed_zbb = {"ANDN", "ORN", "XNOR", "CLZ", "CTZ", "CPOP", "MAX", "MAXU", "MIN", "MINU", "SEXT.B", "SEXT.H", "ZEXT.H", "ROL", "ROR", "RORI", "ORC.B", "REV8"}
    add(
        "Zbb",
        insn,
        CLOSED if insn in closed_zbb else GAP,
        "runtime" if insn in closed_zbb else "execute-pending",
        "test_explicit_b_extension_enables_andn / test_explicit_b_extension_enables_orn / test_explicit_b_extension_enables_xnor / star B runtime parity"
        if insn in {"ANDN", "ORN", "XNOR"}
        else "test_zbb_standard_clz_ctz_cpop_execute_on_rv32_b_and_star"
        if insn in {"CLZ", "CTZ", "CPOP"}
        else "test_zbb_standard_min_max_execute_on_rv32_b_and_star"
        if insn in {"MAX", "MAXU", "MIN", "MINU"}
        else "test_zbb_standard_sign_zero_extend_execute_on_rv32_b_and_star"
        if insn in {"SEXT.B", "SEXT.H", "ZEXT.H"}
        else "test_zbb_standard_orcb_rev8_execute_on_rv32_b_and_star"
        if insn in {"ORC.B", "REV8"}
        else "test_zbb_standard_rotate_execute_on_rv32_b_and_star"
        if insn in {"ROL", "ROR", "RORI"}
        else "Zbb runtime closure pending",
    )

# Zicsr and Zifencei.
for insn in ["CSRRW", "CSRRS", "CSRRC", "CSRRWI", "CSRRSI", "CSRRCI"]:
    add("Zicsr", insn, CLOSED, "runtime", "test_rv32i_standard_zicsr_all_csr_read_write_forms_execute_mstatus_state")
add("Zifencei", "FENCE.I", CLOSED, "runtime", "test_explicit_zifencei_extensions_execute_on_rv32_and_rv64 / star Zifencei tests")

# Standard extensions that define no new user-level instructions in this context.
for ext in ["Zam", "Ztso"]:
    add(ext, "(no new instruction encodings)", NON_INSTRUCTION, "metadata", "Extension affects memory model/atomicity rules rather than adding distinct instruction mnemonics")


def status_counts():
    counts = {CLOSED: 0, PARTIAL: 0, GAP: 0, NON_INSTRUCTION: 0}
    for row in ROWS:
        counts[row["status"]] += 1
    return counts


def write_csv() -> None:
    REPORTS.mkdir(exist_ok=True)
    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["extension", "instruction", "status", "closure", "evidence"])
        writer.writeheader()
        writer.writerows(ROWS)


def write_md() -> None:
    counts = status_counts()
    lines = [
        "# ISA Standard Completion Ledger",
        "",
        "This ledger is the authoritative local checklist for Jasper CPU standard-set closure.",
        "It is deliberately conservative: `CLOSED` requires an executable local runtime closure; `PARTIAL` is not counted as complete.",
        "",
        "## Summary",
        "",
        "| Status | Count |",
        "|--------|------:|",
    ]
    for status in [CLOSED, PARTIAL, GAP, NON_INSTRUCTION]:
        lines.append(f"| {status} | {counts[status]} |")
    lines.extend([
        "",
        "## Policy",
        "",
        "- No standard extension is declared complete while any instruction in that extension is `PARTIAL` or `GAP`.",
        "- `RV32I` is closed at executable runtime level, including the `x0` invariant semantic closure.",
        "- `RV32I+GC` is not yet closed because `M/A/F/D/C/Zicsr` still contain `PARTIAL` or `GAP` rows.",
        "- `RV32I+GC+*` is not yet closed because star/noisy parity is not a substitute for every instruction row reaching `CLOSED`.",
        "",
        "## Instruction Rows",
        "",
        "| Extension | Instruction | Status | Closure | Evidence |",
        "|-----------|-------------|--------|---------|----------|",
    ])
    for row in ROWS:
        lines.append(
            f"| {row['extension']} | {row['instruction']} | {row['status']} | {row['closure']} | {row['evidence']} |"
        )
    lines.append("")
    MD_PATH.write_text("\n".join(lines))


def main() -> None:
    write_csv()
    write_md()
    counts = status_counts()
    print(f"wrote {CSV_PATH.relative_to(ROOT)} and {MD_PATH.relative_to(ROOT)}")
    print(" ".join(f"{key}={counts[key]}" for key in [CLOSED, PARTIAL, GAP, NON_INSTRUCTION]))


if __name__ == "__main__":
    main()
