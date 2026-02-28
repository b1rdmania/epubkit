// X4 EPUB Optimizer - Frontend

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

let uploadedFiles = []; // {task_id, filename, metadata, file_size}

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

    const formData = new FormData();
    epubFiles.forEach(f => formData.append('files', f));

    uploadZone.innerHTML = '<p>Uploading...</p>';

    try {
        const response = await fetch('/upload', { method: 'POST', body: formData });
        const data = await response.json();

        data.files.forEach(file => {
            if (file.task_id) {
                uploadedFiles.push(file);
            }
        });

        renderFileList(data.files);
        optionsPanel.hidden = uploadedFiles.length === 0;
    } catch (err) {
        uploadZone.innerHTML = `<p style="color:#e74c3c">Upload failed: ${err.message}</p>`;
    }

    // Reset upload zone
    setTimeout(() => {
        uploadZone.innerHTML = `
            <div class="upload-content">
                <svg class="upload-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="17 8 12 3 7 8"/>
                    <line x1="12" y1="3" x2="12" y2="15"/>
                </svg>
                <p>Drag &amp; drop more EPUB files</p>
                <p class="upload-hint">or click to browse</p>
            </div>`;
    }, 500);
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
        const metaLine = [meta.author, meta.series].filter(Boolean).join(' - ');

        card.innerHTML = `
            <div class="file-cover">${coverHtml}</div>
            <div class="file-info">
                <div class="file-name">${escapeHtml(meta.title || file.filename)}</div>
                <div class="file-meta">${escapeHtml(metaLine)} ${sizeStr ? '(' + sizeStr + ')' : ''}</div>
                ${errorHtml}
                ${editHtml}
            </div>
            ${file.task_id ? '<button class="file-remove" onclick="removeFile(\'' + file.task_id + '\', this)">&times;</button>' : ''}
        `;

        fileList.appendChild(card);
    });
}

function removeFile(taskId, btn) {
    uploadedFiles = uploadedFiles.filter(f => f.task_id !== taskId);
    btn.closest('.file-card').remove();
    if (uploadedFiles.length === 0) {
        optionsPanel.hidden = true;
        fileList.hidden = true;
    }
}

// ==================== Options ====================

// Preset profiles
document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        const preset = btn.dataset.preset;
        if (preset === 'quick') {
            setOptions({ grayscale: true, contrast: true, fonts: false, css: false, cover: false, metadata: false, lightnovel: false, quality: 70 });
        } else if (preset === 'full') {
            setOptions({ grayscale: true, contrast: true, fonts: true, css: true, cover: true, metadata: true, lightnovel: false, quality: 70 });
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
    document.getElementById('opt-lightnovel').checked = opts.lightnovel;
    setQuality(opts.quality);
}

// Quality slider
qualitySlider.addEventListener('input', () => {
    qualityValue.textContent = qualitySlider.value + '%';
    // Update quality preset buttons
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

    processBtn.disabled = true;
    processBtn.textContent = 'Processing...';
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
        // Get metadata edits
        const titleInput = document.querySelector(`input[data-task="${file.task_id}"][data-field="title"]`);
        const authorInput = document.querySelector(`input[data-task="${file.task_id}"][data-field="author"]`);
        const editTitle = titleInput ? titleInput.value : '';
        const editAuthor = authorInput ? authorInput.value : '';

        try {
            const report = await processFile(file.task_id, options, editTitle, editAuthor);
            completedIds.push({ task_id: file.task_id, report });
        } catch (err) {
            completedIds.push({ task_id: file.task_id, report: { success: false, error: err.message } });
        }
    }

    // Show results
    showResults(completedIds);

    processBtn.disabled = false;
    processBtn.textContent = 'Optimize EPUBs';
}

function getOptions() {
    return {
        grayscale: document.getElementById('opt-grayscale').checked,
        contrast: document.getElementById('opt-contrast').checked,
        quality: parseInt(qualitySlider.value),
        remove_fonts: document.getElementById('opt-fonts').checked,
        remove_css: document.getElementById('opt-css').checked,
        light_novel: document.getElementById('opt-lightnovel').checked,
        generate_cover: document.getElementById('opt-cover').checked,
        clean_metadata: document.getElementById('opt-metadata').checked,
    };
}

function processFile(taskId, options, editTitle, editAuthor) {
    return new Promise((resolve, reject) => {
        const params = new URLSearchParams({
            grayscale: options.grayscale,
            contrast: options.contrast,
            quality: options.quality,
            remove_fonts: options.remove_fonts,
            remove_css: options.remove_css,
            light_novel: options.light_novel,
            generate_cover: options.generate_cover,
            clean_metadata: options.clean_metadata,
            edit_title: editTitle,
            edit_author: editAuthor,
        });

        const eventSource = new EventSource(`/process/${taskId}?${params}`);
        const bar = document.getElementById(`bar-${taskId}`);
        const msg = document.getElementById(`msg-${taskId}`);

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (bar) bar.style.width = `${data.percent}%`;
            if (msg) msg.textContent = data.message;

            if (data.status === 'done' || data.status === 'error') {
                eventSource.close();
                if (bar) bar.classList.add(data.status === 'done' ? 'complete' : 'error');
                resolve(data.report || data);
            }
        };

        eventSource.onerror = () => {
            eventSource.close();
            if (bar) bar.classList.add('error');
            if (msg) msg.textContent = 'Connection error';
            reject(new Error('SSE connection failed'));
        };
    });
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
                    <span class="size-reduction">-${reduction}%</span>
                </div>
                <div class="result-summary">${escapeHtml(report.summary)}</div>
                <a href="/download/${task_id}" class="download-btn" download>Download</a>
            `;
        } else {
            card.innerHTML = `
                <div class="result-header">
                    <span class="filename">Error</span>
                </div>
                <div class="file-error">${escapeHtml(report.error)}</div>
            `;
        }

        resultsItems.appendChild(card);
    });

    // Show Download All button for batch
    if (successIds.length > 1) {
        downloadAllBtn.hidden = false;
        downloadAllBtn.onclick = () => {
            window.location.href = `/download-all?task_ids=${successIds.join(',')}`;
        };
    } else {
        downloadAllBtn.hidden = true;
    }
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
