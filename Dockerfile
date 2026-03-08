FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY server.py .
COPY landing.html .
COPY src/ ./src/

# Set Python path
ENV PYTHONPATH=/app
ENV PORT=8080

# Expose port
EXPOSE 8080

# Default command
CMD ["python", "server.py"]
