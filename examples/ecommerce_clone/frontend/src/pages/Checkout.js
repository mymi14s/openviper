import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { checkout } from '../api';
import { useAuth } from '../context/AuthContext';

const Checkout = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [shippingAddress, setShippingAddress] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!shippingAddress.trim()) { setError('Shipping address is required'); return; }
    setLoading(true);
    const result = await checkout({ shipping_address: shippingAddress });
    setLoading(false);
    if (result.id) navigate(`/orders/${result.id}`);
    else setError(result.error || 'Checkout failed. Please try again.');
  };

  if (!user) { navigate('/login'); return null; }

  return (
    <div className="page">
      <h1 className="page__title">Checkout</h1>
      {error && <div className="alert alert--error">{error}</div>}
      <div className="form-card" style={{ maxWidth: 600 }}>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Shipping Address</label>
            <textarea value={shippingAddress} onChange={(e) => setShippingAddress(e.target.value)}
              rows={4} placeholder="Enter your full shipping address..." />
          </div>
          <button type="submit" disabled={loading} className="btn btn--primary btn--full">
            {loading ? 'Placing Order...' : 'Place Order'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default Checkout;
