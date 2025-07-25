import os
import re
import unicodedata
import requests
from urllib.parse import urlparse
from jinja2 import Environment, FileSystemLoader

# 1) Read inputs from environment variables
labels = os.getenv("ISSUE_LABELS", "").lower()
body = os.getenv("ISSUE_BODY", "").strip()
is_news = "news" in labels

# 2) Setup Jinja2 template environment
env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=False
)

# 3) Slugify function (for folder names)
def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-_ ")

# 4) Parse GitHub Issue body into label-value dictionary
def parse_issue_body(md):
    fields = {}
    blocks = re.split(r"^#{1,6}\s+", md, flags=re.MULTILINE)[1:]
    for blk in blocks:
        lines = blk.splitlines()
        if not lines:
            continue
        label = lines[0].strip()
        value = "\n".join(lines[1:]).strip()
        fields[label] = value
    return fields

parsed = parse_issue_body(body)

# 5) Safe field lookup
def get_field(label):
    return parsed.get(label, "").strip()

# 6) Download image (if provided)
def download_image(md_input):
    print(f" Raw image input: {md_input}")
    url = None
    m = re.search(r"!\[[^\]]*\]\((https?://[^)]+)\)", md_input)
    if m:
        url = m.group(1)
    else:
        m2 = re.search(r'src=\"(https?://[^\"]+)\"', md_input)
        if m2:
            url = m2.group(1)
    if not url:
        print(" No valid image URL found.")
        return ""

    print(f" Downloading image from: {url}")
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f" Failed to fetch image: {e}")
        return ""

    # Infer file extension
    ct = resp.headers.get("Content-Type", "")
    ext = ''
    if 'png' in ct:
        ext = '.png'
    elif 'jpeg' in ct or 'jpg' in ct:
        ext = '.jpg'
    elif 'gif' in ct:
        ext = '.gif'

    # Build filename from URL
    path_part = urlparse(url).path
    name = os.path.basename(path_part) or 'image'
    if not os.path.splitext(name)[1] and ext:
        name += ext

    save_dir = os.path.join('assets', 'uploads')
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, name)

    try:
        with open(save_path, 'wb') as f:
            f.write(resp.content)
        print(f" Saved image to: {save_path}")
        return f"uploads/{name}"
    except Exception as e:
        print(f" Error saving image: {e}")
        return ""

# 7) Determine content type and path
if is_news:
    date = get_field('Date (YYYY-MM-DD)')
    slug = slugify(get_field('News Title (EN)'))
    base = f"content/news/{date}-news-{slug}"
    template_file = "news.md.j2"
else:
    raw_dt = get_field('Date and Time (ISO format)')
    date = raw_dt.split('T')[0]
    slug = slugify(get_field('Event Title (EN)'))
    base = f"content/events/{date}-event-{slug}"
    template_file = "event.md.j2"

os.makedirs(base, exist_ok=True)

# 8) Process image
img_label = 'Image (drag & drop here)' if is_news else 'Image (optional, drag & drop)'
img_md = get_field(img_label)
thumbnail_path = download_image(img_md) if img_md else ''

# 9) Render Jinja template for both English and Turkish
for lang in ['en', 'tr']:
    context = {}

    if is_news:
        context = {
            'title': get_field(f'News Title ({lang.upper()})'),
            'description': get_field(f'Short Description ({lang.upper()})'),
            'date': date,
            'thumbnail': thumbnail_path,
            'content': get_field(f'Full Content ({lang.upper()})')
        }
    else:
        context = {
            'event_type': get_field('Event Type'),  # From dropdown
            'title': get_field(f'Event Title ({lang.upper()})'),
            'name': get_field('Speaker/Presenter Name'),
            'datetime': raw_dt,
            'duration': get_field('Duration'),
            'location': get_field(f'Location ({lang.upper()})'),
            'thumbnail': thumbnail_path,
            'description': get_field(f'Description ({lang.upper()})')
        }

    # Load and render Jinja template
    template = env.get_template(template_file)
    output = template.render(**context)

    # Write markdown file
    out_file = f"{base}/index.{lang}.md"
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(output)
    print(f" Created: {out_file}")
