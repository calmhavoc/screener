FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

# ── Install app code into /app ────────────────────────────────────────────────
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY screener.py .
COPY docker-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# ── /work is the bind-mount point for the host current directory ──────────────
# Mount your cwd at /work so relative paths resolve on the host:
#   docker run --rm -v "$PWD:/work" screener ./urls.txt --output ./new_report
WORKDIR /work

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
