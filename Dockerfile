FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1 \
	UV_COMPILE_BYTECODE=1 \
	UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache

COPY pyproject.toml README.md ./
RUN uv sync --no-install-project --no-dev

COPY mcp ./mcp

EXPOSE 8001

CMD ["uv", "run", "--no-dev", "python", "mcp/tes_mcp.py"]
