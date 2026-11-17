#!/usr/bin/env python3
"""Read-only checks for the static site's URLs, metadata and tracking.

Run from any directory: python3 scripts/check-discoverability.py
Uses only the Python standard library; makes no network requests or changes.
"""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
import re
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://granjadelsol.com/"
UMAMI = "https://cloud.umami.is/script.js"
WEBSITE_ID = "4964bf27-c2f3-4cb7-9a11-6171bdb02b49"
LOCALES = {"de": "de_DE", "en": "en_US", "es": "es_PY", "pt": "pt_BR"}
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9",
      "x": "http://www.w3.org/1999/xhtml"}


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.raw = path.read_text(encoding="utf-8")
        self.tags = []
        self.title = ""
        self.in_title = False
        self.feed(self.raw)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data

    def select(self, tag, **attrs):
        return [a for t, a in self.tags if t == tag
                and all(a.get(k) == v for k, v in attrs.items())]

    def meta(self, key):
        return [a.get("content", "") for t, a in self.tags if t == "meta"
                and a.get("property", a.get("name")) == key]


def canonical(path):
    return BASE + path.replace("/index.html", "/")


def local_path(url):
    path = unquote(urlsplit(url).path).lstrip("/")
    return path + "index.html" if not path or path.endswith("/") else path


def main():
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    pages = {str(p.relative_to(ROOT)): Page(p) for lang in LOCALES
             for p in sorted((ROOT / lang).glob("*.html"))}
    check(len(pages) == 24, "Expected 24 content pages")
    all_pages = {**pages, "index.html": Page(ROOT / "index.html")}

    for path, page in pages.items():
        links = page.select("link", rel="canonical")
        check([a.get("href") for a in links] == [canonical(path)],
              f"{path}: expected exactly one self-canonical")
        tracking = page.select("script", src=UMAMI)
        check(len(tracking) == 1 and tracking[0].get("data-website-id") == WEBSITE_ID
              and "defer" in tracking[0], f"{path}: wrong or duplicate Umami embedding")
        required = ["og:type", "og:title", "og:description", "og:url", "og:image",
                    "og:image:type", "og:image:width", "og:image:height",
                    "og:image:alt", "og:locale", "og:site_name", "twitter:card",
                    "twitter:title", "twitter:description", "twitter:image"]
        for key in required:
            values = page.meta(key)
            check(len(values) == 1 and bool(values[0].strip()), f"{path}: missing/duplicate {key}")
        check(page.meta("og:url") == [canonical(path)], f"{path}: incorrect og:url")
        check(page.meta("og:locale") == [LOCALES[path.split('/')[0]]], f"{path}: incorrect locale")
        for key in ["og:image", "twitter:image"]:
            for value in page.meta(key):
                check(value.startswith(BASE) and (ROOT / local_path(value)).is_file(),
                      f"{path}: missing/nonlocal social image {value}")
        if not path.endswith(("/index.html", "/fotos.html")):
            for key in ["og:title", "twitter:title"]:
                check(page.meta(key) == [page.title], f"{path}: {key} differs from existing title")
            for key in ["og:description", "twitter:description"]:
                check(page.meta(key) == page.meta("description"), f"{path}: {key} differs from description")
            check(page.meta("twitter:image:alt") == page.meta("og:image:alt"),
                  f"{path}: inconsistent social image descriptions")

    for path, page in all_pages.items():
        for attrs in page.select("a"):
            href = attrs.get("href")
            if not href:
                continue
            url = urlsplit(urljoin(canonical(path), href))
            if url.netloc != "granjadelsol.com":
                continue
            check(not re.fullmatch(r"/(de|en|es|pt)/index\.html", url.path),
                  f"{path}: noncanonical homepage link {href}")
            target = local_path(url.geturl())
            check((ROOT / target).is_file(), f"{path}: missing link target {href}")
            if url.fragment and target in all_pages:
                ids = {a.get("id") for _, a in all_pages[target].tags}
                check(unquote(url.fragment) in ids, f"{path}: missing fragment {href}")
        if path.endswith("/fotos.html"):
            check('"index.html' not in page.raw, f"{path}: old gallery fallback URL")

    root = all_pages["index.html"]
    check(root.meta("robots") == ["noindex,follow"], "Root must remain noindex,follow")
    check(not root.select("meta", **{"http-equiv": "refresh"}), "Root must not use meta refresh")
    root_links = {urljoin(BASE, a["href"]) for a in root.select("a") if "href" in a}
    check(root_links == {BASE + lang + "/" for lang in LOCALES}, "Root language links are incomplete")

    try:
        sitemap = ET.parse(ROOT / "sitemap.xml").getroot()
        entries = sitemap.findall("s:url", NS)
        urls = [entry.findtext("s:loc", namespaces=NS) for entry in entries]
        check(len(urls) == 24 and len(set(urls)) == 24, "Sitemap must contain 24 unique URLs")
        check(set(urls) == {canonical(path) for path in pages}, "Sitemap does not match content pages")
        groups = {entry.findtext("s:loc", namespaces=NS):
                  {a.get("hreflang"): a.get("href") for a in entry.findall("x:link", NS)}
                  for entry in entries}
        for url, group in groups.items():
            check(set(group) == {"de", "en-US", "es", "pt-BR", "x-default"}, f"{url}: incomplete hreflang")
            check(url in group.values() and group.get("x-default") == group.get("de"), f"{url}: incorrect self/default language")
            for target in group.values():
                check(groups.get(target) == group, f"{url}: hreflang is not reciprocal for {target}")
        root_alts = {a.get("hreflang"): a.get("href") for a in root.select("link", rel="alternate")}
        check(root_alts == groups.get(BASE + "de/"), "Root hreflang differs from homepage group")
    except ET.ParseError as error:
        errors.append(f"Invalid sitemap XML: {error}")

    if errors:
        print("Discoverability checks FAILED:\n- " + "\n- ".join(errors), file=sys.stderr)
        return 1
    print("PASS: 24 canonicals, preferred internal URLs and fragments, social metadata/images,")
    print("      24 single Umami embeddings, root language links/noindex, sitemap and hreflang.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
