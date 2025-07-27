#!/usr/bin/env python3
import os
import unicodedata
import re
import unicodedata
import uuid
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
title_en = get_field(['title_en','event_title__en','news_title__en'], issue.title)
title_tr = get_field(['title_tr','event_title__tr','news_title__tr'], '')
date_val  = get_field(['date'], '')
time_val  = get_field(['time'], '')

# ─── NEWS‑SPECIFIC VARIABLES ───────────────────────────────────────────────────
desc_en      = get_field(['description_en','short_description_en'], '')
content_en   = get_field(['content_en','full_content_en'], '')
desc_tr      = get_field(['description_tr','short_description_tr'], '')
content_tr   = get_field(['content_tr','full_content_tr'], '')
news_image_md= get_field(['image_markdown'], '')

# ─── EVENT‑SPECIFIC VARIABLES ──────────────────────────────────────────────────
event_type    = get_field(['event_type'], '')
speaker_name  = get_field(['name','speaker_presenter_name'], '')
duration      = get_field(['duration'], '')
location_en   = get_field(['location_en'], '')
location_tr   = get_field(['location_tr'], '')
event_image_md= get_field(['image_markdown'], '')
description_e = get_field(['description_en'], '')
description_t = get_field(['description_tr'], '')

# ─── IMAGE DOWNLOAD (shared) ──────────────────────────────────────────────────
def download_image(md: str) -> str:
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md) or \
        re.search(r"<img[^>]+src=\"(https?://[^\"]+)\"", md)
    if not m:
        return ""
    url = m.group(1)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    ctype = resp.headers.get('Content-Type','').split(';')[0]
    ext   = mimetypes.guess_extension(ctype) or os.path.splitext(url)[1] or '.png'
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    name = uuid.uuid4().hex + ext
    dest = os.path.join(UPLOADS_DIR, name)
    with open(dest, 'wb') as f:
        f.write(resp.content)
    print(f"[DEBUG] Saved image to {dest} (Content-Type: {ctype})")
    return f"uploads/{name}"  # no leading slash

# Choose which image MD to use
image_md = download_image(event_image_md if event_type else news_image_md)

# ─── BUILD CONTEXT & SELECT TEMPLATE ──────────────────────────────────────────
is_event     = bool(event_type)
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''

if is_event:
    ctx_en = {
        'type':       event_type,
        'title':      title_en,
        'name':       speaker_name,
        'datetime':   datetime_iso,
        'duration':   duration,
        'location':   location_en,
        'thumbnail':  image_md,
        'description': description_e,
    }
    ctx_tr = {
        'type':       event_type,
        'title':      title_tr or title_en,
        'name':       speaker_name,
        'datetime':   datetime_iso,
        'duration':   duration,
        'location':   location_tr,
        'thumbnail':  image_md,
        'description': description_t,
    }
    template_path = f"events/{event_type}.md.j2"
    out_subdir    = "events"
else:
    ctx_en = {
        'type':       'news',
        'title':      title_en,
        'description': desc_en,
        'date':        date_val,
        'thumbnail':   image_md,
        'content':     content_en,
        'featured':    False,
    }
    ctx_tr = {
        'type':       'news',
        'title':      title_tr or title_en,
        'description': desc_tr,
        'date':        date_val,
        'thumbnail':   image_md,
        'content':     content_tr,
        'featured':    False,
    }
    template_path = "news.md.j2"
    out_subdir    = "news"

print(f"[DEBUG] Rendering {'Event' if is_event else 'News'} using {template_path}")

# ─── RENDER & WRITE FILES ─────────────────────────────────────────────────────
env  = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)

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
