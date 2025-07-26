#!/usr/bin/env python3
import os
import re
import unicodedata
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

# ─── PARSE ISSUE FORM FIELDS ──────────────────────────────────────────────────
def parse_fields(body: str):
    pattern = re.compile(
        r"^#{1,6}\s+(.*?)\s*\r?\n+(.*?)(?=^#{1,6}\s|\Z)",
        re.MULTILINE | re.DOTALL
    )
    parsed = {}
    for label, val in pattern.findall(body or ""):
        key = re.sub(r"[^a-z0-9_]", "_", label.lower()).strip("_")
        parsed[key] = val.strip()
    return parsed

fields = parse_fields(issue.body)

# ─── DETERMINE TEMPLATE
is_event      = fields.get("event_type") is not None
if is_event:
    template_path = f"events/{fields['event_type']}.md.j2"
else:
    template_path = "news.md.j2"

# ─── SLUGIFY UTILITY
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-_")

# ─── IMAGE DOWNLOAD
def download_image(md_input: str) -> str:
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md_input)
    if not m:
        return ""
    url = m.group(1)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    ext = os.path.splitext(url)[1] or ".png"
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    filename = os.path.basename(url.split("?", 1)[0])
    path = os.path.join(UPLOADS_DIR, filename)
    with open(path, "wb") as f:
        f.write(resp.content)
    return f"uploads/{filename}"

# detect image field
img_field = next((v for k, v in fields.items() if k.startswith("image")), "")
thumbnail = download_image(img_field) if img_field else ""

# ─── BUILD CONTEXT
def build_context():
    base = {
        "title": fields.get("title_en", issue.title),
        "date": fields.get("date", ""),
        "thumbnail": thumbnail
    }
    if is_event:
        base.update({
            "name": fields.get("name", ""),
            "duration": fields.get("duration", ""),
            "location": fields.get("location_en", ""),
            "description": fields.get("description_en", "")
        })
    else:
        base.update({
            "description": fields.get("short_description_en", ""),
            "content": fields.get("full_content_en", "")
        })
    return base

# ─── RENDER & WRITE
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_path)
ctx = build_context()

slug_base = slugify(ctx["title"])
out_dir = os.path.join("content", "events" if is_event else "news", f"{ctx['date']}-{slug_base}")

os.makedirs(out_dir, exist_ok=True)
out_file = os.path.join(out_dir, "index.en.md")
with open(out_file, "w", encoding="utf-8") as f:
    f.write(tmpl.render(**ctx))
