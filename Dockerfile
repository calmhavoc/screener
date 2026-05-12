FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

# App setup
WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY screener.py .

# Runtime working directory
WORKDIR /work

ENTRYPOINT ["python", "/app/screener.py"]