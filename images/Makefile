# Makefile for building local rippled docker image

IMAGE_NAME = xrpld:1.4.0-local
DOCKERFILE = Dockerfile.rippled-1.4.0
IMAGE_NAME_1_7 = xrpld:1.7.2-local
DOCKERFILE_1_7 = Dockerfile.rippled-1.7.2
IMAGE_NAME_2_6 = xrpld:2.6.0-local
DOCKERFILE_2_6 = Dockerfile.rippled-2.6.0
IMAGE_NAME_2_6_BYZZ = xrpld:2.6.0-byzzfuzz-local
DOCKERFILE_2_6_BYZZ = Dockerfile.rippled-2.6.0-byzz-bug-injected
RIPPLED_DIR = rippled

.PHONY: all build clean force-build

all: build

build: 2.6.0-local 2.6.0-byzzfuzz-local # build-1.4 build-1.7 

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

$(RIPPLED_DIR):
	@echo "Note: rippled source should be copied via Dockerfile"
	git clone git@github.com:XRPLF/rippled.git || true

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