#!/bin/bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"

# 服务器上优先把日志和临时目录放到 workspace；本地则走后面的默认值。
if [ -d /data/workspace/lli21 ]; then
    ROCKET_LOG_ROOT="/data/workspace/lli21/logs"
    ROCKET_DEBUG_TMPDIR="/data/workspace/lli21/tmp/rocket-debug"
fi

image_name="${ROCKET_DEBUG_IMAGE_NAME:-rocket-evo-debug:latest}"
dockerfile="${repo_root}/docker/Dockerfile.debug"
cache_root="${ROCKET_DEBUG_CACHE_ROOT:-${repo_root}/.docker-cache/debug-home}"
container_home="${ROCKET_DEBUG_CONTAINER_HOME:-/tmp/rocket-debug-home}"
default_tmp_root="${TMPDIR:-/tmp/rocket-debug-tmp}"
tmp_root="${ROCKET_DEBUG_TMPDIR:-${default_tmp_root}}"
log_root="${ROCKET_LOG_ROOT:-${repo_root}/logs}"

mkdir -p "${log_root}" "${cache_root}" "${tmp_root}"

docker build -f "${dockerfile}" -t "${image_name}" "${repo_root}"

debug_cmd=(bash)
if [ "$#" -gt 0 ]; then
    debug_cmd=("$@")
fi

docker_run_args=(
    --rm
    -it
    --user "$(id -u):$(id -g)"
    --name "rocket-debugger"
    -v "${repo_root}:${repo_root}"
    -v "${log_root}:${log_root}"
    -v "${cache_root}:${container_home}"
    -v "${tmp_root}:${tmp_root}"
    -w "${repo_root}"
    -e HOME="${container_home}"
    -e TMPDIR="${tmp_root}"
    -e PYTHONPATH="${repo_root}"
    -e ROCKET_WORKSPACE="${repo_root}"
    -e ROCKET_LOG_ROOT="${log_root}"
    -e PIP_DISABLE_PIP_VERSION_CHECK=1
    -e MPLCONFIGDIR="${container_home}/.config/matplotlib"
    -e XDG_CONFIG_HOME="${container_home}/.config"
)

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
