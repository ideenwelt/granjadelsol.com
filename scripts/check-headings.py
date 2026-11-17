#!/usr/bin/env python3
"""Check static heading outlines; use --outline to print every heading.

Run with python3 scripts/check-headings.py. No dependencies or file changes.
The gallery's active view must additionally be checked in a browser: its
existing view selection promotes the selected title to H1 and its groups to H2.
"""

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


class Outline(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.stack = []
        self.headings = []
        self.current = None
        self.errors = []
        self.feed(source)
        if self.current is not None:
            self.errors.append("Unclosed heading")

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if re.fullmatch(r"h[1-6]", tag):
            if self.current is not None:
                self.errors.append("Nested heading")
            if any(t == "header" or "logo" in a.get("class", "").split()
                   for t, a in self.stack):
                self.errors.append("Heading used for navigation/branding")
            self.current = {"level": int(tag[1]), "text": "", "line": self.getpos()[0]}
            self.headings.append(self.current)
        if tag not in VOID:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        if re.fullmatch(r"h[1-6]", tag):
            if self.current is None or self.current["level"] != int(tag[1]):
                self.errors.append("Mismatched heading end tag")
            self.current = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outline", action="store_true", help="Print heading levels and texts")
    args = parser.parse_args()
    pages = {str(path.relative_to(ROOT)): Outline(path.read_text(encoding="utf-8"))
             for lang in ("de", "en", "es", "pt")
             for path in sorted((ROOT / lang).glob("*.html"))}
    errors = []
    if len(pages) != 24:
        errors.append("Expected 24 content pages")
    for path, page in pages.items():
        errors.extend(f"{path}: {error}" for error in page.errors)
        levels = [heading["level"] for heading in page.headings]
        if levels.count(1) != 1 or not levels or levels[0] != 1:
            errors.append(f"{path}: expected exactly one leading content H1")
        previous = 0
        for heading in page.headings:
            text = " ".join(heading["text"].split())
            if not text or (heading["level"] == 1 and text == "Granja del Sol"):
                errors.append(f"{path}:{heading['line']}: missing content heading")
            if heading["level"] > previous + 1:
                errors.append(f"{path}:{heading['line']}: H{previous} to H{heading['level']} jump")
            previous = heading["level"]
        if args.outline:
            print(path)
            for heading in page.headings:
                text = " ".join(heading["text"].split())
                print(f"  {'  ' * (heading['level'] - 1)}H{heading['level']} {text}")

    # Existing hreflang groups identify translations of each of the six page types.
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9",
          "x": "http://www.w3.org/1999/xhtml"}
    sitemap = ET.parse(ROOT / "sitemap.xml")
    groups = set()
    for entry in sitemap.findall("s:url", ns):
        paths = set()
        for link in entry.findall("x:link", ns):
            path = urlsplit(link.attrib["href"]).path.lstrip("/")
            paths.add(path + "index.html" if path.endswith("/") else path)
        groups.add(tuple(sorted(paths)))
    if len(groups) != 6:
        errors.append("Expected six translated page groups")
    for group in groups:
        if len(group) != 4 or any(path not in pages for path in group):
            errors.append(f"Incomplete translation group: {group}")
            continue
        outlines = {tuple(h["level"] for h in pages[path].headings) for path in group}
        if len(outlines) != 1:
            errors.append(f"Heading structure differs between translations: {group}")

    if errors:
        print("FAILED:\n- " + "\n- ".join(errors))
        return 1
    print("PASS: 24 content H1s, no branding headings or level jumps, six consistent language groups.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
