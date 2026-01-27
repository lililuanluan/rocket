# Makefile for building local rippled docker image

IMAGE_NAME = xrpld:1.4.0-local
DOCKERFILE = Dockerfile.rippled-1.4.0
RIPPLED_DIR = rippled

# Add 1.7.2 image support
IMAGE_NAME_1_7 = xrpld:1.7.2-local
DOCKERFILE_1_7 = Dockerfile.rippled-1.7.2

.PHONY: all build clean force-build build-1.4 build-1.7 force-build-1.4 force-build-1.7

all: build

build: build-1.4 build-1.7

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

$(RIPPLED_DIR):
	@echo "Note: rippled source should be copied via Dockerfile"
	git clone git@github.com:XRPLF/rippled.git || true

force-build: force-build-1.4 force-build-1.7

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

clean:
#	 rm -rf $(RIPPLED_DIR)
	docker rmi $(IMAGE_NAME) || true
	docker rmi $(IMAGE_NAME_1_7) || true