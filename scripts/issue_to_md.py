# scripts/issue_to_md.py
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
GITHUB_EVENT_PATH = os.getenv("GITHUB_EVENT_PATH")
if not GITHUB_EVENT_PATH:
    raise RuntimeError("GITHUB_EVENT_PATH must be set to the GitHub webhook payload path.")
with open(GITHUB_EVENT_PATH, 'r', encoding='utf-8') as f:
    event_data = json.load(f)
issue_number = event_data.get("issue", {}).get("number")
if not issue_number:
    raise RuntimeError("Issue number not found in GitHub event payload.")

GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
REPO_NAME     = os.getenv("GITHUB_REPOSITORY")
if not GITHUB_TOKEN or not REPO_NAME:
    raise RuntimeError("GITHUB_TOKEN and GITHUB_REPOSITORY must be set in the environment.")

TEMPLATES_DIR = "templates"
UPLOADS_DIR   = os.path.join("assets", "uploads")

# ─── INIT GITHUB CLIENT & ISSUE ───────────────────────────────────────────────
gh    = Github(GITHUB_TOKEN)
repo  = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=issue_number)
print(f"[DEBUG] Loaded Issue #{issue_number}: {issue.title!r}")

# ─── PARSE FORM FIELDS ─────────────────────────────────────────────────────────
def parse_fields(body: str):
    m = re.search(r"<!--\s*({.*})\s*-->", body or "", re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            return data
        except:
            pass
    pattern = re.compile(r"^#{1,6}\s+(.*?)\s*\r?\n+(.*?)(?=^#{1,6}\s|\Z)", re.MULTILINE | re.DOTALL)
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

# Common fields
title_en = get_field(['title_en','event_title__en','news_title__en'], issue.title)
date_val = get_field(['date'], '')
time_val = get_field(['time'], '')

# News-specific
desc_en    = get_field(['description_en','short_description_en'], '')
content_en = get_field(['content_en','full_content_en'], '')
desc_tr    = get_field(['description_tr','short_description_tr'], '')
content_tr = get_field(['content_tr','full_content_tr'], '')
news_image_md = get_field(['image_markdown'], '')

# Event-specific
event_type   = get_field(['event_type'], '')
speaker_name = get_field(['name','speaker_presenter_name'], '')
duration     = get_field(['duration'], '')
location_en  = get_field(['location_en'], '')
location_tr  = get_field(['location_tr'], '')
event_image_md = get_field(['image_markdown'], '')

# Download images
def download_image(md: str) -> str:
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md)
    if not m:
        return ""
    url = m.group(1)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    ctype = resp.headers.get('Content-Type','').split(';')[0]
    ext = mimetypes.guess_extension(ctype) or os.path.splitext(url)[1] or '.png'
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    base = os.path.basename(url).split('?')[0]
    name = os.path.splitext(base)[0] + ext
    dest = os.path.join(UPLOADS_DIR, name)
    with open(dest, 'wb') as f:
        f.write(resp.content)
    return f"/uploads/{name}"

image_md = download_image(event_image_md) if event_type else download_image(news_image_md)

# Map templates
template_map = {
    'news': 'news.md.j2',
    **{etype: f"events/{etype}.md.j2" for etype in ['phd-thesis-defense','ms-thesis-defense','seminar','special-event']}
}
type_key = event_type or 'news'
template_path = template_map[type_key]

# Build contexts with `type`
common_ctx = {
    'type':       type_key,
    'title':      title_en,
    'date':       date_val,
    'time':       time_val,
    'thumbnail':  image_md,
}
if type_key == 'news':
    en_ctx = {**common_ctx, 'description': desc_en, 'content': content_en}
    tr_ctx = {**common_ctx, 'description': desc_tr or desc_en, 'content': content_tr}
else:
    datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''
    ev_ctx = {
        'name':      speaker_name,
        'datetime':  datetime_iso,
        'duration':  duration,
        'location':  location_en,
    }
    en_ctx = {**common_ctx, **ev_ctx, 'description': desc_en}
    tr_ctx = {**common_ctx, **ev_ctx, 'description': desc_tr}

# Render & write files
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)
slug = unicodedata.normalize('NFKD', title_en).encode('ascii','ignore').decode().lower()
slug = re.sub(r"[^\w\s-]", '', slug)
slug = re.sub(r"[-\s]+", '-', slug)
out_dir = os.path.join('content', type_key if type_key!='news' else 'news', f"{date_val}-{slug}")
os.makedirs(out_dir, exist_ok=True)
for lang, ctx, fname in [('en', en_ctx, 'index.en.md'), ('tr', tr_ctx, 'index.tr.md')]:
    with open(os.path.join(out_dir, fname), 'w', encoding='utf-8') as f:
        f.write(tmpl.render(**ctx))
