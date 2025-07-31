FROM python:3.13-slim-bookworm
RUN export LANGUAGE=C.UTF-8; export LANG=C.UTF-8; export LC_ALL=C.UTF-8; export DEBIAN_FRONTEND=noninteractive

WORKDIR /rocket

RUN apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y apt-transport-https ca-certificates curl software-properties-common openssl libssl-dev python3-pip

RUN curl -fsSL https://get.docker.com | sh

COPY requirements.txt requirements.txt
RUN python3 -m pip install -r requirements.txt

COPY . .


CMD dockerd & \
    sleep 5 && \
    python3 -m rocket_controller ByzzQLStrategy
