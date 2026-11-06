"""
archivo-actas | Lector inteligente V11
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
import csv
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

def mejor_etiqueta(texto, aliases, umbral=0.82):
    """
    Coincidencia conservadora:
    - Nunca acepta una sola letra, signos o fragmentos por contención.
    - Busca alias como secuencia de palabras dentro de la línea.
    - Usa similitud difusa solo con cadenas suficientemente largas.
    """
    ntexto = normalizar(texto)
    if len(ntexto) < 4:
        return None, 0.0

    tokens_texto = ntexto.split()
    mejor = (None, 0.0)

    for alias in aliases:
        na = normalizar(alias)
        if len(na) < 4:
            continue

        tokens_alias = na.split()
        n = len(tokens_alias)

        # Coincidencia exacta de frase dentro de una línea que puede
        # contener varios encabezados de tabla.
        exacta = any(
            tokens_texto[i:i+n] == tokens_alias
            for i in range(max(0, len(tokens_texto) - n + 1))
        )
        if exacta:
            return alias, 1.0

        # Similitud completa: solo se permite con longitud suficiente.
        score = SequenceMatcher(None, ntexto, na).ratio()

        # Para líneas con texto adicional, comparar ventanas de palabras
        # de la misma longitud que el alias.
        if len(tokens_texto) > n:
            for i in range(len(tokens_texto) - n + 1):
                ventana = " ".join(tokens_texto[i:i+n])
                score = max(score, SequenceMatcher(None, ventana, na).ratio())

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

    # No asociar líneas solapadas ni que estén en el lado contrario.
    if distancia < 0:
        return None
    # Límite espacial estricto: evita recorrer media página.
    max_dist = min(85, max(35, int(etiqueta["h"] * 2.2)))
    if distancia > max_dist:
        return None

    # Debe existir solapamiento horizontal real entre etiqueta y valor.
    ax1, ax2 = etiqueta["x"], etiqueta["x"] + etiqueta["w"]
    bx1, bx2 = linea["x"], linea["x"] + linea["w"]
    inter = max(0, min(ax2, bx2) - max(ax1, bx1))
    min_ancho = max(1, min(etiqueta["w"], linea["w"]))
    solapamiento = inter / min_ancho
    if solapamiento < 0.20:
        return None

    proximidad = 1.0 - (distancia / max_dist)
    return 0.70 * proximidad + 0.30 * solapamiento


def es_etiqueta_conocida(texto):
    for cfg in ETIQUETAS.values():
        alias, score = mejor_etiqueta(texto, cfg["aliases"])
        if alias and score >= 0.82:
            return True
    return False


def extraer_por_etiquetas(lineas):
    candidatos = {campo: [] for campo in ETIQUETAS}

    for linea in lineas:
        for campo, config in ETIQUETAS.items():
            alias, simil = mejor_etiqueta(linea["texto"], config["aliases"])
            if not alias:
                continue

            opciones = []
            for posible in lineas:
                if posible is linea:
                    continue

                score = puntuacion_valor(
                    posible, linea, config["valor_direccion"]
                )
                if score is None:
                    continue

                texto = posible["texto"].strip()
                if not texto or es_etiqueta_conocida(texto):
                    continue

                # No usar basura OCR de confianza muy baja.
                if posible["confianza"] < 35:
                    continue

                # Aplicar filtro de formato antes de admitir un candidato.
                ok, detalle = validar_formato(campo, texto)
                if not ok:
                    continue

                opciones.append((score, posible))

            if opciones:
                opciones.sort(
                    key=lambda x: (x[0], x[1]["confianza"]),
                    reverse=True
                )
                score, valor = opciones[0]
                candidatos[campo].append({
                    "valor": valor["texto"].strip(),
                    "confianza": valor["confianza"],
                    "etiqueta_detectada": linea["texto"],
                    "alias_coincidente": alias,
                    "similitud_etiqueta": round(simil, 3),
                    "puntuacion_asociacion": round(score, 3),
                    "metodo": "asociacion_local_restringida",
                    "pagina": linea["pagina"],
                    "geometria_etiqueta": {
                        k: linea[k] for k in ("x", "y", "w", "h")
                    },
                    "geometria_valor": {
                        k: valor[k] for k in ("x", "y", "w", "h")
                    }
                })

    return candidatos

    if campo in ("nombre", "primer_apellido", "segundo_apellido",
                 "sexo", "lugar_nacimiento", "nacionalidad"):
        letras = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", str(valor))
        ok = len(letras) >= 2 and len(str(valor).strip()) <= 80
        return ok, "Texto admisible" if ok else "Texto insuficiente"

    return False, "Campo sin regla de validación"



# ---------------- V5: OCR GEOMÉTRICO Y SECCIONES ----------------

def ocr_pagina_config(imagen, pagina_num, psm):
    """OCR alternativo; conserva geometría por palabra."""
    datos = pytesseract.image_to_data(
        imagen, lang=IDIOMA,
        config=f"--oem 1 --psm {psm}",
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
            "texto": texto, "confianza": round(conf, 2),
            "x": int(datos["left"][i]), "y": int(datos["top"][i]),
            "w": int(datos["width"][i]), "h": int(datos["height"][i]),
            "block": int(datos["block_num"][i]),
            "par": int(datos["par_num"][i]),
            "line": int(datos["line_num"][i]),
            "pagina": pagina_num, "psm": psm
        })
    return palabras


def combinar_palabras_ocr(*grupos):
    """Combina PSM 11 y PSM 6 eliminando duplicados geométricos."""
    salida = []
    for grupo in grupos:
        for p in grupo:
            cx = p["x"] + p["w"] / 2
            cy = p["y"] + p["h"] / 2
            duplicado = False
            for q in salida:
                if normalizar(p["texto"]) != normalizar(q["texto"]):
                    continue
                qx = q["x"] + q["w"] / 2
                qy = q["y"] + q["h"] / 2
                if abs(cx - qx) <= max(8, p["w"] * .35) and abs(cy - qy) <= max(6, p["h"] * .45):
                    duplicado = True
                    if p["confianza"] > q["confianza"]:
                        q.update(p)
                    break
            if not duplicado:
                salida.append(dict(p))
    return salida


def lineas_geometricas(palabras):
    """Agrupa palabras por proximidad vertical, sin depender de bloques Tesseract."""
    palabras = sorted(palabras, key=lambda p: (p["y"] + p["h"]/2, p["x"]))
    grupos = []
    for p in palabras:
        cy = p["y"] + p["h"] / 2
        mejor = None
        mejor_dist = None
        for g in grupos[-8:]:
            gy = np.median([z["y"] + z["h"]/2 for z in g])
            tolerancia = max(9, min(24, np.median([z["h"] for z in g + [p]]) * .75))
            d = abs(cy - gy)
            if d <= tolerancia and (mejor_dist is None or d < mejor_dist):
                mejor, mejor_dist = g, d
        if mejor is None:
            grupos.append([p])
        else:
            mejor.append(p)

    lineas = []
    for g in grupos:
        g = sorted(g, key=lambda z: z["x"])
        x1 = min(z["x"] for z in g)
        y1 = min(z["y"] for z in g)
        x2 = max(z["x"] + z["w"] for z in g)
        y2 = max(z["y"] + z["h"] for z in g)
        lineas.append({
            "texto": " ".join(z["texto"] for z in g),
            "texto_norm": normalizar(" ".join(z["texto"] for z in g)),
            "x": x1, "y": y1, "w": x2-x1, "h": y2-y1,
            "confianza": round(float(np.mean([z["confianza"] for z in g])), 2),
            "pagina": g[0]["pagina"], "palabras": g
        })
    return sorted(lineas, key=lambda z: (z["pagina"], z["y"], z["x"]))


def encontrar_encabezado(lineas, frases, y_min=0, y_max=None):
    frases_n = [normalizar(x) for x in frases]
    candidatos = []
    for l in lineas:
        if l["y"] < y_min or (y_max is not None and l["y"] > y_max):
            continue
        t = l["texto_norm"]
        if any(f in t for f in frases_n):
            candidatos.append(l)
    return min(candidatos, key=lambda z: z["y"]) if candidatos else None


def _coincidencia_alias_en_palabras(palabras, aliases):
    """Devuelve la caja de la frase etiqueta detectada en una línea."""
    ws = sorted(palabras, key=lambda z: z["x"])
    toks = [normalizar(z["texto"]) for z in ws]
    for alias in aliases:
        at = normalizar(alias).split()
        if not at:
            continue
        for i in range(len(toks) - len(at) + 1):
            if toks[i:i+len(at)] == at:
                subset = ws[i:i+len(at)]
                x1 = min(z["x"] for z in subset)
                y1 = min(z["y"] for z in subset)
                x2 = max(z["x"] + z["w"] for z in subset)
                y2 = max(z["y"] + z["h"] for z in subset)
                return {
                    "alias": alias, "x": x1, "y": y1,
                    "w": x2-x1, "h": y2-y1,
                    "cx": (x1+x2)/2, "cy": (y1+y2)/2
                }
    # Respaldo difuso, pero solo para una línea completa suficientemente parecida.
    texto = " ".join(z["texto"] for z in ws)
    alias, score = mejor_etiqueta(texto, aliases, umbral=.88)
    if alias:
        x1 = min(z["x"] for z in ws); y1 = min(z["y"] for z in ws)
        x2 = max(z["x"]+z["w"] for z in ws); y2 = max(z["y"]+z["h"] for z in ws)
        return {"alias": alias, "x": x1, "y": y1, "w": x2-x1,
                "h": y2-y1, "cx": (x1+x2)/2, "cy": (y1+y2)/2}
    return None
                    "estado": "requiere_confirmacion"
                }

    # B) Folio: valor debajo de la etiqueta FOLIO, no cualquier número de la página.
    for pagina in paginas:
        ls = [l for l in lineas if l["pagina"] == pagina]
        for l in ls:
            e = _coincidencia_alias_en_palabras(l["palabras"], ["folio"])
            if not e:
                continue
            opciones = []
            for v in ls:
                delta = (v["y"] + v["h"]/2) - e["cy"]
                if 0 < delta < 75:
                    cand = _texto_candidato_columna(v, e["cx"], 90, "folio")
                    if cand and re.fullmatch(r"\d{7,12}", re.sub(r"\s+", "", cand["valor"])):
                        opciones.append((delta, cand))
            if opciones:
                opciones.sort(key=lambda z: z[0])
                campos["folio"] = {
                    **opciones[0][1], "metodo": "etiqueta_folio_y_columna",
                    "validacion_humana": "pendiente",
                    "estado": "requiere_confirmacion", "pagina": pagina
                }
                break

    # C) Persona registrada: restringir al bloque entre ambos encabezados.
    for pagina in paginas:
        ls = [l for l in lineas if l["pagina"] == pagina]
        h_persona = encontrar_encabezado(ls, ["datos de la persona registrada"])
        h_filiacion = encontrar_encabezado(ls, ["datos de filiacion de la persona registrada",
                                                "datos de filiación de la persona registrada"])
        if not h_persona:
            continue
        inicio = h_persona["y"] + h_persona["h"]
        fin = h_filiacion["y"] if h_filiacion else int(inicio + (max(l["y"] for l in ls)-inicio)*.35)
        bloque = [l for l in ls if inicio <= l["y"] < fin + 5]
        etiquetas_persona = {
            "nombre": ["nombre(s)", "nombres", "nombre"],
            "primer_apellido": ["primer apellido", "primerapellido"],
            "segundo_apellido": ["segundo apellido", "segundoapellido"],
            "sexo": ["sexo"],
            "fecha_nacimiento": ["fecha de nacimiento", "fechadenacimiento"],
            "lugar_nacimiento": ["lugar de nacimiento", "lugardenacimiento"]
        }
        encontrados = []
        for l in bloque:
            for campo, aliases in etiquetas_persona.items():
                e = _coincidencia_alias_en_palabras(l["palabras"], aliases)
                if e:
                    encontrados.append((campo, l, e))
        # Cada etiqueta se alinea con el valor de la fila inmediatamente superior.
        centros = sorted(e["cx"] for _,_,e in encontrados)
        dist = [centros[i+1]-centros[i] for i in range(len(centros)-1)
                if centros[i+1]-centros[i] > 10]
        tolerancia_base = max(28, min(105, (float(np.median(dist))*.48 if dist else 65)))
        for campo, etiqueta_linea, e in encontrados:
            opciones = []
            for v in bloque:
                delta = e["cy"] - (v["y"] + v["h"]/2)
                if delta < 0 or delta > 85:
                    continue
                cand = _texto_candidato_columna(v, e["cx"], tolerancia_base, campo)
                if cand:
                    opciones.append((delta, cand))
            if opciones:
                opciones.sort(key=lambda z: (z[0], -z[1]["confianza"]))
                elegido = opciones[0][1]
                anterior = campos.get(campo)
                nuevo = {
                    **elegido, "metodo": "seccion_persona_columna_dinamica",
                    "etiqueta_detectada": e["alias"], "pagina": pagina,
                    "validacion_humana": "pendiente",
                    "estado": "requiere_confirmacion"
                }
                if not anterior or nuevo["confianza"] > anterior.get("confianza", 0):
                    campos[campo] = nuevo
    return campos


def extraer_patrones_v5(lineas):
    """Extrae CURP y códigos numéricos anclados a sus etiquetas espaciales.

    V11 evita tratar todos los números largos de la página como alternativas
    del identificador electrónico. El código de verificación se busca por
    separado y nunca se mezcla con el identificador.
    """
    texto = "\n".join(l.get("texto", "") for l in lineas)
    resultados = {"curp": [], "identificador_electronico": [], "codigo_verificacion": []}

    # CURP: patrón de longitud fija, con deduplicación conservando el orden.
    vistos = set()
    for m in PATRONES["curp"].finditer(texto):
        valor = m.group(0).upper()
        if valor not in vistos:
            vistos.add(valor)
            resultados["curp"].append({
                "valor": valor, "confianza": None, "metodo": "patron_regex",
                "validacion_humana": "pendiente"
            })

    palabras = [w for linea in lineas for w in linea.get("palabras", [])]
    numeros = []
    for w in palabras:
        token = re.sub(r"[^0-9]", "", str(w.get("texto", "")))
        if 15 <= len(token) <= 22:
            numeros.append({
                "valor": token, "x": float(w.get("x", 0)),
                "y": float(w.get("y", 0)), "w": float(w.get("w", 0)),
                "h": float(w.get("h", 0)),
                "pagina": w.get("pagina", 1),
                "confianza": w.get("confianza")
            })
    Busca el valor inmediatamente arriba/abajo de una etiqueta.
    Las distancias y tolerancias se calculan con la altura de texto local.
    """
    alturas = [p["h"] for l in lineas for p in l["palabras"] if p["h"] > 0]
    altura_ref = float(np.median(alturas)) if alturas else 15.0
    max_dist = max(26.0, min(100.0, altura_ref * max_factor))
    tolerancia_x = max(28.0, min(125.0, etiqueta["w"] * 0.85))

    opciones = []
    for linea in lineas:
        for p in linea["palabras"]:
            # No permitir que una palabra que forma parte de la propia
            # etiqueta sea reutilizada como si fuera el valor.
            px1, py1 = p["x"], p["y"]
            px2, py2 = px1 + p["w"], py1 + p["h"]
            ex1, ey1 = etiqueta["x"], etiqueta["y"]
            ex2, ey2 = ex1 + etiqueta["w"], ey1 + etiqueta["h"]
            if min(px2, ex2) > max(px1, ex1) and min(py2, ey2) > max(py1, ey1):
                continue
            cx = p["x"] + p["w"] / 2
            cy = _centro_y(p)
            delta = (etiqueta["cy"] - cy) if direccion == "arriba" else (cy - etiqueta["cy"])
            if delta <= 1 or delta > max_dist:
                continue
            if abs(cx - etiqueta["cx"]) > tolerancia_x:
                continue
            if p["confianza"] < 25:
                continue

            # Para campos de texto se permite reunir varias palabras contiguas
            # alrededor del centro de columna, sin atravesar columnas vecinas.
            zona = [q for q in linea["palabras"]
                    if abs((q["x"] + q["w"]/2) - etiqueta["cx"]) <= tolerancia_x
                    and q["confianza"] >= 20]
            dato = _texto_valido_v6(campo, zona)
            if dato:
                score = (1.0 - delta/max_dist) * 0.65 + (p["confianza"]/100) * 0.35
                opciones.append((score, delta, dato, linea))

    if not opciones:
        return None

    opciones.sort(key=lambda z: (z[0], -z[1]), reverse=True)
    score, delta, dato, linea = opciones[0]
    dato.update({
        "puntuacion_asociacion": round(score, 3),
        "distancia_etiqueta_valor": round(delta, 1),
        "geometria_etiqueta": {
            k: etiqueta[k] for k in ("x", "y", "w", "h")
        }
    })
    return dato




# ---------------- V8: OCR LOCAL POR ETIQUETA ----------------

def ocr_local_etiquetas_v7(imagen, palabras, pagina_num):
  

    lineas = lineas_geometricas(palabras)
    configuraciones = [
        ("folio", ["folio"], "0123456789"),
        ("primer_apellido", ["primer apellido", "primerapellido"], None),
        ("fecha_nacimiento", ["fecha de nacimiento", "fechadenacimiento"], "0123456789/-."),
        ("lugar_nacimiento", ["lugar de nacimiento", "lugardenacimiento"], None),
        ("nacionalidad", ["nacionalidad"], None),
    ]
    regiones = []
    for linea in lineas:
        for campo, aliases, whitelist in configuraciones:
            e = _buscar_etiqueta_v6(linea, aliases, 0.72)
            if not e:
                continue
            # Valores en este formato se encuentran en la banda inmediatamente
            # anterior a la etiqueta. La caja es amplia para captar texto completo.
            alto = max(90, int(e["h"] * 2.5))
            ancho = max(220, int(e["w"] * 1.8))
            x1 = max(0, int(e["cx"] - ancho/2))
            x2 = min(imagen.shape[1], int(e["cx"] + ancho/2))
            y1 = max(0, int(e["y"] - alto))
            y2 = min(imagen.shape[0], int(e["y"] + e["h"] * 0.15))
            if x2-x1 < 40 or y2-y1 < 25:
                continue
            # Evitar repetir prácticamente el mismo recorte.
            if any(abs(x1-r[0]) < 15 and abs(y1-r[1]) < 15 and abs(x2-r[2]) < 15 and abs(y2-r[3]) < 15 for r in regiones):
                continue
            regiones.append((x1,y1,x2,y2,campo,whitelist))

    extras = []
    for ridx, (x1,y1,x2,y2,campo,whitelist) in enumerate(regiones):
        crop = imagen[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        # Ampliación moderada para letras impresas pequeñas.
        escala = 2.0 if crop.shape[1] < 1000 else 1.5
        crop = cv2.resize(crop, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
        # Contraste local y binarización suave en paralelo.
        variantes = [crop, cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]]
        for vi, variante in enumerate(variantes):
            for psm in (7, 6):
                cfg = f"--oem 1 --psm {psm}"
                if whitelist:
                    cfg += f" -c tessedit_char_whitelist={whitelist}"
                data = pytesseract.image_to_data(variante, lang=IDIOMA, config=cfg, output_type=Output.DICT)
                for k, raw in enumerate(data["text"]):
                    txt = raw.strip()
                    if not txt:
                        continue
                    try:
                        conf = float(data["conf"][k])
                    except (ValueError, TypeError):
                        continue
                    if conf < 15:
                        continue
                    # Coordenadas crop -> página original.
                    xx = x1 + int(data["left"][k] / escala)
                    yy = y1 + int(data["top"][k] / escala)
                    ww = max(1, int(data["width"][k] / escala))
                    hh = max(1, int(data["height"][k] / escala))
                    extras.append({
                        "texto": txt, "confianza": round(conf,2),
                        "x": xx, "y": yy, "w": ww, "h": hh,
                        "block": 9000+ridx, "par": vi, "line": psm,
                        "pagina": pagina_num, "psm": f"local{psm}"
                    })
    return extras
    
        # Nacionalidad pertenece a filiación, no a la persona registrada.
        ls = [l for l in lineas if l["pagina"] == pagina]
        en_filiacion = False
        for linea in ls:
            if _buscar_etiqueta_v6(linea, ["datos de filiacion de la persona registrada",
                                           "datos de filiación de la persona registrada"], 0.70):
                en_filiacion = True
                continue
            if not en_filiacion:
                continue
            e = _buscar_etiqueta_v6(linea, ["nacionalidad"], 0.75)
            if e:
                dato = _candidatos_misma_columna_v7(ls, e, "nacionalidad", "arriba", 4.5)
                if dato:
                    dato.update({
                        "metodo": "v6_filiacion_nacionalidad",
                        "etiqueta_detectada": "nacionalidad",
                        "pagina": pagina,
                        "validacion_humana": "pendiente",
                        "estado": "requiere_confirmacion"
                    })
                    salida["nacionalidad"] = dato
    return salida





def extraer_registro_v8(gris, palabras, pagina=1, carpeta_evidencias=None):
    """Lee la tabla registral mediante celdas detectadas y OCR corto por celda."""
    celdas, rejilla = detectar_celdas_tabla(gris)
    alto, ancho = gris.shape
    candidatas=[c for c in celdas if c["y"]>alto*.15 and c["y"]<alto*.40
                and c["w"]>ancho*.045 and c["h"]>alto*.008 and c["h"]<alto*.04]
    filas=[]
    for c in sorted(candidatas,key=lambda z:(z["y"],z["x"])):
        fila=next((f for f in filas if abs(np.median([q["y"] for q in f])-c["y"])<8),None)
        if fila is None: filas.append([c])
        else: fila.append(c)
    filas=[sorted(f,key=lambda z:z["x"]) for f in filas if len(f)>=4]
    resultado={}
    if len(filas)>=2:
        # La fila inferior contiene los valores; columnas ordenadas de izquierda a derecha.
        fila_valores=max(filas,key=lambda f:np.median([c["y"] for c in f]))
        fila_valores=fila_valores[:4]
        nombres=["oficialia","fecha_registro","libro","numero_acta"]
        for idx,(campo,c) in enumerate(zip(nombres,fila_valores)):
            x,y,w,h=(c[k] for k in ("x","y","w","h"))
            crop=gris[max(0,y+2):min(alto,y+h-2),max(0,x+2):min(ancho,x+w-2)]
            if crop.size==0: continue
            crop=cv2.resize(crop,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)
            crop=cv2.copyMakeBorder(crop,18,18,18,18,cv2.BORDER_CONSTANT,value=255)
            whitelist="0123456789/" if campo=="fecha_registro" else "0123456789"
            cfg=f"--oem 1 --psm 7 -c tessedit_char_whitelist={whitelist}"
            data=pytesseract.image_to_data(crop,lang=IDIOMA,config=cfg,output_type=Output.DICT)
            raw=" ".join(t.strip() for t in data["text"] if t.strip())
            confs=[]
            for cval in data["conf"]:
                try:
                    n=float(cval)
                    if n>=0: confs.append(n)
                except (ValueError,TypeError): pass
            confianza=float(np.mean(confs)) if confs else 0.0
            compact=re.sub(r"\s+","",raw)
            if campo=="fecha_registro":
                compact=compact.replace("-","/")
                if re.fullmatch(r"\d{8}",compact): compact=f"{compact[:2]}/{compact[2:4]}/{compact[4:]}"
                elif re.fullmatch(r"\d{4}/\d{4}",compact): compact=f"{compact[:2]}/{compact[2:4]}/{compact[5:]}"
            if campo=="oficialia" and re.fullmatch(r"\d{4}",compact): pass
            elif campo=="fecha_registro" and not re.fullmatch(r"\d{2}/\d{2}/\d{4}",compact): continue
            elif campo in ("libro","numero_acta") and not re.fullmatch(r"\d{1,6}",compact): continue
            resultado[campo]={"valor":compact,"confianza":round(confianza,2),"metodo":"v8_ocr_celda_tabla_detectada",
                "geometria_valor":{"x":x,"y":y,"w":w,"h":h},"pagina":pagina,
                "validacion_humana":"pendiente","estado":"requiere_confirmacion"}

    # Folio: recorte relativo a la etiqueta reconocida por OCR.
    folios=[p for p in palabras if normalizar(p["texto"])=="folio" and p["confianza"]>=70]
    if folios:
        e=folios[0]; x1=max(0,e["x"]-70); x2=min(ancho,e["x"]+e["w"]+80)
        y1=max(0,e["y"]+e["h"]+4); y2=min(alto,y1+42)
        crop=gris[y1:y2,x1:x2]
        if crop.size:
            crop=cv2.resize(crop,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
            crop=cv2.copyMakeBorder(crop,15,15,15,15,cv2.BORDER_CONSTANT,value=255)
            cfg="--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789"
            data=pytesseract.image_to_data(crop,lang=IDIOMA,config=cfg,output_type=Output.DICT)
            raw=" ".join(t.strip() for t in data["text"] if t.strip())
            confs=[]
            for cval in data["conf"]:
                try:
                    n=float(cval)
                    if n>=0: confs.append(n)
                except (ValueError,TypeError): pass
            confianza=float(np.mean(confs)) if confs else 0.0
            folio=re.sub(r"\D","",raw)
            if re.fullmatch(r"\d{7,12}",folio):
                resultado["folio"]={"valor":folio,"confianza":round(confianza,2),"metodo":"v8_folio_recorte_etiqueta",
                    "geometria_valor":{"x":x1,"y":y1,"w":x2-x1,"h":y2-y1},"pagina":pagina,
                    "validacion_humana":"pendiente","estado":"requiere_confirmacion"}
    if carpeta_evidencias is not None and resultado:
        evdir=Path(carpeta_evidencias)/"evidencias_v12"
        evdir.mkdir(parents=True,exist_ok=True)
        overlay=cv2.cvtColor(gris,cv2.COLOR_GRAY2BGR)
        for campo,dato in resultado.items():
            g=dato.get("geometria_valor",{})
            if not g: continue
            x,y,w,h=(g[k] for k in ("x","y","w","h"))
            px=max(12,int(w*.12)); py=max(12,int(h*.7))
            x1=max(0,x-px); y1=max(0,y-py); x2=min(gris.shape[1],x+w+px); y2=min(gris.shape[0],y+h+py)
            crop=gris[y1:y2,x1:x2]
            if crop.size: cv2.imwrite(str(evdir/f"{campo}.png"),crop)
            cv2.rectangle(overlay,(x,y),(x+w,y+h),(0,0,255),2)
            cv2.putText(overlay,campo,(x,max(20,y-8)),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,255),1,cv2.LINE_AA)
        cv2.imwrite(str(evdir/f"pagina_{pagina:03d}_registro_v12.png"),overlay)
    return resultado, rejilla


# ---------------- V8: EXTRACCION POR FILAS Y CELDAS SEMANTICAS ----------------
    curp = (campos_finales.get("curp", {}).get("valor") or "").strip().upper()
    fecha_nac = (campos_finales.get("fecha_nacimiento", {}).get("valor") or "").strip()
    sexo = (campos_finales.get("sexo", {}).get("valor") or "").strip().upper()
    if re.fullmatch(r"[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d", curp):
        if fecha_nac:
            try:
                from datetime import datetime
                fecha = datetime.strptime(fecha_nac, "%d/%m/%Y")
                curp_fecha = curp[4:10]
                fecha_curp = fecha.strftime("%y%m%d")
                validaciones_cruzadas.append({
                    "regla": "curp_fecha_nacimiento",
                    "resultado": "coincide" if curp_fecha == fecha_curp else "discrepancia",
                    "valor_documento": fecha_nac,
                    "valor_curp": curp_fecha,
                    "impacto": "informativo; requiere cotejo humano"
                })
            except ValueError:
                validaciones_cruzadas.append({"regla": "curp_fecha_nacimiento", "resultado": "no_evaluable", "impacto": "fecha OCR no interpretable"})
        if sexo:
            sexo_curp = curp[10]
            sexo_doc = "H" if sexo in ("HOMBRE", "MASCULINO") else "M" if sexo in ("MUJER", "FEMENINO") else None
            if sexo_doc:
                validaciones_cruzadas.append({
                    "regla": "curp_sexo",
                    "resultado": "coincide" if sexo_curp == sexo_doc else "discrepancia",
                    "valor_documento": sexo,
                    "valor_curp": sexo_curp,
                    "impacto": "informativo; requiere cotejo humano"
                })
    recuperados = [k for k,v in campos_finales.items() if v.get("valor") not in (None, "")]
    captura_manual = [k for k,v in campos_finales.items() if v.get("estado") == "captura_manual"]

    # Los campos personales ausentes en V10 quedan para captura manual;
    # no se rellenan con asociaciones heredadas de V5/V6.
    salida = {
        "documento": nombre,
        "paginas": len(paginas),
        "version_motor": "12.0",
        "estrategia": [
            "ocr_complementario_psm_11_y_psm_6",
            "v8_extraccion_por_filas_y_celdas_semanticas",
            "v9_limites_de_columna_dinamicos_sin_coordenada_horizontal_fija",
            "v10_auditoria_de_coherencia_entre_campos",
            "v11_identificador_electronico_anclado_a_etiqueta",
            "v11_codigo_verificacion_independiente",
            "v12_evidencia_geometrica_para_curp_y_codigos",
            "v12_confianza_ocr_propagada_desde_tokens",
            "v12_reporte_de_revision_humana_separado",
            "v9_nacionalidad_solo_si_pertenece_a_seccion_persona_registrada",
            "v10_nacionalidad_no_inferida_de_filiacion",
            "v9_bloqueo_de_fallback_legado_en_campos_personales",
            "v8_evidencias_individuales_por_campo",
            "reconstruccion_de_filas_por_geometria_local_v6",
            "asociacion_etiqueta_valor_por_columna_y_distancia_relativa_v6",
            "separacion_dinamica_persona_y_filiacion_v6",
            "ocr_local_por_etiquetas_v7",
            "asociacion_por_banda_vertical_y_grupo_de_palabras_v7",
            "agrupacion_geometrica_de_palabras",
            "delimitacion_de_secciones_por_encabezados",
            "asociacion_por_columna_y_fila_dinamica",
            "folio_asociado_a_su_etiqueta",
            "curp_por_patron_y_codigos_numericos_por_etiqueta_espacial_v11",
            "revision_humana_obligatoria"
        ],
        "campos": campos_finales,
        "secciones": {
            "persona_registrada": ["nombre", "primer_apellido", "segundo_apellido", "fecha_nacimiento", "sexo", "lugar_nacimiento", "nacionalidad"],
            "datos_registrales": ["oficialia", "fecha_registro", "libro", "numero_acta", "folio"],
            "identificadores": ["curp", "identificador_electronico", "codigo_verificacion"],
            "filiacion": {"estado": "no_extraida_en_esta_version", "nota": "Los datos de madre/padre no se mezclan con los de la persona registrada."}
        },
        "validaciones_cruzadas": validaciones_cruzadas,
        "control_calidad": {
            "total_campos": len(campos_finales),
            "campos_con_valor": len(recuperados),
            "campos_captura_manual": len(captura_manual),
            "campos_recuperados": recuperados,
            "campos_pendientes": captura_manual,
            "nota": "Las validaciones cruzadas son informativas; no validan legalmente el acta ni sustituyen la revisión humana."
        },
        "resultado_paginas": paginas_resultado,
        "estado_expediente": "pendiente_revision_humana"
    }

    archivo_json = carpeta / "resultado_ocr_v12.json"
    archivo_json.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    # Plantilla de cotejo: no confirma campos ni modifica los valores OCR.
    archivo_revision = carpeta / "reporte_revision_humana_v12.csv"
    with archivo_revision.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "seccion", "campo", "valor_ocr", "confianza_ocr", "metodo",
            "estado_ocr", "valor_confirmado_por_revisor", "observaciones"
        ])
        writer.writeheader()
        grupos = {
            "persona_registrada": ["nombre", "primer_apellido", "segundo_apellido", "fecha_nacimiento", "sexo", "lugar_nacimiento", "nacionalidad"],
            "datos_registrales": ["oficialia", "fecha_registro", "libro", "numero_acta", "folio"],
            "identificadores": ["curp", "identificador_electronico", "codigo_verificacion"]
        }
        for seccion, campos in grupos.items():
            for campo in campos:
                d = campos_finales[campo]
                writer.writerow({
                    "seccion": seccion, "campo": campo, "valor_ocr": d.get("valor") or "",
                    "confianza_ocr": d.get("confianza", ""), "metodo": d.get("metodo", ""),
                    "estado_ocr": d.get("estado", ""),
                    "valor_confirmado_por_revisor": "", "observaciones": ""
                })

    print("\n========== RESULTADO V12 ==========")
    for campo, dato in campos_finales.items():
        print(
            f"{campo}: {dato.get('valor') or 'NO IDENTIFICADO'}"
            f" | confianza={dato.get('confianza', 'N/D')}"
            f" | estado={dato.get('estado')}"
        )
    print(f"\nJSON: {archivo_json}")
    print(f"Revisión humana: {archivo_revision}")
    print(f"Evidencias: {carpeta}")
    return salida


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lector inteligente de actas mexicanas V12"
    )