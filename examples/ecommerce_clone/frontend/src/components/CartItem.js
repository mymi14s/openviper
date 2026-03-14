import React from 'react';
import { removeFromCart, updateCartItem } from '../api';

const CartItem = ({ item, onUpdate }) => {
  const handleRemove = async () => { await removeFromCart({ item_id: item.id }); onUpdate(); };
  const handleQty = async (qty) => {
    if (qty < 1) await removeFromCart({ item_id: item.id });
    else await updateCartItem({ item_id: item.id, quantity: qty });
    onUpdate();
  };

  const displayName = item.product_name || `Product ${item.product_id?.slice(0, 8) || ''}`;

  return (
    <div className="cart-item">
      <span className="cart-item__name">{displayName}</span>
      <div className="cart-item__qty">
        <button className="qty-btn" onClick={() => handleQty(item.quantity - 1)}>−</button>
        <span>{item.quantity}</span>
        <button className="qty-btn" onClick={() => handleQty(item.quantity + 1)}>+</button>
      </div>
      <button onClick={handleRemove} className="btn btn--danger btn--sm">Remove</button>
    </div>
  );
};

export default CartItem;
