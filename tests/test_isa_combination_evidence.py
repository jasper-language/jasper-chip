from tools.isa_combination_evidence import EXPECTED_TEST_COUNTS, audit


def test_low_resource_combination_evidence_is_complete():
    result = audit()
    assert result["status"] == "complete", result
    assert result["test_counts"] == EXPECTED_TEST_COUNTS
    assert result["gc_config_total"] == 33
    assert result["evidence_node_count"] == 15
    assert result["wiring_marker_count"] == 10
    assert result["missing_nodes"] == {}
    assert result["missing_markers"] == {}
    assert result["missing_commits"] == []
