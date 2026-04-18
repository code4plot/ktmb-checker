FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1

# 5. Start the application
# Ensure your app (e.g., Flask) listens on 0.0.0.0 and the $PORT variable
CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 100 main:app