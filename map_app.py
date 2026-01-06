#!/usr/bin/env python3
"""
Flask App File Mapper - READ ONLY - DOCUMENTATION TOOL
Maps your Flask app structure and documents all files.
"""

import os
import re
import json
from pathlib import Path
from typing import Set, Dict, List

MAIN_APP_FILE = "app.py"
IGNORE_DIRECTORIES = {'__pycache__', 'node_modules', '.git', 'venv', 'archive'}
IGNORE_DIRECTORY_PATTERNS = ['venv_', 'env_', '.']
OUTPUT_REPORT_FILE = "app_structure_map.json"

class AppMapper:
    def __init__(self, app_root: str):
        self.app_root = Path(app_root)
        self.dependency_chain: Set[Path] = set()
        self.all_project_files: Set[Path] = set()
        self.file_references: Dict[str, List[str]] = {}
        self.processed_files: Set[Path] = set()

    def _should_ignore_path(self, path: Path) -> bool:
        for part in path.parts:
            if part in IGNORE_DIRECTORIES:
                return True
            for pattern in IGNORE_DIRECTORY_PATTERNS:
                if part.startswith(pattern):
                    return True
        return False

    def map_all(self, starting_file: str = None) -> Dict:
        if starting_file is None:
            starting_file = MAIN_APP_FILE

        start_path = self.app_root / starting_file
        if not start_path.exists():
            print(f"Starting file {start_path} not found!")
            return {}

        self._discover_all_files()

        files_to_process = [start_path]

        while files_to_process:
            current_batch = files_to_process.copy()
            files_to_process.clear()

            for current_file in current_batch:
                if current_file in self.processed_files or self._should_ignore_path(current_file):
                    continue
                if not current_file.exists():
                    continue

                self.processed_files.add(current_file)
                self.dependency_chain.add(current_file)

                new_files = []
                if current_file.suffix == '.py':
                    new_files = self._map_python_file(current_file)
                elif current_file.suffix in ['.html', '.htm']:
                    new_files = self._map_html_file(current_file)
                elif current_file.suffix == '.css':
                    new_files = self._map_css_file(current_file)
                elif current_file.suffix == '.js':
                    new_files = self._map_js_file(current_file)

                for new_file in new_files:
                    if new_file not in self.processed_files and not self._should_ignore_path(new_file):
                        files_to_process.append(new_file)

        return self._generate_report()

    def _discover_all_files(self):
        for root, dirs, files in os.walk(self.app_root):
            dirs[:] = [d for d in dirs if not self._should_ignore_path(Path(root) / d)]
            for file in files:
                if not file.startswith('.') and not file.endswith('.pyc'):
                    file_path = Path(root) / file
                    if not self._should_ignore_path(file_path):
                        self.all_project_files.add(file_path)

    def _map_python_file(self, file_path: Path) -> List[Path]:
        new_files = []
        try:
            content = file_path.read_text(encoding='utf-8')
            relative_path = str(file_path.relative_to(self.app_root))
            self.file_references[relative_path] = []

            # Python imports
            for pattern in [r'from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+import', r'from\s+\.([a-zA-Z_][a-zA-Z0-9_.]*)\s+import']:
                for match in re.findall(pattern, content):
                    module_parts = match.split('.')
                    for p in [file_path.parent / f"{module_parts[0]}.py",
                              self.app_root / "utilities" / f"{module_parts[0]}.py",
                              self.app_root / f"{match.replace('.', '/')}.py"]:
                        if p.exists():
                            new_files.append(p)
                            self.file_references[relative_path].append(str(p.relative_to(self.app_root)))
                            break

            # Templates
            for match in re.findall(r"render_template\(\s*['\"]([^'\"]+)['\"]", content):
                for p in [self.app_root / "templates" / match]:
                    if p.exists():
                        new_files.append(p)
                        self.file_references[relative_path].append(str(p.relative_to(self.app_root)))
                        break

            # Static files
            for match in re.findall(r"url_for\(\s*['\"]static['\"],\s*filename\s*=\s*['\"]([^'\"]+)['\"]", content):
                p = self.app_root / "static" / match
                if p.exists():
                    new_files.append(p)
                    self.file_references[relative_path].append(f"static/{match}")
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
        return new_files

    def _map_html_file(self, file_path: Path) -> List[Path]:
        new_files = []
        try:
            content = file_path.read_text(encoding='utf-8')
            relative_path = str(file_path.relative_to(self.app_root))
            self.file_references[relative_path] = []

            patterns = [
                (r'{%\s*extends\s+["\']([^"\']+)["\']', 'templates'),
                (r'{%\s*include\s+["\']/?([^"\']+)["\']', 'templates'),
                (r'href\s*=\s*["\'][/]?static/([^"\']+)["\']', 'static'),
                (r'src\s*=\s*["\'][/]?static/([^"\']+)["\']', 'static'),
                (r"url_for\s*\(\s*['\"]static['\"]\s*,\s*filename\s*=\s*['\"]([^'\"]+)['\"]", 'static'),
            ]

            for pattern, base_dir in patterns:
                for match in re.findall(pattern, content):
                    p = self.app_root / base_dir / match
                    if p.exists():
                        new_files.append(p)
                        self.file_references[relative_path].append(f"{base_dir}/{match}")
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
        return new_files

    def _map_css_file(self, file_path: Path) -> List[Path]:
        new_files = []
        try:
            content = file_path.read_text(encoding='utf-8')
            relative_path = str(file_path.relative_to(self.app_root))
            self.file_references[relative_path] = []

            for match in re.findall(r'url\(["\']?([^"\')\s]+)["\']?\)', content):
                if not match.startswith(('http', 'data:', '#')):
                    p = file_path.parent / match
                    if p.exists():
                        new_files.append(p)
                        self.file_references[relative_path].append(str(p.relative_to(self.app_root)))
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
        return new_files

    def _map_js_file(self, file_path: Path) -> List[Path]:
        relative_path = str(file_path.relative_to(self.app_root))
        self.file_references[relative_path] = []
        return []

    def _generate_report(self) -> Dict:
        chain = sorted([str(f.relative_to(self.app_root)) for f in self.dependency_chain])
        all_files = sorted([str(f.relative_to(self.app_root)) for f in self.all_project_files])
        not_in_chain = sorted([f for f in all_files if f not in chain])

        return {
            'summary': {
                'total_files': len(all_files),
                'in_chain': len(chain),
                'not_in_chain': len(not_in_chain)
            },
            'dependency_chain': chain,
            'not_in_chain': not_in_chain,
            'references': self.file_references
        }

if __name__ == "__main__":
    mapper = AppMapper(".")
    report = mapper.map_all()

    with open(OUTPUT_REPORT_FILE, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Total files: {report['summary']['total_files']}")
    print(f"In dependency chain: {report['summary']['in_chain']}")
    print(f"NOT in chain: {report['summary']['not_in_chain']}")
    print(f"\nFiles NOT in dependency chain:")
    for f in report['not_in_chain']:
        print(f"  - {f}")
