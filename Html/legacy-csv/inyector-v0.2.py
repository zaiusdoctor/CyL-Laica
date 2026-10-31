#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py · Inyector de datos CSV → HTML madre
Observatorio del laicismo · Castilla y León
=================================================
Uso:
    python build.py                 # valida e inyecta en el HTML madre
    python build.py --check         # solo valida, no toca el HTML
    python build.py --csv csv --html Madre-v3.0.html

Entradas (carpeta csv/, todas opcionales salvo que se indique):
    eje1.csv, eje2.csv, eje3.csv, eje4.csv   · reportes (+ flujo en 2 y 3)
    capellanias.csv, educacion.csv, convenios.csv

Formato: delimitador ';', UTF-8 con BOM, fechas DD/MM/AAAA.
En eje2/eje3, una fila por LÍNEA ECONÓMICA: filas que comparten id
forman un solo reporte (regla $) con N importes y N flujos.

Regla de estado: el campo `estado` viaja literal desde el CSV.
El build SOLO lo modifica en caso de deduplicación detectada
(clave provincia+origen+destino+cantidad con fecha igual, distinto id):
fuerza pending en ambas filas y añade nota cruzada «Posible
duplicación con REP-XXX». La resolución es siempre manual.

El motor y el diseño del HTML quedan intactos: los literales JS se
inyectan entre los marcadores /*__DATOS__*/ y /*__FIN_DATOS__*/,
sustituyendo lo que hubiera entre ellos.
"""

import argparse
import csv
import json
import re
import shutil
import sys
from pathlib import Path

# ------------------------------------------------------------------ config

CARPETA_CSV = Path("csv")
HTML_MADRE = Path("Madre-v2.4.html")
MARCA_INI = "/*__DATOS__*/"
MARCA_FIN = "/*__FIN_DATOS__*/"

PROVINCIAS = ["Ávila", "Burgos", "León", "Palencia", "Salamanca",
              "Segovia", "Soria", "Valladolid", "Zamora"]
ORDEN_PROV = {p: i for i, p in enumerate(PROVINCIAS)}

ESTADOS = {"verified", "approx", "pending"}
PROGRAMAS = {"Conservación de patrimonio", "Turismo religioso",
             "Servicios sociales", "Capellanías hospitalarias", "Educación"}
PARTICIPACION = {"organizacion", "intervencion", "asistencia", "protocolo"}
TIPO_E2 = {"conservacion", "turismo"}
SUBTIPOS = {"sanitaria", "militar"}
PARTIDAS = {"profesorado", "concierto"}
GRUS = {"OR", "ID", "EC", "MIX", "EV", "JU", "IS", "HI", "ORT", "BU", "OC"}
BOOL_SI = {"si", "sí", "true", "1", "x"}

PATRON_ORIGEN = re.compile(
    r"^(Junta|M\. |Ministerio|Ayuntamiento de |Diputación de |Comarca)")
FECHA_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4}"
    r"|\d{2}/\d{2}/\d{4}\?"
    r"|\[\d{2}-\d{2}\]/\d{2}/\d{4}"
    r"|\[\d{2}/\d{4}\])$")

COMUNES = ["id", "fecha", "titular", "provincia", "localidad", "fuente",
           "link", "estado", "grupo", "tags", "notas", "descartado",
           "motivo_descarte", "alcance", "fuente_oficial"]
COLUMNAS = {
    "eje1": COMUNES + ["admin", "autoridad", "participacion"],
    "eje2": COMUNES + ["edificio", "origen", "destino", "cantidad",
                       "concepto", "programa", "tipo_e2", "gru"],
    "eje3": COMUNES + ["origen", "destino", "cantidad",
                       "concepto", "programa", "gru"],
    "eje4": COMUNES + ["actor", "tema"],
}
COL_CAPELLANIAS = ["provincia", "subtipo", "periodo", "numero", "coste_anual",
                    "origen", "destino", "concepto", "fuente", "link",
                    "estado", "reporte_id", "notas"]
COL_EDUCACION = ["provincia", "partida", "periodo", "numero", "coste_anual",
                 "destino", "concepto", "fuente", "link", "estado",
                 "reporte_id", "notas"]
COL_CONVENIOS = ["provincia", "origen", "destino", "cantidad", "concepto",
                 "fecha_firma", "link", "pendiente", "alcance"]

errores, avisos = [], []


def error(msg):
    errores.append(msg)


def aviso(msg):
    avisos.append(msg)


# ------------------------------------------------------------------ lectura

def leer(nombre, columnas, obligatorio=False):
    ruta = CARPETA_CSV / nombre
    if not ruta.exists():
        if obligatorio:
            error(f"Falta {ruta}")
        return []
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f, delimiter=";")
        if lector.fieldnames != columnas:
            error(f"{nombre}: cabecera incorrecta.\n  Esperada: {columnas}"
                  f"\n  Encontrada: {lector.fieldnames}")
            return []
        filas = [dict(r) for r in lector]
    return filas


def entero(v, campo, fila, obligatorio=True):
    v = (v or "").strip()
    if v == "":
        if obligatorio:
            error(f"{campo} vacío en fila: {fila.get('id', fila)}")
        return None
    try:
        return int(v)
    except ValueError:
        error(f"{campo} no numérico ({v!r}) en {fila.get('id', fila)}")
        return None


def fecha_valida(v, fila):
    if not FECHA_RE.match((v or "").strip()):
        error(f"fecha mal formada ({v!r}) en {fila.get('id', '?')}")


# ------------------------------------------------------------- validaciones

def validar_comunes(r, eje, ids_vistos):
    rid = (r["id"] or "").strip()
    if not re.match(r"^REP-\d{4}-\d{4}$", rid):
        error(f"id mal formado: {rid!r} ({eje})")
    if rid in ids_vistos[eje]:
        error(f"id repetido en {eje}: {rid}")
    ids_vistos[eje].add(rid)
    if (r["estado"] or "").strip() not in ESTADOS:
        error(f"estado no válido ({r['estado']!r}) en {rid}")
    if (r["provincia"] or "").strip() not in ORDEN_PROV:
        error(f"provincia desconocida ({r['provincia']!r}) en {rid}")
    fecha_valida(r["fecha"], r)
    if (r["descartado"] or "").strip().lower() in BOOL_SI and \
            not (r["motivo_descarte"] or "").strip():
        error(f"{rid}: descartado sin motivo_descarte")
    if (r["estado"] or "").strip() == "pending":
        # pista de verificación recomendada, no exigida
        pass


def validar_cabecera_consistente(filas_por_id):
    """Filas que comparten id deben tener cabecera idéntica (regla $)."""
    for rid, filas in filas_por_id.items():
        if len(filas) < 2:
            continue
        base = {k: filas[0][k] for k in COMUNES}
        for f in filas[1:]:
            for k in COMUNES:
                if (f[k] or "").strip() != (base[k] or "").strip():
                    error(f"{rid}: cabecera divergente en columna "
                          f"{k!r} entre filas del mismo id")


def detectar_duplicados(filas_flujo):
    """Clave (provincia, origen, destino, cantidad) entre ids distintos.
    Misma fecha → pending + nota cruzada en AMBAS filas.
    Fecha distinta → solo aviso en consola (pago fraccionado posible)."""
    indice = {}
    for f in filas_flujo:
        clave = (f["provincia"].strip(), f["origen"].strip(),
                 f["destino"].strip(), f["cantidad"])
        indice.setdefault(clave, []).append(f)
    for clave, grupo in indice.items():
        ids = {(g["id"], g["fecha"]) for g in grupo}
        if len(ids) < 2:
            continue
        por_fecha = {}
        for g in grupo:
            por_fecha.setdefault(g["fecha"].strip(), []).append(g)
        for fecha, fs in por_fecha.items():
            if len({x["id"] for x in fs}) < 2:
                continue
            for f in fs:
                otros = sorted({x["id"] for x in fs if x["id"] != f["id"]})
                f["estado"] = "pending"
                nota = ("Posible duplicación con " +
                        ", ".join(otros) +
                        " (misma fecha, importe, origen y destino) — "
                        "verificar y corregir a mano.")
                f["notas"] = ((f["notas"].strip() + " | ").rstrip(" |")
                              + nota if (f["notas"] or "").strip() else nota)
            aviso(f"Duplicado sospechoso {clave[0]} · {clave[1]} → "
                  f"{clave[2]} · {clave[3]} € · {fecha}: marcados pending "
                  + "/".join(sorted({x['id'] for x in fs}))
                  + " — computarán en sumas cuando se verifique a mano")


# ------------------------------------------------------------------ emisión

def js(obj):
    return json.dumps(obj, ensure_ascii=False)


def parse_fuente_oficial(texto):
    """«BOCyL 928382» → boletin {tipo, numero}. Sin link ni fecha."""
    texto = (texto or "").strip()
    if not texto:
        return {"tipo": "", "numero": "", "expediente": "",
                "fechaPublicacion": "", "link": ""}
    m = re.match(r"^([A-ZÁÉÍÓÚa-záéíóú]+)\s+(.+)$", texto)
    if m:
        return {"tipo": m.group(1), "numero": m.group(2).strip(),
                "expediente": "", "fechaPublicacion": "", "link": ""}
    return {"tipo": texto, "numero": "", "expediente": "",
            "fechaPublicacion": "", "link": ""}


def split_lista(v):
    v = (v or "").strip()
    return [x.strip() for x in v.split("|") if x.strip()] if v else []


def construir_reportes(ejes):
    """ejes: {'eje1': filas, ...} → (reportes_js, flujos_js, ids_conocidos)"""
    reportes, flujos = [], []
    ids_conocidos = set()
    for eje, filas in ejes.items():
        if not filas:
            continue
        n = int(eje[-1])
        por_id = {}
        for r in filas:
            por_id.setdefault(r["id"].strip(), []).append(r)
        validar_cabecera_consistente(por_id)
        for rid, fs in por_id.items():
            ids_conocidos.add(rid)
            f0 = fs[0]
            rep = {
                "id": rid,
                "fecha": f0["fecha"].strip(),
                "titular": f0["titular"].strip(),
                "eje": n,
                "provincia": f0["provincia"].strip(),
                "localidad": f0["localidad"].strip(),
                "medio": f0["fuente"].strip(),   # fuente periodística/BDNS
                "agencia": "",
                "link": f0["link"].strip(),
                "estado": f0["estado"].strip(),
                "grupo": f0["grupo"].strip(),
                "categorias": [],
                "importes": [],
                "boletin": parse_fuente_oficial(f0["fuente_oficial"]),
                "tags": split_lista(f0["tags"]),
                "notas": f0["notas"].strip(),
            }
            if (f0["descartado"] or "").strip().lower() in BOOL_SI:
                rep["descartado"] = True
                rep["motivoDescarte"] = f0["motivo_descarte"].strip()
            if f0["alcance"].strip():             # regla M documentada
                rep["notas"] = (rep["notas"] + " | " if rep["notas"] else "") \
                    + "Alcance territorial: " + f0["alcance"].strip()
            if eje == "eje1":
                rep["admin"] = split_lista(f0["admin"])
                rep["participacion"] = f0["participacion"].strip()
                rep["autoridad"] = f0["autoridad"].strip()
            if eje == "eje2":
                ed = entero(f0["edificio"], "edificio", f0, obligatorio=False)
                rep["edificio"] = ed
            if eje == "eje4":
                rep["actor"] = f0["actor"].strip()
                rep["tema"] = f0["tema"].strip()
            if n in (2, 3):
                pend = f0["estado"].strip() == "pending"
                for f in fs:
                    cant = entero(f["cantidad"], "cantidad", f)
                    if cant is None:
                        continue
                    rep["importes"].append(
                        {"cantidad": cant,
                         "concepto": f["concepto"].strip(),
                         "unidad": "EUR"})
                    flujo = {
                        "provincia": f["provincia"].strip(),
                        "eje": n,
                        "programa": f["programa"].strip(),
                        "origen": f["origen"].strip(),
                        "destino": f["destino"].strip(),
                        "cantidad": cant,
                        "concepto": f["concepto"].strip(),
                        "gru": f["gru"].strip(),
                        "reporteId": rid,
                        "pendiente": pend,
                    }
                    if n == 2:
                        flujo["tipoE2"] = f["tipo_e2"].strip()
                    flujos.append(flujo)
                    if f["programa"].strip() not in PROGRAMAS:
                        error(f"programa fuera de enum ({f['programa']!r}) "
                              f"en {rid}")
                    if f["gru"].strip() not in GRUS:
                        error(f"gru no válido ({f['gru']!r}) en {rid}")
                    if n == 2 and f["tipo_e2"].strip() not in TIPO_E2:
                        error(f"tipo_e2 no válido ({f['tipo_e2']!r}) en {rid}")
                    if not PATRON_ORIGEN.match(f["origen"].strip()):
                        aviso(f"origen fuera de patrón conocido "
                              f"({f['origen']!r}) en {rid} — comprobar "
                              f"COLOR_ORIGEN")
            reportes.append(rep)
    return reportes, flujos, ids_conocidos


def main():
    global CARPETA_CSV, HTML_MADRE
    ap = argparse.ArgumentParser(description="Inyector CSV → HTML madre")
    ap.add_argument("--csv", default=str(CARPETA_CSV))
    ap.add_argument("--html", default=str(HTML_MADRE))
    ap.add_argument("--out", default="Informe-vigilancia.html",
                    help="nombre del informe generado (no toca la plantilla)")
    ap.add_argument("--check", action="store_true",
                    help="solo validar, no escribir el HTML")
    args = ap.parse_args()
    CARPETA_CSV = Path(args.csv)
    HTML_MADRE = Path(args.html)

    # ---- lectura de reportes
    ids_vistos = {"eje1": set(), "eje2": set(), "eje3": set(), "eje4": set()}
    ejes = {}
    for eje in ("eje1", "eje2", "eje3", "eje4"):
        filas = leer(eje + ".csv", COLUMNAS[eje])
        for r in filas:
            validar_comunes(r, eje, ids_vistos)
        ejes[eje] = filas

    # ---- deduplicación (solo eje2+eje3: generan flujo)
    todas_flujo = ejes["eje2"] + ejes["eje3"]
    detectar_duplicados(todas_flujo)

    reportes, flujos, ids_conocidos = construir_reportes(ejes)

    # ---- continuidad de ids (huecos reportados, nunca renumerados)
    anios = {}
    for r in reportes:
        anios.setdefault(r["id"][4:8], []).append(int(r["id"][9:]))
    for anio, nums in anios.items():
        faltan = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
        if faltan:
            aviso(f"Huecos de id en {anio}: "
                  + ", ".join(f"REP-{anio}-{n:04d}" for n in faltan))

    # ---- capellanías
    capellanias = []
    for r in leer("capellanias.csv", COL_CAPELLANIAS):
        if r["subtipo"].strip() not in SUBTIPOS:
            error(f"subtipo no válido ({r['subtipo']!r}) en capellanías")
        if r["estado"].strip() not in ESTADOS:
            error(f"estado no válido ({r['estado']!r}) en capellanías")
        rid = r["reporte_id"].strip()
        if rid and rid not in ids_conocidos:
            error(f"capellanía referencia reporte_id inexistente: {rid}")
        capellanias.append({
            "provincia": r["provincia"].strip(),
            "subtipo": r["subtipo"].strip(),
            "periodo": r["periodo"].strip(),
            "numero": entero(r["numero"], "numero", r, False),
            "costeAnual": entero(r["coste_anual"], "coste_anual", r, False),
            "origen": r["origen"].strip(),
            "destino": r["destino"].strip(),
            "concepto": r["concepto"].strip(),
            "medio": r["fuente"].strip(),
            "link": r["link"].strip(),
            "estado": r["estado"].strip(),
            "reporteId": rid,
            "notas": r["notas"].strip(),
        })

    # ---- educación
    educacion = []
    for r in leer("educacion.csv", COL_EDUCACION):
        if r["partida"].strip() not in PARTIDAS:
            error(f"partida no válida ({r['partida']!r}) en educacion")
        rid = r["reporte_id"].strip()
        if rid and rid not in ids_conocidos:
            error(f"educación referencia reporte_id inexistente: {rid}")
        educacion.append({
            "provincia": r["provincia"].strip(),
            "partida": r["partida"].strip(),
            "periodo": r["periodo"].strip(),
            "numero": entero(r["numero"], "numero", r, False),
            "costeAnual": entero(r["coste_anual"], "coste_anual", r, False),
            "origen": "Junta de Castilla y León · Consejería de Educación",
            "destino": r["destino"].strip(),
            "concepto": r["concepto"].strip(),
            "medio": r["fuente"].strip(),
            "link": r["link"].strip(),
            "estado": r["estado"].strip(),
            "reporteId": rid,
            "notas": r["notas"].strip(),
        })

    # ---- convenios plurianuales vigentes
    convenios = []
    for r in leer("convenios.csv", COL_CONVENIOS):
        convenios.append({
            "provincia": r["provincia"].strip(),
            "eje": 2,
            "origen": r["origen"].strip(),
            "destino": r["destino"].strip(),
            "cantidad": entero(r["cantidad"], "cantidad", r),
            "concepto": r["concepto"].strip(),
            "fechaFirma": r["fecha_firma"].strip(),
            "link": r["link"].strip(),
            "pendiente": (r["pendiente"] or "").strip().lower() in BOOL_SI,
        })

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

    # ---- ordenación: provincia (Ávila→Zamora) y dentro por id
    def orden(r):
        return (ORDEN_PROV.get(r["provincia"], 99),
                r.get("id", r.get("reporteId", "")))
    reportes.sort(key=lambda r: orden(r))
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
        cuerpo = "\n".join(trozos).rstrip(",")
        return f"const {nombre} = [\n{cuerso_body(nombre, cuerpo)}\n];\n" \
            if False else f"const {nombre} = [{cuerpo.rstrip(',')}\n];\n"

    def cuerpo_body(*_):
        return ""

    def flujo_a_literal(f):
        partes = [f'provincia:{js(f["provincia"])}', f'eje:{f["eje"]}']
        if "tipoE2" in f:
            partes.append(f'tipoE2:{js(f["tipoE2"])}')
        partes += [f'programa:{js(f["programa"])}', f'origen:{js(f["origen"])}',
                   f'destino:{js(f["destino"])}', f'cantidad:{f["cantidad"]}',
                   f'concepto:{js(f["concepto"])}', f'gru:{js(f["gru"])}',
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
                f'cantidad:{c["cantidad"]}, concepto:{js(c["concepto"])}, '
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
        emitir("CONVENIOS_VIGENTES", convenios, convenio_a_literal)
    )

       # ---- inyección en el HTML (crea informe nuevo, no sobrescribe plantilla)
    if not HTML_MADRE.exists():
        error(f"No encuentro la plantilla: {HTML_MADRE}")
        sys.exit(1)
    
    src = HTML_MADRE.read_text(encoding="utf-8")
    i, j = src.find(MARCA_INI), src.find(MARCA_FIN)
    if i == -1 or j == -1 or j < i:
        error(f"La plantilla no contiene los marcadores {MARCA_INI} / "
              f"{MARCA_FIN}. Colócalos rodeando las antiguas constantes.")
        sys.exit(1)
    
    nuevo = (src[:i + len(MARCA_INI)] + "\n" + bloques +
             "\n" + src[j:])
    
    # Crear archivo nuevo en lugar de sobrescribir la plantilla
    INFORME_FINAL = Path(args.out)
    if INFORME_FINAL.exists():
        print(f"ℹ Sobrescribiendo {INFORME_FINAL}...")
    INFORME_FINAL.write_text(nuevo, encoding="utf-8")
    print(f"✔ Informe generado: {INFORME_FINAL} (plantilla intacta)")


if __name__ == "__main__":
    main()