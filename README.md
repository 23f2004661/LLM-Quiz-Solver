Hello,
🔁 Automated Recursive Quiz Solver

FastAPI + Playwright + Gemini 2.5 Pro

This project automatically solves multi-step quizzes by scraping each quiz page, sending the extracted data to Gemini for reasoning, and recursively submitting answers until the quiz sequence ends.

🚀 Features

Loads pages using Playwright (supports JavaScript-heavy quizzes)

Extracts:

Page text & HTML

JSON payload templates

Images, PDFs, audio, CSVs

Linked pages & inline scripts

Sends all extracted data to Gemini 2.5 Pro

Gemini returns a function call with solution payload

App submits answers and follows the "next_url" chain

Includes a safe fallback if LLM doesn’t respond correctly

Runs in background via FastAPI /task endpoint

🛠️ Tech Stack

FastAPI

Playwright (Chromium)

Gemini API (Google GenAI)

httpx (async HTTP client)

Uvicorn

▶️ Running the Server
pip install -r requirements.txt
python main.py


Set environment variables in .env:

GEMINI_API_KEY=your_key
SECRET=your_server_secret

🧩 Using /task

Send:

{
  "email": "your-email@example.com",
  "secret": "server_secret",
  "url": "https://quiz-start-url.com"
}


This triggers the full recursive solving chain.

🔍 How It Works (Short)

Scrape quiz page → text, HTML, files, JSON templates

Build prompt + attachments

Gemini returns submit_answer() function call

App POSTs answer to quiz backend

If backend returns "url", solver continues recursively.
