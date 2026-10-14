import ast
from pathlib import Path


CORE = Path(__file__).parents[1] / "rtl" / "rv12_core.py"


def test_rv12_core_vmemory_pipeline_and_dmem_arbitration_are_complete():
    source = CORE.read_text()
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    assert "VMemoryPipeline" in names
    assert any(isinstance(call.func, ast.Name) and
               call.func.id == "VMemoryPipeline" for call in calls)
    assert "vmem_active" not in names
    assert {"vmem_is_insn", "vmem_backend_clear", "vmem_launch"} <= names

    required_ports = {
        "issue_valid", "issue_ready", "insn", "busy", "illegal",
        "redirect", "execute_trap", "base", "stride", "vtype", "vl",
        "vlmax", "vstart", "vregs", "dmem_valid", "dmem_we",
        "dmem_addr", "dmem_wdata", "dmem_rdata", "dmem_grant",
        "dmem_error", "write_valid", "write_reg", "write_byte",
        "write_data", "vl_write_valid", "vl_write_value",
        "vstart_valid", "vstart_value",
    }
    assert required_ports <= attributes

    assert "EX1.valid.eq(IS.valid & ~vmem_launch)" in source
    assert "vmem_pipe.busy" in source
    assert "vmem_pipe.dmem_valid, vmem_pipe.dmem_we" in source
    assert "vmem_pipe.dmem_valid, vmem_pipe.dmem_addr" in source
    assert "vmem_pipe.dmem_valid, vmem_pipe.dmem_wdata" in source
