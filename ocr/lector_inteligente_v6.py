"""
archivo-actas | Lector inteligente V5
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
    """CURP e identificador por patrón; el folio se resuelve por su etiqueta."""
    texto = "\n".join(l["texto"] for l in lineas)
    resultados = {}
    for campo in ("curp", "identificador_electronico"):
        patron = PATRONES[campo]
        encontrados = []
        for m in patron.finditer(texto):
            valor = m.group(0).upper()
            encontrados.append({
                "valor": valor, "confianza": None, "metodo": "patron_regex",
                "validacion_humana": "pendiente"
            })
        resultados[campo] = encontrados
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
        dato = _candidatos_misma_columna_v6(ls, e, campo, direccion, 3.8)
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
        dato = _candidatos_misma_columna_v6(ls, e, "folio", "abajo", 4.0)
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
            dato = _candidatos_misma_columna_v6(bloque, e, campo, "arriba", 5.0)
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
                dato = _candidatos_misma_columna_v6(ls, e, "nacionalidad", "arriba", 4.5)
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



# ---------------- PROCESAMIENTO ----------------

def procesar(ruta, poppler_path=None):
    paginas = cargar_paginas(ruta, poppler_path)
    nombre = Path(ruta).stem
    carpeta = SALIDA / nombre
    carpeta.mkdir(parents=True, exist_ok=True)

    paginas_resultado = []
    todas_palabras = []
    todas_celdas = []

    for numero, pagina in enumerate(paginas, start=1):
        print(f"\nProcesando página {numero}...")
        gris, mejorada = preparar(pagina)
        corregida, angulo = corregir_inclinacion(mejorada)

        # Dos modos complementarios: texto disperso y bloques uniformes.
        p11 = ocr_pagina_config(corregida, numero, 11)
        p6 = ocr_pagina_config(corregida, numero, 6)
        palabras = combinar_palabras_ocr(p11, p6)
        lineas = lineas_geometricas(palabras)

        celdas, rejilla = detectar_celdas_tabla(corregida)
        celdas_leidas = leer_celdas(corregida, celdas)
        todas_celdas.extend([{**c, 'pagina': numero} for c in celdas_leidas])

        todas_palabras.extend(palabras)

        evidencia = cv2.cvtColor(corregida, cv2.COLOR_GRAY2BGR)
        for p in palabras:
            x, y, w, h = p["x"], p["y"], p["w"], p["h"]
            cv2.rectangle(evidencia, (x, y), (x+w, y+h), (0, 0, 255), 1)
        cv2.imwrite(str(carpeta / f"pagina_{numero:03d}_ocr_v6.png"), evidencia)
        cv2.imwrite(str(carpeta / f"pagina_{numero:03d}_rejilla_v6.png"), rejilla)

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

    campos_extraidos = extraer_por_secciones_v5(todas_lineas, todas_celdas)
    patrones = extraer_patrones_v5(todas_lineas)

    # Mantener siempre el esquema esperado, incluso cuando requiera captura manual.
    campos_requeridos = [
        "oficialia", "fecha_registro", "libro", "numero_acta",
        "nombre", "primer_apellido", "segundo_apellido",
        "fecha_nacimiento", "sexo", "lugar_nacimiento", "nacionalidad",
        "folio", "curp", "identificador_electronico"
    ]
    campos_finales = {}
    for campo in campos_requeridos:
        if campo in patrones and patrones[campo]:
            opciones = patrones[campo]
            campos_finales[campo] = {
                "valor": opciones[0]["valor"], "confianza": None,
                "metodo": "patron_regex", "alternativas": opciones[1:],
                "formato_valido": True,
                "detalle_validacion": "Coincide con patrón; requiere cotejo visual",
                "validacion_humana": "pendiente",
                "estado": "requiere_confirmacion"
            }
        elif campo in campos_extraidos:
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
            campos_finales[campo] = {
                "valor": None, "confianza": 0,
                "metodo": "no_identificado",
                "formato_valido": False,
                "detalle_validacion": "No se encontró una asociación estructural confiable",
                "validacion_humana": "pendiente",
                "estado": "captura_manual", "alternativas": []
            }

    # Nacionalidad solo aparece en la sección de filiación en este formato.
    # No se asigna automáticamente a la persona registrada.
    salida = {
        "documento": nombre,
        "paginas": len(paginas),
        "version_motor": "6.0",
        "estrategia": [
            "ocr_complementario_psm_11_y_psm_6",
            "reconstruccion_de_filas_por_geometria_local_v6",
            "asociacion_etiqueta_valor_por_columna_y_distancia_relativa_v6",
            "separacion_dinamica_persona_y_filiacion_v6",
            "agrupacion_geometrica_de_palabras",
            "delimitacion_de_secciones_por_encabezados",
            "asociacion_por_columna_y_fila_dinamica",
            "folio_asociado_a_su_etiqueta",
            "curp_e_identificador_por_patrones",
            "revision_humana_obligatoria"
        ],
        "campos": campos_finales,
        "resultado_paginas": paginas_resultado,
        "estado_expediente": "pendiente_revision_humana"
    }

    archivo_json = carpeta / "resultado_ocr_v6.json"
    archivo_json.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n========== RESULTADO V6 ==========")
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
        description="Lector inteligente de actas mexicanas V6"
    )
    parser.add_argument("documento", help="Ruta de PDF o imagen")
    parser.add_argument(
        "--poppler",
        default=None,
        help="Ruta opcional a la carpeta bin de Poppler"
    )
    args = parser.parse_args()
    procesar(args.documento, args.poppler)
