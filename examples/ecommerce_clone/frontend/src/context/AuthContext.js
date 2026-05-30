import React, { createContext, useContext, useState, useEffect } from 'react';
import { login as apiLogin, register as apiRegister, getProfile } from '../api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem('token'));

  useEffect(() => {
    if (token) {
      getProfile().then((data) => {
        if (data && !data.error) setUser(data);
      });
    }
  }, [token]);

  const login = async (username, password) => {
    const data = await apiLogin({ username, password });
    if (data.access_token) {
      localStorage.setItem('token', data.access_token);
      setToken(data.access_token);
      setUser(data.user);
    }
    return data;
  };

  const register = async (userData) => {
    const data = await apiRegister(userData);
    if (data.access_token) {
      localStorage.setItem('token', data.access_token);
      setToken(data.access_token);
      setUser(data.user);
    }
    return data;
  };

  const logout = () => {
    localStorage.removeItem('token');
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
