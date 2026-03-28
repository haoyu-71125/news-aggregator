"""Global Briefing — News Aggregator"""

import time
import re
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

import feedparser
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FEEDS = [
    {"name": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en", "has_dates": True},
    {"name": "WSJ World", "url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml", "has_dates": True},
    {"name": "WSJ Markets", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "has_dates": True},
    {"name": "WSJ Business", "url": "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml", "has_dates": True},
    {"name": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar", "has_dates": False},
    {"name": "Bloomberg Markets", "url": "https://feeds.bloomberg.com/markets/news.rss", "has_dates": True},
    {"name": "Bloomberg Politics", "url": "https://feeds.bloomberg.com/politics/news.rss", "has_dates": True},
    {"name": "Bloomberg Tech", "url": "https://feeds.bloomberg.com/technology/news.rss", "has_dates": True},
    {"name": "McKinsey", "url": "https://www.mckinsey.com/insights/rss", "has_dates": True},
]

# Maps feed name -> canonical outlet for cross-source counting
OUTLET_MAP = {
    "Reuters": "Reuters",
    "WSJ World": "WSJ", "WSJ Markets": "WSJ", "WSJ Business": "WSJ",
    "Nikkei Asia": "Nikkei",
    "Bloomberg Markets": "Bloomberg", "Bloomberg Politics": "Bloomberg",
    "Bloomberg Tech": "Bloomberg",
    "McKinsey": "McKinsey",
}

CATEGORIES = {
    "Climate & Green Finance": [
        "climate", "green bond", "green finance", "carbon", "emission",
        "renewable", "energy transition", "sustainability", "esg",
        "clean energy", "solar", "wind power", "net zero", "paris agreement",
        "climate adaptation", "climate mitigation", "carbon credit",
        "carbon market", "green taxonomy", "blended finance",
        "climate risk", "stranded asset", "decarboniz",
    ],
    "Infrastructure & Development Finance": [
        "infrastructure", "development bank", "world bank", "imf",
        "asian development bank", "adb", "aiib", "mdb",
        "multilateral", "gcf", "green climate fund", "ifc",
        "development finance", "jica", "jbic", "ebrd",
        "project finance", "ppp", "public-private partnership",
        "sovereign debt", "concessional", "oda",
    ],
    "Geopolitics & International Affairs": [
        "geopolitics", "diplomacy", "sanctions", "trade war",
        "nato", "united nations", "g7", "g20", "brics",
        "security", "conflict", "treaty", "bilateral",
        "indo-pacific", "south china sea", "taiwan",
        "nuclear", "arms", "defense", "alliance",
        "middle east", "ukraine", "russia",
    ],
    "Technology & Innovation": [
        "artificial intelligence", " ai ", "machine learning",
        "semiconductor", "chip", "quantum", "blockchain",
        "cybersecurity", "5g", "6g", "autonomous",
        "robotics", "biotech", "fintech", "digital",
        "tech regulation", "data privacy", "big tech",
        "startup", "venture capital", "openai", "nvidia",
    ],
}

RELEVANCE_KEYWORDS = {
    # Core MPP topics (weight 5)
    "climate finance": 5, "green bond": 5, "infrastructure financing": 5,
    "development bank": 5, "world bank": 5, "green climate fund": 5,
    "gcf": 5, "multilateral development": 5,
    "blended finance": 5, "concessional": 5,
    # Strong relevance (weight 3)
    "climate": 3, "carbon": 3, "emission": 3, "infrastructure": 3,
    "imf": 3, "adb": 3, "aiib": 3, "ifc": 3, "jica": 3,
    "renewable energy": 3, "energy transition": 3, "esg": 3,
    "geopolitics": 3, "diplomacy": 3, "indo-pacific": 3,
    "trade policy": 3, "sanctions": 3, "mdb": 3,
    # Moderate relevance (weight 2)
    "artificial intelligence": 2, "semiconductor": 2,
    "g7": 2, "g20": 2, "brics": 2,
    "united nations": 2, "nato": 2, "japan": 2, "asia": 2,
    "sustainability": 2, "net zero": 2, "paris agreement": 2,
    "oda": 2, "development": 2,
    # Mild relevance (weight 1)
    "economy": 1, "market": 1, "policy": 1, "regulation": 1,
    "china": 1, "trade": 1, "investment": 1, "global": 1,
    "finance": 1, "bank": 1, "security": 1, "technology": 1,
}

REGION_KEYWORDS = {
    "Greater China": [
        "china", "japan", "korea", "taiwan", "north korea", "tokyo",
        "beijing", "shanghai", "hong kong", "seoul", "pyongyang", "dprk",
        "chinese", "japanese", "korean", "nikkei", "yen", "renminbi",
        "xi jinping", "kishida", "okinawa", "shenzhen", "taipei",
    ],
    "ASEAN": [
        "asean", "southeast asia", "indonesia", "philippines", "vietnam",
        "singapore", "thailand", "malaysia", "myanmar", "cambodia", "laos",
        "brunei", "jakarta", "manila", "hanoi", "bangkok",
    ],
    "Europe": [
        "europe", "eu ", "uk ", "britain", "germany", "france", "brussels",
        "london", "paris", "berlin", "italy", "spain", "european", "ecb",
        "bank of england", "scandinavia", "nordic", "nato", "ukraine",
        "russia", "poland", "netherlands", "switzerland", "greece",
    ],
    "Middle East": [
        "middle east", "iran", "israel", "saudi", "emirates", "qatar",
        "iraq", "syria", "strait of hormuz", "gulf state", "opec",
        "yemen", "lebanon", "jordan", "tehran", "riyadh", "dubai",
    ],
    "North America": [
        "us ", "usa", "united states", "america", "canada", "wall street",
        "washington", "fed ", "federal reserve", "congress", "new york",
        "trump", "white house", "pentagon", "treasury", "canadian",
    ],
    "LATAM": [
        "latin america", "brazil", "mexico", "argentina", "colombia",
        "chile", "peru", "venezuela", "caribbean", "central america",
        "cuba", "ecuador", "bolivia", "panama", "costa rica",
    ],
}

# Regions with boosted article limits (user focuses on APAC)
APAC_REGIONS = {"Greater China", "ASEAN"}
MAX_PER_CATEGORY_APAC = 20  # higher cap for APAC regions

_STOP_WORDS = frozenset({
    "the", "and", "for", "that", "this", "with", "from", "have",
    "been", "will", "says", "said", "their", "they", "after",
    "over", "about", "into", "what", "when", "more", "than",
    "also", "amid", "just", "could", "would", "should",
    "news", "report", "update", "latest",
})

REASON_TEMPLATES = {
    "Climate & Green Finance": "Relevant to climate finance and green transition — core MPP focus area",
    "Infrastructure & Development Finance": "Covers development finance / MDBs — directly relevant to your career goals",
    "Geopolitics & International Affairs": "Important context for international affairs and policy studies",
    "Technology & Innovation": "Tech trend with policy and economic implications",
    "Breaking / Trending": "General news worth staying informed about",
}

# Simple in-memory cache
_cache = {"data": None, "timestamp": 0}
CACHE_TTL = 3600  # 1 hour

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

MAX_PER_CATEGORY = 15

# ---------------------------------------------------------------------------
# Feed fetching & parsing
# ---------------------------------------------------------------------------

def fetch_feed(feed_config):
    """Fetch and parse a single RSS feed. Returns list of article dicts."""
    articles = []
    try:
        resp = requests.get(feed_config["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        total_items = len(parsed.entries)
        for idx, entry in enumerate(parsed.entries):
            pub_dt = _parse_date(entry) if feed_config["has_dates"] else None
            summary = entry.get("summary") or entry.get("description") or ""
            # Strip HTML tags from summary
            summary = re.sub(r"<[^>]+>", "", summary).strip()
            articles.append({
                "title": entry.get("title", "").strip(),
                "link": entry.get("link", ""),
                "source": feed_config["name"],
                "published": pub_dt,
                "summary": summary[:300],
                "feed_position": idx,
                "feed_total": total_items,
            })
    except Exception as e:
        return articles, f"{feed_config['name']}: {e}"
    return articles, None


def _parse_date(entry):
    """Try multiple strategies to extract a datetime from a feed entry."""
    # feedparser's parsed time struct
    for field in ("published_parsed", "updated_parsed"):
        ts = entry.get(field)
        if ts:
            try:
                return datetime(*ts[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    # Raw string fallback
    for field in ("published", "updated"):
        raw = entry.get(field)
        if raw:
            try:
                return parsedate_to_datetime(raw)
            except Exception:
                pass
    return None

# ---------------------------------------------------------------------------
# Filtering, scoring, categorization
# ---------------------------------------------------------------------------

def filter_by_date(articles, hours=48):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = []
    for a in articles:
        if a["published"] is None:
            result.append(a)  # no date → assume recent
        elif a["published"] >= cutoff:
            result.append(a)
    return result


def _extract_content_words(title):
    """Extract meaningful words from a title for clustering."""
    words = re.sub(r"[^a-z\s]", "", title.lower()).split()
    return frozenset(w for w in words if len(w) > 3 and w not in _STOP_WORDS)


def _jaccard(set_a, set_b):
    """Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def cluster_articles(articles):
    """Group articles about the same story across sources.
    Marks duplicates and annotates each article with cross-source count."""
    OUTLET_PRIORITY = ["Reuters", "Bloomberg", "WSJ", "Nikkei", "McKinsey"]

    # Extract content words
    for a in articles:
        a["_words"] = _extract_content_words(a["title"])

    # Greedy single-pass clustering
    clusters = []
    for article in articles:
        placed = False
        for cluster in clusters:
            if _jaccard(article["_words"], cluster[0]["_words"]) >= 0.3:
                cluster.append(article)
                placed = True
                break
        if not placed:
            clusters.append([article])

    # Annotate each article with cluster metadata
    result = []
    for cluster in clusters:
        outlet_names = list({OUTLET_MAP.get(a["source"], a["source"]) for a in cluster})
        cross_count = len(outlet_names)

        # Pick canonical article: best outlet priority, then best feed position
        def canonical_key(a):
            outlet = OUTLET_MAP.get(a["source"], a["source"])
            prio = OUTLET_PRIORITY.index(outlet) if outlet in OUTLET_PRIORITY else 99
            pos_ratio = a.get("feed_position", 0) / max(a.get("feed_total", 1), 1)
            return (prio, pos_ratio)

        cluster_sorted = sorted(cluster, key=canonical_key)
        canonical = cluster_sorted[0]

        for a in cluster:
            a["cross_source_count"] = cross_count
            a["co_sources"] = outlet_names
            a["is_duplicate"] = (a is not canonical)

    # Clean up temp field, return flat list
    for a in articles:
        a.pop("_words", None)
    return articles


def _recency_score(published_dt):
    if published_dt is None:
        return 1
    age_hours = (datetime.now(timezone.utc) - published_dt).total_seconds() / 3600
    if age_hours < 4:
        return 3
    if age_hours < 12:
        return 2
    if age_hours < 24:
        return 1
    return 0


def _position_score(feed_position, feed_total):
    if feed_total <= 0:
        return 0
    ratio = feed_position / feed_total
    if ratio <= 0.10:
        return 2
    if ratio <= 0.30:
        return 1
    return 0


def _cross_source_score(cross_source_count):
    if cross_source_count >= 4:
        return 10
    if cross_source_count == 3:
        return 6
    if cross_source_count == 2:
        return 3
    return 0


def compute_final_score(article):
    """Combine importance signals (65%) with keyword relevance (35%).
    Articles in APAC regions (Greater China, ASEAN) get a boost."""
    kw_score, matched_kws = score_article(article)
    kw_normalized = min(kw_score / 10.0, 1.0) * 5.0

    recency = _recency_score(article.get("published"))
    position = _position_score(article.get("feed_position", 0),
                               article.get("feed_total", 1))
    cross_src = _cross_source_score(article.get("cross_source_count", 1))

    importance_score = cross_src + recency + position
    raw_score = importance_score * 0.65 + kw_normalized * 0.35

    # Boost APAC-region articles (user's focus area)
    region = classify_region(article)
    boost = 1.5 if region in APAC_REGIONS else 0
    final_score = raw_score + boost

    return final_score, matched_kws, importance_score, raw_score


def score_article(article):
    text = (article["title"] + " " + article.get("summary", "")).lower()
    score = 0
    matched = []
    for kw, weight in RELEVANCE_KEYWORDS.items():
        if kw in text:
            score += weight
            matched.append(kw)
    return score, matched


def categorize_article(article):
    text = (article["title"] + " " + article.get("summary", "")).lower()
    best_cat = "Breaking / Trending"
    best_count = 0
    for cat, keywords in CATEGORIES.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count = count
            best_cat = cat
    return best_cat


def classify_region(article):
    text = (article["title"] + " " + article.get("summary", "")).lower()
    best_region = "Other"
    best_count = 0
    for region, keywords in REGION_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count = count
            best_region = region
    return best_region


def generate_reason(category, matched_keywords, article):
    co_sources = article.get("co_sources", [])
    cross_count = article.get("cross_source_count", 1)
    published = article.get("published")
    recency = _recency_score(published)

    parts = []

    # Cross-source signal
    if cross_count >= 2:
        source_list = ", ".join(sorted(co_sources))
        parts.append(f"Covered by {cross_count} outlets ({source_list})")

    # Recency signal
    if recency == 3 and published:
        age_h = int((datetime.now(timezone.utc) - published).total_seconds() / 3600)
        parts.append(f"Breaking: {age_h}h ago")
    elif recency == 2 and not parts:
        parts.append("Fresh story (4-12h old)")

    # Category base reason
    base = REASON_TEMPLATES.get(category, "General news")
    if matched_keywords:
        top = matched_keywords[:2]
        base = f"{base} (keywords: {', '.join(top)})"

    if parts:
        return " — ".join(parts) + " — " + base
    return base

# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def get_aggregated_news():
    all_articles = []
    errors = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_feed, f): f for f in FEEDS}
        for future in futures:
            articles, err = future.result()
            all_articles.extend(articles)
            if err:
                errors.append(err)

    # Filter by date
    all_articles = filter_by_date(all_articles, hours=48)

    # Cluster articles across sources and mark duplicates
    all_articles = cluster_articles(all_articles)

    # Keep only canonical articles (non-duplicates)
    all_articles = [a for a in all_articles if not a.get("is_duplicate", False)]

    categorized = {}
    all_regions = list(REGION_KEYWORDS.keys()) + ["Other"]
    regions_summary = {r: {"count": 0, "top_headline": "", "top_score": 0}
                       for r in all_regions}

    for a in all_articles:
        final_score, matched_kws, importance, raw_score = compute_final_score(a)
        category = categorize_article(a)
        region = classify_region(a)
        reason = generate_reason(category, matched_kws, a)

        a["score"] = round(final_score, 2)
        a["raw_score"] = round(raw_score, 2)
        a["importance_score"] = importance
        a["reason"] = reason
        a["category"] = category
        a["region"] = region
        a["source_count"] = a.get("cross_source_count", 1)
        a["co_sources"] = a.get("co_sources", [])

        # Track region summary
        rs = regions_summary[region]
        rs["count"] += 1
        if a["score"] > rs["top_score"]:
            rs["top_score"] = a["score"]
            rs["top_headline"] = a["title"][:80]

        # Serialize datetime
        if a["published"]:
            a["published_iso"] = a["published"].isoformat()
        else:
            a["published_iso"] = None
        del a["published"]

        # Remove internal fields
        for key in ("feed_position", "feed_total", "cross_source_count",
                     "is_duplicate", "cluster_id"):
            a.pop(key, None)

        categorized.setdefault(category, []).append(a)

    # Sort each category by score desc, cap at MAX_PER_CATEGORY
    ordered_cats = [
        "Climate & Green Finance",
        "Infrastructure & Development Finance",
        "Geopolitics & International Affairs",
        "Technology & Innovation",
        "Breaking / Trending",
    ]
    result = {}
    for cat in ordered_cats:
        items = categorized.get(cat, [])
        items.sort(key=lambda x: x["score"], reverse=True)
        result[cat] = items[:MAX_PER_CATEGORY]

    return {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "categories": result,
        "regions_summary": regions_summary,
        "errors": errors,
    }

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/news")
def api_news():
    force = request.args.get("force", "0") == "1"
    now = time.time()
    if not force and _cache["data"] and (now - _cache["timestamp"]) < CACHE_TTL:
        return jsonify(_cache["data"])

    data = get_aggregated_news()
    _cache["data"] = data
    _cache["timestamp"] = now
    return jsonify(data)


if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('FLASK_DEBUG', 'False') == 'True'
    app.run(debug=debug, host='0.0.0.0', port=port)
