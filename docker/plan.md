# Rocket Docker Plan

## 目标

这次容器化只服务两个入口：

- `python evo/run_evotests.py`
- `python evo/plot_fitness_trend.py`

不做通用 dev shell，不做复杂 launcher，不做 DinD，不做容器内 venv，不做自定义 hash 缓存。

先把这两个科研脚本稳定放进 Docker 里跑起来，后面真有需要再扩展。

## 方案结论

推荐方案：

- 一个固定的 `docker/Dockerfile`
- 一个简单的 `docker/entrypoint.sh`
- 一个 `docker/run-evotests.sh`
- 一个 `docker/plot-fitness-trend.sh`

运行模型：

- 控制脚本在容器里跑
- validator 容器由容器里的 Rocket 代码去调用宿主机 Docker daemon 创建
- 通过挂载 `/var/run/docker.sock` 实现“容器里控制宿主机 Docker”

不推荐 DinD。

## 为什么不用 Docker-in-Docker

因为这个项目本身已经是：

- Python 脚本
- 启动 Rust interceptor
- interceptor 再去创建 validator 容器

如果再套一层 DinD，会多出：

- 额外 dockerd
- 额外存储层
- 更复杂的网络
- 更多路径和日志排查成本

你当前只是想稳定跑两个脚本，不值得把系统复杂度抬这么高。

## 为什么需要挂 `docker.sock`

`rocket_interceptor` 会直接连接 Docker API 来创建 validator 容器。

所以容器里跑的 Rocket 必须能访问一个 Docker daemon。

最简单的方式就是：

- 把宿主机 `/var/run/docker.sock` 挂到容器里

这样容器里的代码虽然在容器内运行，但实际控制的是宿主机 Docker。

## 为什么当前建议 `--network host`

当前仓库里很多地方仍然默认用：

- `localhost`
- `127.0.0.1`

去访问 validator 暴露出来的端口。

所以在“不改业务代码”的前提下，最稳的是：

- 控制容器使用 `--network host`

这样容器里的 `localhost` 和宿主机网络语义一致，最符合当前代码假设。

## 为什么 repo 要保持“容器内外同绝对路径”

这是这个项目最容易踩坑的地方。

`rocket_interceptor` 会生成一些配置目录，然后把这些目录作为 bind mount source 传给 Docker daemon 去启动 validator 容器。

注意：

- Docker daemon 用的是宿主机视角解释路径

所以如果：

- 宿主机 repo 路径是 `/data/home/lli21/rocket`
- 容器里挂成 `/workspace/rocket`

那么容器里看起来存在的 `/workspace/rocket/...`
对宿主机 Docker daemon 来说通常是不存在的。

因此必须这样做：

- 宿主机 repo 在哪
- 容器里也挂到同一个绝对路径

例如：

- 宿主机：`/data/home/lli21/rocket`
- 容器内：`/data/home/lli21/rocket`

本地机器也是同样原则，只是路径会变成你本地的 repo 绝对路径。

## 关于日志目录

服务器上你希望把大量日志写到：

- `/data/workspace/lli21`

本地则没有这个路径。

这个问题不要写死进代码，也不要写死进 Dockerfile。

正确做法是：

- 用环境变量 `ROCKET_LOG_ROOT`

例如：

- 服务器：`ROCKET_LOG_ROOT=/data/workspace/lli21/rocket-logs`
- 本地：`ROCKET_LOG_ROOT=/你的本地绝对路径/rocket-logs`

然后运行脚本时：

- 自动创建这个目录
- 挂进容器
- 把它传给 `run_evotests.py` / plot 脚本使用

## 最终只保留这几个文件

```text
docker/
  Dockerfile
  entrypoint.sh
  run-evotests.sh
  plot-fitness-trend.sh
  plan.md
```

如果你以后确实想把本地和服务器参数做成两套，再考虑加：

```text
docker/
  local.env
  server.env
```

但第一阶段甚至可以先不加。

## `docker/Dockerfile`

这份 Dockerfile 负责：

- 提供稳定运行环境
- 安装系统依赖
- 安装稳定的 Python 依赖层

它不负责：

- 构建本地 `serialize/`
- 构建本地 `rocket_interceptor`

推荐内容：

```dockerfile
FROM python:3.12-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV PATH=/usr/local/cargo/bin:${PATH}

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    build-essential \
    ca-certificates \
    curl \
    docker.io \
    git \
    libssl-dev \
    openssh-client \
    pkg-config \
    protobuf-compiler \
    && rm -rf /var/lib/apt/lists/*

RUN curl https://sh.rustup.rs -sSf | sh -s -- -y --profile minimal --default-toolchain stable \
    && rustc --version \
    && cargo --version

WORKDIR /tmp/rocket-build
COPY requirements.txt .
RUN python -m pip install -U pip wheel maturin \
    && pip install -r requirements.txt

COPY docker/entrypoint.sh /usr/local/bin/rocket-entrypoint
RUN chmod +x /usr/local/bin/rocket-entrypoint

ENTRYPOINT ["/usr/local/bin/rocket-entrypoint"]
CMD ["bash"]
```

### 为什么这样写

- `python:3.12-bookworm`：符合当前仓库要求
- `docker.io`：不是为了 DinD，而是为了容器里能执行 `docker logs` / `docker exec`
- `protobuf-compiler`、`libssl-dev`、Rust：为了编译 `serialize` 和 `rocket_interceptor`
- `pip install -r requirements.txt` 放进 Dockerfile：更适合利用 Docker layer cache
- `entrypoint.sh` 单独放：让 bootstrap 逻辑不要堆进 Dockerfile

## `docker/entrypoint.sh`

这份脚本只做最小 bootstrap，不做额外抽象。

原则：

- 不用 venv
- 不做 hash 判断
- 不再安装 `requirements.txt`
- 只负责本地源码相关构建

推荐内容：

```bash
#!/bin/bash

set -euo pipefail

workspace="${ROCKET_WORKSPACE:-$PWD}"
home_dir="${HOME:-/tmp/rocket-home}"
build_jobs="${ROCKET_BUILD_JOBS:-$(nproc)}"

mkdir -p "${home_dir}" "${workspace}"

export HOME="${home_dir}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export CARGO_HOME="${HOME}/.cargo"
export CARGO_REGISTRIES_CRATES_IO_PROTOCOL="${CARGO_REGISTRIES_CRATES_IO_PROTOCOL:-sparse}"
export ROCKET_BUILD_JOBS="${build_jobs}"
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-$build_jobs}"
export MAX_JOBS="${MAX_JOBS:-$build_jobs}"
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-$build_jobs}"

mkdir -p "${CARGO_HOME}"

cat > "${CARGO_HOME}/config.toml" <<EOF
[registries.crates-io]
protocol = "${CARGO_REGISTRIES_CRATES_IO_PROTOCOL}"
EOF

if [ "${ROCKET_SKIP_BOOTSTRAP:-0}" != "1" ]; then
    (
        cd "${workspace}/serialize"
        maturin develop --release --jobs "${ROCKET_BUILD_JOBS}"
        serialize_dir="$(python -c 'import os, serialize; print(os.path.dirname(serialize.__file__))')"
        cp serialize.pyi "${serialize_dir}/"
    )

    (
        cd "${workspace}/rocket_interceptor"
        ./build.sh
    )
fi

cd "${workspace}"
exec "$@"
```

### 为什么先故意写得简单

因为你当前不是在做一个长期维护的开发平台，而是在做科研实验入口。

所以现在不做这些事：

- 不自己实现 hash 门控
- 不自己实现一层小型构建系统
- 不加 venv

同时也做一个职责切分：

- `Dockerfile` 安装 `requirements.txt`
- `entrypoint.sh` 只构建本地 `serialize` 和 `rocket_interceptor`

先让下面这些命令稳稳能跑就够了：

- `python evo/run_evotests.py`
- `python evo/plot_fitness_trend.py`

## `docker/run-evotests.sh`

这个脚本就是你以后在本地和服务器上的主要入口。

它负责：

- `docker build`
- `docker run`
- 挂 repo
- 挂 `docker.sock`
- 挂日志目录
- 用 host 网络
- 最后执行 `python evo/run_evotests.py`

推荐内容：

```bash
#!/bin/bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"

image_name="${ROCKET_IMAGE_NAME:-rocket-evo:latest}"
dockerfile="${repo_root}/docker/Dockerfile"

log_root="${ROCKET_LOG_ROOT:-${repo_root}/logs}"
build_jobs="${ROCKET_BUILD_JOBS:-$(nproc)}"

mkdir -p "${log_root}"

docker build -f "${dockerfile}" -t "${image_name}" "${repo_root}"

exec docker run --rm \
    --network host \
    --user "$(id -u):$(id -g)" \
    --group-add "$(stat -c '%g' /var/run/docker.sock)" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${repo_root}:${repo_root}" \
    -v "${log_root}:${log_root}" \
    -w "${repo_root}" \
    -e HOME=/tmp/rocket-home \
    -e ROCKET_WORKSPACE="${repo_root}" \
    -e ROCKET_BUILD_JOBS="${build_jobs}" \
    -e ROCKET_LOG_ROOT="${log_root}" \
    "${image_name}" \
    python evo/run_evotests.py "$@"
```

### 日志目录怎么用

这个脚本本身只把：

- `ROCKET_LOG_ROOT`

传进容器。

后面如果 `run_evotests.py` 已经支持从配置或参数使用这个目录，就直接走它现有逻辑。

如果它还没有显式读取 `ROCKET_LOG_ROOT`，你可以有两个选择：

1. 先让它继续写 repo 下默认日志目录  
   这种情况下，把 `ROCKET_LOG_ROOT` 先留作未来用。

2. 后面单独改 `evo` 脚本，让它优先读 `ROCKET_LOG_ROOT`  
   这是更推荐的长期方案，但不一定要现在做。

## `docker/plot-fitness-trend.sh`

这个脚本和上面类似，只是入口变成 plot 脚本。

推荐内容：

```bash
#!/bin/bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"

image_name="${ROCKET_IMAGE_NAME:-rocket-evo:latest}"
dockerfile="${repo_root}/docker/Dockerfile"

log_root="${ROCKET_LOG_ROOT:-${repo_root}/logs}"
build_jobs="${ROCKET_BUILD_JOBS:-$(nproc)}"

mkdir -p "${log_root}"

docker build -f "${dockerfile}" -t "${image_name}" "${repo_root}"

exec docker run --rm \
    --network host \
    --user "$(id -u):$(id -g)" \
    --group-add "$(stat -c '%g' /var/run/docker.sock)" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${repo_root}:${repo_root}" \
    -v "${log_root}:${log_root}" \
    -w "${repo_root}" \
    -e HOME=/tmp/rocket-home \
    -e ROCKET_WORKSPACE="${repo_root}" \
    -e ROCKET_BUILD_JOBS="${build_jobs}" \
    -e ROCKET_LOG_ROOT="${log_root}" \
    "${image_name}" \
    python evo/plot_fitness_trend.py "$@"
```

## 本地和服务器怎么用

### 本地

本地直接这样跑：

```bash
export ROCKET_LOG_ROOT=/你的本地绝对路径/rocket-logs
export ROCKET_BUILD_JOBS=5
./docker/run-evotests.sh
```

画图：

```bash
export ROCKET_LOG_ROOT=/你的本地绝对路径/rocket-logs
./docker/plot-fitness-trend.sh
```

### 服务器

服务器直接这样跑：

```bash
export ROCKET_LOG_ROOT=/data/workspace/lli21/rocket-logs
export ROCKET_BUILD_JOBS=10
./docker/run-evotests.sh
```

画图：

```bash
export ROCKET_LOG_ROOT=/data/workspace/lli21/rocket-logs
./docker/plot-fitness-trend.sh
```

## 如果你想再少一个步骤

如果你嫌每次都 `export` 太烦，后面可以再加一个非常简单的：

- `docker/local.env`
- `docker/server.env`

但第一阶段完全可以先不加。

## 第一批验证

### 1. 镜像能 build

```bash
docker build -f docker/Dockerfile -t rocket-evo:latest .
```

### 2. 容器里能访问 Docker

```bash
./docker/run-evotests.sh --help
```

如果启动后容器内 Docker 不通，通常会在实际运行 Rocket 时暴露出来。

### 3. bootstrap 成功

在日志里至少确认这些没有失败：

- Docker build 里的 `pip install -r requirements.txt`
- `maturin develop`
- `rocket_interceptor/build.sh`

### 4. `run_evotests.py` 能正常启动

如果它本身配置正确，接下来才是你的实验参数、并发数、日志目录这类问题。

## 当前不做的事

为了避免 scope 膨胀，当前明确不做：

- `dev-shell.sh`
- `run-controller.sh`
- Docker Compose
- DinD
- 容器内 venv
- 自定义 hash 缓存
- 复杂 profile 系统
- 为未来多用途场景预留太多抽象

## 后续如果有需要，再加什么

如果以后你明确觉得有必要，再逐步加：

1. `local.env` / `server.env`
2. `run_evotests.py` 显式读取 `ROCKET_LOG_ROOT`
3. host.docker.internal 版本，去掉 `--network host`
4. bootstrap 的 hash 门控
5. 更通用的 launcher

但这些都不是现在必须做的。

## 一句话总结

现在最适合你的不是“设计一个通用 Docker 平台”，而是“做两个很薄的 Docker 包装脚本，把 `run_evotests.py` 和 `plot_fitness_trend.py` 稳定放进容器里跑”。
