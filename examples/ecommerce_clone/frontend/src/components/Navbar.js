import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useCart } from '../context/CartContext';

const Navbar = () => {
  const { user, logout } = useAuth();
  const { cartCount } = useCart();
  const navigate = useNavigate();

  const handleLogout = () => { logout(); navigate('/login'); };

  return (
    <nav className="navbar">
      <Link to="/" className="navbar__brand">🛒 EcommerceClone</Link>
      <div className="navbar__links">
        <Link to="/products">Products</Link>
        <Link to="/cart" className="navbar__cart">
          🛒
          {cartCount > 0 && <span className="cart-badge">{cartCount > 99 ? '99+' : cartCount}</span>}
        </Link>
        {user ? (
          <>
            <Link to="/orders">Orders</Link>
            <span className="navbar__user">Hi, {user.username}</span>
            <button onClick={handleLogout} className="navbar__btn">Logout</button>
          </>
        ) : (
          <>
            <Link to="/login">Login</Link>
            <Link to="/register" style={{ color: '#f0c040' }}>Register</Link>
          </>
        )}
      </div>
    </nav>
  );
};

export default Navbar;
