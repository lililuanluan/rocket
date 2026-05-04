#!/bin/bash

set -e

cd "$(dirname "$0")/.."

build_one() {
    local bug_id="$1"
    local tag_suffix

    case "${bug_id}" in
        NONE) tag_suffix="bug0" ;;
        BUG1) tag_suffix="bug1" ;;
        BUG2) tag_suffix="bug2" ;;
        BUG3) tag_suffix="bug3" ;;
        BUG4) tag_suffix="bug4" ;;
        *)
            echo "Unsupported bug id: ${bug_id}" >&2
            exit 1
            ;;
    esac

    DOCKER_BUILDKIT=1 \
    BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}" \
    docker build \
        -t "xrpld:2.6.0-${tag_suffix}-local" \
        -f images/Dockerfile.rippled-2.6.0.bugs \
        --build-arg "BUG_ID=${bug_id}" \
        images
}

build_local_version() {
    local version="$1"

    DOCKER_BUILDKIT=1 \
    BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}" \
    docker build \
        -t "xrpld:${version}-local" \
        -f "images/Dockerfile.rippled-${version}" \
        images
}

if [ "$#" -gt 0 ]; then
    for arg in "$@"; do
        case "${arg}" in
            3.1.0|3.1.0-local|xrpld:3.1.0-local)
                build_local_version "3.1.0"
                ;;
            *)
                build_one "${arg}"
                ;;
        esac
    done
else
    build_one BUG1
    build_one BUG2
    build_one BUG3
    build_one BUG4
fi
