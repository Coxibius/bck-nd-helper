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

En Windows, si un temporal anterior está bloqueado, crea uno nuevo y exclusivo **fuera del repositorio** para cada ejecución; no cambies permisos ni reutilices el bloqueado:

```powershell
$testTemp = Join-Path ([System.IO.Path]::GetTempPath()) ("bck-nd-pytest-" + [guid]::NewGuid().ToString("N"))
.\venv\Scripts\python.exe -m pytest tests/test_mcp_boundary.py -q --basetemp $testTemp
```

`fixtures/uml_inheritance_sample.py` y `test_project/` son ejemplos de entrada; no son pruebas por sí solos. `manual_test_config.py` es una comprobación histórica manual de configuración personalizada, hoy solapada parcialmente por `test_config.py`. `run_asg_tests.py` es un runner manual histórico que comprueba aspectos también presentes en `test_asg.py`; no se integra automáticamente en pytest. Se conservan, pero sus resultados impresos no sustituyen las assertions de la suite.

La comprobación real del portal HTML en un navegador es un paso **separado y opcional**: `node tests/browser/check_docs.cjs <ruta-a-index.html> <ruta-a-capturas>` requiere Playwright y un navegador instalados. El workflow actual de GitHub Pages publica documentación; no ejecuta esta suite de pytest.
