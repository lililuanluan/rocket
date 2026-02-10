#!/bin/bash

source ../.venv/bin/activate
# python3 evotest_deap.py 2>&1 | tee evotest.log
python3 evotest_deap.py
# python3 evotest_parallel.py