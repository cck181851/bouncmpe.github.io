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
UPLOADS_DIR   = os.path.join("static", "uploads")

if not GITHUB_TOKEN or ISSUE_NUMBER == 0:
    raise RuntimeError("GITHUB_TOKEN and ISSUE_NUMBER must be set")

# Initialize GitHub client and issue
gh    = Github(GITHUB_TOKEN)
repo  = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)
print(f"[DEBUG] ── Loaded Issue #{ISSUE_NUMBER} ──")
print(f"[DEBUG] Title: {issue.title!r}")
print(f"[DEBUG] Body length: {len(issue.body or '')}")
print(f"[DEBUG] Body snippet:\n{(issue.body or '')[:500]}")
print("──────────────────────────────────────────────────")

# ─── PARSE ISSUE FORM FIELDS ──────────────────────────────────────────────────
def parse_fields(body: str):
    print("[DEBUG] Entering parse_fields()")
    # 1) Try JSON blob from issue forms
    json_match = re.search(r"<!--\s*({.*})\s*-->", body or "", re.DOTALL)
    print(f"[DEBUG] JSON blob match: {bool(json_match)}")
    if json_match:
        blob = json_match.group(1)
        print(f"[DEBUG] JSON blob content:\n{blob}")
        try:
            data = json.loads(blob)
            print(f"[DEBUG] Successfully parsed JSON fields: {data}")
            return data
        except json.JSONDecodeError as e:
            print(f"[DEBUG] JSON parse error: {e}")

    # 2) Fallback: markdown headers
    pattern = re.compile(
        r"^#{1,6}\s+(.*?)\s*\r?\n+(.*?)(?=^#{1,6}\s|\Z)",
        re.MULTILINE | re.DOTALL
    )
    parsed = {}
    for label, val in pattern.findall(body or ""):
        key = re.sub(r"[^a-z0-9_]", "_", label.lower()).strip("_")
        parsed[key] = val.strip()
        print(f"[DEBUG] Fallback parsed field: {key!r} → {parsed[key]!r}")

    # Remap date field if needed
    if 'date__yyyy_mm_dd' in parsed:
        parsed['date'] = parsed.pop('date__yyyy_mm_dd')
        print("[DEBUG] Remapped date__yyyy_mm_dd → date")

    print(f"[DEBUG] Final parsed fields dict: {parsed}")
    return parsed

fields = parse_fields(issue.body)
print("──────────────────────────────────────────────────")

# ─── EXTRACT VARIABLES ─────────────────────────────────────────────────────────
# Define all your extraction + debug prints
def get_field(name_variants, default=""):
    for name in name_variants:
        if name in fields and fields[name]:
            print(f"[DEBUG] Using field {name!r} = {fields[name]!r}")
            return fields[name]
    print(f"[DEBUG] Field {name_variants!r} not found, default={default!r}")
    return default

event_type   = get_field(['event_type'], '')
title_en     = get_field(['title_en', 'event_title__en'], issue.title)
title_tr     = get_field(['title_tr', 'event_title__tr'], '')
date_val     = get_field(['date'], '')
time_val     = get_field(['time'], '')
duration     = get_field(['duration'], '')
speaker_name = get_field(['name', 'speaker_presenter_name'], '')
location_en  = get_field(['location_en', 'location__en'], '')
location_tr  = get_field(['location_tr', 'location__tr'], '')
desc_en      = get_field(['description_en', 'short_description_en'], '')
desc_tr      = get_field(['description_tr', 'short_description_tr'], '')
image_md     = get_field(['image_markdown'], '')

print("──────────────────────────────────────────────────")
print(f"[DEBUG] Extracted image_md raw:\n{image_md!r}")
print("──────────────────────────────────────────────────")

# ─── DOWNLOAD IMAGE ────────────────────────────────────────────────────────────
def download_image(input_str: str) -> str:
    print("[DEBUG] Entering download_image()")
    print(f"[DEBUG] Raw input for image:\n{input_str!r}")
    # Markdown-style
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", input_str)
    print(f"[DEBUG] Markdown-style match: {bool(m)}")
    # HTML-style fallback
    if not m:
        m = re.search(r"<img[^>]+src=\"(https?://[^\"]+)\"", input_str)
        print(f"[DEBUG] HTML <img> match: {bool(m)}")
    if not m:
        print("[DEBUG] No image URL found in input; returning empty")
        return ""
    url = m.group(1)
    print(f"[DEBUG] Found image URL: {url}")

    resp = requests.get(url, timeout=15)
    print(f"[DEBUG] HTTP GET status: {resp.status_code}")
    resp.raise_for_status()

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    filename = os.path.basename(url.split("?",1)[0])
    dest = os.path.join(UPLOADS_DIR, filename)
    with open(dest, "wb") as f:
        f.write(resp.content)
    print(f"[DEBUG] Saved image at: {dest}")

    served_path = f"/uploads/{filename}"
    print(f"[DEBUG] Returning served_path: {served_path}")
    return served_path

thumbnail = download_image(image_md)
print("──────────────────────────────────────────────────")

# ─── BUILD CONTEXTS ───────────────────────────────────────────────────────────
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''
print(f"[DEBUG] datetime_iso: {datetime_iso!r}")

ctx_common = {
    'title':     title_en,
    'date':      date_val,
    'thumbnail': thumbnail,
}

if event_type:
    print(f"[DEBUG] Building EVENT context for type {event_type!r}")
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
    print("[DEBUG] Building NEWS context")
    content_en = get_field(['content_en'], '')
    ctx_en = { **ctx_common, 'description': desc_en, 'content': content_en }
    template_path = "news.md.j2"

ctx_tr = ctx_en.copy()
ctx_tr.update({
    'title': title_tr or ctx_tr['title'],
    'description': desc_tr or ctx_tr.get('description',''),
})

print(f"[DEBUG] Using template: {template_path}")
print("──────────────────────────────────────────────────")

# ─── RENDER & WRITE FILES ──────────────────────────────────────────────────────
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)

slug = unicodedata.normalize("NFKD", title_en)\
    .encode("ascii","ignore").decode()\
    .lower().strip()
slug = re.sub(r"[^\w\s-]","",slug)
slug = re.sub(r"[-\s]+","-",slug)
print(f"[DEBUG] Generated slug: {slug}")

out_dir = os.path.join("content", 
                       "events" if event_type else "news", 
                       f"{date_val}-{slug}")
os.makedirs(out_dir, exist_ok=True)
print(f"[DEBUG] Output directory: {out_dir}")

for lang, ctx, fname in [
    ("en", ctx_en, "index.en.md"),
    ("tr", ctx_tr, "index.tr.md"),
]:
    path = os.path.join(out_dir, fname)
    print(f"[DEBUG] Writing {lang} file at: {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(tmpl.render(**ctx))
    print(f"[DEBUG] Wrote {lang} markdown successfully.")

print("[DEBUG] Script complete.")


