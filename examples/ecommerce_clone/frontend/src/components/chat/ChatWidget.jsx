import React, { useState } from 'react';
import ChatWindow from './ChatWindow';
import './chat.css';

const ChatWidget = () => {
  const [open, setOpen] = useState(false);

  return (
    <>
      {open && <ChatWindow onClose={() => setOpen(false)} />}
      <button
        className="chat-fab"
        onClick={() => setOpen((v) => !v)}
        title={open ? 'Close assistant' : 'Open shopping assistant'}
        aria-label="Shopping assistant"
      >
        {open ? '✕' : '💬'}
      </button>
    </>
  );
};

export default ChatWidget;
