import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const Login = () => {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: '', password: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    const result = await login(form.username, form.password);
    setLoading(false);
    if (result.access_token) navigate('/');
    else setError(result.error || 'Login failed. Check your credentials.');
  };

  return (
    <div className="page">
      <div className="form-card">
        <h1 style={{ textAlign: 'center', marginTop: 0 }}>Sign In</h1>
        {error && <div className="alert alert--error">{error}</div>}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Username</label>
            <input type="text" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
          </div>
          <button type="submit" disabled={loading} className="btn btn--primary btn--full">
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
        <p style={{ textAlign: 'center', marginTop: '1.25rem' }}>
          New customer? <Link to="/register" style={{ color: '#0078d4' }}>Create account</Link>
        </p>
      </div>
    </div>
  );
};

export default Login;
