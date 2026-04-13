FROM docker.io/library/python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/yoitsu-base

COPY yoitsu-contracts /opt/yoitsu-base/src/yoitsu-contracts
COPY pasloe /opt/yoitsu-base/src/pasloe
COPY trenni /opt/yoitsu-base/src/trenni

ARG YOITSU_CONTRACTS_REV=""
ARG PASLOE_REV=""
ARG TRENNI_REV=""

RUN python -m venv /opt/yoitsu-base/venv \
    && /opt/yoitsu-base/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/yoitsu-base/venv/bin/pip install /opt/yoitsu-base/src/yoitsu-contracts \
    && /opt/yoitsu-base/venv/bin/pip install /opt/yoitsu-base/src/pasloe \
    && /opt/yoitsu-base/venv/bin/pip install /opt/yoitsu-base/src/trenni

RUN mkdir -p /opt/yoitsu-base/revs \
    && printf '%s\n' "$YOITSU_CONTRACTS_REV" > /opt/yoitsu-base/revs/yoitsu-contracts.rev \
    && printf '%s\n' "$PASLOE_REV" > /opt/yoitsu-base/revs/pasloe.rev \
    && printf '%s\n' "$TRENNI_REV" > /opt/yoitsu-base/revs/trenni.rev
