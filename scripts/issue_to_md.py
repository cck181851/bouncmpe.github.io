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
UPLOADS_DIR   = os.path.join("assets", "uploads")

if not GITHUB_TOKEN or ISSUE_NUMBER == 0:
    raise RuntimeError("GITHUB_TOKEN and ISSUE_NUMBER must be set")

# Initialize GitHub client and issue
gh    = Github(GITHUB_TOKEN)
repo  = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)
print(f"[DEBUG] Issue #{ISSUE_NUMBER}: title={issue.title}")

# ─── PARSE ISSUE FORM FIELDS ──────────────────────────────────────────────────
def parse_fields(body: str):
    # GitHub Issue Forms embed a JSON blob inside an HTML comment
    json_match = re.search(r"<!--\s*({.*})\s*-->", body, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            print(f"[DEBUG] Parsed JSON fields: {data}")
            return data
        except json.JSONDecodeError as e:
            print(f"[WARN] JSON parse error: {e}")
    # Fallback to markdown headings parsing
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
    print(f"[DEBUG] Fallback parsed fields: {parsed}")
    return parsed

fields = parse_fields(issue.body)

# ─── EXTRACT VARIABLES ─────────────────────────────────────────────────────────
# Support both JSON field IDs (from issue form) and fallback heading keys
event_type      = fields.get('event_type', '')
# Title: JSON uses title_en/title_tr, fallback uses event_title__en/event_title__tr
title_en        = fields.get('title_en') or fields.get('event_title__en') or issue.title
title_tr        = fields.get('title_tr') or fields.get('event_title__tr') or ''
# Date & Time
date_val        = fields.get('date', '')
time_val        = fields.get('time', '')
# Duration
duration        = fields.get('duration', '')
# Speaker: JSON key 'name', fallback key 'speaker_presenter_name'
speaker_name    = fields.get('name') or fields.get('speaker_presenter_name', '')
# Location: JSON uses location_en/location_tr, fallback uses those keys as well
location_en     = fields.get('location_en') or fields.get('location__en', '')
location_tr     = fields.get('location_tr') or fields.get('location__tr', '')
# Description: JSON uses description_en/description_tr, fallback uses description__en/_tr or short_description variants
desc_en         = fields.get('description_en') or fields.get('short_description_en') or fields.get('description__en') or fields.get('short_description__en', '')
desc_tr         = fields.get('description_tr') or fields.get('short_description_tr') or fields.get('description__tr') or fields.get('short_description__tr', '')
# Image: JSON key 'image_markdown', fallback image__optional... key
image_md        = fields.get('image_markdown') or fields.get('image__optional__drag___drop', '')
print(f"[DEBUG] Variables: event_type={event_type}, title_en={title_en}, speaker={speaker_name}, date={date_val}, time={time_val}, location_en={location_en}, desc_en={desc_en}")

# ─── DETERMINE TEMPLATE & OUTPUT DIR & OUTPUT DIR
is_event = bool(event_type)
template_path = f"events/{event_type}.md.j2" if is_event else "news.md.j2"
out_subdir = 'events' if is_event else 'news'
print(f"[DEBUG] Using template: {template_path}")

# ─── SLUGIFY UTILITY
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-_")

# ─── IMAGE DOWNLOAD (supports markdown and HTML)

def download_image(input_str: str) -> str:
    print(f"[DEBUG] Raw image input: {input_str}")
    # markdown image
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", input_str)
    # html <img src="..."
    if not m:
        m = re.search(r"<img[^>]+src=\"(https?://[^\"]+)\"", input_str)
    if not m:
        print("[DEBUG] No image URL found")
        return ""
    url = m.group(1)
    print(f"[DEBUG] Downloading image URL: {url}")
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    ext = os.path.splitext(url)[1] or ".png"
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    filename = os.path.basename(url.split("?", 1)[0])
    path = os.path.join(UPLOADS_DIR, filename)
    with open(path, "wb") as f:
        f.write(resp.content)
    print(f"[DEBUG] Saved image to: {path}")
    return f"uploads/{filename}"

thumbnail = download_image(image_md)
print(f"[DEBUG] thumbnail path: {thumbnail}")

# ─── BUILD CONTEXTS
# Combine date and time for events
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''

ctx_en = {
    'title': title_en,
    'date': date_val,
    'thumbnail': thumbnail,
}
ctx_tr = {
    'title': title_tr,
    'date': date_val,
    'thumbnail': thumbnail,
}

if is_event:
    ctx_en.update({
        'event_type': event_type,
        'speaker': speaker_name,
        'duration': duration,
        'location': location_en,
        'datetime': datetime_iso,
        'description': desc_en
    })
    ctx_tr.update({
        'event_type': event_type,
        'speaker': speaker_name,
        'duration': duration,
        'location': location_tr,
        'datetime': datetime_iso,
        'description': desc_tr
    })
else:
    ctx_en.update({
        'description': desc_en,
        'content': fields.get('content__en', '')
    })
    ctx_tr.update({
        'description': desc_tr,
        'content': fields.get('content__tr', '')
    })

print(f"[DEBUG] ctx_en: {ctx_en}")
print(f"[DEBUG] ctx_tr: {ctx_tr}")

# ─── RENDER & WRITE FILES ──────────────────────────────────────────────────────
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)

slug_base = slugify(title_en)
out_dir = os.path.join('content', out_subdir, f"{date_val}-{slug_base}")
print(f"[DEBUG] Output directory: {out_dir}")

os.makedirs(out_dir, exist_ok=True)

# English
out_path_en = os.path.join(out_dir, 'index.en.md')
with open(out_path_en, 'w', encoding='utf-8') as f:
    f.write(tmpl.render(**ctx_en))
print(f"[DEBUG] Wrote English markdown: {out_path_en}")

# Turkish
out_path_tr = os.path.join(out_dir, 'index.tr.md')
with open(out_path_tr, 'w', encoding='utf-8') as f:
    f.write(tmpl.render(**ctx_tr))
print(f"[DEBUG] Wrote Turkish markdown: {out_path_tr}")
