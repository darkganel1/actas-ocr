"""
archivo-actas | Lector inteligente V19
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

    if campo == "libro":
        ok = bool(re.fullmatch(r"\d{1,8}", limpio))
        return ok, "Número de libro" if ok else "Libro no numérico"

    if campo == "numero_acta":
        ok = bool(re.fullmatch(r"\d{1,10}", limpio))
        return ok, "Número de acta" if ok else "Acta no numérica"

    if campo == "folio":
        ok = bool(re.fullmatch(r"\d{7,12}", limpio))
        return ok, "Folio numérico" if ok else "Folio no válido"

    if campo in ("fecha_registro", "fecha_nacimiento"):
        if not re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", limpio):
            return False, "Formato de fecha no válido"
        from datetime import datetime
        for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
            try:
                datetime.strptime(limpio, fmt)
                return True, "Fecha calendario válida"
            except ValueError:
                pass
        return False, "Fecha inexistente"

    if campo == "curp":
        ok = bool(PATRONES["curp"].fullmatch(limpio))
        return ok, "Estructura CURP" if ok else "Estructura CURP no válida"

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


def _palabras_en_columna(linea, centro_x, tolerancia):
    return [p for p in linea["palabras"]
            if abs((p["x"] + p["w"]/2) - centro_x) <= tolerancia]


def _texto_candidato_columna(linea, centro_x, tolerancia, campo):
    ws = _palabras_en_columna(linea, centro_x, tolerancia)
    if not ws:
        return None
    texto = " ".join(z["texto"] for z in sorted(ws, key=lambda z: z["x"])).strip()
    if campo == "folio":
        compacto = re.sub(r"\s+", "", texto)
        ok = bool(re.fullmatch(r"\d{7,12}", compacto))
        detalle = "Folio numérico" if ok else "Folio no válido"
    else:
        ok, detalle = validar_formato(campo, texto)
    if not ok:
        # Para texto, tolerancia algo más amplia: el centro puede variar por longitud.
        if campo in ("nombre", "primer_apellido", "segundo_apellido",
                     "sexo", "lugar_nacimiento", "nacionalidad"):
            letras = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", texto)
            ok = len(letras) >= 2 and len(texto) <= 80
    if not ok:
        return None
    conf = float(np.mean([z["confianza"] for z in ws]))
    return {"valor": texto, "confianza": round(conf, 2),
            "geometria_valor": {
                "x": min(z["x"] for z in ws),
                "y": min(z["y"] for z in ws),
                "w": max(z["x"]+z["w"] for z in ws)-min(z["x"] for z in ws),
                "h": max(z["y"]+z["h"] for z in ws)-min(z["y"] for z in ws)
            }, "detalle_validacion": detalle}



def _filas_celdas_v6(celdas):
    """Agrupa cajas de celdas por centro vertical, con tolerancia relativa."""
    validas = [dict(c) for c in (celdas or []) if c.get("w", 0) > 0 and c.get("h", 0) > 0]
    validas.sort(key=lambda c: (c["y"] + c["h"]/2, c["x"]))
    filas = []
    for c in validas:
        cy = c["y"] + c["h"]/2
        grupo = None
        for f in reversed(filas[-8:]):
            fy = float(np.median([z["y"] + z["h"]/2 for z in f]))
            fh = float(np.median([z["h"] for z in f]))
            if abs(cy-fy) <= max(8, min(28, max(fh, c["h"])*0.55)):
                grupo = f
                break
        if grupo is None:
            filas.append([c])
        else:
            grupo.append(c)
    return [sorted(f, key=lambda z: z["x"]) for f in filas]


def _extraer_tabla_celdas_v6(celdas, pagina=1):
    """Encuentra una tabla por dos filas de celdas y sus etiquetas."""
    filas = _filas_celdas_v6(celdas)
    etiquetas = {
        "oficialia": ["oficialia", "numero de oficialia"],
        "fecha_registro": ["fecha de registro", "fecha registro"],
        "libro": ["libro", "numero de libro"],
        "numero_acta": ["numero de acta", "num de acta"]
    }
    mejor_par, mejor_score = None, -1
    for i, fila in enumerate(filas[:-1]):
        textos = [normalizar(c.get("texto", "")) for c in fila]
        encontrados = {}
        for campo, aliases in etiquetas.items():
            for j, txt in enumerate(textos):
                alias, score = mejor_etiqueta(txt, aliases, umbral=0.66)
                if alias:
                    encontrados[campo] = j
                    break
        if len(encontrados) < 3 or len(fila) < 4:
            continue

        siguiente = None
        y_base = max(c["y"] + c["h"] for c in fila)
        for otra in filas[i+1:]:
            delta = min(c["y"] for c in otra) - y_base
            if delta < 0:
                continue
            if delta > max(90, float(np.median([c["h"] for c in fila]))*4):
                break
            if len(otra) < 4:
                continue
            coincidencias = 0
            for h in fila:
                hx = h["x"] + h["w"]/2
                if any(abs(hx-(v["x"]+v["w"]/2)) < max(h["w"],v["w"])*0.65 for v in otra):
                    coincidencias += 1
            if coincidencias >= 3:
                siguiente = otra
                break
        if siguiente is None:
            continue
        score = len(encontrados)*10 + min(len(fila), 6)
        if score > mejor_score:
            mejor_score, mejor_par = score, (fila, siguiente)

    if mejor_par is None:
        return {}

    encabezados, valores = mejor_par
    salida = {}
    orden = ["oficialia", "fecha_registro", "libro", "numero_acta"]
    for idx, campo in enumerate(orden):
        if idx >= len(encabezados) or idx >= len(valores):
            continue
        celda = valores[idx]
        bruto = str(celda.get("texto", "")).strip()
        texto = re.sub(r"\D", "", bruto) if campo != "fecha_registro" else re.sub(r"[^0-9/.-]", "", bruto)
        ok, detalle = validar_formato(campo, texto)
        if not ok:
            continue
        salida[campo] = {
            "valor": texto, "confianza": celda.get("confianza", 0),
            "metodo": "v6_rejilla_tabla_fila_encabezado_valor",
            "etiqueta_detectada": encabezados[idx].get("texto", ""),
            "pagina": pagina, "formato_valido": True,
            "detalle_validacion": detalle, "validacion_humana": "pendiente",
            "estado": "requiere_confirmacion",
            "geometria_valor": {k: celda[k] for k in ("x","y","w","h")}
        }
    return salida



def extraer_registro_v14(imagen, palabras, pagina=1):
    """
    Lee la tabla registral por encabezados detectados en OCR.
    No depende de coordenadas absolutas: localiza los cuatro encabezados,
    calcula límites de columna y relee cada celda de valor por separado.
    """
    campos_alias = {
        "oficialia": ["oficialia", "oficialía"],
        "fecha_registro": ["fecha de registro", "fecha registro"],
        "libro": ["libro"],
        "numero_acta": ["numero de acta", "número de acta"]
    }
    # Agrupar tokens por banda horizontal para localizar etiquetas completas.
    lineas = lineas_geometricas(palabras)
    candidatos = []
    for linea in lineas:
        encontrados = {}
        for campo, aliases in campos_alias.items():
            e = _coincidencia_alias_en_palabras(linea.get("palabras", []), aliases)
            if e:
                encontrados[campo] = e
        if len(encontrados) >= 3:
            candidatos.append((len(encontrados), linea, encontrados))
    if not candidatos:
        return {}

    _, linea_header, encontrados = max(candidatos, key=lambda z: (z[0], z[1]["y"]))
    # La tabla debe tener los encabezados en una misma fila y al menos tres columnas.
    orden = ["oficialia", "fecha_registro", "libro", "numero_acta"]
    presentes = [(c, encontrados[c]) for c in orden if c in encontrados]
    presentes.sort(key=lambda z: z[1]["cx"])
    if len(presentes) < 3:
        return {}

    centros = [e["cx"] for _, e in presentes]
    alto, ancho = imagen.shape[:2]
    limite_izq = max(0, min(e["x"] for _, e in presentes) - 25)
    limite_der = min(ancho, max(e["x"] + e["w"] for _, e in presentes) + 35)
    # Determinar la fila de valores mediante el primer renglón OCR debajo del encabezado.
    y_header_bottom = max(e["y"] + e["h"] for _, e in presentes)
    alto_header = max(e["h"] for _, e in presentes)
    y0 = int(y_header_bottom + max(2, alto_header * 0.10))
    y1 = min(alto, int(y_header_bottom + max(3.2 * alto_header, 58)))

    salida = {}
    for idx, (campo, etiqueta) in enumerate(presentes):
        x0 = limite_izq if idx == 0 else int((centros[idx-1] + centros[idx]) / 2)
        x1 = limite_der if idx == len(presentes)-1 else int((centros[idx] + centros[idx+1]) / 2)
        margen = max(2, int((x1-x0)*0.025))
        x0 += margen
        x1 -= margen
        if x1 <= x0 or y1 <= y0:
            continue
        crop = imagen[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        # OCR focalizado: PSM 7 para la celda de una sola línea.
        config = "--oem 3 --psm 7"
        try:
            txt = pytesseract.image_to_string(crop, lang=IDIOMA, config=config).strip()
            datos = pytesseract.image_to_data(crop, lang=IDIOMA, config=config,
                                               output_type=Output.DICT)
        except Exception:
            continue
        txt = re.sub(r"\s+", " ", txt).strip(" |:_-")
        if campo == "fecha_registro":
            valor = _fecha_es_a_formato(txt) or txt
        else:
            valor = re.sub(r"\D", "", txt)
        ok, detalle = validar_formato(campo, valor)
        if not ok:
            continue
        confs = [float(c) for c in datos.get("conf", []) if str(c).strip() not in ("", "-1")]
        confianza = round(float(np.mean(confs)), 2) if confs else 0.0
        salida[campo] = {
            "valor": valor, "confianza": confianza,
            "metodo": "v15_tabla_registral_encabezados_y_ocr_por_celda",
            "etiqueta_detectada": etiqueta.get("alias", campo),
            "pagina": pagina, "formato_valido": True,
            "detalle_validacion": detalle, "validacion_humana": "pendiente",
            "estado": "requiere_confirmacion",
            "geometria_valor": {"x": x0, "y": y0, "w": x1-x0, "h": y1-y0}
        }
    return salida


def mejorar_lugar_nacimiento_v14(palabras, ancho_pagina, alto_pagina):
    """
    Recupera el lugar de nacimiento como una o varias líneas dentro de su
    propia columna, hasta el encabezado de filiación.
    """
    lineas = _lineas_etiquetas_v8(palabras)
    e_lugar = _hallar_etiquetas_v8(lineas, ["lugar de nacimiento", "lugardenacimiento"], 0.70)
    if not e_lugar:
        return None
    # Delimitar el bloque de persona registrada para no invadir filiación.
    y_persona = 0.0
    y_filiacion = float(alto_pagina)
    for l in lineas:
        n = l.get("texto_norm", "")
        if "datos de la persona registrada" in n:
            y_persona = l["y"] + l["h"]
        if "datos de filiacion" in n:
            y_filiacion = min(y_filiacion, l["y"])
    etiqueta = next((e for e in e_lugar if y_persona < e["cy"] < y_filiacion), None)
    if etiqueta is None:
        return None

    # Usar los centros de las etiquetas de nombre/apellidos/sexo/fecha/lugar
    # para construir límites de columna relativos al documento.
    defs = [
        ["nombre(s)", "nombres"], ["primer apellido", "primerapellido"],
        ["segundo apellido", "segundoapellido"], ["sexo"],
        ["fecha de nacimiento", "fechadenacimiento"],
        ["lugar de nacimiento", "lugardenacimiento"]
    ]
    centros = []
    for aliases in defs:
        halladas = _hallar_etiquetas_v8(lineas, aliases, 0.70)
        hallada = next((z for z in halladas if y_persona < z["cy"] < y_filiacion), None)
        if hallada:
            centros.append(hallada["cx"])
    centros = sorted(set(centros))
    cx = etiqueta["cx"]
    anteriores = [c for c in centros if c < cx]
    siguientes = [c for c in centros if c > cx]
    x_min = (max(anteriores)+cx)/2 if anteriores else max(0, cx-ancho_pagina*0.16)
    x_max = (cx+min(siguientes))/2 if siguientes else min(ancho_pagina, cx+ancho_pagina*0.16)
    margen = max(4, (x_max-x_min)*0.025)
    x_min += margen
    x_max -= margen

    y_max = etiqueta["y"] - 2
    y_min = max(y_persona, y_max - max(150, int(alto_pagina*0.055)))
    filas = _filas_candidatas_v8(palabras, y_max, y_min, x_min, x_max)
    filas_validas = []
    for fila in filas:
        texto = " ".join(p["texto"] for p in fila).strip()
        letras = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", texto)
        if len(letras) < 3:
            continue
        if any(normalizar(texto) == normalizar(x) for x in (
            "lugar de nacimiento", "datos de la persona registrada",
            "datos de filiacion de la persona registrada"
        )):
            continue
        filas_validas.append(fila)
    if not filas_validas:
        return None
    # Orden de arriba hacia abajo y consolidación de líneas dentro de la misma celda.
    filas_validas.sort(key=lambda f: np.median([p["y"] + p["h"]/2 for p in f]))
    usados = [p for fila in filas_validas for p in fila]
    valor = " ".join(" ".join(p["texto"] for p in sorted(f, key=lambda z:z["x"]))
                     for f in filas_validas)
    valor = re.sub(r"\s+", " ", valor).strip(" -_.,:;")
    valor = re.sub(r"\b(Sed|Se|S8|S0)\b", "", valor, flags=re.I).strip()
    valor = re.sub(r"\s+", " ", valor).upper()
    if len(re.sub(r"[^A-ZÁÉÍÓÚÜÑ]", "", valor)) < 4:
        return None
    x0 = min(p["x"] for p in usados); y0 = min(p["y"] for p in usados)
    x1 = max(p["x"]+p["w"] for p in usados); y1 = max(p["y"]+p["h"] for p in usados)
    return {
        "valor": valor, "confianza": round(float(np.mean([p["confianza"] for p in usados])), 2),
        "metodo": "v15_lugar_multilinea_por_columna",
        "geometria_valor": {"x": x0, "y": y0, "w": x1-x0, "h": y1-y0},
        "validacion_humana": "pendiente", "estado": "requiere_confirmacion"
    }



def extraer_registro_v15(imagen, pagina=1):
    """
    Segundo lector de tabla: localiza la zona de tabla mediante proporciones
    de página y lee cada celda de valor por separado. Las proporciones se
    adaptan a cualquier resolución de la misma familia de actas.
    """
    alto, ancho = imagen.shape[:2]
    # La tabla registral está en el bloque superior derecho, antes de
    # "Datos de la Persona Registrada". Se usa una región relativa, no píxeles fijos.
    x0, x1 = int(ancho*0.59), int(ancho*0.96)
    y0, y1 = int(alto*0.25), int(alto*0.31)
    zona = imagen[y0:y1, x0:x1]
    if zona.size == 0:
        return {}
    zh, zw = zona.shape[:2]
    # Límites relativos de las cuatro columnas detectados por la estructura
    # de la tabla de este diseño. Cada celda se procesa de forma independiente.
    limites = [0.04, 0.22, 0.525, 0.695, 0.96]
    campos = ["oficialia", "fecha_registro", "libro", "numero_acta"]
    # Evitar la fila de encabezados y concentrarse en la fila inferior.
    ya, yb = int(zh*0.28), int(zh*0.55)
    salida = {}
    for i, campo in enumerate(campos):
        xa = int(zw*limites[i]) + 3
        xb = int(zw*limites[i+1]) - 3
        celda = zona[ya:yb, xa:xb]
        if celda.size == 0:
            continue
        # Escalado moderado para caracteres pequeños; conservar antialias.
        escala = max(2.0, min(4.0, 180.0/max(1, celda.shape[0])))
        celda = cv2.resize(celda, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
        celda = cv2.copyMakeBorder(celda, 18, 18, 18, 18, cv2.BORDER_CONSTANT, value=255)
        # V17: varios modos de segmentación. La confianza solo se calcula
        # con tokens reales (>0); los -1/0 de Tesseract no se convierten en
        # una confianza artificial.
        cfg_base = "--oem 3 -c tessedit_char_whitelist=0123456789/"
        intentos = []
        for psm in (7, 8, 6, 13):
            cfg = f"{cfg_base} --psm {psm}"
            try:
                txt_try = pytesseract.image_to_string(celda, lang="eng", config=cfg).strip()
                datos_try = pytesseract.image_to_data(celda, lang="eng", config=cfg, output_type=Output.DICT)
            except Exception:
                continue
            conf_try = []
            for token, conf_token in zip(datos_try.get("text", []), datos_try.get("conf", [])):
                if not str(token).strip():
                    continue
                try:
                    c = float(conf_token)
                    if c > 0:
                        conf_try.append(c)
                except (ValueError, TypeError):
                    pass
            intentos.append((len(conf_try), float(np.mean(conf_try)) if conf_try else None,
                             txt_try, psm))
        if not intentos:
            continue
        # Se prioriza una lectura con tokens y confianza positiva; si empatan,
        # se prefiere la de mayor confianza media.
        _, confianza, txt, psm_elegido = max(
            intentos, key=lambda z: (z[0], z[1] if z[1] is not None else -1, len(z[2]))
        )
        txt = re.sub(r"\s+", "", txt)
        if campo == "fecha_registro":
            dig = re.sub(r"[^0-9/]", "", txt)
            # Normalizar separadores perdidos si OCR devuelve 8 dígitos.
            if re.fullmatch(r"\d{8}", dig):
                dig = f"{dig[:2]}/{dig[2:4]}/{dig[4:]}"
            valor = dig
        else:
            valor = re.sub(r"\D", "", txt)
        valido, detalle = validar_formato(campo, valor)
        if valido:
            # Priorizar confianza positiva de tokens reales. En algunas celdas
            # Tesseract devuelve texto válido por image_to_string pero conf=0/-1
            # en image_to_data con PSM 7; se reintenta PSM 6 sin whitelist.
            confs = []
            for token, c in zip(datos.get("text", []), datos.get("conf", [])):
                if not str(token).strip():
                    continue
                try:
                    n = float(c)
                    if n > 0:
                        confs.append(n)
                except (ValueError, TypeError):
                    pass
            if not confs:
                try:
                    datos_alt = pytesseract.image_to_data(
                        celda, lang="eng", config="--oem 1 --psm 6",
                        output_type=Output.DICT
                    )
                    for token, c in zip(datos_alt.get("text", []), datos_alt.get("conf", [])):
                        if not str(token).strip():
                            continue
                        try:
                            n = float(c)
                            if n > 0:
                                confs.append(n)
                        except (ValueError, TypeError):
                            pass
                except Exception:
                    pass
            confianza = round(float(np.mean(confs)), 2) if confs else None
            salida[campo] = {
                "valor": valor, "confianza": confianza,
                "metodo": "v15_ocr_individual_celda_tabla_registral",
                "pagina": pagina, "formato_valido": True,
                "detalle_validacion": detalle, "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion",
                "geometria_valor": {
                    "x": x0+xa, "y": y0+ya, "w": xb-xa, "h": yb-ya
                }
            }
    return salida


def extraer_lugar_nacimiento_v15(imagen, pagina=1):
    """
    Lee el valor multilínea situado inmediatamente encima de la etiqueta
    Lugar de Nacimiento, en la columna derecha de Datos de la Persona Registrada.
    Excluye la tabla superior y la sección de filiación.
    """
    alto, ancho = imagen.shape[:2]
    # Región de persona registrada a la derecha; escalada respecto a la página.
    x0, x1 = int(ancho*0.69), int(ancho*0.96)
    y0, y1 = int(alto*0.365), int(alto*0.435)
    roi = imagen[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    # Reforzar texto fino sin borrar acentos; OCR de bloque multilínea.
    roi = cv2.resize(roi, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
    roi = cv2.copyMakeBorder(roi, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    cfg = "--oem 3 --psm 6"
    try:
        txt = pytesseract.image_to_string(roi, lang=IDIOMA, config=cfg)
        datos = pytesseract.image_to_data(roi, lang=IDIOMA, config=cfg, output_type=Output.DICT)
    except Exception:
        return None
    lineas = []
    for linea in txt.splitlines():
        s = re.sub(r"\s+", " ", linea).strip(" :.-_")
        if not s:
            continue
        n = normalizar(s)
        if any(k in n for k in ["lugar de nacimiento", "segundo apellido", "primer apellido",
                                 "datos de la persona", "datos de filiacion"]):
            continue
        # No aceptar residuos de etiqueta/campo.
        if len(re.sub(r"[^A-ZÁÉÍÓÚÜÑ]", "", s.upper())) < 3:
            continue
        lineas.append(s.upper())
    # Esta región debe contener el nombre del municipio y el estado;
    # descartar OCR que solo haya capturado parte de una etiqueta.
    valor = " ".join(lineas)
    valor = re.sub(r"\s+", " ", valor).strip()
    valor = re.sub(r"\b(APELLIDO|NACIMIENTO|LUGAR|SEGUNDO|PRIMER)\b", "", valor)
    valor = re.sub(r"\s+", " ", valor).strip(" :.-")
    if not valor or len(valor) < 5:
        return None
    confs = [float(c) for c in datos.get("conf", []) if str(c).strip() not in ("", "-1")]
    confianza = round(float(np.mean(confs)), 2) if confs else 0.0
    return {
        "valor": valor, "confianza": confianza,
        "metodo": "v15_lectura_local_multilinea_columna_lugar_nacimiento",
        "pagina": pagina, "validacion_humana": "pendiente",
        "estado": "requiere_confirmacion",
        "geometria_valor": {"x": x0, "y": y0, "w": x1-x0, "h": y1-y0}
    }

def extraer_lugar_nacimiento_v19(palabras, ancho_pagina, alto_pagina, pagina=1):
    """Extrae el lugar anclándose a la etiqueta detectada, sin un ROI fijo.

    Usa las cajas OCR ya calculadas por PSM 6/11. Esto evita una tercera
    llamada Tesseract y limita la lectura a la columna inmediatamente encima
    de la etiqueta "Lugar de Nacimiento".
    """
    lineas = _lineas_etiquetas_v8(palabras)
    etiquetas = _hallar_etiquetas_v8(
        lineas, ["lugar de nacimiento", "lugardenacimiento"], 0.70
    )
    etiquetas = [e for e in etiquetas
                 if alto_pagina * 0.25 < e.get("cy", 0) < alto_pagina * 0.70]
    if not etiquetas:
        return None
    etiqueta = max(etiquetas, key=lambda e: e.get("score", 0))

    # El valor pertenece a la misma columna y aparece justo encima de la etiqueta.
    ex = float(etiqueta.get("x", etiqueta.get("cx", 0)))
    ey = float(etiqueta.get("y", etiqueta.get("cy", 0)))
    ew = float(etiqueta.get("w", max(1, etiqueta.get("linea_h", 1))))
    eh = float(etiqueta.get("h", etiqueta.get("linea_h", 1)))
    x_min = max(0, ex - ew * 0.08)
    x_max = min(ancho_pagina, ex + ew * 1.08)
    y_max = ey - 3
    y_min = max(alto_pagina * 0.25, y_max - max(120, alto_pagina * 0.04))

    candidatos = []
    vistos = set()
    for p in palabras:
        texto = str(p.get("texto", "")).strip()
        if not texto:
            continue
        try:
            conf = float(p.get("confianza", 0))
        except (TypeError, ValueError):
            conf = 0
        cx = float(p.get("x", 0)) + float(p.get("w", 0)) / 2
        cy = float(p.get("y", 0)) + float(p.get("h", 0)) / 2
        if not (x_min <= cx <= x_max and y_min <= cy < y_max):
            continue
        # Excluir puntuación, guiones, residuos de etiquetas y texto de columnas.
        letras = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", texto)
        if len(letras) < 2 or conf < 30:
            continue
        n = normalizar(texto)
        if n in {"lugar", "nacimiento", "apellido", "segundo", "primer",
                 "nombre", "sexo", "fecha", "datos", "persona", "registrada"}:
            continue
        key = (n, round(cx / 12), round(cy / 12))
        if key in vistos:
            continue
        vistos.add(key)
        candidatos.append({**p, "_cx": cx, "_cy": cy, "_conf": conf})

    if not candidatos:
        return None
    candidatos.sort(key=lambda p: (p["_cy"], p["_cx"]))
    filas = []
    for p in candidatos:
        destino = None
        for fila in reversed(filas[-4:]):
            y_fila = float(np.median([q["_cy"] for q in fila]))
            tolerancia = max(10, min(28, 0.55 * max(p.get("h", 1),
                                                    float(np.median([q.get("h", 1) for q in fila])))))
            if abs(p["_cy"] - y_fila) <= tolerancia:
                destino = fila
                break
        if destino is None:
            filas.append([p])
        else:
            destino.append(p)

    textos = []
    usados = []
    for fila in filas:
        fila.sort(key=lambda p: p["_cx"])
        texto_fila = " ".join(str(p["texto"]).strip() for p in fila)
        texto_fila = re.sub(r"\s+", " ", texto_fila).strip(" -_.,:;")
        if len(re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", texto_fila)) < 2:
            continue
        if normalizar(texto_fila) in {"lugar de nacimiento", "datos de la persona registrada"}:
            continue
        textos.append(texto_fila.upper())
        usados.extend(fila)

    valor = re.sub(r"\s+", " ", " ".join(textos)).strip(" -_.,:;")
    valor = re.sub(r"\b(APELLIDO|NACIMIENTO|LUGAR|SEGUNDO|PRIMER)\b", "", valor)
    valor = re.sub(r"\s+", " ", valor).strip(" -_.,:;")
    if len(re.sub(r"[^A-ZÁÉÍÓÚÜÑ]", "", valor)) < 4:
        return None

    x0 = min(int(p["x"]) for p in usados)
    y0 = min(int(p["y"]) for p in usados)
    x1 = max(int(p["x"]) + int(p["w"]) for p in usados)
    y1 = max(int(p["y"]) + int(p["h"]) for p in usados)
    return {
        "valor": valor,
        "confianza": round(float(np.mean([p["_conf"] for p in usados])), 2),
        "metodo": "v19_etiqueta_geometrica_columna_sin_ocr_adicional",
        "pagina": pagina,
        "validacion_humana": "pendiente",
        "estado": "requiere_confirmacion",
        "geometria_valor": {"x": x0, "y": y0, "w": x1-x0, "h": y1-y0}
    }


def extraer_por_secciones_v5(lineas, celdas=None):
    """
    Extrae datos usando límites de secciones y alineación de columnas.
    Las posiciones son relativas a las etiquetas detectadas en cada página.
    """
    campos = {}
    paginas = sorted(set(l["pagina"] for l in lineas))

    # A) Tabla registral: etiquetas arriba y valores inmediatamente debajo.
    config_reg = {
        "oficialia": ["oficialia", "oficialía"],
        "fecha_registro": ["fecha de registro", "fecha registro"],
        "libro": ["libro"],
        "numero_acta": ["numero de acta", "número de acta"]
    }
    for pagina in paginas:
        ls = [l for l in lineas if l["pagina"] == pagina]
        etiquetas = []
        for l in ls:
            for campo, aliases in config_reg.items():
                e = _coincidencia_alias_en_palabras(l["palabras"], aliases)
                if e:
                    etiquetas.append((campo, l, e))
        # Agrupar por encabezado/tabla; los valores deben estar debajo y cerca.
        centros = [e["cx"] for _, _, e in etiquetas]
        separaciones = [abs(a-b) for i,a in enumerate(sorted(centros))
                        for b in sorted(centros)[i+1:] if abs(a-b) > 8]
        paso = float(np.median(separaciones)) if separaciones else 80
        tolerancia = max(18, min(65, paso * .48))
        for campo, etiqueta_linea, e in etiquetas:
            opciones = []
            for l in ls:
                cy = l["y"] + l["h"]/2
                delta = cy - e["cy"]
                if delta < 2 or delta > 95:
                    continue
                cand = _texto_candidato_columna(l, e["cx"], tolerancia, campo)
                if cand:
                    opciones.append((delta, cand))
            if opciones:
                opciones.sort(key=lambda z: (z[0], -z[1]["confianza"]))
                elegido = opciones[0][1]
                campos[campo] = {
                    **elegido, "metodo": "tabla_registral_columna_dinamica",
                    "etiqueta_detectada": e["alias"],
                    "pagina": pagina, "validacion_humana": "pendiente",
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

    def centro_x(w):
        return w["x"] + w["w"] / 2

    def centro_y(w):
        return w["y"] + w["h"] / 2

    def etiqueta_compuesta(alias_tokens):
        hits = []
        for w in palabras:
            t = normalizar(w.get("texto", ""))
            if t in alias_tokens:
                hits.append(w)
        return hits

    # Identificador electrónico: candidato situado debajo de la etiqueta
    # correspondiente, en la misma zona horizontal.
    etiquetas_id = etiqueta_compuesta({"identificador", "electronico"})
    candidatos_id = []
    for n in numeros:
        for e in etiquetas_id:
            dy = centro_y(n) - centro_y(e)
            dx = abs(centro_x(n) - centro_x(e))
            if 0 <= dy <= 180 and dx <= 520:
                candidatos_id.append((dy + dx * 0.18, n))
    if candidatos_id:
        elegido = min(candidatos_id, key=lambda z: z[0])[1]
        resultados["identificador_electronico"] = [{
            "valor": elegido["valor"], "confianza": elegido["confianza"],
            "x": elegido["x"], "y": elegido["y"], "w": elegido["w"], "h": elegido["h"],
            "pagina": elegido.get("pagina", 1),
            "metodo": "patron_regex_etiqueta_espacial_v11",
            "validacion_humana": "pendiente"
        }]

    # Código de verificación: requiere las palabras Código + Verificación;
    # busca el número inmediatamente debajo y en la misma columna.
    etiquetas_cod = etiqueta_compuesta({"codigo", "verificacion"})
    pares_cod = []
    for a in etiquetas_cod:
        for b in etiquetas_cod:
            if a is b:
                continue
            if abs(centro_y(a) - centro_y(b)) <= 35 and abs(centro_x(a) - centro_x(b)) <= 360:
                etiqueta_x = (centro_x(a) + centro_x(b)) / 2
                etiqueta_y = (centro_y(a) + centro_y(b)) / 2
                for n in numeros:
                    dy = centro_y(n) - etiqueta_y
                    dx = abs(centro_x(n) - etiqueta_x)
                    if 0 <= dy <= 150 and dx <= 420:
                        pares_cod.append((dy + dx * 0.18, n))
    if pares_cod:
        elegido = min(pares_cod, key=lambda z: z[0])[1]
        resultados["codigo_verificacion"] = [{
            "valor": elegido["valor"], "confianza": elegido["confianza"],
            "x": elegido["x"], "y": elegido["y"], "w": elegido["w"], "h": elegido["h"],
            "pagina": elegido.get("pagina", 1),
            "metodo": "patron_regex_etiqueta_espacial_v11",
            "validacion_humana": "pendiente"
        }]

    return resultados



def extraer_curp_v16(imagen, palabras, pagina=1, fecha_nacimiento=None):
    """Relee la CURP en un recorte anclado a su etiqueta; no inventa CURP.

    Si OCR confunde O/0 en la posición 17, conserva la lectura original como
    alternativa y propone 0 únicamente cuando la fecha indica nacimiento
    anterior a 2000. La confirmación humana sigue siendo obligatoria.
    """
    alto, ancho = imagen.shape[:2]
    etiquetas = [p for p in palabras if normalizar(p.get("texto", "")) == "curp"]
    if not etiquetas:
        return None
    etiqueta = max(etiquetas, key=lambda p: float(p.get("confianza", 0) or 0))
    ex, ey, ew, eh = (int(etiqueta.get(k, 0)) for k in ("x", "y", "w", "h"))
    # El valor CURP está debajo de la etiqueta y en su misma columna.
    x1 = max(0, ex - int(ancho * 0.015))
    x2 = min(ancho, ex + max(ew, int(ancho * 0.20)) + int(ancho * 0.10))
    y1 = max(0, ey + eh - int(eh * 0.10))
    y2 = min(alto, y1 + int(alto * 0.035))
    roi = imagen[y1:y2, x1:x2]
    if roi.size == 0:
        return None

    candidatos = []
    variantes = []
    base = cv2.resize(roi, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    variantes.append(base)
    gris = cv2.GaussianBlur(base, (3, 3), 0)
    _, otsu = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variantes.append(otsu)
    adapt = cv2.adaptiveThreshold(gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY, 31, 11)
    variantes.append(adapt)
    for vi, recorte in enumerate(variantes):
        recorte = cv2.copyMakeBorder(recorte, 16, 16, 16, 16,
                                     cv2.BORDER_CONSTANT, value=255)
        for psm in (7, 8, 13):
            cfg = (f"--oem 1 --psm {psm} "
                   "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
            try:
                data = pytesseract.image_to_data(recorte, lang="eng", config=cfg,
                                                 output_type=Output.DICT)
            except Exception:
                continue
            raw = "".join(str(t).upper() for t in data.get("text", []) if str(t).strip())
            raw = re.sub(r"[^A-Z0-9]", "", raw)
            confs = []
            for txt, conf in zip(data.get("text", []), data.get("conf", [])):
                if not str(txt).strip():
                    continue
                try:
                    c = float(conf)
                    if c > 0:
                        confs.append(c)
                except (ValueError, TypeError):
                    pass
            if re.fullmatch(r"[A-ZÑ]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d", raw):
                candidatos.append((sum(confs)/len(confs) if confs else 0.0,
                                   raw, vi, psm))

    if not candidatos:
        return None
    candidatos.sort(key=lambda z: (z[0], z[2] == 0), reverse=True)
    conf, raw, vi, psm = candidatos[0]
    valor = raw
    alternativas = []
    correccion = None
    # Posición 17 (índice 16): dígito diferenciador. Para nacimientos 1900-1999
    # se espera un dígito; si OCR devolvió O, proponer 0 sin ocultar el original.
    if len(raw) == 18 and raw[16] == "O":
        try:
            from datetime import datetime
            fecha = datetime.strptime(fecha_nacimiento, "%d/%m/%Y") if fecha_nacimiento else None
        except (ValueError, TypeError):
            fecha = None
        if fecha and fecha.year < 2000:
            sugerida = raw[:16] + "0" + raw[17:]
            alternativas.append({"valor": raw, "motivo": "lectura OCR original; posible O/0"})
            valor = sugerida
            correccion = "Se propone 0 en posición 17 por fecha de nacimiento anterior a 2000; confirmar visualmente"

    return {
        "valor": valor,
        "confianza": round(float(conf), 2) if conf > 0 else None,
        "confianza_ocr": round(float(conf), 2) if conf > 0 else None,
        "texto_ocr": raw,
        "metodo": "v16_ocr_local_curp_anclado_a_etiqueta",
        "pagina": pagina,
        "geometria_valor": {"x": x1, "y": y1, "w": x2-x1, "h": y2-y1},
        "alternativas": alternativas,
        "correccion_sugerida": correccion,
        "validacion_humana": "pendiente",
        "estado": "requiere_confirmacion",
        "formato_valido": True,
        "detalle_validacion": "Lectura local con patrón CURP; requiere cotejo visual"
    }

def adjuntar_evidencia_patrones(resultados, lineas):
    """Adjunta geometría y confianza OCR a CURP/códigos sin alterar su valor."""
    def bbox_union(palabras):
        if not palabras:
            return None
        x1 = min(int(w.get("x", 0)) for w in palabras)
        y1 = min(int(w.get("y", 0)) for w in palabras)
        x2 = max(int(w.get("x", 0)) + int(w.get("w", 0)) for w in palabras)
        y2 = max(int(w.get("y", 0)) + int(w.get("h", 0)) for w in palabras)
        return {"x": x1, "y": y1, "w": x2-x1, "h": y2-y1}

    # Localiza la CURP en las palabras OCR y conserva las cajas que forman el valor.
    for item in resultados.get("curp", []):
        objetivo = str(item.get("valor", "")).upper()
        mejor = None
        for linea in lineas:
            palabras = linea.get("palabras", [])
            texto = " ".join(str(w.get("texto", "")) for w in palabras)
            match = re.search(re.escape(objetivo), texto, re.IGNORECASE)
            if not match:
                # Algunos OCR separan la cadena en varios tokens.
                compacto = "".join(str(w.get("texto", "")) for w in palabras)
                match_compacto = re.search(re.escape(objetivo), compacto, re.IGNORECASE)
                if not match_compacto:
                    continue
                # Para texto compacto, se asocian tokens alfanuméricos de la línea.
                seleccion = [w for w in palabras if re.search(r"[A-Z0-9]", str(w.get("texto", "")), re.I)]
            else:
                inicio, fin = match.span()
                seleccion, cursor = [], 0
                for w in palabras:
                    token = str(w.get("texto", ""))
                    a, b = cursor, cursor + len(token)
                    if b > inicio and a < fin:
                        seleccion.append(w)
                    cursor = b + 1
            if seleccion:
                confs = [float(w.get("confianza", 0)) for w in seleccion if w.get("confianza") is not None]
                media = round(sum(confs)/len(confs), 2) if confs else None
                candidato = {"pagina": linea.get("pagina"), "geometria_valor": bbox_union(seleccion),
                             "confianza_ocr": media, "texto_ocr": " ".join(str(w.get("texto", "")) for w in seleccion)}
                if mejor is None or (media or 0) > (mejor.get("confianza_ocr") or 0):
                    mejor = candidato
        if mejor:
            item.update(mejor)
            item["confianza"] = mejor.get("confianza_ocr")
            item["metodo"] = "patron_regex_con_evidencia_geometrica_v13"

    # Los códigos numéricos ya se asocian espacialmente a su etiqueta en V11.
    # Se propagan sus coordenadas y confianza, que antes se descartaban al formar el JSON final.
    for campo in ("identificador_electronico", "codigo_verificacion"):
        for item in resultados.get(campo, []):
            if all(k in item for k in ("x", "y", "w", "h")):
                item["geometria_valor"] = {k: int(item[k]) for k in ("x", "y", "w", "h")}
                item["pagina"] = item.get("pagina", 1)
                item["confianza_ocr"] = item.get("confianza")
                item["metodo"] = "patron_regex_etiqueta_espacial_con_evidencia_v13"
    return resultados


# ---------------- V6: FILAS Y ASOCIACIÓN POR ETIQUETAS ----------------

def _centro_y(item):
    return item["y"] + item["h"] / 2.0


def lineas_geometricas(palabras):
    """
    Reconstruye filas visuales a partir de las cajas OCR.
    No depende de block/par/line de Tesseract ni de coordenadas absolutas.
    """
    if not palabras:
        return []

    ordenadas = sorted(palabras, key=lambda p: (_centro_y(p), p["x"]))
    grupos = []

    for p in ordenadas:
        cy = _centro_y(p)
        mejor = None
        mejor_dist = None

        # Buscar entre todas las filas recientes; la tolerancia depende
        # de la altura real de letra de cada documento.
        for g in reversed(grupos[-20:]):
            gy = float(np.median([_centro_y(z) for z in g]))
            gh = float(np.median([z["h"] for z in g]))
            ph = float(p["h"])
            tol = max(7.0, min(26.0, 0.62 * max(gh, ph)))
            d = abs(cy - gy)
            if d <= tol and (mejor_dist is None or d < mejor_dist):
                mejor, mejor_dist = g, d

        if mejor is None:
            grupos.append([p])
        else:
            mejor.append(p)

    lineas = []
    for grupo in grupos:
        grupo = sorted(grupo, key=lambda z: z["x"])
        x1 = min(z["x"] for z in grupo)
        y1 = min(z["y"] for z in grupo)
        x2 = max(z["x"] + z["w"] for z in grupo)
        y2 = max(z["y"] + z["h"] for z in grupo)
        texto = " ".join(z["texto"] for z in grupo)
        lineas.append({
            "texto": texto,
            "texto_norm": normalizar(texto),
            "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1,
            "confianza": round(float(np.mean([z["confianza"] for z in grupo])), 2),
            "pagina": grupo[0]["pagina"],
            "palabras": grupo
        })

    return sorted(lineas, key=lambda z: (z["pagina"], z["y"], z["x"]))


def _tokens_norm(palabras):
    salida = []
    for p in sorted(palabras, key=lambda z: z["x"]):
        t = normalizar(p["texto"])
        if t:
            salida.append((t, p))
    return salida


def _buscar_etiqueta_v6(linea, aliases, umbral=0.78):
    """
    Busca frases en secuencias de tokens y admite errores OCR moderados.
    Devuelve geometría ajustada a las palabras que forman la etiqueta.
    """
    tokens = _tokens_norm(linea["palabras"])
    textos = [t for t, _ in tokens]
    mejor = None

    for alias in aliases:
        objetivo = normalizar(alias).split()
        if not objetivo:
            continue

        for inicio in range(len(textos)):
            for largo in range(max(1, len(objetivo)-1), len(objetivo)+2):
                fin = inicio + largo
                if fin > len(textos):
                    continue
                ventana = textos[inicio:fin]
                score = SequenceMatcher(
                    None, " ".join(ventana), " ".join(objetivo)
                ).ratio()
                # Las etiquetas de una sola palabra (p. ej. Sexo) no deben
                # confundirse con ruido OCR del margen.
                umbral_local = max(0.90, umbral) if len(objetivo) == 1 else max(0.80, umbral)
                if score < umbral_local:
                    continue

                subset = [tokens[k][1] for k in range(inicio, fin)]
                x1 = min(z["x"] for z in subset)
                y1 = min(z["y"] for z in subset)
                x2 = max(z["x"] + z["w"] for z in subset)
                y2 = max(z["y"] + z["h"] for z in subset)
                candidato = {
                    "alias": alias, "score": score,
                    "x": x1, "y": y1, "w": x2-x1, "h": y2-y1,
                    "cx": (x1+x2)/2, "cy": (y1+y2)/2
                }
                if mejor is None or score > mejor["score"]:
                    mejor = candidato

    return mejor


def _texto_valido_v6(campo, palabras):
    palabras = sorted(
        [z for z in palabras if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]{2,}", z["texto"])],
        key=lambda z: z["x"]
    )
    if not palabras:
        return None
    texto = " ".join(z["texto"] for z in palabras).strip()
    compacto = re.sub(r"\s+", "", texto)

    if campo == "folio":
        ok = bool(re.fullmatch(r"\d{7,12}", compacto))
        detalle = "Folio numérico" if ok else "Folio no válido"
    else:
        ok, detalle = validar_formato(campo, texto)

    if not ok:
        return None

    return {
        "valor": compacto if campo in ("oficialia", "libro", "numero_acta", "folio") else texto,
        "confianza": round(float(np.mean([z["confianza"] for z in palabras])), 2),
        "detalle_validacion": detalle,
        "geometria_valor": {
            "x": min(z["x"] for z in palabras),
            "y": min(z["y"] for z in palabras),
            "w": max(z["x"] + z["w"] for z in palabras) - min(z["x"] for z in palabras),
            "h": max(z["y"] + z["h"] for z in palabras) - min(z["y"] for z in palabras)
        }
    }


def _candidatos_misma_columna_v6(lineas, etiqueta, campo, direccion,
                                 max_factor=3.2):
    """
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
    """
    Relee regiones próximas a etiquetas conocidas con PSM 7/6.
    Recupera valores pequeños que el OCR de página completa omitió.
    Las coordenadas de salida se convierten nuevamente a coordenadas de página.
    """
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


def _candidatos_misma_columna_v7(lineas, etiqueta, campo, direccion, max_factor=3.2):
    """
    Selecciona palabras por banda vertical del candidato, no toda la línea
    geométrica. Excluye las cajas de la etiqueta y agrupa solo tokens cercanos
    al mismo renglón del valor.
    """
    alturas = [p["h"] for l in lineas for p in l["palabras"] if p["h"] > 0]
    altura_ref = float(np.median(alturas)) if alturas else 18.0
    max_dist = max(35.0, min(135.0, altura_ref * max_factor))
    tol_x = max(75.0, min(260.0, etiqueta["w"] * 0.90))
    candidatos = []

    for linea in lineas:
        for p in linea["palabras"]:
            px1, py1 = p["x"], p["y"]
            px2, py2 = px1+p["w"], py1+p["h"]
            ex1, ey1 = etiqueta["x"], etiqueta["y"]
            ex2, ey2 = ex1+etiqueta["w"], ey1+etiqueta["h"]
            if min(px2,ex2)>max(px1,ex1) and min(py2,ey2)>max(py1,ey1):
                continue
            cx = px1+p["w"]/2
            cy = py1+p["h"]/2
            delta = etiqueta["cy"]-cy if direccion=="arriba" else cy-etiqueta["cy"]
            if not (2 <= delta <= max_dist) or abs(cx-etiqueta["cx"]) > tol_x:
                continue
            if p["confianza"] < 15:
                continue

            # Solo palabras en la misma banda vertical que el candidato.
            banda = max(12.0, min(30.0, altura_ref*0.65))
            zona = []
            for q in linea["palabras"]:
                qcx = q["x"]+q["w"]/2
                qcy = q["y"]+q["h"]/2
                # Excluir cualquier token que intersecte la etiqueta.
                qx1,qy1,qx2,qy2=q["x"],q["y"],q["x"]+q["w"],q["y"]+q["h"]
                overlap = min(qx2,ex2)>max(qx1,ex1) and min(qy2,ey2)>max(qy1,ey1)
                if overlap:
                    continue
                if abs(qcy-cy) <= banda and abs(qcx-etiqueta["cx"]) <= tol_x and q["confianza"] >= 15:
                    zona.append(q)

            # No mezclar tokens muy alejados horizontalmente: mantener
            # únicamente el grupo contiguo más cercano al centro de la etiqueta.
            zona = sorted(zona,key=lambda z:z["x"])
            if not zona:
                zona=[p]
            grupos=[]
            for q in zona:
                if not grupos or q["x"]-(grupos[-1][-1]["x"]+grupos[-1][-1]["w"]) > max(35,altura_ref*1.8):
                    grupos.append([q])
                else:
                    grupos[-1].append(q)
            for grupo in grupos:
                if not any(q is p for q in grupo) and len(grupo)>1:
                    continue
                dato=_texto_valido_v6(campo,grupo)
                if dato:
                    score=(1.0-delta/max_dist)*0.55+(float(np.mean([q["confianza"] for q in grupo]))/100)*0.45
                    candidatos.append((score,delta,dato))

    if not candidatos:
        return None
    candidatos.sort(key=lambda z:(z[0],-z[1]),reverse=True)
    score,delta,dato=candidatos[0]
    dato.update({
        "puntuacion_asociacion":round(score,3),
        "distancia_etiqueta_valor":round(delta,1),
        "geometria_etiqueta":{k:etiqueta[k] for k in ("x","y","w","h")}
    })
    return dato



def _extraer_campos_tabla_v6(lineas, pagina):
    campos = {}
    config = {
        "oficialia": (["oficialia", "oficialía", "numero de oficialia"], "abajo"),
        "fecha_registro": (["fecha de registro", "fecha registro"], "abajo"),
        "libro": (["libro", "numero de libro"], "abajo"),
        "numero_acta": (["numero de acta", "número de acta", "num de acta"], "abajo")
    }

    ls = [l for l in lineas if l["pagina"] == pagina]
    etiquetas = []
    for linea in ls:
        for campo, (aliases, direccion) in config.items():
            e = _buscar_etiqueta_v6(linea, aliases)
            if e:
                etiquetas.append((campo, linea, e, direccion))

    for campo, linea, e, direccion in etiquetas:
        dato = _candidatos_misma_columna_v7(ls, e, campo, direccion, 3.8)
        if dato:
            dato.update({
                "metodo": "v6_tabla_etiqueta_columna_dinamica",
                "etiqueta_detectada": e["alias"],
                "pagina": pagina,
                "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion"
            })
            previo = campos.get(campo)
            if previo is None or dato["confianza"] > previo["confianza"]:
                campos[campo] = dato

    # Folio: siempre asociado a la palabra FOLIO, nunca a cualquier número.
    for linea in ls:
        e = _buscar_etiqueta_v6(linea, ["folio"])
        if not e:
            continue
        dato = _candidatos_misma_columna_v7(ls, e, "folio", "abajo", 4.0)
        if dato:
            dato.update({
                "metodo": "v6_folio_asociado_a_etiqueta",
                "etiqueta_detectada": "FOLIO",
                "pagina": pagina,
                "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion"
            })
            campos["folio"] = dato
        break

    return campos



def _extraer_persona_v6(lineas, pagina):
    ls = [l for l in lineas if l["pagina"] == pagina]
    if not ls:
        return {}

    # Si OCR no reconoce el encabezado de sección, la repetición de Nombre(s)
    # permite identificar dinámicamente el comienzo de filiación.
    filas_nombre = []
    for linea in ls:
        if _buscar_etiqueta_v6(linea, ["nombre(s)", "nombres", "nombre"], 0.74):
            filas_nombre.append(linea)
    corte_filiacion = filas_nombre[1]["y"] if len(filas_nombre) >= 2 else None
    bloque = [l for l in ls if corte_filiacion is None or l["y"] < corte_filiacion]

    etiquetas = {
        "nombre": ["nombre(s)", "nombres", "nombre"],
        "primer_apellido": ["primer apellido", "primerapellido"],
        "segundo_apellido": ["segundo apellido", "segundoapellido"],
        "sexo": ["sexo"],
        "fecha_nacimiento": ["fecha de nacimiento", "fechadenacimiento"],
        "lugar_nacimiento": ["lugar de nacimiento", "lugardenacimiento"]
    }

    salida = {}
    for campo, aliases in etiquetas.items():
        for linea in bloque:
            e = _buscar_etiqueta_v6(linea, aliases, 0.74)
            if not e:
                continue
            dato = _candidatos_misma_columna_v7(bloque, e, campo, "arriba", 5.0)
            if dato:
                dato.update({
                    "metodo": "v6_persona_etiqueta_columna",
                    "etiqueta_detectada": e["alias"],
                    "pagina": pagina,
                    "validacion_humana": "pendiente",
                    "estado": "requiere_confirmacion"
                })
                if campo not in salida or dato["confianza"] > salida[campo]["confianza"]:
                    salida[campo] = dato
            break
    return salida



def extraer_registro_v14(imagen, palabras, pagina=1):
    """
    Lee la tabla registral por encabezados detectados en OCR.
    No depende de coordenadas absolutas: localiza los cuatro encabezados,
    calcula límites de columna y relee cada celda de valor por separado.
    """
    campos_alias = {
        "oficialia": ["oficialia", "oficialía"],
        "fecha_registro": ["fecha de registro", "fecha registro"],
        "libro": ["libro"],
        "numero_acta": ["numero de acta", "número de acta"]
    }
    # Agrupar tokens por banda horizontal para localizar etiquetas completas.
    lineas = lineas_geometricas(palabras)
    candidatos = []
    for linea in lineas:
        encontrados = {}
        for campo, aliases in campos_alias.items():
            e = _coincidencia_alias_en_palabras(linea.get("palabras", []), aliases)
            if e:
                encontrados[campo] = e
        if len(encontrados) >= 3:
            candidatos.append((len(encontrados), linea, encontrados))
    if not candidatos:
        return {}

    _, linea_header, encontrados = max(candidatos, key=lambda z: (z[0], z[1]["y"]))
    # La tabla debe tener los encabezados en una misma fila y al menos tres columnas.
    orden = ["oficialia", "fecha_registro", "libro", "numero_acta"]
    presentes = [(c, encontrados[c]) for c in orden if c in encontrados]
    presentes.sort(key=lambda z: z[1]["cx"])
    if len(presentes) < 3:
        return {}

    centros = [e["cx"] for _, e in presentes]
    alto, ancho = imagen.shape[:2]
    limite_izq = max(0, min(e["x"] for _, e in presentes) - 25)
    limite_der = min(ancho, max(e["x"] + e["w"] for _, e in presentes) + 35)
    # Determinar la fila de valores mediante el primer renglón OCR debajo del encabezado.
    y_header_bottom = max(e["y"] + e["h"] for _, e in presentes)
    alto_header = max(e["h"] for _, e in presentes)
    y0 = int(y_header_bottom + max(2, alto_header * 0.10))
    y1 = min(alto, int(y_header_bottom + max(3.2 * alto_header, 58)))

    salida = {}
    for idx, (campo, etiqueta) in enumerate(presentes):
        x0 = limite_izq if idx == 0 else int((centros[idx-1] + centros[idx]) / 2)
        x1 = limite_der if idx == len(presentes)-1 else int((centros[idx] + centros[idx+1]) / 2)
        margen = max(2, int((x1-x0)*0.025))
        x0 += margen
        x1 -= margen
        if x1 <= x0 or y1 <= y0:
            continue
        crop = imagen[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        # OCR focalizado: PSM 7 para la celda de una sola línea.
        config = "--oem 3 --psm 7"
        try:
            txt = pytesseract.image_to_string(crop, lang=IDIOMA, config=config).strip()
            datos = pytesseract.image_to_data(crop, lang=IDIOMA, config=config,
                                               output_type=Output.DICT)
        except Exception:
            continue
        txt = re.sub(r"\s+", " ", txt).strip(" |:_-")
        if campo == "fecha_registro":
            valor = _fecha_es_a_formato(txt) or txt
        else:
            valor = re.sub(r"\D", "", txt)
        ok, detalle = validar_formato(campo, valor)
        if not ok:
            continue
        confs = [float(c) for c in datos.get("conf", []) if str(c).strip() not in ("", "-1")]
        confianza = round(float(np.mean(confs)), 2) if confs else 0.0
        salida[campo] = {
            "valor": valor, "confianza": confianza,
            "metodo": "v15_tabla_registral_encabezados_y_ocr_por_celda",
            "etiqueta_detectada": etiqueta.get("alias", campo),
            "pagina": pagina, "formato_valido": True,
            "detalle_validacion": detalle, "validacion_humana": "pendiente",
            "estado": "requiere_confirmacion",
            "geometria_valor": {"x": x0, "y": y0, "w": x1-x0, "h": y1-y0}
        }
    return salida


def mejorar_lugar_nacimiento_v14(palabras, ancho_pagina, alto_pagina):
    """
    Recupera el lugar de nacimiento como una o varias líneas dentro de su
    propia columna, hasta el encabezado de filiación.
    """
    lineas = _lineas_etiquetas_v8(palabras)
    e_lugar = _hallar_etiquetas_v8(lineas, ["lugar de nacimiento", "lugardenacimiento"], 0.70)
    if not e_lugar:
        return None
    # Delimitar el bloque de persona registrada para no invadir filiación.
    y_persona = 0.0
    y_filiacion = float(alto_pagina)
    for l in lineas:
        n = l.get("texto_norm", "")
        if "datos de la persona registrada" in n:
            y_persona = l["y"] + l["h"]
        if "datos de filiacion" in n:
            y_filiacion = min(y_filiacion, l["y"])
    etiqueta = next((e for e in e_lugar if y_persona < e["cy"] < y_filiacion), None)
    if etiqueta is None:
        return None

    # Usar los centros de las etiquetas de nombre/apellidos/sexo/fecha/lugar
    # para construir límites de columna relativos al documento.
    defs = [
        ["nombre(s)", "nombres"], ["primer apellido", "primerapellido"],
        ["segundo apellido", "segundoapellido"], ["sexo"],
        ["fecha de nacimiento", "fechadenacimiento"],
        ["lugar de nacimiento", "lugardenacimiento"]
    ]
    centros = []
    for aliases in defs:
        halladas = _hallar_etiquetas_v8(lineas, aliases, 0.70)
        hallada = next((z for z in halladas if y_persona < z["cy"] < y_filiacion), None)
        if hallada:
            centros.append(hallada["cx"])
    centros = sorted(set(centros))
    cx = etiqueta["cx"]
    anteriores = [c for c in centros if c < cx]
    siguientes = [c for c in centros if c > cx]
    x_min = (max(anteriores)+cx)/2 if anteriores else max(0, cx-ancho_pagina*0.16)
    x_max = (cx+min(siguientes))/2 if siguientes else min(ancho_pagina, cx+ancho_pagina*0.16)
    margen = max(4, (x_max-x_min)*0.025)
    x_min += margen
    x_max -= margen

    y_max = etiqueta["y"] - 2
    y_min = max(y_persona, y_max - max(150, int(alto_pagina*0.055)))
    filas = _filas_candidatas_v8(palabras, y_max, y_min, x_min, x_max)
    filas_validas = []
    for fila in filas:
        texto = " ".join(p["texto"] for p in fila).strip()
        letras = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", texto)
        if len(letras) < 3:
            continue
        if any(normalizar(texto) == normalizar(x) for x in (
            "lugar de nacimiento", "datos de la persona registrada",
            "datos de filiacion de la persona registrada"
        )):
            continue
        filas_validas.append(fila)
    if not filas_validas:
        return None
    # Orden de arriba hacia abajo y consolidación de líneas dentro de la misma celda.
    filas_validas.sort(key=lambda f: np.median([p["y"] + p["h"]/2 for p in f]))
    usados = [p for fila in filas_validas for p in fila]
    valor = " ".join(" ".join(p["texto"] for p in sorted(f, key=lambda z:z["x"]))
                     for f in filas_validas)
    valor = re.sub(r"\s+", " ", valor).strip(" -_.,:;")
    valor = re.sub(r"\b(Sed|Se|S8|S0)\b", "", valor, flags=re.I).strip()
    valor = re.sub(r"\s+", " ", valor).upper()
    if len(re.sub(r"[^A-ZÁÉÍÓÚÜÑ]", "", valor)) < 4:
        return None
    x0 = min(p["x"] for p in usados); y0 = min(p["y"] for p in usados)
    x1 = max(p["x"]+p["w"] for p in usados); y1 = max(p["y"]+p["h"] for p in usados)
    return {
        "valor": valor, "confianza": round(float(np.mean([p["confianza"] for p in usados])), 2),
        "metodo": "v15_lugar_multilinea_por_columna",
        "geometria_valor": {"x": x0, "y": y0, "w": x1-x0, "h": y1-y0},
        "validacion_humana": "pendiente", "estado": "requiere_confirmacion"
    }



def extraer_registro_v15(imagen, pagina=1):
    """
    Segundo lector de tabla: localiza la zona de tabla mediante proporciones
    de página y lee cada celda de valor por separado. Las proporciones se
    adaptan a cualquier resolución de la misma familia de actas.
    """
    alto, ancho = imagen.shape[:2]
    # La tabla registral está en el bloque superior derecho, antes de
    # "Datos de la Persona Registrada". Se usa una región relativa, no píxeles fijos.
    x0, x1 = int(ancho*0.59), int(ancho*0.96)
    y0, y1 = int(alto*0.25), int(alto*0.31)
    zona = imagen[y0:y1, x0:x1]
    if zona.size == 0:
        return {}
    zh, zw = zona.shape[:2]
    # Límites relativos de las cuatro columnas detectados por la estructura
    # de la tabla de este diseño. Cada celda se procesa de forma independiente.
    limites = [0.04, 0.22, 0.525, 0.695, 0.96]
    campos = ["oficialia", "fecha_registro", "libro", "numero_acta"]
    # Evitar la fila de encabezados y concentrarse en la fila inferior.
    ya, yb = int(zh*0.28), int(zh*0.55)
    salida = {}
    for i, campo in enumerate(campos):
        xa = int(zw*limites[i]) + 3
        xb = int(zw*limites[i+1]) - 3
        celda = zona[ya:yb, xa:xb]
        if celda.size == 0:
            continue
        # Escalado moderado para caracteres pequeños; conservar antialias.
        escala = max(2.0, min(4.0, 180.0/max(1, celda.shape[0])))
        celda = cv2.resize(celda, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
        celda = cv2.copyMakeBorder(celda, 18, 18, 18, 18, cv2.BORDER_CONSTANT, value=255)
        cfg_base = "--oem 3 -c tessedit_char_whitelist=0123456789/"
        intentos = []
        for psm in (7, 8, 6, 13):
            cfg = f"{cfg_base} --psm {psm}"
            try:
                txt_try = pytesseract.image_to_string(celda, lang="eng", config=cfg).strip()
                datos_try = pytesseract.image_to_data(celda, lang="eng", config=cfg, output_type=Output.DICT)
            except Exception:
                continue
            conf_try = []
            for token, conf_token in zip(datos_try.get("text", []), datos_try.get("conf", [])):
                if not str(token).strip():
                    continue
                try:
                    c = float(conf_token)
                    if c > 0:
                        conf_try.append(c)
                except (ValueError, TypeError):
                    pass
            intentos.append((len(conf_try), float(np.mean(conf_try)) if conf_try else None, txt_try, psm))
        if not intentos:
            continue
        _, confianza, txt, psm_elegido = max(
            intentos, key=lambda z: (z[0], z[1] if z[1] is not None else -1, len(z[2]))
        )
        txt = re.sub(r"\s+", "", txt)
        if campo == "fecha_registro":
            dig = re.sub(r"[^0-9/]", "", txt)
            # Normalizar separadores perdidos si OCR devuelve 8 dígitos.
            if re.fullmatch(r"\d{8}", dig):
                dig = f"{dig[:2]}/{dig[2:4]}/{dig[4:]}"
            valor = dig
        else:
            valor = re.sub(r"\D", "", txt)
        valido, detalle = validar_formato(campo, valor)
        if valido:
            salida[campo] = {
                "valor": valor, "confianza": round(confianza, 2) if confianza is not None else None,
                "metodo": f"v17_ocr_celda_tabla_multipsm_{psm_elegido}",
                "pagina": pagina, "formato_valido": True,
                "detalle_validacion": detalle, "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion",
                "geometria_valor": {
                    "x": x0+xa, "y": y0+ya, "w": xb-xa, "h": yb-ya
                }
            }
    return salida


def extraer_lugar_nacimiento_v15(imagen, pagina=1):
    """
    Lee el valor multilínea situado inmediatamente encima de la etiqueta
    Lugar de Nacimiento, en la columna derecha de Datos de la Persona Registrada.
    Excluye la tabla superior y la sección de filiación.
    """
    alto, ancho = imagen.shape[:2]
    # Región de persona registrada a la derecha; escalada respecto a la página.
    x0, x1 = int(ancho*0.69), int(ancho*0.96)
    y0, y1 = int(alto*0.365), int(alto*0.435)
    roi = imagen[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    # Reforzar texto fino sin borrar acentos; OCR de bloque multilínea.
    roi = cv2.resize(roi, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
    roi = cv2.copyMakeBorder(roi, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    cfg = "--oem 3 --psm 6"
    try:
        txt = pytesseract.image_to_string(roi, lang=IDIOMA, config=cfg)
        datos = pytesseract.image_to_data(roi, lang=IDIOMA, config=cfg, output_type=Output.DICT)
    except Exception:
        return None
    lineas = []
    for linea in txt.splitlines():
        s = re.sub(r"\s+", " ", linea).strip(" :.-_")
        if not s:
            continue
        n = normalizar(s)
        if any(k in n for k in ["lugar de nacimiento", "segundo apellido", "primer apellido",
                                 "datos de la persona", "datos de filiacion"]):
            continue
        # No aceptar residuos de etiqueta/campo.
        if len(re.sub(r"[^A-ZÁÉÍÓÚÜÑ]", "", s.upper())) < 3:
            continue
        lineas.append(s.upper())
    # Esta región debe contener el nombre del municipio y el estado;
    # descartar OCR que solo haya capturado parte de una etiqueta.
    valor = " ".join(lineas)
    valor = re.sub(r"\s+", " ", valor).strip()
    valor = re.sub(r"\b(APELLIDO|NACIMIENTO|LUGAR|SEGUNDO|PRIMER)\b", "", valor)
    valor = re.sub(r"\s+", " ", valor).strip(" :.-")
    if not valor or len(valor) < 5:
        return None
    confs = [float(c) for c in datos.get("conf", []) if str(c).strip() not in ("", "-1")]
    confianza = round(float(np.mean(confs)), 2) if confs else 0.0
    return {
        "valor": valor, "confianza": confianza,
        "metodo": "v15_lectura_local_multilinea_columna_lugar_nacimiento",
        "pagina": pagina, "validacion_humana": "pendiente",
        "estado": "requiere_confirmacion",
        "geometria_valor": {"x": x0, "y": y0, "w": x1-x0, "h": y1-y0}
    }

def extraer_por_secciones_v5(lineas, celdas=None):
    """
    Interfaz compatible con el pipeline anterior.
    V6 reconstruye filas y asocia valores localmente a cada etiqueta.
    """
    salida = {}
    paginas = sorted(set(l["pagina"] for l in lineas))
    for pagina in paginas:
        if celdas:
            celdas_pagina = [c for c in celdas if c.get("pagina", pagina) == pagina]
            salida.update(_extraer_tabla_celdas_v6(celdas_pagina, pagina))
        salida.update(_extraer_campos_tabla_v6(lineas, pagina))
        persona = _extraer_persona_v6(lineas, pagina)
        for campo, dato in persona.items():
            anterior = salida.get(campo)
            if anterior is None or dato["confianza"] > anterior.get("confianza", 0):
                salida[campo] = dato

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
            resultado[campo]={"valor":compact,"confianza":round(confianza,2),"metodo":"v8_ocr_celda_tabla_detectada_v13",
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
        evdir=Path(carpeta_evidencias)/"evidencias_v15"
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
        cv2.imwrite(str(evdir/f"pagina_{pagina:03d}_registro_v13.png"),overlay)
    return resultado, rejilla


# ---------------- V8: EXTRACCION POR FILAS Y CELDAS SEMANTICAS ----------------

def _centro_token_v8(p):
    return p["x"] + p["w"] / 2, p["y"] + p["h"] / 2


def _lineas_etiquetas_v8(palabras):
    """Reconstruye líneas de etiquetas a partir de OCR PSM 6/11."""
    return lineas_geometricas(palabras)


def _hallar_etiquetas_v8(lineas, aliases, umbral=0.76):
    halladas = []
    for linea in lineas:
        e = _buscar_etiqueta_v6(linea, aliases, umbral)
        if e:
            e["linea_y"] = linea["y"]
            e["linea_h"] = linea["h"]
            halladas.append(e)
    # Evitar duplicados PSM6/PSM11 casi coincidentes.
    salida = []
    for e in sorted(halladas, key=lambda z: (-z["score"], z["y"], z["x"])):
        if not any(abs(e["cx"]-q["cx"]) < 35 and abs(e["cy"]-q["cy"]) < 24 for q in salida):
            salida.append(e)
    return sorted(salida, key=lambda z: (z["cy"], z["cx"]))


def _filas_candidatas_v8(palabras, y_max, y_min, x_min, x_max):
    """Agrupa tokens OCR en renglones dentro de una celda delimitada."""
    tokens = []
    for p in palabras:
        cx, cy = _centro_token_v8(p)
        if not (y_min <= cy < y_max and x_min <= cx <= x_max):
            continue
        # Los límites x_min/x_max ya delimitan la columna actual.
        # No aplicar topes absolutos: excluían columnas derechas en páginas anchas.
        if p["confianza"] < 25:
            continue
        if not re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]", p["texto"]):
            continue
        tokens.append(p)
    tokens.sort(key=lambda z: (z["y"]+z["h"]/2, z["x"]))
    filas=[]
    for p in tokens:
        cy=p["y"]+p["h"]/2
        destino=None
        for fila in reversed(filas[-5:]):
            fy=float(np.median([q["y"]+q["h"]/2 for q in fila]))
            tol=max(8,min(22,0.65*max(p["h"],float(np.median([q["h"] for q in fila])))))
            if abs(cy-fy)<=tol:
                destino=fila; break
        if destino is None: filas.append([p])
        else: destino.append(p)
    return [sorted(f,key=lambda z:z["x"]) for f in filas]


def _fecha_es_a_formato(texto):
    """Convierte fechas numéricas o escritas en español a DD/MM/AAAA."""
    from datetime import datetime
    t = normalizar(texto)
    meses = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "setiembre": "09", "octubre": "10",
        "noviembre": "11", "diciembre": "12"
    }
    m = re.search(r"\b(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})\b", t)
    if m and m.group(2) in meses:
        candidato = f"{int(m.group(1)):02d}/{meses[m.group(2)]}/{m.group(3)}"
        try:
            datetime.strptime(candidato, "%d/%m/%Y")
            return candidato
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", str(texto))
    if m:
        candidato = f"{int(m.group(1)):02d}/{int(m.group(2)):02d}/{m.group(3)}"
        try:
            datetime.strptime(candidato, "%d/%m/%Y")
            return candidato
        except ValueError:
            return None
    return None


def _extraer_valor_celda_v8(palabras, etiqueta, etiquetas_misma_fila, campo,
                            ancho_pagina, alto_pagina, max_delta=105):
    """Asocia el renglón de valor inmediatamente superior a la etiqueta.

    Los límites horizontales se calculan con los centros de las etiquetas
    vecinas de la misma fila; no se reutiliza texto de columnas adyacentes.
    """
    centros=sorted(e["cx"] for e in etiquetas_misma_fila)
    centro=etiqueta["cx"]
    idx=min(range(len(centros)),key=lambda i:abs(centros[i]-centro))
    if len(centros)==1:
        x_min=max(60,centro-200); x_max=min(ancho_pagina-60,centro+200)
    else:
        x_min=60 if idx==0 else (centros[idx-1]+centro)/2
        x_max=ancho_pagina-60 if idx==len(centros)-1 else (centro+centros[idx+1])/2
    # Un pequeño margen interior reduce cruces por columnas.
    margen=max(5,(x_max-x_min)*0.015)
    x_min+=margen; x_max-=margen
    y_max=etiqueta["y"]-2
    y_min=max(0, y_max-max_delta)
    filas=_filas_candidatas_v8(palabras,y_max,y_min,x_min,x_max)
    if not filas: return None

    candidatos=[]
    for fila in filas:
        cy=float(np.median([p["y"]+p["h"]/2 for p in fila]))
        delta=etiqueta["cy"]-cy
        if delta<=0: continue
        texto=" ".join(p["texto"] for p in fila).strip()
        # Reglas de contenido y limpieza por campo.
        if campo in ("fecha_nacimiento",):
            fecha_normalizada = _fecha_es_a_formato(texto)
            if not fecha_normalizada: continue
            valor=fecha_normalizada
            usados=fila
        elif campo=="lugar_nacimiento":
            # Permite varias palabras, exige texto alfabético y descarta guiones.
            usados=[p for p in fila if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}",p["texto"])]
            valor=" ".join(p["texto"] for p in usados)
        elif campo=="nacionalidad":
            usados=[p for p in fila if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}",p["texto"])]
            valor=" ".join(p["texto"] for p in usados)
        else:
            usados=[p for p in fila if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}",p["texto"])]
            valor=" ".join(p["texto"] for p in usados)
        if not usados: continue
        valor=re.sub(r"\s+"," ",valor).strip(" -_.,:;")
        # Quitar residuos OCR muy cortos que no son conectores habituales.
        partes=valor.split()
        conectores={"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "SANTA"}
        partes=[p for p in partes if len(p) >= 3 or p.upper() in conectores]
        valor=" ".join(partes)
        if not valor: continue
        # Evitar etiquetas confundidas con valores.
        if normalizar(valor) in {"nombre", "nombres", "primer apellido", "segundo apellido",
                                 "sexo", "fecha de nacimiento", "lugar de nacimiento", "nacionalidad"}:
            continue
        conf=float(np.mean([p["confianza"] for p in usados]))
        # La distancia vertical y la alineación dentro de la celda ponderan.
        score=0.55*(1-min(delta/max_delta,1))+0.45*(conf/100)
        candidatos.append((score,delta,valor,usados))
    if not candidatos: return None
    candidatos.sort(key=lambda z:(z[0],-z[1]),reverse=True)
    score,delta,valor,usados=candidatos[0]
    if campo=="fecha_nacimiento":
        # Formato uniforme DD/MM/AAAA, incluso cuando el acta escribe el mes.
        valor=_fecha_es_a_formato(valor) or valor.replace("-","/")
    if campo in ("nombre","primer_apellido","segundo_apellido","sexo","nacionalidad"):
        valor=valor.upper()
    x1=min(p["x"] for p in usados); y1=min(p["y"] for p in usados)
    x2=max(p["x"]+p["w"] for p in usados); y2=max(p["y"]+p["h"] for p in usados)
    return {
        "valor":valor,"confianza":round(float(np.mean([p["confianza"] for p in usados])),2),
        "metodo":"v9_fila_celda_semantica","puntuacion_asociacion":round(score,3),
        "distancia_etiqueta_valor":round(delta,1),
        "geometria_valor":{"x":x1,"y":y1,"w":x2-x1,"h":y2-y1},
        "geometria_etiqueta":{"x":etiqueta["x"],"y":etiqueta["y"],"w":etiqueta["w"],"h":etiqueta["h"]},
        "validacion_humana":"pendiente","estado":"requiere_confirmacion"
    }


def extraer_personales_v8(palabras, ancho_pagina, alto_pagina, carpeta_evidencias=None, imagen=None):
    """Extrae persona registrada y filiación por bandas de etiquetas y columnas."""
    lineas=_lineas_etiquetas_v8(palabras)
    salida={}
    definiciones={
        "nombre":(["nombre(s)","nombres"],"persona_nombre"),
        "primer_apellido":(["primer apellido","primerapellido"],"persona_apellido1"),
        "segundo_apellido":(["segundo apellido","segundoapellido"],"persona_apellido2"),
        "sexo":(["sexo"],"persona_sexo"),
        "fecha_nacimiento":(["fecha de nacimiento","fechadenacimiento"],"persona_fecha"),
        "lugar_nacimiento":(["lugar de nacimiento","lugardenacimiento"],"persona_lugar"),
        "nacionalidad":(["nacionalidad"],"filiacion_nacionalidad")
    }
    etiquetas={campo:_hallar_etiquetas_v8(lineas,aliases,0.74) for campo,(aliases,_) in definiciones.items()}
    # Delimitar las secciones con sus encabezados; evita confundir el texto
    # superior "Número de Certificado de Nacimiento" con etiquetas personales.
    y_persona=0.0; y_filiacion=float(alto_pagina)
    for linea in lineas:
        norm=linea.get("texto_norm","")
        if "datos de la persona registrada" in norm:
            y_persona=linea["y"]+linea["h"]
        if "datos de filiacion de la persona registrada" in norm or "datos de filiacion" in norm:
            y_filiacion=min(y_filiacion,linea["y"])
    if y_persona==0.0:
        y_persona=alto_pagina*0.27
    if y_filiacion==alto_pagina:
        y_filiacion=alto_pagina*0.43
    for campo in ("nombre","primer_apellido","segundo_apellido","sexo","fecha_nacimiento","lugar_nacimiento"):
        etiquetas[campo]=[e for e in etiquetas[campo] if y_persona < e["cy"] < y_filiacion]
    # Solo aceptar nacionalidad dentro de la sección de la persona registrada.
    # Las etiquetas posteriores al encabezado de filiación corresponden a los padres.
    etiquetas["nacionalidad"]=[e for e in etiquetas["nacionalidad"] if y_persona < e["cy"] < y_filiacion]

    # Persona registrada: primera aparición de Nombre(s), sexo/fecha/lugar.
    grupos=[]
    for campo in ("nombre","primer_apellido","segundo_apellido"):
        if etiquetas[campo]:
            e=etiquetas[campo][0]
            existente=next((g for g in grupos if abs(g[0]["cy"]-e["cy"])<32),None)
            if existente is None: grupos.append([e])
            else: existente.append(e)
    # Completar las etiquetas del primer renglón con el primer match de cada tipo.
    fila_nombre=sorted([etiquetas[c][0] for c in ("nombre","primer_apellido","segundo_apellido") if etiquetas[c]],key=lambda z:z["cx"])
    for campo in ("nombre","primer_apellido","segundo_apellido"):
        if etiquetas[campo] and fila_nombre:
            dato=_extraer_valor_celda_v8(palabras,etiquetas[campo][0],fila_nombre,campo,ancho_pagina,alto_pagina,95)
            if dato: salida[campo]=dato

    fila_datos=[]
    for campo in ("sexo","fecha_nacimiento","lugar_nacimiento"):
        if etiquetas[campo]: fila_datos.append(etiquetas[campo][0])
    fila_datos=sorted(fila_datos,key=lambda z:z["cx"])
    for campo in ("sexo","fecha_nacimiento","lugar_nacimiento"):
        if etiquetas[campo] and fila_datos:
            dato=_extraer_valor_celda_v8(palabras,etiquetas[campo][0],fila_datos,campo,ancho_pagina,alto_pagina,100)
            if dato: salida[campo]=dato

    # Nacionalidad: solo se extrae si la etiqueta está dentro de la sección
    # de la persona registrada. Nunca heredar nacionalidad de madre/padre.
    if etiquetas["nacionalidad"]:
        e=etiquetas["nacionalidad"][0]
        dato=_extraer_valor_celda_v8(palabras,e,[e],"nacionalidad",ancho_pagina,alto_pagina,100)
        if dato: salida["nacionalidad"]=dato

    # Evidencia visual independiente por campo: crop original + caja detectada.
    if carpeta_evidencias is not None and imagen is not None:
        evdir=Path(carpeta_evidencias)/"evidencias_v15"
        evdir.mkdir(parents=True,exist_ok=True)
        for campo,dato in salida.items():
            g=dato.get("geometria_valor")
            if not g: continue
            x,y,w,h=(g[k] for k in ("x","y","w","h"))
            pad_x=max(18,int(w*.18)); pad_y=max(18,int(h*.8))
            x1=max(0,x-pad_x); y1=max(0,y-pad_y)
            x2=min(imagen.shape[1],x+w+pad_x); y2=min(imagen.shape[0],y+h+pad_y)
            crop=imagen[y1:y2,x1:x2]
            if crop.size:
                cv2.imwrite(str(evdir/f"{campo}.png"),crop)
        overlay=cv2.cvtColor(imagen,cv2.COLOR_GRAY2BGR)
        for campo,dato in salida.items():
            g=dato.get("geometria_valor")
            if g:
                x,y,w,h=(g[k] for k in ("x","y","w","h"))
                cv2.rectangle(overlay,(x,y),(x+w,y+h),(0,0,255),2)
                cv2.putText(overlay,campo,(x,max(20,y-8)),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,0,255),1,cv2.LINE_AA)
        cv2.imwrite(str(evdir/"pagina_001_campos_v15.png"),overlay)
    return salida


# ---------------- PROCESAMIENTO ----------------


def extraer_filiacion_v20(palabras, ancho_pagina, alto_pagina):
    """
    Extrae filas de filiación sin mezclarlas con la persona registrada.
    No asigna padre/madre: el formato muestreado no identifica el sexo
    de cada renglón mediante una etiqueta explícita.
    """
    lineas = _lineas_etiquetas_v8(palabras)
    y_filiacion = None
    for linea in lineas:
        norm = linea.get("texto_norm", "")
        if "datos de filiacion de la persona registrada" in norm or "datos de filiacion" in norm:
            y_filiacion = linea["y"] + linea["h"]
            break
    if y_filiacion is None:
        return {"estado": "seccion_no_detectada", "registros": [], "nota": "No se localizó el encabezado de filiación."}

    definiciones = {
        "nombre": ["nombre(s)", "nombres"],
        "primer_apellido": ["primer apellido", "primerapellido"],
        "segundo_apellido": ["segundo apellido", "segundoapellido"],
        "nacionalidad": ["nacionalidad"],
        "curp": ["curp", "clave unica de registro de poblacion"]
    }
    etiquetas = {}
    for campo, aliases in definiciones.items():
        etiquetas[campo] = [
            e for e in _hallar_etiquetas_v8(lineas, aliases, 0.72)
            if e["cy"] > y_filiacion
        ]

    # Agrupar etiquetas que pertenecen al mismo renglón físico.
    todas = [(campo, e) for campo, lista in etiquetas.items() for e in lista]
    filas = []
    for campo, e in sorted(todas, key=lambda z: z[1]["cy"]):
        destino = next((f for f in filas if abs(float(np.median([q[1]["cy"] for q in f])) - e["cy"]) < 34), None)
        if destino is None:
            destino = []
            filas.append(destino)
        destino.append((campo, e))

    registros = []
    for numero, fila in enumerate(sorted(filas, key=lambda f: float(np.median([q[1]["cy"] for q in f]))), start=1):
        fila = sorted(fila, key=lambda z: z[1]["cx"])
        # Evitar duplicados de la misma etiqueta dentro de un renglón.
        fila_unica = []
        vistos = set()
        for campo, e in fila:
            if campo not in vistos:
                fila_unica.append((campo, e)); vistos.add(campo)
        if len(fila_unica) < 2:
            continue
        palabras_registro = {}
        campos_fila = [e for _, e in fila_unica]
        for campo, etiqueta in fila_unica:
            dato = _extraer_valor_celda_v8(
                palabras, etiqueta, campos_fila, campo,
                ancho_pagina, alto_pagina, max_delta=110
            )
            if dato and dato.get("valor"):
                # CURP: no conservar fragmentos OCR que no cumplan 18 caracteres.
                if campo == "curp":
                    curp_limpia = re.sub(r"[^A-Z0-9]", "", dato["valor"].upper())
                    if not re.fullmatch(r"[A-Z]{4}[0-9]{6}[HM][A-Z]{5}[0-9A-Z]{2}", curp_limpia):
                        continue
                    dato["valor"] = curp_limpia
                # En la muestra, "ENG" aparece como residuo de la marca de agua,
                # no como parte del nombre; se elimina solo como prefijo aislado.
                if campo == "nombre":
                    dato["valor"] = re.sub(r"^ENG\s+(?=[A-ZÁÉÍÓÚÑ]{2,})", "", dato["valor"].upper()).strip()
                    if not dato["valor"]:
                        continue
                palabras_registro[campo] = dato
        if any(k in palabras_registro for k in ("nombre", "primer_apellido", "segundo_apellido")):
            registros.append({
                "orden_en_documento": numero,
                "identidad_parental": None,
                "campos": palabras_registro,
                "estado": "requiere_confirmacion_humana"
            })

    if not registros:
        return {
            "estado": "seccion_detectada_sin_datos_recuperables",
            "registros": [],
            "nota": "Se detectó filiación, pero no se recuperaron valores con asociación espacial suficiente."
        }
    return {
        "estado": "datos_recuperados_pendientes_de_revision",
        "registros": registros,
        "nota": "Los renglones se conservan en el orden del documento. No se asignan a padre o madre sin evidencia explícita."
    }


def procesar(ruta, poppler_path=None):
    paginas = cargar_paginas(ruta, poppler_path)
    nombre = Path(ruta).stem
    carpeta = SALIDA / nombre
    carpeta.mkdir(parents=True, exist_ok=True)

    paginas_resultado = []
    todas_palabras = []
    todas_palabras_v8 = []
    todas_celdas = []
    campos_registro_v8 = {}
    # V19: conservar las imágenes preparadas para no repetir OpenCV por página.
    paginas_preparadas = {}

    for numero, pagina in enumerate(paginas, start=1):
        print(f"\nProcesando página {numero}...")
        gris, mejorada = preparar(pagina)
        corregida, angulo = corregir_inclinacion(mejorada)
        paginas_preparadas[numero] = {"gris": gris, "corregida": corregida}

        # Dos modos complementarios: texto disperso y bloques uniformes.
        p11 = ocr_pagina_config(corregida, numero, 11)
        # V8 usa PSM6 sobre gris sin CLAHE: preserva trazos finos en datos personales.
        p6_v8 = ocr_pagina_config(gris, numero, 6)
        palabras = combinar_palabras_ocr(p11, p6_v8)
        todas_palabras_v8.extend(p6_v8)
        # V8 evita el barrido local masivo de V7: los campos personales se
        # releen en regiones semánticas y los registrales usan OCR/tablas.
        extras_locales = []
        lineas = lineas_geometricas(palabras)

        # V19: extractor registral principal. Los extractores alternativos
        # solo se ejecutan si faltan campos, evitando tres lecturas completas.
        registro_pagina, rejilla = extraer_registro_v8(gris, p6_v8, numero, carpeta)
        campos_tabla = ("oficialia", "fecha_registro", "libro", "numero_acta")
        faltantes = [c for c in campos_tabla if not registro_pagina.get(c, {}).get("valor")]
        if faltantes:
            registro_v14 = extraer_registro_v14(gris, palabras, numero)
            for campo in faltantes:
                if registro_v14.get(campo, {}).get("valor"):
                    registro_pagina[campo] = registro_v14[campo]
            faltantes = [c for c in campos_tabla if not registro_pagina.get(c, {}).get("valor")]
        if faltantes:
            registro_v15 = extraer_registro_v15(gris, numero)
            for campo in faltantes:
                if registro_v15.get(campo, {}).get("valor"):
                    registro_pagina[campo] = registro_v15[campo]
        if numero == 1:
            campos_registro_v8 = registro_pagina
        else:
            campos_registro_v8.update(registro_pagina)
        celdas_leidas = []
        todas_palabras.extend(palabras)

        evidencia = cv2.cvtColor(corregida, cv2.COLOR_GRAY2BGR)
        for p in palabras:
            x, y, w, h = p["x"], p["y"], p["w"], p["h"]
            cv2.rectangle(evidencia, (x, y), (x+w, y+h), (0, 0, 255), 1)
        cv2.imwrite(str(carpeta / f"pagina_{numero:03d}_ocr_v15.png"), evidencia)
        cv2.imwrite(str(carpeta / f"pagina_{numero:03d}_rejilla_v15.png"), rejilla)

        paginas_resultado.append({
            "pagina": numero,
            "angulo_corregido": round(angulo, 3),
            "palabras_ocr": len(palabras),
            "lineas_geometricas": len(lineas),
            "celdas_detectadas": len(celdas_leidas),
            "lineas": lineas,
            "celdas": celdas_leidas
        })

    todas_lineas = []
    for p in paginas_resultado:
        todas_lineas.extend(p["lineas"])

    # Se conserva el extractor V7 para los campos registrales y patrones.
    campos_extraidos = extraer_por_secciones_v5(todas_lineas, todas_celdas)
    campos_extraidos.update(campos_registro_v8)
    patrones = extraer_patrones_v5(todas_lineas)
    patrones = adjuntar_evidencia_patrones(patrones, todas_lineas)
    # V8 vuelve a leer los campos personales por celdas semánticas.
    # Se procesa cada página para mantener sus coordenadas y evidencias.
    campos_personales_v8 = {}
    filiacion_v20 = {"estado": "no_procesada", "registros": []}
    curp_v16 = None
    for idx, pagina in enumerate(paginas, start=1):
        # V19 reutiliza la preparación hecha en el primer recorrido.
        gris_v8 = paginas_preparadas[idx]["gris"]
        corregida_v8 = paginas_preparadas[idx]["corregida"]
        palabras_pagina = [p for p in todas_palabras_v8 if p.get("pagina") == idx]
        nuevos = extraer_personales_v8(
            palabras_pagina, corregida_v8.shape[1], corregida_v8.shape[0],
            carpeta_evidencias=carpeta, imagen=gris_v8
        )
        campos_personales_v8.update(nuevos)
        # V20: extractor independiente de filiación; reutiliza tokens PSM6 existentes.
        filiacion_pagina = extraer_filiacion_v20(
            palabras_pagina, corregida_v8.shape[1], corregida_v8.shape[0]
        )
        if filiacion_pagina.get("registros"):
            for reg in filiacion_pagina["registros"]:
                reg["pagina"] = idx
                reg["orden_global"] = len(filiacion_v20["registros"]) + 1
                filiacion_v20["registros"].append(reg)
            filiacion_v20["estado"] = "datos_recuperados_pendientes_de_revision"
        elif filiacion_v20["estado"] == "no_procesada":
            filiacion_v20 = filiacion_pagina
        fecha_ref = campos_personales_v8.get("fecha_nacimiento", {}).get("valor")
        # La relectura local de CURP solo se intenta si el OCR general no la halló.
        curp_local = None
        if not patrones.get("curp"):
            curp_local = extraer_curp_v16(gris_v8, palabras_pagina, idx, fecha_ref)
        if curp_local and (curp_v16 is None or (curp_local.get("confianza") or 0) > (curp_v16.get("confianza") or 0)):
            curp_v16 = curp_local
        # V19 usa la etiqueta detectada y las cajas OCR existentes para
        # extraer solo la columna del lugar de nacimiento, sin repetir Tesseract.
        lugar_v19 = extraer_lugar_nacimiento_v19(
            palabras_pagina, corregida_v8.shape[1], corregida_v8.shape[0], idx
        )
        if lugar_v19:
            campos_personales_v8["lugar_nacimiento"] = lugar_v19

    # V16 prioriza la lectura local de CURP; conserva la lectura general como alternativa.
    if curp_v16:
        anterior_curp = patrones.get("curp", [])
        curp_v16["alternativas"] = list(curp_v16.get("alternativas", [])) + [
            {"valor": c.get("valor"), "motivo": "lectura OCR general V15"}
            for c in anterior_curp if c.get("valor") != curp_v16.get("valor")
        ]
        patrones["curp"] = [curp_v16]
    # V17: conserva la lectura OCR de CURP y agrega una alternativa O/0
    # únicamente en la posición 17 cuando la fecha de nacimiento es anterior
    # a 2000. No se reemplaza el carácter automáticamente.
    curp_candidatos_v17 = patrones.get("curp", [])
    if curp_candidatos_v17:
        for candidato in curp_candidatos_v17:
            raw = re.sub(r"[^A-Z0-9]", "", str(candidato.get("valor", "")).upper())
            fecha_txt = campos_personales_v8.get("fecha_nacimiento", {}).get("valor", "")
            try:
                from datetime import datetime
                fecha_obj = datetime.strptime(fecha_txt, "%d/%m/%Y") if fecha_txt else None
            except (ValueError, TypeError):
                fecha_obj = None
            if len(raw) == 18 and raw[16] in ("O", "0") and fecha_obj and fecha_obj.year < 2000:
                sugerida = raw[:16] + ("0" if raw[16] == "O" else "O") + raw[17:]
                alts = candidato.setdefault("alternativas", [])
                if not any(a.get("valor") == sugerida for a in alts if isinstance(a, dict)):
                    alts.append({
                        "valor": sugerida,
                        "motivo": "Alternativa O/0 en posición 17; verificar visualmente contra el documento"
                    })
                candidato["nota_revision"] = "Existe ambigüedad O/0 en posición 17; no se corrigió automáticamente"

    # El diseño de esta acta muestra 'Número de Certificado de Nacimiento',
    # no una etiqueta FOLIO. No se reutiliza ese número como folio.
    if "folio" not in campos_registro_v8:
        campos_registro_v8["folio"] = {
            "valor": None, "confianza": None, "metodo": "v17_sin_etiqueta_folio",
            "formato_valido": False,
            "detalle_validacion": "No se encontró etiqueta FOLIO asociada a un valor; el número de certificado no se interpreta como folio",
            "validacion_humana": "pendiente", "estado": "captura_manual", "alternativas": []
        }
        campos_extraidos["folio"] = campos_registro_v8["folio"]

    # Mantener siempre el esquema esperado, incluso cuando requiera captura manual.
    campos_requeridos = [
        "oficialia", "fecha_registro", "libro", "numero_acta",
        "nombre", "primer_apellido", "segundo_apellido",
        "fecha_nacimiento", "sexo", "lugar_nacimiento", "nacionalidad",
        "folio", "curp", "identificador_electronico", "codigo_verificacion"
    ]
    campos_finales = {}
    for campo in campos_requeridos:
        if campo in patrones and patrones[campo]:
            opciones = patrones[campo]
            principal = opciones[0]
            campos_finales[campo] = {
                **principal,
                "alternativas": list(principal.get("alternativas", [])) + [
                    o for o in opciones[1:] if o not in principal.get("alternativas", [])
                ],
                "formato_valido": True,
                "detalle_validacion": "Coincide con patrón; evidencia OCR y asociación espacial disponibles cuando fueron localizadas",
                "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion"
            }
        elif campo in campos_personales_v8 and campo in (
            "nombre", "primer_apellido", "segundo_apellido", "fecha_nacimiento",
            "sexo", "lugar_nacimiento", "nacionalidad"
        ):
            dato = campos_personales_v8[campo]
            ok, detalle = validar_formato(campo, dato["valor"])
            campos_finales[campo] = {
                **dato, "formato_valido": ok, "detalle_validacion": detalle,
                "alternativas": [], "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion" if ok else "captura_manual"
            }
        elif campo in campos_extraidos and campo not in (
            "nombre", "primer_apellido", "segundo_apellido", "fecha_nacimiento",
            "sexo", "lugar_nacimiento", "nacionalidad"
        ):
            dato = campos_extraidos[campo]
            ok, detalle = validar_formato(campo, dato["valor"])
            campos_finales[campo] = {
                **dato, "formato_valido": ok,
                "detalle_validacion": detalle,
                "alternativas": [],
                "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion" if ok else "captura_manual"
            }
        else:
            detalle = "No se encontró una asociación estructural confiable"
            if campo == "nacionalidad":
                detalle = (
                    "No hay etiqueta de nacionalidad dentro de Datos de la Persona Registrada; "
                    "no se infiere de la nacionalidad de madre o padre"
                )
            campos_finales[campo] = {
                "valor": None, "confianza": 0,
                "metodo": "no_identificado",
                "formato_valido": False,
                "detalle_validacion": detalle,
                "validacion_humana": "pendiente",
                "estado": "captura_manual", "alternativas": []
            }

    # Auditoría de coherencia: nunca modifica ni sustituye valores OCR.
    validaciones_cruzadas = []
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
        "version_motor": "20.0",
        "estrategia": [
            "v18_reutilizacion_de_imagenes_preparadas_por_pagina",
            "v19_lugar_nacimiento_anclado_a_etiqueta_y_columna",
            "v19_reutiliza_cajas_ocr_existentes_sin_llamada_tesseract_adicional",
            "v18_extractores_registrales_alternativos_solo_si_faltan_campos",
            "v18_curp_local_solo_si_ocr_general_no_la_detecta",
            "v17_alternativas_curp_O_0_sin_autocorreccion",
            "v17_ocr_registro_multipsm_confianza_solo_tokens_positivos",
            "v17_folio_sin_inferir_numero_certificado",
            "v16_ocr_local_curp_anclado_a_etiqueta_con_alternativas", 
            "v16_confianza_celdas_con_reintento_psm_6_y_sin_confianza_fabricada",
            "ocr_complementario_psm_11_y_psm_6",
            "v13_fechas_numericas_y_escritas_en_espanol",
            "v15_tabla_registral_por_encabezados_y_ocr_por_celda",
            "v15_lugar_nacimiento_multilinea_por_columna",
            "v13_filtro_de_residuos_ocr_en_campos_textuales",
            "v13_revision_humana_obligatoria_sin_inferencia_de_datos",
            "v8_extraccion_por_filas_y_celdas_semanticas",
            "v9_limites_de_columna_dinamicos_sin_coordenada_horizontal_fija",
            "v10_auditoria_de_coherencia_entre_campos",
            "v11_identificador_electronico_anclado_a_etiqueta",
            "v11_codigo_verificacion_independiente",
            "v13_evidencia_geometrica_para_curp_y_codigos",
            "v13_confianza_ocr_propagada_desde_tokens",
            "v13_reporte_de_revision_humana_separado",
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
            "v20_extraccion_independiente_de_filiacion_por_filas_y_columnas",
            "filiacion_sin_asignacion_padre_madre_por_inferencia",
            "revision_humana_obligatoria"
        ],
        "campos": campos_finales,
        "secciones": {
            "persona_registrada": ["nombre", "primer_apellido", "segundo_apellido", "fecha_nacimiento", "sexo", "lugar_nacimiento", "nacionalidad"],
            "datos_registrales": ["oficialia", "fecha_registro", "libro", "numero_acta", "folio"],
            "identificadores": ["curp", "identificador_electronico", "codigo_verificacion"],
            "filiacion": filiacion_v20
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

    archivo_json = carpeta / "resultado_ocr_v20.json"
    archivo_json.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    # Plantilla de cotejo: no confirma campos ni modifica los valores OCR.
    archivo_revision = carpeta / "reporte_revision_humana_v20.csv"
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

    print("\n========== RESULTADO V20 ==========")
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
        description="Lector inteligente de actas mexicanas V17"
    )
    parser.add_argument("documento", help="Ruta de PDF o imagen")
    parser.add_argument(
        "--poppler",
        default=None,
        help="Ruta opcional a la carpeta bin de Poppler"
    )
    args = parser.parse_args()
    procesar(args.documento, args.poppler)
