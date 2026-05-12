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

# Run — paths can be relative or absolute
python screener.py /tmp/test_urls.txt --output /tmp/new_report
```

---

### Docker usage

#### Build the image

```bash
docker build -t screener .
```

#### How paths work in Docker

`url_file` and `--output` are **container-internal** paths.
To read files from the host or write output back to the host you must **bind-mount**
the relevant host directories into the container at the same absolute paths.
The simplest pattern is to mount a shared parent directory:

```bash
docker run --rm \
  -v HOST_DIR:CONTAINER_DIR \
  screener CONTAINER_PATH_TO_URLS --output CONTAINER_PATH_FOR_OUTPUT
```

#### Quick example (using `/tmp`)

```bash
# Place your URLs file on the host
echo "https://example.com" > /tmp/test_urls.txt

# Run — mount /tmp into the container so both the input and output live there
docker run --rm \
  -v /tmp:/tmp \
  screener /tmp/test_urls.txt --output /tmp/new_report

# The report is now on your host at /tmp/new_report/report.html
```

#### Generic pattern for any paths

```bash
# If your URLs file lives at /path/to/urls.txt and you want output at /path/to/output:
docker run --rm \
  -v /path/to:/path/to \
  screener /path/to/urls.txt --output /path/to/output
```

Or mount input and output directories separately (more restrictive):

```bash
docker run --rm \
  -v /path/to/urls_dir:/path/to/urls_dir:ro \
  -v /path/to/output_dir:/path/to/output_dir \
  screener /path/to/urls_dir/urls.txt --output /path/to/output_dir/report
```

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
docker run --rm \
  -v /tmp:/tmp \
  screener /tmp/test_urls.txt --output /tmp/new_report --no-screenshots

# Higher concurrency + JSON output
docker run --rm \
  -v /tmp:/tmp \
  screener /tmp/test_urls.txt --output /tmp/new_report \
  --concurrency 10 --json /tmp/new_report/results.json

# Process only the first 20 URLs with verbose logging
docker run --rm \
  -v /tmp:/tmp \
  screener /tmp/test_urls.txt --output /tmp/new_report \
  --max-urls 20 --verbose
```

_Tested with Python 3.9+_
