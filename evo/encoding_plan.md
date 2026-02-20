# Encoding 设计与实现计划

目标：
- 使不同的 `encoding` 子类（构造参数可能不同、内部有分段 segment）能够统一接入 DEAP。
- 支持按段（segment）进行 crossover / mutation / repair。
- 从配置（`evotest.yaml` 的 `strategy` 或 `encoding.type`）动态选择 encoding 类。
- 保持向后兼容：现有扁平 delay-list 行为不变直至切换完成。

高层设计结论（设计模式）
- Factory：从 `strategy`（或显式 `encoding.type`）映射到具体 `Encoding` 类。
- Template（BaseEncoding）：定义统一的 class/instance API（gene_length、random_genes、from_genes、to_genes、segment_specs、mate_genes、mutate_genes、repair、validate）。
- Adapter（DEAP adapter）：在 `evotest_parallel` 中使用 wrapper（create_individual/mate/mutate），这些 wrapper 调用 encoding 的 class-methods/instance-methods，使 DEAP 仍以 list-like `Individual` 工作。

为什么这样做？
- 将实现细节封装在 encoding 子类内部，EA 层无需了解构造参数或内部段结构。
- class-level factory 接口解决“构造函数参数不同”的问题（EA 调用 class-method，不直接实例化复杂构造）。
- Segment 支持使得跨段操作（例如 delays 段用 SBX、byzz 段用 categorical mutation）成为可能。

逐步实现计划（按优先级与可回滚性）

1) 设计并实现统一的 BaseEncoding API（`evo/encodings.py`）
   - 内容：定义必需的 class/instance 方法签名与行为契约（见“API 规范”节）。
   - 原因：建立统一契约，便于所有子类适配。
   - 验证：为现有 `RandomDelayEncoding` 实现并写单元测试（长度、范围、round-trip）。
   - 估时：0.5–1 天。

2) 增加 Segment 支持与工具（`SegmentSpec`）
   - 内容：允许 encoding 声明若干段（name、length、dtype、bounds、cx_method、mut_method、params），并提供 offset 计算工具。
   - 原因：按段应用不同遗传算子，支持混合类型（数值 + categorical）。
   - 验证：segment offset 与段级算子调用的单元测试。
   - 估时：0.5 天。

3) 扩展/实现具体 Encoding 子类（示例：`RandomDelayEncoding` 与 `EvoByzzDelayEncoding`）
   - 要求实现的接口：
     - classmethod `gene_length(num_nodes, config=None)`
     - classmethod `random_genes(num_nodes, min_value, max_value, config=None)`
     - classmethod `from_genes(genes, num_nodes, min_value, max_value, config=None)`
     - `to_genes()`、`repair()`、可选 `segment_specs()`、`mate_genes()`、`mutate_genes()` 等
   - 示例：`EvoByzzDelayEncoding` 包含两段 — delays（数值、SBX/gaussian）和 byzz-behavior（categorical、uniform/choice mutation）。
   - 验证：分段交叉/变异 & repair 的单元测试。
   - 估时：1–2 天。

4) 在 `evotest_parallel.py` 中接入 Factory + Adapter（最小改动、安全回退）
   - 改动点：
     - 从 `configs.config["strategy"]`（或 `encoding.type`）选取 `encoding_cls`
     - 使用 `encoding_cls.gene_length(...)` 计算 encoding_len（fallback 为 legacy 公式）
     - 修改 `create_individual`：调用 `encoding_cls.random_genes(...)`（若可用）
     - 提供 `encoding_mate_wrapper` / `encoding_mutate_wrapper`：调用 `encoding_cls.mate_genes` / `mutate_genes`，并确保类型/范围/repair
     - 在 worker（运行实例与写 YAML）内通过 `encoding_cls.from_genes(...)` 重建 encoding 实例并序列化（`to_genes()`）
   - 原因：EA 层最小侵入；保持 `creator.Individual` 仍为 list（DEAP 兼容）。
   - 验证：回归测试（与旧实现行为对比）、确认 worker 中 YAML 正确写入 encoding
   - 估时：1 天（实现 + 测试）。

5) 配置支持与文档
   - 新增 `encoding` 配置段（可选）：
     - `encoding.type`（覆盖由 `strategy` 推断）
     - `encoding.params`（传递给 encoding 的额外参数）
   - 更新 `configs.py` 与 README/docs
   - 验证：在 `evotest.yaml` 添加示例配置并本地运行
   - 估时：0.5 天。

6) 测试矩阵（单元 + 集成）
   - 单元：API 函数（gene_length/random_genes/from_genes/to_genes/repair）与 segment 操作
   - 集成：小规模运行 `evotest_parallel`（1–2 代、少量个体）保证 DEAP 流程可运行、worker 能重建 encoding
   - CI：新增 `tests/test_encodings.py`、`tests/test_evotest_parallel_encoding_integration.py`
   - 估时：1–2 天。

7) 逐步替换与回滚策略
   - 先实现 BaseEncoding 与使 `RandomDelayEncoding` 满足新 API（不更改默认行为）。
   - 在 `evotest_parallel` 中以 feature-flag 或配置方式逐步启用新机制。
   - 回滚：恢复 `create_individual` 与原有 operator 即可。


API 规范（BaseEncoding 的最小契约）
- @classmethod gene_length(num_nodes: int, config: dict | None = None) -> int
- @classmethod random_genes(num_nodes: int, min_value: int, max_value: int, config: dict | None = None) -> list[int]
- @classmethod from_genes(genes: list[int], num_nodes: int, min_value: int, max_value: int, config: dict | None = None) -> BaseEncoding
- def to_genes(self) -> list[int]
- def repair(self) -> None  # 修正越界或类型问题
- def validate(self) -> bool | None  # 可选，抛错或返回 False 表示非法
- @classmethod segment_specs(num_nodes, config=None) -> list[SegmentSpec]  # 可选，用于分段算子
- @classmethod mate_genes(genes1, genes2, rng=None, **kwargs) -> (genes1', genes2')  # 可选（默认按段交叉）
- @classmethod mutate_genes(genes, rng=None, **kwargs) -> genes'  # 可选（默认按段变异）

说明：EA 层只与上述 API 交互，不直接构造复杂对象。encoding 子类内部可有任意构造参数。

DEAP Adapter（如何接入）
- create_individual(...) 调用 `encoding_cls.random_genes(...)` → 返回 `creator.Individual(genes)`
- toolbox.register("mate", encoding_mate_wrapper)
  - wrapper: 调用 `encoding_cls.mate_genes(list(ind1), list(ind2), rng=...)` → 将返回的 gene-list 写回 ind1/ind2 → 调用 `repair()`（或调用 `encoding_cls.from_genes(...).repair()`）
- toolbox.register("mutate", encoding_mutate_wrapper)
  - wrapper: 调用 `encoding_cls.mutate_genes(list(ind), rng=..., indpb=...)` → 写回并返回 `(ind,)`

分段（segment）模型示例
- SegmentSpec = { name, length, dtype, bounds, cx_method, mut_method, params }
- 例：`EvoByzzDelayEncoding`
  - 段 A（delays）：length = n*(n-1)*7，dtype=int，bounds=[min,max]，cx=SBX，mut=Gaussian
  - 段 B（byzz-behavior）：length = M（如每拜占庭节点一个码），dtype=categorical，cx=uniform，mut=choice
  - 交叉/变异先按段应用对应算子，最后 `repair()` 做一致性/类型修正

配置改动建议（`evotest.yaml`）
- 新增（可选）：
  encoding:
    type: EvoByzzDelayEncoding  # 可选，默认由 strategy 推断
    params:
      byzz_behavior_choices: [do_nothing, flip_sig, replace_tx]
      some_other_param: 42

向后兼容策略
- 如果 Factory 无法找到 encoding 类（mapping 返回 None），使用现有的 flat delay-list 行为。
- 保持 `creator.Individual` 为 list 以满足 DEAP；encoding 仅在需要时重建为对象用于 repair/segment 操作。

注意事项 / 陷阱
- ProcessPoolExecutor 要求可 pickled 的任务参数 — 不要把复杂对象直接放在 Individual 上；在 worker 内重建 encoding（使用 from_genes）。
- DEAP 算子返回值必须遵循 DEAP 约定（mate 返回 (ind1, ind2)，mutate 返回 (ind,)）。
- 数值段在交叉后可能是 float，需要在 wrapper 或 encoding.repair 中强制为 int 并 clamp。

交付物
- `evo/encodings.py`: BaseEncoding、SegmentSpec、RandomDelayEncoding（更新）、示例 EvoByzzDelayEncoding、factory 映射。 
- `evo/evotest_parallel.py`: factory 接入、create_individual 更新、DEAP wrapper operators、worker 内重新构建 encoding 并序列化。 
- `evotest.yaml` & `configs.py`: 可选 `encoding.params` 支持与示例。 
- Tests: `tests/test_encodings.py`、`tests/test_evotest_parallel_encoding_integration.py`。

实现优先级（最小安全增量）
1. BaseEncoding + RandomDelayEncoding 完整 API（保证旧行为）
2. evotest_parallel 中的 factory 查询 + create_individual 使用 class API（fallback 保留旧行为）
3. DEAP wrapper operators（mate/mutate）
4. 实现 EvoByzzDelayEncoding（分段示例）并补充 tests
5. 文档与配置示例

验收标准
- 不改变默认配置时，`evotest_parallel` 运行结果与此前一致（回归通过）。
- 新 encoding 类能被配置并运行；分段交叉/变异按设计生效。
- 单元与集成测试覆盖新增逻辑且通过。

下一步（你选一个）
- 我现在开始实现第 1 步（在 `evo/encodings.py` 添加 BaseEncoding 并把 `RandomDelayEncoding` 对齐），并在 `evotest_parallel.py` 做最小接入（feature-flag 可回退）。
- 或者我先把 API 草稿（interface）贴到这里供你复核。

请选择：我现在开始实现，还是先把接口草稿贴出来供你确认？
