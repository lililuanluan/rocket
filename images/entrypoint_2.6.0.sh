#!/usr/bin/env bash
set -euo pipefail

# Rocket generates compact per-validator configs at runtime.  rippled 2.6.0
# still requires an explicit SQLite bookkeeping directory; newer configs may
# omit it because 3.1.0 tolerates the shorter form.
if [[ $# -eq 0 && -f /config/rippled.cfg ]] && ! grep -q '^\[database_path\]' /config/rippled.cfg; then
  printf '\n[database_path]\n/var/lib/rippled/db\n' >> /config/rippled.cfg
fi

exec /entrypoint.base.sh "$@"
