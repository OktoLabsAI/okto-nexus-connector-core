# K11/TK-42 six-environment offline package check - 2026-09-26

The current Core development artifacts are wheel SHA-256
`c8df78f8165708bc4db717666efaf7f24e1ebbfb6b4b5091368a9096d9eb640b`
and sdist SHA-256
`ec330b7faa08417dd011fe98b057e51c0284c1f0251be965d210662a3b576cee`.
The normalized build produced these same bytes on Windows and WSL2.

`tools/verify_offline_artifacts.py` passed for each artifact on every local
Windows/WSL2 × Python 3.11/3.12/3.13 combination. Each run created fresh
isolated environments, installed from a platform/Python-specific local
wheelhouse with `--no-index --no-cache-dir`, checked the installed API,
`py.typed`, bundled NXL schemas/manifest and Pi extension, then exercised
embedded and remote synthetic consumers against the installed wheel. The
sdist built and installed offline without build isolation using locally
supplied setuptools/wheel.

The WSL2 interpreter/wheelhouse pairs were:

| Python | Interpreter | Wheelhouse |
|---|---|---|
| 3.11 | `/var/tmp/nexus-core-linux311-20260926/bin/python` | `/var/tmp/nexus-core-linux311-wheelhouse-20260926` |
| 3.12 | `/var/tmp/nexus-core-linux-xETnWZ/venv/bin/python` | `/var/tmp/nexus-core-wheelhouse-20260926` |
| 3.13 | `/var/tmp/nexus-core-linux313-20260926/bin/python` | `/var/tmp/nexus-core-linux313-wheelhouse-20260926` |

The Windows Python 3.11/3.12 environments used the matching
`nexus-core-win311-claims-20260926` and `nexus-core-win312-claims-20260926`
virtual environments and corresponding `nexus-core-win311-wheelhouse-20260926`
and `nexus-core-win312-wheelhouse-20260926` temporary wheelhouses. Python
3.13 used the system interpreter and `build/offline-wheelhouse`.

This closes the local six-environment offline-install check for these exact
artifact hashes, not TK-42 as a whole: hosted CI, native non-WSL Linux,
other architectures and real consumer applications remain unverified.
The development build is still `publishable:false` and was not published.

The later process-birth-record artifact pair (wheel
`01b315cf82881f55eb7349511bbe5bedb7a88e41c7fe39b4de6e92672ac26ced`,
sdist `84adc190d7ec6139443ccd8714d08cd22f5bab91bf15560918f6f4cc43e7e255`)
repeated and passed this same six-environment offline installation/resource
matrix. The same hosted/real-consumer limitations apply.

The subsequent synthetic factory integration test left that wheel unchanged
and changed only the sdist to
`a28decaf9eca334f171f9e05b4d13b48009808b01a2b58ffac9a1a89b446ec06`.
This final pair also passed the same six-environment offline matrix.

The later read-only process-birth-observation artifacts (wheel
`63f12188eb648867c33445e5d504ee57db5a60c3d6209837078479d4a0ac0383`,
sdist `d7ffbedf56a1fb13bd03379c733b3a33f8657a8f95d2c157a603a92c1a703cd9`)
also passed that six-environment offline matrix.
