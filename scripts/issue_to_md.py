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

# ─── NORMALIZE FIELD KEYS FOR SIMPLER ACCESS ──────────────────────────────────
key_map = {
    'event_type': 'event_type',
    'event_title__en': 'title_en',
    'title_en': 'title_en',
    'event_title__tr': 'title_tr',
    'title_tr': 'title_tr',
    'description__en': 'description_en',
    'short_description__en': 'description_en',
    'description__tr': 'description_tr',
    'short_description__tr': 'description_tr',
    'full_content__en': 'content_en',
    'full_content__tr': 'content_tr',
    'speaker_presenter_name': 'name',
    'date': 'date',
    'time': 'time',
    'duration': 'duration',
    'location__en': 'location_en',
    'location__tr': 'location_tr',
    'image__optional__drag___drop': 'image_markdown',
    'image_markdown': 'image_markdown'
}
normalized = {}
for raw, val in fields.items():
    if raw in key_map and val:
        normalized[key_map[raw]] = val
print(f"[DEBUG] Normalized fields: {normalized}")
fields = normalized

# ─── DETERMINE TEMPLATE
is_event = bool(fields.get('event_type'))
event_type = fields.get('event_type')
if is_event:
    template_path = f"events/{event_type}.md.j2"
    out_subdir = 'events'
else:
    template_path = "news.md.j2"
    out_subdir = 'news'
print(f"[DEBUG] Using template: {template_path}")

# ─── SLUGIFY UTILITY
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-_")

# ─── IMAGE DOWNLOAD
def download_image(md_input: str) -> str:
    print(f"[DEBUG] Raw image markdown input: {md_input}")
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md_input)
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

img_field = fields.get('image_markdown', '')
thumbnail = download_image(img_field) if img_field else ""
print(f"[DEBUG] thumbnail path: {thumbnail}")

# ─── BUILD CONTEXT
# Combine date and time into ISO datetime for events
date_val = fields.get('date', '')
time_val = fields.get('time', '')
datetime_iso = f"{date_val}T{time_val}" if date_val and time_val else ''

ctx = {
    'title': fields.get('title_en', issue.title),
    'date': date_val,
    'thumbnail': thumbnail
}
if out_subdir == 'events':
    ctx.update({
        'datetime': datetime_iso,
        'description': fields.get('description_en', ''),
        'name': fields.get('name', ''),
        'duration': fields.get('duration', ''),
        'location': fields.get('location_en', '')
    })
else:
    ctx.update({
        'description': fields.get('description_en', ''),
        'content': fields.get('content_en', '')
    })
print(f"[DEBUG] Final context for template rendering: {ctx}")

# ─── RENDER & WRITE FILES ──────────────────────────────────────────────────────
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)

slug_base = slugify(ctx['title'])
out_dir = os.path.join('content', out_subdir, f"{ctx['date']}-{slug_base}")
print(f"[DEBUG] Output directory: {out_dir}")

os.makedirs(out_dir, exist_ok=True)

# Render English version
en_out = tmpl.render(**ctx)
out_path_en = os.path.join(out_dir, 'index.en.md')
with open(out_path_en, 'w', encoding='utf-8') as f:
    f.write(en_out)
print(f"[DEBUG] Wrote English markdown: {out_path_en}")

# Render Turkish version
if out_subdir == 'events':
    tr_ctx = {
        'title': fields.get('title_tr', ''),
        'date': date_val,
        'thumbnail': thumbnail,
        'datetime': datetime_iso,
        'description': fields.get('description_tr', ''),
        'name': fields.get('name', ''),
        'duration': fields.get('duration', ''),
        'location': fields.get('location_tr', '')
    }
else:
    tr_ctx = {
        'title': fields.get('title_tr', ''),
        'date': date_val,
        'thumbnail': thumbnail,
        'description': fields.get('description_tr', ''),
        'content': fields.get('content_tr', '')
    }
print(f"[DEBUG] Turkish context: {tr_ctx}")
tr_out = tmpl.render(**tr_ctx)
out_path_tr = os.path.join(out_dir, 'index.tr.md')
with open(out_path_tr, 'w', encoding='utf-8') as f:
    f.write(tr_out)
print(f"[DEBUG] Wrote Turkish markdown: {out_path_tr}")
