FROM python:3.12-slim-bookworm

# Install uv
RUN pip install uv

WORKDIR /app

# Copy dependency spec first for layer caching
COPY pyproject.toml uv.lock ./

# Install deps WITHOUT the project itself (source isn't present yet)
RUN uv sync --no-dev --no-install-project

# Copy source
COPY farm_agent/ ./farm_agent/

# MUSHY-87: maintained operator tooling (replay_capture.py) has to be reachable
# from inside the running agent, or every use starts by copying a file in.
COPY scripts/ ./scripts/

# Now build + install the farm-agent project wheel (source is present)
RUN uv sync --no-dev

CMD ["uv", "run", "python", "-m", "farm_agent"]
