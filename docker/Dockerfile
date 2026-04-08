FROM python:3.12-bookworm AS pythonbase
FROM docker:cli AS dockercli
FROM rust:bookworm

ENV CARGO_REGISTRIES_CRATES_IO_PROTOCOL=sparse
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

COPY --from=pythonbase /usr/local /usr/local
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker



# 将requirements.txt复制到一个单独的目录然后安装依赖避免在镜像构建阶段就假设真实 repo 路径
# 因为你运行时会把 repo 挂到“宿主机同绝对路径”，这个路径在本地和服务器都不同，不适合硬编码进 Dockerfile。
WORKDIR /tmp/rocket-build

# 注意，dockerfile只能拿到build context的东西，如果context是当前文件夹，则不能拿到 ../requirements.txt，所以在构建的时候需要将context设置为 .. （也就是 repo 根目录），然后使用 docker/entrypoint.sh 来指定文件路径
COPY requirements.txt .
RUN python -m pip install -U pip wheel maturin \
    && pip install -r requirements.txt


COPY docker/entrypoint.sh /usr/local/bin/rocket-dev-entrypoint

RUN chmod +x /usr/local/bin/rocket-dev-entrypoint

# 容器一启动，先跑 /usr/local/bin/rocket-entrypoint 设置环境变量，构建等
ENTRYPOINT ["/usr/local/bin/rocket-dev-entrypoint"]
# 将 CMD 传给entrypont，默认为bash
CMD ["bash"]
