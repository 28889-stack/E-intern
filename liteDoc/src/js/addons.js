
(function litedocAddons() {
    'use strict';

    // settings
    const STORAGE_KEY = 'litedoc_addon_settings_v1';
    const isMobile = /Android|webOS|iPhone|iPad|iPod/i.test(navigator.userAgent) || window.innerWidth <= 768;
    const defaults = {
        ocrEnabled: true,
        ocrLang: 'auto',
        tablesEnabled: !isMobile, // Disabled by default on mobile to save CPU
        vectorsEnabled: !isMobile, // Disabled by default on mobile to save CPU
        mathEnabled: true,
        citationsEnabled: false,
    };
    let settings = { ...defaults };
    try {
        const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
        settings = { ...defaults, ...saved };
    } catch (_) { }
    function persist() {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(settings)); } catch (_) { }
    }

    // OCR integration via ocr.js
    async function ocrCanvas(imagePayload, onProgress) {
        if (!window.__litedocOCR) return '';
        return await window.__litedocOCR.ocrCanvas(imagePayload, onProgress, settings);
    }

    async function cleanupWorker() {
        if (window.__litedocOCR) await window.__litedocOCR.cleanupWorker();
    }

    async function clearOcrQueue() {
        if (window.__litedocOCR && typeof window.__litedocOCR.clearQueue === 'function') {
            await window.__litedocOCR.clearQueue();
        }
    }

    // Smart Queuing (Triage)
    async function triageFiles(files, pdfjsLib, specificIndex = -1, providedPassword = null) {
        const results = [];
        const filesToTriage = specificIndex >= 0 ? [files[specificIndex]] : files;

        for (const file of filesToTriage) {
            const meta = { file, name: file.name, size: file.size, triage: 'native', pages: 0 };
            // If the file already has a password from a previous unlock attempt, use it
            const password = providedPassword || file.password;

            try {
                const arrayBuffer = await file.arrayBuffer();
                const originalBuffer = arrayBuffer.slice ? arrayBuffer.slice(0) : new Uint8Array(arrayBuffer).slice().buffer;
                let pdf = null;
                try {
                    const opts = {
                        data: arrayBuffer,
                        useWorkerFetch: false,
                        isEvalSupported: false,
                        disableFontFace: false,
                        fontExtraProperties: true,
                        useSystemFonts: true,
                        stopAtErrors: false,
                        maxImageSize: 10737418240,
                        password: password || undefined,
                        isOffscreenCanvasSupported: true
                    };
                    pdf = await pdfjsLib.getDocument(opts).promise;
                    if (password) file.password = password;
                } catch (initialErr) {
                    const name = initialErr && (initialErr.name || initialErr.constructor && initialErr.constructor.name);
                    const isPwd = name === 'PasswordException' || /password/i.test(initialErr && initialErr.message || '');
                    if (isPwd) {
                        meta.triage = 'password';
                        results.push(meta);
                        continue;
                    }

                    console.warn('[Triage] Enhanced loading failed, trying basic options...', initialErr);
                    try {
                        const basicOpts = {
                            data: originalBuffer.slice(0),
                            password: password || undefined,
                            stopAtErrors: false
                        };
                        pdf = await pdfjsLib.getDocument(basicOpts).promise;
                        if (password) file.password = password;
                    } catch (fallbackErr) {
                        const fallName = fallbackErr && (fallbackErr.name || fallbackErr.constructor && fallbackErr.constructor.name);
                        const isFallPwd = fallName === 'PasswordException' || /password/i.test(fallbackErr && fallbackErr.message || '');
                        if (isFallPwd) {
                            meta.triage = 'password';
                            results.push(meta);
                            continue;
                        }
                        meta.triage = 'corrupted';
                        results.push(meta);
                        continue;
                    }
                }

                meta.pages = pdf.numPages;
                // Empty first page text layer suggests scanned document requiring OCR.
                const pg = await pdf.getPage(1);
                const tc = await pg.getTextContent();
                const textLen = tc.items.map(it => it.str).join('').trim().length;
                if (textLen === 0) {
                    meta.triage = 'ocr';
                }
                pg.cleanup();
                await pdf.destroy();
            } catch (e) {
                console.warn('Triage failed for', file.name, e);
            }
            results.push(meta);
        }

        if (specificIndex >= 0) {
            const result = results[0];
            files[specificIndex].triage = result.triage;
            files[specificIndex].pages = result.pages;
            return files;
        }

        const order = { 'password': 0, 'native': 1, 'ocr': 2 };
        const sorted = results.sort((a, b) => (order[a.triage] || 0) - (order[b.triage] || 0));

        return sorted.map(m => {
            m.file.triage = m.triage;
            m.file.pages = m.pages;
            return m.file;
        });
    }

    // pwd handling
    function ensurePasswordHost(filename) {
        const container = document.getElementById('dz-list-container');
        if (!container) return document.body;
        const rows = container.querySelectorAll('.dz-file-row');
        for (const r of rows) {
            const titleEl = r.querySelector('span[title]');
            if (titleEl && titleEl.title === filename) return r;
        }
        return container;
    }

    function promptPassword(filename, attempt) {
        return new Promise((resolve, reject) => {
            const host = ensurePasswordHost(filename);
            const existingWrap = host.parentNode.querySelector('.ld-pw-row');

            if (existingWrap && attempt > 0) {
                // Reuse existing UI and trigger shake
                existingWrap.classList.remove('animate-shake');
                void existingWrap.offsetWidth; // trigger reflow
                existingWrap.classList.add('animate-shake');

                const err = existingWrap.querySelector('.ld-pw-err');
                if (err) err.textContent = 'Incorrect password. Please try again.';

                const headSpan = existingWrap.querySelector('.ld-pw-head span');
                if (headSpan) headSpan.textContent = 'Wrong password — try again';

                const input = existingWrap.querySelector('input');
                if (input) {
                    input.value = '';
                    input.focus();
                }

                // Need to re-bind the new promise's resolve/reject to the existing form's listeners
                // or just rely on the existing listeners if we can.
                // Since loadPdfWithPassword is in a loop, it awaits a NEW promise each time.
                // To keep it simple, let's remove existing listeners by cloning the form or just 
                // replace the wrap but preserve the animation state.
            }

            // Actually, to make re-binding easy, let's always recreate the wrap 
            // BUT ensure the animation is applied to the NEW wrap if it's a re-attempt.
            if (existingWrap) existingWrap.remove();

            const wrap = document.createElement('div');
            wrap.className = 'ld-pw-row' + (attempt > 0 ? ' animate-shake' : '');
            wrap.innerHTML = `
        <div class="ld-pw-head">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 11c-1.66 0-3 1.34-3 3 0 .89.39 1.68 1 2.22V19h4v-2.78c.61-.54 1-1.33 1-2.22 0-1.66-1.34-3-3-3zM18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zM9 6c0-1.66 1.34-3 3-3s3 1.34 3 3v2H9V6z"/></svg>
            <span>${attempt > 0 ? 'Wrong password — try again' : 'Password required'}</span>
        </div>
        <div class="ld-pw-name" title="${filename}">${filename}</div>
        <form class="ld-pw-form">
            <input type="password" autocomplete="off" placeholder="Enter PDF password" />
            <button type="submit" class="btn-primary text-xs px-4 py-2">Unlock</button>
            <button type="button" class="btn-ghost text-xs px-4 py-2 ld-pw-cancel">Cancel</button>
        </form>
        <div class="ld-pw-err">${attempt > 0 ? 'Incorrect password. Please try again.' : ''}</div>
    `;
            if (host && host.parentNode) {
                host.parentNode.insertBefore(wrap, host);
            } else {
                document.body.appendChild(wrap);
            }
            const input = wrap.querySelector('input');
            const form = wrap.querySelector('form');
            const cancelBtn = wrap.querySelector('.ld-pw-cancel');
            setTimeout(() => { try { input.focus(); } catch (_) { } }, 20);

            form.addEventListener('submit', (e) => {
                e.preventDefault();
                const v = input.value;
                wrap.remove();
                resolve(v);
            });
            cancelBtn.addEventListener('click', () => {
                wrap.remove();
                reject(new Error('cancelled'));
            });
        });
    }

    async function loadPdfWithPassword(arrayBuffer, filename, initialPassword = undefined) {
        const original = arrayBuffer.slice ? arrayBuffer.slice(0) : new Uint8Array(arrayBuffer).slice().buffer;
        let attempt = 0;
        let password = initialPassword;
        while (true) {
            try {
                const data = attempt === 0 ? arrayBuffer : original.slice(0);
                const opts = {
                    data,
                    useWorkerFetch: false,
                    isEvalSupported: false,
                    disableFontFace: false,
                    fontExtraProperties: true,
                    useSystemFonts: true,
                    stopAtErrors: false,
                    maxImageSize: 10737418240,
                    password: password !== undefined ? password : undefined,
                    isOffscreenCanvasSupported: true
                };
                let pdf;
                try {
                    pdf = await pdfjsLib.getDocument(opts).promise;
                } catch (initialErr) {
                    const name = initialErr && (initialErr.name || initialErr.constructor && initialErr.constructor.name);
                    const isPwd = name === 'PasswordException' || /password/i.test(initialErr && initialErr.message || '');
                    if (isPwd) throw initialErr;

                    // Fallback to basic options if enhanced options fail
                    console.warn('[loadPdfWithPassword] Enhanced loading failed, trying basic options...', initialErr);
                    const basicOpts = {
                        data: original.slice(0),
                        password: password !== undefined ? password : undefined,
                        stopAtErrors: false
                    };
                    pdf = await pdfjsLib.getDocument(basicOpts).promise;
                }
                return { pdf, password };
            } catch (err) {
                const name = err && (err.name || err.constructor && err.constructor.name);
                const isPwd = name === 'PasswordException' || /password/i.test(err && err.message || '');
                if (!isPwd) throw err;

                attempt++;
                if (attempt > 5) throw new Error('Too many password attempts');

                // If initial password was wrong, or subsequent ones, prompt
                try {
                    password = await promptPassword(filename, attempt - 1);
                } catch (_) {
                    throw new Error('Password prompt cancelled');
                }
            }
        }
    }

    // vectors
    async function extractVectorRegions(ctx) {
        function checkSkip() {
            if (window.state && window.state.isSkippingFile) {
                throw new Error('FILE_SKIPPED');
            }
        }
        if (!settings.vectorsEnabled) return '';
        const { page, pdfjsLib, pageNum, pageW, pageH, fileName, extractedImages } = ctx;
        const ops = await page.getOperatorList();
        checkSkip();
        const OPS = pdfjsLib.OPS;
        const PATH_OPS = new Set([
            OPS.constructPath, OPS.fill, OPS.stroke, OPS.fillStroke,
            OPS.closePath, OPS.eoFill, OPS.eoFillStroke, OPS.moveTo,
            OPS.lineTo, OPS.curveTo, OPS.curveTo2, OPS.curveTo3,
            OPS.rectangle,
        ].filter(x => x !== undefined));
        const IMG_OPS = new Set([OPS.paintImageXObject, OPS.paintInlineImageXObject].filter(x => x !== undefined));

        let vectorOpCount = 0, imageOpCount = 0;
        for (let i = 0; i < ops.fnArray.length; i++) {
            if (PATH_OPS.has(ops.fnArray[i])) vectorOpCount++;
            if (IMG_OPS.has(ops.fnArray[i])) imageOpCount++;
        }
        if (vectorOpCount < 80) return '';

        const boxes = [];
        for (let i = 0; i < ops.fnArray.length; i++) {
            if (ops.fnArray[i] === OPS.constructPath) {
                const args = ops.argsArray[i];
                if (Array.isArray(args) && args.length >= 3 && Array.isArray(args[2])) {
                    const [minX, minY, maxX, maxY] = args[2];
                    if (isFinite(minX) && isFinite(minY) && isFinite(maxX) && isFinite(maxY)) {
                        const w = maxX - minX, h = maxY - minY;
                        if (w > 8 && h > 8) boxes.push({ x: minX, y: minY, w, h });
                    }
                }
            } else if (ops.fnArray[i] === OPS.rectangle) {
                const a = ops.argsArray[i];
                if (Array.isArray(a) && a.length >= 4) {
                    const [x, y, w, h] = a;
                    if (w > 8 && h > 8) boxes.push({ x, y, w, h });
                }
            }
        }
        if (boxes.length < 4) return '';
        if (boxes.length > 2000) {
            ctx.logToTerminal(`Vector extraction: Skipped page, too many vector paths (${boxes.length})`, 'info');
            return '';
        }

        function overlap(b1, b2, pad) {
            return !(b1.x + b1.w + pad < b2.x || b2.x + b2.w + pad < b1.x ||
                b1.y + b1.h + pad < b2.y || b2.y + b2.h + pad < b1.y);
        }
        const pad = Math.max(20, pageW * 0.02);
        const clusters = [];
        for (const b of boxes) {
            let merged = false;
            for (const c of clusters) {
                if (overlap(c, b, pad)) {
                    const nx = Math.min(c.x, b.x);
                    const ny = Math.min(c.y, b.y);
                    c.w = Math.max(c.x + c.w, b.x + b.w) - nx;
                    c.h = Math.max(c.y + c.h, b.y + b.h) - ny;
                    c.x = nx; c.y = ny; c.count = (c.count || 1) + 1;
                    merged = true; break;
                }
            }
            if (!merged) clusters.push({ ...b, count: 1 });
        }
        const figures = clusters.filter(c =>
            c.count >= 3 &&
            c.w > pageW * 0.08 && c.h > pageH * 0.05 &&
            c.w < pageW * 0.95 && c.h < pageH * 0.95
        );
        if (!figures.length) return '';

        const SCALE = state.selectedImgRes === 0 ? 1.5 : (state.selectedImgRes === 1 ? 2.0 : 2.5);
        const vp = page.getViewport({ scale: SCALE });
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(vp.width);
        canvas.height = Math.round(vp.height);
        const cctx = canvas.getContext('2d');
        cctx.fillStyle = '#ffffff';
        cctx.fillRect(0, 0, canvas.width, canvas.height);
        await page.render({ canvasContext: cctx, viewport: vp }).promise;
        checkSkip();

        let md = '';
        let figIdx = 1;
        for (const f of figures) {
            const sx = Math.max(0, f.x * SCALE - 6);
            const sw = Math.min(canvas.width - sx, f.w * SCALE + 12);
            const sy = Math.max(0, (pageH - f.y - f.h) * SCALE - 6);
            const sh = Math.min(canvas.height - sy, f.h * SCALE + 12);
            if (sw < 20 || sh < 20) continue;
            const crop = document.createElement('canvas');
            crop.width = Math.round(sw);
            crop.height = Math.round(sh);
            const ccx = crop.getContext('2d');
            ccx.fillStyle = '#ffffff';
            ccx.fillRect(0, 0, crop.width, crop.height);
            ccx.drawImage(canvas, sx, sy, sw, sh, 0, 0, crop.width, crop.height);
            const q = state.selectedImgRes === 0 ? 0.82 : (state.selectedImgRes === 1 ? 0.9 : 0.96);
            const blob = await new Promise(res => crop.toBlob(res, 'image/jpeg', q));
            crop.width = 0; crop.height = 0;
            const dataUrl = URL.createObjectURL(blob);
            const name = `${fileName}_p${pageNum}_figure${figIdx}.jpg`;
            extractedImages.push({ name, dataUrl, dims: `${crop.width}×${crop.height}` });

            const figureMd = `\n\n!Figure ${figIdx}`;

            // Map the figure back into the text flow using its vertical position
            const figTopY = f.y + f.h;
            const closestLg = ctx.lineGroups.length > 0 ? ctx.lineGroups.reduce((prev, curr) => {
                return (Math.abs(curr.y - figTopY) < Math.abs(prev.y - figTopY)) ? curr : prev;
            }, ctx.lineGroups[0]) : null;

            if (closestLg && Math.abs(closestLg.y - figTopY) < 150) closestLg.injectedMarkdown = (closestLg.injectedMarkdown || '') + figureMd;
            else md += figureMd;

            figIdx++;
        }
        canvas.width = 0; canvas.height = 0;
        return md;
    }

    async function findTableGrids(ctx) {
        const { page, pdfjsLib } = ctx;
        if (!page || !pdfjsLib) return [];

        const ops = await page.getOperatorList();
        const OPS = pdfjsLib.OPS;
        const vLinesRaw = [];
        const hLinesRaw = [];
        let curX = 0, curY = 0;

        for (let i = 0; i < ops.fnArray.length; i++) {
            const fn = ops.fnArray[i];
            const args = ops.argsArray[i];
            if (fn === OPS.moveTo) {
                curX = args[0]; curY = args[1];
            } else if (fn === OPS.lineTo) {
                const x = args[0], y = args[1];
                if (Math.abs(y - curY) < 2 && Math.abs(x - curX) > 5) {
                    hLinesRaw.push({ y: (y + curY) / 2, x1: Math.min(x, curX), x2: Math.max(x, curX) });
                } else if (Math.abs(x - curX) < 2 && Math.abs(y - curY) > 5) {
                    vLinesRaw.push({ x: (x + curX) / 2, y1: Math.min(y, curY), y2: Math.max(y, curY) });
                }
                curX = x; curY = y;
            } else if (fn === OPS.rectangle) {
                const rx = args[0], ry = args[1], rw = args[2], rh = args[3];
                hLinesRaw.push({ y: ry, x1: rx, x2: rx + rw });
                hLinesRaw.push({ y: ry + rh, x1: rx, x2: rx + rw });
                vLinesRaw.push({ x: rx, y1: Math.min(ry, ry + rh), y2: Math.max(ry, ry + rh) });
                vLinesRaw.push({ x: rx + rw, y1: Math.min(ry, ry + rh), y2: Math.max(ry, ry + rh) });
            } else if (fn === OPS.constructPath) {
                const opList = args[0];
                const opArgs = args[1];
                let argIdx = 0;
                for (let j = 0; j < opList.length; j++) {
                    const op = opList[j];
                    if (op === 1) { // MOVE_TO
                        curX = opArgs[argIdx++]; curY = opArgs[argIdx++];
                    } else if (op === 2) { // LINE_TO
                        const x = opArgs[argIdx++], y = opArgs[argIdx++];
                        if (Math.abs(y - curY) < 2 && Math.abs(x - curX) > 5) {
                            hLinesRaw.push({ y: (y + curY) / 2, x1: Math.min(x, curX), x2: Math.max(x, curX) });
                        } else if (Math.abs(x - curX) < 2 && Math.abs(y - curY) > 5) {
                            vLinesRaw.push({ x: (x + curX) / 2, y1: Math.min(y, curY), y2: Math.max(y, curY) });
                        }
                        curX = x; curY = y;
                    } else if (op === 7) { // RECTANGLE
                        const rx = opArgs[argIdx++], ry = opArgs[argIdx++], rw = opArgs[argIdx++], rh = opArgs[argIdx++];
                        hLinesRaw.push({ y: ry, x1: rx, x2: rx + rw });
                        hLinesRaw.push({ y: ry + rh, x1: rx, x2: rx + rw });
                        vLinesRaw.push({ x: rx, y1: Math.min(ry, ry + rh), y2: Math.max(ry, ry + rh) });
                        vLinesRaw.push({ x: rx + rw, y1: Math.min(ry, ry + rh), y2: Math.max(ry, ry + rh) });
                    } else if (op === 3) { // CURVE_TO
                        argIdx += 6; curX = opArgs[argIdx - 2]; curY = opArgs[argIdx - 1];
                    } else if (op === 4 || op === 5) { // CURVE_TO2 & CURVE_TO3
                        argIdx += 4; curX = opArgs[argIdx - 2]; curY = opArgs[argIdx - 1];
                    } else if (op === 6) { // CLOSE_PATH
                        // closePath 
                    }
                }
            }
        }

        // Consolidate overlapping lines
        const hLines = [];
        for (const h of hLinesRaw) {
            let found = false;
            for (const existing of hLines) {
                if (Math.abs(existing.y - h.y) < 4) {
                    existing.x1 = Math.min(existing.x1, h.x1);
                    existing.x2 = Math.max(existing.x2, h.x2);
                    found = true;
                    break;
                }
            }
            if (!found) hLines.push({ ...h });
        }

        const vLines = [];
        for (const v of vLinesRaw) {
            let found = false;
            for (const existing of vLines) {
                if (Math.abs(existing.x - v.x) < 4) {
                    existing.y1 = Math.min(existing.y1, v.y1);
                    existing.y2 = Math.max(existing.y2, v.y2);
                    found = true;
                    break;
                }
            }
            if (!found) vLines.push({ ...v });
        }

        hLines.sort((a, b) => b.y - a.y);
        vLines.sort((a, b) => a.x - b.x);

        // Find grid intersections
        const intersections = [];
        for (const h of hLines) {
            for (const v of vLines) {
                if (v.x >= h.x1 - 4 && v.x <= h.x2 + 4 && h.y <= v.y2 + 4 && h.y >= v.y1 - 4) {
                    intersections.push({ x: v.x, y: h.y });
                }
            }
        }

        if (intersections.length < 4) return [];

        const ix = [...new Set(intersections.map(i => Math.round(i.x)))].sort((a, b) => a - b);
        const iy = [...new Set(intersections.map(i => Math.round(i.y)))].sort((a, b) => b - a); // Top to bottom in PDF space

        const gridCols = [];
        for (const x of ix) {
            if (!gridCols.length || x - gridCols[gridCols.length - 1] > 4) gridCols.push(x);
        }

        const gridRows = [];
        for (const y of iy) {
            if (!gridRows.length || gridRows[gridRows.length - 1] - y > 4) gridRows.push(y);
        }

        if (gridCols.length < 2 || gridRows.length < 2) return [];

        const tables = [];
        let currentTableRows = [gridRows[0]];
        for (let i = 1; i < gridRows.length; i++) {
            if (currentTableRows[currentTableRows.length - 1] - gridRows[i] > 150) {
                if (currentTableRows.length >= 2) tables.push({ rows: currentTableRows, cols: gridCols });
                currentTableRows = [gridRows[i]];
            } else {
                currentTableRows.push(gridRows[i]);
            }
        }
        if (currentTableRows.length >= 2) tables.push({ rows: currentTableRows, cols: gridCols });

        return tables.map(tbl => ({
            rows: tbl.rows,
            cols: tbl.cols,
            bbox: {
                yMin: Math.min(...tbl.rows),
                yMax: Math.max(...tbl.rows),
                xMin: Math.min(...tbl.cols),
                xMax: Math.max(...tbl.cols)
            }
        }));
    }

    // extract tables
    async function detectTables(ctx) {
        if (!settings.tablesEnabled) return '';
        const { lineGroups, columns, leftLines, rightLines, logToTerminal } = ctx;

        let finalMd = '';
        let tableState = { idx: 1 };

        const linesToUse = columns && columns.length > 0 ? columns : (leftLines && rightLines ? [leftLines, rightLines] : [lineGroups]);

        for (let i = 0; i < linesToUse.length; i++) {
            const currentLines = linesToUse[i];
            if (!currentLines || currentLines.length === 0) continue;

            finalMd += await processTableLines(currentLines, ctx, linesToUse.length > 1 ? `Col ${i + 1}` : 'Full', tableState);
        }
        return finalMd;
    }

    async function processTableLines(linesToProcess, ctx, columnLabel, tableState) {
        const { logToTerminal } = ctx;
        logToTerminal(`Table detection: Restructuring text grid for analysis (${columnLabel})`, 'info');

        // Extract all valid items and reconstruct strict horizontal lines
        const allItems = [];
        for (const lg of linesToProcess) {
            if (lg.garbage) continue;
            for (const item of lg.items) {
                if (!item.garbage && item.str.trim()) {
                    allItems.push(item);
                }
            }
        }

        if (allItems.length < 4) return '';
        if (allItems.length > 2000) {
            logToTerminal(`Table detection: Skipped block, too many items to process (${allItems.length})`, 'info');
            return '';
        }

        // Sort top-to-bottom, left-to-right
        allItems.sort((a, b) => b.y - a.y || a.x - b.x);

        // Group into lines with tight tolerance
        const lines = [];
        for (const item of allItems) {
            const lastLine = lines[lines.length - 1];
            const tol = Math.max(2, (item.height || 10) * 0.35);
            if (lastLine && Math.abs(item.y - lastLine.y) <= tol) {
                lastLine.items.push(item);
            } else {
                lines.push({ y: item.y, height: item.height || 10, items: [item] });
            }
        }

        // Group items within lines into cells
        for (const line of lines) {
            line.items.sort((a, b) => a.x - b.x);
            const cells = [];
            for (const item of line.items) {
                const lastCell = cells[cells.length - 1];
                const spaceWidth = (item.height || 10) * 0.5;
                const gap = lastCell ? (item.x - lastCell.xMax) : Infinity;

                if (lastCell && gap < spaceWidth * 1.5) {
                    lastCell.str += (gap > spaceWidth * 0.2 ? ' ' : '') + item.str.trim();
                    lastCell.xMax = Math.max(lastCell.xMax, item.x + (item.width || 0));
                    lastCell.items.push(item);
                } else {
                    cells.push({
                        str: item.str.trim(),
                        xMin: item.x,
                        xMax: item.x + (item.width || 0),
                        items: [item]
                    });
                }
            }
            line.cells = cells;
        }

        const tableBlocks = [];
        let currentBlock = [];

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const isTableRow = line.cells.length >= 2;

            if (isTableRow) {
                if (currentBlock.length > 0) {
                    const prevLine = currentBlock[currentBlock.length - 1];
                    const vGap = prevLine.y - line.y;
                    if (vGap > Math.max(prevLine.height, line.height) * 4) {
                        if (currentBlock.filter(l => l.cells.length >= 2).length >= 2) tableBlocks.push(currentBlock);
                        currentBlock = [];
                    }
                }
                currentBlock.push(line);
            } else {
                if (currentBlock.length > 0) {
                    const prevLine = currentBlock[currentBlock.length - 1];
                    const vGap = prevLine.y - line.y;
                    if (vGap < Math.max(prevLine.height, line.height) * 2.5) {
                        currentBlock.push(line);
                    } else {
                        if (currentBlock.filter(l => l.cells.length >= 2).length >= 2) tableBlocks.push(currentBlock);
                        currentBlock = [];
                    }
                }
            }
        }
        if (currentBlock.filter(l => l.cells.length >= 2).length >= 2) tableBlocks.push(currentBlock);

        if (tableBlocks.length === 0) return '';

        let md = '';

        for (const block of tableBlocks) {
            const xEdges = [];
            for (const line of block) {
                for (const cell of line.cells) xEdges.push(cell.xMin);
            }

            xEdges.sort((a, b) => a - b);
            const cols = [];
            let curCol = [xEdges[0]];

            for (let i = 1; i < xEdges.length; i++) {
                if (xEdges[i] - curCol[curCol.length - 1] < 12) {
                    curCol.push(xEdges[i]);
                } else {
                    cols.push(curCol.reduce((a, b) => a + b) / curCol.length);
                    curCol = [xEdges[i]];
                }
            }
            if (curCol.length > 0) cols.push(curCol.reduce((a, b) => a + b) / curCol.length);

            if (cols.length < 2) continue;
            if (cols.length > 60) {
                logToTerminal(`Table detection: Skipped block, extreme column count (${cols.length})`, 'info');
                continue;
            }

            const numCols = cols.length;
            const grid = [];
            let overlapCount = 0;

            for (const line of block) {
                const rowData = Array(numCols).fill('');
                for (const cell of line.cells) {
                    let bestCol = 0;
                    let minDist = Infinity;
                    for (let c = 0; c < numCols; c++) {
                        const dist = Math.abs(cell.xMin - cols[c]);
                        if (dist < minDist) {
                            minDist = dist;
                            bestCol = c;
                        }
                    }
                    
                    // Complex Merged Cells
                    let endCol = bestCol;
                    for (let c = bestCol + 1; c < numCols; c++) {
                        if (cell.xMax > cols[c] - 15) {
                            endCol = c;
                        }
                    }
                    
                    if (endCol > bestCol) {
                        overlapCount += (endCol - bestCol);
                        rowData[bestCol] += (rowData[bestCol] ? ' ' : '') + cell.str;
                        for (let span = bestCol + 1; span <= endCol; span++) {
                            rowData[span] = ''; 
                        }
                    } else {
                        rowData[bestCol] += (rowData[bestCol] ? ' ' : '') + cell.str;
                    }
                }
                grid.push({ rowData, line });
            }

            let filledCount = 0;
            grid.forEach(r => r.rowData.forEach(c => { if (c.trim()) filledCount++; }));
            const fillRatio = filledCount / (grid.length * numCols);

            if (fillRatio < 0.20) {
                logToTerminal(`Table detection: Skipped block, fill ratio too low (${fillRatio.toFixed(2)})`, 'info');
                continue;
            }

            if (overlapCount > (grid.length * numCols) * 0.35) {
                logToTerminal(`Table detection: Skipped block, looks like a paragraph (overlap ratio too high)`, 'info');
                continue;
            }

            logToTerminal(`Table detection: Found table with ${grid.length} rows, ${numCols} cols`, 'success');

            for (const r of grid) {
                for (const cell of r.line.cells) {
                    for (const it of cell.items) {
                        it.garbage = true;
                        it.str = '';
                    }
                }
            }

            let isContinuation = false;
            let prevHeader = null;
            if (tableState.idx === 1 && window.__litedocTableState && window.__litedocTableState.lastTable &&
                window.__litedocTableState.lastTable.cols === numCols) {
                
                const lastH = window.__litedocTableState.lastTable.header;
                const rowTexts = grid[0].rowData.map(c => (c || '').trim());
                
                let headerMatch = false;
                if (lastH) {
                    let matchCount = 0;
                    for (let i = 0; i < numCols; i++) {
                        if (lastH[i] && rowTexts[i] && lastH[i] === rowTexts[i]) matchCount++;
                    }
                    if (matchCount / numCols >= 0.5) headerMatch = true;
                }
                
                if (headerMatch || window.__litedocTableState.lastTable.pageNum >= ctx.pageNum - 2) {
                    isContinuation = true;
                    prevHeader = window.__litedocTableState.lastTable.header;
                    if (headerMatch && grid.length > 1) {
                        grid.shift();
                    }
                }
            }

            const esc = s => (s || '').replace(/\|/g, '\\|').replace(/\n/g, ' ').trim();

            let tableMd = '\n\n';
            for (let r = 0; r < grid.length; r++) {
                const rowTexts = grid[r].rowData.map(esc);
                tableMd += '| ' + rowTexts.join(' | ') + ' |\n';

                if (r === 0) {
                    if (isContinuation && prevHeader) {
                        tableMd = tableMd.replace('| ' + rowTexts.join(' | ') + ' |\n', '| ' + prevHeader.join(' | ') + ' |\n|' + prevHeader.map(() => '---').join('|') + '|\n| ' + rowTexts.join(' | ') + ' |\n');
                        window.__litedocTableState.lastTable = { pageNum: ctx.pageNum, cols: numCols, header: prevHeader };
                    } else {
                        tableMd += '|' + rowTexts.map(() => '---').join('|') + '|\n';

                        if (!window.__litedocTableState) window.__litedocTableState = {};
                        window.__litedocTableState.lastTable = { pageNum: ctx.pageNum, cols: numCols, header: rowTexts };
                    }
                }
            }

            const tableYMin = Math.min(...grid.flatMap(r => r.line.cells.flatMap(c => c.items.map(it => it.y))));
            
            // Find the first logical line group that is physically below the table
            const belowLgs = ctx.lineGroups
                .filter(lg => lg.y < tableYMin - 5 && lg.blockIdx !== undefined)
                .sort((a, b) => a.blockIdx - b.blockIdx);
            
            const targetLg = belowLgs.length > 0 ? belowLgs[0] : null;

            if (targetLg) targetLg.injectedMarkdown = (targetLg.injectedMarkdown || '') + tableMd;
            else md += tableMd;

            tableState.idx++;
        }
        return md;
    }

    async function detectMathRegions(ctx) {
        if (!settings.mathEnabled) return '';
        const { page, pdfjsLib, pageNum, pageW, pageH, fileName, lineGroups, extractedImages, logToTerminal } = ctx;

        let mathRegions = [];
        let currentRegion = null;

        for (let i = 0; i < lineGroups.length; i++) {
            const lg = lineGroups[i];
            if (lg.isTable) continue;

            let totalChars = 0;
            let mathChars = 0;

            for (const item of lg.items) {
                const txt = item.str.trim();
                if (!txt) continue;
                totalChars += txt.length;

                const fontName = (item.fontName || '').toLowerCase();
                const isMathFont = fontName.includes('math') || fontName.includes('cmsy') || fontName.includes('cmmi') || fontName.includes('symbol');

                let hasMathUnicode = false;
                for (let j = 0; j < txt.length; j++) {
                    const code = txt.charCodeAt(j);
                    if (
                        (code >= 0x2200 && code <= 0x22FF) || // Math Operators
                        (code >= 0x2190 && code <= 0x21FF) || // Arrows
                        (code >= 0x0370 && code <= 0x03FF) || // Greek
                        (code >= 0xE000 && code <= 0xF8FF) || // PUA
                        (code >= 0xF0000)                     // PUA-supp
                    ) {
                        hasMathUnicode = true;
                        break;
                    }
                }

                if (isMathFont || hasMathUnicode || txt === '=' || txt === '+' || txt === '-' || txt === '±') {
                    mathChars += txt.length;
                }
            }

            const isMathLine = totalChars > 0 && (mathChars / totalChars) > 0.25;

            if (isMathLine) {
                if (!currentRegion) {
                    currentRegion = { 
                        xMin: lg.xMin, xMax: lg.xMax, yMin: lg.yMin, yMax: lg.yMax,
                        lines: [lg]
                    };
                } else {
                    const distance = Math.max(0, currentRegion.yMin - lg.yMax);
                    if (distance < lg.height * 3) {
                        currentRegion.xMin = Math.min(currentRegion.xMin, lg.xMin);
                        currentRegion.xMax = Math.max(currentRegion.xMax, lg.xMax);
                        currentRegion.yMin = Math.min(currentRegion.yMin, lg.yMin);
                        currentRegion.yMax = Math.max(currentRegion.yMax, lg.yMax);
                        currentRegion.lines.push(lg);
                    } else {
                        mathRegions.push(currentRegion);
                        currentRegion = { 
                            xMin: lg.xMin, xMax: lg.xMax, yMin: lg.yMin, yMax: lg.yMax,
                            lines: [lg]
                        };
                    }
                }
            } else {
                if (currentRegion) {
                    mathRegions.push(currentRegion);
                    currentRegion = null;
                }
            }
        }
        if (currentRegion) mathRegions.push(currentRegion);

        mathRegions = mathRegions.filter(r => (r.xMax - r.xMin) > 15 && (r.yMax - r.yMin) > 10);

        if (mathRegions.length === 0) return '';

        logToTerminal(`Math detection: Found ${mathRegions.length} math regions on page ${pageNum}`, 'success');

        const stateObj = window.state || { selectedImgRes: 1 };
        const SCALE = stateObj.selectedImgRes === 0 ? 1.5 : (stateObj.selectedImgRes === 1 ? 2.0 : 2.5);
        const vp = page.getViewport({ scale: SCALE });
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(vp.width);
        canvas.height = Math.round(vp.height);
        const cctx = canvas.getContext('2d');
        cctx.fillStyle = '#ffffff';
        cctx.fillRect(0, 0, canvas.width, canvas.height);
        await page.render({ canvasContext: cctx, viewport: vp }).promise;

        let md = '';
        let mathIdx = 1;

        for (const r of mathRegions) {
            const pad = 12 * SCALE;
            const sx = Math.max(0, r.xMin * SCALE - pad);
            const sw = Math.min(canvas.width - sx, (r.xMax - r.xMin) * SCALE + pad * 2);
            
            const cropTopY = (pageH - r.yMax) * SCALE - pad;
            const sy = Math.max(0, cropTopY);
            const sh = Math.min(canvas.height - sy, (r.yMax - r.yMin) * SCALE + pad * 2);

            if (sw < 10 || sh < 10) continue;

            const crop = document.createElement('canvas');
            crop.width = Math.round(sw);
            crop.height = Math.round(sh);
            const ccx = crop.getContext('2d');
            ccx.fillStyle = '#ffffff';
            ccx.fillRect(0, 0, crop.width, crop.height);
            ccx.drawImage(canvas, sx, sy, sw, sh, 0, 0, crop.width, crop.height);

            const q = stateObj.selectedImgRes === 0 ? 0.82 : (stateObj.selectedImgRes === 1 ? 0.9 : 0.96);
            let dataUrl = '';
            
            try {
                const blob = await new Promise(res => crop.toBlob(res, 'image/jpeg', q));
                if (blob) {
                    dataUrl = URL.createObjectURL(blob);
                } else {
                    dataUrl = crop.toDataURL('image/jpeg', q);
                }
            } catch(e) {
                dataUrl = crop.toDataURL('image/jpeg', q);
            }
            
            crop.width = 0; crop.height = 0;
            
            const name = `${fileName}_p${pageNum}_math${mathIdx}.jpg`;
            extractedImages.push({ name, dataUrl, dims: `${Math.round(sw)}×${Math.round(sh)}` });

            const mathMd = `\n\n[IMAGE: ${name}]\n\n`;

            r.lines[0].injectedMarkdown = (r.lines[0].injectedMarkdown || '') + mathMd;

            for (const lg of r.lines) {
                lg.garbage = true;
                lg.isMath = true;
                for (const item of lg.items) item.garbage = true;
            }

            mathIdx++;
        }
        
        canvas.width = 0; canvas.height = 0;
        return md;
    }

    async function detectCitations(ctx) {
        if (!settings.citationsEnabled) return '';

        // Reset the tracking state if we are starting a new document (Page 1)
        if (!window.__litedocCitationState || ctx.pageNum === 1) {
            window.__litedocCitationState = { inReferences: false };
        }

        const state = window.__litedocCitationState;
        const citationsFoundOnPage = [];
        let currentCitation = null;

        for (const lg of ctx.lineGroups) {
            if (lg.garbage && !lg.text) continue;

            const text = (lg.text || lg.rawText || '').trim();
            if (!text) continue;

            if (!state.inReferences) {
                const lower = text.toLowerCase();
                if ((lower === 'references' || lower === 'bibliography' || lower === 'literature cited') && text.length < 30) {
                    state.inReferences = true;
                    lg.garbage = true; // Consume the header itself
                    continue;
                }
            }

            if (state.inReferences) {
                // Stop capturing if we hit typical post-reference sections
                const stopMatch = text.toLowerCase().match(/^(appendices|supplementary data|acknowledgments)/);
                if (stopMatch && text.length < 30) {
                    state.inReferences = false;
                    break;
                }

                // Check for new numbered citation (e.g., "[1] " or "1. ")
                const match = text.match(/^(?:\[(\d+)\]|(\d+)\.)\s+(.+)/);
                if (match) {
                    if (currentCitation) citationsFoundOnPage.push(currentCitation);
                    currentCitation = { id: match[1] || match[2], text: match[3] };
                    lg.garbage = true; // Hide from standard markdown flow
                } else if (currentCitation) {
                    currentCitation.text += ' ' + text; // Continuation line
                    lg.garbage = true;
                }
            }
        }
        if (currentCitation) citationsFoundOnPage.push(currentCitation);

        if (citationsFoundOnPage.length > 0) {
            ctx.logToTerminal && ctx.logToTerminal(`Citation extraction: Found ${citationsFoundOnPage.length} references on page ${ctx.pageNum}`, 'success');
            const jsonStr = JSON.stringify(citationsFoundOnPage, null, 2);
            return `\n\n### Extracted Citations (JSON)\n\`\`\`json\n${jsonStr}\n\`\`\`\n\n`;
        }
        return '';
    }

    async function enhancePage(ctx) {
        let extra = '';
        try { extra += await detectTables(ctx); } catch (e) { ctx.logToTerminal && ctx.logToTerminal('table detection error: ' + e.message, 'warn'); }
        try { extra += await extractVectorRegions(ctx); } catch (e) { ctx.logToTerminal && ctx.logToTerminal('vector extraction error: ' + e.message, 'warn'); }
        try { extra += await detectMathRegions(ctx); } catch (e) { ctx.logToTerminal && ctx.logToTerminal('math extraction error: ' + e.message, 'warn'); }
        try { extra += await detectCitations(ctx); } catch (e) { ctx.logToTerminal && ctx.logToTerminal('citation extraction error: ' + e.message, 'warn'); }
        return extra;
    }

    function buildSettingsUI() {
        const settingsCard = document.querySelector('.settings-card');
        if (!settingsCard) return;
        if (settingsCard.querySelector('.ld-addon-block')) return;

        const block = document.createElement('div');
        block.className = 'ld-addon-block';
        block.innerHTML = `
            <div class="ld-addon-row">
                <div class="ld-addon-info">
                    <span class="ld-addon-label">OCR for scanned PDFs</span>
                    <span class="ld-addon-sub">Run Tesseract on pages with no text layer</span>
                </div>
                <button type="button" class="ld-addon-toggle ${settings.ocrEnabled ? 'on' : ''}" data-key="ocrEnabled" aria-label="Toggle OCR"></button>
            </div>
            <div class="ld-addon-row" data-when="ocrEnabled" style="${settings.ocrEnabled ? '' : 'display:none'}">
                <div class="ld-addon-info">
                    <span class="ld-addon-label">OCR language</span>
                    <span class="ld-addon-sub">Tesseract language model</span>
                </div>
                <div class="ld-custom-select" data-key="ocrLang">
                    <div class="ld-select-display">
                        <span class="ld-select-value">Auto-Detect (OSD)</span>
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                    </div>
                    <div class="ld-select-dropdown">
                        <div class="ld-select-option" data-value="auto">Auto-Detect (OSD)</div>
                        <div class="ld-select-option" data-value="eng">English</div>
                        <div class="ld-select-option" data-value="ara">Arabic</div>
                        <div class="ld-select-option" data-value="ara+eng">Arabic + English</div>
                        <div class="ld-select-option" data-value="fra+eng">French + English</div>
                        <div class="ld-select-option" data-value="deu+eng">German + English</div>
                        <div class="ld-select-option" data-value="spa+eng">Spanish + English</div>
                        <div class="ld-select-option" data-value="chi_sim+eng">Chinese + English</div>
                    </div>
                </div>
            </div>
            <div class="ld-addon-row">
                <div class="ld-addon-info">
                    <span class="ld-addon-label">Detect tables &amp; columns</span>
                    <span class="ld-addon-sub">Emit GFM tables when rows align cleanly</span>
                </div>
                <button type="button" class="ld-addon-toggle ${settings.tablesEnabled ? 'on' : ''}" data-key="tablesEnabled" aria-label="Toggle tables"></button>
            </div>
            <div class="ld-addon-row">
                <div class="ld-addon-info">
                    <span class="ld-addon-label">Extract vector figures</span>
                    <span class="ld-addon-sub">Capture charts/diagrams drawn as paths</span>
                </div>
                <button type="button" class="ld-addon-toggle ${settings.vectorsEnabled ? 'on' : ''}" data-key="vectorsEnabled" aria-label="Toggle vectors"></button>
            </div>
            <div class="ld-addon-row">
                <div class="ld-addon-info">
                    <span class="ld-addon-label">Extract citations (JSON)</span>
                    <span class="ld-addon-sub">Parse academic references into structured JSON format</span>
                </div>
                <button type="button" class="ld-addon-toggle ${settings.citationsEnabled ? 'on' : ''}" data-key="citationsEnabled" aria-label="Toggle citations"></button>
            </div>
        `;

        const body = settingsCard.querySelector('.m-collapse-body') || settingsCard.querySelector('div');
        (body || settingsCard).appendChild(block);

        block.querySelectorAll('.ld-addon-toggle').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.dataset.key;
                settings[key] = !settings[key];
                btn.classList.toggle('on', settings[key]);
                persist();
                
                // If a layout formatter is turned ON, Raw Text Mode must be turned OFF
                if (settings[key] && (key === 'tablesEnabled' || key === 'vectorsEnabled' || key === 'citationsEnabled')) {
                    if (window.state && window.state.rawTextMode) {
                        window.state.rawTextMode = false;
                        localStorage.setItem('litedoc-raw-mode', false);
                        const rBtn = document.getElementById('rawtext-toggle-btn');
                        const rKnob = document.getElementById('rawtext-toggle-knob');
                        if (rBtn) rBtn.style.background = 'var(--bg-input)';
                        if (rKnob) { rKnob.style.transform = 'translateX(0)'; rKnob.style.background = 'rgba(255,255,255,0.4)'; }
                    }
                }

                const dep = block.querySelector(`[data-when="${key}"]`);
                if (dep) dep.style.display = settings[key] ? '' : 'none';
            });
        });
        
        const customSel = block.querySelector('.ld-custom-select[data-key="ocrLang"]');
        if (customSel) {
            const display = customSel.querySelector('.ld-select-value');
            const options = customSel.querySelectorAll('.ld-select-option');

            const initialOpt = Array.from(options).find(o => o.dataset.value === settings.ocrLang) || options[0];
            display.textContent = initialOpt.textContent;
            options.forEach(o => o.classList.toggle('selected', o === initialOpt));

            customSel.addEventListener('click', (e) => {
                e.stopPropagation();
                customSel.classList.toggle('open');
            });

            document.addEventListener('click', () => {
                customSel.classList.remove('open');
            });

            options.forEach(opt => {
                opt.addEventListener('click', (e) => {
                    e.stopPropagation();
                    settings.ocrLang = opt.dataset.value;
                    display.textContent = opt.textContent;
                    options.forEach(o => o.classList.toggle('selected', o === opt));
                    customSel.classList.remove('open');
                    
                    if (window.__litedocOCR) window.__litedocOCR.cleanupWorker();
                    persist();
                });
            });
        }
    }

    function onRawModeToggled(isRawOn) {
        if (!isRawOn) return;
        const keysToDisable = ['tablesEnabled', 'vectorsEnabled', 'citationsEnabled'];
        let changed = false;
        keysToDisable.forEach(key => {
            if (settings[key]) {
                settings[key] = false;
                changed = true;
                const btn = document.querySelector(`.ld-addon-toggle[data-key="${key}"]`);
                if (btn) btn.classList.remove('on');
            }
        });
        if (changed) persist();
    }

    window.__litedocAddons = {
        loadPdfWithPassword,
        ocrCanvas,
        ocrEnabled: () => settings.ocrEnabled,
        enhancePage,
        cleanupWorker,
        clearOcrQueue,
        triageFiles,
        _settings: settings,
        onRawModeToggled
    };

    if (document.readyState !== 'loading') buildSettingsUI();
    else document.addEventListener('DOMContentLoaded', buildSettingsUI);
})();
