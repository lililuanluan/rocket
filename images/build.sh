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

build_byzzfuzz_bug() {
    local image_name="xrpld:2.6.0-byzz-bug-injected-local"
    local base_image="xrpld:2.6.0-byzz-bug-injected-base-local"
    local source_repo="${PWD}/images/rippled"
    local source_context

    if docker image inspect "${image_name}" >/dev/null 2>&1; then
        local wrapper_label
        wrapper_label="$(docker image inspect "${image_name}" \
            --format '{{ index .Config.Labels "org.rocket.byzzfuzz_database_path_wrapper" }}')"
        if [ "${wrapper_label}" = "1" ]; then
            echo "Using existing wrapped image ${image_name}."
            return
        fi

        docker tag "${image_name}" "${base_image}" >/dev/null
        DOCKER_BUILDKIT=1 \
        BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}" \
        docker build \
            --build-arg "BASE_IMAGE=${base_image}" \
            -t "${image_name}" \
            -f images/Dockerfile.rippled-2.6.0-byzz-wrapper \
            images
        return
    fi

    if [ ! -d "${source_repo}/.git" ]; then
        echo "Expected rippled source checkout at ${source_repo}" >&2
        exit 1
    fi

    source_context="$(mktemp -d "${TMPDIR:-/tmp}/rocket-byzzfuzz-rippled.XXXXXX")"
    cleanup_byzzfuzz_source_context() {
        rm -rf "${source_context}"
        trap - RETURN
    }
    trap cleanup_byzzfuzz_source_context RETURN

    # Use a clean source archive so uncommitted CSF/replay work in
    # images/rippled cannot leak into the injected-bug benchmark image. This
    # also keeps Docker cache keys stable because no random worktree .git file
    # is copied into the build context.
    git -C "${source_repo}" archive --format=tar \
        origin/byzz-fuzz-bug-reproduce | tar -x -C "${source_context}"

    DOCKER_BUILDKIT=1 \
    BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}" \
    docker build \
        --build-context "rippled-src=${source_context}" \
        -t "${image_name}" \
        -f images/Dockerfile.rippled-2.6.0-byzz-bug-injected \
        images
}

if [ "$#" -gt 0 ]; then
    for arg in "$@"; do
        case "${arg}" in
            3.1.0|3.1.0-local|xrpld:3.1.0-local)
                build_local_version "3.1.0"
                ;;
            3.3.0|3.3.0-local|xrpld:3.3.0-local)
                build_local_version "3.3.0"
                ;;
            byzzfuzz|byzz-fuzz|2.6.0-byzz-bug-injected|xrpld:2.6.0-byzz-bug-injected-local)
                build_byzzfuzz_bug
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
