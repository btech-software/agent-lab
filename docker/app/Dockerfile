FROM python:3.12.15-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV SERVICE_NAME=Agent-Lab
ENV SERVICE_VERSION=1.17.6
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000
ENV WORKERS=1

WORKDIR /agent-lab

COPY --from=mwader/static-ffmpeg:9.0.2-1@sha256:f5d100184884eb3e82b0eb14bb5ebf98da99826ac824989720297fb9ef21c822 /ffmpeg /usr/local/bin/

COPY pyproject.toml uv.lock /agent-lab/
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336,source=/uv,target=/bin/uv \
    uv sync --no-build --frozen --no-dev --no-install-project \
    && rm -rf /tmp/* /var/tmp/* \
    && groupadd -r agent-lab \
    && useradd -r -g agent-lab -d /agent-lab agent-lab \
    && chown -R agent-lab:agent-lab /agent-lab

USER agent-lab
COPY agent_lab /agent-lab/agent_lab/
COPY config-docker.yml /agent-lab/

CMD ["/bin/bash", "-c", "/agent-lab/.venv/bin/python -m uvicorn agent_lab.main:app --host ${HOST} --port ${PORT} --workers ${WORKERS}"]
