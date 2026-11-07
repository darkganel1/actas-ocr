
const { procesarPDF } = require('../services/ocr.service');

const procesarDocumento = async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({
        success: false,
        mensaje: 'Debes seleccionar un archivo PDF.'
      });
    }

    const archivo = req.file;

    // Comprobar extensión y firma real del PDF.
    const extension = archivo.originalname
      .toLowerCase()
      .split('.')
      .pop();

    const firmaPDF = archivo.buffer
      .subarray(0, 5)
      .toString('ascii');

    if (extension !== 'pdf' || firmaPDF !== '%PDF-') {
      return res.status(400).json({
        success: false,
        mensaje: 'El archivo seleccionado no es un PDF válido.'
      });
    }

    const { sha256, resultado } = await procesarPDF(archivo);

    return res.json({
      success: true,
      mensaje: 'Documento procesado correctamente.',
      sha256,
      resultado
    });

  } catch (error) {
    console.error('Error al procesar documento:', error);

    return res.status(500).json({
      success: false,
      mensaje: error.message || 'No fue posible procesar el documento.'
    });
  }
};

module.exports = { procesarDocumento };
