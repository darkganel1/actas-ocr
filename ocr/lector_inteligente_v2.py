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