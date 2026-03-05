#!/bin/bash

source ../.venv/bin/activate

python3 evotest_parallel.py --ripple-image xrpllabsofficial/xrpld:2.6.0 --min-delay-ms 0 --max-delay-ms 100 --rust-log-level info --byzz-min-seq 5 --byzz-max-seq 10  --max-ledger-seq 15 --total-num-tests 100 --population-size 5 --fitness-function "var_validation_time" --strategy "EvoDelayStrategy" --max-parallel-workers 1 --base-network-config-yaml "network.yaml" --mu 4 --timeout-per-seq 30 --individual-timeout-sec 300 --base-port-population 60000 --grpc-base-port 50051 --partition-seq 5 --partition-duration 3000  # --logs-group-dir 自动化