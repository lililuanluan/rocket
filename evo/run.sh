#!/bin/bash

source ../.venv/bin/activate
# python3 evotest_deap.py 2>&1 | tee evotest.log
# python3 evotest_deap.py
python3 evotest_parallel.py --strategy=RandomDelayByzzPartitionStrategy # --max-parallel-workers=5

# TODO: 修改路径配置逻辑，现在太混乱了