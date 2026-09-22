# Mapa de pruebas

Los módulos `test_*.py` son pruebas automáticas de pytest; `pyproject.toml` limita la recogida a `tests/`. La suite está mayormente plana para que cada responsabilidad sea fácil de localizar.

- **MCP:** `test_mcp_tools.py` cubre respuestas públicas; `test_mcp_boundary.py`, autorización de proyectos, aislamiento de archivos, salida segura y cierre; `test_mcp_installer.py`, configuraciones de clientes y concurrencia del instalador. La integración de `prompt --copy` vive en `test_clipboard.py`. Las comprobaciones de registro de todas las tools están junto a la frontera porque verifican que ninguna quede fuera de ella.
- **Requirements:** `test_requirements_models.py` cubre modelos; `test_requirements_parsing.py`, parsing y lectura/carga verificadas; `test_requirements_status.py`, transiciones y concurrencia; `test_requirements_cli.py`, comandos; `test_requirements_context.py`, ContextDumper y scan. `test_requirements_safety.py` concentra límites, rechazo de esquemas inseguros y renderizado acotado. `test_requirements_ux.py` y `test_requirements_locations.py` mantienen sus responsabilidades específicas.
- **Otros dominios:** `test_product_*.py` y `test_prd_cli.py` protegen PRD; `test_*uml*.py`, `test_*er*.py` y `test_tree_sitter.py` cubren análisis y parsing. `test_tree_sitter.py` sólo comprueba que la gramática C# pueda parsear su ejemplo sin errores: no es una prueba del extractor UML de Backend Helper. `test_write_boundary.py`, `test_filesystem_read_boundary.py` y `test_security.py` protegen fronteras de E/S y seguridad.

Al añadir una regresión, colócala junto al comportamiento que falló, sin importar módulos de prueba entre sí. Mantén los fixtures `autouse` en el menor alcance necesario. Si el caso describe una nueva frontera transversal, usa el módulo de frontera correspondiente en vez de mezclarlo con modelos o CLI.

Desde la raíz del repositorio, ejecuta un módulo o la suite completa con:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_requirements_status.py -q
.\venv\Scripts\python.exe -m pytest -q
```

## QA reproducible

Instala el proyecto de este checkout y la única dependencia de pruebas en el mismo entorno de Python:

```console
python -m pip install .
python -m pip install -r requirements-test.txt
python -m pip check
python scripts/run_qa.py
```

El runner usa ese mismo intérprete, funciona aunque se lance desde otro directorio y ejecuta toda la suite una sola vez. Crea una carpeta nueva fuera del repositorio y muestra su ubicación. Allí quedan `qa.log` (salida legible), `junit.xml` (resultado estructurado de pytest) y `summary.json` (estado, código de salida y conteos obtenidos del XML). Si pytest no llega a generar el XML, el resumen deja los conteos en `null`, conserva el diagnóstico disponible y devuelve error. Para elegir un destino nuevo y vacío, usa `python scripts/run_qa.py --report-dir <ruta-fuera-del-repositorio>`. Un fallo conserva un código de salida distinto de cero y no se reintenta ni se convierte en éxito.

Durante el desarrollo puedes ejecutar solamente un módulo, por ejemplo `python -m pytest tests/test_requirements_status.py -q`. En el resumen, **passed** indica una prueba satisfactoria, **failed** una aserción incumplida, **error** un problema de preparación, recogida o ejecución, y **skipped** una prueba que pytest omitió (por ejemplo, por capacidades de la plataforma). Consulta `qa.log` y `junit.xml` para la razón concreta; los skips pueden diferir entre Windows y Ubuntu.

La suite automática incluye los smoke de `test_cli_smoke.py`: arrancan procesos reales de `bck-nd` y `bck-nd-mcp` desde el entorno seleccionado y verifican `scan`, `prompt` y Requirements sobre un proyecto sintético. No sustituyen la revisión manual del portal HTML en un navegador. El workflow `QA` ejecuta este mismo runner en pull requests hacia `main`, pushes a `main` y manualmente, con Python 3.10/3.13 en Ubuntu/Windows. En la página **Actions** de GitHub, abre cada job de la matriz y descarga su artifact `qa-<sistema>-py<versión>` para leer los tres informes incluso cuando fallen tests. Para impedir merges con checks rojos, una persona administradora todavía debe configurar la protección de `main` y marcar como obligatorios los checks `QA` de la matriz; este cambio no altera esa protección.

En Windows, si un temporal anterior está bloqueado, crea uno nuevo y exclusivo **fuera del repositorio** para cada ejecución; no cambies permisos ni reutilices el bloqueado:

```powershell
$testTemp = Join-Path ([System.IO.Path]::GetTempPath()) ("bck-nd-pytest-" + [guid]::NewGuid().ToString("N"))
.\venv\Scripts\python.exe -m pytest tests/test_mcp_boundary.py -q --basetemp $testTemp
```

`fixtures/uml_inheritance_sample.py` y `test_project/` son ejemplos de entrada; no son pruebas por sí solos. `manual_test_config.py` es una comprobación histórica manual de configuración personalizada, hoy solapada parcialmente por `test_config.py`. `run_asg_tests.py` es un runner manual histórico que comprueba aspectos también presentes en `test_asg.py`; no se integra automáticamente en pytest. Se conservan, pero sus resultados impresos no sustituyen las assertions de la suite.

La comprobación real del portal HTML en un navegador es un paso **separado y opcional**: `node tests/browser/check_docs.cjs <ruta-a-index.html> <ruta-a-capturas>` requiere Playwright y un navegador instalados. El workflow de GitHub Pages publica documentación; el workflow `QA` independiente ejecuta pytest y no publica nada.
