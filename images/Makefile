# Makefile for building local rippled docker image

IMAGE_NAME = xrpld:1.4.0-local
DOCKERFILE = Dockerfile.rippled-1.4.0
IMAGE_NAME_1_7 = xrpld:1.7.2-local
DOCKERFILE_1_7 = Dockerfile.rippled-1.7.2
IMAGE_NAME_2_6 = xrpld:2.6.0-local
DOCKERFILE_2_6 = Dockerfile.rippled-2.6.0
IMAGE_NAME_2_6_BYZZ = xrpld:2.6.0-byzzfuzz-local
DOCKERFILE_2_6_BYZZ = Dockerfile.rippled-2.6.0-byzz-bug-injected
IMAGE_NAME_2_6_BUG1 = xrpld:2.6.0-bug1-local
DOCKERFILE_2_6_BUG1 = Dockerfile.rippled-2.6.0-bug1-injected
IMAGE_NAME_2_6_BUG2 = xrpld:2.6.0-bug2-local
DOCKERFILE_2_6_BUG2 = Dockerfile.rippled-2.6.0-bug2-injected
IMAGE_NAME_2_6_BUG3 = xrpld:2.6.0-bug3-local
DOCKERFILE_2_6_BUG3 = Dockerfile.rippled-2.6.0-bug3-injected
IMAGE_NAME_2_6_BUG4 = xrpld:2.6.0-bug4-local
DOCKERFILE_2_6_BUG4 = Dockerfile.rippled-2.6.0-bug4-injected
IMAGE_NAME_2_6_BUG5 = xrpld:2.6.0-bug5-local
DOCKERFILE_2_6_BUG5 = Dockerfile.rippled-2.6.0-bug5-injected
IMAGE_NAME_2_6_BUG6 = xrpld:2.6.0-bug6-local
DOCKERFILE_2_6_BUG6 = Dockerfile.rippled-2.6.0-bug6-injected
IMAGE_NAME_2_6_BUG7 = xrpld:2.6.0-bug7-local
DOCKERFILE_2_6_BUG7 = Dockerfile.rippled-2.6.0-bug7-injected
IMAGE_NAME_2_6_BUG8 = xrpld:2.6.0-bug8-local
DOCKERFILE_2_6_BUG8 = Dockerfile.rippled-2.6.0-bug8-injected
IMAGE_NAME_2_6_BUG9 = xrpld:2.6.0-bug9-local
DOCKERFILE_2_6_BUG9 = Dockerfile.rippled-2.6.0-bug9-injected
IMAGE_NAME_2_6_BUG10 = xrpld:2.6.0-bug10-local
DOCKERFILE_2_6_BUG10 = Dockerfile.rippled-2.6.0-bug10-injected
RIPPLED_DIR = rippled

.PHONY: all build clean force-build

all: build

build:  2.6.0-bug1-local 2.6.0-bug2-local 2.6.0-bug3-local 2.6.0-bug4-local 2.6.0-bug5-local 2.6.0-bug6-local 2.6.0-bug7-local 2.6.0-bug8-local 2.6.0-bug9-local 2.6.0-bug10-local 2.6.0-local 2.6.0-byzzfuzz-local# build-1.4 build-1.7

build-1.4: $(DOCKERFILE) $(RIPPLED_DIR)
	@docker build -f $(DOCKERFILE) -t $(IMAGE_NAME) \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  .

build-1.7: $(DOCKERFILE_1_7) $(RIPPLED_DIR)
	@docker build -f $(DOCKERFILE_1_7) -t $(IMAGE_NAME_1_7) \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  .

2.6.0-local: $(DOCKERFILE_2_6)
	@docker build -f $(DOCKERFILE_2_6) -t $(IMAGE_NAME_2_6) .

2.6.0-byzzfuzz-local: $(DOCKERFILE_2_6_BYZZ)
	@docker build -f $(DOCKERFILE_2_6_BYZZ) -t $(IMAGE_NAME_2_6_BYZZ) .

2.6.0-bug1-local: $(DOCKERFILE_2_6_BUG1)
	@docker build -f $(DOCKERFILE_2_6_BUG1) -t $(IMAGE_NAME_2_6_BUG1) .

2.6.0-bug2-local: $(DOCKERFILE_2_6_BUG2)
	@docker build -f $(DOCKERFILE_2_6_BUG2) -t $(IMAGE_NAME_2_6_BUG2) .

2.6.0-bug3-local: $(DOCKERFILE_2_6_BUG3)
	@docker build -f $(DOCKERFILE_2_6_BUG3) -t $(IMAGE_NAME_2_6_BUG3) .

2.6.0-bug4-local: $(DOCKERFILE_2_6_BUG4)
	@docker build -f $(DOCKERFILE_2_6_BUG4) -t $(IMAGE_NAME_2_6_BUG4) .

2.6.0-bug5-local: $(DOCKERFILE_2_6_BUG5)
	@docker build -f $(DOCKERFILE_2_6_BUG5) -t $(IMAGE_NAME_2_6_BUG5) .

2.6.0-bug6-local: $(DOCKERFILE_2_6_BUG6)
	@docker build -f $(DOCKERFILE_2_6_BUG6) -t $(IMAGE_NAME_2_6_BUG6) .

2.6.0-bug7-local: $(DOCKERFILE_2_6_BUG7)
	@docker build -f $(DOCKERFILE_2_6_BUG7) -t $(IMAGE_NAME_2_6_BUG7) .

2.6.0-bug8-local: $(DOCKERFILE_2_6_BUG8)
	@docker build -f $(DOCKERFILE_2_6_BUG8) -t $(IMAGE_NAME_2_6_BUG8) .

2.6.0-bug9-local: $(DOCKERFILE_2_6_BUG9)
	@docker build -f $(DOCKERFILE_2_6_BUG9) -t $(IMAGE_NAME_2_6_BUG9) .

2.6.0-bug10-local: $(DOCKERFILE_2_6_BUG10)
	@docker build -f $(DOCKERFILE_2_6_BUG10) -t $(IMAGE_NAME_2_6_BUG10) .

$(RIPPLED_DIR):
	@echo "Note: rippled source should be copied via Dockerfile"
	git clone git@github.com:lililuanluan/rippled.git || true

force-build: force-build-1.4 force-build-1.7 force-2.6.0-local force-2.6.0-byzzfuzz-local

force-build-1.4:
	@docker build --no-cache -f $(DOCKERFILE) -t $(IMAGE_NAME) \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  .

force-build-1.7:
	@docker build --no-cache -f $(DOCKERFILE_1_7) -t $(IMAGE_NAME_1_7) \
	  --build-arg UID=$$(id -u) \
	  --build-arg GID=$$(id -g) \
	  .

force-2.6.0-local:
	@docker build --no-cache -f $(DOCKERFILE_2_6) -t $(IMAGE_NAME_2_6) .

force-2.6.0-byzzfuzz-local:
	@docker build --no-cache -f $(DOCKERFILE_2_6_BYZZ) -t $(IMAGE_NAME_2_6_BYZZ) .

clean:
#	 rm -rf $(RIPPLED_DIR)
	docker rmi $(IMAGE_NAME) || true
	docker rmi $(IMAGE_NAME_1_7) || true
	docker rmi $(IMAGE_NAME_2_6) || true
	docker rmi $(IMAGE_NAME_2_6_BYZZ) || true