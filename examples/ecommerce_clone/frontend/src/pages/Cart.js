import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getCart } from '../api';
import CartItem from '../components/CartItem';
import { useAuth } from '../context/AuthContext';
import { useCart } from '../context/CartContext';

const Cart = () => {
  const { user } = useAuth();
  const { refreshCart } = useCart();
  const navigate = useNavigate();
  const [cart, setCart] = useState(null);

  const loadCart = async () => {
    if (user) {
      const data = await getCart();
      setCart(data);
      refreshCart();
    }
  };

  useEffect(() => {
    if (!user) { navigate('/login'); return; }
    loadCart();
  }, [user]);

  if (!cart) return <div className="page">Loading cart...</div>;

  return (
    <div className="page" style={{ maxWidth: 800, margin: '0 auto' }}>
      <h1 className="page__title">Shopping Cart</h1>
      {!cart.items || cart.items.length === 0 ? (
        <div className="empty-state">
          <p>Your cart is empty.</p>
          <button onClick={() => navigate('/products')} className="btn btn--primary">Shop Now</button>
        </div>
      ) : (
        <>
          <div className="card">
            {cart.items.map((item) => <CartItem key={item.id} item={item} onUpdate={loadCart} />)}
          </div>
          <div style={{ marginTop: '1.25rem', textAlign: 'right' }}>
            <button onClick={() => navigate('/checkout')} className="btn btn--primary">
              Proceed to Checkout
            </button>
          </div>
        </>
      )}
    </div>
  );
};

export default Cart;
