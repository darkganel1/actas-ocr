
const {
  guardarActa,
  listarActas,
  obtenerActaPorId,
  obtenerDocumentoActa
} = require('../services/actas.service');

const crearActa = async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({
        success: false,
        mensaje: 'Debes adjuntar el PDF del acta.'
      });
    }

    const firmaPDF = req.file.buffer
      .subarray(0, 5)
      .toString('ascii');

    if (
      !req.file.originalname.toLowerCase().endsWith('.pdf') ||
      firmaPDF !== '%PDF-'
    ) {
      return res.status(400).json({
        success: false,
        mensaje: 'El archivo seleccionado no es un PDF válido.'
      });
    }
   
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

    return res.status(400).json({
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
module.exports = {
  crearActa,
  consultarActas,
  consultarActa,
  visualizarDocumento
};
