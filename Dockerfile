# BopClients Continuous Monitoring Worker Production Container
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

# Entrypoint default runs the monitoring worker run-once CLI
CMD ["python", "-m", "bopclients.worker.monitoring_worker_cli", "--once"]
