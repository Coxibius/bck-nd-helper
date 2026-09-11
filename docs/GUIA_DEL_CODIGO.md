# Guía de lectura: recorrido de `bck-nd prompt .`

Esta guía explica cómo seguir una ejecución real de `bck-nd prompt .` sin intentar memorizar todo el repositorio. La idea central es separar tres preguntas: quién interpreta la orden, quién obtiene el conocimiento técnico y de producto, y quién lo convierte en un contexto compacto para una IA.

## Mapa de responsabilidades

- **CLI:** [`cli.py`](../src/bck_nd_hlpr/cli/cli.py) define comandos y opciones, presenta el progreso y decide si la salida va a un archivo o a `stdout`. No debería contener reglas de análisis ni de selección de producto.
- **Orquestación y análisis técnico:** [`orchestrator.py`](../src/bck_nd_hlpr/core/orchestrator.py) coordina `bck-nd scan`; los analizadores inferiores, como `ProjectScanner`, los parsers ER y el indexador, son reutilizables. `prompt` no llama a `ScannerOrchestrator`: usa esos mismos motores desde `ContextDumper`.
- **Product y Requirements:** [`product/renderer.py`](../src/bck_nd_hlpr/core/product/renderer.py) carga, valida, selecciona y presupuesta PRD; [`requirements/parser.py`](../src/bck_nd_hlpr/core/requirements/parser.py) carga historias y [`requirements/renderer.py`](../src/bck_nd_hlpr/core/requirements/renderer.py) produce su bloque acotado. Product explica intención y alcance; Requirements, comportamiento verificable.
- **Construcción del contexto:** [`context_dumper.py`](../src/bck_nd_hlpr/core/context_dumper.py) es el ensamblador. Mantiene caches de la ejecución, pide cada sección a su dueño y fija el orden final.
- **Lectura, cache y escritura compartidas:** [`FileSystemIndexer`](../src/bck_nd_hlpr/core/utils/indexer.py) crea el inventario seguro; [`FileCache`](../src/bck_nd_hlpr/core/utils/cache.py) lee y reutiliza contenido verificado; [`atomic_write_explicit_output`](../src/bck_nd_hlpr/core/utils/secure_write.py) publica el archivo sin una escritura parcial. El delta cache pertenece al flujo de `scan`, no al de `prompt`.

## Recorrido real de `bck-nd prompt .`

1. **Entrada y opciones.** Typer entra en `prompt_cmd()` de `cli.py`. `path` vale `.` por defecto; `output`, `ai_context.txt`. Allí se detecta si el usuario pidió un modo focused (`--tree`, `--uml` o `--er`), si debe incluir PRD/requirements, los presupuestos, `--copy` y el límite de archivos centrales. Un nombre de salida predeterminado puede adaptarse al modo focused. El proyecto se normaliza después como ruta absoluta dentro de `ContextDumper`; una salida relativa, en cambio, se interpreta desde el directorio de trabajo del proceso.

2. **Inventario inicial.** El constructor de `ContextDumper` crea un `GitIgnoreMatcher` y una única instantánea `FileIndex` con `FileSystemIndexer.build()`. Esta lista clasificada se reutiliza en UML, ER, selección de archivos centrales y cálculo del tamaño bruto. Las lecturas pasan por `FileCache`, que verifica contención y estado del archivo antes de cachearlo. Si la frontera de lectura no puede construir un inventario seguro, el dumper continúa con uno vacío.

3. **Ruta de presentación.** Con `-o -`, la CLI llama directamente a `build()` o `build_focused()` y reserva `stdout` para el contexto. Con salida a archivo, primero puede solicitar árbol, UML y ER para mostrar progreso en Rich y luego construir el resultado. UML y ER quedan cacheados en memoria, por lo que el ensamblado no vuelve a analizarlos. El árbol es una excepción importante: `generate_project_tree()` hace su propio recorrido protegido, aunque comparte raíz, profundidad y matcher de `.gitignore`.

4. **Producto y requisitos.** Al comenzar el ensamblado, `get_product_context()` delega en `build_product_context()`. Este usa `ProductService`, valida la colección, filtra por estado y `applies_to`, redacta valores del repositorio y aplica un presupuesto estructural antes de serializar JSON estricto dentro de `<product_context>`. Si se usa `--no-prd`, esa carga ni siquiera comienza. Después, `get_requirements_result()` carga una vez la colección y sus llamadas hermanas reutilizan el resultado para el informe de scope y `<requirements_context>`; `--no-req` corta también este camino. Los diagnósticos de documentos inválidos permanecen en sus bloques seguros; un fallo excepcional controlado no derriba el prompt.

5. **Secciones técnicas.** En el contexto completo siguen el árbol, UML y ER. `get_uml_diagram()` llama a `ProjectScanner.scan_uml(..., file_index=...)`; `get_er_diagram()` llama a `parse_project_for_er(..., file_index=...)` y luego a `generate_mermaid_er()`. En un modo focused sólo se añaden las secciones técnicas pedidas, pero Product y Requirements permanecen por defecto: `--no-prd` y `--no-req` producen el contexto estrictamente técnico.

6. **Archivos centrales.** Sólo `build()` completo ejecuta `get_core_files()`. Primero reúne candidatos permitidos desde el `FileIndex`. Para backends pondera puntos de entrada, centralidad de dependencias, pistas de dominio y nombres conocidos; para proyectos móviles usa grupos explícitos. `DependencyTracker` recibe el mismo inventario. Cada elegido se lee con `FileCache`, se sanitiza y, cuando corresponde, se trunca antes de entrar en `<core_files>`.

7. **Ensamblado y sanitización.** El orden normal es Product, scope/Requirements, árbol, UML, ER y archivos centrales. `build_focused()` conserva el mismo orden relativo para las partes presentes. Al final, `sanitize_text()` procesa el documento unido como una segunda frontera defensiva. Los presupuestos de Product, Requirements y archivos se resuelven antes; no se corta a ciegas el documento final.

8. **Entrega y métricas.** `stdout` se imprime directamente; un archivo se guarda mediante `atomic_write_explicit_output()`. Si se pidió `--copy`, la CLI copia exactamente el contexto ya construido. Finalmente calcula bytes UTF-8, tokens aproximados a 3,5 caracteres por token y ahorro frente a los archivos fuente del `FileIndex`. En modo `stdout`, estas métricas van a `stderr` para no contaminar la salida canalizable.

## Esquema breve de llamadas

```text
prompt_cmd
└─ ContextDumper.__init__
   └─ FileSystemIndexer.build → FileIndex compartido
└─ ContextDumper.build | build_focused
   ├─ build_product_context → ProductService
   ├─ RequirementsParser.load_collection → render_requirements_context
   ├─ generate_project_tree                         [si corresponde]
   ├─ ProjectScanner.scan_uml                       [si corresponde]
   ├─ parse_project_for_er → generate_mermaid_er    [si corresponde]
   ├─ ContextDumper.get_core_files                  [sólo contexto completo]
   └─ sanitize_text
└─ print | atomic_write_explicit_output
└─ copy_to_clipboard                                [con --copy]
└─ calculate_context_metrics
```

## `scan` frente a `prompt`

`scan` busca responder “¿qué encontró el analizador?”: `ScannerOrchestrator.run()` construye un inventario, ejecuta reportes —varios concurrentemente— y puede usar delta cache o entregar JSON. `prompt` responde “¿qué contexto acotado debería recibir una IA?”: `ContextDumper` ordena Product, Requirements y evidencia técnica, selecciona archivos y aplica presupuestos. No son dos analizadores independientes. Comparten el indexador seguro y agregadores como UML/ER; cambia la coordinación y el formato de entrega.

## Cinco puntos de lectura

1. **[`prompt_cmd`](../src/bck_nd_hlpr/cli/cli.py):** pregunta “¿qué decisiones son interfaz de usuario?”. Observa las ramas `output == "-"` y focused. Omite por ahora el estilo Rich.
2. **[`ContextDumper`](../src/bck_nd_hlpr/core/context_dumper.py):** pregunta “¿qué se calcula una vez y qué se ensambla después?”. Observa constructor, `build()` y `build_focused()`. Omite heurísticas internas en la primera pasada.
3. **[`FileSystemIndexer.build`](../src/bck_nd_hlpr/core/utils/indexer.py):** pregunta “¿qué archivos pueden llegar a los analizadores?”. Observa seguridad, profundidad y `.gitignore`. Omite primero los detalles de patrones.
4. **[`build_product_context`](../src/bck_nd_hlpr/core/product/renderer.py):** pregunta “¿cómo se convierte intención no confiable en JSON acotado?”. Observa selección, sanitización y presupuesto. Omite las búsquedas binarias de ajuste.
5. **[`ContextDumper.get_core_files`](../src/bck_nd_hlpr/core/context_dumper.py):** pregunta “¿por qué entra este archivo y no otro?”. Observa prioridad, centralidad y lectura segura. Omite inicialmente pesos y excepciones móviles.

## Comprobaciones de aprendizaje

1. **¿Por qué `bck-nd prompt . -o -` puede encadenarse sin que las métricas rompan el contexto?** Pista: sigue el argumento `err` desde `_print_context_metrics()`.
2. **¿Qué evita que UML y ER se recalculen al mostrar progreso y luego ensamblar?** Pista: busca los booleanos `*_cached` del dumper; compáralos con el árbol.
3. **¿Dónde se garantiza que `--no-prd` no sólo oculte, sino que evite cargar PRD?** Pista: sigue `include_prd` desde `prompt_cmd()` hasta la primera condición de `get_product_context()`.
