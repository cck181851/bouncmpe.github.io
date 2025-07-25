import os
import re
import requests
import datetime
from github import Github
from jinja2 import Environment, FileSystemLoader

# --- Config ---
REPO_NAME = os.getenv("GITHUB_REPOSITORY")
ISSUE_NUMBER = int(os.getenv("ISSUE_NUMBER"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
EVENT_TYPE = os.getenv("EVENT_TYPE")  # 'opened', 'edited', 'closed', etc.
BRANCH_NAME = f"auto/add-{ISSUE_NUMBER}"
TARGET_DIR = "_data/news"  # Or "_data/events" based on issue type

# --- Setup ---
g = Github(GITHUB_TOKEN)
repo = g.get_repo(REPO_NAME)
issue = repo.get_issue(number=ISSUE_NUMBER)

print(f"[DEBUG] Issue title: {issue.title}")

# --- Field Parsing ---
def parse_fields(body):
    fields = {}
    current = None
    for line in body.splitlines():
        if line.startswith("### "):
            current = line[4:].strip().lower()
            fields[current] = ""
        elif current:
            fields[current] += line.strip() + "\n"
    return {k.strip(): v.strip() for k, v in fields.items() if v.strip()}

fields = parse_fields(issue.body or "")
print("[DEBUG] Parsed fields:", fields)

# --- Determine Type and Template ---
if "event name" in fields:
    template_file = "event.md.j2"
    TARGET_DIR = "_data/events"
else:
    template_file = "news.md.j2"
    TARGET_DIR = "_data/news"

# --- Render with Jinja ---
env = Environment(loader=FileSystemLoader("templates"))
template = env.get_template(template_file)

# Normalize keys (map both TR and EN titles, etc.)
content = template.render({
    "event_type": fields.get("event type", "general"),
    "title": fields.get("event title (en)", fields.get("title", "Untitled")),
    "name": fields.get("speaker/presenter name", ""),
    "datetime": fields.get("date and time (iso format)", ""),
    "duration": fields.get("duration", ""),
    "location": fields.get("location (en)", fields.get("location", "")),
    "thumbnail": extract_image_url(fields.get("image (optional, drag & drop)", "")),
    "description": fields.get("description (en)", "")
})

# --- Helper: Extract image URL ---
def extract_image_url(markdown):
    if not markdown:
        return ""
    match = re.search(r'src=\"(.*?)\"', markdown)
    return match.group(1) if match else ""

# --- Save file ---
os.makedirs(TARGET_DIR, exist_ok=True)
filepath = f"{TARGET_DIR}/{ISSUE_NUMBER}.md"
with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print(f"[INFO] Written content to {filepath}")

# --- Create or update PR ---
def create_or_update_branch():
    base = repo.get_branch("main")
    try:
        branch = repo.get_branch(BRANCH_NAME)
    except:
        repo.create_git_ref(ref=f"refs/heads/{BRANCH_NAME}", sha=base.commit.sha)

    repo.update_file(
        path=filepath,
        message=f"Auto-update from issue #{ISSUE_NUMBER}",
        content=content,
        sha=get_file_sha(filepath),
        branch=BRANCH_NAME,
    )

def get_file_sha(path):
    try:
        file = repo.get_contents(path, ref=BRANCH_NAME)
        return file.sha
    except:
        return None

def create_pull_request():
    pulls = repo.get_pulls(state="open", head=f"{repo.owner.login}:{BRANCH_NAME}")
    if pulls.totalCount == 0:
        repo.create_pull(
            title=f"Auto PR for Issue #{ISSUE_NUMBER}",
            body=f"Generated from issue #{ISSUE_NUMBER}",
            head=BRANCH_NAME,
            base="main",
        )

# --- Handle Events ---
if EVENT_TYPE in ["opened", "edited"]:
    create_or_update_branch()
    create_pull_request()

elif EVENT_TYPE == "closed":
    # Optional: auto-close PR or cleanup branch
    print(f"[INFO] Issue closed. Consider closing related PRs manually.")

else:
    print(f"[WARN] Unhandled EVENT_TYPE: {EVENT_TYPE}")


