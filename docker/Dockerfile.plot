FROM python:3.12-bookworm

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MPLBACKEND=Agg

RUN python -m pip install --upgrade pip \
    && python -m pip install \
        matplotlib==3.10.7 \
        pandas==2.3.3

WORKDIR /workspace

CMD ["/bin/bash"]
