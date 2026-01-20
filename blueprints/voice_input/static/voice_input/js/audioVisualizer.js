/**
 * AudioVisualizer - Handles real-time audio visualization
 */

export class AudioVisualizer {
    constructor(visualizerElement, bars) {
        this.visualizerElement = visualizerElement;
        this.bars = bars;
        this.audioContext = null;
        this.analyser = null;
        this.animationFrame = null;
    }

    /**
     * Start visualizing audio from a media stream
     */
    start(stream) {
        this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        this.analyser = this.audioContext.createAnalyser();
        const source = this.audioContext.createMediaStreamSource(stream);
        source.connect(this.analyser);
        this.analyser.fftSize = 256;

        const bufferLength = this.analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        const animate = () => {
            this.animationFrame = requestAnimationFrame(animate);
            this.analyser.getByteFrequencyData(dataArray);

            this.bars.forEach((bar, i) => {
                const value = dataArray[i * 8] || 0;
                const height = Math.max(10, (value / 255) * 60);
                bar.style.height = `${height}px`;
            });
        };

        this.visualizerElement.classList.add('active');
        animate();
    }

    /**
     * Stop visualization and clean up resources
     */
    stop() {
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        this.visualizerElement.classList.remove('active');
    }
}