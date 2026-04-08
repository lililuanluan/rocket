#!/bin/bash

# 先判断是否存在.venv
if [ ! -d "../.venv" ]; then
  echo "warning: .venv not found. "
else 
  source ../.venv/bin/activate
fi

# 清理遗留的 validator 容器，避免 debug 时端口冲突
docker ps -a --format '{{.Names}}' | grep '_validator_' | xargs -r docker rm -f

# python3 evotest_parallel.py --ripple-image xrpld:2.6.0-bug11-local --min-delay-ms 0 --max-delay-ms 100 --rust-log-level info --byzz-min-seq 5 --byzz-max-seq 10  --max-ledger-seq 15 --total-num-tests 100 --population-size 8 --fitness-function "mean_validation_time" --strategy "EvoDelayByzzPartitionStrategy" --max-parallel-workers 1 --base-network-config-yaml "network.yaml" --mu 4 --timeout-per-seq 30 --individual-timeout-sec 300 --base-port-population 60000 --grpc-base-port 50051 --partition-seq 5 --partition-duration 3000  --output-screen # --logs-group-dir 自动化

# python3 run_evotests.py


exec python -m   evo.evotest_parallel \
  --ripple-image xrpld:2.6.0-bug0-local \
  --min-delay-ms 0 \
  --max-delay-ms 100 \
  --rust-log-level info \
  --byzz-min-seq 5 \
  --byzz-max-seq 10 \
  --max-ledger-seq 15 \
  --total-num-tests 0 \
  --population-size 1 \
  --fitness-function mean_validation_time \
  --strategy ComposedStrategy \
  --delay-mode sparse_rules \
  --partition-mode bi_part_groups \
  --byzz-mode sparse_rules \
  --max-parallel-workers 1 \
  --base-network-config-yaml network.yaml \
  --mu 1 \
  --timeout-per-seq 30 \
  --individual-timeout-sec 300 \
  --base-port-population 60000 \
  --grpc-base-port 50051 \
  --partition-seq 5 \
  --partition-duration 3000 \
  --force-exit-on-second-sigint \
  --output-screen
