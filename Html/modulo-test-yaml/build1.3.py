#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py · Inyector de datos YAML → HTML madre · v1.3
Observatorio del laicismo · Castilla y León
=================================================
Uso:
    python build.py                 # valida y genera el informe
    python build.py --check         # solo valida, sin escribir
    python build.py --yaml yaml --html Madre-v3.0.html --out Informe-vigilancia.html

Entradas (carpeta yaml/, todas opcionales):
    Los archivos se clasifican por el comienzo de su nombre, sin distinguir
    mayúsculas; se admiten varios archivos por colección. Por ejemplo:
    Eje2-2026-test.yaml → eje2, Capellanias-2026-test.yaml → capellanias.
    Se reconocen eje1–eje4, capellanias, educacion y convenios.

El YAML es la fuente de verdad: IDs nacen ahí (CYL-AAAA-COL-NNNN,
mayúsculas, contador independiente por colección+año) y nunca se
renumeran. El HTML y cualquier CSV de verificación son productos de
compilación.

Regla de estado: el campo `estado` viaja literal desde el YAML.
El build SOLO lo modifica en caso de deduplicación detectada:
  · ejes 2/3, clave provincia+origen+destino+cantidad con fecha igual
    y distinto id → pending en ambas filas + nota cruzada automática.
  · capellanías/educación, clave provincia+subtipo/partida+periodo+
    destino dos veces → pending en ambas + nota (renovación = periodo
    distinto; mismo periodo mismo destino es anomalía).
La detección SIEMPRE ocurre antes de construir reportes/flujos, para
que las mutaciones lleguen al informe. La resolución es manual.

El motor y el diseño del HTML quedan intactos: los literales JS se
inyectan entre los marcadores /*__DATOS__*/ y /*__FIN_DATOS__*/.
Requiere PyYAML:  pip install pyyaml

Registro de revisiones:
  v1 (yaml) — adaptación inicial desde CSV.
  v1.1 — corrección de cinco defectos (regla $ sin falso error de
     unicidad; deduplicación antes de construir_reportes; cabecera
     consistente solo sobre campos de cabecera; clave de renovación
     con destino; guardián de ``` visible antes del informe).
  v1.2 — migración a vocabulario del Observatorio (esquema v1.3):
     · `programa` deja de codificarse: el motor lo deriva desde `act`
       mediante TABLA_ACT (CF bifurca según el eje del registro).
     · `tipo_e2` deja de codificarse: la capa de inyección lo DERIVA
       del ACT (RES→conservacion; resto en eje 2→turismo) y lo emite
       como propiedad tipoE2 del flujo para compatibilidad con la
       plantilla actual. Es dato de salida, no maestro.
     · enums nuevos: `act` (18 valores TEMAS) y `gru` migrado a las
       siglas del Observatorio (CJ/CI/COR/CB/CH/CRI); los códigos
       retirados (JU/IS/ORT/BU/HI/OC) dan error con pista de migración.
     · `act` y `gru` obligatorios en registros con `cantidad`.
     · ID acepta sufijo provincial (-A, -B, -C…) para piezas
       multiterritoriales (regla M); la numeración se verifica por
       ID base (el sufijo no consume numeración).
  v1.3 — corrección de la v1.2 (borrador defectuoso, nunca publicado):
     (1) sintaxis reparada en flujo_a_literal (f-string roto);
     (2) la agrupación de regla $ vuelve a ser por ID COMPLETO — el
         borrador fundía las provincias multiterritoriales en un solo
         reporte y disparaba falsos errores de cabecera divergente;
     (3) el reporte y el flujo conservan el ID completo con sufijo;
     (4) tipoE2 se EMITE derivado del ACT (la plantilla sigue
         leyéndolo; eliminación diferida a la migración del HTML);
     (5) nueva función validar_multiterritorial: sufijos consecutivos
         desde A, orden alfabético provincia↔letra, cabecera compartida
         (fecha/grupo/link/alcance), prohibición de mezclar base con y
         sin sufijo, camino 2 íntegramente en pending y con marcador;
     (6) aviso de coherencia act↔fichero (RES/CU en eje3; act social
         en eje2);
     (7) el flujo lleva `act` (propiedad adicional, para el futuro
         sub-desglose de Servicios sociales por ACT).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

# ------------------------------------------------------------------ config

CARPETA_YAML = Path("yaml")
HTML_MADRE = Path("Madre-v3.0.html")
MARCA_INI = "/*__DATOS__*/"
MARCA_FIN = "/*__FIN_DATOS__*/"

PROVINCIAS = ["Ávila", "Burgos", "León", "Palencia", "Salamanca",
              "Segovia", "Soria", "Valladolid", "Zamora"]
ORDEN_PROV = {p: i for i, p in enumerate(PROVINCIAS)}

ESTADOS = {"verified", "approx", "pending"}
PROGRAMAS = {"Conservación de patrimonio", "Turismo religioso",
             "Servicios sociales", "Capellanías hospitalarias", "Educación"}
PARTICIPACION = {"organizacion", "intervencion", "asistencia", "protocolo"}
SUBTIPOS = {"sanitaria", "militar"}
PARTIDAS = {"profesorado", "concierto"}

# GRU — enum del Observatorio (v1.2+). Códigos retirados de la era CSV:
# JU→CJ, IS→CI, ORT→COR, BU→CB, HI→CH, OC→Z.
GRUS = {"ID", "OR", "EC", "MIX", "CRI", "EV", "COR", "CJ", "CI", "CB", "CH", "Z"}
GRUS_RETIRADOS = {"JU": "CJ", "IS": "CI", "ORT": "COR",
                  "BU": "CB", "HI": "CH", "OC": "Z"}

# ACT — enum del Observatorio (TEMAS, 18 valores)
ACTS = {"ED", "UC", "CF", "IC", "HC", "CU", "RES", "FUN", "AS",
        "ASD", "ASE", "ASI", "ASJ", "ASM", "ASR", "AST", "DEP", "Z"}

# id: CYL-AAAA-COL-NNNN · mayúsculas · sufijo provincial opcional (-A…-Z)
# para piezas multiterritoriales (regla M). El sufijo NO consume numeración.
PATRON_ID = re.compile(r"^CYL-(\d{4})-(E[1-4]|CAP|EDU|CON)-(\d{4})(-[A-Z])?$")

PATRON_ORIGEN = re.compile(
    r"^(Junta|M\. |Ministerio|Ayuntamiento de |Diputación de |Comarca)")
FECHA_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4}"
    r"|\d{2}/\d{2}/\d{4}\?"
    r"|\[\d{2}-\d{2}\]/\d{2}/\d{4}"
    r"|\[\d{2}/\d{4}\])$")

# Campos obligatorios por colección (todos los demás, opcionales)
# v1.2+: eje2/eje3 no llevan `programa` (derivado); `act` es obligatorio
# como cabecera temática, exigido además junto a `gru` si hay cantidad.
OBLIGATORIOS = {
    "eje1": ["id", "fecha", "titular", "provincia", "fuente", "estado",
             "grupo", "autoridad", "participacion"],
    "eje2": ["id", "fecha", "titular", "provincia", "fuente", "estado",
             "grupo"],
    "eje3": ["id", "fecha", "titular", "provincia", "fuente", "estado",
             "grupo"],
    "eje4": ["id", "fecha", "titular", "provincia", "fuente", "estado",
             "grupo", "actor", "tema"],
    "capellanias": ["id", "provincia", "subtipo", "periodo", "estado"],
    "educacion": ["id", "provincia", "partida", "periodo", "estado"],
    "convenios": ["id", "provincia", "origen", "destino", "fecha_firma"],
}

# Campos que pertenecen a la LÍNEA ECONÓMICA: pueden variar entre filas
# que comparten id (regla $) y jamás se comparan en la validación de
# cabecera consistente.
CAMPOS_LINEA = {"origen", "destino", "cantidad", "concepto", "gru",
                "edificio"}

# Colecciones que toleran id repetido dentro de sí mismas (regla $).
CON_REGLA_DOLLAR = {"eje2", "eje3"}

# Marcador del camino 2 de la regla M (reparto estimado proporcional)
MARCA_M2 = "desglose estimado proporcional"

# ====================================================================
# TABLA NORMATIVA ACT → macro-programa (derivación del motor)
# CF bifurca: eje 2 → Turismo religioso; eje 3 → Servicios sociales
# ====================================================================
TABLA_ACT = {
    "RES": "Conservación de patrimonio",
    "CU":  "Turismo religioso",
    "CF":  None,                      # bifurca según el eje del registro
    "ED":  "Educación",
    "UC":  "Educación",
    "DEP": "Educación",
    "AS":  "Servicios sociales", "ASD": "Servicios sociales",
    "ASE": "Servicios sociales", "ASI": "Servicios sociales",
    "ASJ": "Servicios sociales", "ASM": "Servicios sociales",
    "ASR": "Servicios sociales", "AST": "Servicios sociales",
    "HC":  "Servicios sociales", "FUN": "Servicios sociales",
    "IC":  "Servicios sociales", "Z":   "Servicios sociales",
}

# ACT esperado por fichero (avisos de coherencia, no errores:
# CF es legítimo en ambos, y la palabra final la tiene el codificador)
ACT_TIPO_EJE2 = {"RES", "CU", "CF", "Z"}
ACT_TIPO_EJE3 = ACTS - {"RES", "CU"}

errores, avisos = [], []
COLECCIONES = ("eje1", "eje2", "eje3", "eje4",
               "capellanias", "educacion", "convenios")


def error(msg):
    errores.append(msg)


def aviso(msg):
    avisos.append(msg)


def id_base(rid):
    """ID sin sufijo provincial: CYL-AAAA-COL-NNNN."""
    m = PATRON_ID.match(rid)
    return (f"CYL-{m.group(1)}-{m.group(2)}-{m.group(3)}"
            if m else rid)


def sufijo_de(rid):
    """Sufijo provincial ('-A', '-B'…) o '' si el ID no lo lleva."""
    m = PATRON_ID.match(rid)
    return m.group(4) or "" if m else ""


def programa_desde_act(act, eje_registro):
    """Deriva el macro-programa desde `act`. CF bifurca según el eje."""
    if act not in TABLA_ACT:
        return None
    prog = TABLA_ACT[act]
    if prog is not None:
        return prog
    if eje_registro == 2:
        return "Turismo religioso"
    if eje_registro == 3:
        return "Servicios sociales"
    return None


# ------------------------------------------------------------------ lectura

def coleccion_de_archivo(ruta):
    """Identifica la colección por el prefijo del nombre del archivo."""
    nombre = ruta.stem.casefold()
    for coleccion in COLECCIONES:
        if nombre == coleccion or any(
                nombre.startswith(coleccion + separador)
                for separador in ("-", "_", " ")):
            return coleccion
    return None


def cargar(rutas):
    """Lee y combina todos los YAML asignados a una colección."""
    filas = []
    for ruta in rutas:
        try:
            with open(ruta, encoding="utf-8") as f:
                datos = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            marca = getattr(exc, "problem_mark", None)
            ubicacion = (f" (línea {marca.line + 1}, "
                         f"columna {marca.column + 1})" if marca else "")
            detalle = getattr(exc, "problem", None) or str(exc).splitlines()[0]
            error(f"{ruta.name}: YAML inválido{ubicacion}: {detalle}")
            continue
        if datos is None:
            continue
        if not isinstance(datos, list) or any(
                not isinstance(d, dict) for d in datos):
            error(f"{ruta.name}: el YAML debe ser una lista plana de registros")
            continue
        filas.extend(datos)
    return filas


def txt(reg, campo):
    """Valor como texto; acepta str, números y ausencia."""
    v = reg.get(campo)
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return str(v).strip()


def entero(v, campo, rid, obligatorio=True):
    """Los importes llegan ya tipados desde YAML; valida el rango de tipos."""
    if v is None:
        if obligatorio:
            error(f"{campo} ausente en {rid}")
        return None
    if isinstance(v, bool):
        error(f"{campo} booleano ({v!r}) en {rid}")
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    error(f"{campo} no entero ({v!r}) en {rid}")
    return None


def lista_tags(v):
    """Acepta tags como 'a|b' (string con barra) o lista nativa."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).split("|") if x.strip()]


# ------------------------------------------------------------- validaciones

def validar_registro(r, coleccion):
    rid = txt(r, "id")
    m = PATRON_ID.match(rid)
    if not m:
        error(f"id mal formado: {rid!r} ({coleccion}) — debe ser "
              f"CYL-AAAA-COL-NNNN en mayúsculas, con sufijo provincial "
              f"opcional (-A, -B, -C…)")
    else:
        col_id = m.group(2)
        if coleccion.startswith("eje"):
            esperado = "E" + coleccion[-1]
        else:
            esperado = coleccion[:3].upper()
        if col_id != esperado:
            error(f"{rid}: prefijo {col_id} no corresponde a {coleccion}")
    for campo in OBLIGATORIOS[coleccion]:
        if not txt(r, campo):
            error(f"{rid}: campo obligatorio vacío o ausente: {campo}")
    if txt(r, "estado") and txt(r, "estado") not in ESTADOS:
        error(f"estado no válido ({r.get('estado')!r}) en {rid}")
    if txt(r, "provincia") and txt(r, "provincia") not in ORDEN_PROV:
        error(f"provincia desconocida ({r.get('provincia')!r}) en {rid}")
    fecha = txt(r, "fecha") or txt(r, "fecha_firma")
    if fecha and not FECHA_RE.match(fecha):
        error(f"fecha mal formada ({fecha!r}) en {rid}")
    if txt(r, "descartado").lower() in ("si", "sí", "true") and \
            not txt(r, "motivo_descarte"):
        error(f"{rid}: descartado sin motivo_descarte")

    # --- enums act / gru (v1.2+)
    act = txt(r, "act")
    if act and act not in ACTS:
        error(f"act no válido ({act!r}) en {rid} — enum de 18 valores "
              "(TEMAS del Observatorio)")
    gru = txt(r, "gru")
    if gru and gru not in GRUS:
        if gru in GRUS_RETIRADOS:
            error(f"gru retirado ({gru!r}) en {rid} — migrar a "
                  f"{GRUS_RETIRADOS[gru]}")
        else:
            error(f"gru no válido ({gru!r}) en {rid}")

    # --- con cantidad: línea económica completa
    if r.get("cantidad") is not None:
        for campo in ("act", "gru", "origen", "destino", "concepto"):
            if not txt(r, campo):
                error(f"{rid}: registro con cantidad pero sin {campo}")

    # --- coherencia act ↔ fichero (aviso: CF bifurca, decide el codificador)
    if act:
        if coleccion == "eje2" and act not in ACT_TIPO_EJE2:
            aviso(f"{rid}: act {act} es típico de eje 3 pero el registro "
                  f"vive en eje2 — comprobar el enrutado")
        if coleccion == "eje3" and act not in ACT_TIPO_EJE3:
            aviso(f"{rid}: act {act} es típico de eje 2 pero el registro "
                  f"vive en eje3 — comprobar el enrutado")
    return rid


def validar_cabecera_consistente(por_id, coleccion):
    """Regla $: filas que comparten id COMPLETO deben tener cabecera
    idéntica. Compara SOLO campos de cabecera; los de línea económica
    quedan excluidos porque varían por diseño entre líneas del mismo
    reporte. Los registros multiterritoriales no entran aquí: cada
    sufijo es un id completo distinto y se validan aparte (regla M)."""
    campos_cab = [c for c in OBLIGATORIOS[coleccion]
                  if c != "id" and c not in CAMPOS_LINEA]
    campos_cab += ["localidad", "link", "tags", "notas", "descartado",
                   "motivo_descarte", "alcance", "fuente_oficial",
                   "admin", "autoridad", "participacion", "actor",
                   "tema", "act"]
    for rid, filas in por_id.items():
        if len(filas) < 2:
            continue
        for campo in set(campos_cab):
            if len({txt(f, campo) for f in filas}) > 1:
                error(f"{rid}: cabecera divergente en {campo!r} entre "
                      f"filas del mismo id (regla $)")


def validar_multiterritorial(colecciones):
    """Regla M — valida los grupos de ID base con sufijo provincial:
    · prohibido mezclar base con y sin sufijo (regla $ vs regla M);
    · sufijos consecutivos desde A, sin letras saltadas ni repetidas;
    · el orden alfabético de provincia corresponde al orden de letras;
    · cabecera compartida: fecha, grupo, link y alcance idénticos en
      todos los registros de la pieza (las notas pueden variar: cada
      provincia lleva su pista de verificación);
    · camino 2 (concepto «desglose estimado proporcional —»): el
      marcador debe estar en TODOS los registros de la pieza y TODOS
      deben estar en estado pending."""
    for coleccion in ("eje1", "eje2", "eje3", "eje4"):
        grupos = {}
        for r in colecciones[coleccion]:
            rid = txt(r, "id")
            if not PATRON_ID.match(rid):
                continue
            grupos.setdefault(id_base(rid), []).append(r)
        for base, filas in grupos.items():
            con_suf = [f for f in filas if sufijo_de(txt(f, "id"))]
            sin_suf = [f for f in filas if not sufijo_de(txt(f, "id"))]
            if not con_suf:
                continue                       # pieza normal (regla $ o única)
            if sin_suf:
                error(f"{base}: mezcla de id con y sin sufijo — la regla $ "
                      f"(id exacto repetido) y la regla M (id base + sufijo "
                      f"provincial) no se combinan; revisar "
                      f"{', '.join(sorted(txt(f, 'id') for f in sin_suf))}")
                continue
            # sufijos consecutivos desde A, sin repetición
            letras = sorted(sufijo_de(txt(f, "id"))[1] for f in filas)
            esperadas = [chr(ord("A") + i) for i in range(len(letras))]
            if letras != esperadas:
                error(f"{base}: sufijos no consecutivos desde A "
                      f"(encontrados: {', '.join('-' + l for l in letras)})")
                continue
            # orden alfabético provincia ↔ letra
            por_letra = sorted(filas,
                               key=lambda f: sufijo_de(txt(f, "id")))
            orden_provincias = [
                ORDEN_PROV.get(txt(f, "provincia"), len(ORDEN_PROV))
                for f in por_letra
            ]
            if orden_provincias != sorted(orden_provincias):
                error(f"{base}: el orden alfabético de provincia no "
                      f"corresponde al orden de los sufijos")
            # cabecera compartida (fecha, grupo, link, alcance)
            for campo in ("fecha", "grupo", "link", "alcance"):
                if len({txt(f, campo) for f in filas}) > 1:
                    error(f"{base}: campo {campo!r} divergente entre "
                          f"registros multiterritoriales (regla M)")
            # camino 2: marcador y pending en todos
            marcadas = [f for f in filas
                        if txt(f, "concepto").startswith(MARCA_M2)]
            if marcadas:
                sin_marca = [txt(f, "id") for f in filas
                             if not txt(f, "concepto").startswith(MARCA_M2)]
                if sin_marca:
                    error(f"{base}: camino 2 de regla M con marcador "
                          f"«{MARCA_M2}» solo en parte de los registros "
                          f"(sin marcador: {', '.join(sin_marca)})")
                no_pend = [txt(f, "id") for f in filas
                           if txt(f, "estado") != "pending"]
                if no_pend:
                    error(f"{base}: camino 2 de regla M debe estar "
                          f"íntegramente en pending (fuera: "
                          f"{', '.join(no_pend)})")


def detectar_duplicados(filas_flujo):
    """Clave (provincia, origen, destino, cantidad) entre ids distintos.
    Misma fecha → pending + nota cruzada en AMBAS filas (aviso, no error).
    Fecha distinta → solo aviso (pago fraccionado posible).
    IMPORTA: se llama ANTES de construir_reportes para que las
    mutaciones (estado, notas) lleguen a reportes y flujos."""
    indice = {}
    for f in filas_flujo:
        if f.get("cantidad") is None:
            continue
        clave = (txt(f, "provincia"), txt(f, "origen"), txt(f, "destino"),
                 f["cantidad"])
        indice.setdefault(clave, []).append(f)
    for clave, grupo in indice.items():
        if len({txt(g, "id") for g in grupo}) < 2:
            continue
        por_fecha = {}
        for g in grupo:
            por_fecha.setdefault(txt(g, "fecha"), []).append(g)
        for fecha, fs in por_fecha.items():
            if len({txt(x, "id") for x in fs}) < 2:
                continue
            for f in fs:
                otros = sorted({txt(x, "id") for x in fs
                               if txt(x, "id") != txt(f, "id")})
                f["estado"] = "pending"
                nota = ("Posible duplicación con " + ", ".join(otros) +
                        " (misma fecha, importe, origen y destino) — "
                        "verificar y corregir a mano.")
                f["notas"] = (txt(f, "notas") + " | " + nota
                              if txt(f, "notas") else nota)
            aviso(f"Duplicado sospechoso {clave[0]} · {clave[1]} → "
                  f"{clave[2]} · {clave[3]} € · {fecha}: marcados pending "
                  + "/".join(sorted({txt(x, 'id') for x in fs}))
                  + " — computarán en sumas cuando se verifique a mano")


def detectar_duplicados_periodo(filas, campo_clave, etiqueta):
    """Capellanías y educación: clave natural provincia+clave+periodo+
    destino (el destino distingue capellanías legítimas del mismo
    subtipo y periodo: varios hospitales de una provincia).
    Renovación = periodo distinto → registro nuevo legítimo."""
    indice = {}
    for f in filas:
        clave = (txt(f, "provincia"), txt(f, campo_clave),
                 txt(f, "periodo"), txt(f, "destino"))
        indice.setdefault(clave, []).append(f)
    for clave, grupo in indice.items():
        ids = sorted({txt(g, "id") for g in grupo})
        if len(ids) < 2:
            continue
        for f in grupo:
            otros = [x for x in ids if x != txt(f, "id")]
            f["estado"] = "pending"
            nota = ("Posible duplicación con " + ", ".join(otros) +
                    " (misma provincia, " + etiqueta + ", periodo y destino)"
                    " — renovar el registro existente, no duplicarlo.")
            f["notas"] = (txt(f, "notas") + " | " + nota
                          if txt(f, "notas") else nota)
        aviso(f"Duplicado de periodo en {etiqueta} · {clave[0]} · "
              f"{clave[1]} · {clave[2]} · {clave[3]}: marcados pending "
              + "/".join(ids))


# ------------------------------------------------------------------ emisión

def js(obj):
    return json.dumps(obj, ensure_ascii=False)


def parse_fuente_oficial(texto):
    """«BOCyL 928382» → boletin {tipo, numero}. Sin link ni fecha."""
    texto = (texto or "").strip() if isinstance(texto, str) else ""
    if not texto:
        return {"tipo": "", "numero": "", "expediente": "",
                "fechaPublicacion": "", "link": ""}
    m = re.match(r"^([A-ZÁÉÍÓÚa-záéíóú]+)\s+(.+)$", texto)
    if m:
        return {"tipo": m.group(1), "numero": m.group(2).strip(),
                "expediente": "", "fechaPublicacion": "", "link": ""}
    return {"tipo": texto, "numero": "", "expediente": "",
            "fechaPublicacion": "", "link": ""}


def construir_reportes(colecciones):
    """Se ejecuta SIEMPRE después de las deduplicaciones, para que
    los estados y notas ya mutados (pending + nota cruzada) se
    propaguen a reportes y flujos.
    La agrupación es por ID COMPLETO (regla $: id exacto repetido).
    Las piezas multiterritoriales (regla M) llegan como ids distintos
    por sufijo y NO se funden: cada provincia conserva su registro."""
    reportes, flujos = [], []
    ids_conocidos = set()
    for coleccion in ("eje1", "eje2", "eje3", "eje4"):
        filas = colecciones[coleccion]
        if not filas:
            continue
        n = int(coleccion[-1])
        por_id = {}
        for r in filas:
            por_id.setdefault(txt(r, "id"), []).append(r)
        validar_cabecera_consistente(por_id, coleccion)
        for rid, fs in por_id.items():
            ids_conocidos.add(rid)
            f0 = fs[0]
            rep = {
                "id": rid,                     # ID COMPLETO (con sufijo si lo hay)
                "fecha": txt(f0, "fecha"),
                "titular": txt(f0, "titular"),
                "eje": n,
                "provincia": txt(f0, "provincia"),
                "localidad": txt(f0, "localidad"),
                "medio": txt(f0, "fuente"),
                "agencia": txt(f0, "agencia"),
                "link": txt(f0, "link"),
                "estado": txt(f0, "estado"),
                "grupo": txt(f0, "grupo"),
                "categorias": [],
                "importes": [],
                "boletin": parse_fuente_oficial(txt(f0, "fuente_oficial")),
                "tags": lista_tags(f0.get("tags")),
                "notas": txt(f0, "notas"),
            }
            if txt(f0, "descartado").lower() in ("si", "sí", "true"):
                rep["descartado"] = True
                rep["motivoDescarte"] = txt(f0, "motivo_descarte")
            if txt(f0, "alcance"):
                rep["notas"] = (rep["notas"] + " | " if rep["notas"] else "") \
                    + "Alcance territorial: " + txt(f0, "alcance")
            if n == 1:
                rep["admin"] = lista_tags(f0.get("admin"))
                rep["participacion"] = txt(f0, "participacion")
                if rep["participacion"] and \
                        rep["participacion"] not in PARTICIPACION:
                    error(f"{rid}: participacion no válida "
                          f"({rep['participacion']!r})")
                rep["autoridad"] = txt(f0, "autoridad")
            if n == 2 and f0.get("edificio") is not None:
                rep["edificio"] = entero(f0.get("edificio"), "edificio", rid)
            if n == 4:
                rep["actor"] = txt(f0, "actor")
                rep["tema"] = txt(f0, "tema")
            if n in (2, 3):
                pend = txt(f0, "estado") == "pending"
                act = txt(f0, "act")
                for f in fs:
                    if f.get("cantidad") is None:
                        continue   # pieza sin flujo (p. ej. exclusión noticiosa)
                    cant = entero(f.get("cantidad"), "cantidad", rid)
                    if cant is None:
                        continue
                    # --- programa derivado desde act (v1.2+)
                    prog = programa_desde_act(act, n)
                    if prog is None:
                        error(f"{rid}: no se pudo derivar el programa desde "
                              f"act ({act!r}) — act ausente o no válido")
                        continue
                    gru = txt(f, "gru")
                    origen = txt(f, "origen")
                    if gru not in GRUS:
                        error(f"gru no válido ({gru!r}) en {rid}")
                        continue
                    if not PATRON_ORIGEN.match(origen):
                        aviso(f"origen fuera de patrón conocido ({origen!r}) "
                              f"en {rid} — comprobar COLOR_ORIGEN")
                    rep["importes"].append({"cantidad": cant,
                                            "concepto": txt(f, "concepto"),
                                            "unidad": "EUR"})
                    flujo = {
                        "provincia": txt(f, "provincia"),
                        "eje": n,
                        "programa": prog,
                        "origen": origen,
                        "destino": txt(f, "destino"),
                        "cantidad": cant,
                        "concepto": txt(f, "concepto"),
                        "gru": gru,
                        "reporteId": rid,
                        "pendiente": pend,
                        # act viaja al flujo: habilita el futuro sub-desglose
                        # de Servicios sociales por ACT sin tocar el YAML.
                        "act": act,
                    }
                    if n == 2:
                        # --- tipoE2 DERIVADO del ACT (dato de salida, no maestro):
                        # la plantilla actual sigue leyéndolo; su eliminación
                        # se decide cuando el HTML agrupe por act directamente.
                        flujo["tipoE2"] = ("conservacion" if act == "RES"
                                           else "turismo")
                    flujos.append(flujo)
            reportes.append(rep)
    return reportes, flujos, ids_conocidos


def generar_config(reportes, rango_arg, etiqueta_arg):
    """CONFIG: rango temporal (editorial o derivado) + versión de datos.
    El rango derivado usa SOLO fechas exactas: las aproximadas
    ([MM/AAAA], [DD-DD]/MM/AAAA) y las discrepantes (AAAA?) se
    ignoran para no falsear la ventana."""
    n = len(reportes)
    anio = "—"
    if reportes:
        anios = [r["id"][4:8] for r in reportes if r.get("id")]
        anio = max(set(anios), key=anios.count) if anios else "—"
    if rango_arg:
        rango = rango_arg
    else:
        exactas = []
        for r in reportes:
            f = txt(r, "fecha")
            m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", f)
            if m:
                dia, mes, agno = m.groups()
                exactas.append((agno, mes, dia))   # orden comparable
        if exactas:
            p, u = min(exactas), max(exactas)
            fp = "/".join((p[2], p[1], p[0]))      # invertir: DD/MM/AAAA
            fu = "/".join((u[2], u[1], u[0]))
            rango = (fp + " – " + fu) if fp != fu else fp
        else:
            rango = "sin determinar"
    etiqueta = etiqueta_arg or "v1.3 (ACT · vocabulario Observatorio)"
    if n:
        version = f"{anio} · Castilla y León · {n} reportes · {etiqueta}"
    else:
        version = f"sin datos · {etiqueta}"
    return ("/* ---------- CONFIG ---------- */\n"
            f'const CONFIG = {{\n'
            f'  rangoTemporal:{js(rango)},\n'
            f'  versionDatos:{js(version)}\n'
            f'}};\n')


def main():
    global CARPETA_YAML, HTML_MADRE
    ap = argparse.ArgumentParser(
        description="Inyector YAML → HTML madre v1.3")
    ap.add_argument("--yaml", default=str(CARPETA_YAML))
    ap.add_argument("--html", default=HTML_MADRE)
    ap.add_argument("--out", default="Informe-vigilancia.html",
                    help="nombre del informe generado (no toca la plantilla)")
    ap.add_argument("--check", action="store_true",
                    help="solo validar, no escribir el HTML")
    ap.add_argument("--rango", default=None,
                    help="rango temporal del informe, p. ej. "
                         "'01/01/2026 - 30/09/2026'. Si no se indica, "
                         "se deriva de las fechas exactas de los reportes.")
    ap.add_argument("--etiqueta-version", default=None,
                    help="etiqueta de versión; por defecto "
                         "'v1.3 (ACT · vocabulario Observatorio)'")
    args = ap.parse_args()
    CARPETA_YAML = Path(args.yaml)
    HTML_MADRE = Path(args.html)
    if not CARPETA_YAML.is_dir():
        ap.error(f"la carpeta YAML no existe o no es un directorio: "
                 f"{CARPETA_YAML}")

    # ---- clasificación, lectura y validación básica de las colecciones
    rutas_por_coleccion = {col: [] for col in COLECCIONES}
    rutas_yaml = (sorted(ruta for ruta in CARPETA_YAML.iterdir()
                         if ruta.is_file()
                         and ruta.suffix.casefold() in (".yaml", ".yml"))
                  if CARPETA_YAML.is_dir() else [])
    if not rutas_yaml:
        ap.error(f"no se encontraron archivos YAML en {CARPETA_YAML}")
    for ruta in rutas_yaml:
        coleccion = coleccion_de_archivo(ruta)
        if coleccion is None:
            aviso(f"{ruta.name}: no se reconoce la colección por su nombre; "
                  "archivo omitido")
        else:
            rutas_por_coleccion[coleccion].append(ruta)
    if not any(rutas_por_coleccion.values()):
        ap.error(f"no hay archivos YAML de colecciones reconocidas en "
                 f"{CARPETA_YAML}")

    colecciones = {}
    for col in COLECCIONES:
        filas = cargar(rutas_por_coleccion[col])
        for r in filas:
            validar_registro(r, col)
        colecciones[col] = filas

    # ---- unicidad de ids COMPLETOS:
    #      · entre colecciones distintas → error siempre;
    #      · dentro de una colección → error salvo eje2/eje3 (regla $,
    #        id exacto repetido; los sufijos de regla M son ids distintos).
    vistos = {}
    for col, filas in colecciones.items():
        conteo = {}
        for r in filas:
            rid = txt(r, "id")
            conteo[rid] = conteo.get(rid, 0) + 1
            if rid in vistos and vistos[rid] != col:
                error(f"id usado en dos colecciones: {rid} "
                      f"({vistos[rid]} y {col})")
        for rid, n in conteo.items():
            if n > 1 and col not in CON_REGLA_DOLLAR:
                error(f"id repetido en {col}: {rid}")
        for rid in conteo:
            vistos.setdefault(rid, col)

    # ---- regla M: validación de grupos de sufijo provincial
    validar_multiterritorial(colecciones)

    # ---- continuidad por espacio CYL-AAAA-COL, computada por ID BASE
    #      (el sufijo no consume numeración: -A, -B y -C de la pieza 0031
    #      son un solo número). Huecos: aviso, nunca renumera.
    espacios = {}
    for col, filas in colecciones.items():
        for r in filas:
            m = PATRON_ID.match(txt(r, "id"))
            if m:
                espacios.setdefault((m.group(1), m.group(2)), []).append(
                    int(m.group(3)))
    for (anio, col), nums in espacios.items():
        unicos = set(nums)
        faltan = sorted(set(range(min(unicos), max(unicos) + 1)) - unicos)
        if faltan:
            aviso(f"Huecos de id en CYL-{anio}-{col}: "
                  + ", ".join(f"CYL-{anio}-{col}-{n:04d}" for n in faltan))

    # ---- deduplicación ANTES de construir (las mutaciones deben llegar)
    detectar_duplicados(colecciones["eje2"] + colecciones["eje3"])
    detectar_duplicados_periodo(colecciones["capellanias"], "subtipo",
                                "subtipo")
    detectar_duplicados_periodo(colecciones["educacion"], "partida",
                                "partida")

    # ---- construcción de reportes y flujos (post-deduplicación)
    reportes, flujos, ids_conocidos = construir_reportes(colecciones)

    # ---- capellanías
    capellanias = []
    for r in colecciones["capellanias"]:
        rid = txt(r, "id")
        sub = txt(r, "subtipo")
        if sub and sub not in SUBTIPOS:
            error(f"subtipo no válido ({sub!r}) en {rid}")
        rep_id = txt(r, "reporte_id")
        if rep_id and rep_id not in ids_conocidos:
            error(f"{rid}: capellanía referencia reporte_id inexistente: {rep_id}")
        capellanias.append({
            "provincia": txt(r, "provincia"),
            "subtipo": sub,
            "periodo": txt(r, "periodo"),
            "numero": entero(r.get("numero"), "numero", rid, False),
            "costeAnual": entero(r.get("coste_anual"), "coste_anual",
                                 rid, False),
            "origen": txt(r, "origen"),
            "destino": txt(r, "destino"),
            "concepto": txt(r, "concepto"),
            "medio": txt(r, "fuente"),
            "link": txt(r, "link"),
            "estado": txt(r, "estado"),
            "reporteId": rep_id,
            "notas": txt(r, "notas"),
        })

    # ---- educación
    educacion = []
    for r in colecciones["educacion"]:
        rid = txt(r, "id")
        partida = txt(r, "partida")
        if partida and partida not in PARTIDAS:
            error(f"partida no válida ({partida!r}) en {rid}")
        rep_id = txt(r, "reporte_id")
        if rep_id and rep_id not in ids_conocidos:
            error(f"{rid}: educación referencia reporte_id inexistente: {rep_id}")
        educacion.append({
            "provincia": txt(r, "provincia"),
            "partida": partida,
            "periodo": txt(r, "periodo"),
            "numero": entero(r.get("numero"), "numero", rid, False),
            "costeAnual": entero(r.get("coste_anual"), "coste_anual",
                                 rid, False),
            "origen": "Junta de Castilla y León · Consejería de Educación",
            "destino": txt(r, "destino"),
            "concepto": txt(r, "concepto"),
            "medio": txt(r, "fuente"),
            "link": txt(r, "link"),
            "estado": txt(r, "estado"),
            "reporteId": rep_id,
            "notas": txt(r, "notas"),
        })

    # ---- convenios plurianuales vigentes (contextuales, sin flujo)
    convenios = []
    for r in colecciones["convenios"]:
        rid = txt(r, "id")
        pendiente = r.get("pendiente")
        if not isinstance(pendiente, bool):
            pendiente = txt(r, "pendiente").lower() in ("si", "sí", "true")
        cant = (entero(r.get("cantidad"), "cantidad", rid, obligatorio=False)
                if r.get("cantidad") is not None else None)
        if cant is None and not pendiente:
            error(f"{rid}: convenio sin cantidad y sin pendiente:true")
        convenios.append({
            "provincia": txt(r, "provincia"),
            "eje": 2,
            "origen": txt(r, "origen"),
            "destino": txt(r, "destino"),
            "cantidad": cant,
            "concepto": txt(r, "concepto"),
            "fechaFirma": txt(r, "fecha_firma"),
            "link": txt(r, "link"),
            "pendiente": pendiente,
        })

    # ---- comprobación previa de la plantilla (para que sus avisos
    #      figuren en el informe de validación que se imprime a continuación)
    src = None
    if HTML_MADRE.exists():
        src = HTML_MADRE.read_text(encoding="utf-8")
        if "```" in src:
            aviso("La plantilla contiene '```' (¿restos de un bloque de "
                  "código pegado?) — el informe saldrá con él incluido. "
                  "Límpialo en la plantilla.")
        if not args.check and (src.find(MARCA_INI) == -1
                               or src.find(MARCA_FIN) == -1
                               or src.find(MARCA_FIN) < src.find(MARCA_INI)):
            error(f"La plantilla no contiene los marcadores {MARCA_INI} / "
                  f"{MARCA_FIN}. Colócalos rodeando las antiguas constantes.")

    # ---- informe de validación
    if avisos:
        print(f"— {len(avisos)} aviso(s):")
        for a in avisos:
            print("   ·", a)
    if errores:
        print(f"✖ {len(errores)} error(es). El HTML NO se ha tocado:")
        for e in errores:
            print("   ✗", e)
        sys.exit(1)
    print(f"✔ Validación superada: {len(reportes)} reportes · "
          f"{len(flujos)} flujos · {len(capellanias)} capellanías · "
          f"{len(educacion)} educación · {len(convenios)} convenios")

    if args.check:
        print("Modo --check: sin escritura.")
        return

    if src is None:
        error(f"No encuentro la plantilla: {HTML_MADRE}")
        sys.exit(1)

    # ---- ordenación: provincia (Ávila→Zamora) y dentro por id completo
    #      (orden de sufijos: '0031-A' < '0031-B' por orden natural de texto)
    def orden(r):
        return (ORDEN_PROV.get(r.get("provincia", ""), 99),
                r.get("id", r.get("reporteId", "")))
    reportes.sort(key=orden)
    flujos.sort(key=orden)

    # ---- emisión de literales con banners por provincia
    def emitir(nombre, registros, fn):
        trozos = []
        prov_actual = None
        for r in registros:
            if r.get("provincia") != prov_actual:
                prov_actual = r.get("provincia")
                trozos.append(f"\n  /* ===== {prov_actual.upper()} ===== */")
            trozos.append("  " + fn(r) + ",")
        cuerpo = "\n".join(trozos)
        return f"const {nombre} = [\n{cuerpo.rstrip(',')}];\n"

    def flujo_a_literal(f):
        partes = [f'provincia:{js(f["provincia"])}', f'eje:{f["eje"]}']
        if "tipoE2" in f:
            partes.append(f'tipoE2:{js(f["tipoE2"])}')
        partes += [f'programa:{js(f["programa"])}',
                   f'origen:{js(f["origen"])}',
                   f'destino:{js(f["destino"])}',
                   f'cantidad:{f["cantidad"]}',
                   f'concepto:{js(f["concepto"])}',
                   f'gru:{js(f["gru"])}',
                   f'act:{js(f["act"])}',
                   f'reporteId:{js(f["reporteId"])}',
                   f'pendiente:{"true" if f["pendiente"] else "false"}']
        return "{" + ", ".join(partes) + "}"

    def capellanias_a_literal(c):
        return ("{" + f'provincia:{js(c["provincia"])}, '
                f'subtipo:{js(c["subtipo"])}, periodo:{js(c["periodo"])}, '
                f'numero:{json.dumps(c["numero"])}, '
                f'costeAnual:{json.dumps(c["costeAnual"])}, '
                f'origen:{js(c["origen"])}, destino:{js(c["destino"])}, '
                f'concepto:{js(c["concepto"])}, medio:{js(c["medio"])}, '
                f'agencia:"", link:{js(c["link"])}, '
                f'estado:{js(c["estado"])}, reporteId:{js(c["reporteId"])}, '
                f'notas:{js(c["notas"])}' + "}")

    def educacion_a_literal(e):
        return ("{" + f'provincia:{js(e["provincia"])}, '
                f'partida:{js(e["partida"])}, periodo:{js(e["periodo"])}, '
                f'numero:{json.dumps(e["numero"])}, '
                f'costeAnual:{json.dumps(e["costeAnual"])}, '
                f'origen:{js(e["origen"])}, destino:{js(e["destino"])}, '
                f'concepto:{js(e["concepto"])}, medio:{js(e["medio"])}, '
                f'agencia:"", link:{js(e["link"])}, '
                f'estado:{js(e["estado"])}, reporteId:{js(e["reporteId"])}, '
                f'notas:{js(e["notas"])}' + "}")

    def convenio_a_literal(c):
        return ("{" + f'provincia:{js(c["provincia"])}, eje:2, '
                f'origen:{js(c["origen"])}, destino:{js(c["destino"])}, '
                f'cantidad:{json.dumps(c["cantidad"])}, '
                f'concepto:{js(c["concepto"])}, '
                f'fechaFirma:{js(c["fechaFirma"])}, link:{js(c["link"])}, '
                f'pendiente:{"true" if c["pendiente"] else "false"}' + "}")

    def reporte_a_literal(r):
        p = [f'id:{js(r["id"])}', f'fecha:{js(r["fecha"])}',
             f'titular:{js(r["titular"])}', f'eje:{r["eje"]}',
             f'provincia:{js(r["provincia"])}', f'localidad:{js(r["localidad"])}',
             f'medio:{js(r["medio"])}', f'agencia:{js(r["agencia"])}',
             f'link:{js(r["link"])}', f'estado:{js(r["estado"])}',
             f'grupo:{js(r["grupo"])}']
        if "admin" in r:
            p.append(f'admin:{json.dumps(r["admin"], ensure_ascii=False)}')
            p.append(f'participacion:{js(r["participacion"])}')
            p.append(f'autoridad:{js(r.get("autoridad", ""))}')
        if "edificio" in r:
            p.append(f'edificio:{json.dumps(r["edificio"])}')
        if "descartado" in r:
            p.append('descartado:true')
            p.append(f'motivoDescarte:{js(r["motivoDescarte"])}')
        if "actor" in r:
            p.append(f'actor:{js(r["actor"])}')
            p.append(f'tema:{js(r["tema"])}')
        p += ['categorias:[]',
              f'importes:{json.dumps(r["importes"], ensure_ascii=False)}',
              f'boletin:{json.dumps(r["boletin"], ensure_ascii=False)}',
              f'tags:{json.dumps(r["tags"], ensure_ascii=False)}',
              f'notas:{js(r["notas"])}']
        return "{" + ", ".join(p) + "}"

    bloques = (
        emitir("REPORTES", reportes, reporte_a_literal) + "\n" +
        emitir("FLUJOS_DINERO", flujos, flujo_a_literal) + "\n" +
        emitir("CAPELANIAS", capellanias, capellanias_a_literal) + "\n" +
        emitir("EDUCACION", educacion, educacion_a_literal) + "\n" +
        emitir("CONVENIOS_VIGENTES", convenios, convenio_a_literal) + "\n" +
        generar_config(reportes, args.rango, args.etiqueta_version)
    )

    # ---- inyección en el HTML (crea informe nuevo, no sobrescribe plantilla)
    i, j = src.find(MARCA_INI), src.find(MARCA_FIN)
    nuevo = (src[:i + len(MARCA_INI)] + "\n" + bloques +
             "\n" + src[j:])

    INFORME_FINAL = Path(args.out)
    if INFORME_FINAL.resolve() == HTML_MADRE.resolve():
        ap.error("--out no puede apuntar al mismo archivo que --html; "
                 "se evitaría sobrescribir la plantilla")
    if INFORME_FINAL.exists():
        print(f"ℹ Sobrescribiendo {INFORME_FINAL}...")
    INFORME_FINAL.write_text(nuevo, encoding="utf-8")
    print(f"✔ Informe generado: {INFORME_FINAL} (plantilla intacta)")


if __name__ == "__main__":
    main()
