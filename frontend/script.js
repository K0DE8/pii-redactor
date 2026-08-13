const form = document.getElementById('upload-form');
const fileInput = document.getElementById('file-input');
const dropzone = document.getElementById('dropzone');
const dropzoneText = document.getElementById('dropzone-text');
const submitBtn = document.getElementById('submit-btn');
const status = document.getElementById('status');

function setStatus(message, type) {
  status.textContent = message || '';
  status.className = 'status' + (type ? ' ' + type : '');
}

function setSelectedFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.docx')) {
    setStatus('Please choose a .docx file.', 'error');
    fileInput.value = '';
    submitBtn.disabled = true;
    return;
  }
  dropzoneText.textContent = file.name;
  submitBtn.disabled = false;
  setStatus('');
}

fileInput.addEventListener('change', () => setSelectedFile(fileInput.files[0]));

dropzone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropzone.classList.add('dragover');
});

dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

dropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  const file = e.dataTransfer.files[0];
  if (file) {
    fileInput.files = e.dataTransfer.files;
    setSelectedFile(file);
  }
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const file = fileInput.files[0];
  if (!file) return;

  submitBtn.disabled = true;
  setStatus('Redacting document... this can take a moment.');

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('https://pii-redactor-production-9a0d.up.railway.app/redact', {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || 'Redaction failed.');
    }

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'redacted.docx';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    setStatus('Done! Your redacted document has downloaded.', 'success');
  } catch (err) {
    setStatus(err.message, 'error');
  } finally {
    submitBtn.disabled = false;
  }
});
