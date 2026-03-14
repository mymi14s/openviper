import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const Register = () => {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: '', email: '', password: '', name: '', address: '' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    const result = await register(form);
    setLoading(false);
    if (result.access_token) navigate('/');
    else setError(result.error || 'Registration failed. Please try again.');
  };

  const field = (name, label, type = 'text', required = false) => (
    <div className="form-group">
      <label>{label}{required && ' *'}</label>
      <input type={type} value={form[name]} onChange={(e) => setForm({ ...form, [name]: e.target.value })} required={required} />
    </div>
  );

  return (
    <div className="page">
      <div className="form-card" style={{ maxWidth: 460 }}>
        <h1 style={{ textAlign: 'center', marginTop: 0 }}>Create Account</h1>
        {error && <div className="alert alert--error">{error}</div>}
        <form onSubmit={handleSubmit}>
          {field('username', 'Username', 'text', true)}
          {field('email', 'Email', 'email', true)}
          {field('password', 'Password', 'password', true)}
          {field('name', 'Full Name')}
          {field('address', 'Address')}
          <button type="submit" disabled={loading} className="btn btn--primary btn--full">
            {loading ? 'Creating account...' : 'Create Account'}
          </button>
        </form>
        <p style={{ textAlign: 'center', marginTop: '1.25rem' }}>
          Already have an account? <Link to="/login" style={{ color: '#0078d4' }}>Sign in</Link>
        </p>
      </div>
    </div>
  );
};

export default Register;
