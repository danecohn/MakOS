/* SPDX-License-Identifier: GPL-3.0-only
 * Keep a dedicated executable identity for KWin's restricted screenshot API.
 * Link the distribution's maintained Python shared library; never copy Python.
 */
#include <stdlib.h>
#include <stdio.h>

extern int Py_BytesMain(int argc, char **argv);

int main(int argc, char **argv)
{
    char **python_argv = calloc((size_t)argc + 3, sizeof(char *));
    if (!python_argv) {
        fputs("MakOS Shell: insufficient memory\n", stderr);
        return 1;
    }
    python_argv[0] = "/usr/bin/python3.14";
    python_argv[1] = "-m";
    python_argv[2] = "makos.shell.main";
    for (int i = 1; i < argc; ++i) python_argv[i + 2] = argv[i];
    int result = Py_BytesMain(argc + 2, python_argv);
    free(python_argv);
    return result;
}
