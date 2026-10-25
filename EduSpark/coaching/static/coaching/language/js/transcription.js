const REALTIME_URL = 'wss://api.elevenlabs.io/v1/speech-to-text/realtime';
const DEFAULT_SAMPLE_RATE = 16000;

const AUDIO_FORMAT_BY_SAMPLE_RATE = {
  8000: 'pcm_8000',
  16000: 'pcm_16000',
  22050: 'pcm_22050',
  24000: 'pcm_24000',
  44100: 'pcm_44100',
  48000: 'pcm_48000',
};

function encodeInt16ToBase64(chunk) {
  const bytes = new Uint8Array(chunk.buffer, chunk.byteOffset, chunk.byteLength);
  let binary = '';
  const blockSize = 0x8000;
  for (let i = 0; i < bytes.length; i += blockSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + blockSize));
  }
  return btoa(binary);
}

export class RealtimeTranscriber {
  constructor({ language = 'en', tokenUrl, onStatusChange, onPartial, onCommitted, onError } = {}) {
    this.languageCode = language;
    this.tokenUrl = tokenUrl;
    this.onStatusChange = onStatusChange || (() => {});
    this.onPartial = onPartial || (() => {});
    this.onCommitted = onCommitted || (() => {});
    this.onError = onError || (() => {});
    this.status = 'idle';
    this.error = null;
    this.socket = null;
    this.sampleRate = DEFAULT_SAMPLE_RATE;
  }

  setStatus(status) {
    this.status = status;
    this.onStatusChange(status);
  }

  teardown() {
    const socket = this.socket;
    if (!socket) {
      return;
    }
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.close();
    }
    this.socket = null;
  }

  disconnect() {
    this.teardown();
    this.onPartial('');
    this.setStatus('idle');
  }

  async connect(sampleRate) {
    this.teardown();
    this.setStatus('connecting');
    this.error = null;
    this.sampleRate = sampleRate;

    const audioFormat = AUDIO_FORMAT_BY_SAMPLE_RATE[sampleRate];
    if (!audioFormat) {
      this.error = `Fréquence d’échantillonnage du micro non prise en charge : ${sampleRate} Hz`;
      this.onError(this.error);
      this.setStatus('error');
      return;
    }

    try {
      const response = await fetch(this.tokenUrl, { credentials: 'same-origin' });
      if (!response.ok) {
        throw new Error(`La demande de jeton a échoué (${response.status})`);
      }
      const data = await response.json();
      if (!data.token) {
        throw new Error(data.message || data.error || 'Aucun jeton reçu');
      }

      const params = new URLSearchParams({
        model_id: 'scribe_v2_realtime',
        token: data.token,
        audio_format: audioFormat,
        commit_strategy: 'vad',
        language_code: this.languageCode,
      });

      const socket = new WebSocket(`${REALTIME_URL}?${params.toString()}`);
      this.socket = socket;

      socket.onopen = () => {
        this.setStatus('connected');
      };

      socket.onmessage = (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch (error) {
          console.error('[RealtimeTranscriber] failed to parse message:', error);
          return;
        }

        switch (message.message_type) {
          case 'session_started':
            break;
          case 'partial_transcript':
            this.onPartial(message.text || '');
            break;
          case 'committed_transcript':
          case 'committed_transcript_with_timestamps':
            if (message.text && message.text.trim()) {
              this.onCommitted(message.text);
            }
            this.onPartial('');
            break;
          case 'error':
          case 'auth_error':
          case 'quota_exceeded':
          case 'rate_limited':
          case 'commit_throttled':
            this.error = message.error || 'Erreur de transcription';
            console.error('[RealtimeTranscriber] server error:', this.error);
            this.onError(this.error);
            break;
          default:
            break;
        }
      };

      socket.onerror = () => {
        this.error = 'La connexion à la transcription a échoué.';
        this.onError(this.error);
        this.setStatus('error');
      };

      socket.onclose = () => {
        if (this.status !== 'error') {
          this.setStatus('idle');
        }
      };
    } catch (error) {
      console.error('[RealtimeTranscriber] failed to connect:', error);
      this.teardown();
      this.error = error instanceof Error ? error.message : 'Impossible de se connecter à la transcription';
      this.onError(this.error);
      this.setStatus('error');
    }
  }

  sendAudioChunk(chunk) {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    socket.send(
      JSON.stringify({
        message_type: 'input_audio_chunk',
        audio_base_64: encodeInt16ToBase64(chunk),
        commit: false,
        sample_rate: this.sampleRate,
      })
    );
  }
}
