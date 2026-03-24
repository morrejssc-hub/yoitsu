FROM docker.io/library/python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/yoitsu

COPY yoitsu-contracts /opt/yoitsu/yoitsu-contracts
COPY palimpsest /opt/yoitsu/palimpsest

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install /opt/yoitsu/yoitsu-contracts \
    && /opt/venv/bin/pip install /opt/yoitsu/palimpsest

ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /opt/yoitsu/palimpsest

CMD ["palimpsest", "container-entrypoint"]
