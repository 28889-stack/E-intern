// Clean up stray blockquote markers and duplicate page headings
function cleanMarkdown(md) {
    const lines = md.split('\n');
    const cleaned = [];
    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];
        // Strip leading '> ' when it is not a true blockquote (previous line not empty or not another blockquote)
        if (line.startsWith('> ')) {
            if (i === 0 || lines[i - 1].trim() === '' || lines[i - 1].startsWith('>')) {
                // keep as blockquote
            } else {
                line = line.slice(2);
            }
        }
        // Skip duplicate page headings that may appear consecutively
        if (line.startsWith('## Page ') && cleaned.length && cleaned[cleaned.length - 1].startsWith('## Page ')) {
            continue;
        }
        cleaned.push(line);
    }
    return cleaned.join('\n');
}

function segmentBox(boxItems, pageW, pageH, depth = 0) {
    if (boxItems.length === 0) return [];

    // ── Helper: find vertical gutters using line-gap voting ───────────
    function findVerticalGutters(items) {
        if (items.length < 5) return [];
        console.log(`[findVerticalGutters] items count: ${items.length}`);

        const pageW_int = Math.ceil(pageW);
        const projection = new Float32Array(pageW_int);
        for (const item of items) {
            const itemW = item.width || 0;
            if (itemW > pageW * 0.50) continue; // Skip full-width headers/tables that destroy the gutter
            const xStart = Math.max(0, Math.floor(item.x));
            const xEnd = Math.min(pageW_int - 1, Math.ceil(item.x + itemW));
            for (let x = xStart; x <= xEnd; x++) {
                projection[x] += 1;
            }
        }

        let maxProj = 0;
        for (let x = 0; x < pageW_int; x++) {
            if (projection[x] > maxProj) maxProj = projection[x];
        }
        // Tolerate up to 25% noise (or 10 absolute items) crossing the gap (e.g. table rows, spanning headers)
        const threshold = Math.max(10, Math.floor(maxProj * 0.25));

        const MIN_GAP = 12;
        const gutters = [];
        let gapStart = -1;
        const searchStart = Math.floor(pageW * 0.15);
        const searchEnd = Math.floor(pageW * 0.85);

        for (let x = searchStart; x <= searchEnd; x++) {
            if (projection[x] <= threshold) {
                if (gapStart === -1) gapStart = x;
            } else {
                if (gapStart !== -1) {
                    const gapWidth = x - gapStart;
                    if (gapWidth >= MIN_GAP) {
                        gutters.push({ x: gapStart + gapWidth / 2, count: gapWidth });
                    }
                    gapStart = -1;
                }
            }
        }
        if (gapStart !== -1) {
            const gapWidth = (searchEnd + 1) - gapStart;
            if (gapWidth >= MIN_GAP) {
                gutters.push({ x: gapStart + gapWidth / 2, count: gapWidth });
            }
        }

        console.log(`[findVerticalGutters] maxProj=${maxProj}, threshold=${threshold}, gutters=${gutters.map(g => g.x).join(', ')}`);
        gutters.sort((a, b) => b.count - a.count);
        return gutters;
    }

    // ── Helper: group items into lines within a single column ──────────
    function groupIntoLines(items, tightGap = false) {
        items.sort((a, b) => Math.abs(b.y - a.y) < 2 ? a.x - b.x : b.y - a.y);
        const lines = [];
        for (const item of items) {
            const last = lines[lines.length - 1];
            const tol = Math.max(3, (item.height || 10) * 0.45);
            let isSameLine = false;
            if (last && Math.abs(item.y - last.y) <= tol) {
                const gap = item.x - last.xMax;
                // Within a single column, word spacing is typically 0.2–0.6× font height
                const maxLineGap = (item.height || 10) * (tightGap ? 0.90 : 1.2);
                if (gap > -(item.height || 10) * 0.5 && gap < maxLineGap) isSameLine = true;
            }
            if (isSameLine) {
                last.items.push(item);
                last.xMax = Math.max(last.xMax, item.x + (item.width || 0));
                last.xMin = Math.min(last.xMin, item.x);
                last.yMin = Math.min(last.yMin, item.y);
                last.yMax = Math.max(last.yMax, item.y + (item.height || 10));
                last.height = Math.max(last.height, item.height || 10);
            } else {
                lines.push({
                    items: [item],
                    xMin: item.x,
                    xMax: item.x + (item.width || 0),
                    yMin: item.y,
                    yMax: item.y + (item.height || 10),
                    y: item.y,
                    height: item.height || 10
                });
            }
        }
        return lines;
    }

    // ── Helper: merge lines into blocks within a single column ────────
    function mergeIntoBlocks(lines) {
        lines.sort((a, b) => Math.abs(b.y - a.y) < 2 ? a.xMin - b.xMin : b.y - a.y);
        const blocks = [];
        for (const line of lines) {
            let assigned = false;
            for (let i = blocks.length - 1; i >= 0; i--) {
                const block = blocks[i];
                const vertGap = block.yMin - line.yMax;
                const yOverlap = Math.max(0, Math.min(block.yMax, line.yMax) - Math.max(block.yMin, line.yMin));
                if (yOverlap > 0 || (vertGap >= -line.height * 0.5 && vertGap < line.height * 2.5)) {
                    const horizOverlap = Math.max(0, Math.min(block.xMax, line.xMax) - Math.max(block.xMin, line.xMin));
                    const minWidth = Math.min(block.xMax - block.xMin, line.xMax - line.xMin);
                    if (horizOverlap > minWidth * 0.3 || (Math.abs(line.xMin - block.xMin) < 20 && Math.abs(line.xMax - block.xMax) < 20)) {
                        block.lines.push(line);
                        block.items.push(...line.items);
                        block.xMin = Math.min(block.xMin, line.xMin);
                        block.xMax = Math.max(block.xMax, line.xMax);
                        block.yMin = Math.min(block.yMin, line.yMin);
                        block.yMax = Math.max(block.yMax, line.yMax);
                        assigned = true;
                        break;
                    }
                }
            }
            if (!assigned) {
                blocks.push({
                    lines: [line],
                    items: [...line.items],
                    xMin: line.xMin,
                    xMax: line.xMax,
                    yMin: line.yMin,
                    yMax: line.yMax
                });
            }
        }
        return blocks;
    }

    // ── Helper: process single-column layout ─────────────────────────
    function processSingleColumn(items) {
        const lines = groupIntoLines(items);
        const blocks = mergeIntoBlocks(lines);
        
        const formattedBlocks = blocks.map(block => ({
            type: 'Single-Column',
            xMin: block.xMin,
            xMax: block.xMax,
            yMin: block.yMin,
            yMax: block.yMax,
            items: block.items
        }));

        const sortedBlocks = window.topologicalSort(formattedBlocks);

        return sortedBlocks.map(block => ({
            type: 'Single-Column',
            bbox: { xMin: block.xMin, xMax: block.xMax, yMin: block.yMin, yMax: block.yMax },
            items: block.items
        }));
    }

    function processComplexGrid(items) {
        function recursiveXYCut(items, depth = 0) {
            if (depth > 10 || items.length < 5) return [{ items }];

            const validItems = items.filter(it => !it.garbage && it.str && it.str.trim().length > 0 && (it.width || 0) >= 2 && (it.height || 0) >= 2);
            if (validItems.length === 0) return [{ items }];

            const xes = validItems.map(it => it.x + (it.width || 0));
            const bXMin = Math.min(...validItems.map(it => it.x));
            const bXMax = xes.length ? Math.max(...xes) : 0;
            const bW = bXMax - bXMin;

            const heights = validItems.map(it => it.height || 10).sort((a, b) => a - b);
            const medianH = heights.length > 0 ? heights[Math.floor(heights.length / 2)] : 10;
            const bXMid = bXMin + bW / 2;

            let structItems = validItems.filter(it => {
                const w = it.width || 0;
                const h = it.height || 10;
                const spansMiddle = (it.x <= bXMid - 10) && ((it.x + w) >= bXMid + 10);
                return w < bW * 0.9 && h <= medianH * 1.5 && !spansMiddle;
            });
            if (structItems.length === 0) structItems = validItems;

            const xIntervals = structItems.map(it => [it.x, it.x + (it.width || 0)]);
            const yIntervals = structItems.map(it => [it.y, it.y + (it.height || 10)]);

            function mergeIntervals(intervals, tol) {
                if (intervals.length === 0) return [];
                intervals.sort((a, b) => a[0] - b[0]);
                const merged = [[intervals[0][0], intervals[0][1]]];
                for (let i = 1; i < intervals.length; i++) {
                    const last = merged[merged.length - 1];
                    if (intervals[i][0] <= last[1] + tol) {
                        last[1] = Math.max(last[1], intervals[i][1]);
                    } else {
                        merged.push([intervals[i][0], intervals[i][1]]);
                    }
                }
                return merged;
            }

            const mergedX = mergeIntervals(xIntervals, 2);
            const mergedY = mergeIntervals(yIntervals, 2);

            const xGaps = [];
            for (let i = 0; i < mergedX.length - 1; i++) {
                xGaps.push({ start: mergedX[i][1], end: mergedX[i+1][0], size: mergedX[i+1][0] - mergedX[i][1] });
            }
            const yGaps = [];
            for (let i = 0; i < mergedY.length - 1; i++) {
                yGaps.push({ start: mergedY[i][1], end: mergedY[i+1][0], size: mergedY[i+1][0] - mergedY[i][1] });
            }

            let bestX = null;
            if (xGaps.length > 0) {
                bestX = xGaps.reduce((best, g) => {
                    let score = g.size;
                    if (bW > 300) {
                        const gapCenter = (g.start + g.end) / 2;
                        const distToMid = Math.abs(gapCenter - bXMid);
                        score = g.size * Math.pow(1 - Math.min(distToMid / (bW / 2), 1), 2);
                    }
                    g.score = score;
                    return (!best || g.score > best.score) ? g : best;
                }, null);
            }

            const bestY = yGaps.length > 0 ? yGaps.reduce((max, g) => g.size > max.size ? g : max, yGaps[0]) : null;

            const MIN_X_GAP = 5;
            const MIN_Y_GAP = 4;

            let cutAxis = null;
            let cutVal = null;

            if (bestX && (!bestY || bestX.size > bestY.size) && bestX.size >= MIN_X_GAP) {
                cutAxis = 'X';
                cutVal = (bestX.start + bestX.end) / 2;
            } else if (bestY && bestY.size >= MIN_Y_GAP) {
                cutAxis = 'Y';
                cutVal = (bestY.start + bestY.end) / 2;
            } else if (bestX && bestX.size >= MIN_X_GAP) {
                cutAxis = 'X';
                cutVal = (bestX.start + bestX.end) / 2;
            }

            if (!cutAxis) {
                console.log(`[XYCut] Depth ${depth}: bW=${bW}, structItems=${structItems.length}, bestX=${bestX ? bestX.size : 'none'}, bestY=${bestY ? bestY.size : 'none'} -> NO CUT`);
                return [{ items }];
            }

            console.log(`[XYCut] Depth ${depth}: CutAxis=${cutAxis}, CutVal=${cutVal}, bW=${bW}, bestX=${bestX ? bestX.size : 'none'}, bestY=${bestY ? bestY.size : 'none'}`);

            const group1 = [];
            const group2 = [];
            const spanning = [];

            if (cutAxis === 'X') {
                for (const item of items) {
                    const itemW = item.width || 0;
                    if (itemW > bW * 0.55 && item.x < cutVal && (item.x + itemW) > cutVal) {
                        spanning.push(item);
                    } else {
                        const center = item.x + itemW / 2;
                        if (center < cutVal) group1.push(item);
                        else group2.push(item);
                    }
                }
            } else {
                for (const item of items) {
                    const center = item.y + (item.height || 10) / 2;
                    if (center > cutVal) group1.push(item); 
                    else group2.push(item);
                }
            }

            if (group1.length === 0 || group2.length === 0) return [{ items }];

            let r1 = recursiveXYCut(group1, depth + 1);
            let r2 = recursiveXYCut(group2, depth + 1);
            let rs = spanning.length > 0 ? recursiveXYCut(spanning, depth + 1) : [];

            return [...r1, ...r2, ...rs];
        }

        const blocks = recursiveXYCut(items);
        const formattedBlocks = blocks.map(block => {
            const blockXMin = Math.min(...block.items.map(it => it.x));
            const blockXMax = Math.max(...block.items.map(it => it.x + (it.width || 0)));
            const blockYMin = Math.min(...block.items.map(it => it.y));
            const blockYMax = Math.max(...block.items.map(it => it.y + (it.height || 10)));
            
            return {
                type: 'Single-Column',
                xMin: blockXMin, xMax: blockXMax, yMin: blockYMin, yMax: blockYMax,
                bbox: { xMin: blockXMin, xMax: blockXMax, yMin: blockYMin, yMax: blockYMax },
                items: block.items
            };
        });

        const sortedBlocks = window.topologicalSort(formattedBlocks);
        
        console.log(`[Layout Engine] Sorted ${sortedBlocks.length} blocks:`);
        for (let i = 0; i < sortedBlocks.length; i++) {
            const b = sortedBlocks[i];
            console.log(`  Block ${i}: x=[${Math.round(b.bbox.xMin)}, ${Math.round(b.bbox.xMax)}] y=[${Math.round(b.bbox.yMin)}, ${Math.round(b.bbox.yMax)}] items=${b.items.length} preview: ${b.items.slice(0,2).map(it=>it.str).join(' ')}`);
        }

        return sortedBlocks.map(block => ({
            type: 'Single-Column',
            bbox: block.bbox,
            items: block.items
        }));
    }

    // ── Helper: process landscape layout ─────────────────────────────
    function processLandscape(items) {
        const lines = groupIntoLines(items);
        const blocks = mergeIntoBlocks(lines);

        const formattedBlocks = blocks.map(block => ({
            type: 'Single-Column',
            xMin: block.xMin,
            xMax: block.xMax,
            yMin: block.yMin,
            yMax: block.yMax,
            items: block.items
        }));

        const sortedBlocks = window.topologicalSort(formattedBlocks);

        return sortedBlocks.map(block => ({
            type: 'Single-Column',
            bbox: { xMin: block.xMin, xMax: block.xMax, yMin: block.yMin, yMax: block.yMax },
            items: block.items
        }));
    }

    // ── Helper: process multi-column layout ──────────────────────────
    function processMultiColumn(items, gutterX) {
        const leftItems = [];
        const rightItems = [];
        const wideItems = [];

        for (const item of items) {
            const itemLeft = item.x;
            const itemRight = item.x + (item.width || 0);
            const itemCenter = (itemLeft + itemRight) / 2;
            const itemWidth = itemRight - itemLeft;

            let crossesGutter = false;
            if (itemWidth > pageW * 0.55) {
                crossesGutter = true;
            } else if (itemLeft < gutterX - 2 && itemRight > gutterX + 2) {
                crossesGutter = true;
            }

            if (crossesGutter) {
                wideItems.push(item);
            } else if (itemCenter < gutterX) {
                leftItems.push(item);
            } else {
                rightItems.push(item);
            }
        }

        const leftBlocks = processSingleColumn(leftItems);
        const rightBlocks = processSingleColumn(rightItems);
        const wideBlocks = processSingleColumn(wideItems);

        const allBlocks = [...leftBlocks, ...rightBlocks, ...wideBlocks];
        const sortedBlocks = window.topologicalSort(allBlocks);
        return sortedBlocks;
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 1: Classify page layout
    // ═══════════════════════════════════════════════════════════════════
    let layoutType = 'Single-Column';
    let gutters = [];
    let gutterX = -1;

    if (boxItems.length >= 5) {
        if (pageW > pageH * 1.05) {
            layoutType = 'Landscape/Presentation';
        } else {
            gutters = findVerticalGutters(boxItems);
            if (gutters.length > 1) {
                layoutType = 'Complex/Mixed-Grid';
            } else if (gutters.length === 1) {
                layoutType = 'Multi-Column';
                gutterX = gutters[0].x;
            } else {
                layoutType = 'Single-Column';
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 1.5: Identify "ARTICLE INFORMATION" or "REFERENCES" headers
    // and extract everything below them to the end of the page.
    // ═══════════════════════════════════════════════════════════════════
    let refYThreshold = -1;
    const tempLines = groupIntoLines([...boxItems], false);
    for (const line of tempLines) {
        const text = line.items.map(it => it.str).join('').replace(/\s+/g, ' ').trim().toUpperCase();
        if (text === 'ARTICLE INFORMATION' || text === 'REFERENCES') {
            refYThreshold = line.yMax + 5;
            break;
        }
    }

    let mainItems = boxItems;
    let refItems = [];
    if (refYThreshold !== -1) {
        mainItems = [];
        for (const item of boxItems) {
            if (item.y <= refYThreshold) {
                refItems.push(item);
            } else {
                mainItems.push(item);
            }
        }
    }

    // ═══════════════════════════════════════════════════════════════════
    // STEP 2: Route to specialized layout processors
    // ═══════════════════════════════════════════════════════════════════
    console.log(`[Layout Engine] Page size: ${Math.round(pageW)}x${Math.round(pageH)}, Classified: ${layoutType}, Gutters: ${gutters.map(g => Math.round(g.x)).join(', ')}`);

    let blocks;
    if (layoutType === 'Landscape/Presentation') {
        blocks = processLandscape(mainItems);
    } else if (layoutType === 'Multi-Column') {
        blocks = processMultiColumn(mainItems, gutterX);
    } else if (layoutType === 'Complex/Mixed-Grid') {
        blocks = processComplexGrid(mainItems);
    } else {
        blocks = processSingleColumn(mainItems);
    }

    if (refItems.length > 0) {
        let refBlocks;
        if (layoutType === 'Landscape/Presentation') {
            refBlocks = processLandscape(refItems);
        } else if (layoutType === 'Multi-Column') {
            refBlocks = processMultiColumn(refItems, gutterX);
        } else if (layoutType === 'Complex/Mixed-Grid') {
            refBlocks = processComplexGrid(refItems);
        } else {
            refBlocks = processSingleColumn(refItems);
        }
        blocks = blocks.concat(refBlocks);
    }

    return blocks;
}

window.executePdfConversion = async function (files) {
    showProgressState(true);
    if (navigator.webdriver) {
        state.autoResolveEnabled = true;
    }
    state.isSkippingFile = false; // Reset skip state
    state.processedData = [];
    state.pendingOcrTexts = state.pendingOcrTexts || {};
    let canceledFiles = 0;
    const ocrPromises = [];

    const checkSkip = () => { if (state.isSkippingFile) throw new Error('SKIP_FILE'); };

    // RTL script detection — Arabic, Hebrew, Syriac, Thaana, etc.
    function containsRTL(str) {
        const rtlRegex = /[\u0590-\u05FF\u0600-\u06FF\u0700-\u074F\u0750-\u077F\u08A0-\u08FF\uFB00-\uFDFF\uFE70-\uFEFF]/g;
        const matches = str.match(rtlRegex);
        if (!matches) return false;
        const chars = str.replace(/\s+/g, '');
        return chars.length > 0 && (matches.length / chars.length) > 0.5;
    }

    fileLoop: for (let fIndex = 0; fIndex < files.length; fIndex++) {
        if (state.isSkippingFile) {
            state.isSkippingFile = false; // Reset for next file in batch
        }
        const file = files[fIndex];
        const baseProgress = (fIndex / files.length) * 100;
        const fileProgressShare = 100 / files.length;

        logToTerminal(`[File ${fIndex + 1}/${files.length}] Initializing: ${file.name}`);
        updateProgress(baseProgress + 5, `Reading file ${fIndex + 1} of ${files.length}...`, file.name);

        try {
            checkSkip();
            const arrayBuffer = await file.arrayBuffer();
            checkSkip();
            const originalBuffer = arrayBuffer.slice ? arrayBuffer.slice(0) : new Uint8Array(arrayBuffer).slice().buffer;

            // Enhanced PDF loading with comprehensive format support options
            const loadingOptions = {
                data: arrayBuffer,
                useWorkerFetch: false,
                isEvalSupported: false,
                disableFontFace: false,
                fontExtraProperties: true,
                useSystemFonts: true,
                stopAtErrors: false,
                maxImageSize: 10737418240, // 10GB max image size
                password: file.password || undefined,
                ...(navigator.webdriver ? { onPassword: () => { throw new Error('PasswordException'); } } : {}),
                isOffscreenCanvasSupported: true,
                // CJK support: set window.PDFJS_CMAP_URL to your cmaps/ folder to enable CJK PDFs
                ...(window.PDFJS_CMAP_URL ? { cMapUrl: window.PDFJS_CMAP_URL, cMapPacked: true } : {}),
                // Better font fallback: set window.PDFJS_STANDARD_FONT_URL to your standard_fonts/ folder
                ...(window.PDFJS_STANDARD_FONT_URL ? { standardFontDataUrl: window.PDFJS_STANDARD_FONT_URL } : {}),
            };

            let pdf;
            if (!navigator.webdriver && window.__litedocAddons && typeof window.__litedocAddons.loadPdfWithPassword === 'function') {
                pdf = await window.__litedocAddons.loadPdfWithPassword(arrayBuffer, file.name, file.password);
            } else {
                try {
                    pdf = await pdfjsLib.getDocument(loadingOptions).promise;
                } catch (initialErr) {
                    const errName = initialErr && (initialErr.name || initialErr.constructor && initialErr.constructor.name);
                    const isPwd = errName === 'PasswordException' || /password/i.test(initialErr && initialErr.message || '');
                    if (isPwd) throw initialErr;

                    // Fallback to basic options if enhanced options fail
                    logToTerminal(`Enhanced loading failed, trying basic options...`, 'warn');
                    const basicOptions = {
                        data: originalBuffer.slice(0),
                        password: file.password || undefined,
                        ...(navigator.webdriver ? { onPassword: () => { throw new Error('PasswordException'); } } : {}),
                        stopAtErrors: false
                    };
                    pdf = await pdfjsLib.getDocument(basicOptions).promise;
                }
            }

            // If it was already an object {pdf, password} (from addons.loadPdfWithPassword)
            const pdfDoc = pdf.pdf ? pdf.pdf : pdf;
            const pdfPassword = pdf.password ? pdf.password : file.password;

            logToTerminal(`Recognized. Pages: ${pdfDoc.numPages}`);
            if (pdfDoc.numPages > 80) logToTerminal(`Large document (${pdfDoc.numPages} pages). Please wait…`, 'warn');

            // Language Auto-Detect (OSD Router)
            let docOcrLang = 'eng';
            if (window.__litedocAddons && window.__litedocAddons.ocrEnabled() && window.__litedocAddons._settings.ocrLang === 'auto') {
                try {
                    logToTerminal(`Detecting document language (OSD Router)…`);
                    const pg1 = await pdfDoc.getPage(1);
                    const vp = pg1.getViewport({ scale: 1.5 });
                    const canv = document.createElement('canvas');
                    canv.width = vp.width; canv.height = vp.height;
                    const ctx = canv.getContext('2d');
                    await pg1.render({ canvasContext: ctx, viewport: vp }).promise;

                    if (window.__litedocOCR && window.__litedocOCR.detectScript) {
                        docOcrLang = await window.__litedocOCR.detectScript(canv);
                        logToTerminal(`OSD Detected: <strong style="color:var(--accent)">${docOcrLang}</strong> script. Routing to specific worker.`, 'success');
                    }
                    pg1.cleanup();
                } catch (osdErr) {
                    logToTerminal(`OSD Detection failed, falling back to eng`, 'warn');
                    docOcrLang = 'eng';
                }
            } else {
                docOcrLang = (window.__litedocAddons && window.__litedocAddons._settings.ocrLang) || 'eng';
            }

            // pass 1: fingerprint
            let allRawLineTexts = [];
            if (pdfDoc.numPages >= 3) {
                const samplePages = Math.min(pdfDoc.numPages, 12);
                for (let pn = 1; pn <= samplePages; pn++) {
                    const pg = await pdfDoc.getPage(pn);
                    const tc = await pg.getTextContent();
                    // rough lines
                    const lines = [];
                    let cur = null;
                    for (const item of tc.items) {
                        const y = Math.round(item.transform[5]);
                        if (cur === null || Math.abs(y - cur.y) > 4) {
                            if (cur) lines.push(cur.str.trim());
                            cur = { y, str: item.str };
                        } else {
                            cur.str += item.str;
                        }
                    }
                    if (cur) lines.push(cur.str.trim());
                    allRawLineTexts.push(...lines);
                    pg.cleanup();
                }
            }
            const repeatingFPs = buildFingerprintSet(allRawLineTexts, pdfDoc.numPages);
            if (repeatingFPs.size > 0) {
                logToTerminal(`Dedup: found ${repeatingFPs.size} repeating header/footer fingerprint(s).`);
            }

            let mdText = `\x3C!-- Converted from ${file.name} — ${pdfDoc.numPages} pages --\x3E\n\n`;
            const extractedImages = [];
            const pageInlineRenders = {};

            const sharedCanvas = document.createElement('canvas');
            const sharedCtx = sharedCanvas.getContext('2d', { willReadFrequently: true });
            const tempCanvas = document.createElement('canvas');
            const tempCtx = tempCanvas.getContext('2d', { willReadFrequently: true });

            // pre-scan
            let fontMode = null; // state
            {
                const scanPages = Math.min(pdfDoc.numPages, 3);
                let foundCorruption = false;
                for (let sp = 1; sp <= scanPages && !foundCorruption; sp++) {
                    const spg = await pdfDoc.getPage(sp);
                    const stc = await spg.getTextContent({ includeMarkedContent: false });
                    const cf = detectCorruptedFonts(stc.items);
                    if (cf.size > 0) foundCorruption = true;
                    spg.cleanup();
                }
                if (foundCorruption) {
                    if (state.autoResolveEnabled) {
                        // auto-resolve
                        fontMode = state.autoResolveAction;
                        logToTerminal(`Auto-resolve: applying "${fontMode}" to ${file.name}.`, 'warn');
                    } else {
                        updateProgress(baseProgress + 8, 'Custom fonts detected…', 'Waiting for your call…');

                        logToTerminal(`Custom-encoded fonts found in ${file.name} — showing options.`, 'warn');
                        const queuePos = files.length > 1 ? `file ${fIndex + 1} of ${files.length}` : '';
                        fontMode = await showFontAlert(file.name, queuePos);
                    }
                    if (fontMode === 'cancel') {
                        logToTerminal(`User cancelled entire batch.`, 'warn');
                        canceledFiles = files.length - fIndex; // cancel rest
                        break fileLoop; // exit
                    }
                    if (fontMode === 'skip') {
                        logToTerminal(`Skipped: ${file.name}`, 'warn');
                        canceledFiles++;
                        continue; // skip
                    }
                    logToTerminal(`Font mode chosen: "${fontMode}" for ${file.name} — proceeding.`);
                }
            }

            // pass 2: extract
            const CHUNK_SIZE = 10;

            const processChunk = async (startPage, endPage) => {
                for (let pageNum = startPage; pageNum <= endPage; pageNum++) {
                    if (state.isSkippingFile) throw new Error('SKIP_FILE');
                    await new Promise(r => setTimeout(r, 0)); // yield

                    try {
                        const localProgress = (pageNum / pdfDoc.numPages) * fileProgressShare * 0.85;
                        updateProgress(
                            baseProgress + 10 + localProgress,
                            `Extracting content…`,
                            `${file.name} — Page ${pageNum}/${pdfDoc.numPages}`
                        );

                    const page = await pdfDoc.getPage(pageNum);
                    checkSkip();
                    const textContent = await page.getTextContent({ includeMarkedContent: false });
                    checkSkip();
                    const viewport = page.getViewport({ scale: 1 });

                    // Use raw PDF coordinate space (pre-rotation) for text position math.
                    // viewport.width/height are post-rotation; page.view gives the actual
                    // coordinate ranges that text transforms (transform[4]/[5]) live in.
                    const [_vx0, _vy0, _vx1, _vy1] = page.view;
                    const pageW = _vx1 - _vx0;
                    const pageH = _vy1 - _vy0;

                    // font check
                    const corruptedFonts = detectCorruptedFonts(textContent.items);
                    const pageHasCorruption = corruptedFonts.size > 0;
                    if (pageHasCorruption) {
                        logToTerminal(`Page ${pageNum}: ${corruptedFonts.size} corrupted font(s).`, 'warn');
                    }

                    // full render mode
                    if (fontMode === 'render' && pageHasCorruption) {
                        const SCALE = state.selectedImgRes === 0 ? 1.0 : (state.selectedImgRes === 1 ? 1.5 : 2.0);
                        const vp2 = page.getViewport({ scale: SCALE });
                        const pgC = document.createElement('canvas');
                        pgC.width = Math.round(vp2.width);
                        pgC.height = Math.round(vp2.height);
                        const ctx2 = pgC.getContext('2d');
                        ctx2.fillStyle = '#ffffff';
                        ctx2.fillRect(0, 0, pgC.width, pgC.height);
                        await page.render({ canvasContext: ctx2, viewport: vp2 }).promise;
                        const token = `RENDER_${pageNum}_FULL`;
                        const quality = state.selectedImgRes === 0 ? 0.82 : (state.selectedImgRes === 1 ? 0.91 : 0.97);
                        const dataUrl = pgC.toDataURL('image/jpeg', quality);
                        pageInlineRenders[token] = dataUrl;
                        extractedImages.push({ name: `${file.name}_p${pageNum}_rendered.jpg`, dataUrl: dataUrl, dims: `${pgC.width}×${pgC.height}` });
                        mdText += (pageNum > 1 ? '\n\n---\n\n' : '') + `## Page ${pageNum}\n\n[INLINE_RENDER: ${token}]`;
                        pgC.width = 0; pgC.height = 0;
                        page.cleanup();
                        continue;
                    }

                    // gibberish mode
                    const effectiveCorruptedFonts = (fontMode === 'gibberish') ? new Set() : corruptedFonts;

                    // enrich items
                    const items = textContent.items
                        .filter(item => item.str && item.str.length > 0)
                        .map(item => {
                            // transform matrix
                            const [a, b, , , e, f] = item.transform;
                            const fontSize = Math.round(Math.sqrt(a * a + b * b) * 10) / 10;
                            const width = item.width || Math.abs(a) * item.str.length * 0.55;
                            const isBold = (item.fontName || '').toLowerCase().includes('bold');
                            const fontName = item.fontName || '__unknown__';
                            const score = itemGibberishScore(item.str, fontName, effectiveCorruptedFonts);
                            const isMarginNoise = f > pageH * 0.96 || f < pageH * 0.06 || e < pageW * 0.04 || e > pageW * 0.96;
                            return {
                                str: item.str,
                                x: e,
                                y: f,
                                width,
                                height: item.height || Math.abs(a) || 12,
                                fontSize,
                                isBold,
                                fontName,
                                garbage: score > 0.20 || isMarginNoise,
                                gScore: score,
                            };
                        });

                    if (!items.length) {
                        // Scale render viewport: Tesseract performs best around 300 DPI, but PDF coordinates default to 72 DPI.
                        const SCALE = state.selectedImgRes === 0 ? 3.0 : (state.selectedImgRes === 1 ? 3.8 : 4.5);
                        const vp2 = page.getViewport({ scale: SCALE });
                        const pgC = document.createElement('canvas');
                        pgC.width = Math.round(vp2.width);
                        pgC.height = Math.round(vp2.height);
                        const ctx2 = pgC.getContext('2d');
                        ctx2.fillStyle = '#ffffff';
                        ctx2.fillRect(0, 0, pgC.width, pgC.height);
                        checkSkip();
                        await page.render({ canvasContext: ctx2, viewport: vp2 }).promise;
                        checkSkip();
                        if (window.__litedocAddons && window.__litedocAddons.ocrEnabled()) {
                            logToTerminal(`Page ${pageNum}: no text layer — queued for Background OCR.`, 'warn');

                            const placeholder = `[OCR_PENDING_PAGE_${pageNum}_${Math.random().toString(36).substr(2, 5)}]`;
                            mdText += (pageNum > 1 ? '\n\n---\n\n' : '') + `## Page ${pageNum}\n\n${placeholder}\n`;

                            ocrPromises.push((async (currentLang) => {
                                try {
                                    const resultText = await window.__litedocAddons.ocrCanvas(pgC, null, { ocrEnabled: true, ocrLang: currentLang });
                                    const finalResult = resultText.trim().length > 10 ? resultText.trim() : `[IMAGE_FALLBACK: Page ${pageNum}]`;

                                    const dataBlock = state.processedData.find(d => d.filename === file.name);
                                    if (dataBlock) {
                                        dataBlock.mdText = dataBlock.mdText.replace(placeholder, finalResult);

                                        if (state.activeDataIndex !== null && state.processedData[state.activeDataIndex].filename === file.name) {
                                            if (window.mdEditor && !state.hasUnsavedChanges) {
                                                const session = window.mdEditor.getSession();
                                                const scrollTop = session.getScrollTop();
                                                const cursor = window.mdEditor.getCursorPosition();
                                                window.isSyncingAce = true;
                                                window.mdEditor.setValue(dataBlock.mdText, -1);
                                                window.mdEditor.clearSelection();
                                                window.mdEditor.moveCursorToPosition(cursor);
                                                session.setScrollTop(scrollTop);
                                                window.isSyncingAce = false;
                                            }
                                            if (state.currentViewType === 'md') {
                                                const renderedEl = document.getElementById('viewer-md-rendered');
                                                const scroll = renderedEl ? renderedEl.scrollTop : 0;
                                                window.renderMarkdown(dataBlock.mdText);
                                                if (renderedEl) setTimeout(() => { renderedEl.scrollTop = scroll; }, 50);

                                                if (state.currentViewMode === 'raw' && !state.isEditing) {
                                                    const rawEl = document.getElementById('viewer-md-container');
                                                    if (rawEl) rawEl.textContent = dataBlock.mdText;
                                                }
                                            }
                                        }
                                    } else {
                                        state.pendingOcrTexts[placeholder] = finalResult;
                                    }
                                    logToTerminal(`Background OCR complete for ${file.name} (Page ${pageNum}).`);
                                } catch (e) {
                                    logToTerminal(`Background OCR failed for ${file.name} (Page ${pageNum}): ${e.message}`, 'error');
                                }
                            })(docOcrLang));

                        } else {
                            logToTerminal(`Page ${pageNum}: no text layer, rendering as image.`, 'warn');
                            const token = `RENDER_${pageNum}_FULL`;
                            const quality = state.selectedImgRes === 0 ? 0.80 : (state.selectedImgRes === 1 ? 0.90 : 0.97);
                            pageInlineRenders[token] = pgC.toDataURL('image/jpeg', quality);
                            mdText += (pageNum > 1 ? '\n\n---\n\n' : '') + `## Page ${pageNum}\n\n[INLINE_RENDER: ${token}]`;
                        }
                        page.cleanup();
                        continue;
                    }


function groupItemsIntoLines(itemList) {
                        itemList.sort((a, b) => Math.abs(b.y - a.y) < 2 ? a.x - b.x : b.y - a.y);
                        const lines = [];
                        for (const item of itemList) {
                            const last = lines[lines.length - 1];
                            const tol = Math.max(3, (item.height || 10) * 0.45);

                            let isSameLine = false;
                            if (last) {
                                const gap = item.x - last.xMax;
                                // Keep a tight merging threshold so columns don't bleed into each other.
                                const maxLineGap = (item.height || 10) * 1.5;
                                const yDiff = Math.abs(item.y - last.y);
                                if (gap >= -5 && gap < maxLineGap && yDiff <= Math.max(3, (item.height || 10) * 0.8)) {
                                    isSameLine = true;
                                } else if (item.y < last.y && yDiff > 2 && yDiff < 15 && item.height < last.height * 0.95 && /^\d+$/.test(item.str.trim())) {
                                    // It's a superscript number!
                                    isSameLine = true;
                                    item.isSuperscript = true;
                                    item.isFootnoteNum = true;
                                }
                            }

                            if (isSameLine) {
                                last.items.push(item);
                                if (item.garbage) last.garbage = true;
                                last.xMax = Math.max(last.xMax, item.x + (item.width || 0));
                                last.yMin = Math.min(last.yMin, item.y);
                                last.yMax = Math.max(last.yMax, item.y + (item.height || 10));
                                if (item.isSuperscript) {
                                    last.str += ` [${item.str.trim()}]`;
                                } else if (item.x - (last.items[last.items.length - 2].x + (last.items[last.items.length - 2].width || 0)) > (item.height || 10) * 0.2) {
                                    last.str += ' ' + item.str;
                                } else {
                                    last.str += item.str;
                                }
                            } else {
                                lines.push({
                                    y: item.y, height: item.height || 10, fontSize: item.fontSize, isBold: item.isBold,
                                    items: [item], garbage: item.garbage, xMin: item.x, xMax: item.x + (item.width || 0),
                                    yMin: item.y, yMax: item.y + (item.height || 10),
                                    str: item.str
                                });
                            }
                        }
                        for (const lg of lines) {
                            const totalItems = lg.items.length;
                            const garbageItems = lg.items.filter(it => it.garbage).length;
                            if (totalItems > 0 && garbageItems / totalItems > 0.40) lg.garbage = true;

                            // Sort elements right-to-left if the line contains RTL text to preserve reading order.
                            const lineStr = lg.items.map(it => it.str).join('');
                            if (containsRTL(lineStr)) {
                                lg.items.sort((a, b) => b.x - a.x);
                            }

                            const rawNoSpace = lg.items.map(it => it.str).join('').trim();
                            const isRepeating = repeatingFPs.has(rawNoSpace);
                            const isPageNumber = /^\d+$/.test(rawNoSpace) || /^(Page\s*)?\d+(\s*of\s*\d+)?$/i.test(rawNoSpace) || /^(pg\.?\s*)?\d+$/i.test(rawNoSpace);
                            const isMargin = lg.y > pageH * 0.90 || lg.y < pageH * 0.10;
                            const isOpinionHeader = /^\s*(opinion|opinionviewpoint)\s*$/i.test(rawNoSpace);
                            
                            if ((isRepeating && isMargin) || (isPageNumber && isMargin) || isOpinionHeader) {
                                lg.garbage = true;
                                lg.items.forEach(it => it.garbage = true);
                            }

                            lg.text = containsRTL(lineStr) ? lg.items.filter(it => !it.garbage && !it.isFootnoteNum).map(it => it.str).join(' ') : joinLineItems(lg.items.filter(it => !it.garbage && !it.isFootnoteNum));
                            lg.rawText = containsRTL(lineStr) ? lg.items.filter(it => !it.isFootnoteNum).map(it => it.str).join(' ') : joinLineItems(lg.items.filter(it => !it.isFootnoteNum));
                        }
                        return lines;
                    }

                    function parseSingleColumn(bbox, regionItems) {
                        const lines = groupItemsIntoLines(regionItems);
                        lines.sort((a, b) => b.y - a.y || a.xMin - b.xMin);
                        lines.forEach(lg => lg.columnIndex = 0);
                        return lines;
                    }

                    const regions = [];

                    const remainingItems = [];
                    for (const item of items) {
                        remainingItems.push(item);
                    }

                    const textBlocks = segmentBox(remainingItems, pageW, pageH);

                    const allRegions = [...textBlocks];
                    for (const r of regions) {
                        let inserted = false;
                        for (let i = 0; i < allRegions.length; i++) {
                            if (Math.max(r.bbox.yMax, r.bbox.yMin) > Math.max(allRegions[i].bbox.yMax, allRegions[i].bbox.yMin)) {
                                allRegions.splice(i, 0, r);
                                inserted = true;
                                break;
                            }
                        }
                        if (!inserted) allRegions.push(r);
                    }

                    const allLineGroups = [];

                    // Block-level Fallback Context
                    let pageCanvas = null;
                    let pageCtx = null;
                    let pageCanvasCache = null;
                    const getPageCanvas = async () => {
                        if (pageCanvasCache) return pageCanvasCache;
                        const RENDER_SCALE = state.selectedImgRes === 0 ? 1.5 : (state.selectedImgRes === 1 ? 2.0 : 2.5);
                        const vp2 = page.getViewport({ scale: RENDER_SCALE });
                        pageCanvas = document.createElement('canvas');
                        pageCanvas.width = Math.round(vp2.width);
                        pageCanvas.height = Math.round(vp2.height);
                        pageCtx = pageCanvas.getContext('2d');
                        pageCtx.fillStyle = '#ffffff';
                        pageCtx.fillRect(0, 0, pageCanvas.width, pageCanvas.height);
                        await page.render({ canvasContext: pageCtx, viewport: vp2 }).promise;
                        pageCanvasCache = { cvs: pageCanvas, scale: RENDER_SCALE };
                        return pageCanvasCache;
                    };

                    let blockIdx = 0;
                    for (const region of allRegions) {
                        if (region.items.length === 0) continue;
                        blockIdx++;

                        try {
                            // 1. Hard Fallback Check: Corrupted Fonts / Garbage Ratio
                            const totalItems = region.items.length;
                            const corruptedItems = region.items.filter(it => it.gScore > 0.20).length;
                            const blockCorrupted = totalItems > 0 ? corruptedItems / totalItems : 0;

                            if (blockCorrupted > 0.40 && fontMode !== 'clean' && fontMode !== 'gibberish') {
                                throw new Error(`Corrupted ratio (${Math.round(blockCorrupted * 100)}%) exceeded 40% threshold`);
                            }

                            // 2. Isolated Mini-Parsers
                            logToTerminal(`Routing DLA Block: [Type: Single-Column]`, 'info');
                            const parsedLines = parseSingleColumn(region.bbox, region.items);
                            parsedLines.forEach(l => l.blockIdx = blockIdx);
                            allLineGroups.push(...parsedLines);
                        } catch (blockErr) {
                            logToTerminal(`DLA Block Error (Page ${pageNum}, Block ${blockIdx}): ${blockErr.message} -> OCR/Image Fallback.`, 'warn');

                            try {
                                const { cvs: pC, scale } = await getPageCanvas();
                                const PAD = 8 * scale;
                                const cropTop = Math.max(0, pageH - Math.max(region.bbox.yMax, region.bbox.yMin));
                                const cropBot = Math.min(pageH, pageH - Math.min(region.bbox.yMax, region.bbox.yMin));
                                const sx = Math.max(0, (region.bbox.xMin * scale) - PAD);
                                const sy = Math.max(0, (cropTop * scale) - PAD);
                                const sw = Math.min(pC.width - sx, ((region.bbox.xMax - region.bbox.xMin) * scale) + PAD * 2);
                                const sh = Math.min(pC.height - sy, ((cropBot - cropTop) * scale) + PAD * 2);

                                if (sw > 10 && sh > 10) {
                                    const cropC = document.createElement('canvas');
                                    cropC.width = Math.round(sw);
                                    cropC.height = Math.round(sh);
                                    const ccx = cropC.getContext('2d');
                                    ccx.fillStyle = '#ffffff';
                                    ccx.fillRect(0, 0, cropC.width, cropC.height);
                                    ccx.drawImage(pC, sx, sy, sw, sh, 0, 0, cropC.width, cropC.height);

                                    const token = `RENDER_${pageNum}_BLK${blockIdx}`;

                                    if (window.__litedocAddons && window.__litedocAddons.ocrEnabled()) {
                                        const placeholder = `[OCR_PENDING_PAGE_${pageNum}_BLK${blockIdx}]`;
                                        allLineGroups.push({ y: region.bbox.yMax, isTable: false, garbage: true, injectedMarkdown: placeholder, items: [], blockIdx });

                                        ocrPromises.push((async (currentLang, tk, cvsToOcr) => {
                                            try {
                                                const resultText = await window.__litedocAddons.ocrCanvas(cvsToOcr, null, { ocrEnabled: true, ocrLang: currentLang });
                                                const finalResult = resultText.trim().length > 0 ? resultText.trim() : `[IMAGE_FALLBACK: Page ${pageNum} Block ${blockIdx}]`;
                                                const db = state.processedData.find(d => d.filename === file.name);
                                                if (db) {
                                                    db.mdText = db.mdText.replace(placeholder, finalResult);
                                                    
                                                    if (state.activeDataIndex !== null && state.processedData[state.activeDataIndex].filename === file.name) {
                                                        if (window.mdEditor && !state.hasUnsavedChanges) {
                                                            const session = window.mdEditor.getSession();
                                                            const scrollTop = session.getScrollTop();
                                                            const cursor = window.mdEditor.getCursorPosition();
                                                            window.isSyncingAce = true;
                                                            window.mdEditor.setValue(db.mdText, -1);
                                                            window.mdEditor.clearSelection();
                                                            window.mdEditor.moveCursorToPosition(cursor);
                                                            session.setScrollTop(scrollTop);
                                                            window.isSyncingAce = false;
                                                        }
                                                        if (state.currentViewType === 'md') {
                                                            const renderedEl = document.getElementById('viewer-md-rendered');
                                                            const scroll = renderedEl ? renderedEl.scrollTop : 0;
                                                            window.renderMarkdown(db.mdText);
                                                            if (renderedEl) setTimeout(() => { renderedEl.scrollTop = scroll; }, 50);
                                                            
                                                            // Update the raw view if user is in raw read-mode
                                                            if (state.currentViewMode === 'raw' && !state.isEditing) {
                                                                const rawEl = document.getElementById('viewer-md-container');
                                                                if (rawEl) rawEl.textContent = db.mdText;
                                                            }
                                                        }
                                                    }
                                                } else {
                                                    state.pendingOcrTexts[placeholder] = finalResult;
                                                }
                                            } catch (e) { }
                                            finally { cvsToOcr.width = 0; cvsToOcr.height = 0; } // release after OCR
                                        })(docOcrLang, token, cropC));
                                    } else {
                                        const quality = state.selectedImgRes === 0 ? 0.82 : (state.selectedImgRes === 1 ? 0.91 : 0.97);
                                        const dataUrl = cropC.toDataURL('image/jpeg', quality);
                                        pageInlineRenders[token] = dataUrl;
                                        extractedImages.push({ name: `${file.name}_p${pageNum}_blk${blockIdx}.jpg`, dataUrl: dataUrl, dims: `${cropC.width}×${cropC.height}` });
                                        allLineGroups.push({ y: region.bbox.yMax, isTable: false, garbage: true, injectedMarkdown: `[INLINE_RENDER: ${token}]`, items: [], blockIdx });
                                        cropC.width = 0; cropC.height = 0; // release immediately after encoding
                                    }
                                }
                            } catch (fallbackErr) {
                                logToTerminal(`Block fallback failed: ${fallbackErr.message}`, 'error');
                            }
                        }
                    }
                    if (pageCanvas) { pageCanvas.width = 0; pageCanvas.height = 0; }
                    const lineGroups = allLineGroups;

                    const maxColIdx = Math.max(0, ...allLineGroups.map(lg => lg.columnIndex || 0));
                    const columnsArr = Array.from({ length: maxColIdx + 1 }, (_, i) => allLineGroups.filter(lg => lg.columnIndex === i));

                    // Addon enhancements: tables, vector graphics, math regions
                    let addonExtras = '';
                    if (window.__litedocAddons) {
                        try {
                            addonExtras = await window.__litedocAddons.enhancePage({
                                page, pdfjsLib, pageNum, pageW, pageH,
                                fileName: file.name,
                                lineGroups, columns: columnsArr,
                                lineGroups, leftLines: lineGroups, rightLines: [],
                                sharedCanvas, sharedCtx,
                                extractedImages,
                                logToTerminal,
                            });
                        } catch (e) {
                            logToTerminal(`Page ${pageNum}: addon enhancement failed (${e.message}).`, 'warn');
                        }
                    }

                    // median height
                    const heights = allLineGroups.map(l => l.height).filter(h => h > 0).sort((a, b) => a - b);
                    const medH = heights[Math.floor(heights.length / 2)] || 12;

                    // Adaptive inter-line gap: compute the modal (most common) line spacing
                    const _ngLines = allLineGroups.filter(l => !l.garbage && (l.text || l.rawText || '').trim());
                    _ngLines.sort((a, b) => b.y - a.y);
                    const _interGaps = [];
                    for (let gi = 1; gi < _ngLines.length; gi++) {
                        const g = _ngLines[gi - 1].y - _ngLines[gi].y;
                        if (g > 0 && g < medH * 5) _interGaps.push(Math.round(g * 10) / 10);
                    }
                    let modalGap = medH * 1.2; // fallback
                    if (_interGaps.length > 2) {
                        const bSize = Math.max(1, medH * 0.15);
                        const _bkts = {};
                        for (const g of _interGaps) {
                            const key = Math.round(g / bSize) * bSize;
                            _bkts[key] = (_bkts[key] || 0) + 1;
                        }
                        let bestBkt = modalGap, bestCnt = 0;
                        for (const [k, v] of Object.entries(_bkts)) {
                            if (v > bestCnt) { bestCnt = v; bestBkt = parseFloat(k); }
                        }
                        modalGap = bestBkt || medH * 1.2;
                    }

                    const hThresh = classifyHeadings(lineGroups);

                    // page garbage
                    // >60% garbage = image (exclude valid but consumed lines like tables)
                    const activeLines = lineGroups.filter(l => !l.isTable && !l.isMath && (l.rawText || '').trim().length > 0);
                    const totalLines = activeLines.length;
                    const garbageLines2 = activeLines.filter(l => l.garbage).length;
                    const pageGarbageRatio = totalLines > 0 ? garbageLines2 / totalLines : 0;

                    if (pageGarbageRatio > 0.60 && fontMode !== 'clean' && fontMode !== 'gibberish') {
                        logToTerminal(`Page ${pageNum}: ${Math.round(pageGarbageRatio * 100)}% garbage — rendering entire page as image.`, 'warn');
                        const SCALE = state.selectedImgRes === 0 ? 1.0 : (state.selectedImgRes === 1 ? 1.5 : 2.0);
                        const vp2 = page.getViewport({ scale: SCALE });
                        const pgC = document.createElement('canvas');
                        pgC.width = Math.round(vp2.width);
                        pgC.height = Math.round(vp2.height);
                        const ctx2 = pgC.getContext('2d');
                        ctx2.fillStyle = '#ffffff';
                        ctx2.fillRect(0, 0, pgC.width, pgC.height);
                        await page.render({ canvasContext: ctx2, viewport: vp2 }).promise;
                        const token = `RENDER_${pageNum}_FULL`;
                        const quality = state.selectedImgRes === 0 ? 0.82 : (state.selectedImgRes === 1 ? 0.91 : 0.97);
                        const dataUrl = pgC.toDataURL('image/jpeg', quality);
                        pageInlineRenders[token] = dataUrl;
                        extractedImages.push({ name: `${file.name}_p${pageNum}_rendered.jpg`, dataUrl: dataUrl, dims: `${pgC.width}×${pgC.height}` });
                        const pageMd = `## Page ${pageNum}\n\n[INLINE_RENDER: ${token}]`;
                        mdText += (pageNum > 1 ? '\n\n---\n\n' : '') + pageMd;
                        pgC.width = 0; pgC.height = 0;

                        // get imgs anyway
                        const ops2 = await page.getOperatorList();
                        let imgOpCount2 = 0;
                        for (let ii = 0; ii < ops2.fnArray.length; ii++) {
                            if (ops2.fnArray[ii] === pdfjsLib.OPS.paintImageXObject || ops2.fnArray[ii] === pdfjsLib.OPS.paintInlineImageXObject) {
                                imgOpCount2++;
                            }
                        }

                        if (imgOpCount2 > 60) {
                            logToTerminal(`Page ${pageNum}: skipped individual image extraction (${imgOpCount2} images detected). Likely graphical noise.`, 'info');
                        } else {
                            let imgIdx2 = 1;
                            const seen2 = new Set();
                            for (let ii = 0; ii < ops2.fnArray.length; ii++) {
                            if (ops2.fnArray[ii] === pdfjsLib.OPS.paintImageXObject) {
                                const ref2 = ops2.argsArray[ii][0];
                                if (seen2.has(ref2)) continue;
                                seen2.add(ref2);
                                try {
                                    const obj2 = await Promise.race([
                                        new Promise((res, rej) => {
                                            try { page.objs.get(ref2, o => o ? res(o) : rej(new Error('null'))); }
                                            catch (e) { rej(e); }
                                        }),
                                        new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 2000))
                                    ]);
                                    if (!obj2 || (!obj2.data && !obj2.bitmap)) continue;
                                    let w2 = obj2.width, h2 = obj2.height;
                                    if (!w2 || !h2 || w2 < 4 || h2 < 4) continue;
                                    sharedCanvas.width = w2; sharedCanvas.height = h2;
                                    if (obj2.bitmap) { sharedCtx.drawImage(obj2.bitmap, 0, 0, w2, h2); }
                                    else {
                                        const id2 = sharedCtx.createImageData(w2, h2);
                                        const src2 = obj2.data || [];
                                        const nc2 = obj2.numComponents || 4;
                                        let j2 = 0;
                                        if (nc2 === 1) {
                                            for (let k = 0; k < src2.length; k++) {
                                                id2.data[j2++] = src2[k]; id2.data[j2++] = src2[k];
                                                id2.data[j2++] = src2[k]; id2.data[j2++] = 255;
                                            }
                                        } else if (nc2 === 3) {
                                            for (let k = 0; k < src2.length; k += 3) {
                                                id2.data[j2++] = src2[k]; id2.data[j2++] = src2[k + 1];
                                                id2.data[j2++] = src2[k + 2]; id2.data[j2++] = 255;
                                            }
                                        } else if (nc2 === 4) {
                                            for (let k = 0; k < src2.length; k += 4) {
                                                const kk2 = src2[k + 3] / 255;
                                                id2.data[j2++] = Math.round(255 * (1 - src2[k] / 255) * (1 - kk2));
                                                id2.data[j2++] = Math.round(255 * (1 - src2[k + 1] / 255) * (1 - kk2));
                                                id2.data[j2++] = Math.round(255 * (1 - src2[k + 2] / 255) * (1 - kk2));
                                                id2.data[j2++] = 255;
                                            }
                                        } else {
                                            // DeviceN / Separation spot colors
                                            for (let k = 0; k < src2.length; k += nc2) {
                                                let sum2 = 0;
                                                for (let c = 0; c < nc2; c++) sum2 += src2[k + c];
                                                const gray2 = Math.round(255 - (sum2 / nc2));
                                                id2.data[j2++] = gray2; id2.data[j2++] = gray2;
                                                id2.data[j2++] = gray2; id2.data[j2++] = 255;
                                            }
                                        }
                                        tempCanvas.width = w2; tempCanvas.height = h2;
                                        tempCtx.putImageData(id2, 0, 0);
                                        sharedCtx.drawImage(tempCanvas, 0, 0, w2, h2);
                                    }
                                    const q2 = state.selectedImgRes === 0 ? 0.75 : (state.selectedImgRes === 1 ? 0.88 : 0.96);
                                    extractedImages.push({ name: `${file.name}_p${pageNum}_img${imgIdx2}.jpg`, dataUrl: sharedCanvas.toDataURL('image/jpeg', q2), dims: `${w2}×${h2}` });
                                    imgIdx2++;
                                } catch (e2) { /* ignore err */ }
                            }
                        }
                        }
                        page.cleanup();
                        continue;
                    }


                    // to md — Smart paragraph merging, hyphen unwrapping, blockquote & heading detection
                    function linesToMd(lines) {
                        const mdArr = [];
                        let prevY = null;
                        let paragraphBuf = '';


                        let prevLine = null;

                        // Dominant left margin for blockquote detection
                        const validLns = lines.filter(l => !l.garbage && (l.text || '').trim());
                        const lMargins = validLns.map(l => l.xMin).sort((a, b) => a - b);
                        const rMargins = validLns.map(l => l.xMax).sort((a, b) => b - a);
                        const domLeftMargin = lMargins.length > 2 ? lMargins[Math.floor(lMargins.length * 0.2)] : (lMargins.length > 0 ? lMargins[0] : 0);
                        const domRightMargin = rMargins.length > 2 ? rMargins[Math.floor(rMargins.length * 0.2)] : pageW;
                        const colW = domRightMargin > domLeftMargin ? (domRightMargin - domLeftMargin) : pageW;
                        const bqIndent = colW * 0.12;

                        const flushPara = () => {
                            if (paragraphBuf.trim()) {
                                mdArr.push(paragraphBuf.trim());
                                paragraphBuf = '';
                            }
                        };

                        for (let li = 0; li < lines.length; li++) {
                            const lg = lines[li];
                            // Recalculate text dynamically to exclude items consumed by tables/figures
                            const tempLineStr = lg.items.map(it => it.str).join('');
                            lg.text = containsRTL(tempLineStr) ? lg.items.filter(it => !it.garbage && !it.isFootnoteNum).map(it => it.str).join(' ') : joinLineItems(lg.items.filter(it => !it.garbage && !it.isFootnoteNum));
                            if (lg.items.length > 0 && lg.items.filter(it => it.garbage).length / lg.items.length > 0.40) lg.garbage = true;

                            const txt = lg.text.trim();
                            const fp = (lg.rawText || txt).trim();

                            // dedup
                            if (repeatingFPs.has(fp) || repeatingFPs.has(txt)) continue;

                            // Inject inline elements (tables, figures) right where they were found
                            if (lg.injectedMarkdown) {
                                flushPara();
                                mdArr.push(lg.injectedMarkdown);
                            }

                            if (lg.garbage && !lg.isTable) continue;
                            if (!txt) continue;

                            // List detection — flush paragraph buffer and emit list item
                            const bulletMatch = txt.match(/^([•*‑\-◦\u2022\u2023\u25E6\u2043\u2219])\s+(.*)/);
                            if (bulletMatch) {
                                flushPara();
                                mdArr.push(`- ${bulletMatch[2]}`);
                                prevY = lg.y;
                                prevLine = lg;
                                continue;
                            }

                            // Numbered list detection
                            const numMatch = txt.match(/^(\d{1,3}[\.)\]])\s+(.+)/);
                            if (numMatch && txt.length < 200) {
                                flushPara();
                                mdArr.push(`${numMatch[1]} ${numMatch[2]}`);
                                prevY = lg.y;
                                prevLine = lg;
                                continue;
                            }

                            // Blockquote: significantly indented from dominant left margin
                            let isIndented = validLns.length > 3 && (lg.xMin - domLeftMargin) > bqIndent;

                            // --- Heading detection ---
                            let level = headingLevel(lg.fontSize, hThresh, lg.isBold);
                            // Fix overly aggressive headings where p85/p95 equals median body text
                            if (level > 0 && lg.fontSize <= hThresh.median * 1.05 && !lg.isBold) level = 0;

                            // Bold-only heading: bold, short, preceded by gap, followed by non-bold body text
                            if (level === 0 && lg.isBold && txt.length < 80) {
                                const gapH = prevY !== null ? (prevY - lg.y) : modalGap * 2;
                                const nextBody = lines.slice(li + 1).find(l => {
                                    const t = joinLineItems(l.items.filter(it => !it.garbage)).trim();
                                    return t && !l.garbage;
                                });
                                if (gapH > modalGap * 1.3 && (!nextBody || !nextBody.isBold)) {
                                    level = 1;
                                }
                            }
                            
                            let fontBlockChars = txt.length;
                            let fontBlockLines = 1;
                            for (let j = li - 1; j >= 0; j--) {
                                if (!lines[j].garbage && (lines[j].text || '').trim()) {
                                    if (Math.abs(lines[j].fontSize - lg.fontSize) < 0.6) {
                                        fontBlockChars += (lines[j].text || '').length;
                                        fontBlockLines++;
                                    } else break;
                                }
                            }
                            for (let j = li + 1; j < lines.length; j++) {
                                if (!lines[j].garbage && (lines[j].text || '').trim()) {
                                    if (Math.abs(lines[j].fontSize - lg.fontSize) < 0.6) {
                                        fontBlockChars += (lines[j].text || '').length;
                                        fontBlockLines++;
                                    } else break;
                                }
                            }

                            // A blockquote/pull-quote should not be formatted as a heading
                            // We use fontBlockChars > 115 to avoid stripping heading status from multi-line titles.
                            // The title is ~89 chars, pull quote is ~136 chars.
                            if (level > 0 && fontBlockChars > 115) {
                                level = 0;
                                isIndented = true; // force blockquote
                            }

                            if (level > 0) {
                                flushPara();
                                const pfx = level === 3 ? '#' : level === 2 ? '##' : '###';
                                mdArr.push(`${pfx} ${txt}`);
                                prevY = lg.y;
                                prevLine = lg;
                                continue;
                            }

                            // --- Paragraph gap analysis ---
                            const gap = prevY !== null ? (prevY - lg.y) : 0;
                            const isParaBreak = prevY !== null && gap > modalGap * 1.8;

                            // Continuation: same font size, normal line spacing, not a break, and horizontally aligned
                            const isContinuation = prevLine && !isParaBreak &&
                                Math.abs(lg.fontSize - prevLine.fontSize) < 0.6 &&
                                gap > 0 && gap < modalGap * 1.6 &&
                                Math.abs(lg.xMin - prevLine.xMin) < pageW * 0.1; // Ensure they are in the same column

                            if (isParaBreak || !isContinuation) {
                                flushPara();
                                if (isParaBreak) mdArr.push('');
                            }

                            if (isContinuation && paragraphBuf) {
                                // Hyphen unwrapping: trailing hyphen + next line starts lowercase → join
                                if (paragraphBuf.endsWith('-') && /^[a-z]/.test(txt)) {
                                    paragraphBuf = paragraphBuf.slice(0, -1) + txt;
                                } else {
                                    paragraphBuf += ' ' + txt;
                                }
                            } else {
                            paragraphBuf = isIndented ? '> ' + txt : txt;
                            }

                            prevY = lg.y;
                            prevLine = lg;
                        }
                        flushPara();
                        return mdArr;
                    }

                    // Footnote extraction: separate footnote lines from body
                    const footnoteLines = [];
                    const bodyLineGroups = [];
                    for (const lg of allLineGroups) {
                        const fnText = (lg.text || lg.rawText || '').trim();
                        const isFootnote =
                            lg.y < pageH * 0.15 &&
                            lg.fontSize < medH * 0.85 &&
                            !lg.garbage &&
                            fnText.length > 0 &&
                            /^\d{1,2}[\.)\s]|^[*†‡§¶\u2020\u2021]/.test(fnText);
                        if (isFootnote) {
                            footnoteLines.push(lg);
                        } else {
                            bodyLineGroups.push(lg);
                        }
                    }

                    let pageMdLines = [];
                    const bodyBlocks = {};
                    for (const lg of bodyLineGroups) {
                        const idx = lg.blockIdx !== undefined ? lg.blockIdx : -1;
                        if (!bodyBlocks[idx]) bodyBlocks[idx] = [];
                        bodyBlocks[idx].push(lg);
                    }
                    const blockKeys = Object.keys(bodyBlocks).map(k => parseInt(k)).sort((a, b) => a - b);
                    for (const k of blockKeys) {
                        pageMdLines.push(...linesToMd(bodyBlocks[k]));
                    }

                    // Format footnotes
                    if (footnoteLines.length > 0) {
                        footnoteLines.sort((a, b) => b.y - a.y);
                        pageMdLines.push('');
                        pageMdLines.push('**Footnotes:**');
                        for (const fn of footnoteLines) {
                            const fnTxt = (fn.text || fn.rawText || '').trim();
                            if (fnTxt) pageMdLines.push(`- ${fnTxt}`);
                        }
                    }

                    // clean empty lines
                    const collapsed = pageMdLines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
                    const pageMdHeader = `## Page ${pageNum}`;
                    let pageMd = collapsed ? `${pageMdHeader}\n\n${collapsed}` : pageMdHeader;
        // Apply cleanup to remove stray blockquote markers and duplicate headings
        pageMd = cleanMarkdown(pageMd);
        // Remove hyphenated line breaks (e.g., 'reim-\n\n' => 'reim')
        pageMd = pageMd.replace(/-\s*\n\s*/g, '');

                    // images
                    if (fontMode !== 'clean') {
                        const ops = await page.getOperatorList();
                        
                        // Failsafe: if a page has thousands of microscopic images (e.g. Arabic characters rendered as bitmaps or a dotted pattern),
                        // extracting them toDataURL will OOM crash the browser. Skip if > 60.
                        let imgOpCount = 0;
                        for (let i = 0; i < ops.fnArray.length; i++) {
                            if (ops.fnArray[i] === pdfjsLib.OPS.paintImageXObject || ops.fnArray[i] === pdfjsLib.OPS.paintInlineImageXObject) {
                                imgOpCount++;
                            }
                        }

                        if (imgOpCount > 60) {
                            logToTerminal(`Page ${pageNum}: skipped individual image extraction (${imgOpCount} images detected). Likely graphical noise.`, 'info');
                        } else {
                            let imgIndex = 1;
                            const seenImgRefs = new Set();

                        for (let i = 0; i < ops.fnArray.length; i++) {
                            const isXObj   = ops.fnArray[i] === pdfjsLib.OPS.paintImageXObject;
                            const isInline = ops.fnArray[i] === pdfjsLib.OPS.paintInlineImageXObject;
                            if (!isXObj && !isInline) continue;

                            const imgRef = ops.argsArray[i][0];

                            // Inline images embed the ImageData directly in argsArray[i][0];
                            // XObjects are referenced by name and stored in page.objs.
                            if (isInline) {
                                // argsArray[i][0] IS the image object for inline images
                                try {
                                    const inlineObj = ops.argsArray[i][0];
                                    if (!inlineObj || (!inlineObj.data && !inlineObj.bitmap)) continue;
                                    let w = inlineObj.width, h = inlineObj.height;
                                    if (!w || !h || w < 4 || h < 4) continue;
                                    // (reuse the same canvas/quality logic below by falling through
                                    //  with imgObj = inlineObj — handled after this block)
                                    const seenKey = `inline_${i}`;
                                    if (seenImgRefs.has(seenKey)) continue;
                                    seenImgRefs.add(seenKey);
                                    // Inline images render at source resolution — respect the downscale cap
                                    if (state.selectedImgRes < 2) {
                                        const maxDim = state.selectedImgRes === 0 ? 600 : 1200;
                                        if (w > maxDim || h > maxDim) {
                                            const ratio = Math.min(maxDim / w, maxDim / h);
                                            w = Math.round(w * ratio);
                                            h = Math.round(h * ratio);
                                        }
                                    }
                                    sharedCanvas.width = w; sharedCanvas.height = h;
                                    if (inlineObj.bitmap) {
                                        sharedCtx.drawImage(inlineObj.bitmap, 0, 0, w, h);
                                    } else {
                                        const srcW = inlineObj.width, srcH = inlineObj.height;
                                        const imgData = sharedCtx.createImageData(srcW, srcH);
                                        const src = inlineObj.data;
                                        const nc = inlineObj.numComponents || 4;
                                        let j = 0;
                                        if (nc === 1) {
                                            for (let k = 0; k < src.length; k++) { imgData.data[j++]=src[k]; imgData.data[j++]=src[k]; imgData.data[j++]=src[k]; imgData.data[j++]=255; }
                                        } else if (nc === 3) {
                                            for (let k = 0; k < src.length; k += 3) { imgData.data[j++]=src[k]; imgData.data[j++]=src[k+1]; imgData.data[j++]=src[k+2]; imgData.data[j++]=255; }
                                        } else if (nc === 4) {
                                            for (let k = 0; k < src.length; k += 4) { const kk=src[k+3]/255; imgData.data[j++]=Math.round(255*(1-src[k]/255)*(1-kk)); imgData.data[j++]=Math.round(255*(1-src[k+1]/255)*(1-kk)); imgData.data[j++]=Math.round(255*(1-src[k+2]/255)*(1-kk)); imgData.data[j++]=255; }
                                        } else {
                                            for (let k = 0; k < src.length; k += nc) { let s=0; for(let c=0;c<nc;c++) s+=src[k+c]; const g=Math.round(255-s/nc); imgData.data[j++]=g; imgData.data[j++]=g; imgData.data[j++]=g; imgData.data[j++]=255; }
                                        }
                                        tempCanvas.width = srcW; tempCanvas.height = srcH;
                                        tempCtx.putImageData(imgData, 0, 0);
                                        sharedCtx.drawImage(tempCanvas, 0, 0, w, h);
                                    }
                                    const quality = state.selectedImgRes === 0 ? 0.75 : (state.selectedImgRes === 1 ? 0.88 : 0.96);
                                    const dataUrl = sharedCanvas.toDataURL('image/jpeg', quality);
                                    const imgName = `${file.name}_p${pageNum}_img${imgIndex}.jpg`;
                                    extractedImages.push({ name: imgName, dataUrl, dims: `${w}×${h}` });
                                    pageMd += `\n\n[IMAGE: ${imgName}]`;
                                    imgIndex++;
                                    
                                    // Aggressive disposal
                                    sharedCanvas.width = 0; sharedCanvas.height = 0;
                                    tempCanvas.width = 0; tempCanvas.height = 0;
                                } catch (inlineErr) {
                                    logToTerminal(`Page ${pageNum}: skipped inline image (${inlineErr.message}).`, 'warn');
                                }
                                continue;
                            }

                            // XObject path (named ref → page.objs)
                            if (seenImgRefs.has(imgRef)) continue; // dedup refs
                            seenImgRefs.add(imgRef);

                                try {
                                    const imgObj = await Promise.race([
                                        new Promise((resolve, reject) => {
                                            try { page.objs.get(imgRef, obj => obj ? resolve(obj) : reject(new Error('null obj'))); }
                                            catch (e) { reject(e); }
                                        }),
                                        new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 2000))
                                    ]);

                                    if (!imgObj || (!imgObj.data && !imgObj.bitmap)) continue;

                                    let w = imgObj.width, h = imgObj.height;
                                    if (!w || !h || w < 4 || h < 4) continue; // skip tiny

                                    if (state.selectedImgRes < 2) {
                                        const maxDim = state.selectedImgRes === 0 ? 600 : 1200;
                                        if (w > maxDim || h > maxDim) {
                                            const ratio = Math.min(maxDim / w, maxDim / h);
                                            w = Math.round(w * ratio);
                                            h = Math.round(h * ratio);
                                        }
                                    }

                                    sharedCanvas.width = w;
                                    sharedCanvas.height = h;

                                    if (imgObj.bitmap) {
                                        sharedCtx.drawImage(imgObj.bitmap, 0, 0, w, h);
                                    } else {
                                        const srcW = imgObj.width, srcH = imgObj.height;
                                        const imgData = sharedCtx.createImageData(srcW, srcH);
                                        const src = imgObj.data;
                                        let j = 0;
                                        const nc = imgObj.numComponents || 4;

                                        if (nc === 1) {
                                            // gray
                                            for (let k = 0; k < src.length; k++) {
                                                imgData.data[j++] = src[k];
                                                imgData.data[j++] = src[k];
                                                imgData.data[j++] = src[k];
                                                imgData.data[j++] = 255;
                                            }
                                        } else if (nc === 3) {
                                            for (let k = 0; k < src.length; k += 3) {
                                                imgData.data[j++] = src[k];
                                                imgData.data[j++] = src[k + 1];
                                                imgData.data[j++] = src[k + 2];
                                                imgData.data[j++] = 255;
                                            }
                                        } else if (nc === 4) {
                                            // cmyk
                                            for (let k = 0; k < src.length; k += 4) {
                                                const kk = src[k + 3] / 255;
                                                imgData.data[j++] = Math.round(255 * (1 - src[k] / 255) * (1 - kk));
                                                imgData.data[j++] = Math.round(255 * (1 - src[k + 1] / 255) * (1 - kk));
                                                imgData.data[j++] = Math.round(255 * (1 - src[k + 2] / 255) * (1 - kk));
                                                imgData.data[j++] = 255;
                                            }
                                        } else {
                                            // DeviceN / Separation (spot colors, nc > 4):
                                            // Average ink channels (0–255 ink values) and invert to get
                                            // approximate lightness. Better than a raw byte copy.
                                            for (let k = 0; k < src.length; k += nc) {
                                                let sum = 0;
                                                for (let c = 0; c < nc; c++) sum += src[k + c];
                                                const gray = Math.round(255 - (sum / nc));
                                                imgData.data[j++] = gray;
                                                imgData.data[j++] = gray;
                                                imgData.data[j++] = gray;
                                                imgData.data[j++] = 255;
                                            }
                                        }
                                        tempCanvas.width = srcW;
                                        tempCanvas.height = srcH;
                                        tempCtx.putImageData(imgData, 0, 0);
                                        sharedCtx.drawImage(tempCanvas, 0, 0, w, h);
                                    }

                                    const quality = state.selectedImgRes === 0 ? 0.75 : (state.selectedImgRes === 1 ? 0.88 : 0.96);
                                    const dataUrl = sharedCanvas.toDataURL('image/jpeg', quality);
                                    const imgName = `${file.name}_p${pageNum}_img${imgIndex}.jpg`;
                                    extractedImages.push({ name: imgName, dataUrl, dims: `${w}×${h}` });
                                    pageMd += `\n\n[IMAGE: ${imgName}]`;
                                    imgIndex++;
                                    
                                    // Aggressive disposal
                                    sharedCanvas.width = 0; sharedCanvas.height = 0;
                                    tempCanvas.width = 0; tempCanvas.height = 0;
                                } catch (imgErr) {
                                    logToTerminal(`Page ${pageNum}: skipped image ref (${imgErr.message}).`, 'warn');
                                }
                        }
                        } // end of else block
                    }

                    if (addonExtras) pageMd += addonExtras;

                    // AcroForm field values + text annotations
                    try {
                        const annotations = await page.getAnnotations({ intent: 'display' });
                        const formFields = [];
                        const textNotes = [];

                        for (const annot of annotations) {
                            if (annot.subtype === 'Widget' && annot.fieldType) {
                                const label = annot.alternativeText || annot.fieldName || '';
                                let value = '';

                                if (annot.fieldType === 'Tx' || annot.fieldType === 'Ch') {
                                    // Text input or choice/dropdown
                                    value = Array.isArray(annot.fieldValue)
                                        ? annot.fieldValue.join(', ')
                                        : (annot.fieldValue || '');
                                } else if (annot.fieldType === 'Btn') {
                                    // Checkbox or radio button
                                    const checked = annot.fieldValue && annot.fieldValue !== 'Off' &&
                                                    annot.fieldValue === (annot.buttonValue || 'Yes');
                                    value = annot.checkBox ? (checked ? '☑' : '☐') : (annot.fieldValue || '');
                                }

                                if (label || value) {
                                    formFields.push(`- **${label || annot.fieldName || 'Field'}**: ${value || '*(empty)*'}`);
                                }
                            } else if (
                                (annot.subtype === 'Text' || annot.subtype === 'FreeText') &&
                                annot.contents && annot.contents.trim()
                            ) {
                                textNotes.push(`> 💬 *${annot.contents.trim()}*`);
                            }
                        }

                        if (formFields.length > 0) pageMd += '\n\n**Form Fields:**\n' + formFields.join('\n');
                        if (textNotes.length > 0) pageMd += '\n\n' + textNotes.join('\n');
                    } catch (_annotErr) {
                        // Annotations are optional; silently continue
                    }

                    mdText += (pageNum > 1 ? '\n\n---\n\n' : '') + pageMd;
                    page.cleanup();
                    } catch (pageErr) {
                        if (pageErr.message === 'SKIP_FILE' || pageErr.message === 'FILE_SKIPPED') throw pageErr;
                        logToTerminal(`Page ${pageNum} error: ${pageErr.message}`, 'error');
                        mdText += (pageNum > 1 ? '\n\n---\n\n' : '') + `## Page ${pageNum}\n\n*[Error extracting page: ${pageErr.message}]*`;
                        try { page.cleanup(); } catch (e) { }
                    }
                }
            };

            // Queue Execution: Run chunks sequentially
            for (let chunkStart = 1; chunkStart <= pdfDoc.numPages; chunkStart += CHUNK_SIZE) {
                const chunkEnd = Math.min(chunkStart + CHUNK_SIZE - 1, pdfDoc.numPages);
                await processChunk(chunkStart, chunkEnd);

                // Forcefully clear shared canvases between chunks to free up GPU/RAM buffers
                sharedCanvas.width = 0; sharedCanvas.height = 0;
                tempCanvas.width = 0; tempCanvas.height = 0;

                // Yield the thread to the browser's Garbage Collector
                await new Promise(r => setTimeout(r, 300));
            }

            // Wait for all queued background OCR tasks to complete before finalizing document
            await Promise.all(ocrPromises);

            await pdfDoc.destroy();
            
            for (const placeholder in state.pendingOcrTexts) {
                if (mdText.includes(placeholder)) {
                    mdText = mdText.replace(placeholder, state.pendingOcrTexts[placeholder]);
                    delete state.pendingOcrTexts[placeholder];
                }
            }

            const recoveredDraft = localStorage.getItem('litedoc_draft_' + file.name);
            const dataBlock = {
                filename: file.name,
                status: 'success',
                numPages: pdfDoc.numPages,
                mdText,
                draftText: recoveredDraft || undefined,
                extractedImages,
                inlineRenders: pageInlineRenders,
                viewMode: 'raw'
            };
            state.processedData.push(dataBlock);

            // Live UI update: Add to explorer immediately
            if (state.processedData.length === 1) {
                const outputArea = document.getElementById('output-area');
                if (outputArea) outputArea.classList.remove('hidden');
                const dynamicTree = document.getElementById('dynamic-tree-content');
                if (dynamicTree) dynamicTree.innerHTML = '';
            }
            if (typeof window.renderFileToTree === 'function') {
                window.renderFileToTree(dataBlock, state.processedData.length - 1);
            }
            if (typeof window.selectVirtualFile === 'function' && state.processedData.length === 1) {
                window.selectVirtualFile(0, 'md');
            }

            logToTerminal(`Conversion complete: ${file.name}`, 'success');

        } catch (err) {
            if (err.message === 'SKIP_FILE' || err.message === 'FILE_SKIPPED') {
                logToTerminal(`Skipped by user: ${file.name}`, 'warn');
                canceledFiles++;
                continue fileLoop;
            }
            const errName = err && (err.name || err.constructor && err.constructor.name);
            const errMsg = err && err.message || 'Unknown error';

            // Provide more specific error messages based on error type
            let userMessage = errMsg;
            let suggestion = '';

            if (errName === 'PasswordException' || /password/i.test(errMsg)) {
                userMessage = 'PDF is password-protected';
                suggestion = 'Please provide the password when prompted.';
            } else if (errName === 'InvalidPDFException' || /invalid pdf/i.test(errMsg)) {
                userMessage = 'Invalid or corrupted PDF file';
                suggestion = 'The file may be damaged or not a valid PDF.';
            } else if (errName === 'MissingPDFException' || /missing pdf/i.test(errMsg)) {
                userMessage = 'PDF data is missing or empty';
                suggestion = 'The file may be empty or corrupted.';
            } else if (errName === 'UnexpectedResponseException' || /unexpected response/i.test(errMsg)) {
                userMessage = 'Unexpected PDF server response';
                suggestion = 'There may be network or server issues.';
            } else if (errName === 'NotImplementedException' || /not implemented/i.test(errMsg)) {
                userMessage = 'Unsupported PDF feature';
                suggestion = 'This PDF uses features not yet supported by PDF.js.';
            } else if (/encoding/i.test(errMsg) || /font/i.test(errMsg)) {
                userMessage = 'Font or encoding issue';
                suggestion = 'The PDF may use custom font encodings. Try rendering as images.';
            } else if (/cmap/i.test(errMsg)) {
                userMessage = 'Character map issue';
                suggestion = 'The PDF may use non-standard character mappings.';
            } else if (/encrypted/i.test(errMsg) || /security/i.test(errMsg)) {
                userMessage = 'Encryption or security issue';
                suggestion = 'The PDF may use unsupported encryption methods.';
            }

            logToTerminal(`Conversion failed on ${file.name}: ${userMessage}${suggestion ? ` (${suggestion})` : ''}`, 'error');
            console.error('[PDF Parser Error]', errName, errMsg, err);

            const dataBlock = {
                filename: file.name,
                status: 'failed',
                error: userMessage,
                suggestion: suggestion,
                mdText: `# Conversion Failed\n\n**File:** ${file.name}\n\n**Error:** ${userMessage}\n\n${suggestion ? `**Suggestion:** ${suggestion}\n\n` : ''}This file could not be converted. It might be corrupted, heavily encrypted, or contain unsupported PDF features.`,
                extractedImages: [],
                inlineRenders: {},
                viewMode: 'raw'
            };
            state.processedData.push(dataBlock);

            if (state.processedData.length === 1) {
                const outputArea = document.getElementById('output-area');
                if (outputArea) outputArea.classList.remove('hidden');
                const dynamicTree = document.getElementById('dynamic-tree-content');
                if (dynamicTree) dynamicTree.innerHTML = '';
            }
            if (typeof window.renderFileToTree === 'function') {
                window.renderFileToTree(dataBlock, state.processedData.length - 1);
            }
            if (typeof window.selectVirtualFile === 'function' && state.processedData.length === 1) {
                window.selectVirtualFile(0, 'md');
            }
        }
    }

    if (window.__litedocAddons && typeof window.__litedocAddons.cleanupWorker === 'function') {
        window.__litedocAddons.cleanupWorker();
    }

    if (state.processedData.length > 0) {
        // Final UI state cleanup (terminal, etc)
        if (typeof window.showProgressState === 'function') window.showProgressState(false);
        if (typeof window.updateSavingsUI === 'function') window.updateSavingsUI();
        if (typeof window.showDonationToast === 'function') setTimeout(window.showDonationToast, 1500);
    } else if (canceledFiles === files.length) {
        showProgressState(false);
        resetTool(true);
    } else {
        updateProgress(0, 'Conversion Failed', 'Failed to process the provided files');
        showAlert('Error', 'Could not process any of the provided files.');
    }
}