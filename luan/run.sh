#!/bin/bash

set -e

source ../.venv/bin/activate

cd ..

# python3 -m rocket_controller -h 


export RUST_BACKTRACE=1

python3 -m rocket_controller -n luan/network.yaml -c luan/RandomFuzzer.yaml RandomFuzzer
