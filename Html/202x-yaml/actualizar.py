#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrar_yaml_v15.py · Migrador del esquema v1.2 → v1.5
Observatorio del laicismo · Castilla y León
=================================================
Uso:
    python migrar_yaml_v15.py yaml/ yaml_migrado/

Entradas (carpeta yaml/):
    eje2*.yaml, eje3*.yaml, capellanias*.yaml, convenios*.yaml
    (la búsqueda no distingue mayúsculas)

Salidas (carpeta yaml_migrado/):
    Todos los YAML convertidos + educacion.yaml nuevo + BLOQUE_F.md
"""

from datetime import date
from pathlib import Path
import re
import yaml

# ==================================================================== MAPAS DE MIGRACIÓN
# ====================================================================

# TABLA PROGRAMAS ANTIGUOS → ACT (nuevo vocabulario)
PROGRAMA_A_ACT = {
    "Conservación de patrimonio": "RES",
    "Turismo religioso": None,  # bifurca: si el receptor es cofradía → CF; si no, CU
    "Educación": None,          # bifurca: si es universidad → UC, sino ED
    "Servicios sociales": None, # bifurca según subcódigo (ver abajo)
    "Capellanías hospitalarias": "HC",
}

# Subcódigos AS para Servicios sociales (prioridad por orden de aparición en concepto)
AS_SUBCODIGOS = {
    "discapacidad": "ASD",
    "droga": "AST",
    "toxicodependencia": "AST",
    "anciano": "ASR",
    "tercera edad": "ASR",
    "menor": "ASI",
    "infancia": "ASI",
    "juventud": "ASJ",
    "mujer": "ASM",
    "enfermo": "ASE",
    "exclusión": "AS",
    "pobreza": "AS",
    "inclusión": "AS",
    "cáritas": "AS",
    "caritas": "AS",
}

# GRU retirados → actuales
GRU_MIGRACION = {
    "ORT": "COR",  # Ortodoxos
    "JU": "CJ",    # Judía
    "IS": "CI",    # Islámica
    "BU": "CB",    # Budista
    "HI": "CH",    # Hinduísta
    "OC": "Z",     # Otros (no confesional)
}

# Determina si una pieza es económica (tiene cantidad o origen+destino+concepto transferencial)
def es_economico(reg):
    if reg.get("cantidad") is not None:
        return True
    if reg.get("origen") and reg.get("destino") and reg.get("concepto"):
        # Verificar que el concepto describe transferencia (palabras clave)
        concepto = str(reg.get("concepto", "")).lower()
        transferencias = ["subvención", "convenio", "concesión", "financiación", 
                         "aportación", "aporte", "pago", "financiar", "costear"]
        return any(term in concepto for term in transferencias)
    return False

# Deriva ACT desde programa antiguo y receptor (gru)
def derive_act(programa_old, concepto, edificio=None, destino=None,
               tags=None, notas=None):
    if programa_old is None:
        # Sin programa antiguo, usar heurística
        concepto_lower = str(concepto or "").lower()
        contexto = " ".join(
            str(value or "") for value in (concepto, edificio, destino, tags, notas)
        ).lower()
        
        # Restauración/obras físicas
        if any(term in contexto for term in ["restauración", "obra", "conservación", "reparación", "rehabilitación", "mantenimiento"]):
            return "RES"
        
        # Apertura turística/cultura
        if any(term in contexto for term in ["apertura", "visita", "turismo", "patrimonio turístico"]):
            return "CU"
        
        # Educación
        if any(term in contexto for term in ["religión", "enseñanza", "docente", "concierto", "universidad", "educación", "educativo", "escuelas católicas"]):
            if "universidad" in contexto:
                return "UC"
            return "ED"
        
        # Cofradías (Semana Santa, pasos, procesiones)
        if any(term in contexto
               for term in ["cofradía", "hermandad"]):
            return "CF"
        if any(term in contexto for term in ["semana santa", "paso", "procesión"]):
            return "CF"
        
        # Acción social
        if any(term in contexto for term in ["cáritas", "caritas", "exclusión", "pobreza", "discapacidad", "anciano", "menor", "inclusión"]):
            return derive_as_subcodigo(contexto)
        
        # Capellanías
        if any(term in contexto for term in ["capellanía", "capellanía sanitaria", "asistencia religiosa hospitalaria"]):
            return "HC"
        
        return "Z"
    
    # Con programa antiguo
    act = PROGRAMA_A_ACT.get(programa_old)
    
    if act:
        return act
    
    # Programa que necesita bifurcación
    if programa_old == "Turismo religioso":
        # Si el receptor es cofradía/hermandad → CF, sino CU
        concepto_lower = str(concepto or "").lower()
        destino_lower = str(destino or "").lower()
        if any(term in concepto_lower or term in destino_lower
               for term in ["cofradía", "hermandad"]):
            return "CF"
        return "CU"
    
    if programa_old == "Educación":
        if "universidad" in f"{concepto or ''} {destino or ''}".lower():
            return "UC"
        return "ED"
    
    if programa_old == "Servicios sociales":
        return derive_as_subcodigo(str(concepto or "").lower())
    
    return "Z"

def derive_gru(destino):
    """Deriva GRU desde el nombre del destinatario según la tabla v1.5."""
    destino_lower = str(destino or "").lower()
    if any(term in destino_lower for term in ("diócesis", "diocesis", "obispado",
                                                "arzobispado", "cabildo catedralicio")):
        return "ID"
    if any(term in destino_lower for term in ("orden ", "hermanas ", "salesianos",
                                                "hijas de la caridad")):
        return "OR"
    if any(term in destino_lower for term in ("cáritas", "caritas", "cofradía",
                                                "cofradia", "hermandad",
                                                "escuelas católicas",
                                                "escuelas catolicas",
                                                "universidad pontificia")):
        return "EC"
    if any(term in destino_lower for term in ("iglesia evangélica",
                                                "iglesia evangelica")):
        return "EV"
    if "comunidad islámica" in destino_lower or "comunidad islamica" in destino_lower:
        return "CI"
    if any(term in destino_lower for term in ("comunidad israelita", "comunidad judía",
                                                "comunidad judia")):
        return "CJ"
    if any(term in destino_lower for term in ("parroquia ortodoxa", "iglesia ortodoxa")):
        return "COR"
    return "Z"

def derive_as_subcodigo(concepto_lower):
    """Deriva subcódigo AS desde concepto."""
    for clave, codigo in AS_SUBCODIGOS.items():
        if clave in concepto_lower:
            return codigo
    return "AS"  # Genérico si no hay subcódigo claro

# ==================================================================== PROCESAMIENTO POR COLECCIÓN
# ====================================================================

def migrar_eje2(reg, original_programa):
    """Elimina campos retirados y deriva act/gru según regla."""
    reg.pop("programa", None)
    reg.pop("tipo_e2", None)
    act = (derive_act(original_programa, reg.get("concepto"),
                      reg.get("edificio"), reg.get("destino"))
           if original_programa else
           reg.get("act") or derive_act(
               None, reg.get("concepto"), reg.get("edificio"),
               reg.get("destino")))
    reg["act"] = act
    return act, migrar_gru(reg)

def migrar_eje3(reg, original_programa):
    """Elimina campos retirados y deriva act/gru según regla."""
    reg.pop("programa", None)
    reg.pop("tipo_e2", None)
    act = (derive_act(original_programa, reg.get("concepto"),
                      destino=reg.get("destino"))
           if original_programa else
           reg.get("act") or derive_act(
               None, reg.get("concepto"), destino=reg.get("destino")))
    reg["act"] = act
    return act, migrar_gru(reg)

def migrar_gru(reg):
    """Migra GRU retirados y devuelve el código anterior si cambió."""
    gru_old = reg.get("gru")
    if gru_old in GRU_MIGRACION:
        reg["gru"] = GRU_MIGRACION[gru_old]
        return gru_old
    return None

def eliminar_campos_retirados(reg):
    """Elimina los campos del esquema anterior en cualquier colección."""
    reg.pop("programa", None)
    reg.pop("tipo_e2", None)

def migrar_capellanias(reg):
    """Migra los campos retirados y conserva el periodo como texto."""
    programa_old = reg.get("programa")
    eliminar_campos_retirados(reg)
    if programa_old:
        reg["act"] = derive_act(programa_old, reg.get("concepto"),
                                destino=reg.get("destino"))
    if reg.get("periodo") is not None:
        reg["periodo"] = str(reg["periodo"])
    return migrar_gru(reg)

def migrar_convenios(reg):
    """Migra cualquier campo de programa o GRU heredado."""
    programa_old = reg.get("programa")
    eliminar_campos_retirados(reg)
    if programa_old or not reg.get("act"):
        reg["act"] = derive_act(
            programa_old, reg.get("concepto"), destino=reg.get("destino"),
            tags=reg.get("tags"), notas=reg.get("notas"))
    gru_old = reg.get("gru")
    if gru_old in GRU_MIGRACION:
        reg["gru"] = GRU_MIGRACION[gru_old]
    elif not gru_old:
        reg["gru"] = derive_gru(reg.get("destino"))
    return gru_old if gru_old in GRU_MIGRACION else None

def crear_educacion():
    """Crear educacion.yaml nuevo con estructura v1.5."""
    return []

def archivos_coleccion(input_dir, prefijo):
    """Busca ficheros YAML de una colección sin distinguir mayúsculas."""
    return sorted(
        path for path in input_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".yaml", ".yml"}
        and path.stem.lower().startswith(prefijo.lower())
    )

def leer_registros(yaml_file):
    with yaml_file.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return []
    if not isinstance(data, list) or any(not isinstance(reg, dict) for reg in data):
        raise ValueError(f"{yaml_file}: se esperaba una lista de registros YAML")
    return data

def registrar_cambios(resumen, reg, coleccion, programa_old, gru_old,
                      act_old, campos_retirados):
    rid = reg.get("id", "(sin ID)")
    cambios = []
    if programa_old:
        cambios.append(f"programa {programa_old!r} → act {reg.get('act')!r}")
    if gru_old in GRU_MIGRACION:
        cambios.append(f"gru {gru_old} → {reg.get('gru')}")
    if act_old is None and reg.get("act"):
        cambios.append(f"act derivado {reg['act']}")
    if campos_retirados and not programa_old:
        cambios.append("campos retirados eliminados")
    if cambios:
        resumen["actualizados"].append(
            f"{rid} ({coleccion}): " + "; ".join(cambios))
    if reg.get("estado") == "pending":
        resumen["pendientes"].append(f"{rid} ({coleccion})")
# ==================================================================== CASOS DE PRUEBA REGLA M
# ====================================================================

def generar_casos_prueba(primer_numero):
    """Genera casos de prueba para Regla M (camino 1 y 2)."""
    id_camino1 = f"CYL-2026-E2-{primer_numero:04d}"
    id_camino2 = f"CYL-2026-E2-{primer_numero + 1:04d}"
    id_no_economico = f"CYL-2026-E2-{primer_numero + 2:04d}"

    # CAMINO 1: Desglose verificado con estados mixtos
    camino1_burgos = {
        "id": f"{id_camino1}-A",
        "fecha": "12/02/2026",
        "titular": "La Junta destina 300.000 euros al escenario de Semana Santa en tres provincias",
        "provincia": "Burgos",
        "localidad": "Burgos",
        "fuente": "Ical",
        "link": "https://www.ical.es/ejemplo-multi",
        "estado": "verified",
        "grupo": "Semana Santa 2026",
        "alcance": "burgos|valladolid|zamora",
        "origen": "Junta de Castilla y León",
        "destino": "Junta de Cofradías",
        "cantidad": 80000,
        "concepto": "Subvención escenario Semana Santa — desglose provincial verificado",
        "act": "CF",
        "gru": "EC",
        "notas": f"Regla M — pieza multiterritorial con desglose provincial. Id base {id_camino1}"
    }
    
    camino1_valladolid = {
        "id": f"{id_camino1}-B",
        "fecha": "12/02/2026",
        "titular": "La Junta destina 300.000 euros al escenario de Semana Santa en tres provincias",
        "provincia": "Valladolid",
        "localidad": "Valladolid",
        "fuente": "Ical",
        "link": "https://www.ical.es/ejemplo-multi",
        "estado": "pending",  # Mixto: pending para probar independencia
        "grupo": "Semana Santa 2026",
        "alcance": "burgos|valladolid|zamora",
        "origen": "Junta de Castilla y León",
        "destino": "Junta de Cofradías",
        "cantidad": 120000,
        "concepto": "Subvención escenario Semana Santa — desglose provincial verificado",
        "act": "CF",
        "gru": "EC",
        "notas": f"Regla M — pieza multiterritorial con desglose provincial. Id base {id_camino1}. Verificación — BOCyL, probable marzo 2026"
    }
    
    camino1_zamora = {
        "id": f"{id_camino1}-C",
        "fecha": "12/02/2026",
        "titular": "La Junta destina 300.000 euros al escenario de Semana Santa en tres provincias",
        "provincia": "Zamora",
        "localidad": "Zamora",
        "fuente": "Ical",
        "link": "https://www.ical.es/ejemplo-multi",
        "estado": "verified",
        "grupo": "Semana Santa 2026",
        "alcance": "burgos|valladolid|zamora",
        "origen": "Junta de Castilla y León",
        "destino": "Junta de Cofradías",
        "cantidad": 100000,
        "concepto": "Subvención escenario Semana Santa — desglose provincial verificado",
        "act": "CF",
        "gru": "EC",
        "notas": f"Regla M — pieza multiterritorial con desglose provincial. Id base {id_camino1}"
    }
    
    # CAMINO 2: residuo asignado por orden alfabético (Burgos y Valladolid).
    campos_comunes_camino2 = {
        "fecha": "12/02/2026",
        "titular": "La Junta destina 100.001 euros a actuaciones de Semana Santa en tres provincias",
        "fuente": "Ical",
        "link": "https://www.ical.es/ejemplo-multi-estimado",
        "grupo": "Semana Santa 2026",
        "alcance": "burgos|valladolid|zamora",
        "origen": "Junta de Castilla y León",
        "destino": "Junta de Cofradías",
        "act": "CF",
        "gru": "EC",
    }
    notas_camino2 = (
        "Regla M — sin desglose provincial. Verificación — BOCyL, "
        "resolución de concesión, probable marzo 2026"
    )
    concepto_camino2 = (
        "desglose estimado proporcional — total 100001 euros para tres provincias"
    )
    camino2_burgos = {
        "id": f"{id_camino2}-A",
        **campos_comunes_camino2,
        "provincia": "Burgos",
        "localidad": "Burgos",
        "cantidad": 33334,
        "concepto": concepto_camino2,
        "estado": "pending",
        "notas": notas_camino2,
    }
    
    camino2_valladolid = {
        "id": f"{id_camino2}-B",
        **campos_comunes_camino2,
        "provincia": "Valladolid",
        "localidad": "Valladolid",
        "cantidad": 33334,
        "concepto": concepto_camino2,
        "estado": "pending",
        "notas": notas_camino2,
    }
    
    camino2_zamora = {
        "id": f"{id_camino2}-C",
        **campos_comunes_camino2,
        "provincia": "Zamora",
        "localidad": "Zamora",
        "cantidad": 33333,
        "concepto": concepto_camino2,
        "estado": "pending",
        "notas": notas_camino2,
    }
    
    # Caso no económico de nacimiento (Ejemplo 3 del prompt)
    no_economico = {
        "id": id_no_economico,
        "fecha": "20/03/2026",
        "titular": "Ávila queda fuera del programa de apertura de monumentos en Semana Santa 2026",
        "provincia": "Ávila",
        "localidad": "Ávila",
        "fuente": "Ávilared",
        "link": "https://avilared.com/art/90714",
        "estado": "verified",
        "grupo": "Turismo religioso",
        "act": "CU"
        # Sin gru porque no hay receptor identificable, sin campos económicos
    }
    
    return [
        ("eje2", camino1_burgos),
        ("eje2", camino1_valladolid),
        ("eje2", camino1_zamora),
        ("eje2", camino2_burgos),
        ("eje2", camino2_valladolid),
        ("eje2", camino2_zamora),
        ("eje2", no_economico),
    ]

def generarBloqueF(resumen):
    """Genera el Bloque F de seguimiento."""
    lines = ["## BLOQUE F · Resumen de cambios y seguimiento", ""]
    lines.append(f"**Fecha de migración:** {resumen['fecha']}")
    lines.append("")
    lines.append("### 1. IDs creados por fichero")
    for fichero, rango in resumen['ids_nuevos'].items():
        lines.append(f"- **{fichero}:** {rango}")
    lines.append("")
    lines.append("### 2. IDs actualizados o reclasificados")
    if resumen['actualizados']:
        for item in resumen['actualizados']:
            lines.append(f"- {item}")
    else:
        lines.append("- —")
    lines.append("")
    lines.append("### 3. Descartes")
    lines.append("- —")
    lines.append("")
    lines.append("### 4. Pendientes")
    if resumen['pendientes']:
        for item in resumen['pendientes']:
            lines.append(f"- {item}")
    else:
        lines.append("- —")
    lines.append("")
    lines.append("### 5. Ambigüedades de act, gru o eje resueltas por criterio propio")
    if resumen['ambigüedades']:
        for item in resumen['ambigüedades']:
            lines.append(f"- {item}")
    else:
        lines.append("- —")
    lines.append("")
    lines.append("### 6. Categorías nuevas de origen")
    lines.append("- —")
    lines.append("")
    lines.append("### 7. Piezas multiterritoriales")
    if resumen['multiterritoriales']:
        for item in resumen['multiterritoriales']:
            lines.append(f"- {item}")
    else:
        lines.append("- —")
    lines.append("")
    lines.append("### 8. Capellanías y educación añadidas o actualizadas")
    if resumen['capellanias_edu']:
        for item in resumen['capellanias_edu']:
            lines.append(f"- {item}")
    else:
        lines.append("- —")
    return "\n".join(lines)

# ==================================================================== MAIN
# ====================================================================

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Migrador YAML v1.2 → v1.5")
    ap.add_argument("--input", default="yaml", help="Carpeta con YAML originales")
    ap.add_argument("--output", default="yaml_migrado", help="Carpeta destino")
    args = ap.parse_args()
    
    input_dir = Path(args.input)
    output_dir = Path(args.output)

    if not input_dir.is_dir():
        ap.error(f"la carpeta de entrada no existe: {input_dir}")
    if input_dir.resolve() == output_dir.resolve():
        ap.error("la carpeta de salida debe ser distinta de la entrada")

    entradas = {
        "eje2": archivos_coleccion(input_dir, "eje2"),
        "eje3": archivos_coleccion(input_dir, "eje3"),
        "capellanias": archivos_coleccion(input_dir, "capellanias"),
        "convenios": archivos_coleccion(input_dir, "convenios"),
    }
    if not any(entradas.values()):
        ap.error(f"no se encontraron YAML de entrada en {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    
    resumen = {
        'fecha': date.today().strftime('%d/%m/%Y'),
        'ids_nuevos': {},
        'actualizados': [],
        'pendientes': [],
        'ambigüedades': [],
        'multiterritoriales': [],
        'capellanias_edu': []
    }
    
    stats = {
        'eje2': {'total': 0, 'sin_programa': 0, 'con_act': 0, 'gru_migrado': 0},
        'eje3': {'total': 0, 'sin_programa': 0, 'con_act': 0, 'gru_migrado': 0},
    }
    
    # Procesar eje2
    eje2_output = []
    for yaml_file in entradas["eje2"]:
        data = leer_registros(yaml_file)
        for reg in data:
            stats['eje2']['total'] += 1
            programa_old = reg.get("programa")
            gru_old = reg.get("gru")
            act_old = reg.get("act")
            campos_retirados = "tipo_e2" in reg
            act, gru_migrado = migrar_eje2(reg, programa_old)
            if programa_old is None:
                stats['eje2']['sin_programa'] += 1
            stats['eje2']['con_act'] += 1
            if gru_migrado:
                stats['eje2']['gru_migrado'] += 1
            registrar_cambios(resumen, reg, "eje2", programa_old, gru_old,
                              act_old, campos_retirados)
            eje2_output.append(reg)
    
    # Agregar casos de prueba Regla M a eje2
    numeros_existentes = [
        int(match.group(1))
        for reg in eje2_output
        if (match := re.fullmatch(
            r"CYL-\d{4}-E2-(\d{4})(?:-[A-Z])?",
            str(reg.get("id", ""))))
    ]
    primer_numero = max(numeros_existentes, default=0) + 1
    if primer_numero + 2 > 9999:
        ap.error("no quedan tres IDs E2 disponibles para los casos de prueba")
    casos = generar_casos_prueba(primer_numero)
    for coleccion, caso in casos:
        if coleccion == "eje2":
            eje2_output.append(caso)
            if caso.get("estado") == "pending":
                resumen['pendientes'].append(f"{caso['id']} (eje2, Regla M)")
    resumen['multiterritoriales'].extend([
        f"CYL-2026-E2-{primer_numero:04d} → burgos|valladolid|zamora → camino 1 (desglose verificado)",
        f"CYL-2026-E2-{primer_numero + 1:04d} → burgos|valladolid|zamora → camino 2 (estimado, pending)",
    ])
    resumen['ids_nuevos']['eje2'] = (
        f"CYL-2026-E2-{primer_numero:04d} a "
        f"CYL-2026-E2-{primer_numero + 2:04d} (casos prueba Regla M)"
    )
    
    # Guardar eje2
    with open(output_dir / "eje2.yaml", "w", encoding="utf-8") as f:
        yaml.dump(eje2_output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # Procesar eje3
    eje3_output = []
    for yaml_file in entradas["eje3"]:
        data = leer_registros(yaml_file)
        for reg in data:
            stats['eje3']['total'] += 1
            programa_old = reg.get("programa")
            gru_old = reg.get("gru")
            act_old = reg.get("act")
            campos_retirados = "tipo_e2" in reg
            act, gru_migrado = migrar_eje3(reg, programa_old)
            if programa_old is None:
                stats['eje3']['sin_programa'] += 1
            stats['eje3']['con_act'] += 1
            if gru_migrado:
                stats['eje3']['gru_migrado'] += 1
            registrar_cambios(resumen, reg, "eje3", programa_old, gru_old,
                              act_old, campos_retirados)
            eje3_output.append(reg)
    
    resumen['ids_nuevos']['eje3'] = "Sin nuevos IDs (solo migración)"
    
    with open(output_dir / "eje3.yaml", "w", encoding="utf-8") as f:
        yaml.dump(eje3_output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # Procesar capellanias
    capellanias_output = []
    for yaml_file in entradas["capellanias"]:
        data = leer_registros(yaml_file)
        for reg in data:
            programa_old = reg.get("programa")
            gru_old = reg.get("gru")
            act_old = reg.get("act")
            retirados = "programa" in reg or "tipo_e2" in reg
            migrar_capellanias(reg)
            registrar_cambios(resumen, reg, "capellanias", programa_old,
                              gru_old, act_old,
                              retirados)
            capellanias_output.append(reg)
            resumen['capellanias_edu'].append(f"{reg.get('provincia')} → {reg.get('subtipo')} → {reg.get('periodo')}")
    
    resumen['ids_nuevos']['capellanias'] = "Sin cambios"
    
    with open(output_dir / "capellanias.yaml", "w", encoding="utf-8") as f:
        yaml.dump(capellanias_output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # Procesar convenios
    convenios_output = []
    for yaml_file in entradas["convenios"]:
        data = leer_registros(yaml_file)
        for reg in data:
            programa_old = reg.get("programa")
            gru_old = reg.get("gru")
            act_old = reg.get("act")
            retirados = "programa" in reg or "tipo_e2" in reg
            migrar_convenios(reg)
            registrar_cambios(resumen, reg, "convenios", programa_old,
                              gru_old, act_old, retirados)
            convenios_output.append(reg)
    
    resumen['ids_nuevos']['convenios'] = "Sin cambios"
    
    with open(output_dir / "convenios.yaml", "w", encoding="utf-8") as f:
        yaml.dump(convenios_output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # Crear educacion (nuevo)
    educacion_output = crear_educacion()
    resumen['ids_nuevos']['educacion'] = "Nuevo archivo creado"
    
    with open(output_dir / "educacion.yaml", "w", encoding="utf-8") as f:
        yaml.dump(educacion_output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    # Generar Bloque F
    bloque_f_content = generarBloqueF(resumen)
    with open(output_dir / "BLOQUE_F.md", "w", encoding="utf-8") as f:
        f.write(bloque_f_content)
    
    # Imprimir resumen
    print("=" * 60)
    print("MIGRACIÓN COMPLETADA")
    print("=" * 60)
    print(f"\nEJE2: {stats['eje2']['total']} registros → {stats['eje2']['con_act']} con act")
    print(f"EJE3: {stats['eje3']['total']} registros → {stats['eje3']['con_act']} con act")
    print(f"\nArchivos generados en '{output_dir}':")
    print(f"  - eje2.yaml")
    print(f"  - eje3.yaml")
    print(f"  - capellanias.yaml")
    print(f"  - convenios.yaml")
    print(f"  - educacion.yaml (nuevo)")
    print(f"  - BLOQUE_F.md")
    print("\nSiguiente paso: ejecutar 'python build.py --check' sobre yaml_migrado/")

if __name__ == "__main__":
    main()