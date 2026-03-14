import React from 'react';
import { Link } from 'react-router-dom';

const MessageList = ({ messages, listRef }) => (
  <div className="chat-messages" ref={listRef}>
    {messages.map((msg, i) => {
      if (msg.role === 'typing') {
        return (
          <div key={i} className="chat-msg chat-msg--typing">
            Assistant is typing…
          </div>
        );
      }

      return (
        <div key={i} className={`chat-msg chat-msg--${msg.role}`}>
          <div>{msg.text}</div>
          {msg.role === 'assistant' && msg.products && msg.products.length > 0 && (
            <div className="chat-products">
              {msg.products.map((p) => (
                <Link key={p.id} to={p.url} className="chat-product-link">
                  {p.name} — ${p.price}
                </Link>
              ))}
            </div>
          )}
        </div>
      );
    })}
  </div>
);

export default MessageList;
