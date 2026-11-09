import { useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  Landmark,
  Users as UsersIcon,
  Plus,
  Search,
  RefreshCw,
  Power,
  X,
  ShieldCheck,
  Pencil,
  KeyRound,
  AlertTriangle,
  CheckCircle2
} from 'lucide-react';

import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import './UsuariosAdmin.css';

const Usuarios = () => {
  const { usuario, cerrarSesion } = useAuth();
  const navigate = useNavigate();

  const [usuarios, setUsuarios] = useState([]);
  const [busqueda, setBusqueda] = useState('');
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [modalAbierto, setModalAbierto] = useState(false);
  const [modalEditarAbierto, setModalEditarAbierto] = useState(false);
  const [modalPasswordAbierto, setModalPasswordAbierto] = useState(false);
  const [confirmacionEstado, setConfirmacionEstado] = useState(null);
  const [usuarioSeleccionado, setUsuarioSeleccionado] = useState(null);
  const [procesandoAccion, setProcesandoAccion] = useState(false);
  const [errorModal, setErrorModal] = useState('');
  const [formularioEdicion, setFormularioEdicion] = useState({
    nombre_completo: '',
    usuario: '',
    correo: ''
  });
  const [passwordNueva, setPasswordNueva] = useState('');
  const [passwordConfirmacion, setPasswordConfirmacion] = useState('');
  const [mensaje, setMensaje] = useState('');
  const [error, setError] = useState('');

  const [formulario, setFormulario] = useState({
    nombre_completo: '',
    usuario: '',
    correo: '',
    password: ''
  });

  const cargarUsuarios = async () => {
    try {
      setCargando(true);
      setError('');

      const respuesta = await api.get('/usuarios');
      setUsuarios(respuesta.data.usuarios || []);

    } catch (err) {
      setError(
        err.response?.data?.mensaje ||
        'No fue posible consultar los usuarios.'
      );
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => {
    if (usuario?.rol === 'Administrador') {
      cargarUsuarios();
    }
  }, [usuario?.rol]);

  const usuariosFiltrados = useMemo(() => {
    const termino = busqueda.toLowerCase().trim();

    if (!termino) return usuarios;

    return usuarios.filter((u) =>
      [
        u.nombre_completo,
        u.usuario,
        u.correo,
        u.rol
      ].some(valor =>
        String(valor || '').toLowerCase().includes(termino)
      )
    );
  }, [usuarios, busqueda]);

  const activos = usuarios.filter(u => Number(u.activo) === 1).length;
  const inactivos = usuarios.length - activos;

  const cambiarCampo = (e) => {
    setFormulario({
      ...formulario,
      [e.target.name]: e.target.value
    });
  };

  const limpiarFormulario = () => {
    setFormulario({
      nombre_completo: '',
      usuario: '',
      correo: '',
      password: ''
    });
  };

  const crearUsuario = async (e) => {
    e.preventDefault();

    try {
      setGuardando(true);
      setError('');
      setMensaje('');

      const respuesta = await api.post('/usuarios', formulario);

      setMensaje(
        respuesta.data.mensaje || 'Usuario creado correctamente.'
      );

      setModalAbierto(false);
      limpiarFormulario();
      await cargarUsuarios();

    } catch (err) {
      setError(
        err.response?.data?.mensaje ||
        'No fue posible crear el usuario.'
      );
    } finally {
      setGuardando(false);
    }
  };

  const abrirEdicion = (u) => {
    setUsuarioSeleccionado(u);
    setFormularioEdicion({
      nombre_completo: u.nombre_completo || '',
      usuario: u.usuario || '',
      correo: u.correo || ''
    });
    setError('');
    setErrorModal('');
    setMensaje('');
    setModalEditarAbierto(true);
  };

  const cambiarCampoEdicion = (e) => {
    setFormularioEdicion((actual) => ({
      ...actual,
      [e.target.name]: e.target.value
    }));
  };

  const guardarEdicion = async (e) => {
    e.preventDefault();
    if (!usuarioSeleccionado) return;

    try {
      setProcesandoAccion(true);
      setError('');
      setMensaje('');

      const respuesta = await api.patch(
        `/usuarios/${usuarioSeleccionado.id_usuario}`,
        formularioEdicion
      );

      setMensaje(respuesta.data.mensaje || 'Datos del usuario actualizados correctamente.');
      setModalEditarAbierto(false);
      setUsuarioSeleccionado(null);
      await cargarUsuarios();
    } catch (err) {
      setErrorModal(
        err.response?.data?.mensaje ||
        'No fue posible actualizar los datos del usuario.'
      );
    } finally {
      setProcesandoAccion(false);
    }
  };

  const abrirRestablecerPassword = (u) => {
    setUsuarioSeleccionado(u);
    setPasswordNueva('');
    setPasswordConfirmacion('');
    setError('');
    setErrorModal('');
    setMensaje('');
    setModalPasswordAbierto(true);
  };

  const restablecerPassword = async (e) => {
    e.preventDefault();
    if (!usuarioSeleccionado) return;

    if (passwordNueva.length < 12) {
      setErrorModal('La contraseña debe tener al menos 12 caracteres.');
      return;
    }

    if (passwordNueva !== passwordConfirmacion) {
      setErrorModal('La confirmación no coincide con la nueva contraseña.');
      return;
    }

    try {
      setProcesandoAccion(true);
      setError('');
      setMensaje('');

      const respuesta = await api.patch(
        `/usuarios/${usuarioSeleccionado.id_usuario}/password`,
        { password_nueva: passwordNueva }
      );

      setMensaje(respuesta.data.mensaje || 'Contraseña restablecida correctamente.');
      setModalPasswordAbierto(false);
      setUsuarioSeleccionado(null);
      setPasswordNueva('');
      setPasswordConfirmacion('');
    } catch (err) {
      setErrorModal(
        err.response?.data?.mensaje ||
        'No fue posible restablecer la contraseña.'
      );
    } finally {
      setProcesandoAccion(false);
    }
  };

  const abrirConfirmacionEstado = (u) => {
    const nuevoEstado = Number(u.activo) !== 1;
    setError('');
    setErrorModal('');
    setMensaje('');
    setConfirmacionEstado({ usuario: u, activo: nuevoEstado });
  };

  const cambiarEstado = async () => {
    if (!confirmacionEstado) return;

    const { usuario: usuarioObjetivo, activo: nuevoEstado } = confirmacionEstado;

    try {
      setProcesandoAccion(true);
      setError('');
      setMensaje('');

      const respuesta = await api.patch(
        `/usuarios/${usuarioObjetivo.id_usuario}/estado`,
        { activo: nuevoEstado }
      );

      setMensaje(respuesta.data.mensaje || 'Estado del usuario actualizado.');
      setConfirmacionEstado(null);
      await cargarUsuarios();
    } catch (err) {
      setErrorModal(
        err.response?.data?.mensaje ||
        'No fue posible cambiar el estado del usuario.'
      );
    } finally {
      setProcesandoAccion(false);
    }
  };

  const fecha = (valor) => {
    if (!valor) return 'Sin registro';

    const fecha = new Date(valor);

    if (Number.isNaN(fecha.getTime())) return 'Sin registro';

    return fecha.toLocaleString('es-MX', {
      dateStyle: 'short',
      timeStyle: 'short'
    });
  };

  if (usuario?.rol !== 'Administrador') {
    return (
      <div className="usuarios-error-page">
        <ShieldCheck size={40} />
        <h2>Acceso restringido</h2>
        <p>Esta sección es exclusiva para administradores.</p>
        <button onClick={() => navigate('/inicio')}>
          Regresar al inicio
        </button>
      </div>
    );
  }

  return (
    <div className="dashboard">

      <aside className="sidebar">

        <div className="sidebar-brand">
          <Landmark size={29} />
          <div>
            <strong>REGISTRO</strong>
            <span>DE ACTAS</span>
          </div>
        </div>

        <div className="sidebar-section">
          MENÃš PRINCIPAL
        </div>

        <nav className="sidebar-nav">

          <button
            className="sidebar-item"
            onClick={() => navigate('/inicio')}
          >
            <ArrowLeft size={19} />
            <span>Panel principal</span>
          </button>

          <button
            className="sidebar-item"
            onClick={() => navigate('/actas')}
          >
            <UsersIcon size={19} />
            <span>Consultar actas</span>
          </button>

          <button
            className="sidebar-item sidebar-item-active"
          >
            <UsersIcon size={19} />
            <span>Usuarios</span>
          </button>

        </nav>

        <button
          className="logout-button"
          onClick={cerrarSesion}
        >
          <Power size={19} />
          Cerrar sesión
        </button>

      </aside>

      <main className="dashboard-main">

        <header className="topbar">
          <span>Sistema de Gestión Documental</span>

          <div className="user-info">
            <div className="user-avatar">
              {usuario?.nombre_completo?.charAt(0) || 'U'}
            </div>

            <div>
              <strong>{usuario?.nombre_completo}</strong>
              <small>{usuario?.rol}</small>
            </div>
          </div>
        </header>

        <section className="usuarios-content">

          <div className="usuarios-heading">
            <div>
              <span className="section-eyebrow">
                ADMINISTRACIÓN / USUARIOS
              </span>

              <h1>Gestión de usuarios</h1>

              <p>
                Administra las cuentas y los accesos al sistema.
              </p>
            </div>

            <button
              className="usuarios-primary-button"
              onClick={() => {
                setError('');
                setMensaje('');
                setModalAbierto(true);
              }}
            >
              <Plus size={18} />
              Nuevo usuario
            </button>
          </div>

          {mensaje && (
            <div className="usuarios-alerta usuarios-alerta-ok">
              {mensaje}
            </div>
          )}

          {error && (
            <div className="usuarios-alerta usuarios-alerta-error">
              {error}
            </div>
          )}

          <div className="usuarios-resumen">

            <article className="usuarios-stat">
              <UsersIcon size={23} />
              <div>
                <strong>{usuarios.length}</strong>
                <span>Total de usuarios</span>
              </div>
            </article>

            <article className="usuarios-stat">
              <ShieldCheck size={23} />
              <div>
                <strong>{activos}</strong>
                <span>Cuentas activas</span>
              </div>
            </article>

            <article className="usuarios-stat">
              <Power size={23} />
              <div>
                <strong>{inactivos}</strong>
                <span>Cuentas inactivas</span>
              </div>
            </article>

          </div>

          <div className="usuarios-panel">

            <div className="usuarios-panel-heading">
              <div>
                <h2>Directorio de usuarios</h2>
                <span>
                  {usuariosFiltrados.length} registros encontrados
                </span>
              </div>

              <button
                className="usuarios-refresh"
                onClick={cargarUsuarios}
                disabled={cargando}
                title="Actualizar listado"
              >
                <RefreshCw size={17} />
              </button>
            </div>

            <div className="usuarios-search">
              <Search size={19} />
              <input
                type="text"
                placeholder="Buscar por nombre, usuario o correo..."
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
              />
            </div>

            {cargando ? (
              <div className="usuarios-loading">
                <RefreshCw size={23} />
                <span>Cargando usuarios...</span>
              </div>
            ) : usuariosFiltrados.length === 0 ? (
              <div className="usuarios-empty">
                <UsersIcon size={35} />
                <h3>No se encontraron usuarios</h3>
                <p>Prueba con otro término de bÃºsqueda.</p>
              </div>
            ) : (

              <div className="usuarios-table-container">
                <table className="usuarios-table">

                  <thead>
                    <tr>
                      <th>Usuario</th>
                      <th>Correo electrónico</th>
                      <th>Rol</th>
                      <th>Estado</th>
                      <th>Último acceso</th>
                      <th>Acciones</th>
                    </tr>
                  </thead>

                  <tbody>
                    {usuariosFiltrados.map((u) => {
                      const activo = Number(u.activo) === 1;
                      const esActual =
                        Number(u.id_usuario) === Number(usuario.id_usuario);

                      return (
                        <tr key={u.id_usuario}>

                          <td>
                            <div className="usuario-identidad">
                              <div className="usuario-avatar">
                                {u.nombre_completo?.charAt(0) || 'U'}
                              </div>

                              <div>
                                <strong>{u.nombre_completo}</strong>
                                <span>@{u.usuario}</span>
                              </div>
                            </div>
                          </td>

                          <td>{u.correo}</td>

                          <td>
                            <span className="usuario-rol">
                              {u.rol}
                            </span>
                          </td>

                          <td>
                            <span className={
                              activo
                                ? 'usuario-estado activo'
                                : 'usuario-estado inactivo'
                            }>
                              {activo ? 'Activo' : 'Inactivo'}
                            </span>
                          </td>

                          <td>{fecha(u.ultimo_acceso)}</td>

                          <td>
                            <div className="usuarios-admin-acciones">
                              <button
                                type="button"
                                className="usuarios-admin-icono editar"
                                onClick={() => abrirEdicion(u)}
                                title={`Editar datos de ${u.nombre_completo}`}
                                aria-label={`Editar datos de ${u.nombre_completo}`}
                              >
                                <Pencil size={16} />
                              </button>

                              <button
                                type="button"
                                className="usuarios-admin-icono password"
                                onClick={() => abrirRestablecerPassword(u)}
                                title={`Restablecer contraseña de ${u.nombre_completo}`}
                                aria-label={`Restablecer contraseña de ${u.nombre_completo}`}
                              >
                                <KeyRound size={16} />
                              </button>

                              <button
                                type="button"
                                className={
                                  activo
                                    ? 'usuario-action desactivar'
                                    : 'usuario-action activar'
                                }
                                disabled={esActual && activo}
                                onClick={() => abrirConfirmacionEstado(u)}
                                title={
                                  esActual
                                    ? 'No puedes desactivar tu propia cuenta'
                                    : activo
                                      ? 'Desactivar usuario'
                                      : 'Activar usuario'
                                }
                                aria-label={activo ? `Desactivar ${u.nombre_completo}` : `Activar ${u.nombre_completo}`}
                              >
                                <Power size={17} />
                              </button>
                            </div>
                          </td>

                        </tr>
                      );
                    })}
                  </tbody>

                </table>
              </div>

            )}

          </div>

        </section>

      </main>

      {modalAbierto && (
        <div
          className="usuarios-modal-overlay"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !guardando) {
              setModalAbierto(false);
            }
          }}
        >
          <div className="usuarios-modal">

            <div className="usuarios-modal-heading">
              <div>
                <span className="section-eyebrow">
                  NUEVA CUENTA
                </span>
                <h2>Registrar usuario</h2>
              </div>

              <button
                type="button"
                onClick={() => setModalAbierto(false)}
                disabled={guardando}
                className="usuarios-modal-close"
                aria-label="Cerrar"
              >
                <X size={21} />
              </button>
            </div>

            <p className="usuarios-modal-description">
              La cuenta se creará con el rol Capturista.
            </p>

            <form onSubmit={crearUsuario}>

              <div className="usuarios-form-group">
                <label>Nombre completo</label>
                <input
                  name="nombre_completo"
                  value={formulario.nombre_completo}
                  onChange={cambiarCampo}
                  placeholder="Nombre y apellidos"
                  required
                  maxLength={150}
                />
              </div>

              <div className="usuarios-form-group">
                <label>Nombre de usuario</label>
                <input
                  name="usuario"
                  value={formulario.usuario}
                  onChange={cambiarCampo}
                  placeholder="usuario01"
                  required
                  maxLength={50}
                />
              </div>

              <div className="usuarios-form-group">
                <label>Correo electrónico</label>
                <input
                  type="email"
                  name="correo"
                  value={formulario.correo}
                  onChange={cambiarCampo}
                  placeholder="correo@ejemplo.com"
                  required
                  maxLength={150}
                />
              </div>

              <div className="usuarios-form-group">
                <label>Contraseña temporal</label>
                <input
                  type="password"
                  name="password"
                  value={formulario.password}
                  onChange={cambiarCampo}
                  placeholder="Mínimo 12 caracteres"
                  minLength={12}
                  required
                  autoComplete="new-password"
                />
                <small>
                  Debe contener al menos 12 caracteres.
                </small>
              </div>

              <div className="usuarios-modal-actions">

                <button
                  type="button"
                  className="usuarios-cancel-button"
                  onClick={() => setModalAbierto(false)}
                  disabled={guardando}
                >
                  Cancelar
                </button>

                <button
                  type="submit"
                  className="usuarios-primary-button"
                  disabled={guardando}
                >
                  {guardando ? 'Guardando...' : 'Crear usuario'}
                </button>

              </div>

            </form>

          </div>
        </div>
      )}

      {modalEditarAbierto && usuarioSeleccionado && (
        <div
          className="usuarios-modal-overlay usuarios-admin-overlay"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !procesandoAccion) {
              setModalEditarAbierto(false);
              setUsuarioSeleccionado(null);
            }
          }}
        >
          <section className="usuarios-modal usuarios-admin-modal" role="dialog" aria-modal="true" aria-labelledby="editar-usuario-titulo">
            <div className="usuarios-modal-heading">
              <div>
                <span className="section-eyebrow">ADMINISTRACIÓN DE CUENTAS</span>
                <h2 id="editar-usuario-titulo">Editar usuario</h2>
              </div>
              <button
                type="button"
                onClick={() => {
                  setModalEditarAbierto(false);
                  setUsuarioSeleccionado(null);
                }}
                disabled={procesandoAccion}
                className="usuarios-modal-close"
                aria-label="Cerrar"
              >
                <X size={21} />
              </button>
            </div>

            <p className="usuarios-modal-description">
              Actualiza los datos de acceso y contacto de {usuarioSeleccionado.nombre_completo}.
            </p>

            {errorModal && <div className="usuarios-alerta usuarios-alerta-error usuarios-admin-error-modal" role="alert">{errorModal}</div>}

            <form onSubmit={guardarEdicion}>
              <div className="usuarios-form-group">
                <label htmlFor="editar-nombre-completo">Nombre completo</label>
                <input
                  id="editar-nombre-completo"
                  name="nombre_completo"
                  value={formularioEdicion.nombre_completo}
                  onChange={cambiarCampoEdicion}
                  required
                  maxLength={150}
                  autoComplete="name"
                />
              </div>

              <div className="usuarios-form-group">
                <label htmlFor="editar-usuario">Nombre de usuario</label>
                <input
                  id="editar-usuario"
                  name="usuario"
                  value={formularioEdicion.usuario}
                  onChange={cambiarCampoEdicion}
                  required
                  maxLength={50}
                  autoComplete="username"
                />
              </div>

              <div className="usuarios-form-group">
                <label htmlFor="editar-correo">Correo electrónico</label>
                <input
                  id="editar-correo"
                  type="email"
                  name="correo"
                  value={formularioEdicion.correo}
                  onChange={cambiarCampoEdicion}
                  required
                  maxLength={150}
                  autoComplete="email"
                />
              </div>

              <div className="usuarios-admin-modal-pie">
                <button
                  type="button"
                  className="usuarios-cancel-button"
                  onClick={() => {
                    setModalEditarAbierto(false);
                    setUsuarioSeleccionado(null);
                  }}
                  disabled={procesandoAccion}
                >Cancelar</button>
                <button type="submit" className="usuarios-primary-button" disabled={procesandoAccion}>
                  {procesandoAccion ? 'Guardando...' : 'Guardar cambios'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {modalPasswordAbierto && usuarioSeleccionado && (
        <div
          className="usuarios-modal-overlay usuarios-admin-overlay"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !procesandoAccion) {
              setModalPasswordAbierto(false);
              setUsuarioSeleccionado(null);
            }
          }}
        >
          <section className="usuarios-modal usuarios-admin-modal" role="dialog" aria-modal="true" aria-labelledby="restablecer-password-titulo">
            <div className="usuarios-modal-heading">
              <div>
                <span className="section-eyebrow">SEGURIDAD DE LA CUENTA</span>
                <h2 id="restablecer-password-titulo">Restablecer contraseña</h2>
              </div>
              <button
                type="button"
                onClick={() => {
                  setModalPasswordAbierto(false);
                  setUsuarioSeleccionado(null);
                }}
                disabled={procesandoAccion}
                className="usuarios-modal-close"
                aria-label="Cerrar"
              ><X size={21} /></button>
            </div>

            <p className="usuarios-modal-description">
              Se asignará una nueva contraseña a <strong>{usuarioSeleccionado.nombre_completo}</strong> (@{usuarioSeleccionado.usuario}).
            </p>

            {errorModal && <div className="usuarios-alerta usuarios-alerta-error usuarios-admin-error-modal" role="alert">{errorModal}</div>}

            <form onSubmit={restablecerPassword}>
              <div className="usuarios-form-group">
                <label htmlFor="password-nueva-usuario">Nueva contraseña temporal</label>
                <input
                  id="password-nueva-usuario"
                  type="password"
                  value={passwordNueva}
                  onChange={(e) => setPasswordNueva(e.target.value)}
                  minLength={12}
                  maxLength={128}
                  required
                  autoComplete="new-password"
                  placeholder="Mínimo 12 caracteres"
                />
              </div>
              <div className="usuarios-form-group">
                <label htmlFor="password-confirmacion-usuario">Confirmar contraseña</label>
                <input
                  id="password-confirmacion-usuario"
                  type="password"
                  value={passwordConfirmacion}
                  onChange={(e) => setPasswordConfirmacion(e.target.value)}
                  minLength={12}
                  maxLength={128}
                  required
                  autoComplete="new-password"
                  placeholder="Repite la nueva contraseña"
                />
              </div>
              <p className="usuarios-admin-ayuda-password">
                Por seguridad, la contraseña no se mostrará nuevamente ni se guardará en la bitácora.
              </p>
              <div className="usuarios-admin-modal-pie">
                <button
                  type="button"
                  className="usuarios-cancel-button"
                  onClick={() => {
                    setModalPasswordAbierto(false);
                    setUsuarioSeleccionado(null);
                  }}
                  disabled={procesandoAccion}
                >Cancelar</button>
                <button type="submit" className="usuarios-primary-button" disabled={procesandoAccion}>
                  {procesandoAccion ? 'Restableciendo...' : 'Restablecer contraseña'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {confirmacionEstado && (
        <div
          className="usuarios-admin-confirm-overlay"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !procesandoAccion) {
              setConfirmacionEstado(null);
            }
          }}
        >
          <section className="usuarios-admin-confirmacion" role="alertdialog" aria-modal="true" aria-labelledby="confirmar-estado-titulo">
            <div className={`usuarios-admin-confirm-icono ${confirmacionEstado.activo ? 'activar' : 'desactivar'}`}>
              {confirmacionEstado.activo ? <CheckCircle2 size={25} /> : <AlertTriangle size={25} />}
            </div>
            <span className="usuarios-admin-confirm-eyebrow">CONFIRMACIÓN DE SEGURIDAD</span>
            <h2 id="confirmar-estado-titulo">
              {confirmacionEstado.activo ? 'Activar cuenta' : 'Desactivar cuenta'}
            </h2>
            <p>
              {confirmacionEstado.activo
                ? <>¿Deseas activar la cuenta de <strong>{confirmacionEstado.usuario.nombre_completo}</strong>?</>
                : <>¿Deseas desactivar la cuenta de <strong>{confirmacionEstado.usuario.nombre_completo}</strong>?</>}
            </p>
            {errorModal && <div className="usuarios-alerta usuarios-alerta-error usuarios-admin-error-modal" role="alert">{errorModal}</div>}
            <div className="usuarios-admin-confirm-nota">
              {confirmacionEstado.activo
                ? 'El usuario podrá volver a iniciar sesión y utilizar los permisos asignados a su cuenta.'
                : 'El usuario ya no podrá iniciar sesión. Su historial y registros de actividad se conservarán.'}
            </div>
            <div className="usuarios-admin-modal-pie">
              <button
                type="button"
                className="usuarios-cancel-button"
                onClick={() => setConfirmacionEstado(null)}
                disabled={procesandoAccion}
              >Cancelar</button>
              <button
                type="button"
                className={confirmacionEstado.activo ? 'usuarios-admin-boton-activar' : 'usuarios-admin-boton-desactivar'}
                onClick={cambiarEstado}
                disabled={procesandoAccion}
              >
                {procesandoAccion
                  ? 'Procesando...'
                  : confirmacionEstado.activo ? 'Activar usuario' : 'Desactivar usuario'}
              </button>
            </div>
          </section>
        </div>
      )}

    </div>
  );
};

export default Usuarios;
