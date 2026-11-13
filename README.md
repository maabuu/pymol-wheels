# Open-source PyMOL wheels

This project builds Python wheels for release tags and arbitrary commits of the open-source version of PyMOL using GitHub Actions and makes them available on the [GitHub release page](https://github.com/maabuu/pymol-wheels/releases/).

Thanks to the original creator Warren L. DeLano for creating PyMOL and to Schrödiger for maintaining it.

- [PyMOL source code](https://github.com/schrodinger/pymol-open-source)
- [PyMOL open-source foundation](https://pymol.org/#opensource)
- [PyMOL license](https://github.com/schrodinger/pymol-open-source/blob/master/LICENSE)

## Versions

Upstream changes its version number rarely, so wheels built from its development branch are numbered `<upstream version>.post<N>`, where `N` is the number of commits in the upstream history at the commit that was built. For example, `3.2.0a0.post5859` is upstream version `3.2.0a` at its 5859th commit. Wheels built from an upstream release tag carry the upstream version unchanged.

## License

A copy of the [PyMOL license](licenses/PYMOL_LICENSE) containing the PyMOL copyright notice and license terms is included.
