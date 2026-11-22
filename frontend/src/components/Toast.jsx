import { useEffect } from 'react';

export function Toast({ notification, onClose }) {
  useEffect(() => {
    if (!notification) return;
    const timer = setTimeout(() => {
      onClose();
    }, 4000);
    return () => clearTimeout(timer);
  }, [notification, onClose]);

  if (!notification) return null;

  const icons = {
    success: '✅',
    error: '❌',
    warning: '⚠️',
    info: 'ℹ️',
  };

  return (
    <div className={`toast-container toast-${notification.type || 'info'}`}>
      <span className="toast-icon">{icons[notification.type] || 'ℹ️'}</span>
      <span className="toast-message">{notification.message}</span>
      <button type="button" className="toast-close-btn" onClick={onClose}>
        ✕
      </button>
    </div>
  );
}
