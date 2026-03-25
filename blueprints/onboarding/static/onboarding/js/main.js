/**
 * Initialize the voice recorder application
 */

(function() {
  'use strict';

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

    if (typeof window.VoiceRecorder === 'undefined') {
      console.error('VoiceRecorder class not found.');
      elements.status.textContent = 'Error: Required scripts not loaded';
      elements.status.className = 'error';
      return;
    }

    const recorder = new window.VoiceRecorder(elements);

    console.log('Voice recorder initialized successfully');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApp);
  } else {
    initializeApp();
  }
})();