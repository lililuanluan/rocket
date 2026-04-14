# EVO 并行化重构方案

这份文档描述如何把当前 `evo` 目录下的两层并行模型，重构成：

- 只有一个地方控制并发度
- 不同配置组合之间可以并行
- 同一个配置组合内部遵守遗传算法的 generation barrier
- 端口、日志、容器命名保持隔离
- 现有 `run_rocket.py` 的单任务执行边界尽量复用

本文档尽量贴近当前代码，而不是重新发明一套系统。

---

## 1. 当前问题

当前并发模型主要有两层：

1. [run_evotests.py](/data/home/lli21/rocket/evo/run_evotests.py)
   会把 `image × strategy × fitness` 的组合并行启动
2. [evotest_parallel.py](/data/home/lli21/rocket/evo/evotest_parallel.py)
   内部又用 `ProcessPoolExecutor` 并行评估一代中的多个 individual

这会导致几个问题：

- 总并发数不透明，很难知道当前到底同时跑了多少个测试
- Docker / systemd / cgroup 压力被两层并发叠加放大
- 出错时难以判断是组合级并发还是 individual 级并发导致
- `evotest_parallel.py` 既负责 GA 逻辑，又负责进程池调度，职责耦合过重

从最近日志来看，当前最直接的故障就是 Docker 容器创建阶段被并发打爆，出现：

- `panicked at src/docker_manager.rs:444:14`
- `failed to create task for container`
- `Timeout waiting for systemd to create docker-....scope`

所以重构目标不是“让并行更多”，而是“让并行受控”。

---

## 2. 重构目标

目标并发语义如下：

- 不同配置组合之间可以并行
- 同一配置组合内部，只有同一 generation 的任务可以并行
- 某个组合的下一代，必须等它自己的上一代全部完成后才能提交
- 全局最多同时运行 `N` 个任务
- 只有一个地方控制这个 `N`

这里“配置组合”建议定义为：

- `ripple_image`
- `strategy`
- `fitness_function`
- 如果未来 `encoding family` 也可变，则加上 `encoding_name`

也就是说，一个组合是一条独立的进化链；不同链之间互不影响，但共享同一个全局任务池。

---

## 3. 设计原则

### 3.1 不拆散 GA 逻辑

`mutation / crossover / selection / generation 推进` 仍然属于“单个实验组合”的内部逻辑，不应被拆成无状态任务。

也就是说：

- 每个组合仍然需要一个自己的 GA runner
- 这个 runner 维护 population、generation、fitness 汇总、hall of fame 等状态

### 3.2 只拆出“单任务执行”

真正应该抽离的是“individual 的评估执行”。

当前 [run_rocket.py](/data/home/lli21/rocket/evo/run_rocket.py) 里的 `run_rocket_and_evaluate(...)` 已经天然是一个很好的“单任务执行边界”：

- 输入：编码、端口基址、日志目录、镜像、策略等
- 输出：`eval_result` 和 `fitness`
- 内部会自己清理容器和临时 YAML

所以它应该继续保留，并作为未来统一任务池的最小执行单元。

### 3.3 调度器统一控并发

未来系统里只能有一个并发控制点：

- 全局 scheduler / task pool

任何组合 runner 都不能再自己内部偷偷开进程池控制并发。

---

## 4. 推荐的新架构

建议把当前结构整理成下面几个角色。

### 4.1 `ExperimentRunner`

职责：

- 代表一个固定配置组合的一整个进化过程
- 持有本组合的 GA 状态
- 只在本组合当前 generation 全部完成后才产生下一代任务
- 不直接执行任务，只生成“可运行任务”

建议每个 runner 管理以下状态：

- `experiment_id`
- `config`
- `population`
- `current_generation`
- `pending_results`
- `completed_results`
- `max_generation`
- `done`

### 4.2 `EvaluationTask`

职责：

- 表示一个可执行的 individual 评估任务

建议字段：

- `experiment_id`
- `generation`
- `individual_id`
- `encoding`
- `ripple_image`
- `strategy`
- `fitness_function`
- `base_port_number`
- `log_dir`
- `cluster_id`
- `timeout_sec`

### 4.3 `GlobalScheduler`

职责：

- 全局唯一并发控制点
- 统一限制最大同时运行任务数
- 从各个 `ExperimentRunner` 收集“当前合法可运行的任务”
- 启动任务
- 监听任务完成
- 把结果回传给对应 runner

建议这个 scheduler 暂时实现为“进程内对象”，不做成独立 server。

原因：

- 当前需求还不需要跨机器或跨客户端提交任务
- 做成独立进程会额外引入协议、状态同步、重连、持久化等复杂度
- 先在同一 Python 进程内实现，已经足够解决当前问题

---

## 5. 建议的文件/脚本组织

当前不建议把所有逻辑继续堆在 [evotest_parallel.py](/data/home/lli21/rocket/evo/evotest_parallel.py) 里。

建议重构成下面的结构：

```text
evo/
  run_evotests.py          # 顶层入口，读取 YAML，创建所有 ExperimentRunner 和全局 Scheduler
  scheduler.py             # 全局任务池与调度循环
  experiment_runner.py     # 单个配置组合的一条 GA 进化链
  task_types.py            # EvaluationTask / TaskResult 等 dataclass
  evaluate_worker.py       # 单任务执行入口，包装 run_rocket_and_evaluate
  run_rocket.py            # 保留，继续作为单任务执行的核心
  port_allocator.py        # 端口分配逻辑集中管理
  configs.py               # CLI / YAML 配置解析
  evologger.py             # 日志输出与结果记录
  parallel.md              # 本文档
```

### 5.1 现有文件如何迁移

[run_evotests.py](/data/home/lli21/rocket/evo/run_evotests.py)

- 保留为最顶层入口
- 不再直接用 subprocess 启多个 `evotest_parallel.py`
- 改为：
  - 读取配置
  - 展开组合
  - 为每个组合构造一个 `ExperimentRunner`
  - 创建一个 `GlobalScheduler`
  - 启动调度循环

[evotest_parallel.py](/data/home/lli21/rocket/evo/evotest_parallel.py)

- 不建议继续保留“parallel”这个语义
- 其中的 GA 核心逻辑拆到 `experiment_runner.py`
- 其中的 `parallel_evaluate_population(...)` 删除或退化为“由 scheduler 代为执行”

[run_rocket.py](/data/home/lli21/rocket/evo/run_rocket.py)

- 尽量保持稳定
- 它已经是一个非常好的单任务执行边界
- 新系统中，worker 最终还是调用它

---

## 6. 端口隔离方案

端口管理必须统一，不要散落在各个模块里临时计算。

### 6.1 当前已有的正确思路

当前 [run_rocket.py](/data/home/lli21/rocket/evo/run_rocket.py) 的做法已经是正确方向：

- 每个 individual 只拿一个 `base_port_number`
- 再按节点数推导出：
  - `base_port_peer`
  - `base_port_ws`
  - `base_port_ws_admin`
  - `base_port_rpc`
  - `grpc_port`

这说明“单任务内部的端口布局”已经是稳定的。

### 6.2 需要改进的地方

当前端口基址分配散落在 [evotest_parallel.py](/data/home/lli21/rocket/evo/evotest_parallel.py) 内部，公式是：

- `offset_index = generation * population_size + idx`
- `base_port_number = base_pop + offset_index * ports_per_test`

这个公式在“单组合串行推进”时可以工作，但如果未来不同组合共享全局任务池，就不够用了，因为不同组合也会抢同一端口区间。

### 6.3 新方案

新增 `port_allocator.py`，统一管理端口。

建议规则：

1. 每个任务只向 allocator 申请一个“端口块”
2. 端口块大小固定为：

```text
ports_per_task = 1 + number_of_nodes * 4
```

3. allocator 维护：

- `port_start`
- `port_end`
- `allocated_blocks`
- `free_blocks`

4. 调度器在真正启动 task 前分配端口块
5. task 完成后释放端口块

这样比“按 generation/idx 静态公式算端口”更稳，因为它能支持：

- 不同组合交错执行
- 失败重试
- task 提前结束后归还端口

### 6.4 为什么不建议继续纯静态公式

静态公式适合“已知顺序、线性执行”的场景。  
而你未来要的是：

- 多个组合同时活跃
- 某些任务完成快、某些任务完成慢
- 全局池动态补位

这时动态端口 allocator 更自然。

### 6.5 cluster_id 隔离

除了端口，容器名也要隔离。

继续沿用当前 `cluster_id` 设计，但建议格式更明确：

```text
<experiment_id>_G<generation>T<individual_id>
```

例如：

```text
img2_6_0_bug0__EvoDelayStrategy__mean_validation_time_G1T7
```

然后继续通过 `sanitize_cluster_id` 变成 docker-safe 名称。

---

## 7. 任务提交和 generation 控制

这是整个方案里最关键的部分。

### 7.1 每个组合内部的规则

对于单个 `ExperimentRunner`：

- 初始化时只生成 `G0` 的任务
- `G0` 的全部 individual 可以并行
- 只有 `G0` 的全部结果都回来了，才能：
  - 计算 fitness
  - 更新 hall of fame
  - 做 selection
  - 做 crossover / mutation
  - 生成 `G1`
- `G1` 提交后，同理等待全部完成后再生成 `G2`

这就是“组合内 generation barrier”。

### 7.2 不同组合之间的关系

不同组合之间没有代际依赖。

所以允许：

- 组合 A 在跑 `G1`
- 同时组合 B 在跑 `G0`
- 同时组合 C 在跑 `G3`

只要每个组合各自遵守自己的 generation barrier 即可。

### 7.3 调度器如何与 runner 配合

建议接口设计如下。

`ExperimentRunner` 提供：

- `get_ready_tasks() -> list[EvaluationTask]`
- `on_task_finished(result: TaskResult) -> None`
- `is_done() -> bool`

语义：

- `get_ready_tasks()` 只返回“当前 generation 中还没被提交的合法任务”
- `on_task_finished(...)` 更新本组合状态
- 如果这一代全完成，则内部推进到下一代，并把下一代任务置为 ready

`GlobalScheduler` 提供：

- `run(runners: list[ExperimentRunner], max_concurrent_tasks: int)`

内部逻辑：

1. 轮询所有 runner 的 `get_ready_tasks()`
2. 把 ready task 放进全局 ready queue
3. 当运行中任务数 `< max_concurrent_tasks` 时，从 queue 里取任务启动
4. 某个任务完成后，把结果回传给对应 runner
5. 某个 runner 如果因此解锁了下一代，再把新任务放进 queue
6. 所有 runner 都 `is_done()` 后退出

### 7.4 调度公平性

不建议 scheduler 永远优先一个组合，不然会出现某些组合长期饥饿。

建议先用简单的 round-robin：

- 按 runner 顺序轮流从每个 runner 拿一个 ready task
- 放入全局队列

这个策略简单、直观，而且足够应对当前场景。

---

## 8. 单任务执行方式

建议保持“一个 task 对应一个 subprocess 执行一次 `run_rocket_and_evaluate(...)`”。

### 8.1 为什么不建议直接在线程里执行所有逻辑

虽然技术上可行，但当前 `run_rocket_and_evaluate(...)` 涉及：

- 子进程
- Docker 容器
- 临时 YAML 文件
- 清理逻辑
- 日志重定向

用独立 subprocess 或 worker process 执行更稳，也更容易在异常时清理。

### 8.2 推荐实现

新增 `evaluate_worker.py`：

- 输入：一个 `EvaluationTask`
- 调用 `run_rocket_and_evaluate(...)`
- 输出：`TaskResult`

`GlobalScheduler` 只负责任务生命周期，不理解 GA 细节。

---

## 9. 配置收敛建议

当前有两个并发控制参数：

- `parallel_mode`
- `max_parallel_workers`

建议未来收敛成一个主参数：

```yaml
max_concurrent_tasks: 4
```

并将下面两个字段逐步废弃：

- `parallel_mode`
- `max_parallel_workers`

保留兼容期时建议：

- 如果检测到旧字段存在，打印 warning
- 但最终真实并发只由 `max_concurrent_tasks` 决定

---

## 10. 建议的分阶段实施步骤

下面给出一个务实的迁移方案，避免一次改太大。

### 第 1 步：明确“单任务边界”

目标：

- 确认 `run_rocket_and_evaluate(...)` 是唯一的 individual 执行入口

操作：

1. 保持 [run_rocket.py](/data/home/lli21/rocket/evo/run_rocket.py) 不做大改
2. 新建 `task_types.py`
3. 定义：
   - `EvaluationTask`
   - `TaskResult`

验收标准：

- 可以把一次 individual 评估的所有输入输出用 dataclass 表达清楚

### 第 2 步：抽出 `ExperimentRunner`

目标：

- 把 GA 逻辑从 `evotest_parallel.py` 中抽出来

操作：

1. 新建 `experiment_runner.py`
2. 把下面这些逻辑迁进去：
   - 初始化 population
   - generation loop
   - `varOr`
   - selection
   - hall of fame
   - logbook
3. 删除 runner 内部直接使用 `ProcessPoolExecutor` 的逻辑

验收标准：

- runner 能在不执行任务的前提下生成一代 tasks
- runner 能在收到一整代结果后推进到下一代

### 第 3 步：实现全局 scheduler

目标：

- 统一控制并发数

操作：

1. 新建 `scheduler.py`
2. 先实现最小版：
   - 维护 `ready_queue`
   - 维护 `running_tasks`
   - 维护 `max_concurrent_tasks`
3. 暂时先串行轮询 runners
4. 用 round-robin 从多个 runner 取 ready task

验收标准：

- 无论有多少组合，同时运行任务数都不超过 `N`

### 第 4 步：实现动态端口分配器

目标：

- 支持多个组合共享全局并发时的端口隔离

操作：

1. 新建 `port_allocator.py`
2. 支持：
   - `allocate() -> base_port_number`
   - `release(base_port_number)`
3. scheduler 在任务启动前分配端口，任务结束后释放端口

验收标准：

- 不同组合同时运行时，不会出现端口重叠

### 第 5 步：让 `run_evotests.py` 接管总调度

目标：

- 顶层入口只做一件事：创建 runners + 启动 scheduler

操作：

1. 读取 YAML
2. 展开所有组合
3. 为每个组合生成唯一 `experiment_id`
4. 构造 `ExperimentRunner`
5. 把所有 runner 交给 `GlobalScheduler`

验收标准：

- `run_evotests.py` 不再自己启动多个 `evotest_parallel.py` 子进程

### 第 6 步：保留兼容层

目标：

- 让旧脚本暂时还能跑

操作：

1. [evotest_parallel.py](/data/home/lli21/rocket/evo/evotest_parallel.py) 暂时保留，但内部改为调用新 runner/scheduler 逻辑，或只保留为兼容入口
2. 在 README / 文档中注明新入口是 `run_evotests.py`

验收标准：

- 旧脚本不阻塞新架构推进

---

## 11. 推荐的运行时执行流程

未来推荐的执行链如下：

1. `run_evotests.py` 读取 `run_evotests.yaml`
2. 展开所有 `image × strategy × fitness × encoding`
3. 为每个组合创建一个 `ExperimentRunner`
4. 创建一个 `GlobalScheduler(max_concurrent_tasks=N)`
5. scheduler 从所有 runner 收集 ready tasks
6. scheduler 取 task，分配端口块，启动 worker
7. worker 调用 `run_rocket_and_evaluate(...)`
8. worker 完成后返回 `TaskResult`
9. scheduler 将结果回传给对应 runner
10. runner 若本代完成，则推进到下一代并释放新任务
11. 所有 runner 完成后退出

---

## 12. 为什么这个方案适合当前项目

这个方案尽量复用了当前代码里已经做对的部分：

- `run_rocket.py` 的单任务执行边界
- `cluster_id` 的隔离思路
- `test_log_dir / GxTy` 的日志组织方式
- 基于 network YAML 动态改端口的机制

真正改变的是：

- 去掉两层并行
- 把 individual 评估并发收口到一处
- 保留 GA 逻辑，但把调度权从 `evotest_parallel.py` 内部抽出来

这样能最大限度减少重写成本，同时解决当前最核心的并发失控问题。

---

## 13. 结论

建议采用的最终模型是：

- 每个配置组合对应一个 `ExperimentRunner`
- 每个 runner 内部维护自己的 GA 状态和 generation barrier
- 所有 runner 共享一个 `GlobalScheduler`
- 全局并发只由 `max_concurrent_tasks` 控制
- 端口由统一 `PortAllocator` 分配
- 单任务执行继续复用 `run_rocket_and_evaluate(...)`

一句话概括：

“组合之间可并行，组合内部代际串行推进，individual 评估统一进入一个全局限流任务池。”
