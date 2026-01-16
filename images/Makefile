# Makefile for building local rippled docker image

IMAGE_NAME = xrpld:1.4.0-local
DOCKERFILE = Dockerfile.rippled-1.4.0
RIPPLED_DIR = rippled

.PHONY: all build clean force-build

all: build

build: $(DOCKERFILE) $(RIPPLED_DIR)
	@UID=$$(id -u); GID=$$(id -g); \
	docker build -f $(DOCKERFILE) -t $(IMAGE_NAME) \
	  --build-arg UID=$$UID \
	  --build-arg GID=$$GID \
	  .

$(RIPPLED_DIR):
	@echo "Note: rippled source should be copied via Dockerfile"
	git clone git@github.com:XRPLF/rippled.git || true

force-build:
	@UID=$$(id -u); GID=$$(id -g); \
	docker build --no-cache -f $(DOCKERFILE) -t $(IMAGE_NAME) \
	  --build-arg UID=$$UID \
	  --build-arg GID=$$GID \
	  .

clean:
# 	rm -rf $(RIPPLED_DIR)
	docker rmi $(IMAGE_NAME) || true