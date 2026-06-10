# Dockerfile — The recipe for packing the app into a "tiffin box" (Docker image).
#
# Docker reads this top-to-bottom and builds a box that contains the app,
# Python, and every library it needs. The same box runs identically on
# your laptop and on AWS — "it works on my machine" problems disappear.
#
# Build it with:  docker build --platform linux/amd64 -t policy-rag .
# (--platform linux/amd64 because AWS servers are Linux, Macs are ARM)

# Start from a slim official Python 3.12 base — small and trusted
FROM python:3.12-slim

# Install the few system tools our libraries need:
#   libpq-dev + gcc → required to talk to Postgres
#   curl            → handy for health checks
# Then delete the package lists to keep the image small.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl && \
    rm -rf /var/lib/apt/lists/*

# uv is a very fast Python package installer (a faster pip)
RUN pip install uv

# All commands from here run inside /app in the box
WORKDIR /app

# Copy ONLY the dependency list first, then install dependencies.
# Docker caches this step — so if only the code changes (not the deps),
# rebuilding is much faster.
COPY pyproject.toml .
RUN uv pip install --system --no-cache .

# Now copy the actual application code into the box
COPY app/ ./app/
COPY ingestion/ ./ingestion/

# Create a normal (non-root) user and switch to it.
# Safety rule: if someone hacks the app, they won't have admin powers.
RUN useradd -m appuser
USER appuser

# The app listens on door (port) 8000
EXPOSE 8000

# What to run when the box opens: the FastAPI web server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
