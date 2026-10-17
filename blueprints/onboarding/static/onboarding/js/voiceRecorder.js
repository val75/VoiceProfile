/**
 * VoiceRecorder - Manages audio recording functionality
 *
 * One button drives the whole take, and its label, icon and color always
 * show the next step:
 *
 *   idle ──tap──▶ recording ──tap/time limit──▶ recorded ──tap──▶ sending
 *    ▲                                            │                 │
 *    └──────────────── Record again ──────────────┘   error ◀───────┘
 *                                                  (back to recorded)
 */

(function(window) {
  'use strict';

  const ICONS = {
    mic:  '<svg viewBox="0 0 24 24"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11h-2z"/></svg>',
    stop: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
    text: '<svg viewBox="0 0 24 24"><path d="M4 3h16a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zm2 4v2h12V7H6zm0 4v2h8v-2H6z"/></svg>',
    spinner: '<span class="spinner"></span>'
  };

  // Idle status comes from the page (a per-question prompt), so it's not here.
  const STATES = {
    idle:      { label: 'Record',        icon: ICONS.mic },
    recording: { label: 'Stop',          icon: ICONS.stop,    status: 'Recording… tap Stop when you finish.' },
    recorded:  { label: 'Transcribe',    icon: ICONS.text,    status: 'Done! Tap Transcribe, or record again.' },
    sending:   { label: 'Transcribing…', icon: ICONS.spinner, status: 'Turning your words into text…' }
  };

  class VoiceRecorder {
    /**
     * @param {object} elements  - DOM element refs: status, recordBtn,
     *                             recordIcon, recordLabel, againBtn, controls,
     *                             timer, visualizer, bars
     * @param {object} [options] - Optional config:
     *   options.transcribeUrl  {string}   - POST endpoint. Falls back to the
     *                                       hidden #transcribeUrl field, then
     *                                       '/voice/transcribe'.
     *   options.onSuccess      {function} - Called with the parsed JSON response
     *                                       after a successful transcription.
     *                                       When provided, the caller owns the
     *                                       screen until it calls reset().
     */
    constructor(elements, options = {}) {
      this.elements = elements;
      this.options  = options;
      this.mediaRecorder = null;
      this.mediaStream = null;
      this.audioChunks = [];
      this.recordingStartTime = null;
      this.lastDurationMs = null;   // length of the last finished recording
      this.timerInterval = null;
      this.idleStatus = elements.status.textContent;

      this.visualizer = new window.AudioVisualizer(
        elements.visualizer,
        elements.bars
      );

      this.bindEvents();
      this.setState('idle');
    }

    // ------------------------------------------------------------------
    // Optional hard cap on recording length. Returns a positive integer
    // (seconds) or null if no cap is in effect. Constructor option wins,
    // then a hidden #maxSeconds field on the page.
    // ------------------------------------------------------------------
    getMaxSeconds() {
      const fromOption = parseInt(this.options.maxSeconds, 10);
      if (Number.isFinite(fromOption) && fromOption > 0) {
        return fromOption;
      }
      const el = document.getElementById('maxSeconds');
      if (el && el.value) {
        const fromField = parseInt(el.value, 10);
        if (Number.isFinite(fromField) && fromField > 0) {
          return fromField;
        }
      }
      return null;
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
      this.elements.recordBtn.onclick = () => {
        if (this.state === 'idle') this.startRecording();
        else if (this.state === 'recording') this.stopRecording();
        else if (this.state === 'recorded') this.sendRecording();
      };
      this.elements.againBtn.onclick = () => this.reset();
    }

    // ------------------------------------------------------------------
    // Single place that updates the button and status for a state.
    // `message` overrides the state's default status line.
    // ------------------------------------------------------------------
    setState(state, message, type = '') {
      const s = STATES[state];
      const btn = this.elements.recordBtn;

      this.state = state;
      btn.dataset.state = state;
      btn.disabled = state === 'sending';
      this.elements.recordIcon.innerHTML = s.icon;
      this.elements.recordLabel.textContent = s.label;
      this.elements.againBtn.hidden = state !== 'recorded';
      this.elements.timer.classList.toggle('live', state === 'recording');
      this.updateStatus(message ?? s.status ?? this.idleStatus, type);
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

      const max = this.maxSeconds;
      if (max) {
        if (elapsed >= max - 30) {
          this.elements.timer.classList.add('near-limit');
        }
        if (elapsed >= max) {
          this.stopRecording();
        }
      }
    }

    startTimer() {
      this.recordingStartTime = Date.now();
      this.maxSeconds = this.getMaxSeconds();   // cache per recording
      this.elements.timer.classList.remove('near-limit');
      this.updateTimer();
      this.timerInterval = setInterval(() => this.updateTimer(), 1000);
    }

    stopTimer() {
      if (this.timerInterval) {
        clearInterval(this.timerInterval);
        this.timerInterval = null;
      }
      if (this.recordingStartTime) {
        this.lastDurationMs = Date.now() - this.recordingStartTime;
      }
      this.recordingStartTime = null;
      this.elements.timer.classList.remove('near-limit');
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
      // Block double taps while the browser asks for the microphone.
      this.elements.recordBtn.disabled = true;
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
          this.setState('recording');
          this.startTimer();
          this.visualizer.start(stream);
        };

        this.mediaRecorder.onstop = () => {
          this.stopTimer();
          this.visualizer.stop();
          this.releaseStream();
          this.setState('recorded');
        };

        this.mediaRecorder.onerror = (e) => {
          console.error('MediaRecorder error:', e);
          this.cleanup();
          this.setState('idle', 'Recording error occurred', 'error');
        };

        this.mediaRecorder.start(100);

      } catch (err) {
        console.error('Failed to start recording:', err);
        this.cleanup();
        const message = err.name === 'NotAllowedError'
          ? 'The microphone is blocked. Allow it in your browser settings, then tap Record.'
          : `Error: ${err.message}`;
        this.setState('idle', message, 'error');
      }
    }

    stopRecording() {
      if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
        this.mediaRecorder.stop();
      }
    }

    async sendRecording() {
      if (!this.audioChunks.length) {
        this.setState('idle', 'No audio recorded', 'error');
        return;
      }

      this.setState('sending');

      try {
        const mimeType = this.mediaRecorder?.mimeType || 'audio/webm';
        const blob = new Blob(this.audioChunks, { type: mimeType });

        const extension = mimeType.includes('webm') ? 'webm' :
                         mimeType.includes('ogg') ? 'ogg' : 'mp4';

        const formData = new FormData();
        formData.append('audio', blob, `voice.${extension}`);

        const questionId = document.getElementById('questionId').value;
        formData.append('question_id', questionId);
        if (this.lastDurationMs != null) {
          formData.append('duration_ms', String(this.lastDurationMs));
        }

        const response = await fetch(this.getTranscribeUrl(), {
          method: 'POST',
          body: formData
        });

        // Error bodies are JSON ({"error": ...}) for 4xx/502; anything else is a server fault.
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.error) {
          throw new Error(data.error || `Server error: ${response.status}`);
        }

        // If a caller-supplied callback exists, hand off the response and
        // let it own the next steps (e.g. showing a confirmation panel).
        if (typeof this.options.onSuccess === 'function') {
          this.elements.controls.hidden = true;
          this.options.onSuccess(data);
        } else {
          // Default behaviour: show the plain transcription text.
          this.reset();
          this.updateStatus(
            data.text ? `Transcription: "${data.text}"` : 'Transcription complete',
            'success'
          );
        }

      } catch (err) {
        // Keep the take so the worker can retry without recording again.
        console.error('Transcription failed:', err);
        this.setState('recorded', "Couldn't turn that into text. Tap Transcribe to try again.", 'error');
      }
    }

    // ------------------------------------------------------------------
    // Throw the take away and show the Record button again. Also used by
    // callers (the confirm panel's Re-record) after onSuccess.
    // ------------------------------------------------------------------
    reset() {
      this.audioChunks = [];
      this.elements.timer.textContent = '00:00';
      this.elements.controls.hidden = false;
      this.setState('idle');
    }

    releaseStream() {
      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach(track => track.stop());
        this.mediaStream = null;
      }
    }

    cleanup() {
      this.stopTimer();
      this.visualizer.stop();
      this.releaseStream();
      this.mediaRecorder = null;
    }
  }

  window.VoiceRecorder = VoiceRecorder;

})(window);
