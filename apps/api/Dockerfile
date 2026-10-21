FROM python:3.11-slim

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml
COPY apps/api/pyproject.toml ./apps/api/

# Install python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
    fastapi>=0.100.0 \
    "uvicorn[standard]>=0.23.0" \
    "pydantic>=2.0" \
    "pydantic-settings>=2.0" \
    "sqlalchemy>=2.0.0" \
    "alembic>=1.12.0" \
    "psycopg2-binary>=2.9.0" \
    "httpx>=0.24.0" \
    "pytest>=7.0.0" \
    "ruff>=0.1.0"

# Copy source code
COPY . .

WORKDIR /workspace/apps/api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
