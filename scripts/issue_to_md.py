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
    # Try to extract the JSON blob GitHub Issue Forms embed
    json_match = re.search(r"<!--\s*({.*})\s*-->", body, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            print(f"[DEBUG] Parsed JSON fields: {data}")
            return data
        except json.JSONDecodeError as e:
            print(f"[WARN] JSON parse error: {e}")
    # Fallback: parse markdown headings
    pattern = re.compile(
        r"^#{1,6}\s+(.*?)\s*\r?\n+(.*?)(?=^#{1,6}\s|\Z)",
        re.MULTILINE | re.DOTALL
    )
    parsed = {}
    for label, val in pattern.findall(body or ""):
        key = re.sub(r"[^a-z0-9_]", "_", label.lower()).strip("_")
        parsed[key] = val.strip()
    # Remap the date label from "(YYYY-MM-DD)" if present
    if 'date__yyyy_mm_dd' in parsed:
        parsed['date'] = parsed.pop('date__yyyy_mm_dd')
    print(f"[DEBUG] Fallback parsed fields: {parsed}")
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
# Speaker: JSON key 'name', fallback key 'speaker_presenter_name'
speaker_name = fields.get('name') or fields.get('speaker_presenter_name', '')
location_en  = fields.get('location_en') or fields.get('location__en', '')
location_tr  = fields.get('location_tr') or fields.get('location__tr', '')
# Description: JSON vs. fallback keys
desc_en      = (fields.get('description_en')
               or fields.get('short_description_en')
               or fields.get('description__en')
               or fields.get('short_description__en', ''))
desc_tr      = (fields.get('description_tr')
               or fields.get('short_description_tr')
               or fields.get('description__tr')
               or fields.get('short_description__tr', ''))
# Image: JSON vs. fallback
image_md     = fields.get('image_markdown') or fields.get('image__optional__drag___drop', '')
print(f"[DEBUG] Extracted variables → speaker: {speaker_name}, image_md: {image_md}, time: {time_val}")

# ─── DOWNLOAD IMAGE (Markdown or HTML) ────────────────────────────────────────
def download_image(input_str: str) -> str:
    print(f"[DEBUG] Raw image input: {input_str}")
    # Try Markdown-style
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", input_str)
    # Fallback to HTML <img src="...">
    if not m:
        m = re.search(r"<img[^>]+src=\"(https?://[^\"]+)\"", input_str)
    if not m:
        print("[DEBUG] No image URL found")
        return ""
    url = m.group(1)
    print(f"[DEBUG] Downloading image URL: {url}")
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    # Choose extension
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

# ─── BUILD CONTEXTS & OUTPUT ─────────────────────────────────────────────────
# Combine date + time for events
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''

ctx_en = {
    'title':     title_en,
    'date':      date_val,
    'thumbnail': thumbnail,
    'event_type': event_type,
    'speaker':   speaker_name,
    'duration':  duration,
    'location':  location_en,
    'datetime':  datetime_iso,
    'description': desc_en
}
ctx_tr = {
    'title':     title_tr,
    'date':      date_val,
    'thumbnail': thumbnail,
    'event_type': event_type,
    'speaker':   speaker_name,
    'duration':  duration,
    'location':  location_tr,
    'datetime':  datetime_iso,
    'description': desc_tr
}
print(f"[DEBUG] ctx_en: {ctx_en}")
print(f"[DEBUG] ctx_tr: {ctx_tr}")

# ─── RENDER & WRITE FILES ──────────────────────────────────────────────────────
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
template_path = f"events/{event_type}.md.j2" if event_type else "news.md.j2"
tmpl = env.get_template(template_path)
print(f"[DEBUG] Using template: {template_path}")

# Generate slug
slug = unicodedata.normalize("NFKD", title_en)
slug = slug.encode("ascii", "ignore").decode("ascii")
slug = re.sub(r"[^\w\s-]", "", slug.lower())
slug = re.sub(r"[-\s]+", "-", slug).strip("-_")

out_dir = os.path.join("content", "events" if event_type else "news", f"{date_val}-{slug}")
print(f"[DEBUG] Output directory: {out_dir}")
os.makedirs(out_dir, exist_ok=True)

# English file
out_path_en = os.path.join(out_dir, "index.en.md")
with open(out_path_en, "w", encoding="utf-8") as f:
    f.write(tmpl.render(**ctx_en))
print(f"[DEBUG] Wrote English markdown: {out_path_en}")

# Turkish file
out_path_tr = os.path.join(out_dir, "index.tr.md")
with open(out_path_tr, "w", encoding="utf-8") as f:
    f.write(tmpl.render(**ctx_tr))
print(f"[DEBUG] Wrote Turkish markdown: {out_path_tr}")

