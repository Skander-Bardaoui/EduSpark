import { csrfHeaders } from './csrf.js';

const FFT_SIZE = 256;

export class ExaminerAudio {
  constructor({ language = 'en', locale = 'en-US', ttsUrl, onStatusChange, onError } = {}) {
    this.language = language;
    this.locale = locale;
    this.ttsUrl = ttsUrl;
    this.onStatusChange = onStatusChange || (() => {});
    this.onError = onError || (() => {});
    this.status = 'idle';
    this.error = null;
    this.context = null;
    this.analyser = null;
    this.source = null;
  }

  setStatus(status) {
    this.status = status;
    this.onStatusChange(status);
  }

  getContext() {
    if (this.context === null) {
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = FFT_SIZE;
      analyser.connect(context.destination);
      this.context = context;
      this.analyser = analyser;
    }
    return this.context;
  }

  stop() {
    if (this.source) {
      this.source.onended = null;
      this.source.disconnect();
      this.source = null;
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    this.setStatus('idle');
  }

  speakWithBrowser(text) {
    if (!('speechSynthesis' in window) || typeof window.SpeechSynthesisUtterance !== 'function') {
      this.error = 'La lecture audio a échoué';
      this.onError(this.error);
      this.setStatus('error');
      return;
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = this.locale;
    utterance.rate = 0.95;
    utterance.pitch = 1;

    const languagePrefix = this.language.toLowerCase();
    const voices = window.speechSynthesis.getVoices();
    const matchingVoice = voices.find((voice) =>
      (voice.lang || '').toLowerCase().startsWith(languagePrefix)
    );
    if (matchingVoice) {
      utterance.voice = matchingVoice;
    }

    utterance.onend = () => {
      this.setStatus('idle');
    };
    utterance.onerror = (event) => {
      if (event.error === 'canceled' || event.error === 'interrupted') {
        this.setStatus('idle');
        return;
      }
      this.error = 'La lecture audio a échoué';
      this.onError(this.error);
      this.setStatus('error');
    };

    this.setStatus('playing');
    window.speechSynthesis.speak(utterance);
  }

  async play(text) {
    this.setStatus('loading');
    this.error = null;

    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }

    try {
      const response = await fetch(this.ttsUrl, {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'same-origin',
        body: JSON.stringify({ text, language: this.language }),
      });

      if (!response.ok) {
        let message = `La requête de synthèse vocale a échoué (statut ${response.status})`;
        try {
          const payload = await response.json();
          if (payload && payload.message) {
            message = payload.message;
          }
        } catch (ignored) {
          // The response was not JSON; keep the status-based message.
        }
        throw new Error(message);
      }

      const arrayBuffer = await response.arrayBuffer();
      const context = this.getContext();
      if (context.state === 'suspended') {
        await context.resume();
      }

      const audioBuffer = await context.decodeAudioData(arrayBuffer);

      if (this.source) {
        this.source.onended = null;
        this.source.disconnect();
        this.source = null;
      }

      const source = context.createBufferSource();
      source.buffer = audioBuffer;
      if (this.analyser) {
        source.connect(this.analyser);
      }
      this.source = source;

      this.setStatus('playing');
      source.onended = () => {
        source.disconnect();
        if (this.source === source) {
          this.source = null;
        }
        this.setStatus('idle');
      };
      source.start();
    } catch (error) {
      console.warn('[ExaminerAudio] server TTS unavailable, using browser voice:', error);
      this.speakWithBrowser(text);
    }
  }

  getFrequencyData() {
    if (!this.analyser) {
      return null;
    }
    const data = new Uint8Array(this.analyser.frequencyBinCount);
    this.analyser.getByteFrequencyData(data);
    return data;
  }
}
