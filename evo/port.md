# Rocket 端口配置指南

## 背景：什么是临时端口（Ephemeral Ports）

### 临时端口是什么？

临时端口（又叫动态端口）是操作系统为客户端的 TCP/UDP 连接临时分配的端口。当应用发起出站连接而未指定源端口时，内核会在**临时端口范围**中随机挑选一个未使用的端口作为源端口。

**关键点：**
- 用于任何发起**出站**连接的程序（HTTP 客户端、DNS 查询、gRPC 客户端、Docker 容器内部通信等）
- 连接关闭后端口会自动释放
- 不用于服务器端监听端口（后者必须显式绑定）
- 不同操作系统的范围不同，可配置

### 为什么临时端口跟 Rocket 有关系？

Rocket 会同时启动多个 Docker 容器，每个容器都有自己的网络栈。这些容器内部会建立大量出站连接（节点间共识、RPC 调用等），内核从临时范围中分配源端口。如果我们给容器分配的测试端口和临时范围重叠，内核可能会随机选到正在使用的端口，导致：

- `RuntimeError: Failed to bind to address [::]:PORT`（gRPC 服务器绑定失败）
- `panicked at 'Failed to start the xrpld container'`（容器启动失败）
- 多个并行 batch 出现间歇性失败

---

## 查看系统的临时端口范围

### Linux

```bash
cat /proc/sys/net/ipv4/ip_local_port_range
```

输出示例：
```
32768   60999
```
表示端口 `32768–60999` 属于临时范围。

或使用更通用的命令：
```bash
sysctl net.ipv4.ip_local_port_range
```

### macOS

```bash
sysctl net.inet.ip.portrange.first net.inet.ip.portrange.last
```

示例：
```
net.inet.ip.portrange.first: 49152
net.inet.ip.portrange.last: 65535
```
表示 `49152–65535` 为临时端口。

### Windows（WSL2）

WSL2 是一个轻量 Linux 虚拟机，因此使用 Linux 方法：
```bash
cat /proc/sys/net/ipv4/ip_local_port_range
```

---

## 选择安全的 `port_start` 值

### 基本原则

**让 `port_start` 低于临时范围的最小值。**

| 系统 | 临时范围 | 推荐 `port_start` | 可用端口数量 | 备注 |
|------|-----------|-------------------|--------------|------|
| Linux（典型） | `32768–65535` | `10000` | `10000–32767`（22 768 个） | 通常安全 |
| Linux（自定义） | `32768–60999` | `10000` | `10000–32767` | WSL2 同此 |
| macOS | `49152–65535` | `10000` | `10000–49151`（39 152 个） | 容量大 |
| Windows (WSL2) | `32768–65535` | `10000` | `10000–32767` | 同 Linux |

### 计算所需端口数量

公式：
```
所需端口 = 镜像数量 × 种群规模 × 每个测试端口数
         = 镜像数量 × 种群规模 × (1 + 节点数 × 4)
```

当前配置示例：5 个镜像 × 10 个个体 × (1 + 7 × 4) = 1 450 个端口。范围 `10000–11449` 完全落在安全区间内。

---

## 单个测试的端口布局

每个测试使用一段连续端口，由 `evotest_parallel.py` 计算：

```
base_port = port_start + (generation × population_size + individual_index) × ports_per_test
```

按 7 节点分配：
```
peer 端口:     base + 0 … base + 6    (7 个)
WS 端口:       base + 7 … base + 13   (7 个)
WS 管理端口:   base + 14 … base + 20  (7 个)
RPC 端口:      base + 21 … base + 27  (7 个)
gRPC 端口:     base + 28             (1 个)
────────────────────────────────────────
总计端口数:    29 = 1 + 4 × 7
```

例如 `port_start=10000` 时：
```
第0代：
  个体1：base=10000, 范围10000–10028
  个体2：base=10029, 范围10029–10057
…
  个体10：base=10261, 范围10261–10289

第1代：
  个体1：base=10290, 范围10290–10318
…
```

---

## 在 `run_evotests.yaml` 中配置

将 `port_start` 参数设置为：

```yaml
# ============================================================================
# PORT CONFIGURATION
# ============================================================================
# 必须低于系统临时端口范围的起点。
# 在 Linux 上使用：cat /proc/sys/net/ipv4/ip_local_port_range
# 在 macOS 上使用：sysctl net.inet.ip.portrange.first
port_start: 10000

# 计算安全范围：
#   需要端口 = 镜像数量 × 种群规模 × (1 + 节点数 × 4)
#   例如 5 × 10 × 29 = 1450，
#   确保 port_start + 1450 < ephemeral_min。
```

---

## 在新机器上设置步骤

1. 检查系统配置

   **Linux/WSL2:**
   ```bash
   cat /proc/sys/net/ipv4/ip_local_port_range
   sudo netstat -tln | awk -F: '$NF >= 10000 && $NF <= 11500 {print}'
   ```

   **macOS:**
   ```bash
   sysctl net.inet.ip.portrange.first net.inet.ip.portrange.last
   lsof -i :10000-11500
   ```

2. 确定安全端口范围

   ```bash
   python3 -c "
   images = 5
   pop_size = 10
   num_nodes = 7
   ports_per_test = 1 + num_nodes * 4
   total_needed = images * pop_size * ports_per_test
   print(f'Total ports needed: {total_needed}')
   print(f'Using port_start=10000, requires up to port {10000 + total_needed - 1}')
   "
   ```

3. 修改配置：
   ```yaml
   port_start: 10000
   ```

4. 运行前验证
   ```bash
   sudo netstat -tln | grep LISTEN | awk -F: '$NF >= 10000 && $NF < 11500'
   lsof -i :10000-11500 | head -20
   ```

---

## 排查端口相关错误

### 错误1：`Failed to bind to address [::]:PORT`

**原因：** gRPC 端口被占用。

**排查：**
```bash
sudo lsof -i :PORT
sudo netstat -tlnp | grep PORT
```

**解决：**
- 把 `run_evotests.yaml` 中的 `port_start` 调高；
- 或调整系统临时端口范围（见下文）。

### 错误2：`panicked at 'Failed to start the xrpld container'`

**原因：** 容器内部的端口绑定失败，也是临时端口冲突导致。

**排查：**
```bash
docker ps
docker inspect <id> | grep -A5 Ports
sudo ss -tlnp | grep <port_range>
```

**解决：** 同错误1。

### 错误3：同一代内部分体出现失败但其他正常

**原因：** 内核从临时范围中随机分配了测试所用的某个端口。

**排查：**
```bash
watch -n 1 'ss -tln | grep LISTEN | wc -l'
```

**解决：** 将 `port_start` 调低到更安全的区域，例如 5000。

---

## 修改系统临时端口范围（高级）

### 何时修改

只有在：
1. 需要大量并发出站连接；
2. 希望使用 60000+ 端口进行测试；
3. 拥有管理员权限。

### Linux

```bash
# 临时调整：
sudo sysctl -w net.ipv4.ip_local_port_range="32768 49151"

# 永久修改：
sudo bash -c 'echo "net.ipv4.ip_local_port_range = 32768 49151" >> /etc/sysctl.conf'
sudo sysctl -p

# 验证：
cat /proc/sys/net/ipv4/ip_local_port_range
```

### macOS

```bash
# 临时：
sudo sysctl -w net.inet.ip.portrange.last=49151

# 永久：
sudo bash -c 'echo "net.inet.ip.portrange.last=49151" >> /etc/sysctl.conf'
sudo sysctl -p

# 验证：
sysctl net.inet.ip.portrange.last
```

### WSL2

按 Linux 方法操作。
可在 `/etc/sysctl.d/99-ports.conf` 中写入配置，并重启 WSL2：
```bash
sudo tee /etc/sysctl.d/99-ports.conf <<'EOF'
net.ipv4.ip_local_port_range = 32768 49151
EOF
```
然后在 Windows 端运行 `wsl --shutdown` 并重新启动。

---

## 不同操作系统的默认临时范围对照

| 操作系统 | 默认范围 | 备注 |
|----------|----------|------|
| Linux    | `32768–65535` | 可通过 `/proc/sys/net/ipv4/ip_local_port_range` 修改 |
| macOS    | `49152–65535` | 可通过 sysctl 修改 |
| Windows  | `49152–65535` | 不容易改 |
| WSL2     | `32768–65535` | 与 Linux 相同 |
| Docker   | 继承主机 | 默认为主机的范围 |

---

## 最佳实践

1. **每次运行前先确认临时范围**。
2. **保守选取起始端口**，例如 10000。
3. **初次测试时监控端口使用情况**。
4. **修改配置或临时范围时做好记录**。
5. **服务器环境保持与基础设施沟通**。

---

## 示例配置流程

```bash
# 查看临时范围
cat /proc/sys/net/ipv4/ip_local_port_range

# 计算所需端口
python3 -c "
config={'num_images':5,'population_size':10,'num_nodes':7}
ports_per_test=1+config['num_nodes']*4
total=config['num_images']*config['population_size']*ports_per_test
print('need', total)
"

# 验证端口空闲
sudo netstat -tln | grep -E ':(100[0-1][0-9]|11[0-4][0-9][0-9])'

# 修改配置
# port_start: 10000

# 运行测试并监控
watch -n 2 'ss -tln | grep LISTEN | wc -l'
```

---

如有疑问请查看系统网络文档 (`man sysctl`、`man netstat`、`man ss`) 或参考本仓库其它文档。
