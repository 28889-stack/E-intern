
(function () {
    // Mobile browsers get unstable with parallel workers, keep it to 1. On desktop, limit to hardwareConcurrency - 1 to keep system responsive.
    const isMobile = /Android|webOS|iPhone|iPad|iPod/i.test(navigator.userAgent) || window.innerWidth <= 768;
    const MAX_WORKERS = isMobile ? 1 : (navigator.hardwareConcurrency ? Math.max(1, Math.min(8, navigator.hardwareConcurrency - 1)) : 4);
    let workerPool = [];
    let poolCreationPromises = 0;
    // Tesseract workers leak memory on long runs. Restarting them every few pages mitigates this.
    const RESTART_THRESHOLD = 8;

    const queue = [];
    let isProcessing = false;
    let totalTasks = 0;
    let completedTasks = 0;
    let activeTasksProgress = new Map();
    let taskIdCounter = 0;

    const taskDurations = [];
    const taskStartTimes = new Map();

    async function terminateWorker(w) {
        if (w && w.worker) {
            console.log('Terminating OCR worker to free memory...');
            const tWorker = w.worker;
            setTimeout(() => { try { tWorker.terminate(); } catch (e) { } }, 1000);
        }
    }

    async function terminateAllWorkers() {
        for (const w of workerPool) {
            terminateWorker(w);
        }
        workerPool = [];
    }

    async function loadScriptOnce(src) {
        return new Promise((resolve, reject) => {
            if (document.querySelector(`script[data-src="${src}"]`)) return resolve();
            const s = document.createElement('script');
            s.src = src;
            s.async = true;
            s.dataset.src = src;
            s.onload = () => resolve();
            s.onerror = () => reject(new Error('Failed to load ' + src));
            document.head.appendChild(s);
        });
    }

    async function loadTesseract() {
        if (window.Tesseract) return;

        if (window.location.protocol === 'file:') {
            console.info('[OCR] Running on file:// protocol. Using CDN for Tesseract.js.');
            await loadScriptOnce('https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js');
            return;
        }

        try {
            await loadScriptOnce('js/tesseract.min.js');
        } catch (e) {
            console.warn('[OCR] Local tesseract.min.js not found. Falling back to CDN...');
            await loadScriptOnce('https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js');
        }
    }

    async function createFallbackWorker(lang, oem, loggerFn) {
        const options = {
            logger: loggerFn
        };

        if (window.__TESS_WORKER_URI) {
            options.workerPath = window.__TESS_WORKER_URI;
        }
        if (window.__TESS_CORE_URI) {
            options.corePath = window.__TESS_CORE_URI;
        }

        // Tesseract.js 5+ handles CDN fallbacks internally if langPath is omitted.
        // We only use langPath if a local models directory is explicitly expected.
        return await window.Tesseract.createWorker(lang, oem, options);
    }

    async function getIdleWorker(lang) {
        let w = workerPool.find(w => !w.isBusy && w.lang === lang);
        if (w) {
            if (w.pagesProcessed >= RESTART_THRESHOLD) {
                terminateWorker(w);
                workerPool = workerPool.filter(x => x !== w);
            } else {
                return w;
            }
        }

        if (workerPool.length + poolCreationPromises < MAX_WORKERS) {
            poolCreationPromises++;
            try {
                await loadTesseract();

                // Equation engine model requires legacy engine (OEM 0) instead of LSTM.
                const oem = lang === 'equ' ? 0 : 1;

                const worker = await createFallbackWorker(lang, oem, (m) => {
                    if (m.status === 'recognizing text') {
                        const poolEntry = workerPool.find(x => x.worker === worker);
                        if (poolEntry && poolEntry.activeTaskId) {
                            activeTasksProgress.set(poolEntry.activeTaskId, m.progress);
                            updateProgressUI();
                        }
                    }
                });
                const poolEntry = { worker, lang, pagesProcessed: 0, isBusy: false, activeTaskId: null };
                workerPool.push(poolEntry);
                return poolEntry;
            } finally {
                poolCreationPromises--;
            }
        }
        return null;
    }

    function updateQueueUI() {
        let container = document.getElementById('ocr-queue-status');
        if (!container) {
            container = document.createElement('div');
            container.id = 'ocr-queue-status';
            container.className = 'fixed bottom-20 left-1/2 -translate-x-1/2 z-[100] px-4 py-3 rounded-2xl shadow-2xl flex flex-col gap-2 min-w-[280px] section-fade-in';
            container.style.cssText = 'background:var(--bg-card);border:1px solid var(--border-hi);backdrop-filter:blur(12px)';
            document.body.appendChild(container);
        }

        const remaining = queue.length + workerPool.filter(w => w.isBusy).length;
        if (remaining === 0 && !isProcessing) {
            container.classList.add('opacity-0', 'pointer-events-none', 'translate-y-4');
            setTimeout(() => { if (queue.length === 0 && !isProcessing) container.remove(); }, 500);
            return;
        }

        container.classList.remove('opacity-0', 'pointer-events-none', 'translate-y-4');

        const progress = totalTasks > 0 ? (completedTasks / totalTasks) * 100 : 0;

        let etaText = 'Calculating ETA...';
        if (taskDurations.length > 0) {
            const avgDuration = taskDurations.reduce((a, b) => a + b, 0) / taskDurations.length;
            const activeWorkersCount = Math.max(1, workerPool.filter(w => w.isBusy).length);
            const remainingMs = (remaining * avgDuration) / activeWorkersCount;
            const remainingSecs = Math.ceil(remainingMs / 1000);
            
            if (remainingSecs < 60) {
                etaText = `Est. ${remainingSecs}s remaining`;
            } else {
                const m = Math.floor(remainingSecs / 60);
                const s = remainingSecs % 60;
                etaText = `Est. ${m}m ${s}s remaining`;
            }
        }

        container.innerHTML = `
            <div class="flex items-center justify-between gap-4">
                <div class="flex items-center gap-2">
                    <div class="spinner-container !w-4 !h-4">
                        <svg class="spinner-svg" viewBox="0 0 50 50"><circle cx="25" cy="25" r="20" fill="none" stroke-width="6"></circle></svg>
                    </div>
                    <span class="text-[11px] font-bold uppercase tracking-wider" style="color:var(--text-1)">Background OCR</span>
                </div>
                <span class="text-[10px] font-mono" style="color:var(--accent)">${completedTasks}/${totalTasks}</span>
            </div>
            <div class="h-1.5 w-full rounded-full overflow-hidden" style="background:var(--bg-input)">
                <div id="ocr-queue-progress-bar" class="h-full transition-all duration-300" style="width:0%;background:var(--accent)"></div>
            </div>
            <div class="flex justify-between items-center mt-1">
                <p class="text-[10px]" style="color:var(--text-3)">Processing textless pages...</p>
                <p class="text-[10px] font-medium" style="color:var(--accent)">${etaText}</p>
            </div>
        `;

        updateProgressUI();
    }

    function updateProgressUI() {
        const bar = document.getElementById('ocr-queue-progress-bar');
        if (!bar || totalTasks === 0) return;

        let activeProgressSum = 0;
        for (const p of activeTasksProgress.values()) {
            activeProgressSum += p;
        }

        const totalProgress = ((completedTasks + activeProgressSum) / totalTasks) * 100;
        bar.style.width = `${totalProgress}%`;
    }

    async function preprocessImagePayload(payload) {
        try {
            let canvas;
            if (payload instanceof HTMLCanvasElement) {
                canvas = document.createElement('canvas');
                canvas.width = payload.width;
                canvas.height = payload.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(payload, 0, 0);
            } else {
                await new Promise((resolve, reject) => {
                    const img = new Image();
                    img.crossOrigin = "Anonymous";
                    img.onload = () => {
                        canvas = document.createElement('canvas');
                        canvas.width = img.width;
                        canvas.height = img.height;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0);
                        resolve();
                    };
                    img.onerror = reject;
                    if (payload instanceof Blob || payload instanceof File) {
                        img.src = URL.createObjectURL(payload);
                    } else if (typeof payload === 'string') {
                        img.src = payload;
                    } else {
                        reject(new Error('Unsupported type'));
                    }
                });
            }

            if (!canvas) return payload;

            const ctx = canvas.getContext('2d');
            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const data = imageData.data;
            const contrast = 1.5;
            const threshold = 128;

            for (let i = 0; i < data.length; i += 4) {
                const r = data[i];
                const g = data[i + 1];
                const b = data[i + 2];
                let gray = r * 0.299 + g * 0.587 + b * 0.114;
                gray = (gray - 128) * contrast + 128;
                const val = gray > threshold ? 255 : 0;
                data[i] = data[i + 1] = data[i + 2] = val;
            }
            ctx.putImageData(imageData, 0, 0);
            return canvas;
        } catch (e) {
            console.warn('[OCR] Preprocessing failed, using original payload', e);
            return payload;
        }
    }

    let isPumping = false;
    async function pumpQueue() {
        if (isPumping || queue.length === 0) {
            if (queue.length === 0 && !workerPool.some(w => w.isBusy)) {
                isProcessing = false;
                updateQueueUI();
                await terminateAllWorkers();
            }
            return;
        }

        isPumping = true;
        try {
            while (queue.length > 0) {
                const firstTask = queue[0];

                if (firstTask.lang === 'auto' || !firstTask.lang) {
                    firstTask.lang = 'detecting...';
                    try {
                        firstTask.resolvedLang = await detectLanguage(firstTask.imagePayload);
                    } catch (e) {
                        console.warn('[OCR] OSD Detection failed or decided to skip. Falling back to eng.', e);
                        firstTask.resolvedLang = 'eng';
                    }
                    firstTask.lang = firstTask.resolvedLang;
                }

                if (firstTask.lang === 'detecting...') break;

                const w = await getIdleWorker(firstTask.lang);
                if (!w) break; // No workers available right now

                const task = queue.shift();
                if (!task) break;

                w.isBusy = true;
                w.activeTaskId = task.id;
                activeTasksProgress.set(task.id, 0);
                taskStartTimes.set(task.id, Date.now());
                isProcessing = true;
                updateQueueUI();

                (async () => {
                    try {
                        const processedPayload = await preprocessImagePayload(task.imagePayload);
                        const recognizeOptions = { user_defined_dpi: '300' };
                        if (task.lang && task.lang.includes('ara')) {
                            recognizeOptions.tessedit_pageseg_mode = '3';
                        }
                        const { data } = await w.worker.recognize(processedPayload, recognizeOptions);
                        completedTasks++;
                        w.pagesProcessed++;
                        task.resolve((data && data.text) || '');
                    } catch (e) {
                        console.error('Background OCR Failed', e);
                        completedTasks++;
                        task.reject(e);
                    } finally {
                        const duration = Date.now() - taskStartTimes.get(task.id);
                        taskDurations.push(duration);
                        if (taskDurations.length > 20) taskDurations.shift();
                        taskStartTimes.delete(task.id);
                        
                        w.isBusy = false;
                        w.activeTaskId = null;
                        activeTasksProgress.delete(task.id);
                        updateQueueUI();
                        pumpQueue();
                    }
                })();
            }
        } finally {
            isPumping = false;
        }
    }

    async function detectLanguage(imagePayload) {
        await loadTesseract();

        console.log('Starting OSD Detection...');
        let osdWorker;
        try {
            osdWorker = await createFallbackWorker('osd', 0, m => console.log('OSD Progress:', m.status, m.progress));
        } catch (initErr) {
            console.error('OSD worker initialization failed, falling back to eng', initErr);
            return 'eng';
        }

        try {
            const detectPromise = osdWorker.detect(imagePayload);
            const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error('OSD Timeout')), 15000));

            const result = await Promise.race([detectPromise, timeoutPromise]);

            if (!result || !result.data || !result.data.script) {
                console.warn('OSD returned incomplete data, falling back to eng');
                return 'eng';
            }

            const script = result.data.script;
            const confidence = result.data.script_confidence || 0;
            console.log('OSD Result:', result.data);

            if (confidence < 15) {
                console.warn('OSD confidence too low:', confidence, 'falling back to eng');
                return 'eng';
            }

            const map = {
                'Arabic': 'ara+eng',
                'Latin': 'eng',
                'Han': 'chi_sim+eng',
                'Japanese': 'jpn+eng',
                'Korean': 'kor+eng',
                'Cyrillic': 'rus+eng',
                'Greek': 'ell+eng',
                'Devanagari': 'hin+eng'
            };

            const detectedLang = map[script] || 'eng';
            console.log('Routed Language:', detectedLang);
            return detectedLang;
        } catch (err) {
            console.error('Inner OSD Error Details:', err, 'Falling back to eng');
            return 'eng';
        } finally {
            console.log('Terminating OSD worker...');
            if (osdWorker) {
                setTimeout(() => { try { osdWorker.terminate(); } catch (e) { } }, 1000);
            }
        }
    }

    window.__litedocOCR = {
        precacheModels: async () => {
            await loadTesseract();
            console.log('[OCR] Precaching OSD model in background...');
            try {
                const worker = await createFallbackWorker('osd', 0, () => {});
                const w = worker;
                setTimeout(() => { try { w.terminate(); } catch (e) { } }, 1000);
                console.log('[OCR] OSD model precached successfully in IndexedDB.');
            } catch (e) {
                console.warn('[OCR] Background precache failed:', e);
            }
        },
        detectScript: async (canvas) => {
            return await detectLanguage(canvas);
        },
        ocrCanvas: async (imagePayload, onProgress, settings) => {
            if (settings && !settings.ocrEnabled) return '';
            const lang = (settings && settings.ocrLang) || 'eng';

            totalTasks++;
            updateQueueUI();

            return new Promise((resolve, reject) => {
                const id = ++taskIdCounter;
                queue.push({ id, imagePayload, lang, resolve, reject });
                pumpQueue();
            });
        },
        cleanupWorker: async () => {
            if (isProcessing || queue.length > 0 || workerPool.some(w => w.isBusy)) return;
            await terminateAllWorkers();
        },
        clearQueue: async () => {
            while (queue.length > 0) {
                queue.shift().reject(new Error('FILE_SKIPPED'));
            }
            await terminateAllWorkers();
            totalTasks = 0;
            completedTasks = 0;
            activeTasksProgress.clear();
            isProcessing = false;
            updateQueueUI();
        }
    };
})();
