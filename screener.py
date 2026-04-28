#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import httpx
from bs4 import BeautifulSoup
from jinja2 import Environment, select_autoescape
from playwright.async_api import Browser, Page, async_playwright


LOGGER = logging.getLogger("screener")


@dataclass(slots=True)
class PageReport:
    """Result of processing a single URL."""

    original_url: str
    normalised_url: str
    final_url: Optional[str]
    status: Optional[int]
    response_time: Optional[float]
    headers: Dict[str, str]
    technologies: List[str]
    screenshot_path: Optional[Path]
    error: Optional[str]

    @property
    def has_error(self) -> bool:
        return self.error is not None


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>URL Screener Report</title>
  <style>
    :root { color-scheme: light dark; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
        background: #f5f7fb;
        color: #111;
    }
    header {
        background: linear-gradient(120deg, #1e3c72, #2a5298);
        color: #fff;
        padding: 2rem 1.5rem 1.5rem;
    }
    header h1 { margin: 0 0 0.5rem; font-size: 2rem; }
    header .meta { font-size: 0.95rem; opacity: 0.85; }
    main { padding: 1.5rem; }
    .summary {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 1rem;
        margin-bottom: 2rem;
    }
    .summary .card {
        background: #fff;
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 6px 20px rgba(0,0,0,0.06);
    }
    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
        gap: 1.5rem;
    }
    .result {
        background: #fff;
        border-radius: 16px;
        overflow: hidden;
        box-shadow: 0 10px 30px rgba(15, 23, 42, 0.12);
        display: flex;
        flex-direction: column;
        min-height: 100%;
    }
    .result header {
        background: none;
        color: inherit;
        padding: 1.2rem 1.2rem 0.25rem;
    }
    .result header h2 {
        font-size: 1.1rem;
        margin: 0 0 0.35rem;
        line-height: 1.4;
        word-break: break-word;
    }
    .result header .status {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.9rem;
        color: #475569;
    }
    .result header .status span {
        background: rgba(59, 130, 246, 0.12);
        color: #1d4ed8;
        padding: 0.2rem 0.5rem;
        border-radius: 999px;
    }
    .meta-list {
        list-style: none;
        padding: 0;
        margin: 0.5rem 0 0;
        font-size: 0.9rem;
        color: #475569;
    }
    .meta-list li { margin-bottom: 0.25rem; }
    .screenshot {
        display: block;
        width: 100%;
        background: #0f172a;
    }
    .screenshot img {
        display: block;
        width: 100%;
        height: auto;
    }
    .details {
        padding: 1.2rem;
        display: grid;
        gap: 1rem;
    }
    .technologies {
        background: #f1f5f9;
        border-radius: 10px;
        padding: 0.75rem 1rem;
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
    }
    .technologies span {
        background: #fff;
        border-radius: 999px;
        padding: 0.2rem 0.65rem;
        font-size: 0.85rem;
        box-shadow: 0 2px 4px rgba(15, 23, 42, 0.08);
    }
    details {
        background: #f8fafc;
        border-radius: 10px;
        padding: 0.75rem 1rem;
    }
    details summary {
        font-weight: 600;
        cursor: pointer;
        margin: -0.75rem -1rem 0.5rem;
        padding: 0.75rem 1rem;
    }
    table.headers {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85rem;
    }
    table.headers th, table.headers td {
        text-align: left;
        padding: 0.3rem 0.4rem;
    }
    table.headers tr:nth-child(odd) { background: rgba(148, 163, 184, 0.1); }
    .error {
        background: rgba(220, 38, 38, 0.12);
        color: #b91c1c;
        border-left: 4px solid #dc2626;
        padding: 0.75rem 1rem;
        border-radius: 0 10px 10px 0;
        margin: 1rem 1.2rem 1.2rem;
    }
    @media (max-width: 720px) {
        header { padding: 1.5rem 1rem; }
        main { padding: 1rem; }
    }
  </style>
</head>
<body>
  <header>
    <h1>URL Screener Report</h1>
    <div class="meta">Generated {{ generated_at }} &middot; Total URLs: {{ total }} &middot; Success: {{ successes }} &middot; Failed: {{ failures }}</div>
  </header>
  <main>
    <section class="summary">
      <div class="card">
        <strong>Input file</strong>
        <div>{{ input_file }}</div>
      </div>
      <div class="card">
        <strong>Output directory</strong>
        <div>{{ output_dir }}</div>
      </div>
      <div class="card">
        <strong>Average response time</strong>
        <div>{{ avg_response_time }} s</div>
      </div>
      <div class="card">
        <strong>Concurrency</strong>
        <div>{{ concurrency }}</div>
      </div>
    </section>

    <section class="grid">
    {% for item in results %}
      <article class="result" id="card-{{ loop.index }}">
        <header>
          <h2><a href="{{ item.final_url or item.normalised_url }}" target="_blank">{{ item.original_url }}</a></h2>
          <div class="status">
            {% if item.status %}<span>Status {{ item.status }}</span>{% endif %}
            {% if item.response_time %}⏱ {{ '%.2f'|format(item.response_time) }} s{% endif %}
          </div>
          <ul class="meta-list">
            {% if item.final_url and item.final_url != item.normalised_url %}<li>Final URL: {{ item.final_url }}</li>{% endif %}
            <li>Normalised: {{ item.normalised_url }}</li>
          </ul>
        </header>

        {% if item.screenshot_path %}
          <div class="screenshot">
            <img src="{{ item.screenshot_path }}" alt="Screenshot of {{ item.original_url }}">
          </div>
        {% endif %}

        {% if item.error %}
          <div class="error">⚠️ {{ item.error }}</div>
        {% endif %}

        <div class="details">
          {% if item.technologies %}
          <div>
            <strong>Detected technologies</strong>
            <div class="technologies">
              {% for tech in item.technologies %}
                <span>{{ tech }}</span>
              {% endfor %}
            </div>
          </div>
          {% endif %}

          {% if item.headers %}
          <details>
            <summary>Response headers</summary>
            <table class="headers">
              <tbody>
                {% for key, value in item.headers.items() %}
                  <tr><th>{{ key }}</th><td>{{ value }}</td></tr>
                {% endfor %}
              </tbody>
            </table>
          </details>
          {% endif %}
        </div>
      </article>
    {% endfor %}
    </section>
  </main>
</body>
</html>
"""


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture screenshots and headers for a list of URLs.")
    parser.add_argument("url_file", type=Path, help="Path to a text file containing one URL per line")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("report.html"),
        help="Destination HTML report path (default: ./report.html)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Maximum number of concurrent browser fetches (default: 5)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds for HTTP fetch and navigation (default: 30)",
    )
    parser.add_argument(
        "--user-agent",
        default=
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36",
        help="Custom User-Agent string",
    )
    parser.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Skip screenshot capture and only collect metadata",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        default=None,
        help="Limit the number of URLs processed from the input file",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional path to write raw result data as JSON",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args(argv)


def load_urls(path: Path, limit: Optional[int] = None) -> List[str]:
    """Load URLs from a file, ignoring empty lines and comments."""

    if not path.exists():
        raise FileNotFoundError(f"URL file {path} does not exist")

    urls: List[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
            if limit and len(urls) >= limit:
                break
    return urls


def normalise_url(url: str) -> str:
    if re.match(r"^https?://", url, flags=re.IGNORECASE):
        return url
    return f"https://{url}"


def slugify(url: str) -> str:
    slug = re.sub(r"https?://", "", url, flags=re.IGNORECASE)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "site"


def detect_technologies(headers: Dict[str, str], html: Optional[str]) -> List[str]:
    insights: List[str] = []

    significant_headers = [
        "server",
        "x-powered-by",
        "via",
        "x-aspnet-version",
        "x-generator",
    ]
    for header in significant_headers:
        value = headers.get(header)
        if value:
            insights.append(f"{header.title()}: {value}")

    content_type = headers.get("content-type")
    if content_type:
        insights.append(f"Content-Type: {content_type}")

    if not html:
        return sorted(set(insights))

    soup = BeautifulSoup(html, "html.parser")
    generator = soup.find("meta", attrs={"name": re.compile("generator", re.I)})
    if generator and generator.get("content"):
        insights.append(f"Generator: {generator['content']}")

    meta_powered = soup.find("meta", attrs={"name": re.compile("powered", re.I)})
    if meta_powered and meta_powered.get("content"):
        insights.append(f"Meta powered: {meta_powered['content']}")

    html_lower = html.lower()
    heuristics = {
        "WordPress": ["wp-content", "wp-includes", "wordpress"],
        "Drupal": ["drupal-settings", "drupal"],
        "Shopify": ["cdn.shopify.com", "shopify"],
        "Squarespace": ["squarespace"],
        "Wix": ["wixstatic", "wix.com"],
        "Angular": ["ng-version", "angular"],
        "React": ["data-reactroot", "react"],
        "Vue.js": ["data-v-app", "vue"],
        "jQuery": ["jquery"],
    }

    for label, markers in heuristics.items():
        if any(marker in html_lower for marker in markers):
            insights.append(label)

    return sorted(set(insights))


async def fetch_metadata(
    client: httpx.AsyncClient,
    url: str,
    timeout: float,
) -> tuple[Optional[httpx.Response], Optional[str], Optional[float]]:
    loop = asyncio.get_running_loop()
    start = loop.time()
    try:
        response = await client.get(url, timeout=timeout)
        elapsed = loop.time() - start
        return response, None, elapsed
    except Exception as exc:  # noqa: BLE001
        elapsed = loop.time() - start
        return None, str(exc), elapsed


async def capture_screenshot(
    browser: Browser,
    url: str,
    destination: Path,
    timeout: float,
    semaphore: asyncio.Semaphore,
    user_agent: str,
) -> Optional[str]:
    async with semaphore:
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=user_agent,
        )
        page: Page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            await page.set_viewport_size({"width": 1600, "height": 900})
            await page.wait_for_timeout(1000)
            await page.screenshot(path=str(destination), full_page=True)
        except Exception as exc:  # noqa: BLE001
            await context.close()
            return str(exc)
        await context.close()
    return None


async def process_url(
    url: str,
    client: httpx.AsyncClient,
    browser: Optional[Browser],
    semaphore: Optional[asyncio.Semaphore],
    screenshot_dir: Path,
    timeout: float,
    capture: bool,
    user_agent: str,
) -> PageReport:
    normalised = normalise_url(url)
    response, fetch_error, elapsed = await fetch_metadata(client, normalised, timeout)

    headers: Dict[str, str] = {}
    technologies: List[str] = []
    html_content: Optional[str] = None
    status_code: Optional[int] = None
    final_url: Optional[str] = None

    if response is not None:
        final_url = str(response.url)
        headers = {k.lower(): v for k, v in response.headers.items()}
        status_code = response.status_code
        content_type = headers.get("content-type", "")
        if content_type.lower().startswith("text/") or "html" in content_type.lower():
            html_content = response.text
        else:
            try:
                html_content = response.text
            except Exception:  # noqa: BLE001
                html_content = None
        technologies = detect_technologies(headers, html_content)

    screenshot_path: Optional[Path] = None
    screenshot_error: Optional[str] = None
    if capture and browser is not None and semaphore is not None and not fetch_error:
        slug = slugify(final_url or normalised)
        screenshot_path = screenshot_dir / f"{slug}.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_error = await capture_screenshot(
            browser,
            final_url or normalised,
            screenshot_path,
            timeout,
            semaphore,
            user_agent,
        )
        if screenshot_error:
            screenshot_path = None

    error_message: Optional[str] = fetch_error or screenshot_error

    return PageReport(
        original_url=url,
        normalised_url=normalised,
        final_url=final_url,
        status=status_code,
        response_time=elapsed,
        headers=headers,
        technologies=technologies,
        screenshot_path=screenshot_path,
        error=error_message,
    )


def render_report(
    reports: Sequence[PageReport],
    output_path: Path,
    input_file: Path,
    concurrency: int,
) -> None:
    env = Environment(autoescape=select_autoescape(["html", "xml"]))
    template = env.from_string(HTML_TEMPLATE)

    successes = sum(1 for report in reports if not report.has_error)
    failures = len(reports) - successes
    response_times = [r.response_time for r in reports if r.response_time]
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0.0

    safe_reports = []
    for report in reports:
        safe_headers = dict(sorted(report.headers.items()))
        screenshot_rel = None
        if report.screenshot_path:
            try:
                screenshot_rel = report.screenshot_path.relative_to(output_path.parent)
            except ValueError:
                screenshot_rel = report.screenshot_path
        safe_reports.append(
            {
                "original_url": report.original_url,
                "normalised_url": report.normalised_url,
                "final_url": report.final_url,
                "status": report.status,
                "response_time": report.response_time,
                "headers": safe_headers,
                "technologies": report.technologies,
                "screenshot_path": str(screenshot_rel) if screenshot_rel else None,
                "error": report.error,
            }
        )

    html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total=len(reports),
        successes=successes,
        failures=failures,
        avg_response_time=f"{avg_response_time:.2f}",
        concurrency=concurrency,
        input_file=str(input_file),
        output_dir=str(output_path.parent.resolve()),
        results=safe_reports,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def write_json_report(path: Path, reports: Sequence[PageReport]) -> None:
    serialisable = [
        {
            "original_url": r.original_url,
            "normalised_url": r.normalised_url,
            "final_url": r.final_url,
            "status": r.status,
            "response_time": r.response_time,
            "headers": r.headers,
            "technologies": r.technologies,
            "screenshot_path": str(r.screenshot_path) if r.screenshot_path else None,
            "error": r.error,
        }
        for r in reports
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialisable, indent=2), encoding="utf-8")


async def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    urls = load_urls(args.url_file, args.max_urls)
    if not urls:
        LOGGER.error("No URLs found in %s", args.url_file)
        return 1

    LOGGER.info("Processing %d URLs with concurrency=%d", len(urls), args.concurrency)

    output_path = args.output.resolve()
    screenshot_dir = output_path.parent / "screenshots"

    headers = {
        "user-agent": args.user_agent,
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
    }

    limits = httpx.Limits(max_connections=args.concurrency * 2, max_keepalive_connections=args.concurrency)
    timeout = httpx.Timeout(args.timeout)

    async with httpx.AsyncClient(follow_redirects=True, headers=headers, limits=limits, timeout=timeout) as client:
        browser: Optional[Browser] = None
        semaphore: Optional[asyncio.Semaphore] = None
        if not args.no_screenshots:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=True)
            semaphore = asyncio.Semaphore(args.concurrency)
        else:
            playwright = None

        try:
            tasks = [
                process_url(
                    url,
                    client,
                    browser,
                    semaphore,
                    screenshot_dir,
                    args.timeout,
                    not args.no_screenshots,
                    args.user_agent,
                )
                for url in urls
            ]
            reports = await asyncio.gather(*tasks)
        finally:
            if browser is not None:
                await browser.close()
            if not args.no_screenshots and playwright is not None:
                await playwright.stop()

    render_report(reports, output_path, args.url_file, args.concurrency)
    if args.json:
        write_json_report(args.json, reports)

    failed_urls = [r.original_url for r in reports if r.has_error]
    if failed_urls:
        fail_file = output_path.parent / "failed_urls.txt"
        fail_file.write_text("\n".join(failed_urls) + "\n", encoding="utf-8")
        LOGGER.warning("%d URLs failed. See %s", len(failed_urls), fail_file)

    LOGGER.info("Report written to %s", output_path)
    return 0


def main() -> None:
    try:
        exit_code = asyncio.run(run())
    except KeyboardInterrupt:  # noqa: CTRL-C
        LOGGER.error("Interrupted by user")
        exit_code = 130
    sys.exit(exit_code)


if __name__ == "__main__":
    main()