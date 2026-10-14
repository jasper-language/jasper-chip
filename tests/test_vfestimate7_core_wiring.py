"""Low-resource machine audit for RV12Core V estimate integration."""

import ast
from pathlib import Path


CORE = Path(__file__).parents[1] / "rtl" / "rv12_core.py"


def test_rv12_core_vfestimate7_pipeline_is_fully_connected():
    source = CORE.read_text()
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    attributes = {node.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute)}
    assert "VFEstimate7Pipeline" in names
    assert any(isinstance(call.func, ast.Name) and
               call.func.id == "VFEstimate7Pipeline" for call in calls)
    required_ports = {
        "issue_valid", "insn", "write_valid", "write_reg", "write_lane",
        "write_data", "fflags_write_valid", "fflags_write_value",
        "vstart_valid", "vstart_value", "busy", "redirect", "illegal",
    }
    assert required_ports <= attributes
    required_paths = (
        "vfestimate7_pipe.issue_valid.eq(1)",
        "vfestimate7_pipe.insn.eq(Cat(",
        "vregs[vfestimate7_pipe.write_reg].word_select(",
        "csr_fflags | vfestimate7_pipe.fflags_write_value",
        "csr_vstart.eq(vfestimate7_pipe.vstart_value)",
        "vfestimate7_pipe.busy",
        "IS.rs1 == 0b00100",
        "IS.rs1 == 0b00101",
        "redirect_pc.eq(IS.pc + 4)",
    )
    for path in required_paths:
        assert path in source
