// DukaanVoice Modular Speech Provider Service
// Integrates:
// - Primary: Gnani Prisma v3.0 (STT) & Timbre v3.0 (TTS) via backend proxy
// - Explicit Fallback: Browser Web Speech API (webkitSpeechRecognition & window.speechSynthesis)
// - Stage B Reliability: 30s auto-cutoff, silence detection, single-stream playback, device error mapping

import { getSpeechProviderStatus, transcribeAudio, synthesizeSpeech } from './api.js';

export function mapMicrophoneError(err) {
  const name = err?.name || '';
  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return {
        type: 'permission_denied',
        name,
        messageEn: 'Microphone permission denied. Please allow microphone access in your browser settings.',
        messageKn: 'ಮೈಕ್ರೊಫೋನ್ ಅನುಮತಿ ನಿರಾಕರಿಸಲಾಗಿದೆ. ದಯವಿಟ್ಟು ಬ್ರೌಸರ್ ಸೆಟ್ಟಿಂಗ್ಸ್‌ನಲ್ಲಿ ಅನುಮತಿ ನೀಡಿ.',
        isPermanent: true,
      };
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return {
        type: 'device_not_found',
        name,
        messageEn: 'No microphone found on this device. Please connect a microphone or use text input.',
        messageKn: 'ಯಾವುದೇ ಮೈಕ್ರೊಫೋನ್ ಕಂಡುಬಂದಿಲ್ಲ. ದಯವಿಟ್ಟು ಮೈಕ್ ಸಂಪರ್ಕಿಸಿ ಅಥವಾ ಟೈಪ್ ಮಾಡಿ.',
        isPermanent: true,
      };
    case 'NotReadableError':
    case 'TrackStartError':
      return {
        type: 'hardware_in_use',
        name,
        messageEn: 'Microphone is currently in use by another application or tab. Please close other audio apps.',
        messageKn: 'ಮೈಕ್ರೊಫೋನ್ ಮತ್ತೊಂದು ಅಪ್ಲಿಕೇಶನ್‌ನಲ್ಲಿ ಬಳಕೆಯಲ್ಲಿದೆ. ದಯವಿಟ್ಟು ಇತರ ಆ್ಯಪ್‌ಗಳನ್ನು ಮುಚ್ಚಿ.',
        isPermanent: false,
      };
    case 'AbortError':
      return {
        type: 'aborted',
        name,
        messageEn: 'Microphone operation was aborted.',
        messageKn: 'ಮೈಕ್ರೊಫೋನ್ ಕಾರ್ಯಾಚರಣೆ ರದ್ದುಗೊಂಡಿದೆ.',
        isPermanent: false,
      };
    default:
      return {
        type: 'unknown_mic_error',
        name,
        messageEn: err?.message || 'Microphone error occurred. Please use text input.',
        messageKn: 'ಮೈಕ್ರೊಫೋನ್ ದೋಷ ಸಂಭವಿಸಿದೆ. ದಯವಿಟ್ಟು ಟೈಪ್ ಮಾಡಿ.',
        isPermanent: false,
      };
  }
}

export class SpeechProviderService {
  constructor() {
    const SpeechRecognition =
      typeof window !== 'undefined'
        ? window.SpeechRecognition || window.webkitSpeechRecognition
        : null;
    this.recognitionClass = SpeechRecognition || null;
    this.recognition = null;
    this.isListening = false;
    this.isStopping = false;
    this.language = 'kn-IN'; // Default to Kannada
    this.synth = typeof window !== 'undefined' ? window.speechSynthesis || null : null;
    this.audioEnabled = true;

    // Gnani state
    this.isGnaniConfigured = false;
    this.gnaniProviderInfo = null;
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.activeAudioElement = null;
    this.activeAudioUrl = null;
    this.recordingStream = null;
    this.recordingTimer = null;
    this.MAX_RECORDING_MS = 30000; // Strict 30s cutoff for Prisma v3.0 REST endpoint
    this.lastRecordedAudio = null; // Cached for user-triggered retry

    // Playback state & duplicate playback prevention
    this.currentPlaybackId = 0;
    this.isSpeaking = false;
    this.activePlaybackProvider = null;

    // Fetch initial backend status if in browser environment
    if (typeof window !== 'undefined') {
      this.refreshProviderStatus();
    }
  }

  async refreshProviderStatus() {
    try {
      const status = await getSpeechProviderStatus();
      this.isGnaniConfigured = Boolean(status.is_configured);
      this.gnaniProviderInfo = status;
      return status;
    } catch (err) {
      console.warn('Failed to fetch speech provider status from backend:', err);
      this.isGnaniConfigured = false;
      return null;
    }
  }

  getProviderInfo() {
    if (this.isGnaniConfigured && this.gnaniProviderInfo) {
      return {
        providerName: 'Gnani Voice AI (Prisma v3.0 / Timbre v3.0)',
        isGnaniActive: true,
        sttModel: this.gnaniProviderInfo.stt_model,
        ttsModel: this.gnaniProviderInfo.tts_model,
        ttsVoice: this.gnaniProviderInfo.tts_voice,
        gnaniStatusNote: 'Gnani Prisma v3.0 (STT) and Timbre v3.0 (TTS) active via backend adapter.',
        isSpeechRecognitionSupported: Boolean(
          (typeof navigator !== 'undefined' && navigator.mediaDevices?.getUserMedia) ||
            this.recognitionClass
        ),
        isSpeechSynthesisSupported: true,
        activeLanguage: this.language,
      };
    }

    return {
      providerName: 'Browser Web Speech API (Fallback)',
      isGnaniActive: false,
      sttModel: 'None (Browser Native)',
      ttsModel: 'None (Browser Native)',
      gnaniStatusNote: 'Gnani credentials are not configured in environment; active fallback is Web Speech API.',
      isSpeechRecognitionSupported: Boolean(this.recognitionClass),
      isSpeechSynthesisSupported: Boolean(this.synth),
      activeLanguage: this.language,
    };
  }

  setLanguage(lang) {
    this.language = lang;
    if (this.recognition) {
      this.recognition.lang = lang;
    }
  }

  setAudioEnabled(enabled) {
    this.audioEnabled = enabled;
    if (!enabled) {
      this.stopSpeaking();
    }
  }

  clearRecordingTimer() {
    if (this.recordingTimer) {
      clearTimeout(this.recordingTimer);
      this.recordingTimer = null;
    }
  }

  releaseRecordingStream() {
    if (this.recordingStream) {
      try {
        this.recordingStream.getTracks().forEach((track) => track.stop());
      } catch {
        // ignore
      }
      this.recordingStream = null;
    }
  }

  async startListening({ onResult, onError, onEnd, onRetry, language }) {
    const targetLang = language || this.language;

    // Strict single-stream audio: stop any active playback before opening microphone
    this.stopSpeaking();

    // If Gnani is active and browser supports media capture, record audio for Prisma STT
    if (
      this.isGnaniConfigured &&
      typeof navigator !== 'undefined' &&
      navigator.mediaDevices?.getUserMedia
    ) {
      return this.startGnaniRecording({ onResult, onError, onEnd, onRetry, language: targetLang });
    }

    // Otherwise use explicit Web Speech API fallback
    return this.startWebSpeechFallback({ onResult, onError, onEnd, language: targetLang });
  }

  async startGnaniRecording({ onResult, onError, onEnd, onRetry, language }) {
    try {
      this.stopListening();
      this.clearRecordingTimer();
      this.releaseRecordingStream();
      this.isStopping = false;

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.recordingStream = stream;
      this.audioChunks = [];

      let mimeType = 'audio/webm';
      if (typeof MediaRecorder !== 'undefined' && typeof MediaRecorder.isTypeSupported === 'function') {
        if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
          mimeType = 'audio/webm;codecs=opus';
        } else if (MediaRecorder.isTypeSupported('audio/webm')) {
          mimeType = 'audio/webm';
        } else if (MediaRecorder.isTypeSupported('audio/mp4')) {
          mimeType = 'audio/mp4';
        }
      }

      this.mediaRecorder = new MediaRecorder(stream, { mimeType });
      this.isListening = true;

      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          this.audioChunks.push(event.data);
        }
      };

      this.mediaRecorder.onstop = async () => {
        this.isListening = false;
        this.clearRecordingTimer();
        this.releaseRecordingStream();

        // 1. Check for empty audio / silence
        if (this.audioChunks.length === 0) {
          this.isStopping = false;
          if (onError) {
            onError({
              type: 'empty_audio',
              isSilence: true,
              messageEn: 'No speech detected. Please speak clearly into the microphone.',
              messageKn: 'ಶಬ್ದ ಕೇಳಿಸಲಿಲ್ಲ, ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಮಾತನಾಡಿ.',
            });
          }
          if (onEnd) onEnd();
          return;
        }

        const audioBlob = new Blob(this.audioChunks, { type: mimeType });
        if (audioBlob.size < 100) {
          this.isStopping = false;
          if (onError) {
            onError({
              type: 'empty_audio',
              isSilence: true,
              messageEn: 'No speech detected. Please speak clearly into the microphone.',
              messageKn: 'ಶಬ್ದ ಕೇಳಿಸಲಿಲ್ಲ, ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಮಾತನಾಡಿ.',
            });
          }
          if (onEnd) onEnd();
          return;
        }

        const format = mimeType.includes('webm') ? 'webm' : 'mp4';

        try {
          const reader = new FileReader();
          reader.readAsDataURL(audioBlob);
          reader.onloadend = async () => {
            this.isStopping = false;
            const base64Audio = (reader.result || '').split(',')[1];
            if (!base64Audio) {
              if (onError) {
                onError({
                  type: 'empty_audio',
                  isSilence: true,
                  messageEn: 'No speech detected. Please speak clearly into the microphone.',
                  messageKn: 'ಶಬ್ದ ಕೇಳಿಸಲಿಲ್ಲ, ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಮಾತನಾಡಿ.',
                });
              }
              if (onEnd) onEnd();
              return;
            }

            // Cache for manual user retry
            this.lastRecordedAudio = {
              base64: base64Audio,
              format,
              language,
            };

            try {
              const res = await transcribeAudio(base64Audio, format, language, {
                maxRetries: 2,
                initialDelayMs: 600,
                onRetry,
              });

              if (res.success && res.transcript && res.transcript.trim()) {
                if (onResult) {
                  onResult({ transcript: res.transcript.trim(), isFinal: true });
                }
              } else if (res.success && (!res.transcript || !res.transcript.trim())) {
                // Empty transcript from STT (silence)
                if (onResult) {
                  onResult({
                    transcript: '',
                    isSilence: true,
                    isFinal: true,
                    messageEn: 'No speech detected. Please speak clearly into the microphone.',
                    messageKn: 'ಶಬ್ದ ಕೇಳಿಸಲಿಲ್ಲ, ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಮಾತನಾಡಿ.',
                  });
                }
              } else if (res.fallback_hint) {
                console.warn('Gnani STT returned fallback hint, attempting Web Speech:', res.error);
                this.startWebSpeechFallback({ onResult, onError, onEnd, language });
                return;
              } else {
                if (onError) {
                  onError({
                    type: 'transcription_error',
                    messageEn: res.error || 'Speech transcription failed.',
                    messageKn: 'ಧ್ವನಿ ಗುರುತಿಸುವಿಕೆ ವಿಫಲವಾಗಿದೆ.',
                  });
                }
              }
            } catch (transcribeErr) {
              console.warn('Gnani STT error, falling back to Web Speech:', transcribeErr);
              this.startWebSpeechFallback({ onResult, onError, onEnd, language });
              return;
            } finally {
              if (onEnd) onEnd();
            }
          };
        } catch (readErr) {
          this.isStopping = false;
          if (onError) onError(readErr);
          if (onEnd) onEnd();
        }
      };

      // 2. Set strict 30-second duration timer cutoff
      this.clearRecordingTimer();
      this.recordingTimer = setTimeout(() => {
        console.warn('Recording reached 30-second duration cutoff.');
        if (this.isListening && !this.isStopping) {
          this.stopListening();
        }
      }, this.MAX_RECORDING_MS);

      this.mediaRecorder.start(250); // Emit slices every 250ms
      return true;
    } catch (micErr) {
      this.clearRecordingTimer();
      this.releaseRecordingStream();
      this.isListening = false;
      this.isStopping = false;

      const mapped = mapMicrophoneError(micErr);
      if (onError) onError(mapped);
      if (onEnd) onEnd();
      return false;
    }
  }

  startWebSpeechFallback({ onResult, onError, onEnd, language }) {
    if (!this.recognitionClass) {
      if (onError) {
        onError({
          type: 'unsupported_browser',
          messageEn: 'Speech recognition is not supported in this browser. Please use text input.',
          messageKn: 'ಈ ಬ್ರೌಸರ್‌ನಲ್ಲಿ ಧ್ವನಿ ಗುರುತಿಸುವಿಕೆ ಬೆಂಬಲಿತವಾಗಿಲ್ಲ. ದಯವಿಟ್ಟು ಟೈಪ್ ಮಾಡಿ.',
        });
      }
      return false;
    }

    if (this.recognition) {
      try {
        this.recognition.abort();
      } catch {
        // ignore
      }
    }

    try {
      this.recognition = new this.recognitionClass();
      this.recognition.continuous = false;
      this.recognition.interimResults = true;
      this.recognition.lang = language || this.language;

      this.recognition.onstart = () => {
        this.isListening = true;
      };

      this.recognition.onresult = (event) => {
        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const item = event.results[i];
          if (item.isFinal) {
            finalTranscript += item[0].transcript;
          } else {
            interimTranscript += item[0].transcript;
          }
        }

        const transcript = finalTranscript || interimTranscript;
        if (onResult) {
          onResult({
            transcript: transcript.trim(),
            isFinal: Boolean(finalTranscript),
            isSilence: Boolean(finalTranscript && !transcript.trim()),
          });
        }
      };

      this.recognition.onerror = (event) => {
        this.isListening = false;
        let mapped = {
          type: event.error || 'speech_error',
          messageEn: 'Microphone recognition error. Please try speaking again.',
          messageKn: 'ಧ್ವನಿ ಗುರುತಿಸುವಿಕೆ ದೋಷ. ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಮಾತನಾಡಿ.',
        };
        if (event.error === 'not-allowed') {
          mapped = mapMicrophoneError({ name: 'NotAllowedError' });
        } else if (event.error === 'no-speech') {
          mapped = {
            type: 'no_speech',
            isSilence: true,
            messageEn: 'No speech detected. Please speak clearly into the microphone.',
            messageKn: 'ಶಬ್ದ ಕೇಳಿಸಲಿಲ್ಲ, ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಮಾತನಾಡಿ.',
          };
        }
        if (onError) onError(mapped);
      };

      this.recognition.onend = () => {
        this.isListening = false;
        if (onEnd) onEnd();
      };

      this.recognition.start();
      return true;
    } catch (err) {
      this.isListening = false;
      if (onError) onError(mapMicrophoneError(err));
      return false;
    }
  }

  stopListening() {
    this.clearRecordingTimer();
    if (this.isStopping) return;

    if (this.mediaRecorder && this.isListening) {
      try {
        this.isStopping = true;
        this.mediaRecorder.stop();
      } catch {
        this.isStopping = false;
        this.releaseRecordingStream();
      }
    } else {
      this.releaseRecordingStream();
    }

    if (this.recognition && this.isListening) {
      try {
        this.recognition.stop();
      } catch {
        // ignore
      }
    }
    this.isListening = false;
  }

  cancelListening() {
    this.clearRecordingTimer();
    this.audioChunks = [];
    this.isListening = false;
    this.isStopping = false;

    if (this.mediaRecorder) {
      try {
        this.mediaRecorder.onstop = null;
        this.mediaRecorder.ondataavailable = null;
        this.mediaRecorder.stop();
      } catch {
        // ignore
      }
      this.mediaRecorder = null;
    }
    this.releaseRecordingStream();

    if (this.recognition) {
      try {
        this.recognition.abort();
      } catch {
        // ignore
      }
      this.recognition = null;
    }
  }

  getLastRecordedAudio() {
    return this.lastRecordedAudio;
  }

  async retryLastAudio({ onResult, onError, onEnd, onRetry } = {}) {
    if (!this.lastRecordedAudio) {
      if (onError) {
        onError({
          type: 'no_cached_audio',
          messageEn: 'No previous recording available to retry. Please speak again.',
          messageKn: 'ಮರುಪ್ರಯತ್ನಿಸಲು ಧ್ವನಿ ಮುದ್ರಿಕೆ ಲಭ್ಯವಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಮಾತನಾಡಿ.',
        });
      }
      if (onEnd) onEnd();
      return false;
    }

    const { base64, format, language } = this.lastRecordedAudio;
    try {
      const res = await transcribeAudio(base64, format, language, {
        maxRetries: 2,
        initialDelayMs: 600,
        onRetry,
      });

      if (res.success && res.transcript && res.transcript.trim()) {
        if (onResult) {
          onResult({ transcript: res.transcript.trim(), isFinal: true });
        }
        return true;
      } else if (res.success && (!res.transcript || !res.transcript.trim())) {
        if (onResult) {
          onResult({
            transcript: '',
            isSilence: true,
            isFinal: true,
            messageEn: 'No speech detected. Please speak clearly into the microphone.',
            messageKn: 'ಶಬ್ದ ಕೇಳಿಸಲಿಲ್ಲ, ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಮಾತನಾಡಿ.',
          });
        }
        return true;
      } else {
        if (onError) {
          onError({
            type: 'transcription_error',
            messageEn: res.error || 'Speech transcription failed.',
            messageKn: 'ಧ್ವನಿ ಗುರುತಿಸುವಿಕೆ ವಿಫಲವಾಗಿದೆ.',
          });
        }
        return false;
      }
    } catch (err) {
      if (onError) {
        onError(err);
      }
      return false;
    } finally {
      if (onEnd) onEnd();
    }
  }

  async speak(text, { language, onStart, onEnd, onError, onProviderUsed, onFallback } = {}) {
    // 1. Guard against empty, null, or whitespace-only responses
    if (!text || typeof text !== 'string' || !text.trim()) {
      if (onEnd) onEnd({ provider: null, reason: 'empty_text' });
      return;
    }

    // 2. Guard against muted audio
    if (!this.audioEnabled) {
      if (onEnd) onEnd({ provider: null, reason: 'audio_disabled' });
      return;
    }

    // 3. Strict single-stream playback: immediately cancel any existing audio and bump playback ID
    this.stopSpeaking();
    const playbackId = ++this.currentPlaybackId;
    const targetLang = language || this.language;
    const trimmedText = text.trim();

    // 4. Primary: Try Gnani Timbre TTS first if configured
    if (this.isGnaniConfigured) {
      try {
        const audioBlob = await synthesizeSpeech(trimmedText, targetLang);

        // Check if playback was superseded or stopped while network request was in-flight
        if (this.currentPlaybackId !== playbackId) {
          return;
        }

        // Validate audio blob (must be non-empty and minimum reasonable size)
        if (!audioBlob || audioBlob.size < 50) {
          throw new Error('Gnani Timbre returned an empty or invalid audio payload.');
        }

        if (typeof window !== 'undefined' && window.URL && window.Audio) {
          const audioUrl = URL.createObjectURL(audioBlob);
          this.activeAudioUrl = audioUrl;

          const audio = new Audio(audioUrl);
          this.activeAudioElement = audio;
          this.activePlaybackProvider = 'Gnani Timbre v3.0';

          if (onProviderUsed) {
            onProviderUsed({
              provider: 'Gnani Timbre v3.0',
              isFallback: false,
              model: this.gnaniProviderInfo?.tts_model || 'timbre-v3.0',
              voice: this.gnaniProviderInfo?.tts_voice || 'Shivani',
              language: targetLang,
            });
          }

          audio.onplay = () => {
            if (this.currentPlaybackId !== playbackId) {
              this.releaseActiveAudio();
              return;
            }
            this.isSpeaking = true;
            if (onStart) onStart({ provider: 'Gnani Timbre v3.0' });
          };

          audio.onended = () => {
            this.isSpeaking = false;
            this.activePlaybackProvider = null;
            this.releaseActiveAudio();
            if (onEnd) onEnd({ provider: 'Gnani Timbre v3.0' });
          };

          audio.onerror = (e) => {
            console.warn('Gnani Timbre audio playback failed, falling back to Web Speech synth:', e);
            this.releaseActiveAudio();
            if (this.currentPlaybackId !== playbackId) return;

            if (onFallback) {
              onFallback({
                fromProvider: 'Gnani Timbre v3.0',
                toProvider: 'Browser SpeechSynthesis',
                reason: 'HTMLAudioElement playback failure',
              });
            }

            this.speakWithWebSpeech(trimmedText, {
              language: targetLang,
              playbackId,
              onStart,
              onEnd,
              onError,
              onProviderUsed,
              fallbackReason: 'HTMLAudio playback failed',
            });
          };

          await audio.play();
          return;
        }
      } catch (err) {
        console.warn('Gnani Timbre TTS failed, activating browser synthesis fallback:', err);
        this.releaseActiveAudio();

        // Check if superseded
        if (this.currentPlaybackId !== playbackId) return;

        if (onFallback) {
          onFallback({
            fromProvider: 'Gnani Timbre v3.0',
            toProvider: 'Browser SpeechSynthesis',
            reason: err?.message || 'Gnani TTS provider unavailable',
            status: err?.status,
          });
        }
      }
    }

    // 5. Explicit Fallback: Browser Web Speech API SpeechSynthesis
    this.speakWithWebSpeech(trimmedText, {
      language: targetLang,
      playbackId,
      onStart,
      onEnd,
      onError,
      onProviderUsed,
      fallbackReason: this.isGnaniConfigured
        ? 'Gnani Timbre service error or timeout'
        : 'Gnani credentials not configured in environment',
    });
  }

  speakWithWebSpeech(text, {
    language,
    playbackId,
    onStart,
    onEnd,
    onError,
    onProviderUsed,
    fallbackReason,
  } = {}) {
    if (!this.audioEnabled) {
      if (onEnd) onEnd({ provider: null, reason: 'audio_disabled' });
      return;
    }

    if (!this.synth) {
      console.warn('SpeechSynthesis is not supported in this environment.');
      if (onError) onError({ message: 'Browser speech synthesis is not supported on this device.' });
      if (onEnd) onEnd({ provider: null, reason: 'synth_unsupported' });
      return;
    }

    if (playbackId !== undefined && this.currentPlaybackId !== playbackId) {
      return;
    }

    try {
      this.synth.cancel();

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = language || this.language;
      utterance.rate = 0.95;
      utterance.pitch = 1.0;

      // Select voice matching requested language if available
      const voices = this.synth.getVoices ? this.synth.getVoices() : [];
      const targetPrefix = utterance.lang.split('-')[0].toLowerCase();
      const matchedVoice = voices.find(
        (v) => v.lang === utterance.lang || v.lang.toLowerCase().startsWith(targetPrefix)
      );
      if (matchedVoice) {
        utterance.voice = matchedVoice;
      }

      this.activePlaybackProvider = 'Browser SpeechSynthesis';

      if (onProviderUsed) {
        onProviderUsed({
          provider: 'Browser SpeechSynthesis',
          isFallback: true,
          fallbackReason: fallbackReason || 'Browser fallback active',
          voice: matchedVoice?.name || 'Default Browser Voice',
          language: utterance.lang,
        });
      }

      utterance.onstart = () => {
        if (playbackId !== undefined && this.currentPlaybackId !== playbackId) {
          try {
            this.synth.cancel();
          } catch {
            // ignore
          }
          return;
        }
        this.isSpeaking = true;
        if (onStart) onStart({ provider: 'Browser SpeechSynthesis' });
      };

      utterance.onend = () => {
        this.isSpeaking = false;
        this.activePlaybackProvider = null;
        if (onEnd) onEnd({ provider: 'Browser SpeechSynthesis' });
      };

      utterance.onerror = (err) => {
        this.isSpeaking = false;
        this.activePlaybackProvider = null;
        console.warn('Web Speech synthesis error:', err);
        if (onError) onError(err);
        if (onEnd) onEnd({ provider: 'Browser SpeechSynthesis', error: err });
      };

      this.synth.speak(utterance);
    } catch (err) {
      this.isSpeaking = false;
      this.activePlaybackProvider = null;
      console.warn('Web Speech synthesis exception:', err);
      if (onError) onError(err);
      if (onEnd) onEnd({ provider: 'Browser SpeechSynthesis', error: err });
    }
  }

  releaseActiveAudio() {
    if (this.activeAudioElement) {
      try {
        this.activeAudioElement.pause();
        this.activeAudioElement.onplay = null;
        this.activeAudioElement.onended = null;
        this.activeAudioElement.onerror = null;
      } catch {
        // ignore
      }
      this.activeAudioElement = null;
    }

    const urlObj = typeof window !== 'undefined' && window.URL ? window.URL : typeof URL !== 'undefined' ? URL : null;
    if (this.activeAudioUrl && urlObj && typeof urlObj.revokeObjectURL === 'function') {
      try {
        urlObj.revokeObjectURL(this.activeAudioUrl);
      } catch {
        // ignore
      }
      this.activeAudioUrl = null;
    }
  }

  stopSpeaking() {
    this.currentPlaybackId++;
    this.isSpeaking = false;
    this.activePlaybackProvider = null;
    this.releaseActiveAudio();
    if (this.synth) {
      try {
        this.synth.cancel();
      } catch {
        // ignore
      }
    }
  }

  getPlaybackStatus() {
    return {
      isSpeaking: this.isSpeaking,
      activeProvider: this.activePlaybackProvider,
      audioEnabled: this.audioEnabled,
      isGnaniConfigured: this.isGnaniConfigured,
    };
  }
}

export const speechService = new SpeechProviderService();
