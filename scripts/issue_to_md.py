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

gh    = Github(GITHUB_TOKEN)
repo  = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)
print(f"[DEBUG] Loaded Issue #{ISSUE_NUMBER}: {issue.title!r}")

# ─── PARSE ISSUE FORM FIELDS ──────────────────────────────────────────────────
def parse_fields(body: str):
    json_match = re.search(r"<!--\s*({.*})\s*-->", body or "", re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
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
    return parsed

fields = parse_fields(issue.body)

def get_field(variants, default=""):
    for name in variants:
        if name in fields and fields[name]:
            return fields[name]
    return default

# ─── EXTRACT VARIABLES ─────────────────────────────────────────────────────────
event_type   = get_field(['event_type'], '')
title_en     = get_field(['title_en','event_title__en'], issue.title)
title_tr     = get_field(['title_tr','event_title__tr'], '')
date_val     = get_field(['date'], '')
time_val     = get_field(['time'], '')
duration     = get_field(['duration'], '')
speaker_name = get_field(['name','speaker_presenter_name'], '')
location_en  = get_field(['location_en','location__en'], '')
location_tr  = get_field(['location_tr','location__tr'], '')
desc_en      = get_field(['description_en','short_description_en','description__en'], '')
desc_tr      = get_field(['description_tr','short_description_tr','description__tr'], '')
image_md     = get_field(['image_markdown','image__optional__drag___drop'], '')

# ─── DOWNLOAD IMAGE WITH EXTENSION DETECTION ──────────────────────────────────
def download_image(input_str: str) -> str:
    # find Markdown or HTML image
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", input_str) \
        or re.search(r"<img[^>]+src=\"(https?://[^\"]+)\"", input_str)
    if not m:
        return ""
    url = m.group(1)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    # Determine extension from content-type
    content_type = resp.headers.get('Content-Type', '')
    ext = mimetypes.guess_extension(content_type.split(';')[0].strip()) or \
          os.path.splitext(url)[1] or '.png'

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    # use a safe filename + extension
    base = os.path.basename(url).split('?')[0]
    name = os.path.splitext(base)[0]
    filename = f"{name}{ext}"
    dest = os.path.join(UPLOADS_DIR, filename)

    with open(dest, "wb") as f:
        f.write(resp.content)
    print(f"[DEBUG] Saved image to {dest} (Content-Type: {content_type})")

    # Hugo will serve under /uploads/
    return f"/uploads/{filename}"

thumbnail = download_image(image_md)

# ─── BUILD CONTEXT & RENDER ───────────────────────────────────────────────────
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''
ctx_common = {
    'title':     title_en,
    'date':      date_val,
    'time':      time_val,
    'thumbnail': thumbnail,
}

if event_type:
    ctx_en = {
        **ctx_common,
        'event_type': event_type,
        'speaker':    speaker_name,
        'duration':   duration,
        'location':   location_en,
        'datetime':   datetime_iso,
        'description': desc_en,
    }
    template_path = f"events/{event_type}.md.j2"
else:
    content_en = get_field(['content_en'], '')
    ctx_en = { **ctx_common, 'description': desc_en, 'content': content_en }
    template_path = "news.md.j2"

ctx_tr = ctx_en.copy()
ctx_tr.update({'title': title_tr or title_en, 'description': desc_tr or desc_en})

env  = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)

slug = unicodedata.normalize("NFKD", title_en).encode("ascii","ignore").decode().lower()
slug = re.sub(r"[^\w\s-]","", slug)
slug = re.sub(r"[-\s]+","-", slug)

out_dir = os.path.join("content", "events" if event_type else "news", f"{date_val}-{slug}")
os.makedirs(out_dir, exist_ok=True)

for lang, ctx, fname in [("en", ctx_en, "index.en.md"), ("tr", ctx_tr, "index.tr.md")]:
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tmpl.render(**ctx))
    print(f"[DEBUG] Wrote {lang} → {path}")


