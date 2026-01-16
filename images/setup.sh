#!/bin/bash


if [ ! -d "./rippled" ]; then
	git clone git@github.com:XRPLF/rippled.git
fi

docker build -f Dockerfile.rippled-1.4.0 -t xrpld:1.4.0-local .