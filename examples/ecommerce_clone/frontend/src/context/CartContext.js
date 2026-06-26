import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getCart } from '../api';
import { useAuth } from './AuthContext';

const CartContext = createContext({ cartCount: 0, refreshCart: () => {} });

export const CartProvider = ({ children }) => {
  const { user } = useAuth();
  const [cartCount, setCartCount] = useState(0);

  const refreshCart = useCallback(async () => {
    if (!user) { setCartCount(0); return; }
    try {
      const data = await getCart();
      setCartCount(data?.item_count ?? (Array.isArray(data?.items) ? data.items.reduce((s, i) => s + (i.quantity || 0), 0) : 0));
    } catch {
      setCartCount(0);
    }
  }, [user]);

  useEffect(() => { refreshCart(); }, [refreshCart]);

  return (
    <CartContext.Provider value={{ cartCount, refreshCart }}>
      {children}
    </CartContext.Provider>
  );
};

export const useCart = () => useContext(CartContext);
