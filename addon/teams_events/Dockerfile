FROM ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.19 AS base_amd64
FROM ghcr.io/home-assistant/aarch64-base-python:3.12-alpine3.19 AS base_arm64

ARG TARGETARCH
FROM base_${TARGETARCH}

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/teams_events

RUN apk add --no-cache python3 py3-pip

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

COPY app /opt/teams_events/app

COPY run.sh /run.sh
RUN chmod +x /run.sh

ENTRYPOINT ["/run.sh"]
