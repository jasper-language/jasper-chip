"""Machine-checkable audit for the low-resource ISA combination closure."""

import argparse
import ast
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_TEST_COUNTS = {
    "tests/test_isa_standard_completion.py": 984,
    "tests/test_extension_config.py": 60,
    "tests/test_gc_backend_config.py": 6,
    "tests/test_jasper_gc_accelerator_config.py": 10,
    "tests/test_jasper_gc_ip_config.py": 17,
}

EVIDENCE_NODES = {
    "tests/test_is_advance_control.py": {
        "test_is_advance_control_all_input_combinations",
    },
    "tests/test_fp_store_hazard_control.py": {
        "test_fp_store_hazard_widths_and_all_pipeline_slots",
        "test_fp_store_hazard_is_disabled_for_finx_register_mode",
    },
    "tests/test_branch_condition.py": {
        "test_all_branch_conditions_and_boundaries",
    },
    "tests/test_jump_control.py": {
        "test_jal_and_jalr_link_target_boundaries",
    },
    "tests/test_pending_register_hazard.py": {
        "test_all_register_indices_and_pending_mask_boundaries",
        "test_all_enable_combinations_and_independent_register_matches",
    },
    "tests/test_dependency_stall_control.py": {
        "test_all_dependency_stall_input_combinations",
    },
    "tests/test_pending_mask_control.py": {
        "test_each_clear_port_and_all_register_indices",
        "test_all_valid_combinations_overlap_and_independent_clears",
    },
    "tests/test_pending_scoreboard_update.py": {
        "test_each_set_and_clear_port_all_registers",
        "test_all_port_valid_combinations_and_clear_priority",
    },
    "tests/test_base_rs1_usage_control.py": {
        "test_all_base_rs1_usage_combinations",
    },
    "tests/test_base_rd_write_control.py": {
        "test_all_opcodes_and_control_combinations",
    },
    "tests/test_jalr_dependency_equivalence.py": {
        "test_jalr_dependency_and_address_equivalence",
    },
}

WIRING_MARKERS = {
    "rtl/rv12_core.py": {
        "BranchCondition(self.xlen)",
        "JumpControl(self.xlen)",
        "PendingRegisterHazard()",
        "DependencyStallControl()",
        "PendingMaskControl(clear_ports=3)",
        "BaseRS1UsageControl()",
        "BaseRDWriteControl()",
        "FPStoreHazardControl(",
        "ISAdvanceControl()",
    },
    "rtl/gc_subsystem.py": {
        "PendingScoreboardUpdate(set_ports=2, clear_ports=4)",
    },
}

EVIDENCE_COMMITS = (
    "1f3e7ca", "88c91f4", "5a91bd7", "b24adb1", "209f776",
    "cbcac34", "b46e403", "6d8ac95", "99ed4ae", "5f469b0",
    "60244bc", "b9a2ff8", "82ac0c5",
)

RESOURCE_REPLACEMENTS = {
    "RV32I+GC+* monolithic": "partitioned extension/configuration evidence",
    "V integer monolithic": "V layered execution and wiring evidence",
    "RV32A aggregate": "RV32/RV64 AMO and LR/SC partitioned evidence",
    "RV32 branch aggregate": "BranchCondition exhaustive evidence",
    "direct JALR dependency core": "JALRDependencyHarness end-to-end evidence",
    "RV32C single core": "C execution evidence plus control-module partitions",
}


def _test_functions(relative_path):
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    return {
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def _commit_exists(commit):
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def audit():
    counts = {
        path: len(_test_functions(path)) for path in EXPECTED_TEST_COUNTS
    }
    missing_nodes = {}
    for path, expected in EVIDENCE_NODES.items():
        missing = sorted(expected - _test_functions(path))
        if missing:
            missing_nodes[path] = missing

    missing_markers = {}
    for path, markers in WIRING_MARKERS.items():
        source = (ROOT / path).read_text(encoding="utf-8")
        missing = sorted(marker for marker in markers if marker not in source)
        if missing:
            missing_markers[path] = missing

    missing_commits = [commit for commit in EVIDENCE_COMMITS
                       if not _commit_exists(commit)]
    q_files = sorted(path.name for path in (ROOT / "tests").glob("test_isa_q_*.py"))
    v_files = sorted(path.name for path in (ROOT / "tests").glob("test_isa_v_*.py"))
    count_ok = counts == EXPECTED_TEST_COUNTS
    gc_total = sum(counts[path] for path in (
        "tests/test_gc_backend_config.py",
        "tests/test_jasper_gc_accelerator_config.py",
        "tests/test_jasper_gc_ip_config.py",
    ))
    complete = (
        count_ok and gc_total == 33 and not missing_nodes and
        not missing_markers and not missing_commits and
        len(q_files) >= 10 and len(v_files) >= 1
    )
    return {
        "status": "complete" if complete else "incomplete",
        "test_counts": counts,
        "gc_config_total": gc_total,
        "evidence_node_count": sum(len(nodes) for nodes in EVIDENCE_NODES.values()),
        "wiring_marker_count": sum(len(markers) for markers in WIRING_MARKERS.values()),
        "evidence_commits": list(EVIDENCE_COMMITS),
        "q_test_file_count": len(q_files),
        "v_test_file_count": len(v_files),
        "resource_replacements": RESOURCE_REPLACEMENTS,
        "missing_nodes": missing_nodes,
        "missing_markers": missing_markers,
        "missing_commits": missing_commits,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit()
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    raise SystemExit(0 if result["status"] == "complete" else 1)


if __name__ == "__main__":
    main()
