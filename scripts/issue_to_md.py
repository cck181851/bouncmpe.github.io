#!/usr/bin/env python3
import os
import re
import unicodedata
import json
import mimetypes
import requests
from github import Github
from jinja2 import Environment, FileSystemLoader

# ─── CONFIG ───────────────────────────────────────────────────────────────────
REPO_NAME     = os.getenv("GITHUB_REPOSITORY")
ISSUE_NUMBER  = int(os.getenv("ISSUE_NUMBER", "0"))
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
TEMPLATES_DIR = "templates"
UPLOADS_DIR   = os.path.join("static", "uploads")

if not GITHUB_TOKEN or ISSUE_NUMBER == 0:
    raise RuntimeError("GITHUB_TOKEN and ISSUE_NUMBER must be set")

# ─── INIT GITHUB CLIENT & ISSUE ───────────────────────────────────────────────
gh    = Github(GITHUB_TOKEN)
repo  = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)
print(f"[DEBUG] Loaded Issue #{ISSUE_NUMBER}: {issue.title!r}")

# ─── PARSE FIELDS ─────────────────────────────────────────────────────────────
def parse_fields(body: str):
    m = re.search(r"<!--\s*({.*})\s*-->", body or "", re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            print("[DEBUG] Parsed JSON form data:", data)
            return data
        except Exception as e:
            print("[DEBUG] JSON parse error:", e)
    # Fallback: markdown headings
    pattern = re.compile(
        r"^#{1,6}\s+(.*?)\s*\r?\n+(.*?)(?=^#{1,6}\s|\Z)",
        re.MULTILINE | re.DOTALL
    )
    parsed = {}
    for label, val in pattern.findall(body or ""):
        key = re.sub(r"[^a-z0-9_]", "_", label.lower()).strip("_")
        parsed[key] = val.strip()
    if 'date__yyyy_mm_dd' in parsed:
        parsed['date'] = parsed.pop('date__yyyy_mm_dd')
    print("[DEBUG] Fallback parsed fields:", parsed)
    return parsed

fields = parse_fields(issue.body)

# ─── FIELD LOOKUP HELPER ──────────────────────────────────────────────────────
def get_field(variants, default=""):
    for name in variants:
        if name in fields and fields[name]:
            return fields[name]
    return default

# ─── COMMON VARIABLES ─────────────────────────────────────────────────────────
title_en = get_field(
    ['title_en','event_title__en','news_title__en'], 
    issue.title
)
title_tr = get_field(
    ['title_tr','event_title__tr','news_title__tr'], 
    ''
)
date_val = get_field(['date'], '')
time_val = get_field(['time'], '')

# ─── NEWS‑SPECIFIC VARIABLES ───────────────────────────────────────────────────
desc_en    = get_field(
    ['description_en','short_description_en','short_description__en'], ''
)
content_en = get_field(
    ['content_en','full_content_en','full_content__en'], ''
)
desc_tr    = get_field(
    ['description_tr','short_description_tr','short_description__tr'], ''
)
content_tr = get_field(
    ['content_tr','full_content_tr','content__tr','full_content__tr'], ''
)
news_image_md = get_field(
    ['image_markdown','image__drag___drop_here','image__optional__drag___drop'], ''
)

# ─── EVENT‑SPECIFIC VARIABLES ──────────────────────────────────────────────────
event_type   = get_field(['event_type'], '')
speaker_name = get_field(['name','speaker_presenter_name'], '')
duration     = get_field(['duration'], '')
location_en  = get_field(['location_en','location__en'], '')
location_tr  = get_field(['location_tr','location__tr'], '')
event_image_md = get_field(
    ['image_markdown','image__optional__drag___drop'], ''
)
description_e = get_field(['description_en','description__en'], '')
description_t = get_field(['description_tr','description__tr'], '')

# ─── IMAGE DOWNLOAD (shared) ──────────────────────────────────────────────────
def download_image(md: str) -> str:
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md) or \
        re.search(r"<img[^>]+src=\"(https?://[^\"]+)\"", md)
    if not m:
        return ""
    url = m.group(1)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    # Determine extension
    ctype = resp.headers.get('Content-Type','').split(';')[0]
    ext = mimetypes.guess_extension(ctype) or os.path.splitext(url)[1] or '.png'
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    base = os.path.basename(url).split('?')[0]
    name = os.path.splitext(base)[0] + ext
    dest = os.path.join(UPLOADS_DIR, name)
    with open(dest, 'wb') as f:
        f.write(resp.content)
    print(f"[DEBUG] Saved image to {dest} (Content-Type: {ctype})")
    return f"/uploads/{name}"

# Choose which image MD to use
image_md = download_image(news_image_md) if not event_type else download_image(event_image_md)

# ─── BUILD CONTEXT & SELECT TEMPLATE ──────────────────────────────────────────
is_event     = bool(event_type)
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''

if is_event:
    ctx_en = {
        'title':      title_en,
        'date':       date_val,
        'time':       time_val,
        'thumbnail':  image_md,
        'event_type': event_type,
        'datetime':   datetime_iso,
        'speaker':    speaker_name,
        'duration':   duration,
        'location':   location_en,
        'description': description_e,
    }
    ctx_tr = {
        'title':      title_tr or title_en,
        'date':       date_val,
        'time':       time_val,
        'thumbnail':  image_md,
        'event_type': event_type,
        'datetime':   datetime_iso,
        'speaker':    speaker_name,
        'duration':   duration,
        'location':   location_tr,
        'description': description_t,
    }
    template_path = f"events/{event_type}.md.j2"
    out_subdir    = "events"
else:
    ctx_en = {
        'title':      title_en,
        'date':       date_val,
        'time':       time_val,
        'thumbnail':  image_md,
        'description': desc_en,
        'content':     content_en,
    }
    ctx_tr = {
        'title':      title_tr or title_en,
        'date':       date_val,
        'time':       time_val,
        'thumbnail':  image_md,
        'description': desc_tr,
        'content':     content_tr,
    }
    template_path = "news.md.j2"
    out_subdir    = "news"

print(f"[DEBUG] Rendering {'Event' if is_event else 'News'} using {template_path}")

# ─── RENDER & WRITE FILES ─────────────────────────────────────────────────────
env  = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)

# Slugify the English title
slug = unicodedata.normalize("NFKD", title_en).encode("ascii","ignore").decode().lower()
slug = re.sub(r"[^\w\s-]","", slug)
slug = re.sub(r"[-\s]+","-", slug)

out_dir = os.path.join("content", out_subdir, f"{date_val}-{slug}")
os.makedirs(out_dir, exist_ok=True)

for lang, ctx, fname in [
    ("en", ctx_en, "index.en.md"),
    ("tr", ctx_tr, "index.tr.md"),
]:
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tmpl.render(**ctx))
    print(f"[DEBUG] Wrote {lang} → {path}")


