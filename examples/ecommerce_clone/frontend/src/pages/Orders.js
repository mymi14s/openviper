import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getOrders } from '../api';
import { useAuth } from '../context/AuthContext';

const Orders = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) { navigate('/login'); return; }
    getOrders().then((data) => { setOrders(Array.isArray(data) ? data : []); setLoading(false); });
  }, [user]);

  if (loading) return <div className="page">Loading orders...</div>;

  return (
    <div className="page">
      <h1 className="page__title">My Orders</h1>
      {orders.length === 0 ? (
        <div className="empty-state">
          <p>You have no orders yet.</p>
          <button onClick={() => navigate('/products')} className="btn btn--primary">Start Shopping</button>
        </div>
      ) : (
        <div className="card" style={{ overflowX: 'auto' }}>
          <table className="orders-table">
            <thead>
              <tr>
                <th>Order ID</th>
                <th>Date</th>
                <th>Total</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.id}>
                  <td data-label="Order ID">{order.id?.slice(0, 8)}…</td>
                  <td data-label="Date">{order.created_at ? new Date(order.created_at).toLocaleDateString() : '-'}</td>
                  <td data-label="Total">${order.total_price}</td>
                  <td data-label="Status">
                    <span className={`badge badge--${order.status}`}>{order.status}</span>
                  </td>
                  <td data-label="">
                    <Link to={`/orders/${order.id}`} style={{ color: '#0078d4' }}>View</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default Orders;
