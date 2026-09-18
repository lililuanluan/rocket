#!/bin/bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"

usage() {
    cat <<'EOF'
Usage: docker/run_benchmark.sh <benchmark|known|all> [--repeats N] [--no-build] [--no-clean] [--clean-workers N]

Benchmarks:
  byzzfuzz-4424        Bench-ripple-bf
  overlap-unl-3.1.0    Bench-ripple-unl
  close-time-zero-3.1.0  Bench-ripple-3.1.0
  flip-full-validation-3.3.0  Bench-ripple-3.3.0
  known, all           Run the three paper benchmark presets above

Each repeat has a separate top-level log directory and includes snapshots of
both the experiment and network YAML.  By default, each successful repeat is
slimmed with docker/clean.sh before the next repeat starts.
EOF
}

if [ "$#" -lt 1 ]; then
    usage >&2
    exit 2
fi

benchmark="$1"
shift
repeats=1
build_images=1
auto_clean=1
clean_workers="${ROCKET_CLEAN_WORKERS:-16}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --repeats)
            if [ "$#" -lt 2 ] || ! [[ "$2" =~ ^[1-9][0-9]*$ ]]; then
                usage >&2
                exit 2
            fi
            repeats="$2"
            shift 2
            ;;
        --no-build)
            build_images=0
            shift
            ;;
        --no-clean)
            auto_clean=0
            shift
            ;;
        --clean-workers)
            if [ "$#" -lt 2 ] || ! [[ "$2" =~ ^[1-9][0-9]*$ ]]; then
                usage >&2
                exit 2
            fi
            clean_workers="$2"
            shift 2
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done

case "${benchmark}" in
    byzzfuzz-4424)
        benchmarks=(byzzfuzz-4424)
        ;;
    overlap-unl-3.1.0)
        benchmarks=(overlap-unl-3.1.0)
        ;;
    close-time-zero-3.1.0)
        benchmarks=(close-time-zero-3.1.0)
        ;;
    flip-full-validation-3.3.0)
        benchmarks=(flip-full-validation-3.3.0)
        ;;
    known|all)
        benchmarks=(byzzfuzz-4424 overlap-unl-3.1.0 close-time-zero-3.1.0)
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac

image_has_label() {
    local image_name="$1"
    local label_key="$2"
    local label_value="$3"

    local actual
    actual="$(docker image inspect "${image_name}" \
        --format "{{ index .Config.Labels \"${label_key}\" }}" 2>/dev/null || true)"
    [ "${actual}" = "${label_value}" ]
}

ensure_image() {
    local benchmark_name="$1"
    local image_name="$2"
    local build_arg="$3"
    local label_key="${4:-}"
    local label_value="${5:-}"

    if docker image inspect "${image_name}" >/dev/null 2>&1; then
        if [ -n "${label_key}" ] && ! image_has_label "${image_name}" "${label_key}" "${label_value}"; then
            if [ "${build_images}" != "1" ]; then
                echo "Image ${image_name} exists but is missing required label ${label_key}=${label_value}; rerun without --no-build." >&2
                exit 1
            fi
            echo "Rebuilding stale image ${image_name} for ${benchmark_name}."
            "${repo_root}/images/build.sh" "${build_arg}"
            return
        fi
        echo "Using existing image ${image_name}."
        return
    fi

    if [ "${build_images}" != "1" ]; then
        echo "Required image ${image_name} is missing; rerun without --no-build or build it manually." >&2
        exit 1
    fi

    echo "Building image ${image_name} for ${benchmark_name}."
    "${repo_root}/images/build.sh" "${build_arg}"
}

run_repeat() {
    local config_path="$1"
    local output_log
    local run_status
    local run_root

    output_log="$(mktemp "${TMPDIR:-/tmp}/rocket-benchmark-run.XXXXXX.log")"

    set +e
    "${script_dir}/run.sh" --config "${config_path}" 2>&1 | tee "${output_log}"
    run_status=${PIPESTATUS[0]}
    set -e

    if [ "${run_status}" -ne 0 ]; then
        echo "Benchmark repeat failed; keeping captured output at ${output_log}" >&2
        return "${run_status}"
    fi

    run_root="$(
        awk -F'Root log dir:[[:space:]]*' '/Root log dir:/ {print $2}' "${output_log}" |
            tail -1 |
            sed 's/[[:space:]]*$//'
    )"

    rm -f "${output_log}"

    if [ "${auto_clean}" != "1" ]; then
        return 0
    fi

    if [ -z "${run_root}" ] || [ ! -d "${run_root}" ]; then
        echo "Warning: could not determine completed run root; skipping auto clean." >&2
        return 0
    fi

    echo
    echo "Slimming completed repeat logs: ${run_root}"
    "${script_dir}/clean.sh" "${run_root}" --summary-only --no-size --workers "${clean_workers}"
}

if docker ps --format '{{.Names}}' | grep -Fxq evo-runner; then
    echo "An evo-runner is already active; wait for it to finish before launching a benchmark." >&2
    exit 1
fi

for selected_benchmark in "${benchmarks[@]}"; do
    case "${selected_benchmark}" in
        byzzfuzz-4424)
            ensure_image \
                "${selected_benchmark}" \
                "xrpld:2.6.0-byzz-bug-injected-local" \
                "byzzfuzz" \
                "org.rocket.byzzfuzz_database_path_wrapper" \
                "1"
            ;;
        overlap-unl-3.1.0)
            ensure_image \
                "${selected_benchmark}" \
                "xrpld:3.1.0-local" \
                "3.1.0"
            ;;
        close-time-zero-3.1.0)
            ensure_image \
                "${selected_benchmark}" \
                "xrpld:3.1.0-local" \
                "3.1.0"
            ;;
        flip-full-validation-3.3.0)
            ensure_image \
                "${selected_benchmark}" \
                "xrpld:3.3.0-local" \
                "3.3.0"
            ;;
    esac

    config_path="${repo_root}/evo/benchmarks/${selected_benchmark}/run_evotests.yaml"
    for ((run_idx = 1; run_idx <= repeats; run_idx++)); do
        echo
        echo "Starting ${selected_benchmark} repeat ${run_idx}/${repeats}"
        run_repeat "${config_path}"
    done
done
