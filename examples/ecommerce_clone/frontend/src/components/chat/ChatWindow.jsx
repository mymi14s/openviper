import React, { useEffect, useRef, useState } from 'react';
import MessageList from './MessageList';
import MessageInput from './MessageInput';
import { sendChatMessage } from '../../api';

const SUGGESTIONS = [
  'What are your best sellers?',
  'Show me electronics under $100',
  'Do you have sports gear?',
  'What books do you recommend?',
];

const WELCOME = {
  role: 'assistant',
  text: 'Hi! 👋 I\'m your shopping assistant. Ask me anything about our products!',
  products: [],
};

const ChatWindow = ({ onClose }) => {
  const [messages, setMessages] = useState([WELCOME]);
  const [loading, setLoading] = useState(false);
  const listRef = useRef(null);

  // Scroll to bottom whenever messages change
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages]);

  const send = async (text) => {
    setMessages((prev) => [...prev, { role: 'user', text }]);
    setMessages((prev) => [...prev, { role: 'typing' }]);
    setLoading(true);

    try {
      const data = await sendChatMessage(text);
      setMessages((prev) => [
        ...prev.filter((m) => m.role !== 'typing'),
        {
          role: 'assistant',
          text: data.reply || 'Sorry, I could not get a response.',
          products: data.related_products || [],
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev.filter((m) => m.role !== 'typing'),
        { role: 'assistant', text: 'Network error. Please try again.', products: [] },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-window">
      <div className="chat-header">
        <span className="chat-header__title">🛍️ Shopping Assistant</span>
        <button className="chat-header__close" onClick={onClose} title="Close">✕</button>
      </div>

      <MessageList messages={messages} listRef={listRef} />

      {/* Suggested quick questions — only shown at the start */}
      {messages.length === 1 && (
        <div className="chat-suggestions">
          {SUGGESTIONS.map((q) => (
            <button key={q} className="chat-suggestion" onClick={() => send(q)}>
              {q}
            </button>
          ))}
        </div>
      )}

      <MessageInput onSend={send} disabled={loading} />
    </div>
  );
};

export default ChatWindow;
