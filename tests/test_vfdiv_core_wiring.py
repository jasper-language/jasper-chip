"""Low-resource machine audit for RV12Core V divide integration."""

import ast
from pathlib import Path


CORE = Path(__file__).parents[1] / "rtl" / "rv12_core.py"


def test_rv12_core_vfdiv_pipeline_is_complete_and_inline_engine_is_gone():
    source = CORE.read_text()
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    attributes = {node.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute)}
    assert "VFDivPipeline" in names
    assert any(isinstance(call.func, ast.Name) and
               call.func.id == "VFDivPipeline" for call in calls)
    assert "VFDivUnit" not in names
    assert "vfdiv_active" not in names
    assert "vfdiv_waiting" not in names
    required_ports = {
        "issue_valid", "insn", "write_valid", "write_reg", "write_lane",
        "write_data", "fflags_write_valid", "fflags_write_value",
        "vstart_valid", "vstart_value", "busy", "redirect", "illegal",
    }
    assert required_ports <= attributes
    required_paths = (
        "vfdiv_pipe.issue_valid.eq(1)",
        "vfdiv_pipe.insn.eq(Cat(",
        "vregs[vfdiv_pipe.write_reg].word_select(",
        "csr_fflags | vfdiv_pipe.fflags_write_value",
        "csr_vstart.eq(vfdiv_pipe.vstart_value)",
        "vfdiv_pipe.busy",
        "redirect_pc.eq(IS.pc + 4)",
    )
    for path in required_paths:
        assert path in source
