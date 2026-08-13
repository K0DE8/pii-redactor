const express = require('express');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { execFile } = require('child_process');
const cors = require('cors');
const app = express();
app.use(cors());
const PORT = process.env.PORT || 3000;

const UPLOAD_DIR = path.join(__dirname, 'uploads');
const REDACTOR_SCRIPT = path.join(__dirname, '..', 'redactor', 'pii_redactor.py');
const PYTHON_BIN = process.env.PYTHON_BIN || 'python';

if (!fs.existsSync(UPLOAD_DIR)) fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const upload = multer({
  dest: UPLOAD_DIR,
  limits: { fileSize: 25 * 1024 * 1024 }, // 25 MB cap
  fileFilter: (req, file, cb) => {
    const ok = path.extname(file.originalname).toLowerCase() === '.docx';
    cb(ok ? null : new Error('Only .docx files are supported'), ok);
  },
});

// Serve the frontend
app.use(express.static(path.join(__dirname, '..', 'frontend')));

app.post('/redact', (req, res) => {
  upload.single('file')(req, res, (uploadErr) => {
    if (uploadErr) {
      return res.status(400).json({ error: uploadErr.message });
    }
    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded' });
    }

    const jobId = crypto.randomBytes(8).toString('hex');
    const inputPath = path.join(UPLOAD_DIR, `${jobId}_input.docx`);
    const outputPath = path.join(UPLOAD_DIR, `${jobId}_redacted.docx`);

    // multer saves without an extension; rename so the python script accepts it
    fs.renameSync(req.file.path, inputPath);

    const cleanup = () => {
      fs.unlink(inputPath, () => { });
      fs.unlink(outputPath, () => { });
    };

    execFile(
      PYTHON_BIN,
      [REDACTOR_SCRIPT, inputPath, '-o', outputPath],
      { timeout: 120000, maxBuffer: 10 * 1024 * 1024 },
      (err, stdout, stderr) => {
        if (err) {
          console.error('Redaction failed:', stderr || err.message);
          cleanup();
          return res.status(500).json({ error: 'Redaction failed', details: stderr || err.message });
        }

        res.download(outputPath, 'redacted.docx', (dlErr) => {
          if (dlErr) console.error('Download error:', dlErr);
          cleanup();
        });
      }
    );
  });
});

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.listen(PORT, () => {
  console.log(`nayaScript backend running on http://localhost:${PORT}`);
});
