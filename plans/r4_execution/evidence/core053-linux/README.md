# Linux installed conformance and public documentation

WSL Ubuntu, Linux kernel 5.15, CPython 3.13.14: **151 passed in 22.63 seconds**
against the same 0.2.53.dev0 wheel used on Windows. The installed runner verifies
package bytes and isolates application imports; manifest and JUnit are retained.
Its first invocation exposed a runner bug: resolving a Unix venv Python symlink
selected the base interpreter, producing ModuleNotFoundError before collection.
The runner now retains the absolute venv executable path without dereferencing
the final link. The successful run proves the venv package is actually consumed.

Hosted run 36958691625 at 33f3a2d failed in all six Windows/Linux Python 3.11–3.13
cells on the same two public-documentation tests only. Linux cells each reported
1167 passed, 2 failed, 21 skipped; Windows cells each reported 1111 passed,
2 failed, 77 skipped. The API guide omitted the two new exports and the version
guide still said .52. Documentation now describes executable R4 separately from
unchanged R3, with compatibility aliases and authority boundaries. All three
public-documentation tests passed against the installed .53 Core.

The failed hosted run stays failed; a new matrix must validate the correction.
This evidence does not qualify Linux native provider installations or independent
hosts and does not close final release gates.
