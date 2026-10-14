"""Low-resource machine audit for RV12Core V add/sub integration."""

import ast
from pathlib import Path


CORE = Path(__file__).parents[1] / "rtl" / "rv12_core.py"


def test_rv12_core_vfadd_pipeline_replaces_inline_add_sub_execution():
    source = CORE.read_text()
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    attributes = {node.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute)}
    assert "VFAddPipeline" in names
    assert any(isinstance(call.func, ast.Name) and
               call.func.id == "VFAddPipeline" for call in calls)
    required_ports = {
        "issue_valid", "insn", "write_valid", "write_reg", "write_lane",
        "write_data", "fflags_write_valid", "fflags_write_value",
        "vstart_valid", "vstart_value", "busy", "redirect", "illegal",
    }
    assert required_ports <= attributes
    assert "vfadd_group_regs" not in names
    assert "vfadd_flags_expr" not in names
    required_paths = (
        "vfadd_pipe.issue_valid.eq(1)",
        "vfadd_pipe.insn.eq(Cat(",
        "vregs[vfadd_pipe.write_reg].word_select(",
        "csr_fflags | vfadd_pipe.fflags_write_value",
        "csr_vstart.eq(vfadd_pipe.vstart_value)",
        "vfadd_pipe.busy",
        "redirect_pc.eq(IS.pc + 4)",
    )
    for path in required_paths:
        assert path in source
