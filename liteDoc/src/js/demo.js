
// demo
async function loadSamplePDF() {
    window.showProgressState(true);
    window.logToTerminal('Loading demo document...', 'warn');
    window.updateProgress(15, 'Opening virtual file descriptor...', 'Initializing PDF.js worker');
    await sleep(800);
    window.updateProgress(45, 'Scanning page contents...', 'Analyzing layout and text layers');
    window.logToTerminal('Beginning text extraction...');
    await sleep(1000);
    window.updateProgress(75, 'Extracting images...', 'Compressing to match resolution preset');
    window.logToTerminal('Compressed academic_paper_v3.pdf_p2_img1.jpg to match preset parameters.');
    await sleep(500);

    const generatedMd = `\x3C!-- Converted from academic_paper_v3.pdf — 3 pages --\x3E

## Page 1
# Abstract: Deep Structural Neural Mapping Architecture
Deep learning strategies often fail when executing unstructured inputs directly.

The loss function is defined as:

$$L(\\theta) = -\\frac{1}{N}\\sum_{i=1}^{N} \\left[ y_i \\log(\\hat{y}_i) + (1-y_i)\\log(1-\\hat{y}_i) \\right]$$

Where the gradient update rule is $\\theta \\leftarrow \\theta - \\eta \\nabla_\\theta L(\\theta)$.

## Page 2
[IMAGE: academic_paper_v3.pdf_p2_img1.jpg]
[IMAGE: academic_paper_v3.pdf_p2_img2.jpg]

## Page 3
### Arabic Sample / نموذج عربي
يُعدّ هذا التطبيق أداةً مجانيةً لتحويل ملفات PDF إلى صيغة Markdown.
جميع العمليات تتم محليًا في متصفحك دون رفع أي ملف إلى خوادم خارجية.

Euler's identity: $e^{i\\pi} + 1 = 0$`;

    const sampleImages = [
        {
            name: 'academic_paper_v3.pdf_p2_img1.jpg',
            dataUrl: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='400' height='200' viewBox='0 0 400 200'><rect width='100%' height='100%' fill='%23121524'/><text x='50%' y='50%' font-family='sans-serif' font-size='16' fill='%236366f1' dominant-baseline='middle' text-anchor='middle'>Diagram: Spatial Grid Flow Map</text></svg>"
        },
        {
            name: 'academic_paper_v3.pdf_p2_img2.jpg',
            dataUrl: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='400' height='200' viewBox='0 0 400 200'><rect width='100%' height='100%' fill='%23121524'/><text x='50%' y='50%' font-family='sans-serif' font-size='16' fill='%23a855f7' dominant-baseline='middle' text-anchor='middle'>Plot: Epoch Metrics Progression Chart</text></svg>"
        }
    ];

    state.processedData = [{ filename: 'academic_paper_v3.pdf', status: 'success', mdText: generatedMd, extractedImages: sampleImages, viewMode: 'raw' }];

    if (typeof window.renderFileToTree === 'function') {
        document.getElementById('output-area').classList.remove('hidden');
        document.getElementById('dynamic-tree-content').innerHTML = '';
        window.renderFileToTree(state.processedData[0], 0);
        window.selectVirtualFile(0, 'md');
    }
    window.showProgressState(false);
    if (typeof window.updateSavingsUI === 'function') window.updateSavingsUI();
    setTimeout(() => { if (typeof window.showDonationToast === 'function') window.showDonationToast(); }, 1500);
}
