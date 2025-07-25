#!/usr/bin/env python3
import os, re, unicodedata, requests
from github import Github
from jinja2 import Environment, FileSystemLoader

# CONFIG
REPO_NAME     = os.getenv("GITHUB_REPOSITORY")
ISSUE_NUMBER  = int(os.getenv("ISSUE_NUMBER", "0"))
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
TEMPLATES_DIR = "templates"
UPLOADS_DIR   = os.path.join("assets", "uploads")

if not GITHUB_TOKEN or ISSUE_NUMBER == 0:
    raise RuntimeError("GITHUB_TOKEN and ISSUE_NUMBER must be set")

# GitHub API
gh    = Github(GITHUB_TOKEN)
repo  = gh.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)
print(f"[DEBUG] Processing issue #{ISSUE_NUMBER}: {issue.title!r}")

# Parse fields
def parse_fields(body):
    pattern = re.compile(r"^#{1,6}\s+(.*?)\s*\n\n(.*?)(?=^#{1,6}\s|\Z)", re.M|re.S)
    parsed = {}
    for label, val in pattern.findall(body or ""):
        key = label.strip().lower().replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "").replace(",", "")
        parsed[key] = val.strip()
    return parsed

fields = parse_fields(issue.body)
print(f"[DEBUG] Parsed fields: {fields.keys()}")

# Determine template
is_event     = "event_type" in fields
template_key = fields.get("event_type", "").lower() if is_event else "news"
template_file= f"{template_key}.md.j2"
print(f"[DEBUG] Using template file: {template_file}")

# Slugify
def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+","-", text).strip("-_")

# Download image
def download_image(md_input):
    m = re.search(r"!\[[^\]]*\]\((https?://[^\)]+)\)", md_input) or re.search(r'src="(https?://[^"]+)"', md_input)
    if not m:
        return ""
    url = m.group(1)
    resp = requests.get(url, timeout=15); resp.raise_for_status()
    ct = resp.headers.get("Content-Type","")
    ext = ".png" if "png" in ct else ".jpg" if any(x in ct for x in ("jpeg","jpg")) else ".gif" if "gif" in ct else ""
    fname = os.path.basename(url.split("?",1)[0])
    if not os.path.splitext(fname)[1] and ext: fname += ext
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    path = os.path.join(UPLOADS_DIR, fname)
    with open(path,"wb") as f: f.write(resp.content)
    return f"uploads/{fname}"

# Detect image field
img_key = next((k for k in fields if k.startswith("image")), None)
thumbnail = download_image(fields[img_key]) if img_key else ""

# Context builder
def build_context(lang):
    ctx = {"thumbnail": thumbnail}
    if is_event:
        ctx.update({
            "date":      fields.get("date_and_time_iso_format","").split("T")[0],
            "event_type":fields["event_type"],
            "title":     fields.get(f"event_title_{lang}",""),
            "name":      fields.get("speaker_presenter_name",""),
            "datetime":  fields.get("date_and_time_iso_format",""),
            "duration":  fields.get("duration",""),
            "location":  fields.get(f"location_{lang}",""),
            "description":fields.get(f"description_{lang}",""),
        })
    else:
        ctx.update({
            "date":       fields.get("date",""),
            "title":      fields.get(f"news_title_{lang}",""),
            "description":fields.get(f"short_description_{lang}",""),
            "content":    fields.get(f"full_content_{lang}",""),
        })
    return ctx

# Render & write
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
tmpl = env.get_template(template_file)

slug_base = slugify(fields.get(f"{template_key}_title_en", issue.title))
out_dir   = os.path.join("content", f"{'events' if is_event else 'news'}", f"{fields.get('date','')}-{slug_base}")
os.makedirs(out_dir, exist_ok=True)

for lang in ("en","tr"):
    ctx = build_context(lang)
    print(f"[DEBUG] Context for {lang}: {ctx}")
    rendered = tmpl.render(**ctx)
    path = os.path.join(out_dir, f"index.{lang}.md")
    with open(path,"w", encoding="utf-8") as f: f.write(rendered)
   

