# Arquitectura del pipeline de datos · Observatorio del laicismo (Castilla y León)

Documento de arquitectura del sistema de vigilancia: qué es cada pieza, por qué existe y qué decisiones de diseño la sostienen. Complementa — no sustituye — al prompt de codificación (v1.5) y al propio código (`build.py` v1.3), que son la referencia operativa.

---

## 1. Qué se ha construido

Un pipeline de datos con tres capas y una dirección única de flujo:

```
Barridos de vigilancia (informes de prensa, CSV del Observatorio)
        │
        ▼
   YAML maestros  ◄──── fuente de verdad (7 colecciones)
        │
        ▼
   build.py (validación + derivación + inyección)
        │
        ▼
   Informe HTML (Madre-v3.0 compilada) · CSV de verificación
```

**Siete colecciones en ficheros YAML:** cuatro ejes de vigilancia (`eje1`–`eje4`), capellanías (`capellanias`), educación (`educacion`) y convenios plurianuales (`convenios`). Cada registro es un elemento de lista plano; cada colección tiene su cabecera y campos propios; el espacio de numeración `CYL-AAAA-COL-NNNN` es cerrado e independiente por colección y año, y **nunca se renumera**.

**El motor** (`build.py`) valida los YAML (enums, fechas, continuidad de IDs, regla $, regla M, referencias cruzadas, duplicados), **deriva** lo que no se codifica (macro-programa desde `act`, `tipoE2` desde `act`, flujos de dinero desde los campos económicos de los ejes 2 y 3) e **inyecta** los literales JS en la plantilla HTML entre marcadores, generando el informe sin tocar la plantilla.

**La batería de pruebas** replica los casos límite del método (regla $ multilínea, regla M multiterritorial en sus dos caminos, duplicados, fechas aproximadas, casos mixtos con `reporte_id`) y se valida con `python build.py --check` antes de cada publicación.

---

## 2. Por qué YAML como fuente de verdad

El origen fue operativo, no teórico. El Observatorio aportaba sus datos en CSV, y se planteó la posibilidad de inyectarlos de forma automática al HTML mediante un script, eliminando la edición manual de datos en la plantilla.

**1. El CSV central fracasó por errores estructurales de la IA.** Al tratar de unificar los reportes hacia el CSV como formato central de cara a la inyección, la IA codificadora cometía errores sistemáticos de estructura: en campos vacíos omitía algún delimitador (`;`) y el siguiente valor se deslizaba a la columna equivocada, corrompiendo filas enteras sin que el error fuera visible al leer la tabla. El problema no era de contenido sino de formato: el CSV depende de delimitadores posicionales, y una omisión invisible desalinea todo lo que viene detrás.

**2. YAML resolvió el problema por diseño.** Al buscar una alternativa apareció YAML como la más adecuada por dos razones prácticas: la IA no cometía errores en él, y es un formato sencillo de visualizar y corregir para un humano. Cada dato vive bajo una clave (`origen:`, `cantidad:`), no en una posición fija; un campo vacío se representa omitiendo la clave, lo cual es válido, consistente y no desplaza ningún otro valor. La clase de error que hundió el CSV desaparece por construcción, no por disciplina.

**3. Al ascender el YAML a fuente de verdad, el CSV pasó a ser secundario.** Decidido que el YAML alimenta la inyección al HTML, el CSV del Observatorio quedó como una vía de entrada de datos — paralela a los reportes del barrido —, no como formato productivo. Y hay un motivo adicional de fondo: **los CSV del Observatorio no traen ID propia**, por lo que es en el YAML donde cada reporte recibe su identificador `CYL-AAAA-COL-NNNN`. El ID pertenece a este sistema, nace aquí y no puede depender de un formato de entrada que no lo conoce.

La consecuencia de arquitectura: una sola fuente de verdad (el YAML), dos vías de entrada (CSV del Observatorio y barridos de prensa) y un solo producto compilado (el informe HTML). Las anomalías que el compilador detecta (huecos de numeración, duplicados, cabeceras divergentes) se marcan `pending` para resolución manual — jamás se corrigen por su cuenta: el humano decide, la máquina vigila. El dato original queda literal, con sus imprecisiones documentadas en notas, porque un sistema de vigilancia no puede permitirse editar silenciosamente la evidencia que pretende vigilar.

---

## 3. Por qué las categorías ACT y GRU del Observatorio

Hasta la v1.2 del esquema, el sistema usaba clasificaciones propias: `programa` (cuatro macros de gasto) y `tipo_e2` (conservación/turismo), codificados a mano en cada registro, más un enum `gru` con siglas inventadas para las confesiones. Ese diseño tenía tres defectos que la adopción del vocabulario nativo del Observatorio elimina.

**Defecto 1: campos redundantes que derivaban contradicciones.** `programa` y `tipo_e2` eran casi derivables el uno del otro y ambos dependían de la disciplina del codificador; el error más frecuente del sistema era exactamente la contradicción interna (`tipo_e2:
conservacion` con `programa: Servicios sociales`). **Solución:** un solo clasificador primario codificado — `act` — y una tabla normativa en el motor (`TABLA_ACT`) de la que se derivan macro-programa y `tipoE2`. Una fuente única de clasificación elimina de raíz la clase de error que vigilaba a mano.

**Defecto 2: pérdida de información en la traducción.** El Observatorio trabaja con 18 temas (TEMAS) que incluían una familia completa de acción social (discapacidad, infancia, mayores, toxicomanías…); nuestros cuatro macros colapsaban ocho códigos en «Servicios sociales» — precisamente el desglose con más interés analítico para un informe de laicismo (¿a dónde va el dinero social: residencias de órdenes religiosas o infancia?). **Solución:** codificar `act` con el vocabulario completo del Observatorio; los macros se derivan para las vistas agregadas (y la comparabilidad histórica se conserva), pero la granularidad original queda disponible — y ya viaja en los flujos para un futuro sub-desglose de Servicios sociales sin tocar los datos.

**Defecto 3: doble traducción contra el socio.** Cada intercambio con el Observatorio exigía una capa de mapeo entre sus claves y las nuestras. **Solución:** adoptar su vocabulario literal. Cuando la fila viene de su CSV, `act` y `gru` se trasladan sin interpretación — la codificación se vuelve traslación pura, y el futuro importador de CSV queda libre de capa de traducción.

**La asimetría conceptual entre ambos campos, que es deliberada:**

- **`gru` clasifica al RECEPTOR** (GRUPOS del Observatorio, 12 valores): quién recibe el dinero — diócesis (ID), orden religiosa (OR), entidad católica con personalidad propia (EC), evangélica (EV), islámica (CI)… La pregunta es «¿quién?».
- **`act` clasifica el TEMA de la pieza** (TEMAS del Observatorio, 18 valores): qué se financia o de qué va la pieza. La taxonomía es deliberadamente híbrida — algunos códigos describen la actividad (RES, ED, familia AS), otros el tipo de receptor (CF, IC, HC, UC) y otros la finalidad (FUN) — porque es la que el Observatorio usa y no se le fuerza una pureza que nunca tuvo. La regla arbitral que resuelve el caso dudoso: **el receptor manda sobre el código, la actividad manda sobre el eje** (una cofradía siempre es CF, pero si restaura un paso va a eje 2 y si hace acción social, a eje 3).

La interacción entre ambos produce el enrutado completo: `act` decide el eje (RES, CU → eje 2; social, educación, sostén → eje 3; CF bifurca según la actividad), el eje y `act` juntos deciden el macro-programa, y `gru` alimenta los agrupados por tipo de beneficiario. Del literal del barrido a las vistas del informe, sin categorías intermedias codificadas a mano.

**Nota de namespaces:** `CH` significa cofradías en la era antigua de TEMAS (ahora `CF`) e hinduísta en GRUPOS. Son espacios independientes. Regla de migración de datos históricos: `CH` en la columna de TEMAS se migra a `CF`; `CH` en la de GRUPOS se lee como hinduísta.

---

## 4. Decisiones de diseño registradas

| Decisión | Motivo |
| - | - |
| IDs nunca se reasignan ni renumeran | Trazabilidad entre informes; el ID es un hecho histórico |
| Regla $ (multiaportante): mismo ID exacto, varias líneas | Es UN reporte con varias líneas económicas; la fusión la hace el motor |
| Regla M (multiterritorial): ID base + sufijo provincial `-A/-B/-C` | Unidad visible de la pieza + estados de verificación independientes por provincia; el sufijo no consume numeración |
| Camino 2 de regla M: reparto proporcional, `pending` obligatorio | La suma restituye el total literal; mientras esté pending, la cifra no computa |
| Piezas económicas sin cifra → `pending`; piezas no económicas → campos económicos omitidos sin penalización | No inundar la cola de revisión con piezas que jamás tendrán cifra |
| Capellanías y educación NO se codifican en los ejes con campos económicos | El motor deriva sus flujos; duplicarlas produciría doble cómputo en el eje 3. Caso mixto: pieza noticiosa sin economía en el eje + `reporte_id` en la colección |
| Organismos instrumentales (Sacyl, ILC) → administración matriz como `origen`, organismo en `notas` | El dinero público tiene un responsable político identificable |
| Codificación es traslación, no investigación | Ninguna cifra, fecha o nombre que no esté literal en el barrido; lo que falta se omite o queda `pending`, nunca se rellena |
| El motor detecta anomalías y marca `pending`; la resolución es siempre manual | El dato original queda literal y auditable; la corrección es un acto humano documentado |

---

## 5. Componentes y versiones

| Componente | Versión actual | Rol |
| - | - | - |
| `build.py` | v1.3 | Validación, derivación (TABLA\_ACT), inyección HTML |
| Prompt de codificación | v1.5 | Contrato del codificador (humano o IA) para convertir barridos en YAML |
| Esquema de datos | v1.3 | Campos por colección, enums ACT/GRU, reglas de método |
| Plantilla `Madre-v3.0.html` | — | Vista: agrupados por ETIQ\_GRU, sub-desglose de eje 2 vía `tipoE2` derivado |
| Batería de pruebas (`yaml/*.yaml`) | migrada al esquema v1.3 | Casos límite del método; validar con `--check` |

Changelog completo de esquema y motor en las cabeceras del prompt y de `build.py` respectivamente.

---

## 6. Líneas futuras

- **Importador CSV del Observatorio:** esqueletos YAML automáticos desde su CSV aprovechando la clave natural compartida (provincia + destino + periodo/fecha) — ahora sin capa de traducción de vocabulario.
- **Sub-desglose de Servicios sociales por ACT** en el informe: el dato ya viaja en los flujos.
- **Eliminación diferida de `tipoE2`** del JS de salida cuando la plantilla agrupe por `act` directamente.
- **Módulos nuevos:** inmatriculaciones e IRPF (placeholders).