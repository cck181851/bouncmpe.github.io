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

# GitHub client
gh    = Github(GITHUB_TOKEN)
repo  = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)
print(f"[DEBUG] Loaded Issue #{ISSUE_NUMBER}: {issue.title!r}")

# ─── PARSE ISSUE FORM FIELDS ──────────────────────────────────────────────────
def parse_fields(body: str):
    # Try the JSON blob that GitHub Forms embeds
    m = re.search(r"<!--\s*({.*})\s*-->", body or "", re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            print("[DEBUG] Parsed JSON form data:", data)
            return data
        except json.JSONDecodeError as e:
            print("[DEBUG] JSON parse error:", e)
    # Fallback to markdown headings
    pattern = re.compile(r"^#{1,6}\s+(.*?)\s*\r?\n+(.*?)(?=^#{1,6}\s|\Z)", re.MULTILINE | re.DOTALL)
    parsed = {}
    for label, val in pattern.findall(body or ""):
        key = re.sub(r"[^a-z0-9_]", "_", label.lower()).strip("_")
        parsed[key] = val.strip()
    if 'date__yyyy_mm_dd' in parsed:
        parsed['date'] = parsed.pop('date__yyyy_mm_dd')
    print("[DEBUG] Fallback parsed fields:", parsed)
    return parsed

fields = parse_fields(issue.body)

# ─── HELPER ───────────────────────────────────────────────────────────────────
def get_field(keys, default=""):
    for k in keys:
        if k in fields and fields[k]:
            return fields[k]
    return default

# ─── EXTRACT COMMON FIELDS ────────────────────────────────────────────────────
event_type   = get_field(['event_type'], '')
title_en     = get_field(['title_en','event_title__en'], issue.title)
title_tr     = get_field(['title_tr','event_title__tr'], '')
date_val     = get_field(['date'], '')
time_val     = get_field(['time'], '')
duration     = get_field(['duration'], '')

# ─── EXTRACT NEWS‐SPECIFIC FIELDS ─────────────────────────────────────────────
# description = “Short Description (EN)” in the form
desc_en = get_field([
    'description_en',
    'short_description_en',
    'short_description__en',
    'description__en'
], '')
# full content = “Full Content (EN)” in the form
content_en = get_field([
    'content_en',
    'full_content_en',
    'full_content__en'
], '')
# image markdown
image_md  = get_field([
    'image_markdown',
], '')

print(f"[DEBUG] News: desc_en={desc_en!r}, content_en={content_en!r}, image_md={image_md!r}")

# ─── IMAGE DOWNLOAD (with extension) ───────────────────────────────────────────
def download_image(md: str) -> str:
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md) \
        or re.search(r"<img[^>]+src=\"(https?://[^\"]+)\"", md)
    if not m:
        return ""
    url = m.group(1)
    r   = requests.get(url, timeout=15)
    r.raise_for_status()
    ext = mimetypes.guess_extension(r.headers.get('Content-Type','').split(';')[0]) \
          or os.path.splitext(url)[1] or '.png'
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    base = os.path.basename(url).split('?')[0]
    name = os.path.splitext(base)[0] + ext
    dest = os.path.join(UPLOADS_DIR, name)
    with open(dest, 'wb') as f:
        f.write(r.content)
    print(f"[DEBUG] Saved image to {dest}")
    return f"/uploads/{name}"

thumbnail = download_image(image_md)

# ─── BUILD CONTEXT & RENDER ───────────────────────────────────────────────────
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''
ctx_common   = {
    'title':     title_en,
    'date':      date_val,
    'time':      time_val,
    'thumbnail': thumbnail,
}

if event_type:
    # … your event logic …
    pass
else:
    # NEWS
    ctx_en       = { **ctx_common, 'description': desc_en, 'content': content_en }
    template_path = "news.md.j2"

# Turkish version (similarly)
ctx_tr = ctx_en.copy()
ctx_tr.update({
    'title': title_tr or title_en,
    'description': get_field([
        'description_tr','short_description_tr','description__tr'
    ], ''),
    'content':     get_field([
        'content_tr','full_content_tr','content__tr','full_content__tr'
    ], '')
})

# Render with Jinja
env  = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)

# Slugify
slug = unicodedata.normalize("NFKD", title_en).encode("ascii","ignore").decode().lower()
slug = re.sub(r"[^\w\s-]","", slug)
slug = re.sub(r"[-\s]+","-", slug)

out_dir = os.path.join("content", "news", f"{date_val}-{slug}")
os.makedirs(out_dir, exist_ok=True)

for lang, ctx, fname in [("en", ctx_en, "index.en.md"), ("tr", ctx_tr, "index.tr.md")]:
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tmpl.render(**ctx))
    print(f"[DEBUG] Wrote {lang} → {path}")

