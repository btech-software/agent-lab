FROM python:3.12-slim

ENV SERVICE_NAME=Agent-Lab
ENV SERVICE_VERSION=1.16.1
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000
ENV WORKERS=1

WORKDIR /agent-lab

COPY --from=mwader/static-ffmpeg:8.1.2@sha256:33f770f812cbfc3de96c547157fc9faf8bd95a36481753439ffa761045167585 /ffmpeg /usr/local/bin/

COPY pyproject.toml uv.lock /agent-lab/
RUN --mount=from=ghcr.io/astral-sh/uv:latest,source=/uv,target=/bin/uv \
    uv sync --no-build --frozen --no-dev --no-install-project \
    && rm -rf /tmp/* /var/tmp/* \
    && groupadd -r agent-lab \
    && useradd -r -g agent-lab -d /agent-lab agent-lab \
    && chown -R agent-lab:agent-lab /agent-lab

USER agent-lab
COPY agent_lab /agent-lab/agent_lab/
COPY config-docker.yml /agent-lab/

CMD ["/bin/bash", "-c", "/agent-lab/.venv/bin/python -m uvicorn agent_lab.main:app --host ${HOST} --port ${PORT} --workers ${WORKERS}"]
