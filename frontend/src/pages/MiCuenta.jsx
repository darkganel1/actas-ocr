import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, KeyRound, ShieldCheck, CheckCircle2, AlertCircle, LoaderCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import '../styles/MiCuenta.css';

export default function MiCuenta() {
  const navigate = useNavigate();
  const { usuario } = useAuth();
  const [passwordActual, setPasswordActual] = useState('');
  const [passwordNueva, setPasswordNueva] = useState('');
  const [confirmacion, setConfirmacion] = useState('');
  const [cargando, setCargando] = useState(false);
  const [mensaje, setMensaje] = useState(null);

  const enviar = async (e) => {
    e.preventDefault();
    setMensaje(null);

    if (passwordNueva.length < 12) {
      setMensaje({ tipo: 'error', texto: 'La nueva contraseña debe tener al menos 12 caracteres.' });
      return;
    }
    if (passwordNueva !== confirmacion) {
      setMensaje({ tipo: 'error', texto: 'La confirmación no coincide con la nueva contraseña.' });
      return;
    }
    if (passwordActual === passwordNueva) {
      setMensaje({ tipo: 'error', texto: 'La nueva contraseña debe ser diferente de la actual.' });
      return;
    }

    setCargando(true);
    try {
      const respuesta = await api.patch('/auth/cambiar-password', {
        password_actual: passwordActual,
        password_nueva: passwordNueva
      });
      setPasswordActual('');
      setPasswordNueva('');
      setConfirmacion('');
      setMensaje({ tipo: 'exito', texto: respuesta.data?.mensaje || 'Contraseña actualizada correctamente.' });
    } catch (error) {
      setMensaje({
        tipo: 'error',
        texto: error.response?.data?.mensaje || error.response?.data?.message || 'No fue posible actualizar la contraseña.'
      });
    } finally {
      setCargando(false);
    }
  };

  return (
    <div className="mi-cuenta-page">
      <header className="mi-cuenta-topbar">
        <button type="button" className="mi-cuenta-volver" onClick={() => navigate('/inicio')}>
          <ArrowLeft size={17} /> Volver al panel
        </button>
        <div className="mi-cuenta-identidad">
          <span className="mi-cuenta-avatar">{usuario?.nombre_completo?.charAt(0) || 'U'}</span>
          <div><strong>{usuario?.nombre_completo || usuario?.usuario}</strong><small>{usuario?.rol}</small></div>
        </div>
      </header>

      <main className="mi-cuenta-contenido">
        <div className="mi-cuenta-titulo">
          <span>CONFIGURACIÓN DE CUENTA</span>
          <h1>Mi cuenta</h1>
          <p>Actualiza las credenciales de acceso de tu cuenta.</p>
        </div>

        <section className="mi-cuenta-card">
          <div className="mi-cuenta-card-titulo">
            <div className="mi-cuenta-icono"><KeyRound size={22} /></div>
            <div><h2>Cambiar contraseña</h2><p>Confirma tu contraseña actual para establecer una nueva.</p></div>
          </div>

          {mensaje && (
            <div className={`mi-cuenta-mensaje ${mensaje.tipo}`} role="status">
              {mensaje.tipo === 'exito' ? <CheckCircle2 size={18} /> : <AlertCircle size={18} />}
              <span>{mensaje.texto}</span>
            </div>
          )}

          <form onSubmit={enviar} className="mi-cuenta-formulario">
            <label>
              Contraseña actual
              <input type="password" autoComplete="current-password" value={passwordActual} onChange={(e) => setPasswordActual(e.target.value)} required />
            </label>
            <label>
              Nueva contraseña
              <input type="password" autoComplete="new-password" value={passwordNueva} onChange={(e) => setPasswordNueva(e.target.value)} minLength={12} maxLength={128} required />
              <small>Mínimo 12 caracteres.</small>
            </label>
            <label>
              Confirmar nueva contraseña
              <input type="password" autoComplete="new-password" value={confirmacion} onChange={(e) => setConfirmacion(e.target.value)} minLength={12} maxLength={128} required />
            </label>
            <button type="submit" disabled={cargando}>
              {cargando ? <><LoaderCircle className="mi-cuenta-spinner" size={17} /> Actualizando…</> : <><ShieldCheck size={17} /> Actualizar contraseña</>}
            </button>
          </form>
          <div className="mi-cuenta-nota">
            <ShieldCheck size={16} /> La contraseña nunca se muestra ni se almacena en la bitácora de auditoría.
          </div>
        </section>
      </main>
    </div>
  );
}
