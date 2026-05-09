# Analysis 模块重写计划

## 1. 目标

新的 `analysis` 模块只做一件事：把日志目录上的不同层级分析统一起来，同时保持接口非常简单。

核心原则：

1. 默认只跑 group-level 分析。
2. case-level 分析只在显式要求时才运行。
3. 每个 case-level 分析模块彼此独立，不共享中间数据。
4. 新增一个分析模块时，只需要实现一个 `func(path: Path) -> list[Path]` 函数。
5. 然后把它注册到分析注册表中即可。


## 2. 层级系统

日志目录采用下面的层级：

```text
logs/<date>/<image>/<encoding>/<fitness>/GxTy
```

在分析模块中，固定为五个层级：

1. `DATE`
2. `IMAGE`
3. `ENCODING`
4. `FITNESS`
5. `CASE`

设计原则：

1. 每个 analyzer 只属于一个层级。
2. 用户提供一个路径后，系统先判断这个路径属于哪个层级。
3. 然后比较“输入路径层级”和“analyzer 所属层级”。


## 3. 层级分发规则

对于某个 analyzer：

### 3.1 输入层级与 analyzer 层级相同

直接在该路径上运行一次。

### 3.2 输入层级高于 analyzer 层级

说明输入路径太粗，需要向下展开。

例如：

- 输入 `ENCODING`
- analyzer 是 `FITNESS`

那么系统自动找到这个 encoding 下所有 fitness 目录，并对每个 fitness 跑一次这个 analyzer。

再例如：

- 输入 `ENCODING`
- analyzer 是 `CASE`

那么系统自动找到这个 encoding 下所有 testcase，并逐个运行。

### 3.3 输入层级低于 analyzer 层级

说明输入路径太细。

例如：

- 输入 `CASE`
- analyzer 是 `ENCODING`

这种情况不允许直接运行，应该报错。


## 4. 目录结构

建议新的 `analysis` 模块结构如下：

```text
evo/analysis/
  __init__.py
  levels.py
  cases.py
  utils.py
  group_plot.py
  registry.py
  case_runner.py
  cli.py
  plot.py
  plan.md
```

各文件职责：

1. `levels.py`
   定义层级枚举。
2. `cases.py`
   负责路径层级识别、case 查找、最新 run 查找、日志子目录查找。
3. `utils.py`
   放通用工具，例如运行子进程、清理中间文件、LaTeX 转 PDF。
4. `group_plot.py`
   负责 group-level 分析，例如：
   - `evolution_report`
   - `fitness_trend_report`
5. `registry.py`
   定义 analyzer 数据结构和注册表。
6. `case_runner.py`
   负责 case-level analyzer 执行和 `analysis_index.json` 维护。
7. `cli.py`
   负责统一命令行入口。
8. `plot.py`
   作为兼容入口，给旧的 `evo/plot_fitness_trend.py` 使用。


## 5. analyzer 接口

每个 analyzer 都遵守同一个接口：

```python
def analyzer_name(path: Path) -> list[Path]:
    ...
```

要求：

1. 输入只有一个 `Path`
2. 输出是“生成的正式产物路径列表”
3. 不返回临时文件路径
4. 不依赖其他 analyzer 的输出


## 6. 注册表设计

建议统一用一个简单的注册表。

```python
@dataclass(frozen=True)
class Analyzer:
    name: str
    level: Level
    description: str
    run: Callable[[Path], list[Path]]
```

然后注册：

```python
ANALYZERS = {
    "fitness_trend_report": Analyzer(...),
    "evolution_report": Analyzer(...),
    "saved_run_timeline": Analyzer(...),
    "validation_matrix": Analyzer(...),
}
```


## 7. group-level 与 case-level 模块

### 7.1 group-level 模块

目前建议有两个：

1. `fitness_trend_report`
   - 层级：`ENCODING`
   - 输出：`_fitness_trend_report.pdf`

2. `evolution_report`
   - 层级：`FITNESS`
   - 输出：`_evolution_report.pdf`

注意：

不要把这两个东西混成一个 analyzer。
它们属于不同层级。


### 7.2 case-level 模块

目前建议保留：

1. `saved_run_timeline`
2. `close_time_causality`
3. `onaccept_table`
4. `preferred_trie`
5. `validation_matrix`
6. `proposal_timeline`


## 8. 输出目录规范

### 8.1 group-level 输出

仍然放在原有层级目录中：

- fitness 层输出 `_evolution_report.pdf`
- encoding 层输出 `_fitness_trend_report.pdf`

### 8.2 case-level 输出

统一放在：

```text
GxTy/analysis/
```

例如：

```text
G0T6/
  analysis/
    analysis_index.json
    saved_run_timeline.json
    saved_run_timeline.md
    close_time_causality.txt
    validation_matrix.json
    validation_matrix.csv
    validation_matrix.pdf
```


## 9. PDF 与中间文件清理

凡是生成 PDF 的 analyzer，都要负责清理中间文件。

至少清理：

1. `.tex`
2. `.aux`
3. `.log`
4. `.out`
5. `.fls`
6. `.fdb_latexmk`

原则：

1. 用户只应该看到正式产物。
2. 临时文件不要留在日志目录里。


## 10. CLI 设计

### 10.1 默认行为

```bash
./docker/plot.sh
./docker/plot.sh /path/to/date
./docker/plot.sh /path/to/image
./docker/plot.sh /path/to/encoding
./docker/plot.sh /path/to/fitness
```

默认只跑 group-level 分析。

### 10.2 运行全部 case-level 模块

```bash
./docker/plot.sh /path/to/G0T6 -v
./docker/plot.sh /path/to/encoding -v
```

语义：

1. `-v` 表示运行全部 case-level 模块
2. 如果输入是单个 testcase，就只分析这个 case
3. 如果输入是更高层级，就自动展开到所有 case

### 10.3 运行一个或多个指定模块

```bash
./docker/plot.sh /path/to/G0T6 -a validation_matrix
./docker/plot.sh /path/to/G0T6 -a validation_matrix -a proposal_timeline
./docker/plot.sh /path/to/encoding -a validation_matrix
./docker/plot.sh /path/to/encoding -a fitness_trend_report
```

语义：

1. `-a` 可重复出现
2. 每个 `-a` 指定一个 analyzer
3. 系统根据 analyzer 的 level 自动决定是否向下展开

### 10.4 列出所有 analyzer

```bash
./docker/plot.sh --list-analyzers
```

输出内容包括：

1. analyzer 名称
2. analyzer 层级
3. 一句话说明

### 10.5 debug

```bash
./docker/plot.sh /path/to/G0T6 --debug
./docker/plot.sh /path/to/G0T6 --debug -a validation_matrix
```

作用：

1. 查看 `analysis_index.json`
2. 查看产物路径
3. 查看错误信息


## 11. 参数冲突规则

建议固定一条规则：

1. `-v` 和 `-a` 不能同时使用

原因：

- `-v` 表示“全部 case-level 模块”
- `-a` 表示“指定模块”

同时出现会造成语义冲突，直接报错更清楚。


## 12. 新增模块的步骤

以后新增一个 analyzer，按下面步骤操作：

1. 写一个函数：

```python
def my_analyzer(path: Path) -> list[Path]:
    ...
```

2. 明确这个 analyzer 的层级：

```python
level=Level.CASE
```

3. 把正式产物写到正确目录：

- group-level：对应层级目录
- case-level：`case/analysis/`

4. 清理所有临时文件

5. 在注册表中注册：

```python
ANALYZERS["my_analyzer"] = Analyzer(
    name="my_analyzer",
    level=Level.CASE,
    description="...",
    run=my_analyzer,
)
```


## 13. 推荐重写顺序

### 第一步

先把目录骨架和 `Level` 系统搭起来。

### 第二步

实现路径层级识别与向下展开逻辑。

### 第三步

接入两个 group-level 模块：

1. `fitness_trend_report`
2. `evolution_report`

### 第四步

接入 case-level 模块：

1. `saved_run_timeline`
2. `close_time_causality`
3. `onaccept_table`
4. `preferred_trie`
5. `validation_matrix`
6. `proposal_timeline`

### 第五步

实现 CLI：

1. 默认 group-level
2. `-v`
3. `-a`
4. `--list-analyzers`
5. `--debug`

### 第六步

验证输出目录、PDF 清理、单 case 分析入口是否都符合预期。


## 14. 最终预期使用方式

```bash
# 默认：最新 run，只跑 group-level
./docker/plot.sh

# 指定 encoding，只跑 group-level
./docker/plot.sh /data/workspace/.../encoding_dir

# 指定单个 case，跑全部 case-level
./docker/plot.sh /data/workspace/.../G0T6 -v

# 指定单个 case，跑一个模块
./docker/plot.sh /data/workspace/.../G0T6 -a validation_matrix

# 指定单个 case，跑多个模块
./docker/plot.sh /data/workspace/.../G0T6 -a validation_matrix -a proposal_timeline

# 指定 encoding，跑所有 case 的某个模块
./docker/plot.sh /data/workspace/.../encoding_dir -a validation_matrix

# 列出模块
./docker/plot.sh --list-analyzers
```


## 15. 总结

这个重写方案的重点不是把架构做复杂，而是把下面几件事彻底固定下来：

1. 分析器有明确层级
2. 默认只跑 group-level
3. case-level 必须显式要求
4. analyzer 之间独立
5. 新模块只需要实现一个 `Path -> outputs` 函数并注册
6. 输出路径统一
7. 中间文件自动清理

只要这几个规则稳定，后面继续加分析模块时，维护成本会很低。
