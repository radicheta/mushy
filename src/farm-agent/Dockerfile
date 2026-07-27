FROM python:3.12-slim-bookworm

# Install uv
RUN pip install uv

WORKDIR /app

# Copy dependency spec first for layer caching
COPY pyproject.toml uv.lock ./

RUN uv sync --no-dev

# Copy source
COPY farm_agent/ ./farm_agent/

CMD ["uv", "run", "python", "-m", "farm_agent"]
