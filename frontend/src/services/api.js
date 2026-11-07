
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:3000/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Agregar token automáticamente a las peticiones.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  return config;
});

// Manejo centralizado de sesiones inválidas.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const esLogin = error.config?.url?.includes('/auth/login');

    if (error.response?.status === 401 && !esLogin) {
      localStorage.removeItem('token');
      localStorage.removeItem('usuario');

      window.dispatchEvent(
        new Event('sesion-expirada')
      );
    }

    return Promise.reject(error);
  }
);

export default api;
