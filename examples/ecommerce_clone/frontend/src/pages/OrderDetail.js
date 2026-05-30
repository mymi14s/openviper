import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getOrder } from '../api';

const OrderDetail = () => {
  const { id } = useParams();
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getOrder(id).then((data) => { setOrder(data); setLoading(false); });
  }, [id]);

  if (loading) return <div className="page">Loading order...</div>;
  if (!order || order.error) return <div className="page" style={{ color: 'red' }}>Order not found.</div>;

  return (
    <div className="page" style={{ maxWidth: 800, margin: '0 auto' }}>
      <h1 className="page__title">Order Details</h1>
      <div className="card" style={{ padding: '1.25rem', marginBottom: '1.25rem' }}>
        <p><strong>Order ID:</strong> {order.id}</p>
        <p><strong>Date:</strong> {order.created_at ? new Date(order.created_at).toLocaleString() : '-'}</p>
        <p><strong>Status:</strong> <span className={`badge badge--${order.status}`}>{order.status}</span></p>
        <p><strong>Shipping Address:</strong> {order.shipping_address}</p>
        <p><strong>Total:</strong> <span style={{ color: '#b12704', fontWeight: 'bold', fontSize: '1.2rem' }}>${order.total_price}</span></p>
      </div>

      {order.items && order.items.length > 0 && (
        <div className="card">
          <h2 style={{ padding: '0.75rem 1rem', borderBottom: '1px solid #eee', margin: 0, fontSize: '1.1rem' }}>Items</h2>
          {order.items.map((item) => (
            <div key={item.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.65rem 1rem', borderBottom: '1px solid #eee', flexWrap: 'wrap', gap: '0.5rem' }}>
              <span style={{ flex: 1 }}>Product: {item.product_id}</span>
              <span>Qty: {item.quantity}</span>
              <span style={{ fontWeight: 'bold' }}>${item.price}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: '1.25rem' }}>
        <Link to="/orders" style={{ color: '#0078d4' }}>← Back to Orders</Link>
      </div>
    </div>
  );
};

export default OrderDetail;
