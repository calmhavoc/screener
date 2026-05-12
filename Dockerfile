FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

# Install app code into /app
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt
COPY . .

# /work is the bind-mount point for the host current directory.
# Running with:  docker run --rm -v "$PWD:/work" screener ./urls.txt --output ./new_report
# resolves relative paths (./urls.txt, ./new_report) relative to the host's cwd.
WORKDIR /work

ENTRYPOINT ["python", "/app/screener.py"]
