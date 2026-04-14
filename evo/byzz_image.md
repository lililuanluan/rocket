# Byzz Image Mixed Deployment Plan

## Goal

当前 `rocket` / `run_evotests` 的实现只能让一个实验实例中的所有 validator 节点使用同一张 `rippled` 镜像。

这份文档的目标是先把“不同节点运行不同镜像”的设计方案写清楚，后续再按方案改代码。本文档只描述方案，不修改业务代码。

目标能力：

- 同一个 cluster 内，不同节点可以使用不同的 `rippled` Docker image。
- 默认情况下仍然支持“所有节点同镜像”的旧行为。
- 优先支持常见场景：
  - honest 节点使用稳定镜像
  - byzantine 节点使用 bug-injected 镜像
- 对 `run_evotests.py` / `evotest_parallel.py` 的现有实验组织方式尽量保持兼容。

## Current Implementation

当前镜像选择链路是单值传递：

1. `evo/run_evotests.py`
   - 从 `run_evotests.yaml` 读取 `ripple_images`
   - 每个实验组合只选出一个 `img`
   - 通过命令行传给 `evo.evotest_parallel`：

```python
cmd = [
    sys.executable,
    "-m",
    "evo.evotest_parallel",
    "--ripple-image",
    img,
    ...
]
```

2. `evo/evotest_parallel.py`
   - 从 config 中读取单个 `ripple_image`
   - 调 `run_rocket_and_evaluate(..., ripple_image=config.get("ripple_image", ""))`

3. `evo/run_rocket.py`
   - 启动 controller 时传一个 `--rippled-img`

```python
cmd = [
    py,
    "-m",
    "rocket_controller",
    strategy_name,
    ...
    "--rippled-img",
    str(ripple_image),
]
```

4. `rocket_controller`
   - `cli_helper.py` 只接收一个 `--rippled-img`
   - `InterceptorManager.start_new()` 只设置一个环境变量：

```python
process_env["RIPPLE_IMAGE"] = self.rippled_img
```

5. `rocket_interceptor/src/docker_manager.rs`
   - `get_image_from_env()` 只返回一个镜像
   - `download_image()` 只检查/拉取一个镜像
   - `start_validator()` 启动每个 validator 时都使用同一个镜像

所以当前行为本质上是：

- 一个实验实例 = 一个 `RIPPLE_IMAGE`
- 一个 `RIPPLE_IMAGE` = 该实例内所有 validator 共用

## Recommended Design

推荐采用：

- `default_ripple_image`
- `node_image_overrides`

而不是仅仅传一个“节点镜像数组”。

推荐数据模型：

```yaml
default_ripple_image: xrpld:2.6.0-local
node_image_overrides:
  3: xrpld:2.6.0-bug5-local
  5: xrpld:1.7.2-local
```

语义：

- 所有节点默认使用 `default_ripple_image`
- 如果某个节点 id 出现在 `node_image_overrides` 中，则该节点使用 override 镜像

这样做的优点：

- 大多数节点同镜像时配置很简洁
- “只让 byzz 节点换镜像”非常自然
- 对现有单镜像流程兼容性最好
- Rust 侧实现简单，不需要每次都传完整数组

## Where To Put The Configuration

推荐把 mixed-image 配置放到 network config 中，也就是 `evo/network.yaml` 对应的那一层，而不是继续塞在 `run_evotests.yaml` 的 `ripple_images` 中。

原因：

- “节点拓扑 + 节点身份 + byzz 节点”本来就属于 network 语义
- `node_image_overrides` 和 `byzz_nodes` 紧密相关
- `run_evotests.yaml` 当前更像“实验 sweep 配置”，适合定义实验组合，不适合定义单个 network 内部节点角色

推荐最终结构：

```yaml
# evo/network.yaml
number_of_nodes: 7
byzz_nodes: [3]

default_ripple_image: xrpld:2.6.0-local
node_image_overrides:
  3: xrpld:2.6.0-bug5-local
```

## Compatibility Strategy

建议保持以下兼容顺序：

1. 如果 network config 中有 `node_image_overrides` 或 `default_ripple_image`
   - 使用 mixed-image 模式
2. 否则如果外层仍然传了旧的单值 `--rippled-img`
   - 所有节点沿用该镜像
3. 如果两者都没有
   - fallback 到 Rust 中当前的默认值 `xrpllabsofficial/xrpld:2.3.0`

这样可以做到：

- 旧实验脚本不必立刻全部改掉
- 新实验可以逐步切换到 mixed-image 配置

## Transport Choice

这里有两个实现路径。

### Option A: Quick Patch Via Environment Variable

做法：

- Python 侧把 `node_image_overrides` 序列化成 JSON
- 通过环境变量传给 interceptor
- Rust 启动节点时解析该 JSON

例如：

```python
process_env["RIPPLE_IMAGE"] = self.rippled_img
process_env["ROCKET_NODE_IMAGE_OVERRIDES"] = json.dumps({"3": "xrpld:2.6.0-bug5-local"})
process_env["ROCKET_DEFAULT_RIPPLE_IMAGE"] = "xrpld:2.6.0-local"
```

优点：

- 改动少
- 不需要改 proto

缺点：

- mixed-image 变成“隐式环境协议”，不如 gRPC config 干净
- 配置源头分散
- 后续维护成本更高

### Option B: Clean Design Via `packet.proto`

做法：

- 扩展 `protos/packet.proto` 中的 `Config`
- controller 在 `get_config()` 中把 image 配置发给 interceptor
- interceptor 直接从 config 中拿节点镜像信息

优点：

- 配置来源单一
- 语义清晰
- 更容易调试和扩展

缺点：

- 需要改 proto，并重新生成 Python / Rust 代码

推荐选择：`Option B`

## Detailed Change Plan

下面按文件给出建议改法。

### 1. `evo/network.yaml`

新增字段：

```yaml
default_ripple_image: xrpld:2.6.0-local
node_image_overrides:
  3: xrpld:2.6.0-bug5-local
```

说明：

- `default_ripple_image` 可选
- `node_image_overrides` 可选
- `node_image_overrides` 的 key 是节点 id
- `node_image_overrides` 的 value 是 Docker image tag

建议增加注释，明确：

- 若某节点未出现在 override 中，则使用默认镜像
- override 中的 node id 必须在 `[0, number_of_nodes - 1]` 范围内

### 2. `protos/packet.proto`

当前 `Config` 是：

```proto
message Config {
    uint32 base_port_peer = 1;
    uint32 base_port_ws = 2;
    uint32 base_port_ws_admin = 3;
    uint32 base_port_rpc = 4;
    uint32 number_of_nodes = 5;
    repeated Partition net_partitions = 6;
    repeated Partition unl_partitions = 7;
}
```

建议扩展为：

```proto
message NodeImageOverride {
    uint32 node_id = 1;
    string image = 2;
}

message Config {
    uint32 base_port_peer = 1;
    uint32 base_port_ws = 2;
    uint32 base_port_ws_admin = 3;
    uint32 base_port_rpc = 4;
    uint32 number_of_nodes = 5;
    repeated Partition net_partitions = 6;
    repeated Partition unl_partitions = 7;

    string default_ripple_image = 8;
    repeated NodeImageOverride node_image_overrides = 9;
}
```

不建议直接在 proto 中用 `map<uint32, string>`，因为：

- 这里的 override 本身是配置项列表
- `repeated message` 在跨语言调试和日志打印时更直观
- 以后要给 override 扩字段时更自然

### 3. Regenerate Proto Outputs

修改 `packet.proto` 后，需要更新：

- `protos/packet_pb2.py`
- `protos/packet_pb2.pyi`
- Rust `tonic::include_proto!("packet")` 所依赖的生成结果

这里不在本方案里具体展开生成命令，但实际实施时必须紧跟在 proto 修改之后完成。

### 4. `rocket_controller/packet_server.py`

当前 `get_config()` 只返回端口、节点数、partition 信息。

需要在 `config_values_types` 之后，额外读取 network config 中的：

- `default_ripple_image`
- `node_image_overrides`

建议处理逻辑：

1. `default_ripple_image = config.get("default_ripple_image", "")`
2. `node_image_overrides = config.get("node_image_overrides", {}) or {}`
3. 校验：
   - 必须是 dict
   - key 可转成 int
   - `0 <= node_id < number_of_nodes`
   - value 必须是非空 string
4. 转成 proto `NodeImageOverride`

建议最终返回形态：

```python
return packet_pb2.Config(
    base_port_peer=config.get("base_port_peer"),
    base_port_ws=config.get("base_port_ws"),
    base_port_ws_admin=config.get("base_port_ws_admin"),
    base_port_rpc=config.get("base_port_rpc"),
    number_of_nodes=config.get("number_of_nodes"),
    net_partitions=net_partitions,
    unl_partitions=unl_partitions,
    default_ripple_image=default_ripple_image,
    node_image_overrides=[
        packet_pb2.NodeImageOverride(node_id=node_id, image=image)
        for node_id, image in sorted(parsed_overrides.items())
    ],
)
```

### 5. `rocket_interceptor/src/docker_manager.rs`

这是核心改动点。

#### 5.1 新增解析函数

新增辅助函数，建议签名：

```rust
fn get_default_image_from_config(&self) -> Option<String>
fn get_node_image_overrides(&self) -> HashMap<u32, String>
fn get_image_for_node(&self, node_id: u32) -> String
fn get_all_images_for_run(&self) -> Vec<String>
```

推荐逻辑：

```rust
fn get_default_image_from_config(&self) -> Option<String> {
    let img = self.config.default_ripple_image.clone();
    if img.trim().is_empty() {
        None
    } else {
        Some(img)
    }
}

fn get_node_image_overrides(&self) -> HashMap<u32, String> {
    self.config
        .node_image_overrides
        .iter()
        .map(|entry| (entry.node_id, entry.image.clone()))
        .collect()
}

fn get_image_for_node(&self, node_id: u32) -> String {
    if let Some(img) = self.get_node_image_overrides().get(&node_id) {
        return img.clone();
    }
    if let Some(img) = self.get_default_image_from_config() {
        return img;
    }
    self.get_image_from_env()
}
```

这里保留现有 `get_image_from_env()`，但它退化为 fallback。

#### 5.2 修改 `download_image()`

当前只处理一个镜像：

```rust
let image = self.get_image_from_env();
```

建议改成：

```rust
let images = self.get_all_images_for_run();
for image in images {
    // 对每个唯一镜像执行 existing-or-pull 逻辑
}
```

`get_all_images_for_run()` 的语义：

- 收集 default image
- 收集所有 override image
- 如果都没有，再加 env image fallback
- 去重

这样一个实验启动前会确保所有需要的镜像都存在。

#### 5.3 修改 `initialize_network()`

当前：

```rust
for (i, (name, keys)) in names_with_keys.iter().enumerate() {
    let mut validator_container = DockerContainer { ... };
    self.start_validator(&mut validator_container).await;
}
```

建议改成：

```rust
for (i, (name, keys)) in names_with_keys.iter().enumerate() {
    let node_id = i as u32;
    let image = self.get_image_for_node(node_id);
    let mut validator_container = DockerContainer { ... };
    self.start_validator(&mut validator_container, &image).await;
}
```

#### 5.4 修改 `start_validator()`

当前函数签名：

```rust
async fn start_validator(&self, container: &mut DockerContainer)
```

建议改成：

```rust
async fn start_validator(&self, container: &mut DockerContainer, image: &str)
```

并把：

```rust
let image = self.get_image_from_env();
```

替换为直接使用传入的 `image`。

容器配置中保留：

```rust
image: Some(image),
```

或按实际借用关系写成：

```rust
image: Some(image.to_string().as_str())
```

实现时要注意 Rust 生命周期，实践里通常会先构造 `String`，再在 config 生成前保持其存活。

#### 5.5 `generate_keys()` 的镜像策略

这里需要明确一个设计决定。

当前 `generate_keys()` 也复用同一张镜像。

建议方案：

- key generator 始终使用 `default_ripple_image`
- 如果 `default_ripple_image` 为空，则 fallback 到 `RIPPLE_IMAGE`

理由：

- key generation 只依赖 `rippled validation_create`
- 让 keygen 和大多数 honest 节点镜像一致，逻辑简单
- 没必要为每个 override 节点单独起一次 keygen

建议辅助函数：

```rust
fn get_keygen_image(&self) -> String {
    if let Some(img) = self.get_default_image_from_config() {
        return img;
    }
    self.get_image_from_env()
}
```

然后在 `generate_keys()` 中替换当前：

```rust
let image = self.get_image_from_env();
```

为：

```rust
let image = self.get_keygen_image();
```

### 6. `rocket_controller/interceptor_manager.py`

如果采用上面的 proto 方案，这里原则上不必承载 mixed-image 配置。

建议仅保留：

```python
process_env["RIPPLE_IMAGE"] = self.rippled_img
```

但把它视作 fallback，而不是 mixed-image 的主要传输渠道。

这样现有单镜像模式仍然成立。

可选优化：

- 在日志里加一句说明当前是 fallback image

例如：

```python
logger.info(f"Using fallback rippled image: {self.rippled_img}")
```

### 7. `rocket_controller/cli_helper.py`

这里可以先不动，保留：

```python
--rippled-img
```

因为它仍然承担“旧接口兼容 + fallback 默认镜像”的职责。

长期如果想让接口更语义化，可以后续考虑：

- `--default-rippled-img`

但这不是这次必需项。

### 8. `evo/run_rocket.py`

这里当前接受的是：

```python
ripple_image: str
```

短期建议先不大改接口，让它继续传一个单值 fallback image 给 controller：

```python
"--rippled-img",
str(ripple_image),
```

但要增加一层说明：

- 当 `network.yaml` 中配置了 mixed-image 时，`ripple_image` 只是 fallback / default
- 当 `network.yaml` 没有 mixed-image 配置时，沿用旧行为，所有节点都使用它

如果后续想把 mixed-image sweep 也纳入 `run_evotests.py`，再扩这个入口。

### 9. `evo/utils.py`

当前：

```python
setup_docker_images(ripple_image, rocket_dir)
```

它只检查一个镜像。

mixed-image 后，建议新增：

```python
def setup_docker_images_for_run(default_image, node_image_overrides, rocket_dir):
    ...
```

逻辑：

- 收集 `default_image`
- 收集 `node_image_overrides.values()`
- 去重
- 对每个镜像执行现有 `_image_exists_locally` / `docker pull` 逻辑

注意：

- 如果 override 中有本地 `*-local` 镜像缺失，应该像现在一样直接报错
- 不要自动 build 本地镜像

### 10. `evo/evotest_parallel.py`

当前 main 中有：

```python
setup_docker_images(configs["ripple_image"], configs["rocket_dir"])
```

建议改为：

- 先读取 base network config
- 从中提取：
  - `default_ripple_image`
  - `node_image_overrides`
- 再统一调用 `setup_docker_images_for_run(...)`

伪代码：

```python
network_cfg = configs.get("base_network_config", {})
default_image = network_cfg.get("default_ripple_image") or configs["ripple_image"]
node_overrides = network_cfg.get("node_image_overrides", {}) or {}

setup_docker_images_for_run(
    default_image=default_image,
    node_image_overrides=node_overrides,
    rocket_dir=configs["rocket_dir"],
)
```

这样做之后：

- 运行前就能一次性校验所有需要的镜像
- 比等到 Rust 侧失败更友好

### 11. `evo/run_evotests.py`

这里有两种策略。

#### Strategy 1: Minimal Change

保持 `run_evotests.yaml` 的 `ripple_images` 不变。

此时其语义变成：

- 它只是给 `run_rocket.py` 提供 fallback image
- mixed-image 的真实节点分配由 `network.yaml` 决定

优点：

- 改动最小
- 很快能兼容现有脚本

缺点：

- `ripple_images` 的名字会稍微误导，因为它不再必然代表“所有节点镜像”

#### Strategy 2: Add Mixed Layout Sweep

把 `run_evotests.yaml` 升级成支持多种 image layout：

```yaml
image_layouts:
  - name: all_honest
    default_ripple_image: xrpld:2.6.0-local
    node_image_overrides: {}

  - name: byzz_bug5
    default_ripple_image: xrpld:2.6.0-local
    node_image_overrides:
      3: xrpld:2.6.0-bug5-local
```

然后 `run_evotests.py` 在每个 layout 下生成一个临时 network config。

这是更强的实验能力，但改动会更大。

推荐顺序：

1. 先做 Strategy 1
2. 跑通 mixed-image
3. 再决定是否做 Strategy 2

## Suggested First Implementation Scope

第一版建议只做以下范围：

1. `evo/network.yaml`
   - 支持 `default_ripple_image`
   - 支持 `node_image_overrides`

2. `packet.proto`
   - 增加 mixed-image 字段

3. `rocket_controller/packet_server.py`
   - 把 mixed-image 配置通过 gRPC 发给 interceptor

4. `rocket_interceptor/src/docker_manager.rs`
   - 按节点选择镜像
   - 预拉取所有镜像
   - keygen 使用 default image

5. `evo/utils.py` / `evo/evotest_parallel.py`
   - 预检查所有镜像是否存在

先不要做：

- `run_evotests.yaml` 的 `image_layouts`
- 更复杂的 CLI 参数重命名
- 对 encoding 的耦合改造

## Validation Checklist

改完后建议按下面顺序验证。

### Case 1: Old Single-Image Mode

配置：

- `network.yaml` 中不写 `default_ripple_image`
- `network.yaml` 中不写 `node_image_overrides`
- 外层仍然传 `--rippled-img xrpld:2.6.0-local`

预期：

- 所有节点仍然运行同一个镜像

### Case 2: Default + One Override

配置：

```yaml
default_ripple_image: xrpld:2.6.0-local
node_image_overrides:
  3: xrpld:2.6.0-bug5-local
```

预期：

- `validator_3` 使用 `xrpld:2.6.0-bug5-local`
- 其他节点使用 `xrpld:2.6.0-local`

### Case 3: Multiple Overrides

配置：

```yaml
default_ripple_image: xrpld:2.6.0-local
node_image_overrides:
  1: xrpld:1.7.2-local
  3: xrpld:2.6.0-bug5-local
  5: xrpld:2.6.0-bug0-local
```

预期：

- 各节点按 override 生效
- 启动前所有需要镜像均被检查

### Case 4: Invalid Node Override

配置：

```yaml
number_of_nodes: 7
node_image_overrides:
  9: xrpld:2.6.0-bug5-local
```

预期：

- controller 在构造 config 时直接报错
- 不进入实验执行

## Risks And Notes

### 1. Key Generation Compatibility

如果不同版本 `rippled` 的 `validation_create` 输出格式不同，keygen 可能受影响。

当前建议先假设：

- 相关版本之间该命令兼容

如果后续遇到问题，再引入独立字段：

```yaml
keygen_ripple_image: xrpld:2.6.0-local
```

### 2. Log Interpretation

后续如果 mixed-image 成为常规实验能力，建议把“每个 validator 最终使用的 image”写入日志目录，便于复盘。

例如：

- `node_image_map.json`

内容：

```json
{
  "0": "xrpld:2.6.0-local",
  "1": "xrpld:2.6.0-local",
  "3": "xrpld:2.6.0-bug5-local"
}
```

这不是第一版必需，但很有用。

### 3. `run_evotests.yaml` Naming

在 mixed-image 语义下，`ripple_images` 这个名字会逐渐不够准确。

短期先不改名没问题。

长期可以考虑改成：

- `fallback_ripple_images`
- 或 `image_layouts`

## Concrete Example

### Example Network Config

```yaml
base_port_peer: 60000
base_port_ws: 61000
base_port_ws_admin: 62000
base_port_rpc: 63000

number_of_nodes: 7
byzz_nodes: [3]

default_ripple_image: xrpld:2.6.0-local
node_image_overrides:
  3: xrpld:2.6.0-bug5-local
```

### Expected Runtime Mapping

- node 0 -> `xrpld:2.6.0-local`
- node 1 -> `xrpld:2.6.0-local`
- node 2 -> `xrpld:2.6.0-local`
- node 3 -> `xrpld:2.6.0-bug5-local`
- node 4 -> `xrpld:2.6.0-local`
- node 5 -> `xrpld:2.6.0-local`
- node 6 -> `xrpld:2.6.0-local`

## Recommended Implementation Order

建议实施顺序：

1. 改 `packet.proto`
2. 重新生成 proto 产物
3. 改 `rocket_controller/packet_server.py`
4. 改 `rocket_interceptor/src/docker_manager.rs`
5. 改 `evo/utils.py`
6. 改 `evo/evotest_parallel.py`
7. 在 `evo/network.yaml` 中加 mixed-image 示例
8. 最后再考虑是否扩展 `run_evotests.py` / `run_evotests.yaml`

## Final Recommendation

推荐方案总结：

- mixed-image 的配置中心放在 `network.yaml`
- 传输方式走 `packet.proto` 的 `Config`
- 使用 `default_ripple_image + node_image_overrides`
- 保留 `--rippled-img` 和 `RIPPLE_IMAGE` 作为 fallback
- 第一版只支持“固定 network mixed-image”
- 第二版再考虑把 mixed-image layout 纳入 `run_evotests.yaml` sweep

这个方案能最小化对现有实验编排的破坏，同时把真正决定“每个节点用什么镜像”的逻辑收敛到 network config 和 interceptor 启动层，后续也最容易维护。
