## URL screenshotter and metadata collector.

This script reads a list of URLs from a text file, captures full-page
screenshots, collects HTTP headers, infers basic technology fingerprints, and
produces an HTML report summarising the results.

### Key features:
    * Asynchronous fetching with httpx for efficient parallelism.
    * Headless Chromium screenshots powered by Playwright.
    * Technology hints derived from response headers and HTML markers.
    * Responsive HTML report rendered via Jinja2.

### Example usage::
    python screener.py urls.txt --output out/report.html --concurrency 6

### Dependencies::
    pip install httpx jinja2 beautifulsoup4 playwright
    playwright install chromium

_Tested with Python 3.9+_