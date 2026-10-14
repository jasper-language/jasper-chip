# Jasper-GC 多核架构设计

## 设计原则

```
离流水线越近 → 每核一份（保持 WB/RB 零周期）
离后台 GC 越近 → 多核共享（避免面积爆炸）
既要低延迟又要高容量 → 每核小缓存 + 共享大模块
```

---

## 1. 每核必有的前台热路径模块

这些模块在主流水线热路径上，必须每核独立，否则跨核仲裁会破坏 WB/RB 零周期。

| 模块 | 原因 |
|------|------|
| **GCSubsystem (Frontend)** | 本核 store/load 的热路径接口 |
| **WB barrier 触发逻辑** | store 在本核提交，不能跨核等仲裁 |
| **WB FIFO (wbq)** | 吸收本核突发 store，满时才回压 |
| **RB pending slots** | 本核 load 的 RD 依赖跟踪 |
| **RB 小 cache** | 低延迟 forwarding fast path |
| **GC slots / pending tag** | 本核 GC 指令响应匹配 |
| **scoreboard (pending_rd_mask)** | 本核寄存器依赖，不能共享 |
| **GC forwarding bypass** | 本核 EX/IS operand 转发 |
| **gc_fire / gc_rsp_match** | GC 指令发射和响应匹配 |
| **heap range / pointer filter** | 本核 store/load 地址判定 |

### 关键约束

```
Core-N:                          Core-M:
┌────────────────────┐          ┌────────────────────┐
│ GCSubsystem        │          │ GCSubsystem        │
│  ├─ WB FIFO        │          │  ├─ WB FIFO        │
│  ├─ RB slots       │          │  ├─ RB slots       │
│  ├─ RB cache       │          │  ├─ RB cache       │
│  ├─ GC slots       │          │  ├─ GC slots       │
│  └─ scoreboard     │          │  └─ scoreboard     │
└────────┬───────────┘          └────────┬───────────┘
         │                              │
         ▼                              ▼
    [共享 GC 后端 — 见下节]              │
```

**不允许共享的理由：** 如果 WB barrier 触发要走跨核仲裁 → store 延迟增加 → WB 不再零周期。  
**必须独立的原因：** load 是否触发 RB 取决于本核地址和本核 scoreboard。

---

## 2. 多核共享更合理的后台模块

这些属于后台 GC，不在单条 load/store 的关键路径上。

| 模块 | 共享理由 |
|------|---------|
| **GCScanCoProc** | 全局写屏障事件聚合器 + card 去重 |
| **GCSweepCoProc / Clean** | 全堆 mark/sweep 状态 |
| **GCMvCoProc** | 全局 old→new forwarding table |
| **GCRootScanner** | 扫全局 root set |
| **GCHeapWalker** | 后台对象图遍历 |
| **GCCycleController** | 统一控制 GC 周期 |
| **全局 mark bitmap** | 全堆共享表示 |
| **Card table / remembered set** | 全堆脏卡信息 |
| **Free list / allocator** | 全局分配状态 |
| **Epoch controller** | 全局 GC 轮次 |

### 共享架构

```
          Core-0        Core-1        Core-2        Core-3
          │             │             │             │
          ▼             ▼             ▼             ▼
    ┌───────────────────────────────────────────────────┐
    │           WB Event Arbiter (RR)                   │
    └───────────────────────┬───────────────────────────┘
                            ▼
                    ┌───────────────┐
                    │ GCScanCoProc  │  (共享去重/聚合)
                    └───────┬───────┘
                            ▼ scan events
                    ┌───────────────┐
                    │ GCSweepCoProc │  (共享清扫)
                    └───────┬───────┘
                            ▼ reloc events
                    ┌───────────────┐
                    │ GCMvCoProc    │  (共享 forwarding)
                    └───────────────┘
```

**面积节省估算（4核）：**
- 每核复制全部后台 GC：4 × 25K 门 = 100K 门
- 每核前台 + 共享后台：4 × 12K + 25K = 73K 门
- **节省约 27%**

---

## 3. 分层架构：每核小前端 + 共享大后端

### 3.1 RB Cache / Forwarding

```
Core-0 RB Cache      Core-1 RB Cache      Core-2 RB Cache
(4-8 entries,         (4-8 entries,        (4-8 entries,
 direct-mapped)        direct-mapped)       direct-mapped)
      │                     │                     │
      └────────────┬────────┴────────┬────────────┘
                   ▼                 ▼
          ┌──────────────────────────────────┐
          │    GCMvCoProc Forwarding Table   │
          │    (256-1024 entries, 4-way)      │
          └──────────────────────────────────┘
```

- **每核 RB Cache**：4-8 条，直接映射，零延迟命中
- **共享 Forwarding Table**：256-1024 条，全局一致
- 本核命中 → 零周期；miss → 查共享表（~2-3 cycle）

### 3.2 Metadata Cache

```
Core-0 L0 Meta   Core-1 L0 Meta   Core-2 L0 Meta
(512B-1KB)       (512B-1KB)       (512B-1KB)
      │                │                │
      └────────┬───────┴────────┬───────┘
               ▼                ▼
       ┌────────────────────────────┐
       │  Shared L2 Metadata Cache   │
       │  (16KB-64KB, 4-8 way)       │
       └────────────────────────────┘
```

- **L0**：每核极小 cache，存最近访问的 mark/card/header
- **L2**：共享大 cache，多核一致
- MCU 可跳过 L0，直接用共享小 cache

### 3.3 Stream Buffer

```
Core-0 ReqQ   Core-1 ReqQ   Core-2 ReqQ
(2-4 entry)   (2-4 entry)   (2-4 entry)
      │             │             │
      └──────┬──────┴──────┬──────┘
             ▼             ▼
     ┌──────────────────────────┐
     │ Shared Stream Buffer      │
     │ (8-16 entry × 64B line)   │
     └──────────────────────────┘
```

- **每核请求队列**：小队列记录 GC 顺序访问模式
- **共享 stream buffer**：实际缓存空间，后台填充

### 3.4 Cache Partition

```
Policy Controller (共享)
  ├── 决定 mutator_reserved_ways / gc_reserved_ways
  ├── 决定 bypass 策略
  └── 广播给所有 cache 层
        │
  ┌─────┼─────┬─────┐
  ▼     ▼     ▼     ▼
L1D0  L1D1  L1D2  L1D3  (本地执行 partition / bypass)
  │     │     │     │
  └─────┴─────┴─────┘
        ▼
     L2/L3          (全局 partition / QoS)
```

- **Policy Controller**：一个共享模块，广播策略
- **Enforcement**：每个 cache 本地执行 bypass/no-fill/partition

---

## 4. 模块归属矩阵

| 模块 | 每核 | 共享 | 分层 |
|------|------|------|------|
| GCSubsystem (Frontend) | ✅ | — | — |
| WB FIFO (wbq) | ✅ | — | — |
| RB pending slots | ✅ | — | — |
| RB Cache (小) | ✅ | — | 可选 L0 |
| RB Cache (大) | — | ✅ | 共享 L2 |
| GC slots | ✅ | — | — |
| Scoreboard | ✅ | — | — |
| GC forwarding bypass | ✅ | — | — |
| Heap range / pointer filter | ✅ | — | — |
| WB Event Arbiter | — | ✅ | RR 仲裁 |
| GCScanCoProc | — | ✅ | 聚合+去重 |
| GCSweepCoProc | — | ✅ | 全局 state |
| GCMvCoProc | — | ✅ | 全局 table |
| GCRootScanner | — | ✅ | 后台扫描 |
| GCHeapWalker | — | ✅ | 后台遍历 |
| GCCycleController | — | ✅ | 统一控制 |
| Metadata Cache | — | ✅ | L0 可选 + L2 共享 |
| Stream Buffer | — | ✅ | 请求本核 + 缓存共享 |
| Cache Partition Policy | — | ✅ | 策共享 + 执行本地 |
| Epoch Controller | — | ✅ | 全局轮次 |
| Card table / Mark bitmap | — | ✅ | 全堆元数据 |
| Forwarding Table | — | ✅ | 全局映射 |
| Cache Pollution Tool | — | ✅ | 非硬件 |

---

## 5. MCU / Desktop / Server 配置差异

### MCU (单核或 2 核小系统)

```
每核: GCSubsystem + WB FIFO(2) + RB slots(2) + RB cache(2-way)
共享: ScanCoProc + SweepCoProc + MvCoProc (精简参数)
Metadata Cache: 可选 1-2KB 共享 或 关闭
Stream Buffer: 可选 2-entry 或 关闭
Partition: 关闭
预估面积: ~35K 门 (GC)
```

### Mobile (4-8 核，功耗优先)

```
每核: GCSubsystem + WB FIFO(4) + RB slots(4) + RB cache(4-way)
共享: Scan + Clean + Move + RootScanner + HeapWalker + Cycle
L0 Metadata: 每核 512B (可选)
L2 Metadata: 共享 8-16KB
Stream Buffer: 共享 4-entry
Partition: 基础 bypass 策略
预估面积: ~60K 门 + 每核 ~12K
```

### Desktop / Server (8-32 核，性能优先)

```
每核: GCSubsystem + WB FIFO(8) + RB slots(8) + RB cache(8-way)
共享: 全后台模块 + 大参数
L0 Metadata: 每核 1KB
L2 Metadata: 共享 32-64KB
Stream Buffer: 共享 8-16 entry
Partition: 完整策略 + QoS
NUMA: 每 NUMA 节点一套共享后台
预估面积: ~120K 门 + 每核 ~15K
```

---

## 6. 实现建议

### 第一阶段（当前 — 单核验证）

- 所有模块单例（每核一套）
- GCSubsystem + 全部后台 + MemoryPolicy 都在一个核内
- 验证 WB/RB 零周期不变

### 第二阶段（多核前台）

- 每核复制 GCSubsystem
- WB FIFO、RB slots、RC cache、GC slots、scoreboard 随核复制
- 共享 Scan/Sweep/Move 保持单例

### 第三阶段（共享后台）

- 引入 WB Event Arbiter（RR 仲裁）
- Scan/Clean/Move 改为多核入口
- GCCycleController 统一管理

### 第四阶段（分层优化）

- L0/L2 Metadata Cache 分层
- Stream Buffer 请求/缓存分离
- Cache Partition 策略 + 执行

---

## 7. 关键底线

无论多核架构如何变化，以下指标不能退化：

```
WB barrier:      零周期（不允许跨核仲裁）
RB barrier:      非阻塞（不允许跨核等待）
GC 指令无依赖:   零 stall
堆 store CPI:    = 非堆 store CPI
pipeline stall:  不因 GC 后台访存产生
```
