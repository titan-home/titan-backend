# The node images, one per process (decisions #85, #147): `api` holds
# titan-api, `admin` holds titan-admin; each installs only its own package and
# titan-core, on a slim Python, run as a non-root user. Build one with
# `docker build --target api .` or `--target admin`. Base images are pinned by
# digest (development rules, 11).

FROM ghcr.io/astral-sh/uv:0.12.24@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a AS uv

FROM python:3.12.15-slim-trixie@sha256:ddb0207ae1f0356c2b724d740769b0c5f5f51cc54a0525178f721825f78fe74c AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY server server
COPY cli/pyproject.toml cli/pyproject.toml

FROM build AS build-api
RUN uv sync --locked --package titan-api --no-dev --no-editable

FROM build AS build-admin
RUN uv sync --locked --package titan-admin --no-dev --no-editable

FROM python:3.12.15-slim-trixie@sha256:ddb0207ae1f0356c2b724d740769b0c5f5f51cc54a0525178f721825f78fe74c AS runtime
RUN useradd --system --uid 10001 --no-create-home titan
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1

FROM runtime AS admin
COPY --from=build-admin /app/.venv /app/.venv
USER titan
CMD ["titan-admin", "migrate"]

FROM runtime AS api
COPY --from=build-api /app/.venv /app/.venv
USER titan
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# The app itself decides whom to believe in X-Forwarded-For
# (TITAN_TRUSTED_PROXIES), so uvicorn's own handling is off. uvicorn's access
# log is off too: it prints query strings, which may hold search text
# (development rules, 11); nginx on the node logs every request without them.
CMD ["uvicorn", "titan_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--no-proxy-headers", "--no-access-log"]
