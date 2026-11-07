
import {
  createContext,
  useContext,
  useEffect,
  useState
} from 'react';

import api from '../services/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {

  const [usuario, setUsuario] = useState(null);

  // La aplicación inicia comprobando si existe una sesión válida.
  const [cargando, setCargando] = useState(true);

  // Eliminar sesión y actualizar React.
  const cerrarSesion = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('usuario');

    setUsuario(null);
  };

  // Recuperar y validar sesión al cargar la aplicación.
  useEffect(() => {
    let activo = true;

    const recuperarSesion = async () => {
      const token = localStorage.getItem('token');

      if (!token) {
        if (activo) {
          setCargando(false);
        }
        return;
      }

      try {
        const respuesta = await api.get('/auth/perfil');

        const datosUsuario = respuesta.data.usuario;

        if (activo) {
          setUsuario(datosUsuario);

          localStorage.setItem(
            'usuario',
            JSON.stringify(datosUsuario)
          );
        }

      } catch (error) {
        cerrarSesion();

      } finally {
        if (activo) {
          setCargando(false);
        }
      }
    };

    recuperarSesion();

    // Escuchar sesiones vencidas o invalidadas.
    const manejarSesionExpirada = () => {
      if (activo) {
        cerrarSesion();
      }
    };

    window.addEventListener(
      'sesion-expirada',
      manejarSesionExpirada
    );

    return () => {
      activo = false;

      window.removeEventListener(
        'sesion-expirada',
        manejarSesionExpirada
      );
    };

  }, []);

  // Inicio de sesión.
  const iniciarSesion = async (credenciales) => {
    setCargando(true);

    try {
      const respuesta = await api.post(
        '/auth/login',
        credenciales
      );

      const {
        token,
        usuario: datosUsuario
      } = respuesta.data;

      localStorage.setItem('token', token);

      localStorage.setItem(
        'usuario',
        JSON.stringify(datosUsuario)
      );

      setUsuario(datosUsuario);

      return datosUsuario;

    } finally {
      setCargando(false);
    }
  };

  // Comprobar permisos.
  const tienePermiso = (permiso) => {
    return usuario?.permisos?.includes(permiso) ?? false;
  };

  const valor = {
    usuario,
    cargando,
    iniciarSesion,
    cerrarSesion,
    tienePermiso,
    autenticado: Boolean(usuario)
  };

  return (
    <AuthContext.Provider value={valor}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const contexto = useContext(AuthContext);

  if (!contexto) {
    throw new Error(
      'useAuth debe utilizarse dentro de AuthProvider.'
    );
  }

  return contexto;
};
