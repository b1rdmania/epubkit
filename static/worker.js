// epubkit — Web Worker that runs the Python pipeline in Pyodide.
// Books are processed in this tab. Nothing is uploaded.

// Keep this version in step with the import below.
const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/';

import { loadPyodide } from 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';

let pyodide = null;
let api = null;
let nextId = 0;
const outputs = {}; // task_id -> {path, filename}

const ready = (async () => {
    pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
    await pyodide.loadPackage(['lxml', 'pillow', 'more-itertools', 'micropip']);
    const micropip = pyodide.pyimport('micropip');
    await micropip.install(new URL('wheels/cssutils-2.11.1-py3-none-any.whl', self.location).href, { deps: false });

    const manifest = await (await fetch('../py/manifest.json')).json();
    pyodide.FS.mkdirTree('/app');
    pyodide.FS.mkdirTree('/work');
    await Promise.all(manifest.map(async name => {
        const res = await fetch('../py/' + name);
        if (!res.ok) throw new Error(`Could not load ${name}`);
        pyodide.FS.writeFile('/app/' + name, new Uint8Array(await res.arrayBuffer()));
    }));
    pyodide.runPython("import sys; sys.path.insert(0, '/app')");
    api = pyodide.pyimport('web_api');
})();

function toJs(proxy) {
    const value = proxy.toJs({ dict_converter: Object.fromEntries });
    proxy.destroy();
    return value;
}

const handlers = {
    async init() {
        await ready;
        return true;
    },

    async inspect({ file }) {
        await ready;
        const taskId = String(++nextId);
        const dir = `/work/${taskId}`;
        pyodide.FS.mkdirTree(dir);
        const path = `${dir}/input.epub`;
        pyodide.FS.writeFile(path, new Uint8Array(await file.arrayBuffer()));
        const result = toJs(api.inspect_upload(path, file.name, file.size));
        result.task_id = result.error ? null : taskId;
        if (result.error) pyodide.FS.unlink(path);
        return result;
    },

    async process({ task_id, filename, params }, post) {
        await ready;
        const dir = `/work/${task_id}`;
        const output = `${dir}/output.epub`;
        const onProgress = (percent, message) => post({ progress: { percent, message } });
        const pyParams = pyodide.toPy(params);
        const report = toJs(api.run_process(`${dir}/input.epub`, output, filename, pyParams, onProgress));
        pyParams.destroy();
        if (report.success) {
            outputs[task_id] = { path: output, filename: report.output_filename || 'optimized.epub' };
        }
        return report;
    },

    async download({ task_id }) {
        const out = outputs[task_id];
        if (!out) throw new Error('Processing not complete');
        const bytes = pyodide.FS.readFile(out.path);
        return { filename: out.filename, blob: new Blob([bytes], { type: 'application/epub+zip' }) };
    },

    async downloadAll({ task_ids }) {
        const entries = task_ids.filter(id => outputs[id]).map(id => [outputs[id].path, outputs[id].filename]);
        const zipPath = `/work/epubkit_optimized_${Date.now()}.zip`;
        const pyEntries = pyodide.toPy(entries);
        api.build_zip(pyEntries, zipPath);
        pyEntries.destroy();
        const bytes = pyodide.FS.readFile(zipPath);
        pyodide.FS.unlink(zipPath);
        return { filename: 'epubkit_optimized_epubs.zip', blob: new Blob([bytes], { type: 'application/zip' }) };
    },

    async remove({ task_id }) {
        delete outputs[task_id];
        const dir = `/work/${task_id}`;
        for (const name of ['input.epub', 'output.epub']) {
            try { pyodide.FS.unlink(`${dir}/${name}`); } catch (e) { /* not there */ }
        }
        return true;
    },
};

self.onmessage = async (event) => {
    const { id, type, payload } = event.data;
    const post = (extra) => self.postMessage({ id, ...extra });
    try {
        const result = await handlers[type](payload, post);
        post({ result });
    } catch (err) {
        post({ error: err.message || String(err) });
    }
};
