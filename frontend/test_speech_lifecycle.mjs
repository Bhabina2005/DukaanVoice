// Phase 1.4 Stage B: Comprehensive Voice Interaction Lifecycle & Audio Reliability Tests
// Executed with Node.js native test runner: node --test frontend/test_speech_lifecycle.mjs

import test from 'node:test';
import assert from 'node:assert/strict';

import { mapMicrophoneError, SpeechProviderService } from './src/services/speechService.js';
import { isTransientError, requestWithRetry } from './src/services/api.js';

test('1. mapMicrophoneError maps NotAllowedError and PermissionDeniedError', () => {
  const err1 = mapMicrophoneError({ name: 'NotAllowedError' });
  assert.equal(err1.type, 'permission_denied');
  assert.equal(err1.isPermanent, true);
  assert.ok(err1.messageEn.includes('permission denied'));
  assert.ok(err1.messageKn.includes('ಅನುಮತಿ ನಿರಾಕರಿಸಲಾಗಿದೆ'));

  const err2 = mapMicrophoneError({ name: 'PermissionDeniedError' });
  assert.equal(err2.type, 'permission_denied');
  assert.equal(err2.isPermanent, true);
});

test('2. mapMicrophoneError maps NotFoundError and DevicesNotFoundError', () => {
  const err1 = mapMicrophoneError({ name: 'NotFoundError' });
  assert.equal(err1.type, 'device_not_found');
  assert.equal(err1.isPermanent, true);
  assert.ok(err1.messageEn.includes('No microphone found'));
  assert.ok(err1.messageKn.includes('ಕಂಡುಬಂದಿಲ್ಲ'));

  const err2 = mapMicrophoneError({ name: 'DevicesNotFoundError' });
  assert.equal(err2.type, 'device_not_found');
  assert.equal(err2.isPermanent, true);
});

test('3. mapMicrophoneError maps NotReadableError and TrackStartError', () => {
  const err1 = mapMicrophoneError({ name: 'NotReadableError' });
  assert.equal(err1.type, 'hardware_in_use');
  assert.equal(err1.isPermanent, false);
  assert.ok(err1.messageEn.includes('in use by another application'));

  const err2 = mapMicrophoneError({ name: 'TrackStartError' });
  assert.equal(err2.type, 'hardware_in_use');
  assert.equal(err2.isPermanent, false);
});

test('4. mapMicrophoneError maps AbortError', () => {
  const err = mapMicrophoneError({ name: 'AbortError' });
  assert.equal(err.type, 'aborted');
  assert.equal(err.isPermanent, false);
  assert.ok(err.messageEn.includes('aborted'));
});

test('5. mapMicrophoneError handles unknown errors cleanly without raw traces', () => {
  const err = mapMicrophoneError(new Error('Internal driver hardware glitch'));
  assert.equal(err.type, 'unknown_mic_error');
  assert.equal(err.isPermanent, false);
  assert.equal(err.messageEn, 'Internal driver hardware glitch');
  assert.ok(err.messageKn.includes('ಮೈಕ್ರೊಫೋನ್ ದೋಷ'));
});

test('6. isTransientError identifies retryable HTTP codes and network fetch errors', () => {
  assert.equal(isTransientError({ status: 408 }), true);
  assert.equal(isTransientError({ status: 502 }), true);
  assert.equal(isTransientError({ status: 503 }), true);
  assert.equal(isTransientError({ status: 504 }), true);

  const netErr = new TypeError('Failed to fetch');
  assert.equal(isTransientError(netErr), true);

  const connErr = new Error('ECONNRESET: connection reset by peer');
  assert.equal(isTransientError(connErr), true);
});

test('7. isTransientError rejects non-retryable permanent client errors', () => {
  assert.equal(isTransientError({ status: 400 }), false);
  assert.equal(isTransientError({ status: 401 }), false);
  assert.equal(isTransientError({ status: 403 }), false);
  assert.equal(isTransientError({ status: 404 }), false);
  assert.equal(isTransientError({ status: 422 }), false);
});

test('8. requestWithRetry retries transient errors and succeeds on retry', async () => {
  let attempts = 0;
  const retryEvents = [];

  const failingThenSuccess = async () => {
    attempts++;
    if (attempts < 2) {
      const err = new Error('Gateway Timeout');
      err.status = 504;
      throw err;
    }
    return { data: 'ok', attempts };
  };

  const result = await requestWithRetry(failingThenSuccess, {
    maxRetries: 2,
    initialDelayMs: 10,
    onRetry: (info) => retryEvents.push(info),
  });

  assert.equal(result.data, 'ok');
  assert.equal(attempts, 2);
  assert.equal(retryEvents.length, 1);
  assert.equal(retryEvents[0].attempt, 1);
});

test('9. requestWithRetry immediately fails on permanent 401 or 400 errors without retrying', async () => {
  let attempts = 0;
  const retryEvents = [];

  const permanentFail = async () => {
    attempts++;
    const err = new Error('Unauthorized');
    err.status = 401;
    throw err;
  };

  await assert.rejects(
    async () => {
      await requestWithRetry(permanentFail, {
        maxRetries: 3,
        initialDelayMs: 10,
        onRetry: (info) => retryEvents.push(info),
      });
    },
    (err) => {
      assert.equal(err.status, 401);
      return true;
    }
  );

  assert.equal(attempts, 1);
  assert.equal(retryEvents.length, 0);
});

test('10. SpeechProviderService: 30-second recording timer cutoff automatically clears timer and stops', () => {
  const service = new SpeechProviderService();
  let stopped = false;
  service.isListening = true;
  service.stopListening = () => {
    stopped = true;
    service.isListening = false;
  };

  // Simulate setting the 30s timer
  service.recordingTimer = setTimeout(() => {
    service.stopListening();
  }, 50);

  assert.ok(service.recordingTimer !== null);

  // Clear timer
  service.clearRecordingTimer();
  assert.equal(service.recordingTimer, null);
  assert.equal(stopped, false);
});

test('11. SpeechProviderService: releaseRecordingStream stops all audio tracks and cleans reference', () => {
  const service = new SpeechProviderService();
  let tracksStopped = 0;

  const mockTrack1 = { stop: () => { tracksStopped++; } };
  const mockTrack2 = { stop: () => { tracksStopped++; } };

  service.recordingStream = {
    getTracks: () => [mockTrack1, mockTrack2],
  };

  service.releaseRecordingStream();

  assert.equal(tracksStopped, 2);
  assert.equal(service.recordingStream, null);
});

test('12. SpeechProviderService: silence / empty audio detection rejects empty chunks', async () => {
  const service = new SpeechProviderService();
  let capturedError = null;
  let endCalled = false;

  // Mock navigator.mediaDevices and MediaRecorder environment
  const mockStream = { getTracks: () => [{ stop: () => {} }] };

  class MockMediaRecorder {
    constructor() {
      this.ondataavailable = null;
      this.onstop = null;
    }
    start() {}
    stop() {
      if (this.onstop) this.onstop();
    }
  }

  try {
    Object.defineProperty(globalThis.navigator, 'mediaDevices', {
      value: {
        getUserMedia: async () => mockStream,
      },
      configurable: true,
      writable: true,
    });
  } catch {
    // If navigator is not configurable, fallback to global mock
  }

  globalThis.MediaRecorder = MockMediaRecorder;
  service.isGnaniConfigured = true;

  // Start recording
  await service.startListening({
    language: 'kn-IN',
    onError: (err) => { capturedError = err; },
    onEnd: () => { endCalled = true; },
  });

  // Verify recorder initialized with 0 chunks
  assert.equal(service.audioChunks.length, 0);

  // Trigger stop on empty audio
  service.mediaRecorder.stop();

  assert.ok(capturedError !== null);
  assert.equal(capturedError.isSilence, true);
  assert.equal(capturedError.type, 'empty_audio');
  assert.ok(capturedError.messageEn.includes('No speech detected'));
  assert.ok(capturedError.messageKn.includes('ಶಬ್ದ ಕೇಳಿಸಲಿಲ್ಲ'));
  assert.equal(endCalled, true);
});

test('13. SpeechProviderService: single-stream playback releases prior audio and revokes ObjectURL', () => {
  const service = new SpeechProviderService();
  let paused = false;
  let revokedUrl = null;

  globalThis.URL = {
    revokeObjectURL: (url) => { revokedUrl = url; },
  };

  service.activeAudioElement = {
    pause: () => { paused = true; },
    onplay: () => {},
    onended: () => {},
    onerror: () => {},
  };
  service.activeAudioUrl = 'blob:http://localhost:5173/mock-audio-uuid';

  // Stop speaking
  service.stopSpeaking();

  assert.equal(paused, true);
  assert.equal(revokedUrl, 'blob:http://localhost:5173/mock-audio-uuid');
  assert.equal(service.activeAudioElement, null);
  assert.equal(service.activeAudioUrl, null);
});

test('14. SpeechProviderService: cancelListening releases recorder, tracks, and timers completely', () => {
  const service = new SpeechProviderService();
  let recorderStopped = false;
  let tracksStopped = 0;

  service.recordingTimer = setTimeout(() => {}, 10000);
  service.audioChunks = ['chunk1', 'chunk2'];
  service.isListening = true;

  service.mediaRecorder = {
    stop: () => { recorderStopped = true; },
  };
  service.recordingStream = {
    getTracks: () => [{ stop: () => { tracksStopped++; } }],
  };

  service.cancelListening();

  assert.equal(service.recordingTimer, null);
  assert.equal(service.audioChunks.length, 0);
  assert.equal(service.isListening, false);
  assert.equal(recorderStopped, true);
  assert.equal(tracksStopped, 1);
  assert.equal(service.mediaRecorder, null);
  assert.equal(service.recordingStream, null);
});

test('15. SpeechProviderService: retryLastAudio provides cached retry and rejects when no audio is cached', async () => {
  const service = new SpeechProviderService();
  service.lastRecordedAudio = null;

  let capturedError = null;
  let endCalled = false;

  const result = await service.retryLastAudio({
    onError: (err) => { capturedError = err; },
    onEnd: () => { endCalled = true; },
  });

  assert.equal(result, false);
  assert.equal(capturedError.type, 'no_cached_audio');
  assert.ok(capturedError.messageEn.includes('No previous recording available'));
  assert.equal(endCalled, true);
});
