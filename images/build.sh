#!/bin/bash

set -e

cd ..

docker build -t xrpld:2.6.0-bug0-local -f images/Dockerfile.rippled-2.6.0.bugs --build-arg GIT_REF=buglab --build-arg BUG_ID=NONE images