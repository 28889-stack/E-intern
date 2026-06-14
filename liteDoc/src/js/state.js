window.isSyncingAce = false;

window.state = {
    selectedImgRes: 0,
    processedData: [],
    activeDataIndex: null, // default to null until a file is selected
    mathEnabled: true,
    currentViewMode: 'raw',
    currentViewType: 'md',
    rawTextMode: false,
    currentImageIndex: null,
    splitRatio: 50,
    pendingFiles: [],
    hasUnsavedChanges: false,
    isEditing: false,
    isSkippingFile: false,
};

window.skipCurrentFile = function () {
    window.state.isSkippingFile = true;
    if (window.logToTerminal) {
        window.logToTerminal('Skipping current file...', 'warn');
    }
    if (window.__litedocAddons && window.__litedocAddons.clearOcrQueue) window.__litedocAddons.clearOcrQueue();
};
