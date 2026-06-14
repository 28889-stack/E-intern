
// exports
async function copyMarkdownText() {
    if (!state.processedData.length) return;
    if (state.currentViewMode === 'edit' && state.activeDataIndex !== null && window.mdEditor) {
        state.processedData[state.activeDataIndex].mdText = window.mdEditor.getValue();
    }
    const fullMd = state.processedData.map(d => d.mdText).join('\n\n---\n\n');
    try {
        await navigator.clipboard.writeText(fullMd);
        window.showAlert('Copied', 'Markdown copied to clipboard.');
    } catch {
        window.showAlert('Error', 'Clipboard access was denied.');
    }
}

function downloadMarkdown(fIndex) {
    const data = state.processedData[fIndex];
    const blob = new Blob([data.mdText], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = data.filename.replace('.pdf', '') + '.md';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadImage(fIndex, iIndex) {
    const img = state.processedData[fIndex].extractedImages[iIndex];
    const a = document.createElement('a');
    a.href = img.dataUrl; a.download = img.name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

async function downloadZip() {
    if (!state.processedData.length) return;
    window.logToTerminal('Assembling workspace ZIP structure...');
    const zip = new JSZip();
    for (const data of state.processedData) {
        if (data.status === 'failed') continue;
        zip.file(data.filename.replace('.pdf', '') + '.md', data.mdText);
        if (data.extractedImages.length) {
            const folder = zip.folder(`_pdf_images_${data.filename}`);
            for (const img of data.extractedImages) {
                const res = await fetch(img.dataUrl);
                const blob = await res.blob();
                folder.file(img.name, blob);
            }
        }
    }
    try {
        const content = await zip.generateAsync({ type: 'blob' });
        const url = URL.createObjectURL(content);
        const a = document.createElement('a');
        a.href = url; a.download = 'litedoc_workspace.zip';
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        window.logToTerminal('ZIP generation complete.', 'success');
    } catch {
        window.showAlert('Compression Failed', 'Error generating ZIP archive.');
    }
}

window.copyMarkdownText = copyMarkdownText;
window.downloadMarkdown = downloadMarkdown;
window.downloadImage = downloadImage;
window.downloadZip = downloadZip;
