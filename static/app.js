// epubkit — Frontend

const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
const fileList = document.getElementById('file-list');
const optionsPanel = document.getElementById('options-panel');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const processBtn = document.getElementById('process-btn');
const qualitySlider = document.getElementById('opt-quality');
const qualityValue = document.getElementById('quality-value');
const downloadAllBtn = document.getElementById('download-all-btn');
const filenameTemplateRow = document.getElementById('filename-template-row');
const filenameTemplate = document.getElementById('opt-filename-template');

// ==================== Engine ====================
// The Python pipeline runs in a Web Worker (Pyodide). Books never leave this device.

const engine = new Worker('static/worker.js', { type: 'module' });
const pending = {};
let nextRequestId = 0;

engine.onmessage = (event) => {
    const { id, result, error, progress } = event.data;
    const req = pending[id];
    if (!req) return;
    if (progress) {
        if (req.onProgress) req.onProgress(progress);
        return;
    }
    delete pending[id];
    if (error) req.reject(new Error(error));
    else req.resolve(result);
};

function callEngine(type, payload = {}, onProgress = null) {
    return new Promise((resolve, reject) => {
        const id = ++nextRequestId;
        pending[id] = { resolve, reject, onProgress };
        engine.postMessage({ id, type, payload });
    });
}

// Start loading Python while the reader picks files.
const engineReady = callEngine('init');

function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
}

let uploadedFiles = []; // {task_id, filename, metadata, file_size}
let selectedDevice = 'x4'; // 'x4' (480x800) or 'x3' (528x792), both 4-level gray
let selectedFilenameFormat = 'author-title';

// ==================== Upload ====================

uploadZone.addEventListener('click', () => fileInput.click());

uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('dragover');
});

uploadZone.addEventListener('dragleave', () => {
    uploadZone.classList.remove('dragover');
});

uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    handleFiles(e.dataTransfer.files);
});

fileInput.addEventListener('change', () => {
    handleFiles(fileInput.files);
    fileInput.value = '';
});

async function handleFiles(files) {
    const epubFiles = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.epub'));
    if (epubFiles.length === 0) return;

    // Show uploading state
    const uploadContent = uploadZone.querySelector('.upload-content');
    if (uploadContent) {
        uploadContent.innerHTML = `
            <div class="upload-spinner"></div>
            <p class="upload-label">Reading${epubFiles.length > 1 ? ` ${epubFiles.length} files` : ''}...</p>
            <p class="upload-hint">First visit loads the optimiser (about 15 MB), then it is cached</p>
        `;
    }

    try {
        await engineReady;
        const data = { files: [] };
        for (const f of epubFiles) {
            data.files.push(await callEngine('inspect', { file: f }));
        }

        data.files.forEach(file => {
            if (file.task_id) {
                uploadedFiles.push(file);
            }
        });

        renderFileList(data.files);
        optionsPanel.hidden = uploadedFiles.length === 0;
    } catch (err) {
        uploadZone.innerHTML = `<div class="upload-content"><p class="upload-label" style="color:var(--error)">Could not read the file: ${escapeHtml(err.message)}</p></div>`;
    }

    // Reset upload zone
    setTimeout(() => {
        resetUploadZone();
    }, 400);
}

function resetUploadZone() {
    uploadZone.innerHTML = `
        <div class="upload-content">
            <svg class="upload-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="17 8 12 3 7 8"/>
                <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
            <p class="upload-label">${uploadedFiles.length > 0 ? 'Drop more EPUB files' : 'Drop EPUB files here'}</p>
            <p class="upload-hint">or click to browse &bull; up to 100 MB each</p>
        </div>`;
}

function renderFileList(files) {
    fileList.hidden = false;

    files.forEach(file => {
        const card = document.createElement('div');
        card.className = `file-card ${file.error ? 'error' : ''}`;
        card.dataset.taskId = file.task_id || '';

        const meta = file.metadata || {};
        const coverHtml = meta.cover_data
            ? `<img src="data:image/jpeg;base64,${meta.cover_data}" alt="Cover">`
            : '<div class="no-cover">No cover</div>';

        const errorHtml = file.error
            ? `<div class="file-error">${file.error}</div>`
            : '';

        const editHtml = file.task_id && !file.error ? `
            <div class="file-edit">
                <input type="text" placeholder="Title" value="${escapeHtml(meta.title || '')}" data-field="title" data-task="${file.task_id}">
                <input type="text" placeholder="Author" value="${escapeHtml(meta.author || '')}" data-field="author" data-task="${file.task_id}">
            </div>` : '';

        const sizeStr = file.file_size ? formatBytes(file.file_size) : '';
        const metaLine = [meta.author, meta.series].filter(Boolean).join(' \u2014 ');

        card.innerHTML = `
            <div class="file-cover">${coverHtml}</div>
            <div class="file-info">
                <div class="file-name">${escapeHtml(meta.title || file.filename)}</div>
                <div class="file-meta">${escapeHtml(metaLine)}${sizeStr ? (metaLine ? ' \u00b7 ' : '') + sizeStr : ''}</div>
                ${errorHtml}
                ${editHtml}
            </div>
            ${file.task_id ? '<button class="file-remove" onclick="removeFile(\'' + file.task_id + '\', this)" title="Remove">&times;</button>' : ''}
        `;

        fileList.appendChild(card);
    });
}

function removeFile(taskId, btn) {
    callEngine('remove', { task_id: taskId });
    uploadedFiles = uploadedFiles.filter(f => f.task_id !== taskId);
    const card = btn.closest('.file-card');
    card.style.opacity = '0';
    card.style.transform = 'translateX(20px)';
    card.style.transition = 'all 0.2s ease';
    setTimeout(() => {
        card.remove();
        if (uploadedFiles.length === 0) {
            optionsPanel.hidden = true;
            fileList.hidden = true;
        }
    }, 200);
}

// ==================== Options ====================

document.querySelectorAll('.filename-format-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.filename-format-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        selectedFilenameFormat = btn.dataset.filenameFormat;
        filenameTemplateRow.hidden = selectedFilenameFormat !== 'custom';
        if (selectedFilenameFormat === 'custom') filenameTemplate.focus();
    });
});

// Device toggle
document.querySelectorAll('.device-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.device-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        selectedDevice = btn.dataset.device;
    });
});

// Preset profiles
document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        const preset = btn.dataset.preset;
        if (preset === 'quick') {
            setOptions({ grayscale: true, contrast: true, fonts: false, css: false, cover: false, metadata: false, textcleanup: true, lightnovel: false, quality: 70 });
        } else if (preset === 'full') {
            setOptions({ grayscale: true, contrast: true, fonts: true, css: true, cover: true, metadata: true, textcleanup: true, lightnovel: false, quality: 70 });
        }
        // 'custom' doesn't change anything - user picks
    });
});

function setOptions(opts) {
    document.getElementById('opt-grayscale').checked = opts.grayscale;
    document.getElementById('opt-contrast').checked = opts.contrast;
    document.getElementById('opt-fonts').checked = opts.fonts;
    document.getElementById('opt-css').checked = opts.css;
    document.getElementById('opt-cover').checked = opts.cover;
    document.getElementById('opt-metadata').checked = opts.metadata;
    document.getElementById('opt-textcleanup').checked = opts.textcleanup;
    document.getElementById('opt-lightnovel').checked = opts.lightnovel;
    setQuality(opts.quality);
}

// Quality slider
qualitySlider.addEventListener('input', () => {
    qualityValue.textContent = qualitySlider.value + '%';
    document.querySelectorAll('.quality-btn').forEach(b => b.classList.remove('active'));
    const matching = document.querySelector(`.quality-btn[data-quality="${qualitySlider.value}"]`);
    if (matching) matching.classList.add('active');
});

document.querySelectorAll('.quality-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        setQuality(parseInt(btn.dataset.quality));
    });
});

function setQuality(val) {
    qualitySlider.value = val;
    qualityValue.textContent = val + '%';
    document.querySelectorAll('.quality-btn').forEach(b => b.classList.remove('active'));
    const matching = document.querySelector(`.quality-btn[data-quality="${val}"]`);
    if (matching) matching.classList.add('active');
}

// When any option changes, switch to Custom preset
document.querySelectorAll('.option input, #opt-quality').forEach(input => {
    input.addEventListener('change', () => {
        document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
        document.querySelector('.preset-btn[data-preset="custom"]').classList.add('active');
    });
});

// ==================== Processing ====================

processBtn.addEventListener('click', startProcessing);

async function startProcessing() {
    const validFiles = uploadedFiles.filter(f => f.task_id && !f.error);
    if (validFiles.length === 0) return;
    if (!validateFilenameTemplate()) return;

    processBtn.disabled = true;
    processBtn.innerHTML = `
        <svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
            <path d="M21 12a9 9 0 11-6.219-8.56"/>
        </svg>
        Processing...`;
    progressSection.hidden = false;
    resultsSection.hidden = true;

    const options = getOptions();
    const completedIds = [];

    // Create progress items
    const progressItems = document.getElementById('progress-items');
    progressItems.innerHTML = '';

    for (const file of validFiles) {
        const item = document.createElement('div');
        item.className = 'progress-item';
        item.id = `progress-${file.task_id}`;
        item.innerHTML = `
            <div class="filename">${escapeHtml(file.filename)}</div>
            <div class="progress-bar-container">
                <div class="progress-bar" id="bar-${file.task_id}"></div>
            </div>
            <div class="progress-message" id="msg-${file.task_id}">Waiting...</div>
        `;
        progressItems.appendChild(item);
    }

    // Process files sequentially
    for (const file of validFiles) {
        const titleInput = document.querySelector(`input[data-task="${file.task_id}"][data-field="title"]`);
        const authorInput = document.querySelector(`input[data-task="${file.task_id}"][data-field="author"]`);
        const editTitle = titleInput ? titleInput.value : '';
        const editAuthor = authorInput ? authorInput.value : '';

        try {
            const report = await processFile(file.task_id, file.filename, options, editTitle, editAuthor);
            completedIds.push({ task_id: file.task_id, report });
        } catch (err) {
            completedIds.push({ task_id: file.task_id, report: { success: false, error: err.message } });
        }
    }

    showResults(completedIds);

    processBtn.disabled = false;
    processBtn.innerHTML = `
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="18" height="18">
            <polyline points="16 16 12 12 8 16"/>
            <line x1="12" y1="12" x2="12" y2="21"/>
            <path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/>
        </svg>
        Optimize EPUBs`;
}

function validateFilenameTemplate() {
    filenameTemplate.setCustomValidity('');
    if (selectedFilenameFormat !== 'custom') return true;

    if (!filenameTemplate.value.trim()) {
        filenameTemplate.setCustomValidity('Enter a custom filename template.');
    } else {
        const remainder = filenameTemplate.value
            .replace(/\{\{|\}\}/g, '')
            .replace(/\{(?:title|author|year|series|series_index|language|original)\}/g, '');
        if (/[{}]/.test(remainder)) {
            filenameTemplate.setCustomValidity(
                'Use only the placeholders listed below the template.'
            );
        }
    }

    if (!filenameTemplate.checkValidity()) {
        filenameTemplate.reportValidity();
        filenameTemplate.focus();
        return false;
    }
    return true;
}

function getOptions() {
    return {
        device: selectedDevice,
        grayscale: document.getElementById('opt-grayscale').checked,
        contrast: document.getElementById('opt-contrast').checked,
        quality: parseInt(qualitySlider.value),
        remove_fonts: document.getElementById('opt-fonts').checked,
        remove_css: document.getElementById('opt-css').checked,
        light_novel: document.getElementById('opt-lightnovel').checked,
        generate_cover: document.getElementById('opt-cover').checked,
        clean_metadata: document.getElementById('opt-metadata').checked,
        text_cleanup: document.getElementById('opt-textcleanup').checked,
        filename_format: selectedFilenameFormat,
        filename_template: filenameTemplate.value,
    };
}

async function processFile(taskId, filename, options, editTitle, editAuthor) {
    const bar = document.getElementById(`bar-${taskId}`);
    const msg = document.getElementById(`msg-${taskId}`);
    const params = { ...options, edit_title: editTitle, edit_author: editAuthor };

    const onProgress = ({ percent, message }) => {
        if (bar) bar.style.width = `${percent}%`;
        if (msg) msg.textContent = message;
    };

    try {
        const report = await callEngine('process', { task_id: taskId, filename, params }, onProgress);
        if (bar) {
            bar.style.width = '100%';
            bar.classList.add(report.success ? 'complete' : 'error');
        }
        if (msg) msg.textContent = report.success ? 'Complete' : `Error: ${report.error}`;
        return report;
    } catch (err) {
        if (bar) bar.classList.add('error');
        if (msg) msg.textContent = `Error: ${err.message}`;
        throw err;
    }
}

// ==================== Results ====================

function showResults(completed) {
    resultsSection.hidden = false;
    const resultsItems = document.getElementById('results-items');
    resultsItems.innerHTML = '';

    const successIds = [];

    completed.forEach(({ task_id, report }) => {
        const card = document.createElement('div');
        card.className = `result-card ${report.success ? 'success' : 'error'}`;

        if (report.success) {
            successIds.push(task_id);
            const reduction = report.original_size > 0
                ? ((1 - report.optimized_size / report.original_size) * 100).toFixed(1)
                : 0;

            card.innerHTML = `
                <div class="result-header">
                    <span class="filename">${escapeHtml(report.output_filename || 'optimized.epub')}</span>
                </div>
                <div class="result-size">
                    <span class="size-original">${formatBytes(report.original_size)}</span>
                    <span class="size-arrow">&rarr;</span>
                    <span class="size-new">${formatBytes(report.optimized_size)}</span>
                    <span class="size-reduction">${reduction >= 0 ? '&minus;' + reduction : '+' + Math.abs(reduction).toFixed(1)}%</span>
                </div>
                <div class="result-summary">${escapeHtml(report.summary)}</div>
                <a href="#" class="download-btn" data-task="${task_id}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                        <polyline points="7 10 12 15 17 10"/>
                        <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                    Download
                </a>
            `;
        } else {
            card.innerHTML = `
                <div class="result-header">
                    <span class="filename">Error</span>
                </div>
                <div class="file-error">${escapeHtml(report.error)}</div>
            `;
        }

        const link = card.querySelector('.download-btn');
        if (link) {
            link.addEventListener('click', async (e) => {
                e.preventDefault();
                const { blob, filename } = await callEngine('download', { task_id });
                saveBlob(blob, filename);
            });
        }

        resultsItems.appendChild(card);
    });

    // Show Download All button for batch
    if (successIds.length > 1) {
        downloadAllBtn.hidden = false;
        downloadAllBtn.onclick = async () => {
            const { blob, filename } = await callEngine('downloadAll', { task_ids: successIds });
            saveBlob(blob, filename);
        };
    } else {
        downloadAllBtn.hidden = true;
    }

    // Scroll results into view
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ==================== Utilities ====================

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Spinning animation for processing button
const style = document.createElement('style');
style.textContent = `
    @keyframes spin { to { transform: rotate(360deg); } }
    .spin { animation: spin 1s linear infinite; }
    .upload-spinner {
        width: 28px; height: 28px;
        border: 3px solid var(--border);
        border-top-color: var(--accent);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
        margin: 0 auto 12px;
    }
`;
document.head.appendChild(style);
