# AI-Powered Quiz Solver

> **Institutional Project** - Automated multi-step quiz solver using FastAPI, Playwright, and Gemini 2.5 Pro

An intelligent system that recursively solves complex, multi-step quizzes by scraping quiz pages, analyzing content with Google's Gemini AI, and automatically submitting answers until completion.

## 🎯 Overview

This project demonstrates the integration of web scraping, LLM reasoning, and automated form submission to create an autonomous quiz-solving agent. Built as an institutional project, it showcases practical applications of AI in educational technology contexts.

## ✨ Key Features

- **Intelligent Scraping** - Uses Playwright to handle JavaScript-heavy quiz interfaces
- **Multi-Modal Analysis** - Extracts and processes:
  - Page text & HTML structure
  - JSON payload templates
  - Images, PDFs, audio files, and CSVs
  - Linked pages and inline scripts
- **AI-Powered Reasoning** - Leverages Gemini 2.5 Pro to analyze questions and generate answers
- **Recursive Solving** - Automatically follows quiz chains through multiple pages
- **Robust Error Handling** - Includes fallback mechanisms for unexpected LLM responses
- **Async Architecture** - Built with FastAPI for efficient background task processing

## 🏗️ Architecture

1. **Scraping Layer** - Playwright extracts all relevant content from quiz pages
2. **Analysis Layer** - Gemini 2.5 Pro processes extracted data and reasons through questions
3. **Submission Layer** - Automated form submission using function calling responses
4. **Recursion Layer** - Follows `next_url` chains until quiz completion

## 🛠️ Tech Stack

- **Backend**: FastAPI, Uvicorn
- **Browser Automation**: Playwright (Chromium)
- **AI/LLM**: Google Gemini 2.5 Pro API
- **HTTP Client**: httpx (async)
- **Language**: Python 3.x

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- Google Gemini API key

### Installation

1. Clone the repository
```bash
git clone <your-repo-url>
cd <repo-name>
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Configure environment variables

Create a `.env` file in the project root:
```env
GEMINI_API_KEY=your_gemini_api_key_here
SECRET=your_server_secret_key
```

4. Run the server
```bash
python main.py
```

The API will be available at `http://localhost:8000`

## 📡 API Usage

### Start Quiz Solving Task

**Endpoint**: `POST /task`

**Request Body**:
```json
{
  "email": "your-email@example.com",
  "secret": "your_server_secret",
  "url": "https://quiz-start-url.com"
}
```

**Response**: Task initiated in background; solver will recursively process the entire quiz chain.

## 🔄 How It Works
```
┌─────────────────┐
│  Quiz Page URL  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Playwright Scraper             │
│  • Extract text & HTML          │
│  • Download media files         │
│  • Parse JSON templates         │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Gemini 2.5 Pro Analysis        │
│  • Process multi-modal content  │
│  • Reason through questions     │
│  • Generate answer payload      │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Submit Answer                  │
│  • POST to quiz backend         │
│  • Receive next URL (if any)    │
└────────┬────────────────────────┘
         │
         ▼
    Next page? → Repeat recursively
```

## 🔐 Security Notes

- Server secret authentication required for `/task` endpoint
- API keys stored securely in environment variables
- Never commit `.env` file to version control

## 📝 Project Context

This project was developed as part of an institutional initiative to explore AI applications in educational automation. It demonstrates practical implementation of LLM function calling, multi-modal content processing, and autonomous agent design patterns.

## ⚠️ Disclaimer

This tool is intended for educational and research purposes. Please ensure compliance with the terms of service of any quiz platforms you interact with.

## 🤝 Contributing

This is an institutional project. For questions or collaboration inquiries, please contact via the repository issues.
