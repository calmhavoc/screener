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

# ── Retry / back-off for transient metadata-fetch failures ──────────
MAX_METADATA_RETRIES = 3
BASE_BACKOFF: float = 0.5  # first wait, doubles each retry

# httpx exception types that indicate transient network problems.
_RETRYABLE = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    httpx.TransportError,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.PoolTimeout,
)
# ─────────────────────────────────────────────────────────────────────


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

    /* ── Filter bar ── */
    .filter-bar {
        background: #fff;
        border-radius: 12px;
        box-shadow: 0 6px 20px rgba(0,0,0,0.06);
        padding: 1rem 1.25rem;
        margin-bottom: 1.5rem;
        display: flex;
        flex-wrap: wrap;
        align-items: flex-end;
        gap: 1rem;
    }
    .filter-group {
        display: flex;
        flex-direction: column;
        gap: 0.3rem;
        flex: 1 1 160px;
    }
    .filter-group label {
        font-size: 0.8rem;
        font-weight: 600;
        color: #475569;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .filter-group select {
        padding: 0.45rem 0.7rem;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        font-size: 0.9rem;
        background: #f8fafc;
        color: #111;
        cursor: pointer;
    }
    .filter-group select:focus {
        outline: 2px solid #2a5298;
        outline-offset: 1px;
    }
    .filter-actions {
        display: flex;
        align-items: flex-end;
        gap: 0.75rem;
    }
    #reset-btn {
        padding: 0.47rem 1rem;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        background: #f1f5f9;
        color: #475569;
        font-size: 0.9rem;
        cursor: pointer;
    }
    #reset-btn:hover { background: #e2e8f0; }
    #visible-count {
        font-size: 0.9rem;
        color: #475569;
        white-space: nowrap;
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
    .result[hidden] { display: none !important; }
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
    .no-results {
        grid-column: 1 / -1;
        text-align: center;
        padding: 2rem;
        color: #64748b;
        font-size: 1rem;
    }
    @media (max-width: 720px) {
        header { padding: 1.5rem 1rem; }
        main { padding: 1rem; }
        .filter-bar { flex-direction: column; }
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

    <!-- ── Filter bar ── -->
    <div class="filter-bar" role="search" aria-label="Filter results">
      <div class="filter-group">
        <label for="filter-status">Status code</label>
        <select id="filter-status">
          <option value="">All statuses</option>
          {% for code in status_codes %}
            <option value="{{ code }}">{{ code }}</option>
          {% endfor %}
          {% if has_errors %}
            <option value="error">Error / no response</option>
          {% endif %}
        </select>
      </div>

      <div class="filter-group">
        <label for="filter-server">Server</label>
        <select id="filter-server">
          <option value="">All servers</option>
          {% for srv in servers %}
            <option value="{{ srv }}">{{ srv }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="filter-group">
        <label for="filter-tech">Technology</label>
        <select id="filter-tech">
          <option value="">All technologies</option>
          {% for tech in all_technologies %}
            <option value="{{ tech }}">{{ tech }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="filter-actions">
        <button id="reset-btn" type="button">Reset</button>
        <span id="visible-count"></span>
      </div>
    </div>
    <!-- ── / Filter bar ── -->

    <section class="grid" id="results-grid">
    {% for item in results %}
      <article
        class="result"
        id="card-{{ loop.index }}"
        data-status="{{ item.status if item.status else 'error' }}"
        data-server="{{ item.server | lower }}"
        data-technologies="{{ item.technologies | join(',') | lower }}"
      >
        <header>
          <h2><a href="{{ item.final_url or item.normalised_url }}" target="_blank">{{ item.original_url }}</a></h2>
          <div class="status">
            {% if item.status %}<span>Status {{ item.status }}</span>{% endif %}
            {% if item.response_time %}&#x23F1; {{ '%.2f'|format(item.response_time) }} s{% endif %}
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
          <div class="error">&#x26A0;&#xFE0F; {{ item.error }}</div>
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
      <p class="no-results" id="no-results" hidden>No results match the selected filters.</p>
    </section>
  </main>

  <script>
    (function () {
      var selStatus = document.getElementById('filter-status');
      var selServer = document.getElementById('filter-server');
      var selTech   = document.getElementById('filter-tech');
      var resetBtn  = document.getElementById('reset-btn');
      var countEl   = document.getElementById('visible-count');
      var noResults = document.getElementById('no-results');
      var cards     = Array.from(document.querySelectorAll('.result[id^="card-"]'));

      function applyFilters() {
        var status = selStatus.value;
        var server = selServer.value.toLowerCase();
        var tech   = selTech.value.toLowerCase();
        var visible = 0;

        cards.forEach(function (card) {
          var cardStatus = card.dataset.status;
          var cardServer = card.dataset.server;
          var cardTechs  = card.dataset.technologies;

          var match = true;
          if (status && cardStatus !== status) match = false;
          if (server && cardServer.indexOf(server) === -1) match = false;
          if (tech   && cardTechs.indexOf(tech)   === -1) match = false;

          card.hidden = !match;
          if (match) visible++;
        });

        countEl.textContent = visible + ' of ' + cards.length + ' shown';
        noResults.hidden = visible > 0;
      }

      function resetFilters() {
        selStatus.value = '';
        selServer.value = '';
        selTech.value   = '';
        applyFilters();
      }

      selStatus.addEventListener('change', applyFilters);
      selServer.addEventListener('change', applyFilters);
      selTech.addEventListener('change', applyFilters);
      resetBtn.addEventListener('click', resetFilters);

      // Initialise count on load
      applyFilters();
    })();
  </script>
</body>
</html>
"""


MAIN_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>URL Screener – Aggregate Dashboard</title>
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

    /* ── Filter bar ── */
    .filter-bar {
        background: #fff;
        border-radius: 12px;
        box-shadow: 0 6px 20px rgba(0,0,0,0.06);
        padding: 1rem 1.25rem;
        margin-bottom: 1.5rem;
        display: flex;
        flex-wrap: wrap;
        align-items: flex-end;
        gap: 1rem;
    }
    .filter-group {
        display: flex;
        flex-direction: column;
        gap: 0.3rem;
        flex: 1 1 160px;
    }
    .filter-group label {
        font-size: 0.8rem;
        font-weight: 600;
        color: #475569;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .filter-group select {
        padding: 0.45rem 0.7rem;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        font-size: 0.9rem;
        background: #f8fafc;
        color: #111;
        cursor: pointer;
    }
    .filter-group select:focus {
        outline: 2px solid #2a5298;
        outline-offset: 1px;
    }
    .filter-actions {
        display: flex;
        align-items: flex-end;
        gap: 0.75rem;
    }
    #reset-btn {
        padding: 0.47rem 1rem;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        background: #f1f5f9;
        color: #475569;
        font-size: 0.9rem;
        cursor: pointer;
    }
    #reset-btn:hover { background: #e2e8f0; }
    .refresh-btn {
        padding: 0.47rem 1rem;
        border: 1px solid #2a5298;
        border-radius: 8px;
        background: #2a5298;
        color: #fff;
        font-size: 0.9rem;
        cursor: pointer;
    }
    .refresh-btn:hover { background: #1e3c72; }
    #visible-count {
        font-size: 0.9rem;
        color: #475569;
        white-space: nowrap;
    }
    .loading {
        text-align: center;
        padding: 3rem;
        color: #64748b;
        font-size: 1.1rem;
    }
    .loading .spinner {
        display: inline-block;
        width: 2rem;
        height: 2rem;
        border: 3px solid #e2e8f0;
        border-top-color: #2a5298;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        margin-bottom: 0.75rem;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

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
    .result[hidden] { display: none !important; }
    .result header {
        background: none;
        color: inherit;
        padding: 1.2rem 1.2rem 0.25rem;
    }
    .result header .report-badge {
        display: inline-block;
        font-size: 0.75rem;
        font-weight: 600;
        background: #e0e7ff;
        color: #3730a3;
        padding: 0.15rem 0.55rem;
        border-radius: 999px;
        margin-bottom: 0.35rem;
        text-transform: uppercase;
        letter-spacing: 0.03em;
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
    .no-results {
        grid-column: 1 / -1;
        text-align: center;
        padding: 2rem;
        color: #64748b;
        font-size: 1rem;
    }
    @media (max-width: 720px) {
        header { padding: 1.5rem 1rem; }
        main { padding: 1rem; }
        .filter-bar { flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <h1>URL Screener – Aggregate Dashboard</h1>
    <div class="meta">Dynamically loaded from <span id="report-count">0</span> report folder(s) &middot; <span id="total-urls">0</span> total URLs</div>
  </header>
  <main>
    <div id="loading" class="loading">
      <div class="spinner"></div>
      <div>Loading reports…</div>
    </div>

    <section id="content" hidden>
      <section class="summary">
        <div class="card">
          <strong>Report folders</strong>
          <div id="summary-folders">0</div>
        </div>
        <div class="card">
          <strong>Total URLs</strong>
          <div id="summary-total">0</div>
        </div>
        <div class="card">
          <strong>Successful</strong>
          <div id="summary-successes">0</div>
        </div>
        <div class="card">
          <strong>Failed</strong>
          <div id="summary-failures">0</div>
        </div>
      </section>

      <!-- ── Filter bar ── -->
      <div class="filter-bar" role="search" aria-label="Filter results">
        <div class="filter-group">
          <label for="filter-status">Status code</label>
          <select id="filter-status">
            <option value="">All statuses</option>
          </select>
        </div>

        <div class="filter-group">
          <label for="filter-server">Server</label>
          <select id="filter-server">
            <option value="">All servers</option>
          </select>
        </div>

        <div class="filter-group">
          <label for="filter-tech">Technology</label>
          <select id="filter-tech">
            <option value="">All technologies</option>
          </select>
        </div>

        <div class="filter-group">
          <label for="filter-report">Report folder</label>
          <select id="filter-report">
            <option value="">All folders</option>
          </select>
        </div>

        <div class="filter-actions">
          <button id="reset-btn" type="button">Reset</button>
          <button id="refresh-btn" class="refresh-btn" type="button">&#x21bb; Reload</button>
          <span id="visible-count"></span>
        </div>
      </div>
      <!-- ── / Filter bar ── -->

      <section class="grid" id="results-grid"></section>
    </section>
  </main>

  <script>
    (function () {
      var MANIFEST = 'reports.json';
      var loadingEl  = document.getElementById('loading');
      var contentEl  = document.getElementById('content');
      var gridEl     = document.getElementById('results-grid');

      var selStatus = document.getElementById('filter-status');
      var selServer = document.getElementById('filter-server');
      var selTech   = document.getElementById('filter-tech');
      var selReport = document.getElementById('filter-report');
      var resetBtn  = document.getElementById('reset-btn');
      var refreshBtn= document.getElementById('refresh-btn');
      var countEl   = document.getElementById('visible-count');
      var reportCountEl = document.getElementById('report-count');
      var totalUrlsEl   = document.getElementById('total-urls');
      var summaryFoldersEl = document.getElementById('summary-folders');
      var summaryTotalEl   = document.getElementById('summary-total');
      var summarySuccessesEl = document.getElementById('summary-successes');
      var summaryFailuresEl  = document.getElementById('summary-failures');

      var allCards = [];

      function escapeHtml(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
      }

      function renderCards(cards) {
        gridEl.innerHTML = '';
        cards.forEach(function (card) {
          var article = document.createElement('article');
          article.className = 'result';
          article.id = 'card-' + card.uid;
          article.dataset.status = card.status || 'error';
          article.dataset.server = (card.server || '').toLowerCase();
          article.dataset.technologies = (card.technologies || []).join(',').toLowerCase();
          article.dataset.reportFolder = card.reportFolder.toLowerCase();

          var headerHtml = '<header>';
          headerHtml += '<div class="report-badge">' + escapeHtml(card.reportFolder) + '</div>';
          headerHtml += '<h2><a href="' + escapeHtml(card.finalUrl || card.normalisedUrl) + '" target="_blank">' + escapeHtml(card.originalUrl) + '</a></h2>';
          headerHtml += '<div class="status">';
          if (card.status) headerHtml += '<span>Status ' + card.status + '</span>';
          if (card.responseTime != null) headerHtml += ' &#x23F1; ' + card.responseTime.toFixed(2) + ' s';
          headerHtml += '</div>';
          headerHtml += '<ul class="meta-list">';
          if (card.finalUrl && card.finalUrl !== card.normalisedUrl) headerHtml += '<li>Final URL: ' + escapeHtml(card.finalUrl) + '</li>';
          headerHtml += '<li>Normalised: ' + escapeHtml(card.normalisedUrl) + '</li>';
          headerHtml += '</ul>';
          headerHtml += '</header>';
          article.innerHTML = headerHtml;

          if (card.screenshotPath) {
            var screenshotDiv = document.createElement('div');
            screenshotDiv.className = 'screenshot';
            var img = document.createElement('img');
            img.src = card.reportFolder + '/' + card.screenshotPath;
            img.alt = 'Screenshot of ' + card.originalUrl;
            img.loading = 'lazy';
            screenshotDiv.appendChild(img);
            article.appendChild(screenshotDiv);
          }

          if (card.error) {
            var errorDiv = document.createElement('div');
            errorDiv.className = 'error';
            errorDiv.textContent = '\u26A0\uFE0F ' + card.error;
            article.appendChild(errorDiv);
          }

          var detailsDiv = document.createElement('div');
          detailsDiv.className = 'details';

          if (card.technologies && card.technologies.length > 0) {
            var techSection = document.createElement('div');
            var techStrong = document.createElement('strong');
            techStrong.textContent = 'Detected technologies';
            techSection.appendChild(techStrong);
            techSection.appendChild(document.createElement('br'));
            var techContainer = document.createElement('div');
            techContainer.className = 'technologies';
            card.technologies.forEach(function (tech) {
              var span = document.createElement('span');
              span.textContent = tech;
              techContainer.appendChild(span);
            });
            techSection.appendChild(techContainer);
            detailsDiv.appendChild(techSection);
          }

          if (card.headers && Object.keys(card.headers).length > 0) {
            var details = document.createElement('details');
            var summary = document.createElement('summary');
            summary.textContent = 'Response headers';
            details.appendChild(summary);
            var table = document.createElement('table');
            table.className = 'headers';
            var tbody = document.createElement('tbody');
            var headerKeys = Object.keys(card.headers).sort();
            headerKeys.forEach(function (key) {
              var tr = document.createElement('tr');
              var th = document.createElement('th');
              th.textContent = key;
              var td = document.createElement('td');
              td.textContent = card.headers[key];
              tr.appendChild(th);
              tr.appendChild(td);
              tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            details.appendChild(table);
            detailsDiv.appendChild(details);
          }

          article.appendChild(detailsDiv);

          var noResults = document.getElementById('no-results');
          if (noResults) {
            gridEl.appendChild(noResults);
          }
          gridEl.appendChild(article);
        });
      }

      function populateFilterOptions() {
        var statusSet = new Set();
        var serverSet = new Set();
        var techSet   = new Set();
        var reportSet = new Set();

        allCards.forEach(function (card) {
          statusSet.add(card.status || 'error');
          serverSet.add(card.server || '');
          (card.technologies || []).forEach(function (t) { techSet.add(t); });
          reportSet.add(card.reportFolder);
        });

        function setOptions(sel, values, emptyLabel) {
          sel.innerHTML = '';
          var optAll = document.createElement('option');
          optAll.value = '';
          optAll.textContent = emptyLabel;
          sel.appendChild(optAll);
          var sorted = Array.from(values).sort(function (a, b) { return a.toLowerCase().localeCompare(b.toLowerCase()); });
          sorted.forEach(function (v) {
            if (!v) return;
            var opt = document.createElement('option');
            opt.value = v;
            opt.textContent = v;
            sel.appendChild(opt);
          });
          // add "error" option if status set has it
          if (sel === selStatus && values.has('error')) {
            var optErr = document.createElement('option');
            optErr.value = 'error';
            optErr.textContent = 'Error / no response';
            sel.appendChild(optErr);
          }
        }

        setOptions(selStatus, statusSet, 'All statuses');
        setOptions(selServer, serverSet, 'All servers');
        setOptions(selTech, techSet, 'All technologies');
        setOptions(selReport, reportSet, 'All folders');
      }

      function applyFilters() {
        var status = selStatus.value;
        var server = selServer.value.toLowerCase();
        var tech   = selTech.value.toLowerCase();
        var report = selReport.value.toLowerCase();
        var visible = 0;

        allCards.forEach(function (card) {
          var match = true;
          if (status && (card.status || 'error') !== status) match = false;
          if (server && (card.server || '').toLowerCase().indexOf(server) === -1) match = false;
          if (tech) {
            var techs = (card.technologies || []).join(',').toLowerCase();
            if (techs.indexOf(tech) === -1) match = false;
          }
          if (report && card.reportFolder.toLowerCase().indexOf(report) === -1) match = false;

          var el = document.getElementById('card-' + card.uid);
          if (el) {
            el.hidden = !match;
            if (match) visible++;
          }
        });

        countEl.textContent = visible + ' of ' + allCards.length + ' shown';
        var noResults = document.getElementById('no-results');
        if (!noResults) {
          noResults = document.createElement('p');
          noResults.className = 'no-results';
          noResults.id = 'no-results';
          noResults.textContent = 'No results match the selected filters.';
          gridEl.appendChild(noResults);
        }
        noResults.hidden = visible > 0;
      }

      function resetFilters() {
        selStatus.value = '';
        selServer.value = '';
        selTech.value   = '';
        selReport.value = '';
        applyFilters();
      }

      function updateSummary() {
        var total = allCards.length;
        var successes = 0;
        var failures = 0;
        allCards.forEach(function (c) {
          if (c.error) failures++;
          else successes++;
        });
        var folderSet = new Set(allCards.map(function (c) { return c.reportFolder; }));

        reportCountEl.textContent = folderSet.size;
        totalUrlsEl.textContent = total;
        summaryFoldersEl.textContent = folderSet.size;
        summaryTotalEl.textContent = total;
        summarySuccessesEl.textContent = successes;
        summaryFailuresEl.textContent = failures;
      }

      function loadAll() {
        loadingEl.hidden = false;
        contentEl.hidden = true;
        gridEl.innerHTML = '';
        allCards = [];

        fetch(MANIFEST)
          .then(function (r) {
            if (!r.ok) throw new Error('Failed to load ' + MANIFEST + ' (HTTP ' + r.status + ')');
            return r.json();
          })
          .then(function (manifest) {
            var folders = manifest.reports || [];
            if (folders.length === 0) throw new Error('No report folders found in manifest.');

            var fetches = folders.map(function (folder) {
              return fetch(folder + '/data.json')
                .then(function (r) {
                  if (!r.ok) throw new Error('Failed to load ' + folder + '/data.json (HTTP ' + r.status + ')');
                  return r.json();
                })
                .then(function (data) {
                  var results = data.results || [];
                  var uidCounter = 0;
                  results.forEach(function (item) {
                    allCards.push({
                      uid: 'uid-' + folder + '-' + (uidCounter++),
                      reportFolder: folder,
                      originalUrl: item.original_url,
                      normalisedUrl: item.normalised_url,
                      finalUrl: item.final_url,
                      status: item.status ? String(item.status) : null,
                      responseTime: item.response_time,
                      headers: item.headers || {},
                      server: item.server || '',
                      technologies: item.technologies || [],
                      screenshotPath: item.screenshot_path || null,
                      error: item.error || null,
                    });
                  });
                })
                .catch(function (err) {
                  console.warn('Skipping folder ' + folder + ': ' + err.message);
                });
            });

            return Promise.all(fetches);
          })
          .then(function () {
            if (allCards.length === 0) throw new Error('No results loaded from any report folder.');
            renderCards(allCards);
            populateFilterOptions();
            updateSummary();
            applyFilters();
            loadingEl.hidden = true;
            contentEl.hidden = false;
          })
          .catch(function (err) {
            loadingEl.innerHTML = '<p style="color:#b91c1c;">Error: ' + escapeHtml(err.message) + '</p>' +
              '<p style="font-size:0.9rem;color:#64748b;margin-top:1rem;">' +
              'Make sure you are viewing through an HTTP server, e.g.:<br>' +
              '<code style="background:#f1f5f9;padding:0.3rem 0.6rem;border-radius:6px;">python3 -m http.server 8000</code>' +
              '</p>';
          });
      }

      selStatus.addEventListener('change', applyFilters);
      selServer.addEventListener('change', applyFilters);
      selTech.addEventListener('change', applyFilters);
      selReport.addEventListener('change', applyFilters);
      resetBtn.addEventListener('click', resetFilters);
      refreshBtn.addEventListener('click', loadAll);

      loadAll();
    })();
  </script>
</body>
</html>
"""


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture screenshots and headers for a list of URLs.\n\n"
            "URL_FILE and --output accept relative or absolute paths.\n\n"
            "Docker quick-start (relative to your current directory):\n\n"
            "  docker run --rm -v \"$PWD:/work\" screener ./urls.txt --output ./new_report\n\n"
            "The container mounts your current directory at /work, so relative paths like\n"
            "./urls.txt and ./new_report refer to files in your host working directory.\n"
            "After the run, ./new_report/report.html will be on your host machine."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "url_file",
        type=Path,
        help=(
            "Relative or absolute path to a text file containing one URL per line. "
            "In Docker, relative paths resolve from the bind-mounted /work directory "
            "(i.e. your host current working directory)."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("report"),
        help=(
            "Relative or absolute directory for report.html and screenshots/. "
            "Created automatically if it does not exist. "
            "In Docker, relative paths resolve from the bind-mounted /work directory "
            "(i.e. your host current working directory), so --output ./new_report "
            "will create ./new_report on the host. Default: ./report"
        ),
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
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Enforce SSL/TLS certificate verification (disabled by default)",
    )
    return parser.parse_args(argv)


def load_urls(path: Path, limit: Optional[int] = None) -> List[str]:
    """Load URLs from a file, ignoring empty lines and comments."""

    if not path.exists():
        hint = (
            "\nHint: if you are running inside Docker, your host current directory must "
            "be bind-mounted at /work so the container can see local files.\n"
            f"  docker run --rm -v \"$PWD:/work\" screener {path} --output ./new_report\n"
            "\nRelative paths (e.g. ./urls.txt) resolve from /work inside the container, "
            "which maps to the directory you mount with -v \"$PWD:/work\"."
        )
        raise FileNotFoundError(f"URL file '{path}' does not exist.{hint}")

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
    semaphore: asyncio.Semaphore,
) -> tuple[Optional[httpx.Response], Optional[str], Optional[float]]:
    """GET *url* with retry-and-backoff for transient failures.

    The request is throttled by *semaphore* so that at most N metadata
    fetches run concurrently.  Once an HTTP response is received
    (even 4xx/5xx) the result is returned immediately – no retries for
    application-level status codes.  Only network-level transient errors
    (timeouts, connection resets, pool timeouts, etc.) trigger retries.
    """
    loop = asyncio.get_running_loop()
    start = loop.time()
    last_exc: Optional[Exception] = None

    for attempt in range(1, MAX_METADATA_RETRIES + 1):
        try:
            async with semaphore:
                response = await client.get(url, timeout=timeout)
            elapsed = loop.time() - start
            LOGGER.debug("GET %s → %d (attempt %d/%d)", url, response.status_code, attempt, MAX_METADATA_RETRIES)
            return response, None, elapsed
        except _RETRYABLE as exc:
            last_exc = exc
            if attempt < MAX_METADATA_RETRIES:
                delay = BASE_BACKOFF * (2 ** (attempt - 1))
                LOGGER.debug(
                    "GET %s retryable error (attempt %d/%d): %s %s – retrying in %.1fs",
                    url, attempt, MAX_METADATA_RETRIES, type(exc).__name__, exc, delay,
                )
                await asyncio.sleep(delay)
            else:
                LOGGER.debug(
                    "GET %s failed after %d attempts: %s %s",
                    url, MAX_METADATA_RETRIES, type(exc).__name__, exc,
                )
        except Exception as exc:  # noqa: BLE001 – non-retryable (e.g. programming errors)
            elapsed = loop.time() - start
            return None, f"{type(exc).__name__}: {exc}", elapsed

    # All retries exhausted – include the last exception type & message
    elapsed = loop.time() - start
    assert last_exc is not None
    return None, f"{type(last_exc).__name__}: {last_exc} (after {MAX_METADATA_RETRIES} attempts)", elapsed


async def capture_screenshot(
    browser: Browser,
    url: str,
    destination: Path,
    timeout: float,
    semaphore: asyncio.Semaphore,
    user_agent: str,
    ignore_https_errors: bool,
) -> Optional[str]:
    async with semaphore:
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=user_agent,
            ignore_https_errors=ignore_https_errors,
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
    http_semaphore: asyncio.Semaphore,
    browser: Optional[Browser],
    screenshot_semaphore: Optional[asyncio.Semaphore],
    screenshot_dir: Path,
    timeout: float,
    capture: bool,
    user_agent: str,
    ignore_https_errors: bool,
) -> PageReport:
    normalised = normalise_url(url)
    response, fetch_error, elapsed = await fetch_metadata(client, normalised, timeout, http_semaphore)

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
    if capture and browser is not None and screenshot_semaphore is not None and not fetch_error:
        slug = slugify(final_url or normalised)
        screenshot_path = screenshot_dir / f"{slug}.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_error = await capture_screenshot(
            browser,
            final_url or normalised,
            screenshot_path,
            timeout,
            screenshot_semaphore,
            user_agent,
            ignore_https_errors,
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

    # ── Collect filter option sets ──────────────────────────────────────────
    status_codes: List[str] = sorted(
        {str(r.status) for r in reports if r.status is not None},
        key=lambda s: int(s),
    )
    servers: List[str] = sorted(
        {r.headers.get("server", "").strip() for r in reports if r.headers.get("server", "").strip()},
        key=str.lower,
    )
    all_technologies: List[str] = sorted(
        {tech for r in reports for tech in r.technologies},
        key=str.lower,
    )
    has_errors = any(r.has_error for r in reports)
    # ────────────────────────────────────────────────────────────────────────

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
                # server header value exposed separately for the filter bar
                "server": report.headers.get("server", ""),
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
        # filter option lists
        status_codes=status_codes,
        servers=servers,
        all_technologies=all_technologies,
        has_errors=has_errors,
    )

    output_path.write_text(html, encoding="utf-8")


def write_data_json(
    reports: Sequence[PageReport],
    output_path: Path,
    input_file: Path,
    concurrency: int,
) -> None:
    """Write a machine-readable data.json alongside report.html."""
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
                "server": report.headers.get("server", ""),
                "technologies": report.technologies,
                "screenshot_path": str(screenshot_rel) if screenshot_rel else None,
                "error": report.error,
            }
        )

    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(reports),
        "successes": successes,
        "failures": failures,
        "avg_response_time": f"{avg_response_time:.2f}",
        "concurrency": concurrency,
        "input_file": str(input_file),
        "output_dir": str(output_path.parent.resolve()),
        "results": safe_reports,
    }

    data_path = output_path.parent / "data.json"
    data_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    LOGGER.info("Data written to %s", data_path)


def update_reports_manifest(output_dir: Path) -> None:
    """Add *output_dir* to the aggregate reports.json manifest.

    The manifest lives in the parent of *output_dir* so it can list sibling
    folders.  Each entry is just the folder basename.
    """
    manifest_dir = output_dir.parent
    manifest_path = manifest_dir / "reports.json"

    folder_name = output_dir.name
    known: List[str] = []
    if manifest_path.exists():
        try:
            known = json.loads(manifest_path.read_text(encoding="utf-8")).get("reports", [])
        except (json.JSONDecodeError, Exception):
            known = []

    if folder_name not in known:
        known.append(folder_name)
        known.sort()

    manifest_path.write_text(
        json.dumps({"reports": known}, indent=2),
        encoding="utf-8",
    )
    LOGGER.info("Manifest updated at %s", manifest_path)


def generate_main_html(output_dir: Path) -> None:
    """Write main.html into the parent of *output_dir*."""
    main_path = output_dir.parent / "main.html"
    main_path.write_text(MAIN_HTML_TEMPLATE, encoding="utf-8")
    LOGGER.info("Aggregate dashboard written to %s", main_path)


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

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "report.html"
    screenshot_dir = output_dir / "screenshots"

    headers = {
        "user-agent": args.user_agent,
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
    }

    limits = httpx.Limits(max_connections=args.concurrency * 2, max_keepalive_connections=args.concurrency)
    timeout = httpx.Timeout(args.timeout)

    if not args.verify_ssl:
        LOGGER.warning(
            "TLS certificate verification is disabled. Connections will proceed without validating certificates."
        )

    # Two separate semaphores so that the concurrency parameter caps both
    # the number of simultaneous HTTP metadata fetches and the number of
    # simultaneous browser screenshot sessions independently.
    http_semaphore = asyncio.Semaphore(args.concurrency)
    screenshot_semaphore: Optional[asyncio.Semaphore] = None

    async with httpx.AsyncClient(
        follow_redirects=True,
        headers=headers,
        limits=limits,
        timeout=timeout,
        verify=args.verify_ssl,
    ) as client:
        browser: Optional[Browser] = None
        playwright = None
        if not args.no_screenshots:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=True)
            screenshot_semaphore = asyncio.Semaphore(args.concurrency)

        try:
            tasks = [
                process_url(
                    url,
                    client,
                    http_semaphore,
                    browser,
                    screenshot_semaphore,
                    screenshot_dir,
                    args.timeout,
                    not args.no_screenshots,
                    args.user_agent,
                    ignore_https_errors=not args.verify_ssl,
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

    # ── Write machine-readable data for the aggregate dashboard ──
    write_data_json(reports, output_path, args.url_file, args.concurrency)
    update_reports_manifest(output_dir)
    generate_main_html(output_dir)
    # ─────────────────────────────────────────────────────────────

    if args.json:
        write_json_report(args.json, reports)

    failed_urls = [r.original_url for r in reports if r.has_error]
    if failed_urls:
        fail_file = output_dir / "failed_urls.txt"
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