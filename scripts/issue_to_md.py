#!/usr/bin/env python3
import os
import re
import unicodedata
import requests
from github import Github
from jinja2 import Environment, FileSystemLoader

# ─── CONFIG ───────────────────────────────────────────────────────────────────
REPO_NAME    = os.getenv("GITHUB_REPOSITORY")      # e.g. "bouncmpe/bouncmpe.github.io"
ISSUE_NUMBER = int(os.getenv("ISSUE_NUMBER", "0")) # should be set in your workflow
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
TEMPLATES_DIR = "templates"
UPLOADS_DIR   = os.path.join("assets", "uploads")

# ─── INITIALIZE ────────────────────────────────────────────────────────────────
if not GITHUB_TOKEN or ISSUE_NUMBER == 0:
    raise RuntimeError("GITHUB_TOKEN and ISSUE_NUMBER must be set in env")

gh   = Github(GITHUB_TOKEN)
repo = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)

print(f"[DEBUG] Processing issue #{ISSUE_NUMBER}: {issue.title!r}")

# ─── PARSE FIELDS ──────────────────────────────────────────────────────────────
def parse_fields(body: str):
    """
    Parses all "### Label\n\nvalue" blocks into a dict:
      { 'label_name': 'the user input', … }
    Normalizes keys to lowercase_underscored.
    """
    field_pattern = re.compile(
        r"^#{1,6}\s+(.*?)\s*\n\n(.*?)(?=^#{1,6}\s|\Z)",
        re.MULTILINE | re.DOTALL
    )
    matches = field_pattern.findall(body)
    parsed = {}
    for label, val in matches:
        key = label.strip().lower().replace(" ", "_")
        parsed[key] = val.strip()
    return parsed

fields = parse_fields(issue.body or "")
print(f"[DEBUG] Parsed fields: {fields}")

# ─── DETERMINE TYPE ────────────────────────────────────────────────────────────
# If the form had an "event_type" dropdown → treat as event,
# otherwise assume news.
is_event = "event_type" in fields
template_type = "event" if is_event else "news"
template_file = f"{template_type}.md.j2"
print(f"[DEBUG] Inferred template_type = {template_type!r}")

# ─── SLUGIFY ───────────────────────────────────────────────────────────────────
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-_")

# ─── IMAGE DOWNLOAD ────────────────────────────────────────────────────────────
def download_image(md_input: str) -> str:
    """
    Accepts either:
      - Markdown: ![alt](https://…)
      - HTML: <img src="https://…">
    Returns the local path under UPLOADS_DIR, or empty string.
    """
    # find URL
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md_input)
    if not m:
        m = re.search(r'src="(https?://[^"]+)"', md_input)
    if not m:
        print("[WARN] No image URL found in:", md_input)
        return ""
    url = m.group(1)
    print("[DEBUG] Downloading image from", url)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    # infer extension
    ct = resp.headers.get("Content-Type", "")
    ext = ""
    if "png"  in ct: ext = ".png"
    if "jpeg" in ct or "jpg" in ct: ext = ".jpg"
    if "gif"  in ct: ext = ".gif"

    # filename from URL
    filename = os.path.basename(url.split("?",1)[0])
    if not os.path.splitext(filename)[1] and ext:
        filename += ext

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    save_path = os.path.join(UPLOADS_DIR, filename)
    with open(save_path, "wb") as f:
        f.write(resp.content)
    print(f"[DEBUG] Image saved to {save_path}")
    # return relative path for frontmatter
    return f"uploads/{filename}"

# ─── BUILD CONTEXT ─────────────────────────────────────────────────────────────
# Shared fields:
title_key = "news_title_(en)" if not is_event else "event_title_(en)"
title = fields.get(title_key, issue.title)
date  = fields.get("date", "")
desc  = fields.get("description_(en)", "")
img_md = fields.get("image_markdown", "") or fields.get("image_(optional,_drag_&_drop)", "")
thumbnail = download_image(img_md) if img_md else ""

context = {
    "title": title,
    "description": desc,
    "date": date,
    "thumbnail": thumbnail,
    "content": fields.get("content_(en)", "") if not is_event else fields.get("description_(en)", "")
}

if is_event:
    context.update({
        "event_type": fields.get("event_type", ""),
        "name":       fields.get("speaker/presenter_name", ""),
        "datetime":   fields.get("date_and_time_(iso_format)", ""),
        "duration":   fields.get("duration", ""),
        "location":   fields.get("location_(en)", "")
    })

print(f"[DEBUG] Rendering template {template_file} with context:")
for k,v in context.items():
    print(f"  - {k}: {v!r}")

# ─── RENDER & WRITE ────────────────────────────────────────────────────────────
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
try:
    tmpl = env.get_template(template_file)
except Exception as e:
    raise FileNotFoundError(f"Could not load template '{template_file}' from '{TEMPLATES_DIR}'") from e

output = tmpl.render(**context)

# determine output path
slug = slugify(title)
subdir = "events" if is_event else "news"
base_dir = os.path.join("content", subdir, f"{date}-{slug}")
os.makedirs(base_dir, exist_ok=True)

# write both EN and TR
for lang in ("en","tr"):
    fname = os.path.join(base_dir, f"index.{lang}.md")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(output)
   



