import ast
from pathlib import Path


CORE = Path(__file__).parents[1] / "rtl" / "rv12_core.py"


def test_vmask_logical_all_encodings_reserved_vm_and_restart_boundary():
    source = CORE.read_text()
    tree = ast.parse(source)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    constants = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }

    assert "is_mask_logical" in names
    assert set(range(0x18, 0x20)) <= constants
    assert "csr_vtype[self.xlen - 1] | ~vm" in source
    assert "csr_vstart < csr_vl" in source
    assert "vregs[IS.rs2] & ~vregs[IS.rs1]" in source
    assert "~(vregs[IS.rs2] ^ vregs[IS.rs1])" in source
