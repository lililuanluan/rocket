#!/bin/bash

# set -e

# if [ ! -d "./rippled" ]; then
# 	git clone git@github.com:lililuanluan/rippled.git
# fi

# cd rippled
# git for-each-ref --format='%(refname:short) %(objectname:short) %(authordate:iso8601) %(authorname) %(subject)' refs/heads/bug*
# git branch --list 'bug*'
# # git push origin 'refs/heads/bug*:refs/heads/bug*' 将新分支推送到远端
# cd -

# docker image ls  | grep "2.6.0-bug"

# docker build -f Dockerfile.rippled-2.6.0-bug1-injected -t  2.6.0-bug1-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug2-injected -t  2.6.0-bug2-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug3-injected -t  2.6.0-bug3-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug4-injected -t  2.6.0-bug4-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug5-injected -t  2.6.0-bug5-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug6-injected -t  2.6.0-bug6-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug7-injected -t  2.6.0-bug7-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug8-injected -t  2.6.0-bug8-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug9-injected -t  2.6.0-bug9-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug10-injected -t  2.6.0-bug10-local --no-cache .
# additional bugs
# docker build -f Dockerfile.rippled-2.6.0-bug11-injected -t  2.6.0-bug11-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug12-injected -t  2.6.0-bug12-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug13-injected -t  2.6.0-bug13-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug14-injected -t  2.6.0-bug14-local --no-cache .
# docker build -f Dockerfile.rippled-2.6.0-bug15-injected -t  2.6.0-bug15-local --no-cache .




for i in {11..15}; do
	python3 setup.py --jobs 10 -f --build xrpld:2.6.0-bug${i}-local --max-workers 1
done