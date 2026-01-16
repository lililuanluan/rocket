#!/usr/bin/env bash
set -euo pipefail

# 确保日志文件存在并可写（其他目录在 Dockerfile 已创建）
mkdir -p /var/log/rippled
touch /var/log/rippled/rippled.log   # 假设默认日志名
chown rippleduser:rippleduser /var/log/rippled/rippled.log || true

# 如果是 server_info 子命令，直接执行并输出
if [[ "${1-}" == "server_info" ]]; then
  exec rippled server_info
fi

# 如果有其他参数，转发给 rippled
if [[ $# -gt 0 ]]; then
  exec rippled "$@"
fi

# 默认：前台启动 rippled
exec rippled --net --conf /config/rippled.cfg