# async def call_llm(extracted: dict, app: FastAPI):

# 	# ----------------------------------------------------
# 	# 1. Build the prompt
# 	# ----------------------------------------------------
# 	prompt = f"""You are an expert data scientist who can solve quizzes given in any webpage as quickly as possible
# 	This is the url of the current page: {extracted['current_url']}
# 	This is the content of the web page: {extracted['page_text']}
# 	Understand the question in the page and execute that task meticulously.
# 	if the question requires you to use audio's,csv's, pdf's or images it will be provided to you as attachments.
# 	use this secret or the email if required-
# 	secret = toothless
# 	email = 23f2004661@ds.study.iitm.ac.in

#     Each web page you will get will require you to solve a task like:
#         -Scraping a website (which may require JavaScript) for information
#         -Sourcing from an API (with API-specific headers provided where required)
#         -Cleansing text / data / PDF / … you retrieved
#         -Processing the data (e.g. data transformation, transcription, vision)
#         -Analysing by filtering, sorting, aggregating, reshaping, or applying statistical / ML models. Includes geo-spatial / network analysis
#         -Visualizing by generating charts (as images or interactive), narratives, slides

#     IMPORTANT:
#     -After finding the solution to the task print a json like this:
#         {{
#         'email': '23f2004661@ds.study.iitm.ac.in',
#         'secret': 'toothless',
#         'url': {extracted['current_url']},
#         'answer': 12345 // the correct answer
#         }}

# 	-DO NOT Try to submit the answer yourself just return me the JSON I will Perform the submission myself
# 	- Always return json in code_execution_result.output even if you are not able to get the answer
# """

# 	# Gemini "contents" list
# 	contents = [prompt]

# 	# ----------------------------------------------------
# 	# 2. Download ALL files using ONE httpx client
# 	# ----------------------------------------------------
# 	async with httpx.AsyncClient() as client:

# 		# ---- CSVs ----
# 		for link in extracted["csv_links"]:
# 			try:
# 				resp = await client.get(link)
# 				contents.append(
# 					types.Part.from_bytes(
# 						data=resp.content,
# 						mime_type="text/csv",
# 					)
# 				)
# 			except Exception as e:
# 				print("CSV attach failed:", e)

# 		# ---- PDFs ----
# 		for link in extracted["pdf_links"]:
# 			try:
# 				resp = await client.get(link)
# 				contents.append(
# 					types.Part.from_bytes(
# 						data=resp.content,
# 						mime_type="application/pdf",
# 					)
# 				)
# 			except Exception as e:
# 				print("PDF attach failed:", e)

# 		def guess_audio_mime(url: str):
# 			if url.endswith(".mp3"):
# 				return "audio/mpeg"
# 			if url.endswith(".wav"):
# 				return "audio/wav"
# 			if url.endswith(".opus"):
# 				return "audio/ogg; codecs=opus"
# 			return "application/octet-stream"
		

# 		# ---- AUDIO ----
# 		for link in extracted["audio_links"]:
# 			try:
# 				resp = await client.get(link)
# 				mime = guess_audio_mime(link)
# 				contents.append(
# 					types.Part.from_bytes(
# 						data=resp.content,
# 						mime_type=mime 
# 					)
# 				)
# 			except Exception as e:
# 				print("Audio attach failed:", e)

# 		for link in extracted["image_links"]:
# 			try:
# 				resp = await client.get(link)
# 				ext = link.lower()
# 				if ext.endswith(".png"):
# 					mime = "image/png"
# 				elif ext.endswith(".jpg") or ext.endswith(".jpeg"):
# 					mime = "image/jpeg"
# 				elif ext.endswith(".gif"):
# 					mime = "image/gif"
# 				elif ext.endswith(".webp"):
# 					mime = "image/webp"
# 				elif ext.endswith(".svg"):
# 					mime = "image/svg+xml"
# 				else:
# 					mime = "application/octet-stream"
# 				contents.append(
# 					types.Part.from_bytes(
# 						data=resp.content,
# 						mime_type=mime
# 					)
# 				)
# 			except Exception as e:
# 				print("Image attach failed:", e)

# 	def extract_json(text):
# 		try:
# 			# Extract first {...} block (non-recursive but works for flat JSON)
# 			match = re.search(r"\{[\s\S]*\}", text)
# 			if match:
# 				return json.loads(match.group(0))
# 		except Exception as e:
# 			print("JSON parsing error:", e)

# 		raise ValueError("No JSON found")
# 	client = app.state.gemini
# 	# ----------------------------------------------------
# 	# 4. Call Gemini
# 	# ----------------------------------------------------
# 	response = client.models.generate_content(
# 		model="gemini-2.5-flash",
# 		contents=contents,
# 		config=types.GenerateContentConfig(
# 			tools=[types.Tool(code_execution=types.ToolCodeExecution)]
# 		)
# 	)

# 	try:
# 		for part in response.candidates[0].content.parts:
# 			if part.text is not None:
# 				print(f"This is the llm text:\n{part.text}")
# 				data = extract_json(part.text)
# 				print(data)
# 			if part.executable_code is not None:
# 				print(f"This is the llm code:\n{part.executable_code.code}")
# 			if part.code_execution_result is not None:
# 				print(f"This is the llm output:\n{part.code_execution_result.output}")
# 				result = extract_json(part.code_execution_result.output)
# 				print(result)
# 		if result:
# 			if extracted['submit_url']:
# 				return [extracted['submit_url'],result] 
# 			else:
# 				return [app.state.submit_url,result]
# 		elif data:
# 			if extracted['submit_url']:
# 				return [extracted['submit_url'],data] 
# 			else:
# 				return [app.state.submit_url,data]
# 		else:
# 			if extracted['submit_url']:
# 				return [extracted['submit_url'],{
# 					"email": email,
# 					"secret": secret,
# 					"url": extracted["current_url"],
# 					"answer": "anything"
# 				}]
# 			else:
# 				return [
# 					app.state.prev_submit,
# 					{
# 					"email": email,
# 					"secret": secret,
# 					"url": extracted["current_url"],
# 					"answer": "anything"
# 				}
# 				]

# 	except Exception as e:
# 		print("❌ Invalid LLM response:", e)
# 		print(response)

# 		# SAME FALLBACK HERE TOO
# 		if extracted["payload_templates"]:
# 			template = extracted["payload_templates"][0]
# 			email = template.get("email", app.state.user_email)
# 			secret = template.get("secret", app.state.user_secret)
# 		else:
# 			email = app.state.user_email
# 			secret = app.state.user_secret

# 		fallback_payload = {
# 			"email": email,
# 			"secret": secret,
# 			"url": extracted["current_url"],
# 			"answer": "anything"
# 		}

# 		return fallback_payload