
const fs = require('fs/promises');
const path = require('path');
const os = require('os');
const { execFile } = require('child_process');
const { promisify } = require('util');
const crypto = require('crypto');

const ejecutar = promisify(execFile);

// Raíz del proyecto: C:\actas-ocr
const raizProyecto = path.resolve(__dirname, '../../..');

const procesarPDF = async (archivo) => {
  const directorioTemporal = await fs.mkdtemp(
    path.join(os.tmpdir(), 'registro-actas-')
  );

  try {
    // PDF temporal con nombre controlado.
    const rutaPDF = path.join(directorioTemporal, 'documento.pdf');

    await fs.writeFile(rutaPDF, archivo.buffer);

    // Huella digital SHA-256.
    const sha256 = crypto
      .createHash('sha256')
      .update(archivo.buffer)
      .digest('hex');

    // Resolver rutas desde la raíz del proyecto.
    const configuracionScript =
      process.env.OCR_SCRIPT || 'ocr/lector_paddleocr_v4_1.py';

    const rutaScript = path.isAbsolute(configuracionScript)
      ? configuracionScript
      : path.resolve(raizProyecto, configuracionScript);

    const configuracionPython =
      process.env.OCR_PYTHON ||
      '.venv-paddle/Scripts/python.exe';

    const python = path.isAbsolute(configuracionPython)
      ? configuracionPython
      : path.resolve(raizProyecto, configuracionPython);

    // Carpeta única para evitar sobrescribir documentos.
    const identificador = crypto.randomUUID();

    const directorioSalida = path.join(
      raizProyecto,
      'storage',
      'paddleocr',
      `proceso_${identificador}`
    );

    // Argumentos para PaddleOCR V4.1.
    const argumentos = [
      rutaScript,
      rutaPDF,
      '--salida',
      directorioSalida
    ];

    // Ejecutar OCR.
    await ejecutar(python, argumentos, {
      cwd: raizProyecto,
      windowsHide: true,
      timeout: 600000,
      maxBuffer: 30 * 1024 * 1024
    });

    // Leer el JSON generado por V4.1.
    const rutaResultado = path.join(
      directorioSalida,
      'resultado_paddleocr_v4_1.json'
    );

    const contenido = await fs.readFile(rutaResultado, 'utf8');
    const resultado = JSON.parse(contenido);

    return {
      sha256,
      resultado
    };

  } catch (error) {
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
    // Eliminar únicamente los archivos temporales.
    // Los resultados PaddleOCR permanecen en storage/paddleocr.
    await fs.rm(directorioTemporal, {
      recursive: true,
      force: true
    });
  }
};

module.exports = { procesarPDF };
