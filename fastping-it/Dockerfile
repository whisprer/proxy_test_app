# Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ultimate_fastping_app.py .

# Create directories for data persistence
RUN mkdir -p /app/data /app/logs

# Create non-root user for security
RUN useradd -m -u 1000 fastping && chown -R fastping:fastping /app
USER fastping

# Expose port
EXPOSE 9876

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9876/health || exit 1

# Run the application
CMD ["python", "ultimate_fastping_app.py"]