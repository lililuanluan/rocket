FROM python:3.12-bookworm

ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MPLBACKEND=Agg

RUN apt-get update && apt-get install -y \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip \
    && python -m pip install \
        matplotlib==3.10.7 \
        pandas==2.3.3 \
        pyyaml

WORKDIR /workspace

CMD ["/bin/bash"]
