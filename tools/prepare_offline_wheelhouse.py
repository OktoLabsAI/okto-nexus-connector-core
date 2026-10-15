"""Download this interpreter's declared runtime and build dependencies for CI."""
from pathlib import Path
import subprocess
import sys
import tomllib


def main():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    requirements = [*project['build-system']['requires'], *project['project']['dependencies']]
    subprocess.run([
        sys.executable, '-m', 'pip', 'download', '--only-binary=:all:',
        '--dest', str(root / 'build/offline-wheelhouse'), *requirements,
    ], check=True)


if __name__ == '__main__':
    main()
