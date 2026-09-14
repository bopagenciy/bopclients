# BopClients Production Runtime & Operational Container
FROM python:3.11-slim

# Create non-root system user and working directory
RUN groupadd -r bopgroup && useradd -r -g bopgroup -d /app bopuser
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY bopclients ./bopclients
COPY forge ./forge

# Set ownership to non-root user
RUN chown -R bopuser:bopgroup /app
USER bopuser

# Set environment variables
ENV PYTHONPATH=/app
ENV BOPCLIENTS_ENV=production
ENV LOG_LEVEL=INFO

# Default CMD runs the production scheduler tick; can be overridden for worker, db migrate, or readiness CLI
CMD ["python", "-m", "bopclients.runtime.scheduler_cli"]
