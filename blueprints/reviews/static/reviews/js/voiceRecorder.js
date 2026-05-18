/**
 * VoiceRecorder — adapted for review form.
 * onSuccess(data) callback receives the JSON response from /voice/transcribe.
 */
(function(window) {
  'use strict';

  class VoiceRecorder {
    constructor(elements, options = {}) {
      this.elements = elements;
      this.options  = options;
      this.mediaRecorder = null;
      this.mediaStream   = null;
      this.audioChunks   = [];
      this.recordingStartTime = null;
      this.timerInterval = null;

      this.visualizer = new window.AudioVisualizer(
        elements.visualizer,
        elements.bars
      );

      this.bindEvents();
    }

    bindEvents() {
      this.elements.recordBtn.onclick = () => this.startRecording();
      this.elements.stopBtn.onclick   = () => this.stopRecording();
      this.elements.sendBtn.onclick   = () => this.sendRecording();
    }

    updateStatus(message, type = '') {
      this.elements.status.textContent = message;
      this.elements.status.className   = 'recorder-status ' + type;
    }

    updateTimer() {
      if (!this.recordingStartTime) return;
      const elapsed = Math.floor((Date.now() - this.recordingStartTime) / 1000);
      const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
      const ss = String(elapsed % 60).padStart(2, '0');
      this.elements.timer.textContent = `${mm}:${ss}`;
    }

    startTimer() {
      this.recordingStartTime = Date.now();
      this.updateTimer();
      this.timerInterval = setInterval(() => this.updateTimer(), 1000);
    }

    stopTimer() {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
      this.recordingStartTime = null;
    }

    async getAudioStream() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Your browser does not support audio recording');
      }
      return navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });
    }

    getSupportedMimeType() {
      const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
      return types.find(t => MediaRecorder.isTypeSupported(t)) || '';
    }

    async startRecording() {
      this.updateStatus('Requesting microphone access…');
      this.audioChunks = [];

      try {
        const stream = await this.getAudioStream();
        this.mediaStream = stream;

        const mimeType = this.getSupportedMimeType();
        if (!mimeType) throw new Error('No supported audio format found');

        this.mediaRecorder = new MediaRecorder(stream, { mimeType });

        this.mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) this.audioChunks.push(e.data);
        };

        this.mediaRecorder.onstart = () => {
          this.elements.recordBtn.disabled = true;
          this.elements.recordBtn.classList.add('recording');
          this.elements.recordText.textContent = 'Recording…';
          this.elements.stopBtn.disabled = false;
          this.elements.sendBtn.disabled = true;
          this.updateStatus('Recording in progress…');
          this.startTimer();
          this.visualizer.start(stream);
        };

        this.mediaRecorder.onstop = () => {
          this.elements.recordBtn.disabled = false;
          this.elements.recordBtn.classList.remove('recording');
          this.elements.recordText.textContent = 'Record';
          this.elements.stopBtn.disabled = true;
          this.elements.sendBtn.disabled = false;
          this.stopTimer();
          this.visualizer.stop();

          if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(t => t.stop());
            this.mediaStream = null;
          }

          this.updateStatus(`Done (${this.elements.timer.textContent}) — click Send to transcribe`, 'success');
        };

        this.mediaRecorder.onerror = () => {
          this.updateStatus('Recording error', 'error');
          this.cleanup();
        };

        this.mediaRecorder.start(100);
      } catch (err) {
        this.updateStatus(`Error: ${err.message}`, 'error');
        this.cleanup();
      }
    }

    stopRecording() {
      if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
        this.mediaRecorder.stop();
      }
    }

    async sendRecording() {
      if (!this.audioChunks.length) {
        this.updateStatus('No audio recorded', 'error');
        return;
      }

      this.elements.sendBtn.disabled = true;
      this.updateStatus('Transcribing…');

      try {
        const mimeType  = this.mediaRecorder?.mimeType || 'audio/webm';
        const extension = mimeType.includes('webm') ? 'webm' : mimeType.includes('ogg') ? 'ogg' : 'mp4';
        const blob      = new Blob(this.audioChunks, { type: mimeType });

        const formData = new FormData();
        formData.append('audio', blob, `voice.${extension}`);

        const response = await fetch('/voice/transcribe', { method: 'POST', body: formData });

        if (!response.ok) throw new Error(`Server error: ${response.status}`);

        const data = await response.json();

        if (data.error) {
          this.updateStatus(`Error: ${data.error}`, 'error');
          this.elements.sendBtn.disabled = false;
          return;
        }

        if (typeof this.options.onSuccess === 'function') {
          this.options.onSuccess(data);
        } else {
          this.updateStatus(data.text ? `Got: "${data.text}"` : 'Done', 'success');
          this.elements.sendBtn.disabled = false;
        }

        this.audioChunks = [];
        this.elements.timer.textContent = '00:00';
      } catch (err) {
        this.updateStatus(`Upload failed: ${err.message}`, 'error');
        this.elements.sendBtn.disabled = false;
      }
    }

    cleanup() {
      this.stopTimer();
      this.visualizer.stop();
      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach(t => t.stop());
        this.mediaStream = null;
      }
      this.mediaRecorder = null;
      this.elements.recordBtn.disabled = false;
      this.elements.recordBtn.classList.remove('recording');
      this.elements.recordText.textContent = 'Record';
      this.elements.stopBtn.disabled = true;
    }
  }

  window.VoiceRecorder = VoiceRecorder;
})(window);
