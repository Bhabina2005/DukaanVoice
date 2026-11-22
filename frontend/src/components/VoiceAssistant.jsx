import { useState, useEffect, useRef, useCallback } from 'react';
import {
  processVoiceCommand,
  confirmVoiceTransaction,
  cancelVoiceTransaction,
  correctVoiceTransaction,
  getPendingVoiceStatus,
} from '../services/api';
import { speechService } from '../services/speechService';

const DEMO_CHIPS = [
  { label: 'Ramesh ge 340 rupees udhaar haaku.', desc: 'Credit (₹340)' },
  { label: 'No, 430 maadu.', desc: 'Correct to ₹430' },
  { label: 'Howdu.', desc: 'Confirm' },
  { label: 'Ramesh total eshtu?', desc: 'Check Balance' },
  { label: 'Ramesh ge 100 kodidare.', desc: 'Payment (₹100)' },
  { label: 'Illa.', desc: 'Cancel' },
];

export function VoiceAssistant({ onTransactionSaved, onNotification }) {
  // Voice interaction lifecycle state: 'idle' | 'recording' | 'processing' | 'retrying'
  const [processingState, setProcessingState] = useState('idle');
  const [liveTranscript, setLiveTranscript] = useState('');
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [language, setLanguage] = useState('kn-IN');
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [providerInfo, setProviderInfo] = useState(speechService.getProviderInfo());

  // Active audio playback state
  const [playingMessageId, setPlayingMessageId] = useState(null);
  const [, setPlayingProvider] = useState(null);

  // Safe retry and error feedback state
  const [lastFailedUtterance, setLastFailedUtterance] = useState(null); // { text, isAudio, errorMsg }
  const [retryFeedback, setRetryFeedback] = useState('');

  const msgIdCounter = useRef(1);
  const chatEndRef = useRef(null);
  const [sessionId] = useState(() => 'session_' + Math.random().toString(36).substring(2, 9));
  const sessionIdRef = useRef(sessionId);
  const isMountedRef = useRef(true);

  // Component lifecycle safety: Cancel in-flight audio, timers and playback on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      speechService.cancelListening();
      speechService.stopSpeaking();
    };
  }, []);

  useEffect(() => {
    async function fetchSpeechProvider() {
      await speechService.refreshProviderStatus();
      if (isMountedRef.current) {
        setProviderInfo(speechService.getProviderInfo());
      }
    }
    fetchSpeechProvider();
  }, []);

  // Conversation history
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      sender: 'assistant',
      textEn: 'Namaskara! DukaanVoice is ready. Speak in Kannada or Kanglish to record credit, payment, or check balance.',
      textKn: 'ನಮಸ್ಕಾರ! ದೂಕಾನ್ ವಾಯ್ಸ್ ಸಿದ್ಧವಾಗಿದೆ. ಉದ್ದಾರ, ಜಮಾ ಅಥವಾ ಬಾಕಿ ತಿಳಿಯಲು ಮಾತನಾಡಿ.',
      timestamp: 'Just now',
    },
  ]);

  // Active Pending Transaction
  const [pendingTransaction, setPendingTransaction] = useState(null);
  const [isEditingAmount, setIsEditingAmount] = useState(false);
  const [editAmountValue, setEditAmountValue] = useState('');
  const [disambiguationOptions, setDisambiguationOptions] = useState(null);
  const [isConfirming, setIsConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState(null);

  const checkActivePending = useCallback(async () => {
    try {
      const res = await getPendingVoiceStatus(sessionIdRef.current);
      if (isMountedRef.current && res.has_pending && res.pending_transaction) {
        setPendingTransaction(res.pending_transaction);
      }
    } catch {
      // ignore on mount
    }
  }, []);

  useEffect(() => {
    checkActivePending();
  }, [checkActivePending]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, pendingTransaction]);

  function handleLanguageChange(newLang) {
    setLanguage(newLang);
    speechService.setLanguage(newLang);
  }

  function handleAudioToggle() {
    const nextState = !audioEnabled;
    setAudioEnabled(nextState);
    speechService.setAudioEnabled(nextState);
    if (!nextState) {
      setPlayingMessageId(null);
      setPlayingProvider(null);
    }
  }

  function handleSilenceDetected(customEn, customKn) {
    const textEn = customEn || 'No speech detected. Please speak clearly into the microphone.';
    const textKn = customKn || 'ಶಬ್ದ ಕೇಳಿಸಲಿಲ್ಲ, ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಮಾತನಾಡಿ.';
    const id = `msg_${msgIdCounter.current++}`;
    setMessages((prev) => [
      ...prev,
      {
        id,
        sender: 'assistant',
        textEn,
        textKn,
        spokenText: textKn,
        timestamp: 'Now',
        isSilenceNotice: true,
      },
    ]);
    setProcessingState('idle');

    if (audioEnabled) {
      setPlayingMessageId(id);
      speechService.speak(textKn, {
        language,
        onStart: ({ provider }) => {
          if (!isMountedRef.current) return;
          setPlayingMessageId(id);
          setPlayingProvider(provider);
        },
        onProviderUsed: ({ provider, isFallback }) => {
          if (!isMountedRef.current) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === id ? { ...m, ttsProvider: provider, isTtsFallback: isFallback } : m
            )
          );
        },
        onFallback: ({ reason }) => {
          if (!isMountedRef.current) return;
          if (onNotification) {
            onNotification({
              type: 'info',
              message: `Gnani TTS fallback active (${reason}). Playing via Browser Speech.`,
            });
          }
        },
        onEnd: () => {
          if (!isMountedRef.current) return;
          setPlayingMessageId(null);
          setPlayingProvider(null);
        },
        onError: () => {
          if (!isMountedRef.current) return;
          setPlayingMessageId(null);
          setPlayingProvider(null);
        },
      });
    }
  }

  function toggleListening() {
    // Prevent starting or stopping while processing or retrying
    if (processingState === 'processing' || processingState === 'retrying') {
      return;
    }

    if (processingState === 'recording') {
      speechService.stopListening();
      setProcessingState('processing');
    } else {
      setLiveTranscript('');
      setLastFailedUtterance(null);
      setRetryFeedback('');
      setProcessingState('recording');

      const started = speechService.startListening({
        language,
        onRetry: ({ attempt, maxRetries }) => {
          if (!isMountedRef.current) return;
          setProcessingState('retrying');
          setRetryFeedback(`ಮರುಪ್ರಯತ್ನಿಸಲಾಗುತ್ತಿದೆ (${attempt}/${maxRetries})... / Retrying (${attempt}/${maxRetries})...`);
        },
        onResult: ({ transcript, isFinal, isSilence, messageEn, messageKn }) => {
          if (!isMountedRef.current) return;
          if (transcript) {
            setLiveTranscript(transcript);
          }
          if (isFinal) {
            if (isSilence || !transcript || !transcript.trim()) {
              // Empty speech or silence detected: give friendly feedback without backend NLU call
              handleSilenceDetected(messageEn, messageKn);
              setLiveTranscript('');
            } else {
              setProcessingState('processing');
              handleUserUtterance(transcript.trim());
              setLiveTranscript('');
            }
          }
        },
        onError: (err) => {
          if (!isMountedRef.current) return;
          console.warn('Speech recognition error:', err);
          setProcessingState('idle');
          setLiveTranscript('');

          if (err?.isSilence || err?.type === 'empty_audio' || err?.type === 'no_speech') {
            handleSilenceDetected(err.messageEn, err.messageKn);
            return;
          }

          const msgEn = err?.messageEn || err?.message || 'Microphone error occurred. Please use text input.';
          const msgKn = err?.messageKn || 'ಮೈಕ್ರೊಫೋನ್ ದೋಷ ಸಂಭವಿಸಿದೆ. ದಯವಿಟ್ಟು ಟೈಪ್ ಮಾಡಿ.';

          const errId = `msg_${msgIdCounter.current++}`;
          setMessages((prev) => [
            ...prev,
            {
              id: errId,
              sender: 'assistant',
              textEn: msgEn,
              textKn: msgKn,
              timestamp: 'Now',
              isError: true,
              canRetryAudio: !err?.isPermanent && Boolean(speechService.getLastRecordedAudio()),
            },
          ]);

          if (!err?.isPermanent) {
            setLastFailedUtterance({
              isAudio: true,
              text: null,
              errorMsg: msgEn,
            });
          }

          if (onNotification) {
            onNotification({
              type: 'warning',
              message: msgEn,
            });
          }
        },
        onEnd: () => {
          if (!isMountedRef.current) return;
          setProcessingState((prev) => (prev === 'recording' ? 'idle' : prev));
        },
      });

      if (!started) {
        setProcessingState('idle');
      }
    }
  }

  function handleVoiceResponse(res) {
    const id = `msg_${msgIdCounter.current++}`;
    const assistantMsg = {
      id,
      sender: 'assistant',
      textEn: res.message,
      textKn: res.message_kn,
      spokenText: res.spoken_text,
      timestamp: 'Now',
      balanceInfo: res.customer_balance,
      confirmedTxn: res.confirmed_transaction,
    };
    setMessages((prev) => [...prev, assistantMsg]);

    // Speak response if audio enabled (single-stream audio guaranteed by speechService)
    if (res.spoken_text && res.spoken_text.trim() && audioEnabled) {
      setPlayingMessageId(assistantMsg.id);
      speechService.speak(res.spoken_text, {
        language,
        onStart: ({ provider }) => {
          if (!isMountedRef.current) return;
          setPlayingMessageId(assistantMsg.id);
          setPlayingProvider(provider);
        },
        onProviderUsed: ({ provider, isFallback }) => {
          if (!isMountedRef.current) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsg.id ? { ...m, ttsProvider: provider, isTtsFallback: isFallback } : m
            )
          );
        },
        onFallback: ({ reason }) => {
          if (!isMountedRef.current) return;
          if (onNotification) {
            onNotification({
              type: 'info',
              message: `Gnani TTS fallback active (${reason}). Playing via Browser Speech.`,
            });
          }
        },
        onEnd: () => {
          if (!isMountedRef.current) return;
          setPlayingMessageId(null);
          setPlayingProvider(null);
        },
        onError: () => {
          if (!isMountedRef.current) return;
          setPlayingMessageId(null);
          setPlayingProvider(null);
        },
      });
    }

    // Handle Pending Transaction state
    if (res.pending_transaction) {
      if (res.intent === 'CANCELLED' || res.pending_transaction.status === 'CANCELLED') {
        setPendingTransaction(null);
        setConfirmError(null);
      } else if (res.intent === 'CONFIRMED' || res.pending_transaction.status === 'CONFIRMED') {
        setPendingTransaction(null);
        setConfirmError(null);
        if (onTransactionSaved) onTransactionSaved();
      } else if (res.intent === 'STALE_PREVIEW') {
        setPendingTransaction(res.pending_transaction);
        setEditAmountValue(res.pending_transaction.amount.toString());
        setConfirmError({
          isStale: true,
          message: res.message || 'Customer balance changed while waiting. Please review updated preview before confirming.',
        });
      } else {
        setPendingTransaction(res.pending_transaction);
        setEditAmountValue(res.pending_transaction.amount.toString());
        setConfirmError(null);
      }
    } else if (res.intent === 'CANCELLED' || res.intent === 'CONFIRMED') {
      setPendingTransaction(null);
      setConfirmError(null);
      if (res.intent === 'CONFIRMED' && onTransactionSaved) {
        onTransactionSaved();
      }
    }

    // Handle Disambiguation
    if (res.disambiguation_options && res.disambiguation_options.length > 0) {
      setDisambiguationOptions(res.disambiguation_options);
    } else {
      setDisambiguationOptions(null);
    }

    if (res.success && res.intent === 'CONFIRMED' && onNotification) {
      onNotification({
        type: 'success',
        message: res.message,
      });
    }
  }

  async function handleUserUtterance(text, { isRetry = false } = {}) {
    if (!text.trim() || isLoading) return;

    if (!isRetry) {
      const id = `msg_${msgIdCounter.current++}`;
      const userMsg = {
        id,
        sender: 'user',
        textEn: text,
        textKn: '',
        timestamp: 'Now',
      };
      setMessages((prev) => [...prev, userMsg]);
      setInputText('');
    }

    setIsLoading(true);
    setProcessingState('processing');
    setRetryFeedback('');

    try {
      const response = await processVoiceCommand(text, sessionIdRef.current, {
        maxRetries: 2,
        initialDelayMs: 600,
        onRetry: ({ attempt, maxRetries }) => {
          if (!isMountedRef.current) return;
          setProcessingState('retrying');
          setRetryFeedback(`ಮರುಪ್ರಯತ್ನಿಸಲಾಗುತ್ತಿದೆ (${attempt}/${maxRetries})... / Retrying (${attempt}/${maxRetries})...`);
        },
      });
      setLastFailedUtterance(null);
      handleVoiceResponse(response);
    } catch (error) {
      console.error('Error processing command:', error);
      const errId = `msg_${msgIdCounter.current++}`;
      const errorMsg = {
        id: errId,
        sender: 'assistant',
        textEn: `Error: ${error.message || 'Could not process instruction'}`,
        textKn: 'ದೋಷ: ಪ್ರಕ್ರಿಯೆಗೊಳಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ.',
        timestamp: 'Now',
        isError: true,
        failedUtteranceText: text,
      };
      setMessages((prev) => [...prev, errorMsg]);
      setLastFailedUtterance({
        isAudio: false,
        text,
        errorMsg: error.message,
      });
      if (onNotification) {
        onNotification({ type: 'error', message: error.message });
      }
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
        setProcessingState('idle');
        setRetryFeedback('');
      }
    }
  }

  async function handleRetryLastUtterance() {
    if (!lastFailedUtterance || isLoading || processingState === 'processing' || processingState === 'retrying') {
      return;
    }

    if (lastFailedUtterance.isAudio) {
      setProcessingState('retrying');
      setRetryFeedback('ಧ್ವನಿ ಮರುಪ್ರಯತ್ನಿಸಲಾಗುತ್ತಿದೆ... / Retrying audio transcription...');
      await speechService.retryLastAudio({
        onRetry: ({ attempt, maxRetries }) => {
          if (!isMountedRef.current) return;
          setRetryFeedback(`ಮರುಪ್ರಯತ್ನಿಸಲಾಗುತ್ತಿದೆ (${attempt}/${maxRetries})... / Retrying (${attempt}/${maxRetries})...`);
        },
        onResult: ({ transcript, isFinal, isSilence, messageEn, messageKn }) => {
          if (!isMountedRef.current) return;
          if (isFinal) {
            if (isSilence || !transcript || !transcript.trim()) {
              handleSilenceDetected(messageEn, messageKn);
            } else {
              setLastFailedUtterance(null);
              setProcessingState('processing');
              handleUserUtterance(transcript.trim());
            }
          }
        },
        onError: (err) => {
          if (!isMountedRef.current) return;
          setProcessingState('idle');
          setRetryFeedback('');
          const msgEn = err?.messageEn || err?.message || 'Retry failed. Please use text input.';
          if (onNotification) {
            onNotification({ type: 'error', message: msgEn });
          }
        },
        onEnd: () => {
          if (!isMountedRef.current) return;
          setProcessingState((prev) => (prev === 'retrying' ? 'idle' : prev));
          setRetryFeedback('');
        },
      });
    } else if (lastFailedUtterance.text) {
      handleUserUtterance(lastFailedUtterance.text, { isRetry: true });
    }
  }

  async function handleConfirmPending() {
    if (!pendingTransaction || isConfirming) return;
    setIsConfirming(true);
    setConfirmError(null);
    try {
      // Pass expected baseline for double server-side stale-check protection
      const baseline = pendingTransaction.balance_preview?.baseline_balance;
      const res = await confirmVoiceTransaction(
        pendingTransaction.pending_id,
        sessionIdRef.current,
        baseline
      );
      setConfirmError(null);
      handleVoiceResponse(res);
    } catch (err) {
      console.error('Confirmation error:', err);
      const isStale =
        err.status === 409 ||
        (err.message || '').includes('balance has changed') ||
        (err.message || '').includes('stale');

      if (isStale) {
        // Refresh active pending to show the updated balance preview
        await checkActivePending();
        const staleMsg =
          err.message ||
          'Customer balance changed since preview was generated. Please review updated balance before confirming.';
        setConfirmError({
          isStale: true,
          message: staleMsg,
        });
        if (onNotification) {
          onNotification({ type: 'warning', message: staleMsg });
        }
      } else {
        // Network or other error: user can safely recover without duplicate commits
        const errMsg = err.message || 'Failed to confirm transaction. Please try again.';
        setConfirmError({
          isStale: false,
          message: errMsg,
        });
        if (onNotification) {
          onNotification({ type: 'error', message: errMsg });
        }
      }
    } finally {
      if (isMountedRef.current) {
        setIsConfirming(false);
      }
    }
  }

  async function handleCancelPending() {
    if (!pendingTransaction || isConfirming) return;
    setIsLoading(true);
    try {
      const res = await cancelVoiceTransaction(
        pendingTransaction.pending_id,
        sessionIdRef.current
      );
      setConfirmError(null);
      handleVoiceResponse(res);
    } catch (err) {
      if (onNotification) {
        onNotification({ type: 'error', message: err.message });
      }
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
      }
    }
  }

  async function handleSaveAmountCorrection() {
    if (!pendingTransaction || !editAmountValue || isConfirming) return;
    const newAmount = parseInt(editAmountValue, 10);
    if (isNaN(newAmount) || newAmount <= 0) {
      if (onNotification) {
        onNotification({ type: 'warning', message: 'Please enter a valid amount greater than zero.' });
      }
      return;
    }

    setIsLoading(true);
    setConfirmError(null);
    try {
      const res = await correctVoiceTransaction(
        pendingTransaction.pending_id,
        { amount: newAmount },
        sessionIdRef.current
      );
      setIsEditingAmount(false);
      handleVoiceResponse(res);
    } catch (err) {
      if (onNotification) {
        onNotification({ type: 'error', message: err.message });
      }
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false);
      }
    }
  }

  function handleSelectDisambiguationCustomer(customer) {
    setDisambiguationOptions(null);
    const text = `${customer.name} ge maadu`;
    handleUserUtterance(text);
  }

  function handleReplayAudio(target) {
    const spokenText = typeof target === 'string' ? target : target?.spokenText;
    const targetMsgId = typeof target === 'string' ? null : target?.id;

    if (!spokenText || !spokenText.trim()) return;

    // If this specific message is currently playing, clicking stops it
    if (targetMsgId && playingMessageId === targetMsgId) {
      speechService.stopSpeaking();
      setPlayingMessageId(null);
      setPlayingProvider(null);
      return;
    }

    // Stop any existing playback and start this message
    speechService.stopSpeaking();
    if (targetMsgId) {
      setPlayingMessageId(targetMsgId);
    }

    speechService.speak(spokenText, {
      language,
      onStart: ({ provider }) => {
        if (!isMountedRef.current) return;
        if (targetMsgId) setPlayingMessageId(targetMsgId);
        setPlayingProvider(provider);
      },
      onProviderUsed: ({ provider, isFallback }) => {
        if (!isMountedRef.current) return;
        if (targetMsgId) {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === targetMsgId ? { ...m, ttsProvider: provider, isTtsFallback: isFallback } : m
            )
          );
        }
      },
      onFallback: ({ reason }) => {
        if (!isMountedRef.current) return;
        if (onNotification) {
          onNotification({
            type: 'info',
            message: `Gnani TTS fallback active (${reason}). Playing via Browser Speech.`,
          });
        }
      },
      onEnd: () => {
        if (!isMountedRef.current) return;
        setPlayingMessageId(null);
        setPlayingProvider(null);
      },
      onError: () => {
        if (!isMountedRef.current) return;
        setPlayingMessageId(null);
        setPlayingProvider(null);
      },
    });
  }

  return (
    <div className="voice-assistant-view">
      {/* Top Controls Bar */}
      <div className="voice-controls-bar">
        <div className={`provider-info-badge ${providerInfo.isGnaniActive ? 'gnani-active' : 'fallback-active'}`}>
          <span className="badge-icon">{providerInfo.isGnaniActive ? '⚡' : '🎙️'}</span>
          <div className="badge-details">
            <span className="badge-name">{providerInfo.providerName}</span>
            <span className="badge-note">{providerInfo.gnaniStatusNote}</span>
          </div>
        </div>

        <div className="voice-settings">
          <div className="setting-item">
            <label htmlFor="lang-select">Language:</label>
            <select
              id="lang-select"
              value={language}
              onChange={(e) => handleLanguageChange(e.target.value)}
              className="lang-dropdown"
            >
              <option value="kn-IN">ಕನ್ನಡ (Kannada - kn-IN)</option>
              <option value="en-IN">English (India - en-IN)</option>
            </select>
          </div>

          <button
            type="button"
            className={`audio-toggle-btn ${audioEnabled ? 'active' : 'muted'}`}
            onClick={handleAudioToggle}
            title={audioEnabled ? 'Audio replies enabled (Click to mute)' : 'Audio muted (Click to unmute)'}
          >
            {audioEnabled ? '🔊 ಧ್ವನಿ On' : '🔇 Mute'}
          </button>
        </div>
      </div>

      {/* Main Mic Section with Dynamic Processing Lifecycle */}
      <div className="central-mic-container">
        <div className={`mic-ring-pulse ${processingState === 'recording' ? 'listening' : ''} ${processingState}`}>
          <button
            type="button"
            className={`mic-main-button ${processingState === 'recording' ? 'active-mic' : ''} ${processingState}`}
            onClick={toggleListening}
            disabled={processingState === 'processing' || processingState === 'retrying'}
            aria-label={
              processingState === 'recording'
                ? 'Stop listening'
                : processingState === 'processing'
                ? 'Processing speech...'
                : processingState === 'retrying'
                ? 'Retrying request...'
                : 'Start speaking'
            }
          >
            <span className="mic-symbol">
              {processingState === 'recording'
                ? '⏹️'
                : processingState === 'processing'
                ? '⏳'
                : processingState === 'retrying'
                ? '🔄'
                : '🎙️'}
            </span>
          </button>
        </div>

        <div className="mic-status-label">
          {processingState === 'recording' && (
            <span className="listening-text">
              <span className="live-dot"></span>
              ಕೇಳುತ್ತಿದ್ದೇವೆ... ಮಾತನಾಡಿ (ಗರಿಷ್ಠ 30 ಸೆಕೆಂಡುಗಳು) / Listening... Speak now (max 30s)
            </span>
          )}
          {processingState === 'processing' && (
            <span className="processing-text">
              ⏳ ಪ್ರಕ್ರಿಯೆಗೊಳಿಸಲಾಗುತ್ತಿದೆ... / Processing...
            </span>
          )}
          {processingState === 'retrying' && (
            <span className="retrying-text">
              🔄 {retryFeedback || 'ಮರುಪ್ರಯತ್ನಿಸಲಾಗುತ್ತಿದೆ... / Retrying...'}
            </span>
          )}
          {processingState === 'idle' && (
            <span className="idle-text">ಮೈಕ್ ಮೇಲೆ ಕ್ಲಿಕ್ ಮಾಡಿ / Click mic to speak</span>
          )}
        </div>

        {/* Actionable Retry Banner for Failed Utterance or Recording */}
        {lastFailedUtterance && processingState === 'idle' && (
          <div className="retry-action-banner">
            <span>⚠️ {lastFailedUtterance.errorMsg || 'Action failed.'}</span>
            <button
              type="button"
              className="retry-action-btn"
              onClick={handleRetryLastUtterance}
            >
              🔄 ಮರುಪ್ರಯತ್ನಿಸಿ / Retry
            </button>
          </div>
        )}

        {/* Live speech preview */}
        {liveTranscript && (
          <div className="live-transcript-box">
            <span className="preview-prefix">Recognized: </span>
            <span className="preview-text">"{liveTranscript}"</span>
          </div>
        )}
      </div>

      {/* Active Pending Confirmation Card */}
      {pendingTransaction && (
        <div className="pending-confirmation-card">
          <div className="pending-card-header">
            <div className="pending-header-title">
              <span className="warning-icon">⚠️</span>
              <div>
                <h3 className="pending-title">ದೃಢೀಕರಣ ಅಗತ್ಯವಿದೆ / Confirmation Required</h3>
                <p className="pending-subtitle">Verify details before adding to ledger</p>
              </div>
            </div>
            <span
              className={`txn-type-badge ${
                pendingTransaction.transaction_type === 'CREDIT' ? 'badge-credit' : 'badge-payment'
              }`}
            >
              {pendingTransaction.transaction_type === 'CREDIT' ? 'ಉದ್ದಾರ / CREDIT' : 'ಜಮಾ / PAYMENT'}
            </span>
          </div>

          <div className="pending-card-body">
            <div className="pending-data-row">
              <div className="data-col">
                <span className="data-label">ಗ್ರಾಹಕರು / Customer</span>
                <span className="data-value customer-name">
                  👤 {pendingTransaction.customer_name}
                  {pendingTransaction.customer_phone && (
                    <span className="customer-phone"> ({pendingTransaction.customer_phone})</span>
                  )}
                </span>
              </div>

              <div className="data-col">
                <span className="data-label">ಮೊತ್ತ / Amount</span>
                {isEditingAmount ? (
                  <div className="edit-amount-group">
                    <span className="rupee-sign">₹</span>
                    <input
                      type="number"
                      className="edit-amount-input"
                      value={editAmountValue}
                      onChange={(e) => setEditAmountValue(e.target.value)}
                      min="1"
                      autoFocus
                    />
                    <button
                      type="button"
                      className="save-edit-btn"
                      onClick={handleSaveAmountCorrection}
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      className="cancel-edit-btn"
                      onClick={() => setIsEditingAmount(false)}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="amount-display-row">
                    <span className="data-value amount-value">₹ {pendingTransaction.amount}</span>
                    <button
                      type="button"
                      className="edit-amount-icon-btn"
                      onClick={() => setIsEditingAmount(true)}
                      title="Edit amount"
                    >
                      ✏️ Edit
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Authoritative Balance Preview & Accounting Breakdown */}
            {pendingTransaction.balance_preview && (
              <div className="balance-preview-box">
                <div className="preview-header">
                  <span className="preview-title">📊 ನಿವ್ವಳ ಲೆಕ್ಕ ಪರಿಶೀಲನೆ / Authoritative Balance Preview</span>
                </div>

                <div className="preview-metrics-grid">
                  {/* Current Balance */}
                  <div className="preview-metric-card current-metric">
                    <span className="metric-tag">ಈಗಿನ ಬಾಕಿ / Current</span>
                    <span className="metric-figure">
                      ₹ {pendingTransaction.balance_preview.current_outstanding}
                    </span>
                    {pendingTransaction.balance_preview.current_advance > 0 && (
                      <span className="metric-sub-advance">
                        (ಮುಂಗಡ / Advance: ₹{pendingTransaction.balance_preview.current_advance})
                      </span>
                    )}
                    <span className="metric-desc">
                      {pendingTransaction.balance_preview.current_advance > 0
                        ? 'Current Advance Deposit'
                        : 'Current Outstanding'}
                    </span>
                  </div>

                  {/* Operation Indicator */}
                  <div className="preview-arrow">
                    {pendingTransaction.transaction_type === 'CREDIT' ? '➕' : '➖'}
                  </div>

                  {/* Transaction Delta */}
                  <div className="preview-metric-card delta-metric">
                    <span className="metric-tag">
                      {pendingTransaction.transaction_type === 'CREDIT' ? 'ಹೊಸ ಉದ್ದಾರ / New Credit' : 'ಜಮಾ / Payment Received'}
                    </span>
                    <span
                      className={`metric-figure ${
                        pendingTransaction.transaction_type === 'CREDIT' ? 'amt-credit' : 'amt-payment'
                      }`}
                    >
                      {pendingTransaction.transaction_type === 'CREDIT' ? '+' : '-'} ₹ {pendingTransaction.amount}
                    </span>
                    <span className="metric-desc">
                      {pendingTransaction.transaction_type === 'CREDIT'
                        ? 'Added to outstanding dues'
                        : 'Deducted from balance'}
                    </span>
                  </div>

                  {/* Result Indicator */}
                  <div className="preview-arrow">➔</div>

                  {/* Expected Resulting Balance */}
                  <div className="preview-metric-card expected-metric">
                    <span className="metric-tag">ಫಲಿತಾಂಶ / Expected</span>
                    <span className="metric-figure expected-figure">
                      ₹ {pendingTransaction.balance_preview.expected_outstanding}
                    </span>
                    {pendingTransaction.balance_preview.expected_advance > 0 && (
                      <span className="metric-sub-advance advance-highlight">
                        ಮುಂಗಡ / Advance: ₹{pendingTransaction.balance_preview.expected_advance}
                      </span>
                    )}
                    <span className="metric-desc">
                      {pendingTransaction.balance_preview.expected_advance > 0
                        ? 'Advance Balance'
                        : 'Expected Outstanding'}
                    </span>
                  </div>
                </div>

                {/* Plain-Language Accounting Explanation Callout */}
                <div
                  className={`explanation-callout ${
                    pendingTransaction.balance_preview.expected_advance > 0
                      ? 'callout-advance'
                      : pendingTransaction.balance_preview.expected_outstanding > 0
                      ? 'callout-due'
                      : 'callout-settled'
                  }`}
                >
                  <span className="callout-icon">
                    {pendingTransaction.balance_preview.expected_advance > 0
                      ? '💰'
                      : pendingTransaction.balance_preview.expected_outstanding > 0
                      ? '📌'
                      : '🎉'}
                  </span>
                  <div className="callout-text">
                    <strong className="callout-kn">
                      {pendingTransaction.balance_preview.balance_explanation_kn}
                    </strong>
                    <span className="callout-en">
                      {pendingTransaction.balance_preview.balance_explanation}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Prompt Question */}
            <div className="pending-prompt-message">
              <span className="prompt-speaker">🤖 DukaanVoice:</span>
              <p className="prompt-kn">
                {pendingTransaction.transaction_type === 'CREDIT'
                  ? `${pendingTransaction.customer_name} ge ₹${pendingTransaction.amount} credit add maadbekaa?`
                  : `${pendingTransaction.customer_name} inda ₹${pendingTransaction.amount} payment add maadbekaa?`}
              </p>
            </div>

            {/* Stale Balance Warning Alert */}
            {confirmError?.isStale && (
              <div className="stale-preview-alert">
                <div className="stale-alert-header">
                  <span className="stale-alert-icon">⚠️</span>
                  <div>
                    <strong>ಗ್ರಾಹಕರ ಬಾಕಿ ಬದಲಾಗಿದೆ / Balance Changed</strong>
                    <p>{confirmError.message}</p>
                  </div>
                </div>
              </div>
            )}

            {/* General Confirmation Error Alert with Recovery Button */}
            {confirmError && !confirmError.isStale && (
              <div className="confirm-error-alert">
                <div className="error-alert-header">
                  <span className="error-alert-icon">❌</span>
                  <div>
                    <strong>ದೋಷ / Error</strong>
                    <p>{confirmError.message}</p>
                  </div>
                </div>
                <button
                  type="button"
                  className="retry-confirm-btn"
                  onClick={handleConfirmPending}
                  disabled={isConfirming}
                >
                  🔄 {isConfirming ? 'ಮರುಪ್ರಯತ್ನಿಸಲಾಗುತ್ತಿದೆ...' : 'ದೃಢೀಕರಣ ಮರುಪ್ರಯತ್ನಿಸಿ / Retry Confirmation'}
                </button>
              </div>
            )}

            {/* Audit Trail info */}
            {pendingTransaction.audit_trail && pendingTransaction.audit_trail.length > 1 && (
              <div className="audit-trail-history">
                <span className="audit-badge-title">Correction History:</span>
                <ul className="audit-list">
                  {pendingTransaction.audit_trail.map((entry, idx) => (
                    <li key={idx} className="audit-item">
                      <span className="audit-action">{entry.action}:</span> {entry.details}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="pending-card-actions">
            <button
              type="button"
              className="confirm-btn"
              onClick={handleConfirmPending}
              disabled={isConfirming || isLoading || isEditingAmount}
            >
              {isConfirming ? '⏳ Confirming...' : '✅ ಹೌದು / Confirm Transaction'}
            </button>
            <button
              type="button"
              className="cancel-btn"
              onClick={handleCancelPending}
              disabled={isConfirming || isLoading}
            >
              ❌ ಇಲ್ಲ / Cancel
            </button>
          </div>
        </div>
      )}

      {/* Disambiguation Card */}
      {disambiguationOptions && (
        <div className="disambiguation-card">
          <h4 className="disambiguation-title">
            ಒಂದಕ್ಕಿಂತ ಹೆಚ್ಚು ಗ್ರಾಹಕರು ಸಿಕ್ಕಿದ್ದಾರೆ / Multiple Customers Found
          </h4>
          <p className="disambiguation-prompt">ದಯವಿಟ್ಟು ಒಬ್ಬರನ್ನು ಆಯ್ಕೆಮಾಡಿ / Please select the intended customer:</p>
          <div className="disambiguation-list">
            {disambiguationOptions.map((opt) => (
              <button
                key={opt.id}
                type="button"
                className="disambiguation-item-btn"
                onClick={() => handleSelectDisambiguationCustomer(opt)}
              >
                <span className="opt-name">👤 {opt.name}</span>
                {opt.phone && <span className="opt-phone">📞 {opt.phone}</span>}
                <span className="opt-action">ಆಯ್ಕೆ / Select ➔</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Quick Demo Chips */}
      <div className="demo-chips-section">
        <span className="demo-chips-title">💡 ಡೆಮೋ ಪರೀಕ್ಷಾ ವಾಕ್ಯಗಳು / Quick Demo Expressions:</span>
        <div className="demo-chips-list">
          {DEMO_CHIPS.map((chip, idx) => (
            <button
              key={idx}
              type="button"
              className="demo-chip-btn"
              onClick={() => handleUserUtterance(chip.label)}
              disabled={isLoading || processingState === 'processing' || processingState === 'retrying'}
              title={`Simulate: "${chip.label}"`}
            >
              <span className="chip-label">"{chip.label}"</span>
              <span className="chip-desc">{chip.desc}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Manual Input Fallback */}
      <form
        className="manual-input-form"
        onSubmit={(e) => {
          e.preventDefault();
          handleUserUtterance(inputText);
        }}
      >
        <input
          type="text"
          className="manual-input-field"
          placeholder="ಟೈಪ್ ಮಾಡಿ (ಉದಾ: 'Ramesh ge 430 rupees udhaar haaku') / Type command here..."
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          disabled={isLoading || processingState === 'processing' || processingState === 'retrying'}
        />
        <button
          type="submit"
          className="send-btn"
          disabled={!inputText.trim() || isLoading || processingState === 'processing' || processingState === 'retrying'}
        >
          {isLoading ? '...' : 'ಕಳುಹಿಸಿ / Send'}
        </button>
      </form>

      {/* Conversation History Stream */}
      <div className="conversation-section">
        <h3 className="section-title">ಸಂಭಾಷಣೆ ಇತಿಹಾಸ / Conversation History</h3>
        <div className="conversation-stream">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`chat-bubble-row ${msg.sender === 'user' ? 'row-user' : 'row-assistant'}`}
            >
              <div
                className={`chat-bubble ${
                  msg.sender === 'user' ? 'bubble-user' : 'bubble-assistant'
                } ${msg.isError ? 'bubble-error' : ''} ${msg.isSilenceNotice ? 'bubble-silence' : ''}`}
              >
                <div className="bubble-header">
                  <span className="sender-tag">
                    {msg.sender === 'user' ? '👤 ಅಂಗಡಿಯವರು / You' : '🏪 DukaanVoice'}
                  </span>
                  <span className="timestamp">{msg.timestamp}</span>
                </div>

                {msg.textKn && <p className="bubble-kannada">{msg.textKn}</p>}
                <p className="bubble-english">{msg.textEn}</p>

                {/* Inline retry button for failed utterance */}
                {msg.isError && (msg.failedUtteranceText || msg.canRetryAudio) && (
                  <button
                    type="button"
                    className="retry-inline-btn"
                    onClick={handleRetryLastUtterance}
                  >
                    🔄 ಮರುಪ್ರಯತ್ನಿಸಿ / Retry
                  </button>
                )}

                {/* Balance display badge if inquiry */}
                {msg.balanceInfo && (
                  <div className="chat-balance-badge">
                    <span className="badge-cust">{msg.balanceInfo.customer_name}</span>
                    <span className="badge-amt">
                      ಒಟ್ಟು ಬಾಕಿ / Outstanding: ₹{msg.balanceInfo.outstanding_balance}
                    </span>
                  </div>
                )}

                {/* Confirmed Txn summary badge */}
                {msg.confirmedTxn && (
                  <div className="chat-confirmed-badge">
                    <span>
                      ✅ Txn #{msg.confirmedTxn.id} Recorded: {msg.confirmedTxn.transaction_type} ₹
                      {msg.confirmedTxn.amount}
                    </span>
                  </div>
                )}

                {/* Audio playback controls & provider indicator for assistant messages */}
                {msg.sender === 'assistant' && msg.spokenText && (
                  <div className="chat-audio-controls-row">
                    <button
                      type="button"
                      className={`replay-audio-btn ${playingMessageId === msg.id ? 'btn-stop-audio active-playing' : 'btn-play-audio'}`}
                      onClick={() => handleReplayAudio(msg)}
                      title={playingMessageId === msg.id ? 'Stop audio playback' : 'Play voice output again'}
                    >
                      {playingMessageId === msg.id ? '⏹️ Stop' : '🔊 Play'}
                    </button>
                    {msg.ttsProvider && (
                      <span
                        className={`tts-provider-tag ${
                          msg.ttsProvider.includes('Gnani') ? 'tag-gnani' : 'tag-browser'
                        }`}
                        title={
                          msg.ttsProvider.includes('Gnani')
                            ? 'Audio generated by Gnani Timbre v3.0'
                            : `Audio generated by Browser Speech Synthesis (${msg.isTtsFallback ? 'Fallback' : 'Native'})`
                        }
                      >
                        {msg.ttsProvider.includes('Gnani') ? '⚡ Gnani Timbre' : '🎙️ Browser Voice'}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>
      </div>
    </div>
  );
}
