# Research: Fetching News from ForexFactory, Bloomberg & Yahoo Finance

---

## 1. ForexFactory.com

### The Landscape
ForexFactory has **no official API**. They are known for **aggressive anti-scraping** measures (Cloudflare, rate limiting, IP bans).

### Approaches (Best → Worst)

#### A. Unofficial Python Wrappers (Recommended)
```python
# forex-python or similar community packages
pip install forex-python

# More targeted: FF calendar scraper
pip install ffcal  # ForexFactory Calendar scraper
```
- **`ffcal`** – Scrapes the FF economic calendar. Lightweight, parses the HTML table.
- **`forex-calendar`** – Another wrapper around FF calendar.

#### B. Direct HTML Scraping (with precautions)
```python
import requests
from bs4 import BeautifulSoup

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
    "Accept": "text/html",
    "Accept-Language": "en-US,en;q=0.9",
}

# News page
url = "https://www.forexfactory.com/news"
session = requests.Session()
session.headers.update(headers)
resp = session.get(url)
soup = BeautifulSoup(resp.content, "html.parser")
```

**Key challenges:**
- Cloudflare JS challenge → use `cloudscraper` or `undetected-chromedriver`
- They embed data in HTML tables with class-based selectors that change
- Calendar data is in `<tr>` rows with `data-eventid` attributes

```python
# Bypass Cloudflare
pip install cloudscraper
import cloudscraper
scraper = cloudscraper.create_scraper()
resp = scraper.get("https://www.forexfactory.com/calendar")
```

#### C. Headless Browser (Most Reliable but Slow)
```python
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from seleniumbase import SB  # or undetected-chromedriver

with SB(uc=True) as sb:
    sb.open("https://www.forexfactory.com/calendar")
    html = sb.get_page_source()
```

#### D. RSS Feeds
ForexFactory does **not** offer public RSS feeds anymore (discontinued).

### FF Pro Tips
- Target the **calendar** page (`/calendar`) for economic events — it's the most valuable data
- The **news** page (`/news`) is forum-style, harder to parse
- Use the `week` URL parameter: `/calendar?week=Jan1.2024` for specific weeks
- **Respect rate limits** — 1 request per 10-15 seconds minimum
- Cache aggressively; calendar data doesn't change for past events

---

## 2. Bloomberg

### The Landscape
Bloomberg has **the most aggressive anti-scraping** of the three. They use Cloudflare Enterprise, behavioral analysis, and actively pursue legal action against scrapers. Their paid Terminal/BQNT API costs $20K+/year.

### Approaches (Best → Worst)

#### A. Bloomberg RSS Feeds (Easiest, Legal)
Bloomberg still maintains **public RSS feeds**:

```python
import feedparser

feeds = {
    "top_news": "https://feeds.bloomberg.com/markets/news.rss",
    "economics": "https://feeds.bloomberg.com/economics/news.rss",
    "currencies": "https://feeds.bloomberg.com/currencies/news.rss",
    "markets": "https://feeds.bloomberg.com/markets/news.rss",
}

for category, url in feeds.items():
    feed = feedparser.parse(url)
    for entry in feed.entries[:5]:
        print(f"[{category}] {entry.title} — {entry.link}")
```

**Caveat:** RSS feeds give you **headlines + summaries only**, not full article text. Full-text requires visiting the article URL, which is where scraping gets hard.

#### B. Bloomberg API Endpoints (Reverse-Engineered)
Bloomberg's website makes internal API calls you can mimic:

```python
# Search/stories endpoint (may change)
import requests

url = "https://www.bloomberg.com/lineup-next/api/stories"
params = {
    "limit": 20,
    "pageNumber": 1,
}
headers = {
    "User-Agent": "...",
    "Accept": "application/json",
}
# This endpoint rotates and may require auth tokens
```

⚠️ These endpoints are **undocumented** and change frequently. Not reliable for production.

#### C. Headless Browser with Stealth
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 ...",
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    page.goto("https://www.bloomberg.com/markets")
    # Wait for dynamic content
    page.wait_for_selector('[data-component="headlineList"]')
    headlines = page.query_selector_all("a[href*='/news/']")
    for h in headlines:
        print(h.inner_text())
```

**Problem:** Bloomberg serves a paywall/registration wall after a few articles. They also fingerprint browsers aggressively.

#### D. Third-Party Aggregators
```python
# Using Google News as proxy to Bloomberg articles
from newsapi import NewsApiClient
api = NewsApiClient(api_key='YOUR_KEY')
articles = api.get_everything(sources='bloomberg')
```

### Bloomberg Pro Tips
- **RSS is your best friend** for Bloomberg — it's legal and stable
- For full article text, consider pairing RSS links with a **readability extractor**:
```python
import readability
from lxml import etree
# After fetching article HTML
doc = readability.Document(html_content)
summary = doc.summary()
```
- Bloomberg **Telegram bots** and **Discord feeds** exist that repost Bloomberg content (gray area)
- Consider **Newscatcher API** or **GNews API** which index Bloomberg articles

---

## 3. Yahoo Finance

### The Landscape
Yahoo Finance is the **easiest** of the three. They have well-known unofficial API endpoints, and the community has built robust libraries.

### Approaches (Best → Worst)

#### A. `yfinance` Library (For Market Data + Some News)
```python
import yfinance as yf

ticker = yf.Ticker("EURUSD=X")
# Get news related to ticker
news = ticker.news  # Returns list of dicts with title, url, publisher, etc.
for article in news:
    print(f"{article['title']} - {article['publisher']}")
```

**Limitation:** `ticker.news` returns **limited results** (typically 10-15 articles per ticker) and is ticker-specific, not general market news.

#### B. Yahoo Finance v2 API Endpoints (Reverse-Engineered, Most Powerful)
The internal Yahoo Finance API endpoints are well-documented by the community:

```python
import requests

# General market news
url = "https://query2.finance.yahoo.com/v1/finance/search"
params = {
    "q": "forex EURUSD",
    "newsCount": 20,
    "quotesCount": 0,
}
headers = {"User-Agent": "Mozilla/5.0 ..."}
resp = requests.get(url, params=params, headers=headers)
data = resp.json()
for article in data.get("news", []):
    print(f"{article['title']} — {article['url']}")

# Trending news
url_trending = "https://query2.finance.yahoo.com/v1/finance/trending/US"
resp = requests.get(url_trending, headers=headers)

# Specific topic feeds
topics = {
    "business": "https://query2.finance.yahoo.com/v1/finance/topic/business",
    "tech": "https://query2.finance.yahoo.com/v1/finance/topic/tech",
    "markets": "https://query2.finance.yahoo.com/v1/finance/topic/markets",
}
```

#### C. Full News Listing API
```python
# More comprehensive news endpoint
url = "https://finance.yahoo.com/news/"

# Or the API that powers the news page:
url = "https://query1.finance.yahoo.com/ws/insights/v1/finance/insights"
params = {
    "allCount": 50,
    "certifiedCount": 0,
    "streamCount": 50,
}
```

#### D. RSS Feeds (Still Available)
```python
import feedparser

# Yahoo Finance RSS (some still work)
feeds = [
    "https://finance.yahoo.com/news/rssindex",
    "https://finance.yahoo.com/rss/topstories",
]
for url in feeds:
    feed = feedparser.parse(url)
    for entry in feed.entries[:10]:
        print(entry.title, entry.link)
```

#### E. BeautifulSoup Scraping
```python
import requests
from bs4 import BeautifulSoup

url = "https://finance.yahoo.com/topic/stock-market-news/"
headers = {"User-Agent": "Mozilla/5.0 ..."}
resp = requests.get(url, headers=headers)
soup = BeautifulSoup(resp.text, "html.parser")

# Yahoo renders most content via JS now, so this is limited
# You'll get better results with the API endpoints above
```

### Yahoo Finance Pro Tips
- `query2.finance.yahoo.com` endpoints are **the gold standard** — community has mapped them extensively
- No API key needed (for now), but Yahoo has been known to add/remove auth requirements
- For **forex-specific news**, query tickers like `"EURUSD=X"`, `"GBPUSD=X"`, etc.
- Use `yfinance` for convenience, raw API for control
- Full article content still requires visiting the page; use `readability` or `newspaper3k`:
```python
from newspaper import Article
article = Article(url)
article.download()
article.parse()
print(article.text)
```

---

## Cross-Cutting Solutions

### Production-Grade Architecture

```
┌─────────────────────────────────────────────┐
│              Scheduler (APScheduler)         │
│           Runs every 5-15 minutes            │
└──────────────┬──────────────────────────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌───────┐ ┌────────┐ ┌──────────┐
│  FF   │ │Bloom-  │ │  Yahoo   │
│Scraper│ │berg RSS│ │  API v2  │
│(cloud-│ │(feed-  │ │(requests)│
│scraper│ │parser) │ │          │
│ + BS4)│ │        │ │          │
└───┬───┘ └───┬────┘ └────┬─────┘
    │         │           │
    ▼         ▼           ▼
┌──────────────────────────────┐
│     Normalizer / Deduper     │
│  - Unified schema            │
│  - Remove duplicates by URL  │
│  - Classify by currency pair │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│   Storage (PostgreSQL/Redis) │
│   + Optional: NLP pipeline   │
│     (sentiment analysis)     │
└──────────────────────────────┘
```

### Unified Data Model
```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class NewsArticle:
    source: str          # "forexfactory", "bloomberg", "yahoo"
    title: str
    url: str
    summary: str
    published_at: datetime
    fetched_at: datetime
    symbols: list[str]   # ["EURUSD", "GBPUSD"]
    sentiment: float | None = None  # -1.0 to 1.0
```

### Anti-Ban Strategy (All Sources)
```python
import time, random
from fake_useragent import UserAgent

ua = UserAgent()

class RateLimitedSession:
    def __init__(self, min_delay=10, max_delay=25):
        self.session = requests.Session()
        self.min_delay = min_delay
        self.max_delay = max_delay
    
    def get(self, url, **kwargs):
        self.session.headers.update({"User-Agent": ua.random})
        resp = self.session.get(url, **kwargs)
        time.sleep(random.uniform(self.min_delay, self.max_delay))
        return resp
    
    def rotate_proxy(self, proxy_list):
        # Optional: rotate through residential proxies
        proxy = random.choice(proxy_list)
        self.session.proxies.update(proxy)
```

### Full Article Extraction (Works for All)
```python
# Best libraries for extracting article body from any URL
pip install newspaper3k readability-lxml trafilatura

# Trafilatura is currently the most reliable
import trafilatura

def extract_article(url):
    downloaded = trafilatura.fetch_url(url)
    text = trafilatura.extract(downloaded)
    metadata = trafilatura.extract(
        downloaded, output_format="json", include_metadata=True
    )
    return text, metadata
```

---

## Summary Comparison

| Feature | ForexFactory | Bloomberg | Yahoo Finance |
|---|---|---|---|
| **Easiest method** | `cloudscraper` + BS4 | RSS feeds | `yfinance` / API v2 |
| **Anti-scraping** | High (Cloudflare) | Very High | Low-Medium |
| **Full article text** | Yes (forum posts) | Hard (paywall) | Medium (JS render) |
| **Forex-specific** | ⭐⭐⭐⭐⭐ Best | ⭐⭐⭐ Good | ⭐⭐⭐ Good |
| **Reliability** | Medium | Low (w/o RSS) | High |
| **Rate limit** | ~1 req/15s | ~1 req/30s | ~1 req/5s |
| **API stability** | Fragile | RSS stable, rest fragile | Community-known endpoints |

### Recommendation Stack
1. **Yahoo Finance** → `query2.finance.yahoo.com` API endpoints (no auth, reliable, rich data)
2. **Bloomberg** → RSS feeds for headlines + `trafilatura` for full text extraction
3. **ForexFactory** → `cloudscraper` + BeautifulSoup for calendar; headless browser as fallback for news
4. **All three** → Cache in DB, deduplicate by URL, run on staggered intervals
