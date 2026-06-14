/**
 * LiteDoc - Mobile UX Overrides & Layout Enhancements
 * Handles mobile-specific layout tagging, view guards, keyboard management, and toolbar syncing.
 */

(function mobileUxLogic() {
    function ready(fn) {
        if (document.readyState !== 'loading') fn();
        else document.addEventListener('DOMContentLoaded', fn);
    }
    
    ready(function () {
        const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

        // 1. Layout Tagging (Enables specific mobile CSS rules)
        try {
            var main = document.querySelector('main');
            if (main) {
                var firstCard = main.querySelector('.card');
                if (firstCard) firstCard.parentElement.classList.add('author-card-wrap');
            }
            var grid = document.querySelector('main .grid.grid-cols-1.lg\\:grid-cols-3');
            if (grid) {
                grid.classList.add('main-grid');
                var first = grid.firstElementChild;
                if (first) first.classList.add('settings-card');
            }
        } catch (e) { }

        // 2. Mobile-Only Settings Collapsible
        try {
            var settings = document.querySelector('.settings-card');
            if (settings) {
                var heading = settings.querySelector('.settings-heading');
                var inner = settings.querySelector('div'); 
                if (heading && inner && heading.parentElement === inner) {
                    var hint = document.createElement('span');
                    hint.className = 'm-collapse-hint';
                    hint.textContent = 'Tap to expand';
                    var chev = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                    chev.setAttribute('class', 'm-chev');
                    chev.setAttribute('viewBox', '0 0 24 24');
                    chev.setAttribute('fill', 'none');
                    chev.setAttribute('stroke', 'currentColor');
                    chev.setAttribute('stroke-width', '2');
                    chev.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>';
                    var right = document.createElement('div');
                    right.style.display = 'flex';
                    right.style.alignItems = 'center';
                    right.style.gap = '8px';
                    right.appendChild(hint);
                    right.appendChild(chev);

                    var body = document.createElement('div');
                    body.className = 'm-collapse-body';
                    var children = Array.from(inner.children);
                    children.forEach(function (c) { if (c !== heading) body.appendChild(c); });
                    inner.appendChild(body);

                    var toggleRow = document.createElement('button');
                    toggleRow.type = 'button';
                    toggleRow.className = 'm-collapse-toggle';
                    heading.parentNode.insertBefore(toggleRow, heading);
                    toggleRow.appendChild(heading);
                    toggleRow.appendChild(right);

                    settings.classList.add('m-collapsible');
                    toggleRow.addEventListener('click', function () {
                        settings.classList.toggle('is-open');
                        hint.textContent = settings.classList.contains('is-open') ? 'Tap to collapse' : 'Tap to expand';
                    });
                }
            }
        } catch (e) { }

        // 3. Global Mobile Class Toggling
        const setMobileClass = () => document.body.classList.toggle('is-mobile', isMobile());
        setMobileClass();
        window.addEventListener('resize', setMobileClass);
        window.addEventListener('orientationchange', setMobileClass);

        // 3.5 FAQ Desktop State Fix (Force open attribute to avoid shadow DOM issues)
        let wasDesktopFaq = null;
        const updateFaqState = () => {
            const isDesktop = window.innerWidth >= 768;
            if (isDesktop !== wasDesktopFaq) {
                wasDesktopFaq = isDesktop;
                document.querySelectorAll('details.faq-card').forEach(details => {
                    if (isDesktop) {
                        details.setAttribute('open', '');
                    } else {
                        details.removeAttribute('open');
                    }
                });
            }
        };
        updateFaqState();
        window.addEventListener('resize', updateFaqState);
        window.addEventListener('orientationchange', updateFaqState);


        // 4. Ace Resize Trap
        try {
            var resizeAce = function () {
                if (window.mdEditor && window.mdEditor.resize) window.mdEditor.resize(true);
            };
            var rAceTimer;
            window.addEventListener('resize', () => { clearTimeout(rAceTimer); rAceTimer = setTimeout(resizeAce, 120); });
            document.addEventListener('click', (e) => {
                if (e.target.closest('.view-mode-pill button, #vm-edit, #vm-fullscreen')) setTimeout(resizeAce, 200);
            });
        } catch (e) { }

        // 5. Tooltips (Non-critical UX)
        try {
            const copyBtn = document.getElementById('viewer-copy-btn');
            const fullBtn = document.getElementById('vm-fullscreen');
            const actionBtn = document.getElementById('viewer-action-btn');
            if (copyBtn) copyBtn.title = "Copy Content to Clipboard";
            if (fullBtn) fullBtn.title = "Toggle Fullscreen";
            if (actionBtn) actionBtn.title = "Download Document";
        } catch (e) { }

        // 6. Focus Mode & Toolbar Logic
        window.toggleFocusMode = function() {
            document.body.classList.toggle('m-focus-mode');
            const isFocus = document.body.classList.contains('m-focus-mode');
            const focusBtn = document.getElementById('vm-focus');
            if (focusBtn) {
                focusBtn.classList.toggle('active', isFocus);
                focusBtn.style.color = isFocus ? 'var(--accent-hi)' : '';
                focusBtn.style.background = isFocus ? 'var(--accent-low)' : '';
            }
            if (window.mdEditor) {
                setTimeout(() => window.mdEditor.resize(), 300);
            }
        };

        window.insertMd = function(prefix, suffix) {
            if (!window.mdEditor) return;
            const editor = window.mdEditor;
            const selectedText = editor.getSelectedText();
            if (selectedText) {
                editor.insert(prefix + selectedText + suffix);
            } else {
                editor.insert(prefix + suffix);
                if (suffix.length > 0) {
                    const pos = editor.getCursorPosition();
                    editor.moveCursorTo(pos.row, pos.column - suffix.length);
                }
            }
            editor.focus();
        };

        function syncToolbar() {
            const toolbar = document.getElementById('m-editor-toolbar');
            if (!toolbar) return;
            const shouldShow = isMobile() && state.isEditing && state.currentViewType === 'md';
            toolbar.classList.toggle('m-show', shouldShow);
        }

        // Hook into existing functions to ensure toolbar stays in sync
        const _origEnterEdit = window.enterEditMode;
        if (typeof _origEnterEdit === 'function') {
            window.enterEditMode = function() { 
                _origEnterEdit(); 
                syncToolbar(); 
                if (isMobile() && !document.body.classList.contains('m-focus-mode')) {
                    window.toggleFocusMode();
                }
            };
        }
        
        const _origSaveEdits = window.saveEdits;
        if (typeof _origSaveEdits === 'function') {
            window.saveEdits = function(arg) { 
                _origSaveEdits(arg); 
                syncToolbar(); 
                if (document.body.classList.contains('m-focus-mode')) window.toggleFocusMode(); 
            };
        }
        
        const _origCancelEdits = window.cancelEdits;
        if (typeof _origCancelEdits === 'function') {
            window.cancelEdits = function() { 
                _origCancelEdits(); 
                syncToolbar(); 
                if (document.body.classList.contains('m-focus-mode')) window.toggleFocusMode(); 
            };
        }
        
        const _origSelectFile = window.selectVirtualFile;
        if (typeof _origSelectFile === 'function') {
            window.selectVirtualFile = function(a, b, c) { 
                _origSelectFile(a, b, c); 
                syncToolbar(); 
            };
        }
        
        const _origSetViewMode = window.setViewMode;
        if (typeof _origSetViewMode === 'function') {
            window.setViewMode = function(mode) { 
                _origSetViewMode(mode); 
                syncToolbar(); 
            };
        }

        syncToolbar();
    });
})();

/* Block split view on small screens */
(function mobileViewModeGuard() {
    const mq = window.matchMedia('(max-width: 768px)');
    function enforce() {
        if (!mq.matches) return;
        if (typeof state.currentViewMode !== 'undefined' && state.currentViewMode === 'split'
            && typeof window.setViewMode === 'function') {
            window.setViewMode(typeof state.isEditing !== 'undefined' && state.isEditing ? 'raw' : 'rendered');
        }
    }
    mq.addEventListener ? mq.addEventListener('change', enforce) : mq.addListener(enforce);
    window.addEventListener('load', enforce);
})();

/* iOS Keyboard Push-up Logic */
(function mobileKeyboardHandling() {
    const mq = window.matchMedia('(max-width: 768px)');
    const root = document.documentElement;
    root.style.setProperty('--kb-inset', '0px');
    root.style.setProperty('--toolbar-h', '0px');

    window.addEventListener('DOMContentLoaded', () => {
        const toolbarEl = document.getElementById('viewer-editor-header')
            || document.querySelector('#viewer-card > div:first-child');
        function measureToolbar() {
            if (!toolbarEl) return 0;
            const h = mq.matches ? toolbarEl.getBoundingClientRect().height : 0;
            root.style.setProperty('--toolbar-h', h + 'px');
            return h;
        }
        if (typeof ResizeObserver !== 'undefined' && toolbarEl) {
            new ResizeObserver(measureToolbar).observe(toolbarEl);
        }
        window.addEventListener('resize', measureToolbar);
        measureToolbar();

        const vv = window.visualViewport;
        if (!vv) return;

        let lastInset = 0;
        let insetRaf = 0;
        function updateInset() {
            if (!mq.matches) {
                if (lastInset !== 0) {
                    root.style.setProperty('--kb-inset', '0px');
                    document.body.classList.remove('kb-open');
                    lastInset = 0;
                }
                return;
            }
            if (insetRaf) return;
            insetRaf = requestAnimationFrame(() => {
                insetRaf = 0;
                const inset = Math.max(0, window.innerHeight - (vv.height + vv.offsetTop));
                if (Math.abs(inset - lastInset) > 24) {
                    root.style.setProperty('--kb-inset', inset + 'px');
                    document.body.classList.toggle('kb-open', inset > 120);
                    lastInset = inset;
                }
            });
        }
        vv.addEventListener('resize', updateInset);
        vv.addEventListener('scroll', updateInset);
        window.addEventListener('orientationchange', updateInset);
        updateInset();
    });
})();

// Mobile View Switcher
window.setMobileView = function(view) {
    document.body.classList.remove('m-view-explorer', 'm-view-editor');
    document.body.classList.add('m-view-' + view);
    const explorerBtn = document.getElementById('mobile-view-explorer-btn');
    const editorBtn = document.getElementById('mobile-view-editor-btn');
    if (explorerBtn) explorerBtn.classList.toggle('m-view-btn-active', view === 'explorer');
    if (editorBtn) editorBtn.classList.toggle('m-view-btn-active', view === 'editor');
    if (view === 'editor' && window.mdEditor) setTimeout(() => window.mdEditor.resize(), 100);
};

// Default View Initialization
document.addEventListener('DOMContentLoaded', () => {
    if (window.innerWidth <= 768) document.body.classList.add('m-view-explorer');
});
