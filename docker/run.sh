#!/bin/bash


set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
workspace_root="/data/workspace/lli21"
workspace_cache_root="${workspace_root}/docker_cache"

# 服务器上优先把日志和临时目录放到 workspace；本地则走后面的默认值。
if [ -d "${workspace_root}" ]; then
    ROCKET_LOG_ROOT="${ROCKET_LOG_ROOT:-${workspace_root}/logs}"
    ROCKET_TMPDIR="${ROCKET_TMPDIR:-${workspace_cache_root}/tmp}"
    ROCKET_CACHE_ROOT="${ROCKET_CACHE_ROOT:-${workspace_cache_root}/home}"
fi

# 默认使用环境变量 ROCKET_IMAGE_NAME 指定的镜像名称，如果没有设置则使用 rocket-evo:latest
image_name="${ROCKET_IMAGE_NAME:-rocket-evo:latest}"
dockerfile="${repo_root}/docker/Dockerfile"
# 缓存目录挂到容器的 HOME，这样 ~/.cargo 和 pip 的缓存都一起持久化，而且不需要改 entrypoint.sh 的逻辑
cache_root="${ROCKET_CACHE_ROOT:-${repo_root}/.docker-cache/home}"
container_home="${ROCKET_CONTAINER_HOME:-/tmp/rocket-home}"
default_tmp_root="${TMPDIR:-/tmp/rocket-tmp}"
tmp_root="${ROCKET_TMPDIR:-${default_tmp_root}}"

log_root="${ROCKET_LOG_ROOT:-${repo_root}/logs}"
volume_root="${ROCKET_VOLUMES_ROOT:-${tmp_root%/}/volumes}"
network_root="${ROCKET_NETWORK_ROOT:-${tmp_root%/}/network}"
build_jobs="${ROCKET_BUILD_JOBS:-$(nproc)}"

mkdir -p "${log_root}" "${cache_root}" "${tmp_root}" "${volume_root}" "${network_root}"

force_build="${ROCKET_FORCE_BUILD:-0}"
if [ "${force_build}" = "1" ] || ! docker image inspect "${image_name}" >/dev/null 2>&1; then
    docker build -f "${dockerfile}" -t "${image_name}" "${repo_root}"
else
    echo "Using existing image ${image_name}; skipping docker build (set ROCKET_FORCE_BUILD=1 to rebuild)."
fi


exec docker run --rm \
    --network host \
    --user "$(id -u):$(id -g)" \
    --group-add "$(stat -c '%g' /var/run/docker.sock)" \
    --name "evo-runner" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${repo_root}:${repo_root}" \
    -v "${log_root}:${log_root}" \
    -v "${cache_root}:${container_home}" \
    -v "${tmp_root}:${tmp_root}" \
    -v "${volume_root}:${volume_root}" \
    -v "${network_root}:${network_root}" \
    -w "${repo_root}" \
    -e HOME="${container_home}" \
    -e TMPDIR="${tmp_root}" \
    -e ROCKET_WORKSPACE="${repo_root}" \
    -e ROCKET_BUILD_JOBS="${build_jobs}" \
    -e ROCKET_LOG_ROOT="${log_root}" \
    -e ROCKET_VOLUMES_ROOT="${volume_root}" \
    -e ROCKET_NETWORK_ROOT="${network_root}" \
    -e ROCKET_HOST_UID="$(id -u)" \
    -e ROCKET_HOST_GID="$(id -g)" \
    -e USER="$(id -un)" \
    "${image_name}" \
    python evo/run_evotests.py "$@"

# 杀死所有容器（放在这里防止忘了），不要删！！
docker rm -f evo-runner || true
docker ps --format '{{.Names}}' | grep -E "^${USER}_.*(validator_[0-9]+|key_generator)$" | xargs -r docker rm -f # 根据前缀杀死
# docker ps --format '{{.Names}}' | grep -E '(^validator_|_validator_|^key_generator$|_key_generator$)' | xargs -r docker rm -f


rm -rf "${workspace_cache_root}/tmp"


# 删掉数据库目录以及临时文件目录：
# docker run --rm -v /tmp:/host-tmp -v /data/workspace/lli21:/workspace alpine sh -c 'rm -rf /host-tmp/rocket-tmp /workspace/tmp'
