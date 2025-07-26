#!/usr/bin/env python3
import os
import re
import unicodedata
import json
import requests
from github import Github
from jinja2 import Environment, FileSystemLoader

# ─── CONFIG ───────────────────────────────────────────────────────────────────
REPO_NAME     = os.getenv("GITHUB_REPOSITORY")
ISSUE_NUMBER  = int(os.getenv("ISSUE_NUMBER", "0"))
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
TEMPLATES_DIR = "templates"
# ← change assets/uploads → static/uploads
UPLOADS_DIR   = os.path.join("static", "uploads")

if not GITHUB_TOKEN or ISSUE_NUMBER == 0:
    raise RuntimeError("GITHUB_TOKEN and ISSUE_NUMBER must be set")

# Initialize GitHub client and issue
gh    = Github(GITHUB_TOKEN)
repo  = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)
print(f"[DEBUG] Issue #{ISSUE_NUMBER}: title={issue.title}")

# ─── PARSE ISSUE FORM FIELDS ──────────────────────────────────────────────────
def parse_fields(body: str):
    json_match = re.search(r"<!--\s*({.*})\s*-->", body, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            return data
        except json.JSONDecodeError:
            pass
    # fallback markdown headers
    pattern = re.compile(
        r"^#{1,6}\s+(.*?)\s*\r?\n+(.*?)(?=^#{1,6}\s|\Z)",
        re.MULTILINE | re.DOTALL
    )
    parsed = {}
    for label, val in pattern.findall(body or ""):
        key = re.sub(r"[^a-z0-9_]", "_", label.lower())
        parsed[key] = val.strip()
    if 'date__yyyy_mm_dd' in parsed:
        parsed['date'] = parsed.pop('date__yyyy_mm_dd')
    return parsed

fields = parse_fields(issue.body)
print(f"[DEBUG] Fields after parse: {fields}")

# ─── EXTRACT VARIABLES ─────────────────────────────────────────────────────────
event_type   = fields.get('event_type', '')
title_en     = fields.get('title_en') or fields.get('event_title__en') or issue.title
title_tr     = fields.get('title_tr') or fields.get('event_title__tr') or ''
date_val     = fields.get('date', '')
time_val     = fields.get('time', '')
duration     = fields.get('duration', '')
speaker_name = fields.get('name') or fields.get('speaker_presenter_name', '')
location_en  = fields.get('location_en') or fields.get('location__en', '')
location_tr  = fields.get('location_tr') or fields.get('location__tr', '')
desc_en      = fields.get('description_en') or fields.get('short_description_en', '')
desc_tr      = fields.get('description_tr') or fields.get('short_description_tr', '')
image_md     = fields.get('image_markdown') or ''

print(f"[DEBUG] Extracted → image_md: {image_md}")

# ─── DOWNLOAD IMAGE ────────────────────────────────────────────────────────────
def download_image(input_str: str) -> str:
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", input_str)
    if not m:
        m = re.search(r"<img[^>]+src=\"(https?://[^\"]+)\"", input_str)
    if not m:
        return ""
    url = m.group(1)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    filename = os.path.basename(url.split("?",1)[0])
    dest = os.path.join(UPLOADS_DIR, filename)
    with open(dest, "wb") as f:
        f.write(resp.content)
    print(f"[DEBUG] Saved image to: {dest}")
    # return path that Hugo will serve: /uploads/<filename>
    return f"/uploads/{filename}"

thumbnail = download_image(image_md)
print(f"[DEBUG] thumbnail front-matter value: {thumbnail!r}")

# ─── BUILD CONTEXTS & OUTPUT ─────────────────────────────────────────────────
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''

ctx_common = {
    'title':     title_en,
    'date':      date_val,
    'thumbnail': thumbnail,
}

if event_type:
    # EVENT
    ctx_en = { **ctx_common, 
        'event_type': event_type,
        'speaker':   speaker_name,
        'duration':  duration,
        'location':  location_en,
        'datetime':  datetime_iso,
        'description': desc_en
    }
    template_path = f"events/{event_type}.md.j2"
else:
    # NEWS
    content_en = fields.get('content_en') or ''
    ctx_en = { **ctx_common, 'description': desc_en, 'content': content_en }
    template_path = "news.md.j2"

# Turkish context
ctx_tr = ctx_en.copy()
ctx_tr.update({
    'title': title_tr or ctx_tr['title'],
    'description': desc_tr or ctx_tr.get('description',''),
})

print(f"[DEBUG] Using template: {template_path}")

env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)

# Slugify
slug = unicodedata.normalize("NFKD", title_en)\
    .encode("ascii","ignore").decode()\
    .lower().strip()
slug = re.sub(r"[^\w\s-]","",slug)
slug = re.sub(r"[-\s]+","-",slug)

out_dir = os.path.join("content", 
                       "events" if event_type else "news", 
                       f"{date_val}-{slug}")
os.makedirs(out_dir, exist_ok=True)

for lang, ctx, fname in [
    ("en", ctx_en, "index.en.md"),
    ("tr", ctx_tr, "index.tr.md"),
]:
    path = os.path.join(out_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tmpl.render(**ctx))
    print(f"[DEBUG] Wrote {lang} markdown: {path}")

