const TARGET_SAMPLE_RATE = 16000;

function floatToInt16(input) {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, input[i]));
    output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return output;
}

function describeCaptureError(error) {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return 'L’accès au micro a été refusé. Autorisez le micro dans votre navigateur puis réessayez.';
    }
    if (error.name === 'NotFoundError') {
      return 'Aucun micro n’a été trouvé. Connectez un micro puis réessayez.';
    }
  }
  return error instanceof Error ? error.message : 'L’accès au micro a échoué';
}

export class AudioCapture {
  constructor({ onChunk, workletUrl, onStatusChange, onError } = {}) {
    this.onChunk = onChunk || (() => {});
    this.workletUrl = workletUrl;
    this.onStatusChange = onStatusChange || (() => {});
    this.onError = onError || (() => {});
    this.status = 'idle';
    this.error = null;
    this.sampleRate = null;
    this.stream = null;
    this.context = null;
    this.node = null;
    this.source = null;
    this.gain = null;
  }

  setStatus(status) {
    this.status = status;
    this.onStatusChange(status);
  }

  teardown() {
    if (this.node) {
      this.node.port.onmessage = null;
      this.node.disconnect();
      this.node = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.gain) {
      this.gain.disconnect();
      this.gain = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }
    if (this.context) {
      void this.context.close();
      this.context = null;
    }
  }

  stop() {
    this.teardown();
    this.sampleRate = null;
    this.setStatus('idle');
  }

  async start() {
    this.setStatus('requesting');
    this.error = null;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      this.stream = stream;

      const context = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
      if (context.state === 'suspended') {
        await context.resume();
      }
      this.context = context;

      await context.audioWorklet.addModule(this.workletUrl);

      const source = context.createMediaStreamSource(stream);
      this.source = source;

      const node = new AudioWorkletNode(context, 'pcm-processor');
      node.port.onmessage = (event) => {
        this.onChunk(floatToInt16(event.data));
      };
      this.node = node;

      const gain = context.createGain();
      gain.gain.value = 0;
      this.gain = gain;

      source.connect(node);
      node.connect(gain);
      gain.connect(context.destination);

      this.sampleRate = context.sampleRate;
      this.setStatus('active');
      return this.sampleRate;
    } catch (error) {
      console.error('[AudioCapture] failed to start:', error);
      this.teardown();
      this.error = describeCaptureError(error);
      this.onError(this.error);
      this.setStatus('error');
      throw error;
    }
  }
}
