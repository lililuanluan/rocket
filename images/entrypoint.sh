#!/usr/bin/env bash
set -euo pipefail

# 如果有参数传入（如 server_info, validation_create），直接执行 rippled 命令
# 不输出任何调试信息，确保返回纯 JSON
if [[ $# -gt 0 ]]; then
  exec rippled "$@"
fi

# ============ 以下是容器启动时的逻辑（无参数时执行）============

# 清理旧的数据库文件，避免 rippled 2.6.0 因 "state db error" 拒绝启动
# 这些目录在每次重启时应该是干净的
echo "[entrypoint] Cleaning up old database files..."
rm -rf /config/db/* /var/lib/rippled/db/* 2>/dev/null || true

# 如果 /config/rippled.cfg 不存在，使用默认配置
if [[ ! -f /config/rippled.cfg ]]; then
  echo "[entrypoint] No rippled.cfg found, using default configuration"
  if [[ -f /opt/ripple/etc/rippled.cfg ]]; then
    cp /opt/ripple/etc/rippled.cfg /config/rippled.cfg
  fi
fi

# 如果 /config/validators.txt 不存在，使用默认配置
if [[ ! -f /config/validators.txt ]]; then
  echo "[entrypoint] No validators.txt found, using default"
  if [[ -f /opt/ripple/etc/validators.txt ]]; then
    cp /opt/ripple/etc/validators.txt /config/validators.txt
  fi
fi

# Ensure the log directory exists
mkdir -p /var/log/rippled

echo "[entrypoint] UID: $(id -u), GID: $(id -g)"
echo "[entrypoint] /var/log/rippled permissions:"
ls -ld /var/log/rippled
echo "[entrypoint] /var/log/rippled/rippled.log permissions (if exists):"
ls -l /var/log/rippled/rippled.log 2>/dev/null || echo "[entrypoint] Log file does not exist yet."

echo "[entrypoint] ENV_ARGS=${ENV_ARGS-}" 

# Check log directory writability
if [ -w /var/log/rippled ]; then
  echo "[entrypoint] /var/log/rippled is writable by UID $(id -u)"
else
  echo "[entrypoint] WARNING: /var/log/rippled is not writable by UID $(id -u)."
fi

# 默认启动 rippled。ENV_ARGS 可以传入额外参数（例如 --start --ledgerfile ...）
ENV_ARGS=${ENV_ARGS:---start}

echo "[entrypoint] Starting rippled with ENV_ARGS: ${ENV_ARGS}"
# split ENV_ARGS into array
read -r -a _env_args <<< "${ENV_ARGS}"
exec rippled "${_env_args[@]}" --conf /config/rippled.cfg