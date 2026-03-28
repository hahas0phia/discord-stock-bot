FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY main.py wsgi.py health.py dashboard.html .env.example ./

# Expose port 8080
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD-SHELL curl -f http://localhost:${PORT:-8080}/health || exit 1

# Run the application with Gunicorn
CMD ["sh", "-c", "gunicorn -w 1 -b 0.0.0.0:${PORT:-8080} --timeout 300 --access-logfile - --error-logfile - wsgi:app"]
