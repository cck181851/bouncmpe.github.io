import os
import re
import json
import sys
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

# Read inputs
issue_json_path = os.environ["ISSUE_JSON_PATH"]
template_dir = os.environ["TEMPLATE_DIR"]
output_dir = os.environ["OUTPUT_DIR"]
issue_number = os.environ["ISSUE_NUMBER"]
is_event = os.environ["IS_EVENT"].lower() == "true"

# Load issue JSON
with open(issue_json_path, encoding="utf-8") as f:
    issue = json.load(f)

fields = {}
for line in issue["body"].splitlines():
    if match := re.match(r"^### (.+)", line):
        current = match.group(1).strip().lower().replace(" ", "_")
        fields[current] = ""
    elif line.strip() and current:
        fields[current] += (line.strip() + "\n")

# Normalize field keys
fields = {k.strip(): v.strip() for k, v in fields.items()}

# Get image if available
thumbnail = fields.get("poster_or_cover_image", "").strip()

# Language loop
env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
langs = ["en", "tr"]
template_name = "event.md.j2" if is_event else "news.md.j2"

def build_context(lang):
    ctx = {
        "thumbnail": thumbnail
    }

    if is_event:
        ctx.update({
            "date":        fields.get("date_and_time_iso_format", "").split("T")[0],
            "event_type":  fields.get("event_type", ""),
            "title":       fields.get(f"event_name_{lang}", ""),
            "name":        fields.get("speaker_presenter_name", ""),
            "datetime":    fields.get("date_and_time_iso_format", ""),
            "duration":    fields.get("duration", ""),
            "location":    fields.get(f"location_{lang}", ""),
            "description": fields.get(f"description_{lang}", "") or fields.get(f"short_description_{lang}", "")
        })
    else:
        ctx.update({
            "date":        fields.get("date", "") or fields.get("date_and_time_iso_format", "").split("T")[0],
            "title":       fields.get(f"news_title_{lang}", ""),
            "description": fields.get(f"short_description_{lang}", "") or fields.get(f"description_{lang}", ""),
            "content":     fields.get(f"full_content_{lang}", ""),
        })

    return ctx

for lang in langs:
    context = build_context(lang)
    template = env.get_template(template_name)
    output = template.render(**context)

    filename = f"{issue_number}_{lang}.md"
    with open(os.path.join(output_dir, filename), "w", encoding="utf-8") as f:
        f.write(output)

