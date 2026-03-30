#!/bin/bash

set -euo pipefail

workspace="${ROCKET_WORKSPACE:-$PWD}"
home_dir="${HOME:-/tmp/rocket-home}"
build_jobs="${ROCKET_BUILD_JOBS:-$(nproc)}"
tmp_dir="${TMPDIR:-${HOME}/tmp}"

mkdir -p "${home_dir}" "${workspace}" "${tmp_dir}"

export HOME="${home_dir}"
export TMPDIR="${tmp_dir}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export CARGO_HOME="${HOME}/.cargo"
export CARGO_REGISTRIES_CRATES_IO_PROTOCOL="${CARGO_REGISTRIES_CRATES_IO_PROTOCOL:-sparse}"
export ROCKET_BUILD_JOBS="${build_jobs}"
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-$build_jobs}"
export MAX_JOBS="${MAX_JOBS:-$build_jobs}"
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-$build_jobs}"

mkdir -p "${CARGO_HOME}"

cat > "${CARGO_HOME}/config.toml" <<EOF
[registries.crates-io]
protocol = "${CARGO_REGISTRIES_CRATES_IO_PROTOCOL}"
EOF

if [ "${ROCKET_SKIP_BOOTSTRAP:-0}" != "1" ]; then
    (
        cd "${workspace}/serialize"
        maturin build --release --jobs "${ROCKET_BUILD_JOBS}"
        pip install --force-reinstall target/wheels/*.whl
        serialize_dir="$(python -c 'import os, serialize; print(os.path.dirname(serialize.__file__))')"
        cp serialize.pyi "${serialize_dir}/"
    )

    (
        cd "${workspace}/rocket_interceptor"
        ./build.sh
    )
fi

cd "${workspace}"
exec "$@"
