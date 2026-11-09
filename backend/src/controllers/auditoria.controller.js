
const {
  listarEventos,
  obtenerEvento
} = require('../services/auditoria.service');

const listar = async (req, res) => {
  try {
    const resultado = await listarEventos(req.query);

    res.json({
      success: true,
      ...resultado
    });
  } catch (error) {
    console.error('Error al consultar auditoría:', error);

    res.status(500).json({
      success: false,
      mensaje: 'Error al consultar la bitácora de auditoría.'
    });
  }
};

const obtener = async (req, res) => {
  try {
    const { id } = req.params;

    if (!/^\d+$/.test(id)) {
      return res.status(400).json({
        success: false,
        mensaje: 'Identificador de evento no válido.'
      });
    }

    const evento = await obtenerEvento(id);

    if (!evento) {
      return res.status(404).json({
        success: false,
        mensaje: 'Evento no encontrado.'
      });
    }

    res.json({
      success: true,
      evento
    });
  } catch (error) {
    console.error('Error al consultar evento:', error);

    res.status(500).json({
      success: false,
      mensaje: 'Error al consultar el evento.'
    });
  }
};

module.exports = {
  listar,
  obtener
};
