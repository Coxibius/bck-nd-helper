import pytest
from pathlib import Path
from bck_nd_hlpr.context_dumper import ContextDumper
from bck_nd_hlpr.tree_generator import generate_project_tree

def _create_project(tmp_path, structure: dict):
    for name, content in structure.items():
        if name.endswith("/"):
            dir_path = tmp_path / name.rstrip("/")
            dir_path.mkdir(parents=True, exist_ok=True)
            if isinstance(content, dict):
                _create_project(dir_path, content)
        else:
            file_path = tmp_path / name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

def test_expo_project_detection_and_prioritization(tmp_path):
    # Create an Expo project structure
    _create_project(tmp_path, {
        "app.json": "{}",
        "package.json": "{}",
        "App.js": "export default function App() {}",
        "app/": {
            "index.tsx": "export default function Index() {}",
        },
        "src/": {
            "api/": {
                "auth.ts": "export const login = () => {};",
                "users.ts": "export const getUsers = () => {};",
            },
            "config/": {
                "firebase.ts": "export const db = {};",
            },
            "utils/": {
                "math.ts": "export const add = () => {};",
            },
        },
        "hooks/": {
            "useTheme.tsx": "export const useTheme = () => {};",
        },
    })

    # Test initialization detects mobile project and defaults max_core_files to 8
    dumper = ContextDumper(path=str(tmp_path))
    assert dumper.is_mobile is True
    assert dumper.max_core_files == 8

    # Check the prioritized core files list
    core_files = dumper.get_core_files()
    paths = [f["path"] for f in core_files]

    # Priority order:
    # 1. src/api/*.ts -> src/api/auth.ts, src/api/users.ts
    # 2. src/config/*.ts -> src/config/firebase.ts
    # 3. hooks/*.tsx -> hooks/useTheme.tsx
    # 4. app/index.tsx
    # 5. App.js
    # 6. src/utils/*.ts -> src/utils/math.ts
    expected_order = [
        "src/api/auth.ts",
        "src/api/users.ts",
        "src/config/firebase.ts",
        "hooks/useTheme.tsx",
        "app/index.tsx",
        "App.js",
        "src/utils/math.ts"
    ]
    
    assert paths == expected_order

def test_expo_router_detection_and_limit(tmp_path):
    # Create an Expo Router structure with _layout.tsx
    _create_project(tmp_path, {
        "app/": {
            "_layout.tsx": "export default function Layout() {}",
            "index.tsx": "export default function Index() {}",
        },
        "src/": {
            "api/": {
                "a.ts": "", "b.ts": "", "c.ts": "", "d.ts": "", "e.ts": "", "f.ts": "", "g.ts": "", "h.ts": "", "i.ts": ""
            }
        }
    })

    # Test initialization detects mobile project with _layout.tsx
    dumper = ContextDumper(path=str(tmp_path))
    assert dumper.is_mobile is True

    # Test configurable max_core_files limit (default is 8)
    core_files_default = dumper.get_core_files()
    assert len(core_files_default) == 8

    # Test custom max_core_files limit (e.g., 3)
    dumper_custom = ContextDumper(path=str(tmp_path), max_core_files=3)
    assert dumper_custom.max_core_files == 3
    core_files_custom = dumper_custom.get_core_files()
    assert len(core_files_custom) == 3
