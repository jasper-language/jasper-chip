# tests/test_gc_backend_config.py — GC 多 backend 配置回归
from rtl.gc_config import JasperGCConfig, get_profile, GCBackendConfig

def test_backend_defaults():
    """backend_count/bank_count 默认全部=1"""
    c = GCBackendConfig()
    assert c.scan_backend_count == 1
    assert c.sweep_backend_count == 1
    assert c.move_backend_count == 1
    assert c.heap_walk_backend_count == 1
    assert c.metadata_bank_count == 1
    assert c.forwarding_bank_count == 1
    assert c.slots_bank_count == 1
    assert c.backend_dispatch_policy == "round_robin"
    assert c.backend_merge_policy == "none"
    print("PASS")

def test_lite_profile():
    """Lite: 全部=1"""
    c = get_profile("lite")
    assert c.backend.scan_backend_count == 1
    assert c.backend.sweep_backend_count == 1
    assert c.backend.move_backend_count == 1
    assert c.backend.heap_walk_backend_count == 1
    assert c.backend.metadata_bank_count == 1
    assert c.backend.forwarding_bank_count == 1
    assert c.backend.slots_bank_count == 1
    print("PASS")

def test_standard_profile():
    """Standard: 全部=1"""
    c = get_profile("standard")
    assert c.backend.scan_backend_count == 1
    assert c.backend.sweep_backend_count == 1
    assert c.backend.move_backend_count == 1
    assert c.backend.heap_walk_backend_count == 1
    assert c.backend.metadata_bank_count == 1
    assert c.backend.forwarding_bank_count == 1
    assert c.backend.slots_bank_count == 1
    print("PASS")

def test_server_profile():
    """Server: 多 backend (experimental)"""
    c = get_profile("server")
    assert c.backend.scan_backend_count == 4
    assert c.backend.sweep_backend_count == 2
    assert c.backend.move_backend_count == 4
    assert c.backend.heap_walk_backend_count == 1  # 未显式设置, 默认=1
    assert c.backend.metadata_bank_count == 4
    assert c.backend.forwarding_bank_count == 4
    assert c.backend.slots_bank_count == 2
    assert c.backend.backend_dispatch_policy == "hash_lsb"
    assert c.backend.backend_merge_policy == "ordered"
    assert c.backend.forwarding_table_impl == "banked_pipeline"
    assert c.backend.metadata_pipeline_impl == "pipelined"
    assert c.backend.slots_impl == "banked"
    print("PASS")

def test_policy_valid():
    """dispatch/merge policy 取值合法"""
    valid_dispatch = {"round_robin", "hash_lsb", "broadcast", "affinity"}
    valid_merge = {"none", "ordered", "priority"}
    for name in ["lite", "standard", "server"]:
        c = get_profile(name)
        assert c.backend.backend_dispatch_policy in valid_dispatch, f"{name}: bad dispatch"
        assert c.backend.backend_merge_policy in valid_merge, f"{name}: bad merge"
    print("PASS")

def test_single_backend_equiv():
    """backend_count=1 等价于无后端配置"""
    d = JasperGCConfig()
    c = JasperGCConfig(backend=GCBackendConfig())
    assert c.backend.scan_backend_count == d.backend.scan_backend_count
    assert c.backend.sweep_backend_count == d.backend.sweep_backend_count
    assert c.backend.move_backend_count == d.backend.move_backend_count
    assert c.backend.metadata_bank_count == d.backend.metadata_bank_count
    for attr in ["backend_dispatch_policy", "backend_merge_policy"]:
        assert getattr(c.backend, attr) == getattr(d.backend, attr)
    print("PASS")

if __name__ == "__main__":
    tests = [
        ("defaults", test_backend_defaults),
        ("lite profile", test_lite_profile),
        ("standard profile", test_standard_profile),
        ("server profile", test_server_profile),
        ("policy valid", test_policy_valid),
        ("single equiv", test_single_backend_equiv),
    ]
    print("=" * 50)
    print("GC Backend Config Test")
    print("=" * 50)
    all_ok = True
    for name, fn in tests:
        try:
            fn()
            print(f"  {name:20s} ✅")
        except Exception as e:
            print(f"  {name:20s} ❌ {e}")
            all_ok = False
    print(f"\n{'ALL PASS' if all_ok else 'SOME FAILED'}")
    import sys
    sys.exit(0 if all_ok else 1)
