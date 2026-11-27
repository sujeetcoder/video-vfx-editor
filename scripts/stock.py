#!/usr/bin/env python3
"""Free stock search: Openverse, Wikimedia, NASA (no keys). Scores metadata, writes credits.

Never CC-BY-NC. Pixabay only if the user supplies PIXABAY_KEY.

    python scripts/stock.py "city night" --count 6 --json
    python scripts/stock.py "city night" --download 1 --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import InvalidInput, add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, project_root, read_json, record_stage, work_dir,  # noqa: E402
                    write_json)

UA = {"User-Agent": "video-vfx-editor/0.1 (local editing)"}
BAD_LICENSES = ("by-nc", "noncommercial", "by-nd")
STOPWORDS = set("""the a an and or but if then than this that these those is are was were be been
being of to in on for with at by from as it its i you he she we they my your our their there here
what which who how why when where not no yes do does did done can could should would will just
very really about into over under more most some any all one two get got make made""".split())
WORD_RE = re.compile(r"[A-Za-z\u0900-\u097F][A-Za-z\u0900-\u097F'-]{2,}")


def keywords(text: str, k: int = 6) -> str:
    """Pure-python RAKE-style keyword extraction for stock queries."""
    words = WORD_RE.findall((text or "").lower())
    freq, degree = {}, {}
    for i, word in enumerate(words):
        if word in STOPWORDS:
            continue
        freq[word] = freq.get(word, 0) + 1
        if i and words[i - 1] not in STOPWORDS:
            degree[word] = degree.get(word, 0) + 1
    scored = {w: (freq[w] + degree.get(w, 0)) * (1 + min(len(w), 12) / 24) for w in freq}
    ranked = sorted(scored, key=lambda w: (-scored[w], w))[:k]
    return " ".join(ranked)


def _get(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def search_openverse(query: str, count: int) -> list:
    url = ("https://api.openverse.org/v1/images/?"
           + urllib.parse.urlencode({"q": query, "page_size": count, "license_type": "all"}))
    data = _get(url)
    out = []
    for item in data.get("results", []):
        licence = (item.get("license") or "").lower()
        if any(bad in licence for bad in BAD_LICENSES):
            continue  # never surface a non-commercial asset
        out.append({
            "provider": "openverse", "title": item.get("title") or query,
            "url": item.get("url"), "thumb": item.get("thumbnail"),
            "width": item.get("width"), "height": item.get("height"),
            "license": item.get("license"), "license_version": item.get("license_version"),
            "creator": item.get("creator"), "source": item.get("foreign_landing_url"),
            "orientation": "portrait" if (item.get("height") or 0) > (item.get("width") or 0)
            else ("landscape" if item.get("width") else "square"),
        })
    return out


def search_wikimedia(query: str, count: int) -> list:
    params = {"action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}",
              "gsrnamespace": "6", "gsrlimit": str(count), "prop": "imageinfo",
              "iiprop": "url|size|extmetadata", "iiurlwidth": "640", "format": "json"}
    data = _get("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_short = ((meta.get("LicenseShortName") or {}).get("value") or "").lower()
        if any(bad in license_short.replace("_", "-") for bad in BAD_LICENSES):
            continue
        out.append({
            "provider": "wikimedia", "title": page.get("title", query),
            "url": info.get("url"), "thumb": info.get("thumburl"),
            "width": info.get("width"), "height": info.get("height"),
            "license": license_short or "see file page",
            "creator": (meta.get("Artist") or {}).get("value"),
            "source": info.get("descriptionurl"),
            "orientation": "portrait" if (info.get("height") or 0) > (info.get("width") or 0) else "landscape",
        })
    return out


def search_nasa(query: str, count: int) -> list:
    data = _get("https://images-api.nasa.gov/search?"
                + urllib.parse.urlencode({"q": query, "media_type": "image"}))
    out = []
    for item in (data.get("collection") or {}).get("items", [])[:count]:
        d = item.get("data", [{}])[0]
        link = (item.get("links") or [{}])[0].get("href")
        out.append({
            "provider": "nasa", "title": d.get("title", query), "url": link, "thumb": link,
            "width": None, "height": None, "license": "public-domain (NASA)",
            "creator": d.get("photographer") or d.get("center"), "source": "https://images.nasa.gov",
            "orientation": "landscape",
        })
    return out


def score(asset: dict, want: str = "9:16") -> dict:
    w, h = asset.get("width") or 0, asset.get("height") or 0
    notes = []
    s = 0.5
    if w and h:
        if min(w, h) >= 1080:
            s += 0.2
        else:
            notes.append("low resolution")
        want_portrait = want in ("9:16", "4:5")
        if (h > w) == want_portrait:
            s += 0.15
        else:
            notes.append("orientation differs from the deliverable (crop will lose pixels)")
    else:
        notes.append("unknown dimensions")
    if not any(bad in (asset.get("license") or "").lower() for bad in BAD_LICENSES):
        s += 0.1
    else:
        s -= 0.6
        notes.append("licence not usable")
    if not asset.get("creator"):
        notes.append("credit unknown")
    asset["score"] = round(min(s, 1.0), 2)
    asset["notes"] = notes
    return asset


def search(query: str, count: int, provider: str = "auto") -> list:
    providers = [provider] if provider != "auto" else ["openverse", "wikimedia", "nasa"]
    results = []
    for name in providers:
        try:
            fn = {"openverse": search_openverse, "wikimedia": search_wikimedia, "nasa": search_nasa}[name]
            results.extend(fn(query, count))
        except Exception as exc:  # noqa: BLE001 - network sources fail independently
            log(f"WARN {name} search failed: {exc}")
        if len(results) >= count * 2:
            break
    if os.environ.get("PIXABAY_KEY") and provider in ("auto", "pixabay"):
        results.extend(_pixabay(query, count))
    return results


def _pixabay(query: str, count: int) -> list:
    key = os.environ["PIXABAY_KEY"]
    data = _get("https://pixabay.com/api/?"
                + urllib.parse.urlencode({"key": key, "q": query, "per_page": count, "image_type": "photo"}))
    return [{"provider": "pixabay", "title": item.get("tags", query), "url": item.get("largeImageURL"),
             "thumb": item.get("previewURL"), "width": item.get("imageWidth"),
             "height": item.get("imageHeight"), "license": "pixabay-content-license",
             "creator": item.get("user"), "source": item.get("pageURL"),
             "orientation": "portrait" if (item.get("imageHeight") or 0) > (item.get("imageWidth") or 0)
             else "landscape"} for item in data.get("hits", [])]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Free stock search with credits")
    add_common(parser)
    parser.add_argument("query", nargs="?", default=None)
    parser.add_argument("--from-transcript", default=None,
                        help="derive keywords from a words.json transcript")
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--provider", default="auto", choices=["auto", "openverse", "wikimedia", "nasa", "pixabay"])
    parser.add_argument("--aspect", default="9:16")
    parser.add_argument("--download", default=None, help="asset number(s) to download, e.g. 1,3")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)

    with stage("stock", args) as run:
        query = args.query
        if args.from_transcript:
            transcript = read_json(args.from_transcript, {})
            text = transcript.get("text") or " ".join(
                str(w.get("w", "")) for w in transcript.get("words", []))
            query = query or keywords(text)
            log(f"keywords from transcript: {query}")
        if not query:
            raise InvalidInput("no search query",
                               fix='pass a query or --from-transcript edit/work/.../words.json')
        args.query = query
        assets = [score(a, args.aspect) for a in search(query, args.count, args.provider)]
        assets.sort(key=lambda a: a["score"], reverse=True)
        work = work_dir(root, "stock")
        index = work / "stock.json"
        credits = work / "credits.json"
        write_json(index, {"query": args.query, "assets": assets})
        write_json(credits, {"query": args.query,
                             "assets": [{"title": a["title"], "creator": a["creator"],
                                         "license": a["license"], "source": a["source"]}
                                        for a in assets]})
        downloaded = []
        if args.download:
            picks = [int(x) for x in args.download.split(",") if x.strip().isdigit()]
            out_dir = Path(args.out_dir) if args.out_dir else work / "downloads"
            out_dir.mkdir(parents=True, exist_ok=True)
            for i in picks:
                if not 1 <= i <= len(assets):
                    continue
                asset = assets[i - 1]
                if not asset.get("url"):
                    continue
                dest = out_dir / f"stock_{i:02d}{Path(urllib.parse.urlparse(asset['url']).path).suffix or '.jpg'}"
                try:
                    req = urllib.request.Request(asset["url"], headers=UA)
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        dest.write_bytes(resp.read())
                    downloaded.append(str(dest))
                    asset["local"] = str(dest)
                except Exception as exc:  # noqa: BLE001
                    log(f"WARN download failed for {i}: {exc}")
            write_json(index, {"query": args.query, "assets": assets})
        run.add_check("results", "pass" if assets else "warn", len(assets), ">= 1")
        bad_licences = sum(1 for a in assets if any("licence not usable" in n for n in a["notes"]))
        run.add_check("licences", "pass" if bad_licences == 0 else "warn", bad_licences,
                      "0 non-commercial")
        if not args.dry_run:
            state = ensure_edit(root)
            record_stage(root, state, "stock", index, count=len(assets))
        run.ok(output=str(index), artifacts=[str(index), str(credits), *downloaded],
               next_cmd="review the thumbnails, then insert an approved asset")
        if not args.json:
            for i, a in enumerate(assets, 1):
                print(f"{i}. [{a['score']:.2f}] {a['provider']:<10} {a['title'][:50]} "
                      f"({a['license']}, {a['creator']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
