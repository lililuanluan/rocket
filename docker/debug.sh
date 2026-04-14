#!/bin/bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
workspace_root="/data/workspace/lli21"
workspace_cache_root="${workspace_root}/docker_cache"

# 服务器上优先把日志和临时目录放到 workspace；本地则走后面的默认值。
if [ -d "${workspace_root}" ]; then
    ROCKET_LOG_ROOT="${ROCKET_LOG_ROOT:-${workspace_root}/logs}"
    ROCKET_DEBUG_TMPDIR="${ROCKET_DEBUG_TMPDIR:-${workspace_cache_root}/debug-tmp}"
    ROCKET_DEBUG_CACHE_ROOT="${ROCKET_DEBUG_CACHE_ROOT:-${workspace_cache_root}/debug-home}"
fi

# debug 默认直接复用主运行镜像，尽量和 docker/run.sh 保持一致。
image_name="${ROCKET_DEBUG_IMAGE_NAME:-rocket-evo:latest}"
dockerfile="${ROCKET_DEBUG_DOCKERFILE:-${repo_root}/docker/Dockerfile}"
cache_root="${ROCKET_DEBUG_CACHE_ROOT:-${repo_root}/.docker-cache/home}"
container_home="${ROCKET_DEBUG_CONTAINER_HOME:-/tmp/rocket-home}"
default_tmp_root="${TMPDIR:-/tmp/rocket-tmp}"
tmp_root="${ROCKET_DEBUG_TMPDIR:-${default_tmp_root}}"
log_root="${ROCKET_LOG_ROOT:-${repo_root}/logs}"
volume_root="${ROCKET_DEBUG_VOLUMES_ROOT:-${tmp_root%/}/volumes}"
network_root="${ROCKET_DEBUG_NETWORK_ROOT:-${tmp_root%/}/network}"
build_jobs="${ROCKET_BUILD_JOBS:-$(nproc)}"
skip_bootstrap="${ROCKET_SKIP_BOOTSTRAP:-1}"

mkdir -p "${log_root}" "${cache_root}" "${tmp_root}" "${volume_root}" "${network_root}"

force_build="${ROCKET_DEBUG_FORCE_BUILD:-0}"
if [ "${force_build}" = "1" ] || ! docker image inspect "${image_name}" >/dev/null 2>&1; then
    docker build -f "${dockerfile}" -t "${image_name}" "${repo_root}"
else
    echo "Using existing image ${image_name}; skipping docker build (set ROCKET_DEBUG_FORCE_BUILD=1 to rebuild)."
fi

# 无参数时进入交互式 shell；有参数时直接在容器里执行该命令。
# 容器本身带 --rm，所以命令结束或手动 exit 后会自动清理退出。
debug_cmd=(bash -il)
if [ "$#" -gt 0 ]; then
    debug_cmd=("$@")
fi

docker_run_args=(
    --rm
    --network host
    --user "$(id -u):$(id -g)"
    --name "rocket-debugger"
    -v "${repo_root}:${repo_root}"
    -v "${log_root}:${log_root}"
    -v "${cache_root}:${container_home}"
    -v "${tmp_root}:${tmp_root}"
    -v "${volume_root}:${volume_root}"
    -v "${network_root}:${network_root}"
    -w "${repo_root}"
    -e HOME="${container_home}"
    -e TMPDIR="${tmp_root}"
    -e PYTHONPATH="${repo_root}:${repo_root}/evo"
    -e ROCKET_WORKSPACE="${repo_root}"
    -e ROCKET_BUILD_JOBS="${build_jobs}"
    -e ROCKET_SKIP_BOOTSTRAP="${skip_bootstrap}"
    -e ROCKET_LOG_ROOT="${log_root}"
    -e ROCKET_VOLUMES_ROOT="${volume_root}"
    -e ROCKET_NETWORK_ROOT="${network_root}"
    -e ROCKET_HOST_UID="$(id -u)"
    -e ROCKET_HOST_GID="$(id -g)"
    -e USER="$(id -un)"
    -e DOCKER_BUILDKIT=1
    -e BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"
    -e PIP_DISABLE_PIP_VERSION_CHECK=1
    -e MPLCONFIGDIR="${container_home}/.config/matplotlib"
    -e XDG_CONFIG_HOME="${container_home}/.config"
    -e TERM="${TERM:-xterm-256color}"
    -e COLORTERM="${COLORTERM:-truecolor}"
    -e CLICOLOR=1
    -e FORCE_COLOR=1
)

if [ -t 0 ] && [ -t 1 ]; then
    docker_run_args+=(-it)
fi

if [ -S /var/run/docker.sock ]; then
    docker_run_args+=(
        --group-add "$(stat -c '%g' /var/run/docker.sock)"
        -v /var/run/docker.sock:/var/run/docker.sock
    )
fi

exec docker run \
    "${docker_run_args[@]}" \
    "${image_name}" \
    "${debug_cmd[@]}"
