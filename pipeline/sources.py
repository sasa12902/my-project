from __future__ import annotations

import http.client
import random
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Iterable

from dateutil import parser as date_parser

from .models import RawItem, SourceType
from .text import normalize_text, utc_now

HTTP_TIMEOUT = 12.0
USER_AGENT = "mining-intelligence-aggregator/0.1 (+research prototype)"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "form"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "div", "article", "main", "section", "li", "h1", "h2", "h3"}:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "form"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        self._parts.append(data)

    @property
    def text(self) -> str:
        return normalize_text(" ".join(self._parts))


class SourceCollector:
    source_type: SourceType
    source_name: str

    def collect(self, days: int, limit: int) -> list[RawItem]:
        raise NotImplementedError


class RssCollector(SourceCollector):
    def __init__(self, source_type: SourceType, source_name: str, feed_urls: Iterable[str]) -> None:
        self.source_type = source_type
        self.source_name = source_name
        self.feed_urls = list(feed_urls)

    def collect(self, days: int, limit: int) -> list[RawItem]:
        cutoff = utc_now() - timedelta(days=days)
        items: list[RawItem] = []
        for feed_url in self.feed_urls:
            feed_text = _fetch_url(feed_url)
            if not feed_text:
                continue
            for entry in _parse_rss_entries(feed_text):
                published = _parse_date(entry.get("published") or entry.get("updated"))
                if published < cutoff:
                    continue
                url = entry.get("link", "")
                summary = normalize_text(entry.get("summary", ""))
                content = normalize_text(entry.get("content", "")) or summary
                if url:
                    full_text = _fetch_article_text(url)
                    if len(full_text) > len(content):
                        content = full_text
                items.append(
                    RawItem(
                        source_type=self.source_type,
                        source_name=self.source_name,
                        url=url,
                        title=normalize_text(entry.get("title", "")),
                        published_at=published,
                        summary=summary,
                        content=content,
                        metadata={"feed_url": feed_url},
                    )
                )
                if len(items) >= limit:
                    return items
        return items


class HtmlListingCollector(SourceCollector):
    def __init__(
        self,
        source_type: SourceType,
        source_name: str,
        urls: Iterable[str],
        keywords: Iterable[str] = (),
    ) -> None:
        self.source_type = source_type
        self.source_name = source_name
        self.urls = list(urls)
        self.keywords = [item.lower() for item in keywords]

    def collect(self, days: int, limit: int) -> list[RawItem]:
        items: list[RawItem] = []
        now = utc_now()
        for url in self.urls:
            html = _fetch_url(url)
            if not html:
                continue
            extractor = _TextExtractor()
            extractor.feed(html)
            page_text = extractor.text
            title = normalize_text(extractor.title) or self.source_name
            if self.keywords and not any(keyword in page_text.lower() for keyword in self.keywords):
                continue
            items.append(
                RawItem(
                    source_type=self.source_type,
                    source_name=self.source_name,
                    url=url,
                    title=title,
                    published_at=now,
                    summary=page_text[:360],
                    content=page_text[:6000],
                    metadata={"listing_url": url},
                )
            )
        cutoff = now - timedelta(days=days)
        return [item for item in items if item.published_at >= cutoff][:limit]


def default_collectors() -> dict[SourceType, list[SourceCollector]]:
    return {
        "news": [
            RssCollector(
                "news",
                "Mining.com RSS",
                [
                    "https://www.mining.com/feed/",
                    "https://www.mining.com/category/markets/commodities/feed/",
                ],
            )
        ],
        "policy": [
            HtmlListingCollector(
                "policy",
                "China Rare Earth Group",
                ["https://www.crecg.com/"],
                ["稀土", "政策", "矿产", "rare earth"],
            ),
            HtmlListingCollector(
                "policy",
                "Australia DISR Critical Minerals",
                [
                    "https://www.industry.gov.au/publications/critical-minerals-strategy-2023-2030",
                    "https://www.industry.gov.au/mining-oil-and-gas/minerals/critical-minerals",
                ],
                ["critical minerals", "lithium", "export", "strategy"],
            ),
        ],
        "price": [
            HtmlListingCollector(
                "price",
                "LME Metals",
                ["https://www.lme.com/en/Metals/Non-ferrous"],
                ["copper", "zinc", "nickel", "price", "settlement"],
            ),
            HtmlListingCollector(
                "price",
                "SHFE Lithium and Metals",
                ["https://www.shfe.com.cn/"],
                ["锂", "铜", "锌", "镍", "价格", "期货"],
            ),
            HtmlListingCollector(
                "price",
                "Mysteel Iron Ore",
                ["https://www.mysteel.net/"],
                ["iron ore", "铁矿石", "price", "价格"],
            ),
        ],
    }


def collect_all(days: int = 30, limit_per_source_type: int = 200, fill_synthetic: bool = True) -> list[RawItem]:
    all_items: list[RawItem] = []
    for source_type, collectors in default_collectors().items():
        type_items: list[RawItem] = []
        per_collector_limit = max(limit_per_source_type, 20)
        for collector in collectors:
            try:
                type_items.extend(collector.collect(days=days, limit=per_collector_limit))
            except (OSError, ValueError, http.client.HTTPException) as exc:
                print(f"collector_failed source={collector.source_name!r} error={type(exc).__name__}: {exc}")
            if len(type_items) >= limit_per_source_type:
                break
        if fill_synthetic and len(type_items) < limit_per_source_type:
            type_items.extend(
                synthetic_items(
                    source_type=source_type,
                    count=limit_per_source_type - len(type_items),
                    days=days,
                    offset=len(type_items),
                )
            )
        all_items.extend(type_items[:limit_per_source_type])
    return all_items


def synthetic_items(source_type: SourceType, count: int, days: int, offset: int = 0) -> list[RawItem]:
    now = utc_now()
    commodities = ["lithium", "copper", "nickel", "zinc", "iron ore", "rare earths"]
    countries = ["Australia", "China", "Indonesia", "Chile", "Peru", "Canada"]
    policy_actions = ["export review", "royalty update", "permitting reform", "processing subsidy", "environmental review"]
    price_moves = ["rose", "fell", "held steady", "traded mixed", "rebounded"]
    items: list[RawItem] = []
    for i in range(count):
        seq = offset + i + 1
        day_offset = seq % max(days, 1)
        published = now - timedelta(days=day_offset, hours=seq % 23)
        commodity = commodities[seq % len(commodities)]
        country = countries[seq % len(countries)]
        if source_type == "news":
            title = f"{country} {commodity} mine update highlights supply and project risks #{seq}"
            content = (
                f"{country} mining operators reported new developments affecting {commodity} supply. "
                f"The update covers production guidance, project timing, financing conditions and downstream demand. "
                f"Analysts noted that logistics, permitting and energy costs remain important variables for the next 30 days."
            )
            source_name = "Synthetic Mining News"
        elif source_type == "policy":
            action = policy_actions[seq % len(policy_actions)]
            title = f"{country} critical minerals policy {action} affects {commodity} market #{seq}"
            content = (
                f"{country} authorities discussed a {action} related to critical minerals and {commodity}. "
                f"The policy note may affect export controls, strategic stockpiles, processing incentives or approval timelines. "
                f"Market participants should monitor official guidance and implementation dates."
            )
            source_name = "Synthetic Critical Minerals Policy"
        else:
            move = price_moves[seq % len(price_moves)]
            price = 800 + (seq * 37) % 12000
            title = f"{commodity} benchmark price {move} as inventories and demand shifted #{seq}"
            content = (
                f"{commodity} benchmark prices {move} near {price} in the latest session. "
                f"Drivers included exchange inventories, spot demand, macro sentiment and supply interruptions. "
                f"The observation is suitable for retrieval tests and should be replaced with licensed market data in production."
            )
            source_name = "Synthetic Metals Price"
        items.append(
            RawItem(
                source_type=source_type,
                source_name=source_name,
                url=f"synthetic://{source_type}/{seq}",
                title=title,
                published_at=published,
                summary=content[:220],
                content=content,
                metadata={
                    "commodity": commodity,
                    "country": country,
                    "is_synthetic": True,
                    "sequence": seq,
                },
            )
        )
    random.shuffle(items)
    return items


def _parse_date(value: str | None) -> datetime:
    if not value:
        return utc_now()
    try:
        parsed = date_parser.parse(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return utc_now()


def _parse_rss_entries(feed_text: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError:
        return []
    entries: list[dict[str, str]] = []
    for node in root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        entries.append(
            {
                "title": _child_text(node, "title"),
                "link": _entry_link(node),
                "summary": _child_text(node, "description") or _child_text(node, "summary"),
                "content": _child_text(node, "{http://purl.org/rss/1.0/modules/content/}encoded"),
                "published": _child_text(node, "pubDate") or _child_text(node, "published"),
                "updated": _child_text(node, "updated"),
            }
        )
    return entries


def _child_text(node: ET.Element, name: str) -> str:
    child = node.find(name)
    if child is None:
        return ""
    return normalize_text("".join(child.itertext()))


def _entry_link(node: ET.Element) -> str:
    link = _child_text(node, "link")
    if link:
        return link
    atom_link = node.find("{http://www.w3.org/2005/Atom}link")
    if atom_link is not None:
        return atom_link.attrib.get("href", "")
    return ""


def _fetch_article_text(url: str) -> str:
    html = _fetch_url(url)
    if not html:
        return ""
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.text[:12000]


def _fetch_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, http.client.HTTPException):
        return ""
