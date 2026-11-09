const { procesarPDF } = require('../services/ocr.service');
const { validarPDF } = require('../services/pdf.validation.service');

const procesarDocumento = async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({
        success: false,
        mensaje: 'Debes seleccionar un archivo PDF.'
      });
    }

    await validarPDF(req.file);
    const { sha256, resultado } = await procesarPDF(req.file);

    return res.json({
      success: true,
      mensaje: 'Documento procesado correctamente.',
      sha256,
      resultado
    });
  } catch (error) {
    console.error('Error al procesar documento:', error);
    return res.status(error.statusCode || 500).json({
      success: false,
      mensaje: error.statusCode
        ? error.message
        : 'No fue posible procesar el documento. Revisa el servicio OCR.'
    });
  }
};

module.exports = { procesarDocumento };
