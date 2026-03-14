import React, { useState } from 'react';

const MessageInput = ({ onSend, disabled }) => {
  const [value, setValue] = useState('');

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue('');
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="chat-input-area">
      <textarea
        className="chat-input"
        rows={1}
        placeholder="Ask about products…"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKey}
        disabled={disabled}
      />
      <button className="chat-send" onClick={submit} disabled={disabled || !value.trim()} title="Send">
        ➤
      </button>
    </div>
  );
};

export default MessageInput;
