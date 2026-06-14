/**
 * LiteDoc - UI Logic
 * Consolidates general UI behaviors, theme management, and view mode switching.
 */

// Prevent accidental tab closure
window.addEventListener('beforeunload', (e) => {
    if (state.hasUnsavedChanges || (state.pendingFiles && state.pendingFiles.length > 0)) {
        e.preventDefault(); e.returnValue = '';
    }
});

// Theme Management
function toggleTheme() {
    const html = document.documentElement;
    const isDark = html.getAttribute('data-theme') === 'dark';
    html.setAttribute('data-theme', isDark ? 'light' : 'dark');
    
    const moon = document.getElementById('icon-moon');
    const sun = document.getElementById('icon-sun');
    const knob = document.getElementById('theme-toggle-knob');
    
    if (isDark) {
        if (moon) moon.style.display = 'none';
        if (sun) sun.style.display = '';
        if (knob) { knob.style.transform = 'translateX(20px)'; knob.style.background = 'var(--accent)'; }
    } else {
        if (moon) moon.style.display = '';
        if (sun) sun.style.display = 'none';
        if (knob) { knob.style.transform = 'translateX(0)'; knob.style.background = 'var(--text-3)'; }
    }
    
    if (window.mdEditor) {
        window.mdEditor.setTheme(isDark ? "ace/theme/chrome" : "ace/theme/tomorrow_night");
    }
    localStorage.setItem('litedoc-theme', isDark ? 'light' : 'dark');
}

// Initial theme load
(function () {
    const saved = localStorage.getItem('litedoc-theme');
    if (saved === 'light') {
        document.documentElement.setAttribute('data-theme', 'light');
        window.addEventListener('DOMContentLoaded', () => {
            const moon = document.getElementById('icon-moon');
            const sun = document.getElementById('icon-sun');
            const knob = document.getElementById('theme-toggle-knob');
            if (moon) moon.style.display = 'none';
            if (sun) sun.style.display = '';
            if (knob) { knob.style.transform = 'translateX(20px)'; knob.style.background = 'var(--accent)'; }
        });
    }
})();

// Initial Auto-Resolve load
(function () {
    window.addEventListener('DOMContentLoaded', () => {
        const arEnabled = localStorage.getItem('litedoc-ar-enabled') === 'true';
        const arAction = localStorage.getItem('litedoc-ar-action') || 'render';
        const mathEnabledRaw = localStorage.getItem('litedoc-math-enabled');
        const mathEnabled = mathEnabledRaw === null ? true : mathEnabledRaw === 'true';
        
        state.autoResolveEnabled = arEnabled;
        state.autoResolveAction = arAction;
        state.mathEnabled = mathEnabled;

        const arBtn = document.getElementById('autoresolve-toggle-btn');
        const arKnob = document.getElementById('autoresolve-toggle-knob');
        const arSub = document.getElementById('autoresolve-submenu');
        
        if (state.autoResolveEnabled) {
            if (arBtn) arBtn.style.background = 'var(--accent)';
            if (arKnob) arKnob.style.transform = 'translateX(20px)';
            if (arSub) arSub.classList.remove('hidden');
        } else {
            if (arBtn) arBtn.style.background = 'var(--border)';
            if (arKnob) arKnob.style.transform = 'translateX(0)';
            if (arSub) arSub.classList.add('hidden');
        }

        document.querySelectorAll('[data-ar]').forEach(b => {
            const isSelected = b.dataset.ar === state.autoResolveAction;
            b.classList.toggle('selected', isSelected);
            if (isSelected) {
                const display = document.getElementById('ar-action-display');
                if (display) display.textContent = b.textContent;
            }
        });

        const mathBtn = document.getElementById('math-toggle-btn');
        const mathKnob = document.getElementById('math-toggle-knob');
        if (state.mathEnabled) {
            if (mathBtn) mathBtn.style.background = 'var(--accent)';
            if (mathKnob) mathKnob.style.transform = 'translateX(20px)';
        } else {
            if (mathBtn) mathBtn.style.background = 'var(--border)';
            if (mathKnob) mathKnob.style.transform = 'translateX(0)';
        }

        const rawEnabledRaw = localStorage.getItem('litedoc-raw-mode');
        state.rawTextMode = rawEnabledRaw === 'true';
        const rawBtn = document.getElementById('rawtext-toggle-btn');
        const rawKnob = document.getElementById('rawtext-toggle-knob');
        if (state.rawTextMode) {
            if (rawBtn) rawBtn.style.background = 'var(--accent)';
            if (rawKnob) { rawKnob.style.transform = 'translateX(20px)'; rawKnob.style.background = '#fff'; }
        } else {
            if (rawBtn) rawBtn.style.background = 'var(--bg-input)';
            if (rawKnob) { rawKnob.style.transform = 'translateX(0)'; rawKnob.style.background = 'rgba(255,255,255,0.4)'; }
        }
    });
})();

// Fullscreen Toggle
function toggleFullscreen() {
    const viewerCard = document.getElementById('viewer-card');
    const btn = document.getElementById('vm-fullscreen');
    if (!viewerCard.classList.contains('fixed')) {
        viewerCard.classList.add('fixed', 'inset-0', 'z-[200]', 'rounded-none');
        viewerCard.classList.remove('md:col-span-2', 'min-h-[450px]');
        btn.style.color = 'var(--accent-hi)';
        btn.style.background = 'var(--accent-low)';
        btn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 14h6m0 0v6m0-6l-7 7m17-11h-6m0 0V4m0 6l-7-7M4 10h6m0 0V4m0 6l-7-7m17 11h-6m0 0v6m0-6l7 7" /></svg>`;
    } else {
        viewerCard.classList.remove('fixed', 'inset-0', 'z-[200]', 'rounded-none');
        viewerCard.classList.add('md:col-span-2', 'min-h-[450px]');
        btn.style.color = 'var(--text-2)';
        btn.style.background = 'transparent';
        btn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" /></svg>`;
    }
    if (window.mdEditor) setTimeout(() => window.mdEditor.resize(), 50);
}

// Math Rendering Toggle
function toggleMathRendering() {
    state.mathEnabled = !state.mathEnabled;
    localStorage.setItem('litedoc-math-enabled', state.mathEnabled);

    const btn = document.getElementById('math-toggle-btn');
    const knob = document.getElementById('math-toggle-knob');
    if (state.mathEnabled) {
        if (btn) btn.style.background = 'var(--accent)';
        if (knob) knob.style.transform = 'translateX(20px)';
    } else {
        if (btn) btn.style.background = 'var(--border)';
        if (knob) knob.style.transform = 'translateX(0)';
    }
    if (state.currentViewMode === 'rendered' && state.currentViewType === 'md') {
        const data = state.processedData[state.activeDataIndex];
        if (data) window.renderMarkdown(data.mdText);
    }
}

// Alert Handlers
function showAlert(title, message) {
    document.getElementById('alert-title').textContent = title;
    document.getElementById('alert-message').textContent = message;
    const el = document.getElementById('custom-alert');
    el.classList.remove('hidden'); el.classList.add('flex');
}
function closeAlert() {
    const el = document.getElementById('custom-alert');
    el.classList.add('hidden'); el.classList.remove('flex');
}

// Image Preview
function openImagePreview() {
    const imgSrc = document.getElementById('viewer-img-element').src;
    if (!imgSrc) return;
    document.getElementById('image-preview-large').src = imgSrc;
    const actionBtn = document.getElementById('viewer-action-btn');
    const downloadBtn = document.getElementById('image-preview-download-btn');
    downloadBtn.setAttribute('onclick', actionBtn.getAttribute('onclick') + '; event.stopPropagation();');
    const modal = document.getElementById('image-preview-modal');
    modal.classList.remove('hidden'); modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
}
function closeImagePreview() {
    const modal = document.getElementById('image-preview-modal');
    modal.classList.add('hidden'); modal.classList.remove('flex');
    document.body.style.overflow = '';
}

// Keyboard Listeners
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === 's' || e.key === 'S')) {
        e.preventDefault(); if (window.saveEdits) window.saveEdits(false);
    }
    const modal = document.getElementById('image-preview-modal');
    const isModalOpen = modal && !modal.classList.contains('hidden');
    if (e.key === 'Escape') {
        if (isModalOpen) closeImagePreview();
        else if (document.getElementById('viewer-card').classList.contains('fixed')) toggleFullscreen();
    } else if (isModalOpen) {
        if (e.key === 'ArrowLeft') navigateImage(-1);
        else if (e.key === 'ArrowRight') navigateImage(1);
    }
});

// File Tree Keyboard Navigation
window.addEventListener('DOMContentLoaded', () => {
    const ftc = document.getElementById('file-tree-container');
    if (ftc) ftc.addEventListener('keydown', (e) => {
        const nodes = Array.from(document.querySelectorAll('.file-node'));
        if (!nodes.length) return;
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            let idx = nodes.indexOf(document.activeElement);
            if (idx === -1) idx = nodes.findIndex(n => n.classList.contains('active-md') || n.classList.contains('active-img'));
            if (idx === -1) idx = 0;
            else idx = (e.key === 'ArrowDown') ? Math.min(idx + 1, nodes.length - 1) : Math.max(idx - 1, 0);
            nodes[idx].focus(); nodes[idx].click();
        } else if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault(); if (document.activeElement.classList.contains('file-node')) document.activeElement.click();
        }
    });
});

// Image Navigation
function navigateImage(dir) {
    if (state.activeDataIndex === null || state.currentImageIndex === null) return;
    const data = state.processedData[state.activeDataIndex];
    if (!data || !data.extractedImages || data.extractedImages.length === 0) return;
    let newIndex = state.currentImageIndex + dir;
    if (newIndex < 0) newIndex = data.extractedImages.length - 1;
    if (newIndex >= data.extractedImages.length) newIndex = 0;
    window.selectVirtualFile(state.activeDataIndex, 'img', newIndex);
    openImagePreview();
}

// Auto-Resolve Configuration
function toggleAutoResolve() {
    state.autoResolveEnabled = !state.autoResolveEnabled;
    localStorage.setItem('litedoc-ar-enabled', state.autoResolveEnabled);

    const btn = document.getElementById('autoresolve-toggle-btn');
    const knob = document.getElementById('autoresolve-toggle-knob');
    const sub = document.getElementById('autoresolve-submenu');
    if (state.autoResolveEnabled) {
        if (btn) btn.style.background = 'var(--accent)';
        if (knob) knob.style.transform = 'translateX(20px)';
        if (sub) sub.classList.remove('hidden');
    } else {
        if (btn) btn.style.background = 'var(--border)';
        if (knob) knob.style.transform = 'translateX(0)';
        if (sub) sub.classList.add('hidden');
    }
}

// Raw Text Dump Toggle
function toggleRawTextMode() {
    state.rawTextMode = !state.rawTextMode;
    localStorage.setItem('litedoc-raw-mode', state.rawTextMode);

    // Communicate to addons.js that raw mode turned on
    if (state.rawTextMode && window.__litedocAddons && window.__litedocAddons.onRawModeToggled) {
        window.__litedocAddons.onRawModeToggled(true);
    }

    const btn = document.getElementById('rawtext-toggle-btn');
    const knob = document.getElementById('rawtext-toggle-knob');
    if (state.rawTextMode) {
        if (btn) btn.style.background = 'var(--accent)';
        if (knob) { knob.style.transform = 'translateX(20px)'; knob.style.background = '#fff'; }
    } else {
        if (btn) btn.style.background = 'var(--bg-input)';
        if (knob) { knob.style.transform = 'translateX(0)'; knob.style.background = 'rgba(255,255,255,0.4)'; }
    }
}

function setAutoResolveAction(action) {
    state.autoResolveAction = action;
    localStorage.setItem('litedoc-ar-action', action);
    document.querySelectorAll('[data-ar]').forEach(b => {
        const isSelected = b.dataset.ar === action;
        b.classList.toggle('selected', isSelected);
        if (isSelected) {
            const display = document.getElementById('ar-action-display');
            if (display) display.textContent = b.textContent;
        }
    });
    const customSel = document.getElementById('ar-custom-select');
    if (customSel) customSel.classList.remove('open');
}

// Close custom select when clicking outside
document.addEventListener('click', (e) => {
    const customSel = document.getElementById('ar-custom-select');
    if (customSel && customSel.classList.contains('open') && !customSel.contains(e.target)) {
        customSel.classList.remove('open');
    }
});

// Font Alert Promised Wrapper
function showFontAlert(filename, queuePos) {
    return new Promise(resolve => {
        window._fontAlertResolve = resolve;
        const chip = document.getElementById('font-alert-filename');
        if (chip) chip.textContent = filename || 'unknown.pdf';
        const pos = document.getElementById('font-alert-queue-pos');
        if (pos) pos.textContent = queuePos || '';
        document.getElementById('font-alert-overlay').classList.add('active');
    });
}
function fontAlertChoice(choice) {
    document.getElementById('font-alert-overlay').classList.remove('active');
    if (window._fontAlertResolve) { window._fontAlertResolve(choice); window._fontAlertResolve = null; }
}

// Donation Toast
function showDonationToast() {
    const t = document.getElementById('donation-toast');
    if (t) { t.classList.remove('translate-y-32', 'opacity-0'); t.classList.add('translate-y-0', 'opacity-100'); }
}
function closeDonationToast() {
    const t = document.getElementById('donation-toast');
    if (t) { t.classList.add('translate-y-32', 'opacity-0'); t.classList.remove('translate-y-0', 'opacity-100'); }
}

// Resolution Presets
function setImgRes(v) {
    state.selectedImgRes = v;
    document.querySelectorAll('.res-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll(`.res-btn-val-${v}`).forEach(b => b.classList.add('active'));
}

/**
 * View Mode Management
 * consolidated logic for raw/rendered/split views
 */
function setViewMode(mode) {
    if (state.currentViewType !== 'md') return;

    // Mobile view mode guard
    if (mode === 'split' && window.matchMedia('(max-width: 768px)').matches) {
        mode = state.isEditing ? 'raw' : 'rendered';
    }

    state.currentViewMode = mode;
    const activeData = state.processedData[state.activeDataIndex];
    if (activeData) {
        activeData.viewMode = mode;
        activeData.isEditing = state.isEditing;
    }

    // Toggle Pills
    document.getElementById('vm-raw').classList.toggle('on', mode === 'raw');
    document.getElementById('vm-rendered').classList.toggle('on', mode === 'rendered');
    document.getElementById('vm-split').classList.toggle('on', mode === 'split');

    const editBtn = document.getElementById('vm-edit');
    const saveBtn = document.getElementById('vm-save');
    const cancelBtn = document.getElementById('vm-cancel');
    const actionBtn = document.getElementById('viewer-action-btn');
    const readActions = document.getElementById('viewer-read-actions');
    const editActions = document.getElementById('viewer-edit-actions');
    const copyBtn = document.getElementById('viewer-copy-btn');
    const unformatBtn = document.getElementById('vm-unformat');
    const headerRight = document.getElementById('viewer-header-right');
    const fullscreenBtn = document.getElementById('vm-fullscreen');
    const utilGroup = document.getElementById('viewer-util-group');
    const viewerCard = document.getElementById('viewer-card');
    const mdControls = document.getElementById('md-controls');

    if (state.isEditing) {
        document.body.classList.add('is-editing');
        if (readActions) readActions.classList.add('hidden');
        if (editActions) editActions.classList.remove('hidden');
        // Legacy individual button compat
        if (editBtn) editBtn.classList.add('hidden');
        if (saveBtn) saveBtn.classList.remove('hidden');
        if (cancelBtn) cancelBtn.classList.remove('hidden');
        if (actionBtn) actionBtn.classList.add('hidden');
        
        // Relocate copy button next to unformat button during edit
        if (copyBtn && unformatBtn && unformatBtn.parentNode) {
            unformatBtn.parentNode.insertBefore(copyBtn, unformatBtn.nextSibling);
        }
        // Relocate fullscreen button to toolbar in edit mode on desktop, hide on mobile
        if (fullscreenBtn) {
            if (window.innerWidth <= 768) {
                fullscreenBtn.style.display = 'none';
            } else if (unformatBtn && unformatBtn.parentNode) {
                unformatBtn.parentNode.appendChild(fullscreenBtn);
            }
        }
        // Move utility group to bottom of viewer-card on mobile edit mode
        if (window.innerWidth <= 768) {
            if (utilGroup && viewerCard && utilGroup.parentNode !== viewerCard) {
                viewerCard.appendChild(utilGroup);
            }
        } else {
            if (utilGroup && mdControls && utilGroup.parentNode !== mdControls) {
                mdControls.appendChild(utilGroup);
            }
        }
    } else {
        document.body.classList.remove('is-editing');
        if (readActions) readActions.classList.remove('hidden');
        if (editActions) editActions.classList.add('hidden');
        // Legacy individual button compat
        if (editBtn) editBtn.classList.remove('hidden');
        if (saveBtn) saveBtn.classList.add('hidden');
        if (cancelBtn) cancelBtn.classList.add('hidden');
        if (actionBtn) actionBtn.classList.remove('hidden');
        
        // Restore copy button to original position
        if (copyBtn && headerRight && actionBtn) {
            headerRight.insertBefore(copyBtn, actionBtn);
        }
        // Restore fullscreen button to original position and style
        if (fullscreenBtn) {
            fullscreenBtn.style.display = '';
            if (headerRight) {
                headerRight.appendChild(fullscreenBtn);
            }
        }
        // Move utility group back to mdControls when not editing
        if (utilGroup && mdControls && utilGroup.parentNode !== mdControls) {
            mdControls.appendChild(utilGroup);
        }
    }

    const rawEl = document.getElementById('viewer-md-container');
    const renderedEl = document.getElementById('viewer-md-rendered');
    const editorEl = document.getElementById('raw-markdown-block');
    const wrapper = document.getElementById('viewer-content-wrapper');
    const findBtn = document.getElementById('vm-find');
    const linesBtn = document.getElementById('vm-linenumbers');
    const wrapBtn = document.getElementById('vm-wordwrap');
    const undoBtn = document.getElementById('vm-undo');
    const redoBtn = document.getElementById('vm-redo');
    const resizer = document.getElementById('split-resizer');

    // Reset visibility
    [rawEl, renderedEl, editorEl, findBtn, linesBtn, wrapBtn, unformatBtn, undoBtn, redoBtn, resizer].forEach(el => { if (el) el.classList.add('hidden'); });
    if (wrapper) { wrapper.classList.remove('flex-row'); wrapper.classList.add('flex-col'); }

    const textToRender = (window.mdEditor && state.hasUnsavedChanges) ? window.mdEditor.getValue() : (activeData ? activeData.mdText : '');

    if (mode === 'raw') {
        if (state.isEditing && editorEl) {
            editorEl.classList.remove('hidden');
            [findBtn, linesBtn, wrapBtn, unformatBtn, undoBtn, redoBtn].forEach(el => { if (el) el.classList.remove('hidden'); });
            if (window.mdEditor) {
                if (!state.hasUnsavedChanges && activeData) {
                    window.isSyncingAce = true; window.mdEditor.setValue(activeData.mdText, -1); window.isSyncingAce = false;
                }
                window.mdEditor.resize();
            }
        } else if (rawEl) {
            rawEl.classList.remove('hidden');
            if (activeData) rawEl.textContent = textToRender;
        }
    } else if (mode === 'rendered') {
        if (renderedEl) {
            renderedEl.classList.remove('hidden');
            if (activeData) window.renderMarkdown(textToRender);
        }
    } else if (mode === 'split') {
        if (renderedEl && wrapper) {
            renderedEl.classList.remove('hidden');
            wrapper.classList.remove('flex-col'); wrapper.classList.add('flex-row');
            if (resizer) resizer.classList.remove('hidden');
            
            if (state.isEditing && editorEl) {
                editorEl.classList.remove('hidden');
                [findBtn, linesBtn, wrapBtn, unformatBtn, undoBtn, redoBtn].forEach(el => { if (el) el.classList.remove('hidden'); });
                if (window.mdEditor) {
                    if (!state.hasUnsavedChanges && activeData) {
                        window.isSyncingAce = true; window.mdEditor.setValue(activeData.mdText, -1); window.isSyncingAce = false;
                    }
                    window.renderMarkdown(window.mdEditor.getValue());
                    setTimeout(() => window.mdEditor.resize(), 50);
                }
            } else if (rawEl) {
                rawEl.classList.remove('hidden');
                if (activeData) { rawEl.textContent = textToRender; window.renderMarkdown(textToRender); }
            }
        }
    }
}

// Ensure utility group placement is correct on resize when in edit mode
window.addEventListener('resize', () => {
    const utilGroup = document.getElementById('viewer-util-group');
    const viewerCard = document.getElementById('viewer-card');
    const mdControls = document.getElementById('md-controls');
    if (window.state && window.state.isEditing) {
        if (window.innerWidth <= 768) {
            if (utilGroup && viewerCard && utilGroup.parentNode !== viewerCard) {
                viewerCard.appendChild(utilGroup);
            }
        } else {
            if (utilGroup && mdControls && utilGroup.parentNode !== mdControls) {
                mdControls.appendChild(utilGroup);
            }
        }
    }
});

// Split Resizer Logic
window.addEventListener('DOMContentLoaded', () => {
    const splitResizer = document.getElementById('split-resizer');
    const viewerWrapper = document.getElementById('viewer-content-wrapper');
    const editorBlock = document.getElementById('raw-markdown-block');
    const rawEl = document.getElementById('viewer-md-container');
    let isResizing = false;

    if (splitResizer) {
        splitResizer.addEventListener('mousedown', () => {
            isResizing = true; splitResizer.classList.add('dragging');
            document.body.style.cursor = 'col-resize'; document.body.style.userSelect = 'none';
        });
        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;
            const containerRect = viewerWrapper.getBoundingClientRect();
            let newWidthPercent = ((e.clientX - containerRect.left) / containerRect.width) * 100;
            newWidthPercent = Math.max(15, Math.min(85, newWidthPercent));
            state.splitRatio = newWidthPercent;
            
            if (state.isEditing && editorBlock) {
                editorBlock.style.flex = `0 0 ${newWidthPercent}%`;
                if (window.mdEditor) window.mdEditor.resize();
            } else if (rawEl) {
                rawEl.style.flex = `0 0 ${newWidthPercent}%`;
            }
        });
        document.addEventListener('mouseup', () => {
            if (isResizing) {
                isResizing = false; splitResizer.classList.remove('dragging');
                document.body.style.cursor = ''; document.body.style.userSelect = '';
            }
        });
    }
});

/**
 * Demo Loader
 */
async function loadSamplePDF() {
    if (window.showProgressState) window.showProgressState(true);
    if (window.logToTerminal) window.logToTerminal('Loading demo document...', 'warn');
    if (window.updateProgress) window.updateProgress(15, 'Opening virtual file descriptor...', 'Initializing PDF.js worker');
    await new Promise(r => setTimeout(r, 800));
    if (window.updateProgress) window.updateProgress(45, 'Scanning page contents...', 'Analyzing layout and text layers');
    await new Promise(r => setTimeout(r, 1000));
    if (window.updateProgress) window.updateProgress(75, 'Extracting images...', 'Compressing to match resolution preset');
    await new Promise(r => setTimeout(r, 500));

    const generatedMd = `<!-- Converted from academic_paper_v3.pdf — 3 pages -->\n\n## Page 1\n# Abstract: Deep Structural Neural Mapping Architecture\nDeep learning strategies often fail when executing unstructured inputs directly.\n\nThe loss function is defined as:\n\n$$L(\\theta) = -\\frac{1}{N}\\sum_{i=1}^{N} \\left[ y_i \\log(\\hat{y}_i) + (1-y_i)\\log(1-\\hat{y}_i) \\right]$$\n\nWhere the gradient update rule is $\\theta \\leftarrow \\theta - \\eta \\nabla_\\theta L(\\theta)$.\n\n## Page 2\n[IMAGE: academic_paper_v3.pdf_p2_img1.jpg]\n[IMAGE: academic_paper_v3.pdf_p2_img2.jpg]\n\n## Page 3\n### Arabic Sample / نموذج عربي\nيُعدّ هذا التطبيق أداةً مجانيةً لتحويل ملفات PDF إلى صيغة Markdown.\nجميع العمليات تتم محليًا في متصفحك دون رفع أي ملف إلى خوادم خارجية.\n\nEuler's identity: $e^{i\\pi} + 1 = 0$`;
    const sampleImages = [
        { name: 'academic_paper_v3.pdf_p2_img1.jpg', dataUrl: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='400' height='200' viewBox='0 0 400 200'><rect width='100%' height='100%' fill='%23121524'/><text x='50%' y='50%' font-family='sans-serif' font-size='16' fill='%236366f1' dominant-baseline='middle' text-anchor='middle'>Diagram: Spatial Grid Flow Map</text></svg>" },
        { name: 'academic_paper_v3.pdf_p2_img2.jpg', dataUrl: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='400' height='200' viewBox='0 0 400 200'><rect width='100%' height='100%' fill='%23121524'/><text x='50%' y='50%' font-family='sans-serif' font-size='16' fill='%23a855f7' dominant-baseline='middle' text-anchor='middle'>Plot: Epoch Metrics Progression Chart</text></svg>" }
    ];
    state.processedData = [{ filename: 'academic_paper_v3.pdf', status: 'success', mdText: generatedMd, extractedImages: sampleImages, viewMode: 'raw', numPages: 3 }];
    if (window.finishProcessing) window.finishProcessing();
}

async function copyCurrentFile() {
    let textToCopy = '';
    if (state.isEditing && window.mdEditor) {
        textToCopy = window.mdEditor.getValue();
    } else if (state.activeDataIndex !== null) {
        const data = state.processedData[state.activeDataIndex];
        if (data && data.mdText) textToCopy = data.mdText;
    }

    if (!textToCopy) return;

    try {
        await navigator.clipboard.writeText(textToCopy);
        if (window.showAlert) window.showAlert('Copied to clipboard!', 'success');
    } catch (e) {
        console.error('Copy failed:', e);
        if (window.showAlert) window.showAlert('Failed to copy text', 'error');
    }
}

// Global UI Exposures
window.toggleTheme = toggleTheme;
window.toggleMathRendering = toggleMathRendering;
window.toggleAutoResolve = toggleAutoResolve;
window.toggleRawTextMode = toggleRawTextMode;
window.setAutoResolveAction = setAutoResolveAction;
window.setImgRes = setImgRes;
window.setViewMode = setViewMode;
window.copyCurrentFile = copyCurrentFile;
window.toggleFullscreen = toggleFullscreen;
window.loadSamplePDF = loadSamplePDF;
window.showAlert = showAlert;
window.closeAlert = closeAlert;
window.fontAlertChoice = fontAlertChoice;
window.closeDonationToast = closeDonationToast;
window.openImagePreview = openImagePreview;
window.closeImagePreview = closeImagePreview;
window.navigateImage = navigateImage;
