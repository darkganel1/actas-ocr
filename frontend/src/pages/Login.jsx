import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Landmark, LockKeyhole, UserRound, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const Login = () => {
  const navigate = useNavigate();
  const { iniciarSesion, cargando } = useAuth();

  const [usuario, setUsuario] = useState('');
  const [password, setPassword] = useState('');
  const [mostrarPassword, setMostrarPassword] = useState(false);
  const [error, setError] = useState('');

  const manejarLogin = async (e) => {
    e.preventDefault();
    setError('');

    try {
      await iniciarSesion({ usuario, password });
      navigate('/inicio', { replace: true });
    } catch (err) {
      setError(
        err.response?.data?.message ||
        'No fue posible iniciar sesión. Verifica tus credenciales.'
      );
    }
  };

  return (
    <main className="login-page">
      <section className="login-brand">
        <div className="brand-content">
          <div className="brand-emblem">
            <Landmark size={42} strokeWidth={1.5} />
          </div>

          <div className="brand-divider" />

          <p className="brand-overline">SISTEMA INSTITUCIONAL</p>

          <h1>Registro de Actas</h1>

          <p className="brand-description">
            Sistema de gestión, consulta y administración
            de documentos registrales.
          </p>
        </div>

        <span className="brand-footer">
          SISTEMA DE GESTIÓN DOCUMENTAL
        </span>
      </section>

      <section className="login-content">
        <form className="login-card" onSubmit={manejarLogin}>
          <div className="login-heading">
            <span className="login-label">BIENVENIDO</span>
            <h2>Iniciar sesión</h2>
            <p>Ingresa tus credenciales para continuar.</p>
          </div>

          {error && (
            <div className="login-error" role="alert">
              {error}
            </div>
          )}

          <div className="form-group">
            <label htmlFor="usuario">Usuario o correo electrónico</label>

            <div className="input-wrapper">
              <UserRound size={19} />
              <input
                id="usuario"
                type="text"
                value={usuario}
                onChange={(e) => setUsuario(e.target.value)}
                placeholder="Ingresa tu usuario"
                autoComplete="username"
                required
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="password">Contraseña</label>

            <div className="input-wrapper">
              <LockKeyhole size={19} />

              <input
                id="password"
                type={mostrarPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Ingresa tu contraseña"
                autoComplete="current-password"
                required
              />

              <button
                type="button"
                className="password-toggle"
                onClick={() => setMostrarPassword(!mostrarPassword)}
                aria-label={mostrarPassword ? 'Ocultar contraseña' : 'Mostrar contraseña'}
              >
                {mostrarPassword
                  ? <EyeOff size={19} />
                  : <Eye size={19} />}
              </button>
            </div>
          </div>

          <button
            className="login-button"
            type="submit"
            disabled={cargando}
          >
            {cargando ? 'Verificando...' : 'Ingresar al sistema'}
          </button>

          <p className="login-security">
            <LockKeyhole size={14} />
            Acceso exclusivo para personal autorizado.
          </p>
        </form>

        <footer className="login-copyright">
          Registro de Actas · Sistema de Gestión Documental
        </footer>
      </section>
    </main>
  );
};

export default Login;