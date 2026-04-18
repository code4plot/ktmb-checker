FROM mcr.microsoft.com/playwright/python:v1.53.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
CMD ["python", "ktmb_checker.py"]