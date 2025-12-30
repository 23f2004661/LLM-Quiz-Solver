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

def clean_json_text(raw: str) -> str:
	"""Clean malformed JSON in <pre> blocks."""
	# Remove HTML tags like <span class="origin">...</span>
	raw = re.sub(r"<[^>]+>", "", raw)

	# Replace invalid ellipsis (...) with null
	raw = raw.replace("...", "null")

	# Remove trailing commas before closing braces
	raw = re.sub(r",\s*([}\]])", r"\1", raw)

	return raw.strip()

async def extract_everything(page: Page, url: str):
	"""Load a quiz URL and extract all data for LLM."""

	# -------------------------
	# 1️⃣ Load main page
	# -------------------------
	await page.goto(url, wait_until="networkidle")

	# -------------------------
	# 2️⃣ Extract visible text
	# -------------------------
	try:
		page_text = await page.inner_text("body")
	except:
		page_text = ""
	try:
		html = await page.content()
	except:
		html = ""

	# -------------------------
	# 4️⃣ Extract JSON payloads from <pre>/<code>
	# -------------------------
	payload_templates = []
	blocks = await page.query_selector_all("pre, code")

	for block in blocks:
		raw = (await block.inner_text()).strip()

		# Try raw JSON
		try:
			payload_templates.append(json.loads(raw))
			continue
		except:
			pass

		# Clean JSON and retry
		cleaned = clean_json_text(raw)
		try:
			payload_templates.append(json.loads(cleaned))
		except:
			pass

	# -------------------------
	# 5️⃣ Find submit URL (relative or absolute)
	# -------------------------
	submit_url = None

	# A) Inside JSON payload
	for payload in payload_templates:
		for key, value in payload.items():
			if isinstance(value, str):
				full_url = urljoin(page.url, value)
				if "submit" in full_url.lower():
					submit_url = full_url
					break

	# Regex supports both relative + absolute
	url_pattern = r"(https?://[^\s\"'<>()]+|/[^\s\"'<>()]+)"

	# B) In visible text
	if not submit_url:
		urls = re.findall(url_pattern, page_text)
		for u in urls:
			full = urljoin(page.url, u)
			if "submit" in full.lower():
				submit_url = full
				break

	# C) In HTML
	if not submit_url:
		urls = re.findall(url_pattern, html)
		for u in urls:
			full = urljoin(page.url, u)
			if "submit" in full.lower():
				submit_url = full
				break

	# -------------------------
	# 6️⃣ Collect all <a> hrefs FIRST (Avoid stale DOM errors)
	# -------------------------
	hrefs = []
	a_tags = await page.query_selector_all("a")

	for a in a_tags:
		href = await a.get_attribute("href")
		if href:
			hrefs.append(urljoin(page.url, href))

	# -------------------------
	# 7️⃣ Extract linked internal pages (SAFE)
	# -------------------------
	linked_pages = {}
	for h in hrefs:
		# Only follow internal paths like /demo-scrape-data...
		if not h.startswith("http"):
			continue
		if page.url.split("//")[1].split("/")[0] not in h:
			continue
	# -------------------------
	# 8️⃣ Extract file links (PDF, CSV, AUDIO, IMG)
	# -------------------------
	pdfs, csvs, audios, images = [], [], [], []

	for h in hrefs:
		if h.endswith(".pdf"):
			pdfs.append(h)
		elif h.endswith(".csv"):
			csvs.append(h)
		elif any(h.endswith(ext) for ext in [".mp3", ".opus", ".wav"]):
			audios.append(h)
		elif any(h.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif"]):
			images.append(h)

	# Extract audio from <audio> tags
	audio_tags = await page.query_selector_all("audio")
	for audio in audio_tags:
		src = await audio.get_attribute("src")
		if src:
			audios.append(urljoin(page.url, src))

	# -------------------------
    # Extract <img src="...">
    # -------------------------
	img_tags = await page.query_selector_all("img")
	img_links = []
	for img in img_tags:
		src = await img.get_attribute("src")
		if not src:
			continue
		if src.startswith("data:image"):
			img_links.append(src)
		else:
			img_links.append(urljoin(page.url, src))
		
	bg_urls = re.findall(r'url\((.*?)\)', html)
	for bg in bg_urls:
		bg = bg.strip('\'"')
		img_links.append(urljoin(page.url, bg))

	script_tags = await page.query_selector_all("script:not([src])")
	js_scripts = []

	for tag in script_tags:
		try:
			content = await tag.inner_html()
			js_scripts.append(content)
		except:
			pass
	# -------------------------
	# 9️⃣ Return structured payload
	# -------------------------

	return {
		"current_url": page.url,
		"page_text": page_text,
		"payload_templates": payload_templates,
		"submit_url": submit_url,
		"pdf_links": pdfs,
		"csv_links": csvs,
		"audio_links": audios,
		"image_links": images + img_links,
		"linked_pages": linked_pages,
		"js_scripts": js_scripts,
	}

async def call_llm(extracted: dict, app: FastAPI):

	# ----------------------------------------------------
	# 1. Build the prompt
	# ----------------------------------------------------
	prompt = f"""You are an expert data scientist who can solve quizzes given in any webpage as quickly as possible
	This is the url of the current page: {extracted['current_url']}
	This is the content of the web page: {extracted['page_text']}
	Understand the question in the page and execute that task meticulously.
	if the question requires you to use audio's,csv's, pdf's or images it will be provided to you as attachments.
	use this secret or the email if required-
	secret = toothless
	email = 23f2004661@ds.study.iitm.ac.in

    Each web page you will get will require you to solve a task like:
        -Scraping a website (which may require JavaScript) for information
        -Sourcing from an API (with API-specific headers provided where required)
        -Cleansing text / data / PDF / … you retrieved
        -Processing the data (e.g. data transformation, transcription, vision)
        -Analysing by filtering, sorting, aggregating, reshaping, or applying statistical / ML models. Includes geo-spatial / network analysis
        -Visualizing by generating charts (as images or interactive), narratives, slides

    IMPORTANT:
    -After finding the solution to the task print a json like this:
        {{
        'email': '3f2004661@ds.study.iitm.ac.in',
        'secret': 'toothless',
        'url': {extracted['current_url']},
        'answer': 12345 // the correct answer
        }}
"""
	contents =[]
	# ----------------------------------------------------
	# 2. Download ALL files using ONE httpx client
	# ----------------------------------------------------
	async with httpx.AsyncClient() as client:

		# ---- CSVs ----
		for link in extracted["csv_links"]:
			try:
				resp = await client.get(link)
				contents.append(
					types.Part.from_bytes(
						data=resp.content,
						mime_type="text/csv",
					)
				)
			except Exception as e:
				print("CSV attach failed:", e)

		# ---- PDFs ----
		for link in extracted["pdf_links"]:
			try:
				resp = await client.get(link)
				contents.append(
					types.Part.from_bytes(
						data=resp.content,
						mime_type="application/pdf",
					)
				)
			except Exception as e:
				print("PDF attach failed:", e)

		def guess_audio_mime(url: str):
			if url.endswith(".mp3"):
				return "audio/mpeg"
			if url.endswith(".wav"):
				return "audio/wav"
			if url.endswith(".opus"):
				return "audio/ogg; codecs=opus"
			return "application/octet-stream"
		

		# ---- AUDIO ----
		for link in extracted["audio_links"]:
			try:
				resp = await client.get(link)
				mime = guess_audio_mime(link)
				contents.append(
					types.Part.from_bytes(
						data=resp.content,
						mime_type=mime 
					)
				)
			except Exception as e:
				print("Audio attach failed:", e)

		for link in extracted["image_links"]:
			try:
				resp = await client.get(link)
				ext = link.lower()
				if ext.endswith(".png"):
					mime = "image/png"
				elif ext.endswith(".jpg") or ext.endswith(".jpeg"):
					mime = "image/jpeg"
				elif ext.endswith(".gif"):
					mime = "image/gif"
				elif ext.endswith(".webp"):
					mime = "image/webp"
				elif ext.endswith(".svg"):
					mime = "image/svg+xml"
				else:
					mime = "application/octet-stream"
				contents.append(
					types.Part.from_bytes(
						data=resp.content,
						mime_type=mime
					)
				)
			except Exception as e:
				print("Image attach failed:", e)
	contents.append(prompt)
	
	print(f"Contents given to the prompt\n:{contents}")
	# ----------------------------------------------------
	# 4. Call Gemini
	# ----------------------------------------------------
	
	client = app.state.gemini
	code_execution_tool = types.Tool(code_execution=types.ToolCodeExecution)
	google_search_tool = types.Tool(google_search=types.GoogleSearch())
	url_context_tool = types.Tool(url_context=types.UrlContext())	
	automatic_function_calling=types.AutomaticFunctionCallingConfig(
		disable=True
    ),
	function_calling_tool = types.Tool(function_declarations=[submit_schema])
	all_tools = [
		code_execution_tool,
		google_search_tool,
		url_context_tool,
		function_calling_tool
	]
	response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=contents,
    config=types.GenerateContentConfig(
		automatic_function_calling=types.AutomaticFunctionCallingConfig(
		disable=True
    	),
        tools=all_tools
    	),
	)
	try:
		for part in response.candidates[0].content.parts:
			if part.text is not None:
				print(part.text)
			if part.executable_code is not None:
				print(part.executable_code.code)
			if part.code_execution_result is not None:
				print(part.code_execution_result.output)
	except Exception as e:
		print(e)
	try:
		if response.candidates[0].content.parts[0].function_call:
			function_call = response.candidates[0].content.parts[0].function_call
			print(f"Function to call: {function_call.name}")
			print(f"Arguments: {function_call.args}")
			return {
				"name": function_call.name,
				"args": function_call.args
			}
		else:
			print("No function call found in the response.")
			# print(response.text)

		# -------------------------------------------------------
		# ❌ NO FUNCTION CALL – USE SAFE FALLBACK
		# -------------------------------------------------------
		print("❌ No function call found.")
		# print("Finish reason:", cand.finish_reason)

		# 1. Pick template if available
		if extracted["payload_templates"]:
			template = extracted["payload_templates"][0]
			email = template.get("email", app.state.user_email)
			secret = template.get("secret", app.state.user_secret)
		else:
			# 2. No template → use stored values
			email = app.state.user_email
			secret = app.state.user_secret

		fallback_payload = {
			"email": email,
			"secret": secret,
			"url": extracted["current_url"],
			"answer": "anything"
		}

		return {
			"name": "submit_answer",
			"arguments": {
				"submit_url": extracted["submit_url"],
				"payload": fallback_payload,
			}
		}

	except Exception as e:
		print("❌ Invalid LLM response:", e)
		print(response)

		# SAME FALLBACK HERE TOO
		if extracted["payload_templates"]:
			template = extracted["payload_templates"][0]
			email = template.get("email", app.state.user_email)
			secret = template.get("secret", app.state.user_secret)
		else:
			email = app.state.user_email
			secret = app.state.user_secret

		fallback_payload = {
			"email": email,
			"secret": secret,
			"url": extracted["current_url"],
			"answer": "anything"
		}

		return {
			"name": "submit_answer",
			"arguments": {
				"submit_url": extracted["submit_url"],
				"payload": fallback_payload,
			}
		}



async def submit_answer(app: FastAPI, submit_url: str, payload: dict):
	print("📤 SUBMITTING ANSWER TO:", submit_url)
	print("📦 PAYLOAD:", payload)

	async with httpx.AsyncClient() as client:
		resp = await client.post(submit_url, json=payload)

	print("📥 SUBMISSION RESPONSE:", resp.text)

	try:
		result = resp.json()
	except:
		print("❌ Could not decode JSON")
		return

	print("response by server:", result)

	# 🔥 If server sends next URL → continue solving workflow
	if result.get("url"):
		next_url = result["url"]
		print("➡️ NEXT QUIZ URL:", next_url)
		await solve_quiz_chain(app.state.page, next_url)
	else:
		print("🏁 QUIZ ENDED")



async def solve_quiz_step(page: Page, url: str):
	print(f"Solving quiz step at {url}")

	extracted = await extract_everything(page, url)

	print("Extracted:", extracted)

	llm_output = await call_llm(extracted, app)

	if not llm_output:
		print("❌ LLM returned nothing.")
		return

	print("LLM output received:", llm_output)

	submit_url = llm_output["arguments"]["submit_url"]
	payload = llm_output["arguments"]["payload"]
	payload["url"] = extracted['current_url']
	payload["email"] = app.state.user_email
	payload["secret"] = app.state.user_secret
	await submit_answer(app,submit_url, payload)

async def solve_quiz_chain(page: Page, start_url: str):
	print("Starting quiz solving chain")
	await solve_quiz_step(page, start_url)

@app.post("/task")
async def handle_task(data: dict, background_tasks: BackgroundTasks):
	secret = os.getenv("SECRET")
	print(data)
	if data.get("secret") == secret:
		# Run the task in background (not implemented here)
		app.state.user_email = data["email"]
		app.state.user_secret = data["secret"]
		background_tasks.add_task(solve_quiz_chain, app.state.page, data['url'])
		return {"message": "Secret Matches!", "status_code": 200}
	else:
		return {"message": "Secret does not match", "status_code": 403}

if __name__ == "__main__":
	uvicorn.run(app,port=8000)

