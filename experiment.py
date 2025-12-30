from fastapi import FastAPI, BackgroundTasks
import uvicorn
import os
import dotenv
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
dotenv.load_dotenv()
import subprocess
import traceback
import re
from contextlib import asynccontextmanager
import asyncio
from playwright.async_api import async_playwright, Page
import json
from urllib.parse import urljoin
import httpx
import tempfile
import pathlib

# ============================================================
#  CONFIG: tweak these if needed
# ============================================================
# Maximum size (bytes) to inline as Part.from_bytes. If larger, will upload via Files API.
INLINE_SIZE_LIMIT = 15 * 1024 * 1024  # 15 MB, tune as needed

# Extensions we treat as supported for inline attachment (Part.from_bytes)
INLINE_EXTS = {
    # images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    # audio
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".opus": "audio/ogg; codecs=opus",
    # documents / text
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
}

# Extensions we treat as UNSUPPORTED (upload via Files API)
FILES_API_EXTS = {".db", ".sqlite", ".parquet", ".zip", ".gz"}

# ============================================================
#  LIFESPAN
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.playwright = await async_playwright().start()
    app.state.browser = await app.state.playwright.chromium.launch(headless=True)
    app.state.page = await app.state.browser.new_page()
    app.state.gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    print("Browser launched")
    try:
        yield
    finally:
        await app.state.page.close()
        await app.state.browser.close()
        await app.state.playwright.stop()
        print("Browser closed")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
#  UTILITIES
# ============================================================
def clean_json_text(raw: str) -> str:
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = raw.replace("...", "null")
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    return raw.strip()

def is_gemini_supported_url(url: str) -> bool:
    url = (url or "").lower()
    supported_ext = [
        ".html", ".htm",
        ".json", ".txt", ".xml",
        ".css", ".js",
        ".csv", ".rtf",
        ".png", ".jpg", ".jpeg", ".bmp", ".webp",
        ".pdf"
    ]
    if any(url.endswith(ext) for ext in supported_ext):
        return True
    api_text_indicators = ["json", "html", "data", "text"]
    if any(key in url for key in api_text_indicators):
        return True
    return False

def guess_mime_from_bytes(url: str, data: bytes) -> str:
    """Guess a usable MIME for inline parts (images, audio, pdf, csv, json, text)."""
    lower = (url or "").lower()
    for ext, mime in INLINE_EXTS.items():
        if lower.endswith(ext):
            return mime

    # Magic bytes detection (simple)
    if data.startswith(b"PAR1"):
        return "application/x-parquet"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    # PDF header
    if data.startswith(b"%PDF"):
        return "application/pdf"
    # Fallback
    return "application/octet-stream"

def ext_from_url(url: str) -> str:
    """Return file extension (lowercased) from URL path, or empty string."""
    if not url:
        return ""
    path = url.split("?")[0].split("#")[0]
    if "." in path:
        return "." + path.split("/")[-1].split(".")[-1].lower()
    return ""

# ------------------------------------------------------------
# Files API uploader (synchronous) — used for unsupported binaries
# ------------------------------------------------------------
def upload_file_to_gemini_files_api(app, file_bytes: bytes, file_name: str):
    """
    Synchronous uploader using client.files.upload(file=path).
    Note: we DO NOT pass mime_type here to avoid SDK issues.
    """
    tmp_dir = tempfile.gettempdir()
    safe_name = file_name or "file.bin"
    tmp_path = os.path.join(tmp_dir, safe_name)
    pathlib.Path(tmp_dir).mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "wb") as f:
        f.write(file_bytes)

    # NOTE: Do not pass mime_type (some SDK versions reject that arg).
    uploaded = app.state.gemini.files.upload(file=tmp_path)

    # cleanup
    try:
        os.remove(tmp_path)
    except Exception:
        pass

    return uploaded

# ============================================================
#  EXTRACTION (collect audio/video/img links too)
# ============================================================
async def extract_everything(page: Page, url: str):
    await page.goto(url, wait_until="networkidle")

    try:
        page_text = await page.inner_text("body")
    except:
        page_text = ""
    try:
        html = await page.content()
    except:
        html = ""

    # ---- JSON extraction (only dicts) ----
    payload_templates = []
    blocks = await page.query_selector_all("pre, code")
    for block in blocks:
        raw = (await block.inner_text()).strip()
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload_templates.append(parsed)
                continue
        except:
            pass
        cleaned = clean_json_text(raw)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                payload_templates.append(parsed)
        except:
            pass

    # ---- find submit URL ----
    submit_url = None
    url_pattern = r"(https?://[^\s\"'<>()]+|/[^\s\"'<>()]+)"

    for payload in payload_templates:
        if not isinstance(payload, dict):
            continue
        for _, value in payload.items():
            if isinstance(value, str):
                full = urljoin(page.url, value)
                if "submit" in full.lower():
                    submit_url = full
                    break
        if submit_url:
            break

    if not submit_url:
        for u in re.findall(url_pattern, page_text):
            full = urljoin(page.url, u)
            if "submit" in full.lower():
                submit_url = full
                break

    if not submit_url:
        for u in re.findall(url_pattern, html):
            full = urljoin(page.url, u)
            if "submit" in full.lower():
                submit_url = full
                break

    # ---- collect hrefs from <a> ----
    hrefs = []
    a_tags = await page.query_selector_all("a")
    for a in a_tags:
        h = await a.get_attribute("href")
        if h:
            hrefs.append(urljoin(page.url, h))

    # ---- collect images ----
    img_links = []
    img_tags = await page.query_selector_all("img")
    for img in img_tags:
        src = await img.get_attribute("src")
        if src:
            img_links.append(urljoin(page.url, src))

    bg_urls = re.findall(r'url\((.*?)\)', html)
    for bg in bg_urls:
        bg = bg.strip('\'"')
        if bg:
            img_links.append(urljoin(page.url, bg))

    # ---- collect audio / video sources ----
    media_srcs = []
    media_elements = await page.query_selector_all("audio, video")
    for el in media_elements:
        src = await el.get_attribute("src")
        if src:
            media_srcs.append(urljoin(page.url, src))

    source_tags = await page.query_selector_all("audio source, video source")
    for s in source_tags:
        src = await s.get_attribute("src")
        if src:
            media_srcs.append(urljoin(page.url, src))

    # ---- build download candidates ----
    download_candidates = []
    valid_exts = [
        ".db", ".sqlite", ".zip", ".gz",
        ".json", ".csv", ".pdf", ".txt",
        ".wav", ".mp3", ".opus",
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".parquet"
    ]
    api_like = ["download", "export", "dump", "file"]

    for h in hrefs:
        low = (h or "").lower()
        if any(low.endswith(ext) for ext in valid_exts) or any(k in low for k in api_like):
            download_candidates.append(h)

    # include images and media
    for img in img_links:
        if img not in download_candidates:
            download_candidates.append(img)
    for m in media_srcs:
        if m not in download_candidates:
            download_candidates.append(m)

    # ---- split into gemini-fetchable vs backend-only ----
    gemini_fetch_urls = []
    backend_fetch_urls = []
    for link in download_candidates:
        if is_gemini_supported_url(link):
            gemini_fetch_urls.append(link)
        else:
            backend_fetch_urls.append(link)

    return {
        "current_url": page.url,
        "page_text": page_text,
        "payload_templates": payload_templates,
        "submit_url": submit_url,
        "gemini_fetch_urls": gemini_fetch_urls,
        "backend_fetch_urls": backend_fetch_urls,
        "image_links": img_links,
        "html": html
    }

# ============================================================
#  BACKEND: download and either inline-attach or upload to Files API
# ============================================================
async def download_and_handle_file(url: str, client: httpx.AsyncClient, contents: list, app: FastAPI):
    """
    If file is a supported inline type and small enough -> attach Part.from_bytes(...)
    Otherwise -> upload via Files API (synchronous call via run_in_executor) and append the returned uploaded file object.
    """
    try:
        resp = await client.get(url, timeout=30.0)
        resp.raise_for_status()
        data = resp.content
        size = len(data)
        ext = ext_from_url(url)

        # Decide whether to inline
        inline_mime = None
        if ext in INLINE_EXTS:
            inline_mime = INLINE_EXTS[ext]
        else:
            # attempt to guess via magic bytes for some cases (e.g. png/jpg/pdf)
            guessed = guess_mime_from_bytes(url, data)
            if guessed != "application/octet-stream" and any(guessed.startswith(prefix) for prefix in ("image/", "audio/", "application/pdf", "text/", "application/json")):
                inline_mime = guessed

        if inline_mime and size <= INLINE_SIZE_LIMIT:
            # Inline attachment
            print(f"[INLINE] Attaching {url} as {inline_mime} ({size} bytes)")
            contents.append(
                types.Part.from_bytes(
                    data=data,
                    mime_type=inline_mime
                )
            )
            return

        # Else: upload via Files API for larger or unsupported binary
        print(f"[FILES API] Uploading {url} ({size} bytes) via Files API")
        file_name = url.split("/")[-1] or "file.bin"

        uploaded = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: upload_file_to_gemini_files_api(app, data, file_name)
        )

        print(f"[FILES API] Uploaded: {getattr(uploaded, 'name', '<unknown>')}")
        # Append the uploaded file object so Gemini can reference it in contents
        contents.append(uploaded)

    except Exception as e:
        print(f"❌ Failed to download/handle file {url}: {e}")

# ============================================================
#  LLM CALL
# ============================================================
async def call_llm(extracted: dict, app: FastAPI):
    prompt = f"""
You are an expert autonomous agent. Solve the task precisely.

Visit this URL:
{extracted['current_url']} solve the task present over there

If the Page reqires you downloaded ome files it will be provided here:
	Files I downloaded and handled (backend_fetch_urls):
	{json.dumps(extracted['backend_fetch_urls'], indent=2)}

The content of these files you can get yourself using URL Context Tool:
{json.dumps(extracted['gemini_fetch_urls'], indent=2)}


RULES:
- Use URL Tool only for gemini_fetch_urls.
- Inline-attached media are provided as binary parts in this request (images/audio/pdf/csv/json/text).
- Files uploaded via the Files API are attached as file objects (returned by client.files.upload()) and included in the contents list.
- Do NOT perform arbitrary network calls inside code execution.
- When using a Files API file, reference it by the file object name printed in the response or by index/order.

When you have the final result, print EXACTLY the JSON object (nothing else):

{{
  "email": "23f2004661@ds.study.iitm.ac.in",
  "secret": "toothless",
  "url": "{extracted['current_url']}",
  "answer": <THE_ANSWER>
}}
"""

    contents = [prompt]

    # Download & attach backend-only files (either inline or via Files API)
    async with httpx.AsyncClient() as client:
        for link in extracted.get("backend_fetch_urls", []):
            await download_and_handle_file(link, client, contents, app)

    # Tools: allow code execution + URL context
    tools = [
        types.Tool(code_execution=types.ToolCodeExecution()),
        types.Tool(url_context=types.UrlContext())
    ]

    try:
        response = app.state.gemini.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(tools=tools)
        )
    except Exception as e:
        print("❌ Gemini generate_content error:", e)
        traceback.print_exc()
        return

    # Print response parts for debugging
    try:
        parts = response.candidates[0].content.parts
        for part in parts:
            if getattr(part, "text", None):
                print("\n=== LLM TEXT ===\n", part.text)
            if getattr(part, "executable_code", None):
                print("\n=== LLM CODE ===\n", part.executable_code.code)
            if getattr(part, "code_execution_result", None):
                print("\n=== EXEC RESULT ===\n", part.code_execution_result.output)
    except Exception as e:
        print("LLM parse error:", e)
        traceback.print_exc()

# ============================================================
#  SOLVING WORKFLOW
# ============================================================
async def solve_quiz_step(page: Page, url: str):
    print(f"Solving quiz step at {url}")
    extracted = await extract_everything(page, url)
    print("Extracted:", extracted)
    await call_llm(extracted, app)

async def solve_quiz_chain(page: Page, start_url: str):
    print("Starting quiz solving chain")
    await solve_quiz_step(page, start_url)

# ============================================================
#  API ENDPOINT
# ============================================================
@app.post("/task")
async def handle_task(data: dict, background_tasks: BackgroundTasks):
    secret = os.getenv("SECRET")
    print(data)
    if data.get("secret") == secret:
        app.state.user_email = data["email"]
        app.state.user_secret = data["secret"]
        background_tasks.add_task(solve_quiz_chain, app.state.page, data["url"])
        return {"message": "Secret Matches!", "status_code": 200}
    else:
        return {"message": "Secret does not match", "status_code": 403}

if __name__ == "__main__":
    uvicorn.run(app, port=8000)
