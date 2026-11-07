
const fs = require('fs/promises');
const path = require('path');
const os = require('os');
const { execFile } = require('child_process');
const { promisify } = require('util');
const crypto = require('crypto');

const ejecutar = promisify(execFile);

const procesarPDF = async (archivo) => {
  const directorioTemporal = await fs.mkdtemp(
    path.join(os.tmpdir(), 'registro-actas-')
  );

  try {
    // Nombre controlado para evitar problemas con caracteres especiales.
    const rutaPDF = path.join(directorioTemporal, 'documento.pdf');

    await fs.writeFile(rutaPDF, archivo.buffer);

    // Huella digital para detectar archivos idénticos posteriormente.
    const sha256 = crypto
      .createHash('sha256')
      .update(archivo.buffer)
      .digest('hex');

    const rutaScript = path.resolve(
      process.cwd(),
      process.env.OCR_SCRIPT || '../ocr/lector_inteligente_v19.py'
    );

    const python = process.env.OCR_PYTHON || 'python';
    const poppler = process.env.OCR_POPPLER_PATH;

    const argumentos = [rutaScript, rutaPDF];

    if (poppler && poppler.trim() !== '') {
      argumentos.push('--poppler', poppler);
    }

    // Ejecutar OCR dentro del directorio temporal aislado.
    await ejecutar(python, argumentos, {
      cwd: directorioTemporal,
      windowsHide: true,
      timeout: 600000, // 10 minutos
maxBuffer: 30 * 1024 * 1024
    });

    // V19 genera el JSON dentro de storage/procesados/<nombre>/.
    const rutaResultado = path.join(
      directorioTemporal,
      'storage',
      'procesados',
      'documento',
      'resultado_ocr_v19.json'
    );

    const contenido = await fs.readFile(rutaResultado, 'utf8');
    const resultado = JSON.parse(contenido);

    return {
      sha256,
      resultado
    };

  }  catch (error) {
  console.error('Error en servicio OCR:', error.message);

  if (error.stdout) {
    console.error('OCR STDOUT:', error.stdout);
  }

  if (error.stderr) {
    console.error('OCR STDERR:', error.stderr);
  }

  if (error.killed) {
    throw new Error(
      'El procesamiento OCR superó el límite de 10 minutos.'
    );
  }

  if (error.code === 'ENOENT') {
    throw new Error(
      'No se encontró Python, el script OCR o el archivo de resultado.'
    );
  }

  throw new Error(
    error.message || 'No fue posible procesar el documento.'
  );

} finally {
    // Elimina PDF temporal, JSON, CSV e imágenes de evidencia.
    await fs.rm(directorioTemporal, {
      recursive: true,
      force: true
    });
  }
};

module.exports = { procesarPDF };
