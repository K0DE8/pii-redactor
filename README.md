# nayaScript

A simple tool: upload a `.docx`, it gets run through a PII redaction script, and you get back a `redacted.docx` with names, emails, phone numbers, addresses, etc. swapped for realistic fake values.

## Structure

```
nayaScript/
├── backend/
│   ├── server.js          # Express server: handles upload, calls python, returns file
│   ├── package.json
│   └── uploads/            # scratch space, files are deleted after each request
├── redactor/
│   ├── pii_redactor.py     # the redaction script
│   ├── replacement_map.json
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── script.js
│   └── style.css
├── README.md
└── .gitignore
```

## Setup

### 1. Python side

```bash
cd redactor
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

If you want image/OCR redaction (identity documents embedded as images) instead of text-only redaction, also install the Tesseract binary — see the comment at the bottom of `requirements.txt`. By default the backend runs with `--no-ocr` so you don't need Tesseract just to get started.

### 2. Node side

```bash
cd backend
npm install
```

### 3. Run it

```bash
cd backend
npm start
```

Open `http://localhost:3000` in your browser, upload a `.docx`, and the redacted version downloads automatically.

## How it fits together

1. The frontend posts the file to `POST /redact`.
2. `server.js` saves it to `backend/uploads/`, then shells out to `python3 redactor/pii_redactor.py <input> -o <output>`.
3. Once the script finishes, the server streams `<output>` back as `redacted.docx` and deletes both temp files.

## Notes / things worth knowing

- The uploaded file and the redacted output are temporary — deleted right after the response is sent. Nothing lingers in `uploads/`.
- `PYTHON_BIN` env var lets you point at a specific Python (e.g. `PYTHON_BIN=python` on Windows, or a venv path).
- Max upload size is capped at 25 MB in `server.js` — change `limits.fileSize` if you need more.
- The redactor script had a bug in `redact_image()` (undefined variables when an image *wasn't* flagged as an ID document) — that's fixed in this copy.
