# Use official Python image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements if exists, else fallback to install fastapi and uvicorn
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 80

# Run FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]