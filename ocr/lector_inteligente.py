
import argparse
import json
import re
from pathlib import Path

import pytesseract
from pytesseract import Output
from pdf2image import convert_from_path
from PIL import Image, ImageOps, ImageEnhance, ImageDraw


# ==========================================
# CONFIGURACIÓN
# ==========================================

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

IDIOMA = "spa+eng"
DPI = 300

CARPETA_SALIDA = Path("storage/procesados")


# ==========================================
# PREPARACIÓN DE IMÁGENES
# ==========================================

def preparar_imagen(imagen):

    imagen = ImageOps.exif_transpose(imagen)
    imagen = ImageOps.grayscale(imagen)
    imagen = ImageOps.autocontrast(imagen)

    imagen = ImageEnhance.Contrast(imagen).enhance(1.25)

    return imagen


def cargar_documento(ruta):

    ruta = Path(ruta)

    if not ruta.exists():
        raise FileNotFoundError(f"No existe: {ruta}")

    extension = ruta.suffix.lower()

    if extension == ".pdf":

        paginas = convert_from_path(
            str(ruta),
            dpi=DPI
        )

    elif extension in [".jpg", ".jpeg", ".png", ".tif", ".tiff"]:

        paginas = [Image.open(ruta).convert("RGB")]

    else:
        raise ValueError("Formato no compatible.")

    return paginas


# ==========================================
# RECONOCIMIENTO OCR
# ==========================================

def reconocer_pagina(imagen, numero_pagina):

    imagen = preparar_imagen(imagen)

    resultados = []

    configuraciones = [11, 6]

    for psm in configuraciones:

        configuracion = f"--oem 1 --psm {psm}"

        datos = pytesseract.image_to_data(
            imagen,
            lang=IDIOMA,
            config=configuracion,
            output_type=Output.DICT
        )

        palabras = []

        for i, texto in enumerate(datos["text"]):

            texto = texto.strip()

            if not texto:
                continue

            try:
                confianza = float(datos["conf"][i])
            except (ValueError, TypeError):
                continue

            if confianza < 0:
                continue

            palabras.append({
                "texto": texto,
                "x": int(datos["left"][i]),
                "y": int(datos["top"][i]),
                "ancho": int(datos["width"][i]),
                "alto": int(datos["height"][i]),
                "confianza": round(confianza, 2),
                "bloque": int(datos["block_num"][i]),
                "parrafo": int(datos["par_num"][i]),
                "linea": int(datos["line_num"][i]),
                "pagina": numero_pagina
            })

        if palabras:

            promedio = sum(
                p["confianza"] for p in palabras
            ) / len(palabras)

            # Seleccionar configuración por cantidad de
            # palabras y confianza media.
            puntuacion = (
                len(palabras) * 0.5
                + promedio * 0.5
            )

            resultados.append({
                "psm": psm,
                "palabras": palabras,
                "promedio": promedio,
                "puntuacion": puntuacion
            })

    if not resultados:
        return []

    mejor = max(
        resultados,
        key=lambda r: r["puntuacion"]
    )

    print(
        f"Página {numero_pagina}: "
        f"PSM {mejor['psm']} | "
        f"{len(mejor['palabras'])} palabras | "
        f"Confianza media: {mejor['promedio']:.2f}"
    )

    return mejor["palabras"]


# ==========================================
# AGRUPACIÓN DINÁMICA DE TEXTO
# ==========================================

def agrupar_lineas(palabras):

    grupos = {}

    for palabra in palabras:

        clave = (
            palabra["pagina"],
            palabra["bloque"],
            palabra["parrafo"],
            palabra["linea"]
        )

        grupos.setdefault(clave, []).append(palabra)

    lineas = []

    for clave, elementos in grupos.items():

        elementos.sort(key=lambda p: p["x"])

        texto = " ".join(
            p["texto"] for p in elementos
        )

        x1 = min(p["x"] for p in elementos)
        y1 = min(p["y"] for p in elementos)

        x2 = max(
            p["x"] + p["ancho"]
            for p in elementos
        )

        y2 = max(
            p["y"] + p["alto"]
            for p in elementos
        )

        lineas.append({
            "texto": texto,
            "x": x1,
            "y": y1,
            "ancho": x2 - x1,
            "alto": y2 - y1,
            "pagina": clave[0],
            "palabras": elementos
        })

    lineas.sort(key=lambda l: (l["pagina"], l["y"], l["x"]))

    return lineas


# ==========================================
# IDENTIFICACIÓN INICIAL DE ETIQUETAS
# ==========================================

def normalizar(texto):

    import unicodedata

    texto = unicodedata.normalize("NFD", texto)

    texto = "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
    )

    return texto.lower().strip()


ETIQUETAS = {
    "oficialia": [
        "oficialia",
        "numero de oficialia"
    ],
    "fecha_registro": [
        "fecha de registro",
        "fecha registro"
    ],
    "libro": [
        "libro"
    ],
    "numero_acta": [
        "numero de acta",
        "num de acta",
        "numero acta"
    ],
    "folio": [
        "folio"
    ],
    "curp": [
        "curp",
        "clave unica de registro de poblacion"
    ],
    "nombre": [
        "nombre(s)",
        "nombres",
        "nombre"
    ],
    "primer_apellido": [
        "primer apellido"
    ],
    "segundo_apellido": [
        "segundo apellido"
    ],
    "fecha_nacimiento": [
        "fecha de nacimiento"
    ]
}


def detectar_etiquetas(lineas):

    encontradas = []

    for linea in lineas:

        texto = normalizar(linea["texto"])

        for campo, variantes in ETIQUETAS.items():

            for etiqueta in variantes:

                etiqueta_normalizada = normalizar(etiqueta)

                if etiqueta_normalizada in texto:

                    encontradas.append({
                        "campo": campo,
                        "etiqueta": etiqueta,
                        "texto_detectado": linea["texto"],
                        "x": linea["x"],
                        "y": linea["y"],
                        "ancho": linea["ancho"],
                        "alto": linea["alto"],
                        "pagina": linea["pagina"]
                    })

    return encontradas


# ==========================================
# VISUALIZACIÓN DE RESULTADOS
# ==========================================

def guardar_visualizacion(imagen, palabras, destino):

    imagen = imagen.convert("RGB")

    dibujo = ImageDraw.Draw(imagen)

    for palabra in palabras:

        x = palabra["x"]
        y = palabra["y"]

        dibujo.rectangle(
            (
                x,
                y,
                x + palabra["ancho"],
                y + palabra["alto"]
            ),
            outline="red",
            width=2
        )

    imagen.save(destino)


# ==========================================
# PROCESAMIENTO PRINCIPAL
# ==========================================

def procesar_documento(ruta):

    paginas = cargar_documento(ruta)

    nombre = Path(ruta).stem

    carpeta = CARPETA_SALIDA / nombre

    carpeta.mkdir(parents=True, exist_ok=True)

    todas_las_palabras = []

    for numero, imagen in enumerate(paginas, start=1):

        print(f"\nProcesando página {numero}...")

        palabras = reconocer_pagina(
            imagen,
            numero
        )

        todas_las_palabras.extend(palabras)

        guardar_visualizacion(
            imagen,
            palabras,
            carpeta / f"pagina_{numero:03d}_ocr.png"
        )

    lineas = agrupar_lineas(todas_las_palabras)

    etiquetas = detectar_etiquetas(lineas)

    resultado = {
        "documento": nombre,
        "paginas": len(paginas),
        "motor": "Tesseract",
        "palabras": todas_las_palabras,
        "lineas": lineas,
        "etiquetas": etiquetas,
        "estado": "pendiente_revision"
    }

    salida = carpeta / "resultado_ocr.json"

    salida.write_text(
        json.dumps(
            resultado,
            ensure_ascii=False,
            indent=4
        ),
        encoding="utf-8"
    )

    print("\n===================================")
    print(" LECTOR INTELIGENTE")
    print("===================================")

    print(f"Documento: {nombre}")
    print(f"Páginas: {len(paginas)}")
    print(f"Palabras: {len(todas_las_palabras)}")
    print(f"Líneas: {len(lineas)}")
    print(f"Etiquetas detectadas: {len(etiquetas)}")

    for etiqueta in etiquetas:
        print(
            f"{etiqueta['campo']}: "
            f"{etiqueta['texto_detectado']}"
        )

    print(f"\nJSON generado: {salida}")

    return resultado


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "documento",
        help="Ruta de PDF o imagen"
    )

    args = parser.parse_args()

    try:
        procesar_documento(args.documento)

    except Exception as error:
        print(f"\nERROR: {error}")
        raise
