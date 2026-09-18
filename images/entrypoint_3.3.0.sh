#!/usr/bin/env bash
set -euo pipefail

# Rocket 运行时生成的是紧凑的 per-validator 配置，不含 [database_path]。
# rippled 3.1.0 容忍省略（默认 SQLite 路径恰好可写），但 3.3.0 与 2.6.0 一样
# 需要显式的记账目录；缺失时 rippled 会以宿主 uid 启动失败：
#   terminate called after throwing an instance of 'soci::sqlite3_soci_error'
#     what():  Cannot establish connection to the database. unable to open database file
# 容器随即退出，interceptor 在 docker exec 探测 server_info 时拿到失败，
# 于 src/docker_manager.rs:148 的 unwrap() 处 panic。
#
# 与 entrypoint_2.6.0.sh 同构：只在无参数（即真正要起 validator）且配置缺该段时补齐。
if [[ $# -eq 0 && -f /config/rippled.cfg ]] && ! grep -q '^\[database_path\]' /config/rippled.cfg; then
  printf '\n[database_path]\n/var/lib/rippled/db\n' >> /config/rippled.cfg
fi

exec /entrypoint.base.sh "$@"
