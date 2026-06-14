/**
 * LiteDoc - Hardware Benchmarking Tool
 */

// Initialize PDF.js Worker (build.py will patch this URL with a data URI)
if (typeof pdfjsLib !== 'undefined' && !pdfjsLib.GlobalWorkerOptions.workerSrc) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
}

const benchmarkBtn = document.getElementById('run-benchmark-btn');
if (benchmarkBtn) {
    benchmarkBtn.addEventListener('click', runBenchmark);
}

async function runBenchmark() {
    const runBtn = document.getElementById('run-benchmark-btn');
    const resultsCard = document.getElementById('results-card');
    const logCard = document.getElementById('log-card');
    const logEl = document.getElementById('benchmark-log');
    
    runBtn.disabled = true;
    runBtn.textContent = 'Benchmarking...';
    logCard.classList.remove('hidden');
    logEl.innerHTML = '';

    try {
        // 1. Engine Spin-Up
        logToTerminal('Phase 1: Measuring Engine Spin-Up...');
        const t0 = performance.now();
        
        // Force-load worker by doing a tiny conversion
        const dummyPdf = await createDummyPdf();
        await window.executePdfConversion([dummyPdf]);
        
        const spinUpTime = Math.round(performance.now() - t0);
        document.getElementById('spin-up-time').textContent = `${spinUpTime}ms`;
        logToTerminal(`Spin-up complete: ${spinUpTime}ms`);

        // 2. PPT (Pages Per Toast - Synthetic Burst)
        logToTerminal('Phase 2: Measuring Burst Throughput (PPT)...');
        logToTerminal('Downloading tracemonkey.pdf (14 pages)...');
        const testPdf = await fetchTestPdf('https://raw.githubusercontent.com/mozilla/pdf.js/master/test/pdfs/tracemonkey.pdf', 'tracemonkey.pdf');
        
        const t1 = performance.now();
        await window.executePdfConversion([testPdf]);
        const burstTime = performance.now() - t1;
        
        const numPages = state.processedData[0].numPages;
        const ppt = Math.round((numPages / (burstTime / 1000)) * 10) / 10;
        document.getElementById('ppt-metric').textContent = ppt;
        logToTerminal(`Burst test: ${numPages} pages in ${Math.round(burstTime)}ms (PPT: ${ppt})`);

        // 3. PPM (Pages Per Minute - Sustained)
        logToTerminal('Phase 3: Measuring Sustained Throughput (PPM)...');
        const iterations = 3;
        let totalPages = 0;
        const t2 = performance.now();
        
        for (let i = 0; i < iterations; i++) {
            logToTerminal(`Iteration ${i+1}/${iterations}...`);
            await window.executePdfConversion([testPdf]);
            totalPages += state.processedData[0].numPages;
        }
        
        const sustainedTime = performance.now() - t2;
        const ppm = Math.round((totalPages / (sustainedTime / 60000)));
        document.getElementById('ppm-metric').textContent = ppm;
        logToTerminal(`Sustained test: ${totalPages} pages in ${Math.round(sustainedTime)}ms (PPM: ${ppm})`);

        logToTerminal('Benchmark complete!');
        document.getElementById('copy-results-btn').classList.remove('hidden');
    } catch (error) {
        logToTerminal(`Error during benchmark: ${error.message}`, 'error');
        console.error(error);
    } finally {
        runBtn.disabled = false;
        runBtn.textContent = 'Run Benchmark Again';
    }
}

async function createDummyPdf() {
    // Just a tiny valid PDF structure or a very small fetch
    return await fetchTestPdf('https://raw.githubusercontent.com/mozilla/pdf.js/master/test/pdfs/basicapi.pdf', 'basicapi.pdf');
}

async function fetchTestPdf(url, name) {
    const response = await fetch(url);
    if (!response.ok) throw new Error("Failed to download benchmark PDF");
    const blob = await response.blob();
    return new File([blob], name, { type: 'application/pdf' });
}



const copyBtn = document.getElementById('copy-results-btn');
if (copyBtn) {
    copyBtn.addEventListener('click', () => {
    const spinUp = document.getElementById('spin-up-time').textContent;
    const ppt = document.getElementById('ppt-metric').textContent;
    const ppm = document.getElementById('ppm-metric').textContent;
    const log = document.getElementById('benchmark-log').innerText;
    
    const results = `LiteDoc Hardware Benchmark\n--------------------------\nEngine Spin-Up: ${spinUp}\nBurst Throughput: ${ppt} PPT\nSustained Throughput: ${ppm} PPM\n\nLog:\n${log}`;
    
    navigator.clipboard.writeText(results).then(() => {
        const btn = document.getElementById('copy-results-btn');
        const orig = btn.innerHTML;
        btn.innerHTML = `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg> Copied!`;
        setTimeout(() => { btn.innerHTML = orig; }, 2000);
    });
    });
}
