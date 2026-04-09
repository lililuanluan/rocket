#!/bin/bash

set -e

cd ..

DOCKER_BUILDKIT=1 \
BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}" \
docker build -t xrpld:2.6.0-bug0-local -f images/Dockerfile.rippled-2.6.0.bugs --build-arg BUG_ID=NONE images
