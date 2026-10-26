class PcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 1600;
    this.buffer = new Float32Array(this.bufferSize);
    this.offset = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (input && input[0]) {
      const channel = input[0];
      for (let i = 0; i < channel.length; i += 1) {
        this.buffer[this.offset] = channel[i];
        this.offset += 1;
        if (this.offset === this.bufferSize) {
          this.port.postMessage(this.buffer.slice(0));
          this.offset = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor('pcm-processor', PcmProcessor);
