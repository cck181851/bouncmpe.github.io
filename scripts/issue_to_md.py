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
print("──────────────────────────────────────────────────")

# ─── PARSE ISSUE FORM FIELDS ──────────────────────────────────────────────────
def parse_fields(body: str):
    print("[DEBUG] Entering parse_fields()")
    # Try JSON blob
    json_match = re.search(r"<!--\s*({.*})\s*-->", body or "", re.DOTALL)
    print(f"[DEBUG] JSON blob match: {bool(json_match)}")
    if json_match:
        blob = json_match.group(1)
        print(f"[DEBUG] JSON blob:\n{blob}")
        try:
            data = json.loads(blob)
            print(f"[DEBUG] Parsed JSON fields: {data}")
            return data
        except json.JSONDecodeError as e:
            print(f"[DEBUG] JSON parse error: {e}")

    # Fallback: markdown headings
    pattern = re.compile(
        r"^#{1,6}\s+(.*?)\s*\r?\n+(.*?)(?=^#{1,6}\s|\Z)",
        re.MULTILINE | re.DOTALL
    )
    parsed = {}
    for label, val in pattern.findall(body or ""):
        key = re.sub(r"[^a-z0-9_]", "_", label.lower()).strip("_")
        parsed[key] = val.strip()
        print(f"[DEBUG] Fallback parsed: {key!r} = {parsed[key]!r}")

    if 'date__yyyy_mm_dd' in parsed:
        parsed['date'] = parsed.pop('date__yyyy_mm_dd')
        print("[DEBUG] Remapped date__yyyy_mm_dd → date")

    print(f"[DEBUG] Final parsed fields: {parsed}")
    return parsed

fields = parse_fields(issue.body)
print("──────────────────────────────────────────────────")

# ─── FIELD EXTRACTION WITH DEBUG ──────────────────────────────────────────────
def get_field(variants, default=""):
    for name in variants:
        if name in fields and fields[name]:
            print(f"[DEBUG] Using field {name!r} = {fields[name]!r}")
            return fields[name]
    print(f"[DEBUG] None of {variants!r} found, default={default!r}")
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
# include the fallback key for image
image_md     = get_field(['image_markdown', 'image__optional__drag___drop'], '')
# include fallback keys for description
desc_en      = get_field(['description_en', 'short_description_en', 'description__en'], '')
desc_tr      = get_field(['description_tr', 'short_description_tr', 'description__tr'], '')

print("──────────────────────────────────────────────────")
print(f"[DEBUG] image_md raw:\n{image_md!r}")
print(f"[DEBUG] desc_en raw:\n{desc_en!r}")
print(f"[DEBUG] desc_tr raw:\n{desc_tr!r}")
print("──────────────────────────────────────────────────")

# ─── DOWNLOAD IMAGE ────────────────────────────────────────────────────────────
def download_image(input_str: str) -> str:
    print("[DEBUG] Entering download_image()")
    print(f"[DEBUG] Raw input:\n{input_str!r}")
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", input_str)
    print(f"[DEBUG] Markdown match: {bool(m)}")
    if not m:
        m = re.search(r"<img[^>]+src=\"(https?://[^\"]+)\"", input_str)
        print(f"[DEBUG] HTML <img> match: {bool(m)}")
    if not m:
        print("[DEBUG] No image URL found")
        return ""
    url = m.group(1)
    print(f"[DEBUG] Image URL: {url}")

    resp = requests.get(url, timeout=15)
    print(f"[DEBUG] GET status: {resp.status_code}")
    resp.raise_for_status()

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    filename = os.path.basename(url.split("?",1)[0])
    dest = os.path.join(UPLOADS_DIR, filename)
    with open(dest, "wb") as f:
        f.write(resp.content)
    print(f"[DEBUG] Saved image at: {dest}")

    served = f"/uploads/{filename}"
    print(f"[DEBUG] Returning: {served}")
    return served

thumbnail = download_image(image_md)
print("──────────────────────────────────────────────────")

# ─── BUILD CONTEXT & RENDER ───────────────────────────────────────────────────
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''
print(f"[DEBUG] datetime_iso: {datetime_iso!r}")

ctx_common = {'title': title_en, 'date': date_val, 'thumbnail': thumbnail}

if event_type:
    print(f"[DEBUG] EVENT flow for type {event_type!r}")
    ctx_en = {
        **ctx_common,
        'event_type': event_type,
        'speaker': speaker_name,
        'duration': duration,
        'location': location_en,
        'datetime': datetime_iso,
        'description': desc_en
    }
    template_path = f"events/{event_type}.md.j2"
else:
    print("[DEBUG] NEWS flow")
    content_en = get_field(['content_en'], '')
    ctx_en = {**ctx_common, 'description': desc_en, 'content': content_en}
    template_path = "news.md.j2"

ctx_tr = ctx_en.copy()
ctx_tr.update({'title': title_tr or ctx_tr['title'], 'description': desc_tr or ctx_tr.get('description','')})
print(f"[DEBUG] Using template: {template_path}")

env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)

slug = unicodedata.normalize("NFKD", title_en).encode("ascii","ignore").decode().lower()
slug = re.sub(r"[^\w\s-]","",slug)
slug = re.sub(r"[-\s]+","-",slug)
print(f"[DEBUG] slug: {slug}")

out_dir = os.path.join("content", "events" if event_type else "news", f"{date_val}-{slug}")
os.makedirs(out_dir, exist_ok=True)
print(f"[DEBUG] out_dir: {out_dir}")

for lang, ctx, fname in [("en", ctx_en, "index.en.md"), ("tr", ctx_tr, "index.tr.md")]:
    path = os.path.join(out_dir, fname)
    print(f"[DEBUG] Writing {lang} → {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(tmpl.render(**ctx))
    print(f"[DEBUG] Wrote {lang} file")

print("[DEBUG] Script complete.")

