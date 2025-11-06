#!/bin/bash

set -e

source ../.venv/bin/activate

maturin develop --release

echo "Copying type stub file..."
SERIALIZE_DIR=$(python3 -c "import serialize; import os; print(os.path.dirname(serialize.__file__))")
cp serialize.pyi "$SERIALIZE_DIR/"