#!/usr/bin/env bash
set -euo pipefail

# Ensure the log directory exists. Do NOT create the log file here — when the
# host bind-mounts the directory, Docker may create it as root on the host. We
# prefer the host (evotest preflight) to create log directories as the operator
# user to avoid root-owned files. If the directory is not writable, we print a
# helpful diagnostic and continue so the container logs are visible for debugging.
mkdir -p /var/log/rippled

echo "[entrypoint] UID: $(id -u), GID: $(id -g)"
echo "[entrypoint] /var/log/rippled permissions:"
ls -ld /var/log/rippled
echo "[entrypoint] /var/log/rippled/rippled.log permissions (if exists):"
ls -l /var/log/rippled/rippled.log || echo "[entrypoint] Log file does not exist yet."

echo "[entrypoint] ENV_ARGS=${ENV_ARGS-}" 

# 如果是 server_info 子命令，直接执行并输出
if [[ "${1-}" == "server_info" ]]; then
  exec rippled server_info
fi

# 如果有其他参数，转发给 rippled
if [[ $# -gt 0 ]]; then
  exec rippled "$@"
fi

# Ensure log directory exists and show diagnostics about writability. Don't try to
# create or chown files here (that can create root-owned files on the host).
mkdir -p /var/log/rippled
if [ -w /var/log/rippled ]; then
  echo "[entrypoint] /var/log/rippled is writable by UID $(id -u)"
else
  echo "[entrypoint] WARNING: /var/log/rippled is not writable by UID $(id -u)."
  echo "[entrypoint] If you are bind-mounting this directory from the host, please pre-create it as your user and ensure it is writable." 
  echo "[entrypoint] Example on host: mkdir -p /path/to/rocket_interceptor/logs/<name> && chown $(id -u):$(id -g) /path/to/rocket_interceptor/logs/<name>"
fi
ls -l /var/log/rippled

# 默认：前台启动 rippled. 如果 ENV_ARGS 提供了额外参数（例如 --start --ledgerfile ...），则传递它们。
ENV_ARGS=${ENV_ARGS:---start}

if [[ -n "${ENV_ARGS-}" ]]; then
  echo "[entrypoint] Starting rippled with ENV_ARGS: ${ENV_ARGS}"
  # split ENV_ARGS into array
  read -r -a _env_args <<< "${ENV_ARGS}"
  exec rippled "${_env_args[@]}" --net --conf /config/rippled.cfg
else
  exec rippled --net --conf /config/rippled.cfg
fi