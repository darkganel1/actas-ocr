"""
archivo-actas | Lector inteligente V3
Extracción híbrida:
1) OCR de página completa con cajas y confianza.
2) Detección dinámica de tablas/celdas.
3) Asociación espacial de etiquetas y valores (sin coordenadas fijas).
4) Extracción por patrones para folio, CURP e identificador electrónico.
5) JSON auditable; ningún dato se considera validado automáticamente.

Requisitos:
  pip install opencv-python numpy pytesseract Pillow pdf2image
Tesseract OCR y Poppler deben estar instalados en Windows.
"""

import argparse
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pytesseract import Output
from PIL import Image, ImageOps

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None


# ---------------- CONFIGURACIÓN ----------------

TESSERACT_EXE = os.environ.get(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

IDIOMA = os.environ.get("ACTAS_OCR_LANG", "spa+eng")
DPI_PDF = 300
SALIDA = Path("storage/procesados")

# Etiquetas con posibles variantes OCR. No se usan posiciones fijas.
ETIQUETAS = {
    "oficialia": {
        "aliases": ["oficialia", "numero de oficialia", "no de oficialia"],
        "valor_direccion": "abajo",
        "tipo": "numero"
    },
    "fecha_registro": {
        "aliases": ["fecha de registro", "fecha registro"],
        "valor_direccion": "abajo",
        "tipo": "fecha"
    },
    "libro": {
        "aliases": ["libro", "numero de libro"],
        "valor_direccion": "abajo",
        "tipo": "numero"
    },
    "numero_acta": {
        "aliases": ["numero de acta", "num de acta", "no de acta"],
        "valor_direccion": "abajo",
        "tipo": "numero"
    },
    "nombre": {
        "aliases": ["nombre(s)", "nombres", "nombre"],
        "valor_direccion": "arriba",
        "tipo": "texto"
    },
    "primer_apellido": {
        "aliases": ["primer apellido"],
        "valor_direccion": "arriba",
        "tipo": "texto"
    },
    "segundo_apellido": {
        "aliases": ["segundo apellido"],
        "valor_direccion": "arriba",
        "tipo": "texto"
    },
    "fecha_nacimiento": {
        "aliases": ["fecha de nacimiento"],
        "valor_direccion": "arriba",
        "tipo": "fecha"
    },
    "sexo": {
        "aliases": ["sexo"],
        "valor_direccion": "arriba",
        "tipo": "texto"
    },
    "lugar_nacimiento": {
        "aliases": ["lugar de nacimiento"],
        "valor_direccion": "arriba",
        "tipo": "texto"
    },
    "nacionalidad": {
        "aliases": ["nacionalidad"],
        "valor_direccion": "arriba",
        "tipo": "texto"
    }
}

PATRONES = {
    "folio": re.compile(r"(?<!\d)\d{7,12}(?!\d)"),
    "curp": re.compile(
        r"\b[A-ZÑ]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b",
        re.IGNORECASE
    ),
    "identificador_electronico": re.compile(r"\b\d{15,22}\b"),
}


# ---------------- NORMALIZACIÓN ----------------

def normalizar(texto):
    texto = unicodedata.normalize("NFD", str(texto))
    texto = "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
    )
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def similitud(a, b):
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


def cargar_paginas(ruta, poppler_path=None):
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo: {ruta}")

    ext = ruta.suffix.lower()
    if ext == ".pdf":
        if convert_from_path is None:
            raise RuntimeError(
                "Falta pdf2image. Instala con: "
                "python -m pip install pdf2image"
            )
        kwargs = {"dpi": DPI_PDF}
        if poppler_path:
            kwargs["poppler_path"] = poppler_path
        return convert_from_path(str(ruta), **kwargs)

    if ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"):
        return [Image.open(ruta)]

    raise ValueError("Formato admitido: PDF, JPG, JPEG, PNG, TIF, BMP o WEBP.")


# ---------------- PREPROCESAMIENTO ----------------

def preparar(imagen_pil):
    imagen_pil = ImageOps.exif_transpose(imagen_pil).convert("RGB")
    rgb = np.array(imagen_pil)
    gris = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    alto, ancho = gris.shape
    if max(alto, ancho) < 1800:
        factor = 1800 / max(alto, ancho)
        gris = cv2.resize(
            gris, None, fx=factor, fy=factor,
            interpolation=cv2.INTER_CUBIC
        )

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    mejorada = clahe.apply(gris)
    return gris, mejorada


def corregir_inclinacion(gris):
    bordes = cv2.Canny(gris, 50, 150, apertureSize=3)
    lineas = cv2.HoughLinesP(
        bordes, 1, np.pi / 1800,
        threshold=max(80, gris.shape[1] // 12),
        minLineLength=max(100, gris.shape[1] // 8),
        maxLineGap=25
    )

    angulos = []
    if lineas is not None:
        for linea in lineas:
            valores = np.asarray(linea).reshape(-1)
            if len(valores) != 4:
                continue
            x1, y1, x2, y2 = map(int, valores)
            angulo = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(angulo) <= 5:
                angulos.append(angulo)

    if not angulos:
        return gris, 0.0

    angulo = float(np.median(angulos))
    if abs(angulo) < 0.15:
        return gris, 0.0

    h, w = gris.shape
    matriz = cv2.getRotationMatrix2D((w / 2, h / 2), angulo, 1.0)
    rotada = cv2.warpAffine(
        gris, matriz, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )
    return rotada, angulo


# ---------------- OCR DE PÁGINA COMPLETA ----------------

def ocr_pagina(imagen, pagina_num):
    """Devuelve palabras OCR con geometría, línea y confianza."""
    config = "--oem 1 --psm 11"
    datos = pytesseract.image_to_data(
        imagen, lang=IDIOMA, config=config,
        output_type=Output.DICT
    )

    palabras = []
    for i, raw in enumerate(datos["text"]):
        texto = raw.strip()
        if not texto:
            continue
        try:
            conf = float(datos["conf"][i])
        except (ValueError, TypeError):
            continue
        if conf < 0:
            continue

        palabras.append({
            "texto": texto,
            "confianza": round(conf, 2),
            "x": int(datos["left"][i]),
            "y": int(datos["top"][i]),
            "w": int(datos["width"][i]),
            "h": int(datos["height"][i]),
            "block": int(datos["block_num"][i]),
            "par": int(datos["par_num"][i]),
            "line": int(datos["line_num"][i]),
            "pagina": pagina_num
        })
    return palabras


def agrupar_lineas(palabras):
    grupos = {}
    for p in palabras:
        key = (p["pagina"], p["block"], p["par"], p["line"])
        grupos.setdefault(key, []).append(p)

    lineas = []
    for key, items in grupos.items():
        items = sorted(items, key=lambda z: z["x"])
        x1 = min(p["x"] for p in items)
        y1 = min(p["y"] for p in items)
        x2 = max(p["x"] + p["w"] for p in items)
        y2 = max(p["y"] + p["h"] for p in items)
        lineas.append({
            "texto": " ".join(p["texto"] for p in items),
            "texto_norm": normalizar(" ".join(p["texto"] for p in items)),
            "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1,
            "confianza": round(float(np.mean([p["confianza"] for p in items])), 2),
            "pagina": key[0],
            "palabras": items
        })
    return sorted(lineas, key=lambda l: (l["pagina"], l["y"], l["x"]))


# ---------------- DETECCIÓN DINÁMICA DE TABLAS ----------------

def detectar_celdas_tabla(gris):
    alto, ancho = gris.shape
    binaria = cv2.adaptiveThreshold(
        gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 31, 12
    )

    horizontal = cv2.morphologyEx(
        binaria, cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(25, ancho // 35), 1)
        )
    )
    vertical = cv2.morphologyEx(
        binaria, cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (1, max(20, alto // 55))
        )
    )
    rejilla = cv2.dilate(
        cv2.add(horizontal, vertical),
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        iterations=1
    )

    contornos, _ = cv2.findContours(
        rejilla, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )

    candidatos = []
    area_min = ancho * alto * 0.000025

    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if w * h < area_min:
            continue
        if w < ancho * 0.025 or h < alto * 0.004:
            continue
        if w > ancho * 0.90 and h > alto * 0.85:
            continue
        ratio = w / max(h, 1)
        if not 0.45 <= ratio <= 35:
            continue
        candidatos.append({"x": x, "y": y, "w": w, "h": h})

    # Eliminar duplicados casi idénticos, no contenedores y contenidos.
    candidatos.sort(key=lambda c: c["w"] * c["h"])
    unicos = []
    for a in candidatos:
        duplicado = False
        for b in unicos:
            ix1, iy1 = max(a["x"], b["x"]), max(a["y"], b["y"])
            ix2 = min(a["x"] + a["w"], b["x"] + b["w"])
            iy2 = min(a["y"] + a["h"], b["y"] + b["h"])
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            union = a["w"] * a["h"] + b["w"] * b["h"] - inter
            iou = inter / union if union else 0
            sw = min(a["w"], b["w"]) / max(a["w"], b["w"])
            sh = min(a["h"], b["h"]) / max(a["h"], b["h"])
            if iou > 0.90 and sw > 0.90 and sh > 0.90:
                duplicado = True
                break
        if not duplicado:
            unicos.append(a)

    return sorted(unicos, key=lambda c: (c["y"], c["x"])), rejilla


# ---------------- EXTRACCIÓN POR CELDAS ----------------

def ocr_celda(recorte, tipo="texto"):
    if recorte.size == 0:
        return "", 0.0

    factor = max(2.0, min(5.0, 900 / max(1, recorte.shape[1])))
    ampliada = cv2.resize(
        recorte, None, fx=factor, fy=factor,
        interpolation=cv2.INTER_CUBIC
    )

    variantes = [ampliada]
    _, otsu = cv2.threshold(
        ampliada, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    variantes.append(otsu)

    bloque = max(11, min(51, (min(ampliada.shape) // 2) * 2 + 1))
    adaptativa = cv2.adaptiveThreshold(
        ampliada, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, bloque, 11
    )
    variantes.append(adaptativa)

    configs = [
        "--oem 1 --psm 7",
        "--oem 1 --psm 8",
        "--oem 1 --psm 13"
    ]
    if tipo in ("numero", "fecha"):
        configs += [
            "--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789/",
            "--oem 1 --psm 8 -c tessedit_char_whitelist=0123456789/"
        ]

    mejor = ("", 0.0, -1)
    for variante in variantes:
        entrada = cv2.copyMakeBorder(
            variante, 30, 30, 30, 30,
            cv2.BORDER_CONSTANT, value=255
        )
        for config in configs:
            texto = pytesseract.image_to_string(
                entrada, lang=IDIOMA, config=config
            ).strip()
            datos = pytesseract.image_to_data(
                entrada, lang=IDIOMA, config=config,
                output_type=Output.DICT
            )
            confs = []
            for c in datos["conf"]:
                try:
                    n = float(c)
                    if n >= 0:
                        confs.append(n)
                except (ValueError, TypeError):
                    pass
            conf = float(np.mean(confs)) if confs else 0.0
            limpio = re.sub(r"\s+", "", texto)
            if not limpio:
                continue
            score = conf + min(len(limpio), 24) * 1.2
            if tipo in ("numero", "fecha") and re.fullmatch(r"[0-9/-]+", limpio):
                score += 8
            if score > mejor[2]:
                mejor = (texto, round(conf, 2), score)

    return mejor[0], mejor[1]


def leer_celdas(gris, celdas):
    salida = []
    alto, ancho = gris.shape
    for idx, c in enumerate(celdas):
        x, y, w, h = c["x"], c["y"], c["w"], c["h"]
        margen = max(3, int(min(w, h) * 0.07))
        x1, y1 = max(0, x + margen), max(0, y + margen)
        x2, y2 = min(ancho, x + w - margen), min(alto, y + h - margen)
        recorte = gris[y1:y2, x1:x2]
        texto, conf = ocr_celda(recorte)
        salida.append({
            **c, "id": idx, "texto": texto,
            "texto_norm": normalizar(texto), "confianza": conf
        })
    return salida


# ---------------- ASOCIACIÓN SEMÁNTICA ----------------

def mejor_etiqueta(texto, aliases, umbral=0.72):
    ntexto = normalizar(texto)
    mejor = (None, 0.0)
    for alias in aliases:
        na = normalizar(alias)
        score = SequenceMatcher(None, ntexto, na).ratio()
        # Contención exacta/parcial es más fiable que similitud aislada.
        if na and (na in ntexto or ntexto in na):
            score = max(score, 0.90)
        if score > mejor[1]:
            mejor = (alias, score)
    return mejor if mejor[1] >= umbral else (None, mejor[1])


def puntuacion_valor(linea, etiqueta, direccion):
    if linea["pagina"] != etiqueta["pagina"]:
        return None
    if direccion == "abajo":
        distancia = linea["y"] - (etiqueta["y"] + etiqueta["h"])
    else:
        distancia = etiqueta["y"] - (linea["y"] + linea["h"])

    if distancia < -3:
        return None

    # Preferir líneas verticalmente próximas y con solapamiento horizontal.
    centro_a = etiqueta["x"] + etiqueta["w"] / 2
    centro_b = linea["x"] + linea["w"] / 2
    ancho_ref = max(etiqueta["w"], linea["w"], 1)
    alineacion = max(0, 1 - abs(centro_a - centro_b) / ancho_ref)
    max_dist = max(etiqueta["h"] * 5, 90)
    if distancia > max_dist:
        return None

    proximidad = 1 - distancia / max_dist
    return 0.65 * proximidad + 0.35 * alineacion


def extraer_por_etiquetas(lineas):
    candidatos = {campo: [] for campo in ETIQUETAS}

    for linea in lineas:
        for campo, config in ETIQUETAS.items():
            alias, simil = mejor_etiqueta(
                linea["texto"], config["aliases"]
            )
            if not alias:
                continue

            direccion = config["valor_direccion"]
            opciones = []
            for posible in lineas:
                if posible is linea:
                    continue
                score = puntuacion_valor(posible, linea, direccion)
                if score is None:
                    continue

                texto = posible["texto"].strip()
                if not texto:
                    continue

                # Evitar asociar otra etiqueta como si fuera un valor.
                es_otra_etiqueta = any(
                    mejor_etiqueta(texto, cfg["aliases"])[0]
                    for cfg in ETIQUETAS.values()
                )
                if es_otra_etiqueta:
                    continue

                opciones.append((score, posible))

            if opciones:
                opciones.sort(key=lambda x: x[0], reverse=True)
                score, valor = opciones[0]
                candidatos[campo].append({
                    "valor": valor["texto"].strip(),
                    "confianza": valor["confianza"],
                    "etiqueta_detectada": linea["texto"],
                    "similitud_etiqueta": round(simil, 3),
                    "puntuacion_asociacion": round(score, 3),
                    "metodo": "ocr_linea_vecina_" + direccion,
                    "pagina": linea["pagina"],
                    "geometria_etiqueta": {
                        k: linea[k] for k in ("x", "y", "w", "h")
                    },
                    "geometria_valor": {
                        k: valor[k] for k in ("x", "y", "w", "h")
                    }
                })

    return candidatos


def extraer_patrones(lineas):
    texto = "\n".join(l["texto"] for l in lineas)
    resultados = {}

    for campo, patron in PATRONES.items():
        encontrados = []
        for match in patron.finditer(texto):
            valor = match.group(0).upper()
            # CURP debe cumplir patrón; se deja pendiente de validación.
            encontrados.append({
                "valor": valor,
                "confianza": None,
                "metodo": "patron_regex",
                "validacion_humana": "pendiente"
            })
        resultados[campo] = encontrados

    return resultados


# ---------------- VALIDACIONES BÁSICAS ----------------

def validar_formato(campo, valor):
    if not valor:
        return False, "Sin valor reconocido"

    limpio = re.sub(r"\s+", "", str(valor))

    if campo == "oficialia":
        ok = bool(re.fullmatch(r"\d{1,6}", limpio))
        return ok, "Número" if ok else "Formato numérico no válido"

    if campo in ("libro", "numero_acta"):
        ok = bool(re.fullmatch(r"[A-Za-z0-9/-]{1,20}", limpio))
        return ok, "Identificador admisible" if ok else "Revisar identificador"

    if campo in ("fecha_registro", "fecha_nacimiento"):
        ok = bool(re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", limpio))
        return ok, "Formato de fecha" if ok else "Revisar fecha"

    if campo == "curp":
        ok = bool(PATRONES["curp"].fullmatch(limpio))
        return ok, "Estructura CURP" if ok else "Estructura CURP no válida"

    return True, "Pendiente de comprobación visual"


# ---------------- PROCESAMIENTO ----------------

def procesar(ruta, poppler_path=None):
    paginas = cargar_paginas(ruta, poppler_path)
    nombre = Path(ruta).stem
    carpeta = SALIDA / nombre
    carpeta.mkdir(parents=True, exist_ok=True)

    paginas_resultado = []
    todas_lineas = []
    todas_palabras = []
    candidatos = extraer_por_etiquetas([])

    for numero, pagina in enumerate(paginas, start=1):
        print(f"\nProcesando página {numero}...")

        gris, mejorada = preparar(pagina)
        corregida, angulo = corregir_inclinacion(mejorada)

        palabras = ocr_pagina(corregida, numero)
        lineas = agrupar_lineas(palabras)
        celdas, rejilla = detectar_celdas_tabla(corregida)
        celdas_leidas = leer_celdas(corregida, celdas)

        todas_palabras.extend(palabras)
        todas_lineas.extend(lineas)

        # Guardar evidencias visuales.
        evidencia = cv2.cvtColor(corregida, cv2.COLOR_GRAY2BGR)
        for c in celdas_leidas:
            x, y, w, h = c["x"], c["y"], c["w"], c["h"]
            cv2.rectangle(evidencia, (x, y), (x+w, y+h), (0, 0, 255), 2)

        cv2.imwrite(
            str(carpeta / f"pagina_{numero:03d}_celdas_v3.png"),
            evidencia
        )
        cv2.imwrite(
            str(carpeta / f"pagina_{numero:03d}_rejilla_v3.png"),
            rejilla
        )

        paginas_resultado.append({
            "pagina": numero,
            "angulo_corregido": round(angulo, 3),
            "palabras_ocr": len(palabras),
            "lineas_ocr": len(lineas),
            "celdas_detectadas": len(celdas_leidas),
            "lineas": lineas,
            "celdas": celdas_leidas
        })

    candidatos = extraer_por_etiquetas(todas_lineas)
    patrones = extraer_patrones(todas_lineas)

    campos_finales = {}
    for campo, opciones in candidatos.items():
        if opciones:
            opciones.sort(
                key=lambda x: (
                    x.get("puntuacion_asociacion", 0),
                    x.get("confianza", 0)
                ),
                reverse=True
            )
            elegido = opciones[0]
            valor = elegido["valor"]
            ok, detalle = validar_formato(campo, valor)
            campos_finales[campo] = {
                **elegido,
                "formato_valido": ok,
                "detalle_validacion": detalle,
                "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion",
                "alternativas": opciones[1:]
            }
        else:
            campos_finales[campo] = {
                "valor": None,
                "confianza": 0,
                "formato_valido": False,
                "detalle_validacion": "No se encontró asociación confiable",
                "validacion_humana": "pendiente",
                "estado": "captura_manual"
            }

    for campo, opciones in patrones.items():
        if opciones:
            campos_finales[campo] = {
                "valor": opciones[0]["valor"],
                "confianza": None,
                "metodo": "patron_regex",
                "alternativas": opciones[1:],
                "formato_valido": True,
                "detalle_validacion": "Coincide con patrón; verificar contra el documento",
                "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion"
            }
        else:
            campos_finales[campo] = {
                "valor": None,
                "confianza": 0,
                "formato_valido": False,
                "detalle_validacion": "No encontrado por patrón",
                "validacion_humana": "pendiente",
                "estado": "captura_manual"
            }

    salida = {
        "documento": nombre,
        "paginas": len(paginas),
        "version_motor": "3.0",
        "estrategia": [
            "ocr_completo_con_geometria",
            "deteccion_dinamica_de_tablas",
            "asociacion_semantica_por_proximidad",
            "extraccion_por_patrones"
        ],
        "campos": campos_finales,
        "resultado_paginas": paginas_resultado,
        "estado_expediente": "pendiente_revision_humana"
    }

    archivo_json = carpeta / "resultado_ocr_v3.json"
    archivo_json.write_text(
        json.dumps(salida, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\n========== RESULTADO V3 ==========")
    for campo, dato in campos_finales.items():
        print(
            f"{campo}: {dato.get('valor') or 'NO IDENTIFICADO'}"
            f" | confianza={dato.get('confianza', 'N/D')}"
            f" | estado={dato.get('estado')}"
        )

    print(f"\nJSON: {archivo_json}")
    print(f"Evidencias: {carpeta}")
    return salida


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lector inteligente de actas mexicanas V3"
    )
    parser.add_argument("documento", help="Ruta de PDF o imagen")
    parser.add_argument(
        "--poppler",
        default=None,
        help="Ruta opcional a la carpeta bin de Poppler"
    )
    args = parser.parse_args()
    procesar(args.documento, args.poppler)
