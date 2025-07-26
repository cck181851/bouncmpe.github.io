import os
import re
import sys
import requests
from github import Github
from jinja2 import Environment, FileSystemLoader
from datetime import datetime

# Constants
TEMPLATE_DIR = "templates"
OUTPUT_DIR = "content"
ASSETS_DIR = "assets/uploads"

# Setup Jinja2
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))

# Get GitHub token from env
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_NAME = os.getenv("GITHUB_REPOSITORY")
ISSUE_NUMBER = int(os.getenv("ISSUE_NUMBER", "0"))

if not GITHUB_TOKEN or not REPO_NAME or not ISSUE_NUMBER:
    print("Missing environment variables.")
    sys.exit(1)

gh = Github(GITHUB_TOKEN)
repo = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)

print(f"[DEBUG] Issue #{issue.number}: title={issue.title}")

# Parse body
def parse_issue_body(body):
    fields = {}
    fallback = {}

    # Attempt fallback parsing from markdown
    current_key = None
    for line in body.splitlines():
        if line.startswith("### "):
            current_key = line.strip("# ").strip().lower().replace(" ", "_")
        elif current_key and line.strip():
            fallback[current_key] = line.strip()

    # Attempt extracting from GitHub Issue Form
    match = re.search(r"```json\s+(.*?)\s+```", body, re.DOTALL)
    if match:
        import json
        try:
            fields = json.loads(match.group(1))
        except json.JSONDecodeError:
            print("[DEBUG] Failed to parse JSON block.")
            fields = {}
    
    fields = fields or fallback
    print(f"[DEBUG] Fallback parsed fields: {fallback}")
    print(f"[DEBUG] Fields after parse: {fields}")
    return fields

fields = parse_issue_body(issue.body)

# Extract info
title_en = fields.get("event_title__en", issue.title)
title_tr = fields.get("event_title__tr", "")
description_en = fields.get("description__en", "")
description_tr = fields.get("description__tr", "")
speaker_name = fields.get("speaker_presenter_name", fields.get("name", ""))
duration = fields.get("duration", "")
location_en = fields.get("location__en", "")
location_tr = fields.get("location__tr", "")
image_md = fields.get("image__optional__drag___drop", "")
time_val = fields.get("time", "")
date_val = fields.get("date__yyyy_mm_dd", fields.get("date", ""))
event_type = fields.get("event_type", "other")

print(f"[DEBUG] Extracted: name={speaker_name}, img_md={image_md}, time={time_val}")
print(f"[DEBUG] Raw image input: {image_md}")

# Combine date + time
datetime_val = ""
if date_val and time_val:
    datetime_val = f"{date_val}T{time_val}"
elif date_val:
    datetime_val = date_val

# Handle image download
def download_image(md_input: str) -> str:
    match = re.search(r'src="([^"]+)"', md_input)
    if not match:
        return ""
    url = match.group(1)
    print(f"[DEBUG] Downloading image URL: {url}")
    os.makedirs(ASSETS_DIR, exist_ok=True)
    filename = url.split("/")[-1]
    path = os.path.join(ASSETS_DIR, filename)

    try:
        r = requests.get(url)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        print(f"[DEBUG] Saved image to: {path}")
        return f"/{ASSETS_DIR}/{filename}"
    except Exception as e:
        print(f"[ERROR] Image download failed: {e}")
        return ""

thumbnail_path = download_image(image_md)
print(f"[DEBUG] thumbnail path: {thumbnail_path}")

# Slug
slug = title_en.lower().replace(" ", "-").replace(".", "").replace(",", "")
output_path = os.path.join(OUTPUT_DIR, "events", f"{date_val}-{slug}")
os.makedirs(output_path, exist_ok=True)

# Select template
template_path = f"events/{event_type}.md.j2"
try:
    tmpl = env.get_template(template_path)
except Exception as e:
    print(f"[ERROR] Template load failed: {e}")
    sys.exit(1)

# Prepare context
ctx_en = {
    "title": title_en,
    "date": date_val,
    "thumbnail": thumbnail_path,
    "event_type": event_type,
    "speaker": speaker_name,
    "duration": duration,
    "location": location_en,
    "datetime": datetime_val,
    "description": description_en,
}
ctx_tr = {
    "title": title_tr,
    "date": date_val,
    "thumbnail": thumbnail_path,
    "event_type": event_type,
    "speaker": speaker_name,
    "duration": duration,
    "location": location_tr,
    "datetime": datetime_val,
    "description": description_tr,
}

print(f"[DEBUG] ctx_en: {ctx_en}")
print(f"[DEBUG] ctx_tr: {ctx_tr}")

# Render and write
out_path_en = os.path.join(output_path, "index.en.md")
out_path_tr = os.path.join(output_path, "index.tr.md")

with open(out_path_en, "w", encoding="utf-8") as f:
    f.write(tmpl.render(**ctx_en))
with open(out_path_tr, "w", encoding="utf-8") as f:
    f.write(tmpl.render(**ctx_tr))

# Print front-matter preview
try:
    with open(out_path_en, "r", encoding="utf-8") as f:
        lines = [next(f) for _ in range(10)]
        print("[DEBUG] Generated MD front-matter:\n" + "".join(lines))
except Exception:
    pass

