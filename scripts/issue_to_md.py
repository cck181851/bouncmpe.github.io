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
            print("[DEBUG] Parsed JSON form data:", data)
            return data
        except Exception as e:
            print("[DEBUG] JSON parse error:", e)
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

def get_field(variants, default=""):
    for name in variants:
        if name in fields and fields[name]:
            return fields[name]
    return default

# Common
common_title = get_field(['title_en','event_title__en','news_title__en'], issue.title)
common_date  = get_field(['date'], '')
common_time  = get_field(['time'], '')

# News
desc_en    = get_field(['description_en','short_description_en'], '')
content_en = get_field(['content_en','full_content_en'], '')
desc_tr    = get_field(['description_tr','short_description_tr'], '')
content_tr = get_field(['content_tr','full_content_tr'], '')
news_image = get_field(['image_markdown'], '')

# Event
event_type   = get_field(['event_type'], '')
speaker_name = get_field(['name','speaker_presenter_name'], '')
duration     = get_field(['duration'], '')
location_en  = get_field(['location_en'], '')
location_tr  = get_field(['location_tr'], '')
event_image  = get_field(['image_markdown'], '')

# Download images

def download_image(md: str) -> str:
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md)
    if not m:
        return ""
    url = m.group(1)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    ctype = resp.headers.get('Content-Type','').split(';')[0]
    ext = mimetypes.guess_extension(ctype) or '.png'
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    name = os.path.basename(url).split('?')[0]
    dest = os.path.join(UPLOADS_DIR, name)
    with open(dest, 'wb') as f:
        f.write(resp.content)
    print(f"[DEBUG] Saved image to {dest}")
    return f"/uploads/{name}"

image_md = download_image(event_image if event_type else news_image)

# Template mapping
mapping = {
    'news': 'news.md.j2',
    **{etype: f"events/{etype}.md.j2" for etype in [
        'phd-thesis-defense','ms-thesis-defense','seminar','special-event'
    ]}
}
key = event_type or 'news'
template_path = mapping[key]
print(f"[DEBUG] Using template: {template_path}")

# Build contexts
common = {'title': common_title, 'date': common_date, 'time': common_time, 'thumbnail': image_md, 'type': key}
if key == 'news':
    en_ctx = {**common, 'description': desc_en, 'content': content_en}
    tr_ctx = {**common, 'description': desc_tr or desc_en, 'content': content_tr}
else:
    datetime_iso = f"{common_date}T{common_time}" if common_date and common_time else ''
    ev_common = {'event_type': key, 'datetime': datetime_iso, 'speaker': speaker_name, 'duration': duration}
    en_ctx = {**common, **ev_common, 'location': location_en, 'description': get_field(['description_en'], '')}
    tr_ctx = {**common, **ev_common, 'location': location_tr, 'description': get_field(['description_tr'], '')}

# Render & write
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)
slug = unicodedata.normalize("NFKD", common_title).encode("ascii","ignore").decode().lower()
slug = re.sub(r"[^\w\s-]","", slug)
slug = re.sub(r"[-\s]+","-", slug)
out_dir = os.path.join("content", key if key!='news' else 'news', f"{common_date}-{slug}")
os.makedirs(out_dir, exist_ok=True)
for lang, ctx, fname in [('en', en_ctx, 'index.en.md'), ('tr', tr_ctx, 'index.tr.md')]:
    path = os.path.join(out_dir, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(tmpl.render(**ctx))
    print(f"[DEBUG] Wrote {lang}: {path}")

