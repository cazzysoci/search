#!/usr/bin/env python3
"""Extract useful keywords and phrases from local site dumps.

Usage: python3 search.py dumps example.com
Supports HTML/text files and gzip-compressed files, including Common Crawl-style
WARC files (.warc, .warc.gz). Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import gzip
import html
import os
import re
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

STOPWORDS = set("""a an the and or but if then than so as at by for from in into of on onto to up via with without is am are was were be been being do does did have has had can could may might must shall should will would this that these those it its they them their he she we you i me my our your who what when where why how which not no nor very just also more most less least such about over under after before between during again further once here there all any both each few other some own same too only s t d ll m re ve don doesn didn isn aren wasn weren won wouldn shouldn couldn mustn needn shan theirs yourself yourselves himself herself itself ourselves themselves himself used using use""".split())
TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.UNICODE)
DOMAIN_RE_CACHE: dict[str, re.Pattern[str]] = {}

class TextExtractor(HTMLParser):
    """Strip markup and hidden/non-content regions while keeping useful text."""
    SKIP = {"script", "style", "noscript", "svg", "canvas", "template"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = False
        self.title_parts: list[str] = []
    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        if tag == "title": self.title = True
    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        if tag == "title": self.title = False
        if tag in {"p", "div", "li", "h1", "h2", "h3", "br", "tr"}:
            self.parts.append(" ")
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.title: self.title_parts.append(data)

def domain_pattern(domain: str) -> re.Pattern[str]:
    domain = domain.lower().strip().rstrip(".")
    if domain not in DOMAIN_RE_CACHE:
        escaped = re.escape(domain)
        DOMAIN_RE_CACHE[domain] = re.compile(r"(?<![\w.-])(?:[a-z0-9-]+\.)*" + escaped + r"(?::\d+)?(?:[/:?#]|\b)", re.I)
    return DOMAIN_RE_CACHE[domain]

def matching_domain(value: str, domain: str) -> bool:
    try:
        host = (urlsplit(value.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    d = domain.lower().rstrip(".")
    return host == d or host.endswith("." + d)

def decode(raw: bytes) -> str:
    # HTML dumps commonly use UTF-8; replacement avoids failures on malformed pages.
    return raw.decode("utf-8", errors="replace")

def content_text(raw: bytes) -> tuple[str, str]:
    text = decode(raw)
    # Strip HTTP response headers when present inside WARC payloads.
    if text.startswith("HTTP/") and "\r\n\r\n" in text:
        text = text.split("\r\n\r\n", 1)[1]
    parser = TextExtractor()
    try:
        parser.feed(text)
        body = html.unescape(" ".join(parser.parts))
        title = html.unescape(" ".join(parser.title_parts))
        return title, body
    except Exception:
        return "", re.sub(r"<[^>]+>", " ", text)

def warc_records(data: bytes):
    """Yield (target URI, record type, payload) from concatenated WARC records."""
    pos = 0
    marker = b"WARC/"
    n = len(data)
    while pos < n:
        start = data.find(marker, pos)
        if start < 0: break
        head_end = data.find(b"\r\n\r\n", start)
        sep_len = 4
        if head_end < 0:
            head_end = data.find(b"\n\n", start)
            sep_len = 2
        if head_end < 0: break
        header = data[start:head_end].decode("latin-1", errors="replace")
        length_match = re.search(r"(?im)^Content-Length:\s*(\d+)\s*$", header)
        target_match = re.search(r"(?im)^WARC-Target-URI:\s*(\S+)", header)
        type_match = re.search(r"(?im)^WARC-Type:\s*(\S+)", header)
        body_start = head_end + sep_len
        if not length_match:
            pos = body_start
            continue
        length = int(length_match.group(1))
        end = min(body_start + length, n)
        if target_match:
            yield target_match.group(1), (type_match.group(1).lower() if type_match else ""), data[body_start:end]
        pos = end

def iter_pages(root: Path, domain: str):
    for path in root.rglob("*"):
        if not path.is_file() or path.name.startswith("."):
            continue
        try:
            opener = gzip.open if path.suffix.lower() in {".gz", ".gzip"} else open
            with opener(path, "rb") as f:
                raw = f.read()
        except (OSError, EOFError, PermissionError):
            continue
        if b"WARC/" in raw[:4096] or path.name.lower().endswith((".warc", ".warc.gz", ".warc.gzip")):
            for uri, record_type, payload in warc_records(raw):
                if record_type not in {"response", "resource", "revisit"} or not matching_domain(uri, domain):
                    continue
                # Revisit records usually contain no page content.
                if record_type == "revisit": continue
                title, text = content_text(payload)
                if text.strip(): yield path, uri, title, text
        else:
            # For standalone files, require an explicit matching site URL in the content or filename.
            probe = decode(raw[: min(len(raw), 2_000_000)])
            if domain in path.name.lower() or domain_pattern(domain).search(probe):
                title, text = content_text(raw)
                if text.strip(): yield path, "", title, text

def terms(text: str) -> list[str]:
    out = []
    for token in TOKEN_RE.findall(text.lower().replace("’", "'")):
        token = token.strip("'")
        if len(token) >= 3 and token not in STOPWORDS and not token.isdigit(): out.append(token)
    return out

def main() -> int:
    ap = argparse.ArgumentParser(description="Find high-signal keywords in local site dumps.")
    ap.add_argument("directory", help="Folder containing HTML/text or WARC dumps")
    ap.add_argument("domain", help="Domain to match, e.g. example.com (subdomains included)")
    ap.add_argument("-n", "--limit", type=int, default=30, help="number of results (default: 30)")
    ap.add_argument("--min-count", type=int, default=2, help="minimum total occurrences (default: 2)")
    ap.add_argument("--phrases", choices=("none", "bigrams", "all"), default="bigrams", help="include adjacent 2/3-word phrases")
    args = ap.parse_args()
    root = Path(args.directory)
    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr); return 2
    domain = args.domain.lower().strip()
    domain = re.sub(r"^https?://", "", domain).split("/", 1)[0].split(":", 1)[0].rstrip(".")
    if not domain or "." not in domain:
        print("Error: provide a valid domain, e.g. example.com", file=sys.stderr); return 2

    counts: Counter[str] = Counter()
    docs: Counter[str] = Counter()
    matched = 0
    seen = set()
    for path, uri, title, text in iter_pages(root, domain):
        # Deduplicate exact target URIs where possible.
        key = uri or str(path)
        if key in seen: continue
        seen.add(key); matched += 1
        words = terms(text)
        if not words: continue
        counts.update(words)
        docs.update(set(words))
        # Titles are a strong relevance signal; avoid allowing repeated titles to dominate.
        title_words = terms(title)
        counts.update({w: 2 for w in title_words})
        docs.update(title_words)
        if args.phrases != "none":
            for size in ((2,) if args.phrases == "bigrams" else (2, 3)):
                for i in range(len(words) - size + 1):
                    phrase_words = words[i:i + size]
                    # Avoid phrases formed across distant markup by limiting token run already normalized.
                    counts[" ".join(phrase_words)] += 1
    if not matched:
        print(f"No matching pages found for {domain} under {root}.", file=sys.stderr)
        print("Supported inputs: HTML/text files and gzip-compressed Common Crawl WARC files.", file=sys.stderr)
        return 1

    # Score blends repeated occurrence and spread across pages, damping boilerplate-heavy terms.
    ranked = []
    for term, count in counts.items():
        if count < args.min_count: continue
        document_frequency = docs.get(term, 1)
        score = count * (1.0 + (document_frequency / matched) ** 0.5)
        ranked.append((score, count, document_frequency, term))
    ranked.sort(key=lambda row: (-row[0], -row[1], row[3]))
    print(f"Domain: {domain} | matching pages: {matched} | keywords: {min(args.limit, len(ranked))}")
    print(f"{'#':>3}  {'score':>8}  {'count':>7}  {'pages':>7}  keyword")
    for i, (score, count, df, term) in enumerate(ranked[:max(args.limit, 0)], 1):
        print(f"{i:>3}  {score:>8.1f}  {count:>7}  {df:>7}  {term}")
    if not ranked:
        print("No terms met the minimum count. Try --min-count 1.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
