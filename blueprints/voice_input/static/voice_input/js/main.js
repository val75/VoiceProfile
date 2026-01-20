import { VoiceRecorder } from './voiceRecorder.js';

/**
 * Initialize the voice recorder application
 */
function initializeApp() {
    const elements = {
        status: document.getElementById('status'),
        recordBtn: document.getElementById('record'),
        stopBtn: document.getElementById('stop'),
        sendBtn: document.getElementById('send'),
        timer: document.getElementById('timer'),
        recordText: document.getElementById('recordText'),
        visualizer: document.getElementById('visualizer'),
        bars: document.querySelectorAll('.bar')
    };

    const recorder = new VoiceRecorder(elements);

    console.log('Voice recorder initialized');
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeApp);
} else {
  initializeApp();
}