import os
import re
import requests
from github import Github
from jinja2 import Environment, FileSystemLoader
from datetime import datetime

# --- CONFIG ---
REPO_NAME = os.getenv("GITHUB_REPOSITORY")  # e.g. 'bouncmpe/bouncmpe.github.io'
ISSUE_NUMBER = int(os.getenv("ISSUE_NUMBER"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
TEMPLATES_DIR = "templates"

# --- INIT ---
gh = Github(GITHUB_TOKEN)
repo = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)

# --- Extract fields ---
def parse_fields(body):
    """
    Converts Markdown-style form fields into a dictionary
    """
    field_pattern = re.compile(r"### (.*?)\n\n(.*?)(?=\n###|\Z)", re.DOTALL)
    matches = field_pattern.findall(body)
    return {k.strip().lower().replace(" ", "_"): v.strip() for k, v in matches}

fields = parse_fields(issue.body or "")

# Debug print
print("Parsed fields:", fields)

# --- Required fields ---
template_type = fields.get("template_type", "").lower()  # 'event' or 'news'
title = fields.get("title", issue.title)
description = fields.get("description", "")
thumbnail_url = fields.get("poster_or_cover_image", "")
content = fields.get("description", "")
date_str = fields.get("date", datetime.utcnow().strftime("%Y-%m-%d"))

# Additional fields for event
event_fields = {
    "event_type": fields.get("event_type", "General"),
    "name": fields.get("event_name", ""),
    "datetime": fields.get("start_date_and_time", ""),
    "duration": fields.get("duration", ""),
    "location": fields.get("location", "")
}

# --- Download thumbnail ---
def download_image(url, save_dir):
    if not url or not url.startswith("http"):
        return None
    response = requests.get(url)
    if response.status_code == 200:
        filename = os.path.basename(url.split("?")[0])
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, filename)
        with open(path, "wb") as f:
            f.write(response.content)
        return filename
    return None

thumbnail_filename = download_image(thumbnail_url, f"static/images/{template_type}")
if thumbnail_filename:
    thumbnail_relative_path = f"/images/{template_type}/{thumbnail_filename}"
else:
    thumbnail_relative_path = None

# --- Jinja render ---
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
template_file = f"{template_type}.md.j2"
template = env.get_template(template_file)

context = {
    "title": title,
    "description": description,
    "date": date_str,
    "thumbnail": thumbnail_relative_path,
    "content": content
}

if template_type == "event":
    context.update(event_fields)

output_md = template.render(context)

# --- Write file ---
slug = re.sub(r'\W+', '-', title.lower()).strip("-")
filename = f"{slug}.md"
output_dir = f"content/{template_type}s"
os.makedirs(output_dir, exist_ok=True)

output_path = os.path.join(output_dir, filename)
with open(output_path, "w", encoding="utf-8") as f:
    f.write(output_md)




