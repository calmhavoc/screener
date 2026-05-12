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

```bash
docker build -t screener .
```

#### How it works

The container sets its working directory to `/work`.
When you mount your current directory at `/work`, relative paths like
`./urls.txt` and `./new_report` resolve directly to files in your host
working directory — so the output appears locally after the container exits.

#### Run (current-directory paths)

```bash
# urls.txt must exist in your current directory
docker run --rm -v "$PWD:/work" screener ./urls.txt --output ./new_report

# The report is now on your host at ./new_report/report.html
```

#### How paths work

| What you pass | What it resolves to (inside container) | Appears on host at |
|---|---|---|
| `./urls.txt` | `/work/urls.txt` | `$PWD/urls.txt` |
| `./new_report` | `/work/new_report` | `$PWD/new_report` |
| `/abs/path/file.txt` | `/abs/path/file.txt` | requires matching `-v /abs/path:/abs/path` |

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

_Tested with Python 3.9+_
