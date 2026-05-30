const API_BASE = '/api';

const getHeaders = () => {
  const token = localStorage.getItem('token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

// Auth
export const register = (data) =>
  fetch(`${API_BASE}/auth/register`, { method: 'POST', headers: getHeaders(), body: JSON.stringify(data) }).then((r) => r.json());

export const login = (data) =>
  fetch(`${API_BASE}/auth/login`, { method: 'POST', headers: getHeaders(), body: JSON.stringify(data) }).then((r) => r.json());

export const getProfile = () =>
  fetch(`${API_BASE}/auth/profile`, { headers: getHeaders() }).then((r) => r.json());

// Products
export const getProducts = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return fetch(`${API_BASE}/products${qs ? `?${qs}` : ''}`, { headers: getHeaders() }).then((r) => r.json());
};
export const getProduct = (id) =>
  fetch(`${API_BASE}/products/${id}`, { headers: getHeaders() }).then((r) => r.json());

export const getCategories = () =>
  fetch(`${API_BASE}/products/categories`, { headers: getHeaders() }).then((r) => r.json());

// Cart
export const getCart = () =>
  fetch(`${API_BASE}/cart`, { headers: getHeaders() }).then((r) => r.json());

export const addToCart = (data) =>
  fetch(`${API_BASE}/cart/add`, { method: 'POST', headers: getHeaders(), body: JSON.stringify(data) }).then((r) => r.json());

export const updateCartItem = (data) =>
  fetch(`${API_BASE}/cart/update`, { method: 'POST', headers: getHeaders(), body: JSON.stringify(data) }).then((r) => r.json());

export const removeFromCart = (data) =>
  fetch(`${API_BASE}/cart/remove`, { method: 'POST', headers: getHeaders(), body: JSON.stringify(data) }).then((r) => r.json());

// Orders
export const checkout = (data) =>
  fetch(`${API_BASE}/orders/checkout`, { method: 'POST', headers: getHeaders(), body: JSON.stringify(data) }).then((r) => r.json());

export const getOrders = () =>
  fetch(`${API_BASE}/orders`, { headers: getHeaders() }).then((r) => r.json());

export const getOrder = (id) =>
  fetch(`${API_BASE}/orders/${id}`, { headers: getHeaders() }).then((r) => r.json());

// Reviews
export const submitReview = (data) =>
  fetch(`${API_BASE}/reviews`, { method: 'POST', headers: getHeaders(), body: JSON.stringify(data) }).then((r) => r.json());

export const getProductReviews = (productId) =>
  fetch(`${API_BASE}/reviews/product/${productId}`, { headers: getHeaders() }).then((r) => r.json());


// Chat
export const sendChatMessage = (message) =>
  fetch(`${API_BASE}/chat`, { method: 'POST', headers: getHeaders(), body: JSON.stringify({ message }) }).then((r) => r.json());
