
const {
  guardarActa,
  listarActas,
  obtenerActaPorId,
  obtenerDocumentoActa,
  actualizarActaPorAdministrador,
  eliminarActaPermanentemente
} = require('../services/actas.service');
const { registrarEventoAuditoria } = require('../services/auditoria-registro.service');
const { validarPDF } = require('../services/pdf.validation.service');

const crearActa = async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({
        success: false,
        mensaje: 'Debes adjuntar el PDF del acta.'
      });
    }

    // Valida extensión, encabezado, EOF y estructura real con Poppler/pdfinfo.
    await validarPDF(req.file);

    let datos;

    try {
      datos = JSON.parse(req.body.datos);
    } catch {
      return res.status(400).json({
        success: false,
        mensaje: 'Los datos del acta no contienen un JSON válido.'
      });
    }

    const resultado = await guardarActa({
      archivo: req.file,
      datos,
      idUsuario: req.usuario.id_usuario
    });

    return res.status(201).json({
      success: true,
      mensaje: resultado.duplicado
        ? 'Acta registrada. Advertencia: el PDF ya había sido cargado anteriormente.'
        : 'Acta registrada correctamente.',
      ...resultado
    });

  } catch (error) {
    console.error('Error al guardar acta:', error);

    return res.status(error.statusCode || 400).json({
      success: false,
      mensaje: error.message || 'No fue posible guardar el acta.'
    });
  }
};
const consultarActas = async (req, res) => {
  try {
    const resultado = await listarActas({
      busqueda: String(req.query.busqueda || ''),
      pagina: req.query.pagina,
      limite: req.query.limite
    });

    return res.json({
      success: true,
      ...resultado
    });
  } catch (error) {
    console.error('Error al consultar actas:', error);

    return res.status(500).json({
      success: false,
      mensaje: 'No fue posible consultar las actas.'
    });
  }
};

const consultarActa = async (req, res) => {
  try {
    const id = Number(req.params.id);

    if (!Number.isSafeInteger(id) || id <= 0) {
      return res.status(400).json({
        success: false,
        mensaje: 'El identificador del acta no es válido.'
      });
    }

    const acta = await obtenerActaPorId(id);

    if (!acta) {
      return res.status(404).json({
        success: false,
        mensaje: 'No se encontró el acta solicitada.'
      });
    }

    // Auditar antes de entregar los datos personales del expediente.
    await registrarEventoAuditoria({
      idUsuario: req.usuario.id_usuario,
      accion: 'CONSULTAR',
      entidad: 'actas',
      idRegistro: id,
      valorNuevo: { id_acta: id },
      detalle: 'Consulta del expediente de acta por un usuario autorizado.'
    });

    return res.json({
      success: true,
      acta
    });
  } catch (error) {
    console.error('Error al consultar acta:', error);

    return res.status(500).json({
      success: false,
      mensaje: 'No fue posible consultar el expediente.'
    });
  }
};

const visualizarDocumento = async (req, res) => {
  try {
    const id = Number(req.params.id);

    if (!Number.isSafeInteger(id) || id <= 0) {
      return res.status(400).json({
        success: false,
        mensaje: 'El identificador del acta no es válido.'
      });
    }

    const documento = await obtenerDocumentoActa(id);

    if (!documento) {
      return res.status(404).json({
        success: false,
        mensaje: 'No se encontró el documento del acta.'
      });
    }

    const fs = require('fs');

    if (!fs.existsSync(documento.ruta)) {
      return res.status(404).json({
        success: false,
        mensaje: 'El archivo PDF no está disponible en el almacenamiento.'
      });
    }

    // Auditar antes de transmitir el documento privado.
    await registrarEventoAuditoria({
      idUsuario: req.usuario.id_usuario,
      accion: 'VISUALIZAR_DOCUMENTO',
      entidad: 'documentos',
      idRegistro: documento.id_documento,
      valorNuevo: { id_acta: id, id_documento: documento.id_documento },
      detalle: 'Visualización del PDF asociado a un acta.'
    });

    const nombreSeguro = encodeURIComponent(
      documento.nombre_original.replace(/[\r\n"]/g, '_')
    );

    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader(
      'Content-Disposition',
      `inline; filename*=UTF-8''${nombreSeguro}`
    );
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Cache-Control', 'private, no-store');

    return res.sendFile(documento.ruta);
  } catch (error) {
    console.error('Error al visualizar documento:', error);

    return res.status(500).json({
      success: false,
      mensaje: 'No fue posible visualizar el documento.'
    });
  }
};


// Corrección administrativa de datos del acta (no reemplaza el PDF original).
const actualizarActa = async (req, res) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isSafeInteger(id) || id <= 0) {
      return res.status(400).json({
        success: false,
        mensaje: 'El identificador del acta no es válido.'
      });
    }

    const resultado = await actualizarActaPorAdministrador({
      idActa: id,
      datos: req.body,
      idUsuario: req.usuario.id_usuario
    });

    return res.json({
      success: true,
      mensaje: resultado.actualizado
        ? 'Acta actualizada correctamente.'
        : 'No se detectaron cambios en el acta.',
      ...resultado
    });
  } catch (error) {
    console.error('Error al actualizar acta:', error);
    return res.status(error.statusCode || 500).json({
      success: false,
      mensaje: error.statusCode
        ? error.message
        : 'No fue posible actualizar el acta.'
    });
  }
};

// Eliminación física: borra acta, metadatos y PDF; conserva snapshot en bitácora.
const eliminarActa = async (req, res) => {
  try {
    const id = Number(req.params.id);
    if (!Number.isSafeInteger(id) || id <= 0) {
      return res.status(400).json({
        success: false,
        mensaje: 'El identificador del acta no es válido.'
      });
    }

    const resultado = await eliminarActaPermanentemente({
      idActa: id,
      idUsuario: req.usuario.id_usuario
    });

    return res.json({
      success: true,
      mensaje: resultado.pdf_eliminado_fisicamente
        ? 'El acta y su PDF fueron eliminados permanentemente. El historial permanece en la bitácora.'
        : 'El registro fue eliminado, pero el PDF requiere una purga manual.',
      ...resultado
    });
  } catch (error) {
    console.error('Error al eliminar acta:', error);
    return res.status(error.statusCode || 500).json({
      success: false,
      mensaje: error.statusCode
        ? error.message
        : 'No fue posible eliminar el acta.'
    });
  }
};

module.exports = {
  crearActa,
  consultarActas,
  consultarActa,
  visualizarDocumento,
  actualizarActa,
  eliminarActa
};
