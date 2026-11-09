import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState
} from 'react';

import api from '../services/api';

const AuthContext = createContext(null);

const TIEMPO_INACTIVIDAD_MS = 30 * 60 * 1000;
const INTERVALO_HEARTBEAT_MS = 5 * 60 * 1000;
const INTERVALO_REVISION_MS = 1000;
const CLAVE_ULTIMA_ACTIVIDAD = 'actas_ultima_actividad';

export const AuthProvider = ({ children }) => {
  const [usuario, setUsuario] = useState(null);
  const [cargando, setCargando] = useState(true);
  const ultimaActividadRef = useRef(0);
  const ultimoHeartbeatRef = useRef(0);
  const ultimaEscrituraRef = useRef(0);
  const cerrandoSesionRef = useRef(false);

  const limpiarSesionLocal = useCallback(() => {
    localStorage.removeItem('token');
    localStorage.removeItem('usuario');
    localStorage.removeItem(CLAVE_ULTIMA_ACTIVIDAD);
    setUsuario(null);
  }, []);

  const cerrarSesion = useCallback(async ({ notificarServidor = true, motivo = 'MANUAL' } = {}) => {
    if (cerrandoSesionRef.current) return;
    cerrandoSesionRef.current = true;

    const token = localStorage.getItem('token');
    let solicitudCierre = Promise.resolve();
    if (notificarServidor && token) {
      solicitudCierre = api.post(
        '/auth/logout',
        motivo === 'INACTIVIDAD' ? { motivo: 'INACTIVIDAD' } : {},
        { headers: { Authorization: `Bearer ${token}` } }
      ).catch(() => {
        // La sesión puede haber expirado o sido revocada ya en el servidor.
      });
    }

    // Cierra la interfaz inmediatamente; el servidor revoca la sesión en paralelo.
    limpiarSesionLocal();
    await solicitudCierre;
    cerrandoSesionRef.current = false;
  }, [limpiarSesionLocal]);

  // Recuperar sesión. Si el navegador estuvo inactivo 30 minutos, no la reactiva.
  useEffect(() => {
    let activo = true;

    const recuperarSesion = async () => {
      const token = localStorage.getItem('token');
      if (!token) {
        if (activo) setCargando(false);
        return;
      }

      const almacenada = Number(localStorage.getItem(CLAVE_ULTIMA_ACTIVIDAD) || 0);
      if (almacenada && Date.now() - almacenada >= TIEMPO_INACTIVIDAD_MS) {
        cerrarSesion({ motivo: 'INACTIVIDAD' });
        if (activo) setCargando(false);
        return;
      }

      // Compatibilidad en la primera carga tras instalar este control.
      if (!almacenada) {
        const ahora = Date.now();
        localStorage.setItem(CLAVE_ULTIMA_ACTIVIDAD, String(ahora));
        ultimaActividadRef.current = ahora;
      }

      try {
        const respuesta = await api.get('/auth/perfil');
        if (!activo) return;
        const datosUsuario = respuesta.data.usuario;
        setUsuario(datosUsuario);
        localStorage.setItem('usuario', JSON.stringify(datosUsuario));
      } catch (error) {
        limpiarSesionLocal();
      } finally {
        if (activo) setCargando(false);
      }
    };

    recuperarSesion();

    const manejarSesionExpirada = () => limpiarSesionLocal();
    const manejarCambioAlmacenamiento = (event) => {
      if (event.key === 'token' && !event.newValue) {
        limpiarSesionLocal();
      }
      if (event.key === CLAVE_ULTIMA_ACTIVIDAD && event.newValue) {
        const valor = Number(event.newValue);
        if (Number.isFinite(valor)) {
          ultimaActividadRef.current = Math.max(ultimaActividadRef.current, valor);
        }
      }
    };

    window.addEventListener('sesion-expirada', manejarSesionExpirada);
    window.addEventListener('storage', manejarCambioAlmacenamiento);

    return () => {
      activo = false;
      window.removeEventListener('sesion-expirada', manejarSesionExpirada);
      window.removeEventListener('storage', manejarCambioAlmacenamiento);
    };
  }, [limpiarSesionLocal, cerrarSesion]);

  // Actividad real del usuario, latido periódico solo mientras siga activo.
  useEffect(() => {
    if (!usuario?.id_usuario || !localStorage.getItem('token')) return undefined;

    const ahora = Date.now();
    const valorGuardado = Number(localStorage.getItem(CLAVE_ULTIMA_ACTIVIDAD) || ahora);
    ultimaActividadRef.current = valorGuardado || ahora;
    ultimoHeartbeatRef.current = ahora;

    let ultimoMovimiento = 0;

    const registrarActividad = () => {
      const instante = Date.now();
      const guardada = Number(localStorage.getItem(CLAVE_ULTIMA_ACTIVIDAD) || 0);
      const ultima = Math.max(ultimaActividadRef.current, guardada);

      // No permitir que una interacción tardía reactive una sesión ya inactiva.
      if (ultima && instante - ultima >= TIEMPO_INACTIVIDAD_MS) {
        cerrarSesion({ motivo: 'INACTIVIDAD' });
        return;
      }

      ultimaActividadRef.current = instante;
      if (instante - ultimaEscrituraRef.current >= 3000) {
        localStorage.setItem(CLAVE_ULTIMA_ACTIVIDAD, String(instante));
        ultimaEscrituraRef.current = instante;
      }

      // Si la pestaña estuvo abierta mucho tiempo sin peticiones al servidor,
      // comunica la nueva actividad inmediatamente (siempre antes del límite).
      if (
        document.visibilityState === 'visible' &&
        instante - ultimoHeartbeatRef.current >= INTERVALO_HEARTBEAT_MS
      ) {
        ultimoHeartbeatRef.current = instante;
        api.post('/auth/actividad').catch(() => {
          // El interceptor centralizado cerrará la sesión ante un 401.
        });
      }
    };

    const registrarMovimiento = () => {
      const instante = Date.now();
      if (instante - ultimoMovimiento < 5000) return;
      ultimoMovimiento = instante;
      registrarActividad();
    };

    const eventos = ['pointerdown', 'keydown', 'scroll', 'touchstart', 'click'];
    eventos.forEach((nombre) => window.addEventListener(nombre, registrarActividad, { passive: true }));
    window.addEventListener('mousemove', registrarMovimiento, { passive: true });

    const revisarSesion = window.setInterval(() => {
      const instante = Date.now();
      const guardada = Number(localStorage.getItem(CLAVE_ULTIMA_ACTIVIDAD) || 0);
      const ultima = Math.max(ultimaActividadRef.current, guardada);
      ultimaActividadRef.current = ultima;

      if (ultima && instante - ultima >= TIEMPO_INACTIVIDAD_MS) {
        cerrarSesion({ motivo: 'INACTIVIDAD' });
        return;
      }

      const sigueActivo = ultima && instante - ultima < INTERVALO_HEARTBEAT_MS;
      const paginaVisible = document.visibilityState === 'visible';
      if (
        sigueActivo && paginaVisible &&
        instante - ultimoHeartbeatRef.current >= INTERVALO_HEARTBEAT_MS
      ) {
        ultimoHeartbeatRef.current = instante;
        api.post('/auth/actividad').catch(() => {
          // El interceptor centralizado cerrará la sesión ante un 401.
        });
      }
    }, INTERVALO_REVISION_MS);

    const alVolverVisible = () => {
      if (document.visibilityState === 'visible') registrarActividad();
    };
    document.addEventListener('visibilitychange', alVolverVisible);

    return () => {
      window.clearInterval(revisarSesion);
      eventos.forEach((nombre) => window.removeEventListener(nombre, registrarActividad));
      window.removeEventListener('mousemove', registrarMovimiento);
      document.removeEventListener('visibilitychange', alVolverVisible);
    };
  }, [usuario?.id_usuario, cerrarSesion]);

  const iniciarSesion = async (credenciales) => {
    setCargando(true);
    try {
      const respuesta = await api.post('/auth/login', credenciales);
      const { token, usuario: datosUsuario } = respuesta.data;
      const ahora = Date.now();

      localStorage.setItem('token', token);
      localStorage.setItem('usuario', JSON.stringify(datosUsuario));
      localStorage.setItem(CLAVE_ULTIMA_ACTIVIDAD, String(ahora));
      ultimaActividadRef.current = ahora;
      ultimoHeartbeatRef.current = ahora;
      setUsuario(datosUsuario);
      return datosUsuario;
    } finally {
      setCargando(false);
    }
  };

  const tienePermiso = (permiso) => usuario?.permisos?.includes(permiso) ?? false;

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
    throw new Error('useAuth debe utilizarse dentro de AuthProvider.');
  }
  return contexto;
};
