/**
 * VoiceRecorder - Manages audio recording functionality
 */

(function(window) {
  'use strict';

  class VoiceRecorder {
    /**
     * @param {object} elements  - DOM element refs (unchanged)
     * @param {object} [options] - Optional config:
     *   options.transcribeUrl  {string}   - POST endpoint. Falls back to the
     *                                       hidden #transcribeUrl field, then
     *                                       '/voice/transcribe'.
     *   options.onSuccess      {function} - Called with the parsed JSON response
     *                                       after a successful transcription.
     *                                       When provided, the caller owns the
     *                                       status message for that case.
     */
    constructor(elements, options = {}) {
      this.elements = elements;
      this.options  = options;
      this.mediaRecorder = null;
      this.mediaStream = null;
      this.audioChunks = [];
      this.recordingStartTime = null;
      this.timerInterval = null;

      this.visualizer = new window.AudioVisualizer(
        elements.visualizer,
        elements.bars
      );

      this.bindEvents();
    }

    // ------------------------------------------------------------------
    // Resolve the transcribe URL at send-time (so the hidden field is
    // guaranteed to exist in the DOM when we read it).
    // ------------------------------------------------------------------
    getTranscribeUrl() {
      if (this.options.transcribeUrl) {
        return this.options.transcribeUrl;
      }
      const el = document.getElementById('transcribeUrl');
      if (el && el.value) {
        return el.value;
      }
      return '/voice/transcribe';
    }

    bindEvents() {
      this.elements.recordBtn.onclick = () => this.startRecording();
      this.elements.stopBtn.onclick = () => this.stopRecording();
      this.elements.sendBtn.onclick = () => this.sendRecording();
    }

    updateStatus(message, type = '') {
      this.elements.status.textContent = message;
      this.elements.status.className = type;
    }

    updateTimer() {
      if (!this.recordingStartTime) return;

      const elapsed = Math.floor((Date.now() - this.recordingStartTime) / 1000);
      const minutes = Math.floor(elapsed / 60);
      const seconds = elapsed % 60;
      this.elements.timer.textContent =
        `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    startTimer() {
      this.recordingStartTime = Date.now();
      this.updateTimer();
      this.timerInterval = setInterval(() => this.updateTimer(), 1000);
    }

    stopTimer() {
      if (this.timerInterval) {
        clearInterval(this.timerInterval);
        this.timerInterval = null;
      }
      this.recordingStartTime = null;
    }

    async getAudioStream() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Your browser does not support audio recording');
      }

      return navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
    }

    getSupportedMimeType() {
      const types = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/ogg;codecs=opus',
        'audio/mp4'
      ];

      return types.find(type => MediaRecorder.isTypeSupported(type)) || '';
    }

    async startRecording() {
      this.updateStatus('Requesting microphone access...', '');
      this.audioChunks = [];

      try {
        const stream = await this.getAudioStream();
        this.mediaStream = stream;

        const mimeType = this.getSupportedMimeType();
        if (!mimeType) {
          throw new Error('No supported audio format found');
        }

        this.mediaRecorder = new MediaRecorder(stream, { mimeType });

        this.mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) {
            this.audioChunks.push(e.data);
          }
        };

        this.mediaRecorder.onstart = () => {
          this.elements.recordBtn.disabled = true;
          this.elements.recordBtn.classList.add('recording');
          this.elements.recordText.textContent = 'Recording...';
          this.elements.stopBtn.disabled = false;
          this.elements.sendBtn.disabled = true;
          this.updateStatus('Recording in progress...', '');
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
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
          }

          const duration = this.elements.timer.textContent;
          this.updateStatus(`Recording complete (${duration})`, 'success');
        };

        this.mediaRecorder.onerror = (e) => {
          console.error('MediaRecorder error:', e);
          this.updateStatus('Recording error occurred', 'error');
          this.cleanup();
        };

        this.mediaRecorder.start(100);

      } catch (err) {
        console.error('Failed to start recording:', err);
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
      this.updateStatus('Uploading and transcribing...', '');

      try {
        const mimeType = this.mediaRecorder?.mimeType || 'audio/webm';
        const blob = new Blob(this.audioChunks, { type: mimeType });

        const extension = mimeType.includes('webm') ? 'webm' :
                         mimeType.includes('ogg') ? 'ogg' : 'mp4';

        const formData = new FormData();
        formData.append('audio', blob, `voice.${extension}`);

        const questionId = document.getElementById('questionId').value;
        formData.append('question_id', questionId);

        const response = await fetch(this.getTranscribeUrl(), {
          method: 'POST',
          body: formData
        });

        if (!response.ok) {
          throw new Error(`Server error: ${response.status}`);
        }

        const data = await response.json();

        if (data.error) {
          this.updateStatus(`Error: ${data.error}`, 'error');
          this.elements.sendBtn.disabled = false;
          return;
        }

        // If a caller-supplied callback exists, hand off the response and
        // let it own the next steps (e.g. showing a confirmation panel).
        if (typeof this.options.onSuccess === 'function') {
          this.options.onSuccess(data);
        } else {
          // Default behaviour: show the plain transcription text.
          if (data.text) {
            this.updateStatus(`Transcription: "${data.text}"`, 'success');
          } else {
            this.updateStatus('Transcription complete', 'success');
          }
          this.elements.sendBtn.disabled = false;
        }

        // Reset audio buffer and timer for a potential re-record.
        this.audioChunks = [];
        this.elements.timer.textContent = '00:00';

      } catch (err) {
        console.error('Upload failed:', err);
        this.updateStatus(`Upload failed: ${err.message}`, 'error');
        this.elements.sendBtn.disabled = false;
      }
    }

    cleanup() {
      this.stopTimer();
      this.visualizer.stop();

      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach(track => track.stop());
        this.mediaStream = null;
      }

      if (this.mediaRecorder) {
        this.mediaRecorder = null;
      }

      this.elements.recordBtn.disabled = false;
      this.elements.recordBtn.classList.remove('recording');
      this.elements.recordText.textContent = 'Record';
      this.elements.stopBtn.disabled = true;
    }
  }

  window.VoiceRecorder = VoiceRecorder;

})(window);