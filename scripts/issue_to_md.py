#!/usr/bin/env python3
import os
import re
import unicodedata
import requests
from github import Github
from jinja2 import Environment, FileSystemLoader

# ─── CONFIG ───────────────────────────────────────────────────────────────────
REPO_NAME     = os.getenv("GITHUB_REPOSITORY")       # e.g. "bouncmpe/bouncmpe.github.io"
ISSUE_NUMBER  = int(os.getenv("ISSUE_NUMBER", "0"))  # set in your workflow
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
TEMPLATES_DIR = "templates"
UPLOADS_DIR   = os.path.join("assets", "uploads")

if not GITHUB_TOKEN or ISSUE_NUMBER == 0:
    raise RuntimeError("GITHUB_TOKEN and ISSUE_NUMBER must be set")

# ─── GITHUB API SETUP ─────────────────────────────────────────────────────────
gh    = Github(GITHUB_TOKEN)
repo  = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)
print(f"[DEBUG] Processing issue #{ISSUE_NUMBER}: {issue.title!r}")

# ─── PARSE FORM FIELDS ─────────────────────────────────────────────────────────
def parse_fields(body: str):
    pattern = re.compile(
        r"^#{1,6}\s+(.*?)\s*\n\n(.*?)(?=^#{1,6}\s|\Z)",
        re.MULTILINE | re.DOTALL
    )
    parsed = {}
    for label, val in pattern.findall(body or ""):
        key = (label.strip()
                  .lower()
                  .replace(" ", "_")
                  .replace("/", "_")
                  .replace("(", "")
                  .replace(")", "")
                  .replace(",", "")
              )
        parsed[key] = val.strip()
    return parsed

fields = parse_fields(issue.body)
print(f"[DEBUG] Parsed fields: {fields.keys()}")

# ─── DETERMINE TEMPLATE FILE ───────────────────────────────────────────────────
is_event     = "event_type" in fields
template_key = fields.get("event_type", "news").lower() if is_event else "news"
template_file= f"{template_key}.md.j2"
print(f"[DEBUG] Using template: {template_file}")

# ─── SLUGIFY HELPER ────────────────────────────────────────────────────────────
def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-_")

# ─── IMAGE DOWNLOAD ────────────────────────────────────────────────────────────
def download_image(md_input: str) -> str:
    """
    Finds the first URL in Markdown ![](...) or HTML <img src="...">,
    downloads it into UPLOADS_DIR, and returns the 'uploads/...' path.
    """
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md_input) \
        or re.search(r'src="(https?://[^"]+)"', md_input)
    if not m:
        print("[WARN] No image URL found in field value:", md_input)
        return ""
    url = m.group(1)
    print("[DEBUG] Downloading image from", url)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    ext = ".png" if "png" in content_type else \
          ".jpg" if ("jpeg" in content_type or "jpg" in content_type) else \
          ".gif" if "gif" in content_type else ""

    filename = os.path.basename(url.split("?", 1)[0])
    if not os.path.splitext(filename)[1] and ext:
        filename += ext

    os.makedirs(UPLOADS_DIR, exist_ok=True)
    save_path = os.path.join(UPLOADS_DIR, filename)
    with open(save_path, "wb") as f:
        f.write(resp.content)
    print(f"[DEBUG] Image saved to {save_path}")
    return f"uploads/{filename}"

# ─── DETECT & DOWNLOAD POSTER IMAGE ───────────────────────────────────────────
# Now matches any key containing 'image'
img_keys = [k for k in fields if "image" in k]
thumbnail = ""
if img_keys:
    thumbnail = download_image(fields[img_keys[0]])

# ─── CONTEXT BUILDER ───────────────────────────────────────────────────────────
def build_context(lang: str):
    ctx = {"thumbnail": thumbnail}
    if is_event:
        ctx.update({
            "date":        fields.get("date_and_time_iso_format", "").split("T")[0],
            "event_type":  fields["event_type"],
            "title":       fields.get(f"event_title_{lang}", ""),
            "name":        fields.get("speaker_presenter_name", ""),
            "datetime":    fields.get("date_and_time_iso_format", ""),
            "duration":    fields.get("duration", ""),
            "location":    fields.get(f"location_{lang}", ""),
            "description": fields.get(f"description_{lang}", ""),
        })
    else:
        ctx.update({
            "date":        fields.get("date", ""),
            "title":       fields.get(f"news_title_{lang}", ""),
            "description": fields.get(f"short_description_{lang}", ""),
            "content":     fields.get(f"full_content_{lang}", ""),
        })
    return ctx

# ─── RENDER AND WRITE FILES ────────────────────────────────────────────────────
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_file)

slug_base = slugify(fields.get(f"{template_key}_title_en", issue.title))
subdir    = "events" if is_event else "news"
out_dir   = os.path.join("content", subdir, f"{fields.get('date','')}-{slug_base}")
os.makedirs(out_dir, exist_ok=True)

for lang in ("en", "tr"):
    ctx = build_context(lang)
    print(f"[DEBUG] Context for {lang}: {ctx}")
    rendered = tmpl.render(**ctx)
    out_path = os.path.join(out_dir, f"index.{lang}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"[✅] Wrote: {out_path}")


