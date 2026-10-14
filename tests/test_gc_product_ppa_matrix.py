from tools.gc_product_ppa_matrix import (
    PROCESS_NODES,
    PRODUCT_TIERS,
    build_matrix,
)


def test_product_ppa_matrix_shape():
    rows = build_matrix()
    assert len(rows) == len(PRODUCT_TIERS) * len(PROCESS_NODES)
    assert len(rows) == 30
    assert {row["tier"] for row in rows} == {
        "MCU", "EDGE", "MOBILE", "LAPTOP", "DESKTOP", "SERVER",
    }
    assert {row["node"] for row in rows} == {"12nm", "10nm", "7nm", "5nm", "3nm"}


def test_product_ppa_matrix_cpu_core_semantics():
    rows = build_matrix()
    mobile = next(row for row in rows if row["tier"] == "MOBILE" and row["node"] == "5nm")
    laptop = next(row for row in rows if row["tier"] == "LAPTOP" and row["node"] == "5nm")
    desktop = next(row for row in rows if row["tier"] == "DESKTOP" and row["node"] == "5nm")
    server = next(row for row in rows if row["tier"] == "SERVER" and row["node"] == "5nm")

    assert mobile["cpu_cores"] == 8
    assert laptop["cpu_cores"] == 16
    assert desktop["cpu_cores"] == 32
    assert server["cpu_cores"] == 64
    assert mobile["cpu_freq_ghz"] == 3.2
    assert laptop["cpu_freq_ghz"] == 4.2
    assert desktop["cpu_freq_ghz"] == 5.2
    assert server["cpu_freq_ghz"] == 3.2
    assert mobile["gc_ip_freq_ghz"] < mobile["cpu_freq_ghz"]


def test_product_ppa_matrix_throughput_order_at_each_node():
    rows = build_matrix()
    tier_order = ["MCU", "EDGE", "MOBILE", "LAPTOP", "DESKTOP", "SERVER"]
    for node in {row["node"] for row in rows}:
        values = [
            next(row["backend_theory_mev_s"] for row in rows
                 if row["tier"] == tier and row["node"] == node)
            for tier in tier_order
        ]
        assert values == sorted(values)


def test_product_ppa_matrix_current_top_ingress_limit_is_explicit():
    rows = build_matrix()
    for row in rows:
        assert row["current_top_evt_per_cycle"] <= row["backend_theory_evt_per_cycle"]
        assert row["current_top_evt_per_cycle"] <= row["ingress_evt_per_cycle"]
    edge_5nm = next(row for row in rows if row["tier"] == "EDGE" and row["node"] == "5nm")
    mobile_5nm = next(row for row in rows if row["tier"] == "MOBILE" and row["node"] == "5nm")
    assert edge_5nm["current_top_evt_per_cycle"] > 1.0
    assert mobile_5nm["current_top_evt_per_cycle"] > edge_5nm["current_top_evt_per_cycle"]


def test_product_ppa_matrix_cpu_demand_is_modelled():
    rows = build_matrix()
    for row in rows:
        assert row["cpu_gc_event_demand_mev_s"] > 0
        assert row["headroom_vs_cpu_demand"] > 0
    mobile_5nm = next(row for row in rows if row["tier"] == "MOBILE" and row["node"] == "5nm")
    server_5nm = next(row for row in rows if row["tier"] == "SERVER" and row["node"] == "5nm")
    assert mobile_5nm["current_top_mev_s"] > mobile_5nm["cpu_gc_event_demand_mev_s"]
    assert server_5nm["cpu_gc_event_demand_mev_s"] > mobile_5nm["cpu_gc_event_demand_mev_s"]
