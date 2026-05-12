## URL screenshotter and metadata collector.

This script reads a list of URLs from a text file, captures full-page
screenshots, collects HTTP headers, infers basic technology fingerprints, and
produces an HTML report summarising the results.

### Key features

* Asynchronous fetching with httpx for efficient parallelism.
* Headless Chromium screenshots powered by Playwright.
* Technology hints derived from response headers and HTML markers.
* Responsive HTML report rendered via Jinja2.
* **Client-side filtering** in the generated report by status code, server header, or detected technology.

---

### Local usage

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run with paths relative to your current directory
python screener.py ./urls.txt --output ./new_report
```

---

### Docker usage

#### Build the image

> **Important:** run this command every time you change `screener.py`, `Dockerfile`,  
> or `docker-entrypoint.sh` to ensure the container reflects the latest code.

```bash
docker build -t screener .
```

#### How it works

The container's working directory is `/work`.
When you mount your host current directory at `/work`, relative paths like
`./urls.txt` and `./new_report` resolve directly to files in your host directory —
so the output appears locally after the container exits.

#### Run (current-directory paths)

```bash
# urls.txt (or any file) must exist in your current directory
docker run --rm -v "$PWD:/work" screener ./urls.txt --output ./new_report

# After the run, open ./new_report/report.html on your host
```

Any filename works — it does not have to be `urls.txt`:

```bash
docker run --rm -v "$PWD:/work" screener ./targets.txt --output ./targets_report
docker run --rm -v "$PWD:/work" screener ./customer_urls.txt --output ./customer_report
```

#### How paths work

| What you pass | Resolves inside container | Appears on host at |
|---|---|---|
| `./urls.txt` | `/work/urls.txt` | `$PWD/urls.txt` |
| `./new_report` | `/work/new_report` | `$PWD/new_report` |
| `/abs/path/file.txt` | `/abs/path/file.txt` | requires `-v /abs/path:/abs/path` |

#### Common options

| Flag | Default | Description |
|---|---|---|
| `--concurrency N` | `5` | Max parallel browser sessions |
| `--timeout N` | `30` | Per-URL timeout in seconds |
| `--no-screenshots` | off | Skip screenshots, metadata only |
| `--max-urls N` | unlimited | Cap the number of URLs processed |
| `--json PATH` | none | Also write raw results as JSON |
| `--verify-ssl` | off | Enable strict TLS verification |
| `--verbose` | off | Enable debug logging |

#### More examples

```bash
# Metadata only (faster, no Playwright browser needed)
docker run --rm -v "$PWD:/work" screener ./urls.txt --output ./new_report --no-screenshots

# Higher concurrency + JSON output saved next to the report
docker run --rm -v "$PWD:/work" screener ./urls.txt --output ./new_report \
  --concurrency 10 --json ./new_report/results.json

# Process only the first 20 URLs
docker run --rm -v "$PWD:/work" screener ./urls.txt --output ./new_report --max-urls 20

# Use an absolute path for both input and output
docker run --rm -v /data:/data screener /data/urls.txt --output /data/report
```

---

### Troubleshooting

#### Report is written to `/app/...` inside the container and not visible on the host

**Cause:** The Docker image was not rebuilt after a recent change, or the container
was run without a bind mount.

**Fix:**
1. Rebuild the image:
   ```bash
   docker build --no-cache -t screener .
   ```
2. Always mount your current directory at `/work`:
   ```bash
   docker run --rm -v "$PWD:/work" screener ./urls.txt --output ./new_report
   ```

#### Any filename other than `urls.txt` fails with "file not found"

**Cause:** The container does not have access to your host filesystem unless you
bind-mount it. Without `-v "$PWD:/work"`, the container only sees files that were
copied into the image during `docker build` (which includes the repo's `urls.txt`).

**Fix:** Always include `-v "$PWD:/work"` when running, and pass any filename you
want — the bind mount makes all files in your current directory visible:

```bash
docker run --rm -v "$PWD:/work" screener ./my_targets.txt --output ./results
```

#### Container starts but exits immediately with "URL file not found"

Run with `--verbose` to see full error output:

```bash
docker run --rm -v "$PWD:/work" screener ./urls.txt --output ./new_report --verbose
```

The error message includes the exact bind-mount command needed.

_Tested with Python 3.9+_
