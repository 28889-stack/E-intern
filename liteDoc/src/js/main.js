/**
 * LiteDoc Central Orchestrator
 * Resolves load-order crashes and securely manages module mounting.
 */

// 3. Safely Mount Modules on Boot
document.addEventListener('DOMContentLoaded', async () => {
    console.log('[Boot] Mounting LiteDoc sub-modules...');

    // 0. (Service Worker registration removed for standalone HTML release)

    // Auto-inject logic removed because it conflicts with the build script bundler.
    // Core scripts are bundled inline.

    // 2. PDF.js Worker Initialization (delayed to ensure pdf.js is loaded)
    if (typeof pdfjsLib !== 'undefined') {
        // Configure comprehensive PDF.js options for maximum format support
        pdfjsLib.GlobalWorkerOptions.workerPort = null;

        // Default worker URL (build.py will patch this with a data URI)
        if (!pdfjsLib.GlobalWorkerOptions.workerSrc) {
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        }

        // If the worker is already configured (e.g. inlined as a data URI or pointing to a CDN by the build script), skip detection
        const currentSrc = pdfjsLib.GlobalWorkerOptions.workerSrc || '';
        if (currentSrc.startsWith('data:') || currentSrc.startsWith('http')) {
            console.info('[Boot] PDF.js worker already configured.');
        } else if (window.location.protocol === 'file:') {
            console.info('[Boot] Running on file:// protocol. Using CDN for PDF.js worker.');
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
        } else {
            try {
                // Try local worker first, but catch the 404 to avoid console noise if possible
                // Using { method: 'HEAD' } is better than a full GET but still shows 404 in most browsers
                const res = await fetch('js/pdf.worker.min.js', { method: 'HEAD' });
                if (res.ok || res.status === 0) {
                    pdfjsLib.GlobalWorkerOptions.workerSrc = 'js/pdf.worker.min.js';
                } else {
                    throw new Error('Local worker not found');
                }
            } catch (e) {
                console.info('[Boot] Local PDF.js worker not found or inaccessible. Falling back to CDN...');
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
            }
        }

        console.info('[Boot] PDF.js worker configured successfully.');
    }

    try {
        // Execute modular initialization if the modules define them
        if (typeof window.initUI === 'function') window.initUI();
        if (typeof window.initOCR === 'function') window.initOCR();
        if (typeof window.initAddons === 'function') window.initAddons();

        // Verify critical components loaded
        if (typeof window.executePdfConversion !== 'function' && typeof window.startConversionLogic !== 'function') {
            console.warn('[Boot] pdf-parser.js has not registered the conversion engine yet.');
        }

        // Fire and forget: Precache OCR models in the background
        if (window.__litedocOCR && typeof window.__litedocOCR.precacheModels === 'function') {
            if (!window.__litedocAddons || window.__litedocAddons.ocrEnabled()) {
                window.__litedocOCR.precacheModels();
            }
        }

        console.log('[Boot] Sequence complete.');
    } catch (error) {
        console.error('[Boot] Critical module initialization failure:', error);
        if (typeof window.showAlert === 'function') {
            window.showAlert('Initialization Error', 'A critical module failed to load. Please check the console and refresh the page.');
        }
    }

    // 4. Remove Splash Screen / Preloader (FOUC protection)
    setTimeout(() => {
        const preloader = document.getElementById('app-preloader');
        if (preloader) {
            preloader.style.opacity = '0';
            preloader.style.visibility = 'hidden';
            setTimeout(() => preloader.remove(), 500); // Wait for fade transition
        }
    }, 150); // Slight delay ensures Tailwind paints first
});

// 4. Central Conversion Pipeline Hook for dropzone.js
window.startConversion = async function (filesToProcess) {
    if (typeof window.executePdfConversion === 'function') {
        return await window.executePdfConversion(filesToProcess);
    } else {
        console.error('[Orchestrator] PDF Parser module is missing or crashed during load.');
        if (typeof window.showAlert === 'function') {
            window.showAlert('System Error', 'The PDF Parser module failed to load. Please ensure your script tags are correct in index.html.');
        }
    }
};

// 5. Progressive Web App (PWA) Support
let deferredPrompt;
window.addEventListener('beforeinstallprompt', (e) => {
    // Prevent the mini-infobar from appearing on mobile
    e.preventDefault();
    // Stash the event so it can be triggered later.
    deferredPrompt = e;
});

window.installPWA = async function() {
    if (deferredPrompt) {
        // Show the install prompt
        deferredPrompt.prompt();
        // Wait for the user to respond to the prompt
        const { outcome } = await deferredPrompt.userChoice;
        console.log(`User response to the install prompt: ${outcome}`);
        // We've used the prompt, and can't use it again, throw it away
        deferredPrompt = null;
    } else {
        // Fallback for iOS / Desktop without prompt
        const userAgent = navigator.userAgent || navigator.vendor || window.opera;
        let message = "To install this app:\n\nSelect 'Install App' or 'Add to Home Screen' from your browser menu.";
        
        if (/iPad|iPhone|iPod/.test(userAgent) && !window.MSStream) {
            message = "To install on your iPhone/iPad:\n\nTap the Share button at the bottom of Safari, then select 'Add to Home Screen'.";
        } else if (/android/i.test(userAgent)) {
            message = "To install on Android:\n\nTap the browser menu (⋮), then select 'Install App' or 'Add to Home Screen'.";
        } else if (/Macintosh|Mac OS X/.test(userAgent)) {
            message = "To install on your Mac:\n\nClick the install icon in the Safari/Chrome address bar, or select 'Install App' from the browser menu.";
        } else if (/Windows/.test(userAgent)) {
            message = "To install on Windows:\n\nClick the install icon in the Chrome/Edge address bar, or select 'Install App' from the browser menu.";
        }

        if (typeof window.showAlert === 'function') {
            window.showAlert("Install App", message);
        } else {
            alert(message);
        }
    }
};

if ('serviceWorker' in navigator && window.location.protocol !== 'file:') {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('sw.js').then(reg => {
            console.log('[PWA] Service worker registered.', reg.scope);
        }).catch(err => {
            console.log('[PWA] Service worker registration failed:', err);
        });
    });
}