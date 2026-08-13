# nayaScript — PII Redaction Tool

Upload a `.docx`, it runs through a redaction script, and you get back `redacted.docx` with names, emails, phone numbers, companies, addresses, etc. swapped for realistic fake values.

## Approach

Hybrid detector, not a single method:

- **Regex** for structured PII — emails, phone numbers, CIN, credit card, SSN, IP, DOB.
- **spaCy NER + context rules** for unstructured PII — person names, company names.
- **OCR (Tesseract)** for PII embedded in images inside the DOCX (e.g. scanned ID/PAN-style images), optional via `--no-ocr`.

Every detected value is normalized and mapped to one stable fake replacement per run (`Rahul` → `Bablu Sharma` everywhere), stored in `replacement_map.json` so the run is auditable. The original file is never overwritten — a copy is edited.

**Explicit scope call:** company names are treated as PII and redacted; order/ticket-style reference numbers are not, unless they matched a structured pattern (e.g. CIN) by design.

## Tradeoffs / known false positives & negatives

Evaluated against a real run on `Red Herring Prospectus.docx` (see the evaluation report for full numbers):

- **Structured types are solid** — email and CIN hit 100% precision and recall; regex on a fixed pattern doesn't miss or overreach.
- **Person-name NER is the weak spot** — only ~32% of flagged "person" spans were real names. spaCy regularly tags place names, scheme names, and stock legal phrases ("Selling Shareholders", "Key Managerial Personnel") as people. One boundary bug: "Bandra Kurla Complex" inside a bank's address got replaced with a fake person name, corrupting the address around it.
- **Phone regex over-matches** — ~45% of flagged "phone" values are actually folio/reference/DP-ID numbers of similar shape, not phone numbers.
- **Address recall is low** — most addresses in a large document aren't caught; only a handful of clearly-labeled ones are. Free-text addresses don't have a reliable fixed pattern.
- **OCR is inherently less reliable** than native text extraction — expect more false negatives on scanned/embedded images than on document text.

## Setup

```bash
cd redactor
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

Image/OCR redaction needs the Tesseract binary too (see `requirements.txt`). The backend runs with `--no-ocr` by default so it's not required to get started.

```bash
cd backend
npm install
npm start
```

Open `http://localhost:3000`, upload a `.docx`, and the redacted version downloads automatically.

Or run the script directly:

```bash
python redactor/pii_redactor.py "input.docx" -o "output.docx" --map replacement_map.json
```

## Deployment

- **Frontend:** deployed on Vercel — [pii-redactor-seven.vercel.app](https://pii-redactor-seven.vercel.app/)
- **Backend:** deployed on Railway — [pii-redactor-production-9a0d.up.railway.app](https://pii-redactor-production-9a0d.up.railway.app)

The frontend calls the Railway backend URL for redaction, so no local setup is needed to try it — just open the Vercel link and upload a `.docx`. Local setup below is only for development.

## How it fits together

1. Frontend posts the file to `POST /redact`.
2. `server.js` saves it to `backend/uploads/`, then shells out to `python3 redactor/pii_redactor.py <input> -o <output>`.
3. Server streams the output back as `redacted.docx` and deletes both temp files — nothing lingers in `uploads/`.

## Structure

```
nayaScript/
├── backend/
│   ├── server.js          # Express server: upload, calls python, returns file
│   ├── package.json
│   └── uploads/            # scratch space, cleared after each request
├── redactor/
│   ├── pii_redactor.py     # the redaction script
│   ├── replacement_map.json
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── script.js
│   └── style.css
└── README.md
```

## Extending to a new PII type

Add a pattern (regex) or a spaCy label mapping in `redactor/pii_redactor.py`'s detector, give it a fake-value generator, and it picks up the same stable-replacement and audit-map behavior automatically — no other file needs to change.

## Notes

- `PYTHON_BIN` env var points at a specific Python (e.g. a venv path, or `python` on Windows).
- Max upload size is 25 MB (`limits.fileSize` in `server.js`).
