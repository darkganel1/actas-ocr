import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:3000/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Agrega automáticamente el token a las peticiones protegidas.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Centraliza la expiración, inactividad y revocación de sesiones.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = error.config?.url || '';
    const esLogin = url.includes('/auth/login');
    const esLogout = url.includes('/auth/logout');

    if (error.response?.status === 401 && !esLogin && !esLogout) {
      window.dispatchEvent(new Event('sesion-expirada'));
    }
    return Promise.reject(error);
  }
);

export default api;
