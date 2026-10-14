"""Low-resource machine audit for the RV12Core V FMA integration."""

import ast
from pathlib import Path


CORE = Path(__file__).parents[1] / "rtl" / "rv12_core.py"


def test_rv12_core_vffma_pipeline_is_complete_and_inline_engine_is_gone():
    source = CORE.read_text()
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert "VFFMAPipeline" in names
    assert any(isinstance(call.func, ast.Name) and
               call.func.id == "VFFMAPipeline" for call in calls)
    assert "VFFMAUnit" not in names
    assert "vffma_active" not in names
    assert "vffma_index" not in names

    required_ports = {
        "issue_valid", "insn", "write_valid", "write_reg", "write_lane",
        "write_data", "fflags_write_valid", "fflags_write_value",
        "vstart_clear", "busy", "redirect", "illegal",
    }
    assert required_ports <= attributes

    required_paths = (
        "vffma_pipe.issue_valid.eq(1)",
        "vffma_pipe.insn.eq(Cat(",
        "vregs[vffma_pipe.write_reg].word_select(",
        "csr_fflags | vffma_pipe.fflags_write_value",
        "csr_vstart.eq(0)",
        "vffma_pipe.busy",
        "redirect_pc.eq(IS.pc + 4)",
    )
    for path in required_paths:
        assert path in source
