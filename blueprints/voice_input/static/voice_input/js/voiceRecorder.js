import { AudioVisualizer } from './audioVisualizer.js';

/**
 * VoiceRecorder - Manages audio recording functionality
 */
export class VoiceRecorder {
    constructor(elements) {
        this.elements = elements;
        this.mediaRecorder = null;
        this.mediaStream = null;
        this.audioChunks = [];
        this.recordingStartTime = null;
        this.timerInterval = null;

        this.visualizer = new AudioVisualizer(
            elements.visualizer,
            elements.bars
        );

        this.bindEvents();
    }

    /**
     * Bind event listeners to UI elements
     */
    bindEvents() {
        this.elements.recordBtn.onclick = () => this.startRecording();
        this.elements.stopBtn.onclick = () => this.stopRecording();
        this.elements.sendBtn.onclick = () => this.sendRecording();
    }

    /**
     * Update status message with optional type (error/success)
     */
    updateStatus(message, type = '') {
        this.elements.status.textContent = message;
        this.elements.status.className = type;
    }

    /**
     * Update the recording timer display
     */
    updateTimer() {
        if (!this.recordingStartTime) return;

        const elapsed = Math.floor((Date.now() - this.recordingStartTime) / 1000);
        const minutes = Math.floor(elapsed / 60);
        const seconds = elapsed % 60;
        this.elements.timer.textContent = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    /**
     * Start the recording timer
     */
    startTimer() {
        this.recordingStartTime = Date.now();
        this.updateTimer();
        this.timerInterval = setInterval(() => this.updateTimer(), 1000);
    }

    /**
     * Stop the recording timer
     */
    stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
        this.recordingStartTime = null;
    }

    /**
     * Request audio stream with quality settings
     */
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

    /**
     * Get the best supported MIME type for recording
     */
    getSupportedMimeType() {
        const types = [
            'audio/webm;codecs=opus',
            'audio/webm',
            'audio/ogg;codecs=opus',
            'audio/mp4'
        ];

        return types.find(type => MediaRecorder.isTypeSupported(type)) || '';
    }

    /**
     * Start recording audio
     */
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

    /**
     * Stop the current recording
     */
    stopRecording() {
        if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
            this.mediaRecorder.stop();
        }
    }

    /**
     * Send the recorded audio to the server for transcription
     */
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

            const extension = mimeType.includes('webm') ? 'webm' : mimeType.includes('ogg') ? 'ogg' : 'mp4';

            const formData = new FormData();
            formData.append('audio', blob, `voice.${extension}`);

            const response = await fetch('/voice/transcribe', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            const data = await response.json();

            if (data.text) {
                this.updateStatus(`Transcription: "${data.text}"`, 'success');
            } else if (data.error) {
                this.updateStatus(`Error: ${data.error}`, 'error');
            } else {
                this.updateStatus('Transcription complete', 'success');
            }

            this.audioChunks = [];
            this.elements.timer.textContent = '00:00';

        } catch (err) {
            console.error('Upload failed:', err);
            this.updateStatus(`Upload failed: ${err.message}`, 'error');
        } finally {
            this.elements.sendBtn.disabled = false;
        }
    }

    /**
     * Clean up resources and reset state
     */
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