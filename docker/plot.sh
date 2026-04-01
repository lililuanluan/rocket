#!/bin/bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
plot_home_root="${ROCKET_PLOT_HOME_ROOT:-/data/workspace/lli21/tmp/rocket-plot-home}"
plot_tmp_root="${ROCKET_PLOT_TMP_ROOT:-/data/workspace/lli21/tmp/rocket-plot-tmp}"
container_home="${ROCKET_PLOT_CONTAINER_HOME:-/tmp/rocket-plot-home}"
container_tmp="${ROCKET_PLOT_CONTAINER_TMP:-/tmp/rocket-plot-tmp}"
log_root="${ROCKET_LOG_ROOT:-/data/workspace/lli21/logs}"

mkdir -p "${plot_home_root}" "${plot_tmp_root}"

docker build -f "${script_dir}/Dockerfile.plot" -t rocket-plot:latest "${repo_root}"



exec docker run --rm -it \
  --user "$(id -u):$(id -g)" \
  -v "${repo_root}:${repo_root}" \
  -v "${log_root}:${log_root}" \
  -v "${plot_home_root}:${container_home}" \
  -v "${plot_tmp_root}:${container_tmp}" \
  -w "${repo_root}" \
  -e HOME="${container_home}" \
  -e TMPDIR="${container_tmp}" \
  -e MPLCONFIGDIR="${container_home}/.config/matplotlib" \
  -e XDG_CONFIG_HOME="${container_home}/.config" \
  -e ROCKET_LOG_ROOT="${log_root}" \
  rocket-plot:latest \
  python evo/plot_fitness_trend.py
