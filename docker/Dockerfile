# Use the official Python 3.13 image as base
FROM python:3.13-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Install build dependencies for chromadb (hnswlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user (appuser with UID 1000)
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -m appuser

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml README.md ./

# Install dependencies globally using uv (while still root)
RUN uv pip install --system --no-cache -e ".[dev]"

# Copy application source code
COPY . .

# Change ownership of the application directory to the non-root user
RUN chown -R appuser:appgroup /app

# Switch to the non-root user
USER appuser

# Expose the MCP server port
EXPOSE 8001

# Start the application
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8001"]
