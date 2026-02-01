# Makefile for building local rippled docker image

IMAGE_NAME = xrpld:1.4.0-local
DOCKERFILE = Dockerfile.rippled-1.4.0
RIPPLED_DIR = rippled

.PHONY: all build clean force-build

all: build

<<<<<<< HEAD
build: $(DOCKERFILE) $(RIPPLED_DIR)
	@UID=$$(id -u); GID=$$(id -g); \
	docker build -f $(DOCKERFILE) -t $(IMAGE_NAME) \
	  --build-arg UID=$$UID \
	  --build-arg GID=$$GID \
	  .

=======
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

>>>>>>> 8c00566 (build images better)
$(RIPPLED_DIR):
	@echo "Note: rippled source should be copied via Dockerfile"
	git clone git@github.com:XRPLF/rippled.git || true

<<<<<<< HEAD
force-build:
	@UID=$$(id -u); GID=$$(id -g); \
	docker build --no-cache -f $(DOCKERFILE) -t $(IMAGE_NAME) \
	  --build-arg UID=$$UID \
	  --build-arg GID=$$GID \
	  .

=======
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

>>>>>>> 8c00566 (build images better)
clean:
# 	rm -rf $(RIPPLED_DIR)
	docker rmi $(IMAGE_NAME) || true