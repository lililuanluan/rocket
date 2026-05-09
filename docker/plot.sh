#!/bin/bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
workspace_root="/data/workspace/lli21"
workspace_cache_root="${workspace_root}/docker_cache"
plot_home_root="${ROCKET_PLOT_HOME_ROOT:-${workspace_cache_root}/plot-home}"
plot_tmp_root="${ROCKET_PLOT_TMP_ROOT:-${workspace_cache_root}/plot-tmp}"
container_home="${ROCKET_PLOT_CONTAINER_HOME:-/tmp/rocket-plot-home}"
container_tmp="${ROCKET_PLOT_CONTAINER_TMP:-/tmp/rocket-plot-tmp}"
log_root="${ROCKET_LOG_ROOT:-${workspace_root}/logs}"
data_root="${workspace_root}/data"

mkdir -p "${plot_home_root}" "${plot_tmp_root}"

force_build="${ROCKET_PLOT_FORCE_BUILD:-0}"
if [ "${force_build}" = "1" ] || ! docker image inspect rocket-plot:latest >/dev/null 2>&1; then
  docker build -f "${script_dir}/Dockerfile.plot" -t rocket-plot:latest "${repo_root}"
else
  echo "Using existing image rocket-plot:latest; skipping docker build (set ROCKET_PLOT_FORCE_BUILD=1 to rebuild)."
fi

exec docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  -v "${repo_root}:${repo_root}" \
  -v "${log_root}:${log_root}" \
  -v "${data_root}:${data_root}" \
  -v "${plot_home_root}:${container_home}" \
  -v "${plot_tmp_root}:${container_tmp}" \
  -w "${repo_root}" \
  -e HOME="${container_home}" \
  -e TMPDIR="${container_tmp}" \
  -e MPLCONFIGDIR="${container_home}/.config/matplotlib" \
  -e XDG_CONFIG_HOME="${container_home}/.config" \
  -e ROCKET_LOG_ROOT="${log_root}" \
  rocket-plot:latest \
  python -m evo.analysis.cli "$@"
