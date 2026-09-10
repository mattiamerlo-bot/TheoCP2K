# TheoDORE CP2K NTO-cube GUI

This extension reads converged CP2K TDDFPT output together with the NTO hole and
particle cube files produced by `PRINT/NTO_ANALYSIS`. It adds a desktop workflow
without changing TheoDORE's existing transition-density analysis.

The source bundle is based on `plasser-lab/theodore` commit
`e7ddc34fc2be7f877c0b592d2c035d7bf7e5b60e` (the repository state retrieved for
this implementation).

## Features

- parses the **final converged** CP2K state table (energy, transition dipole,
  oscillator strength), the excitation amplitudes, NTO eigenvalues, geometry,
  and CP2K exciton descriptors;
- imports one or more matched hole/particle NTO pairs per electronic state;
- edits, colours, saves, and reloads atom-based molecular fragments;
- integrates very large cube grids in streaming blocks instead of loading a
  `450 × 450 × 450` array into memory;
- builds fragment hole→particle `Ω_AB` maps, classifies LE/CT/mixed states, and
  reports TheoDORE-style CT/PR/POS/COH descriptors;
- stores completed Omega maps and their analysed descriptors inside version 2
  project files and restores them when a project is reopened;
- displays the molecule and selected NTO pair in 3-D, or the hole and
  particle/electron orbitals separately, and saves any view as PNG, PDF, or SVG;
- exports CSV, structured JSON, legacy-compatible `OmFrag.txt`, and one PNG map
  per analysed state; the CSV includes normalised hole and electron
  localisations for every fragment;
- includes a headless CLI for reproducible runs.

Rows of every Ω map are **hole fragments** and columns are
**particle/electron fragments**. Thus an off-diagonal cell `(A, B)` represents
charge transfer `A → B`.

## Start

Python 3.8 or newer, NumPy, and Matplotlib are required. Tk must be available in
the Python installation (`python3-tk` on Debian/Ubuntu). SciPy accelerates nearest-atom assignment; without it
a memory-bounded NumPy implementation is used. scikit-image is optional and
provides smooth marching-cubes surfaces; without it the NTO viewer uses a point
isosurface fallback.

From the source tree:

```bash
python -m pip install numpy matplotlib scipy scikit-image
python -m theodore.cp2k_cube.gui
```

For a GUI-only editable installation (without forcing TheoDORE's optional
OpenBabel/ORBKIT stack):

```bash
python -m pip install -r requirements-cp2k-gui.txt
python -m pip install -e . --no-deps
theodore-cp2k-gui
```

Existing full TheoDORE environments can use `python -m pip install -e
'.[cp2k-gui]'` directly.

The extension is also registered as `theodore cp2k_cube_gui` in the legacy
dispatcher.

### Linux desktop launcher and dock icon

The AppImage embeds `TheoCP2K.desktop` and the scalable application icon. The
Tk runtime also sets the same icon and a matching window class, allowing
Linux desktops to associate the running window with its launcher in the dock.

For a Python/editable installation, install the desktop entry for the current
user after installing the `theodore-cp2k-gui` command:

```bash
packaging/linux/install-desktop.sh
```

This copies only `TheoCP2K.desktop` and `TheoCP2K.svg` below
`${XDG_DATA_HOME:-$HOME/.local/share}`.

## Suggested CP2K print section

The exact enclosing input depends on the calculation. The relevant print key
is:

```text
&FORCE_EVAL
  ...
  &PROPERTIES
    &TDDFPT
      ...
      &PRINT
        &NTO_ANALYSIS
          CUBE_FILES TRUE
          STATE_LIST 1 2 3 4
          THRESHOLD 0.99
          STRIDE 2 2 2
        &END NTO_ANALYSIS
      &END PRINT
    &END TDDFPT
  &END PROPERTIES
&END FORCE_EVAL
```

Generating cube files with a CP2K-side `STRIDE` of 2 or 3 is normally much more
space-efficient than generating full `450³` grids and downsampling them later.

## CP2K filename convention (important)

CP2K 2025.2 (the version in the supplied output) writes names containing a
field equivalent to:

```text
NTO_00301_Hole_State.cube
NTO_00301_Particle_State.cube
```

Here `003` is the **electronic excitation index** and `01` is the **NTO pair
index**. In contrast, the second cube comment may say:

```text
Natural Transition Orbital Hole State 3
```

That `3` is the **NTO pair index**, not the electronic state. The importer uses
the filename for the electronic state and checks the title for role/pair. If a
file has been renamed and the state can no longer be inferred, it is highlighted
in the *File cube* tab and can be associated manually.

## Workflow

1. Open the converged CP2K `.out`.
2. Add cube files or a directory containing them.
3. Inspect highlighted associations in *File cube*; double-click to correct an
   electronic state, NTO pair, or role.
4. In *Frammenti e geometria*, select atoms and create/assign/rename fragments.
   A single fragment necessarily gives CT = 0.
5. Choose the analysis stride. `1` uses every grid point. `2` samples every
   second point along each axis (roughly eight times fewer samples). The selected
   value is recorded in every result.
6. Analyse one state or all states with complete pairs.
7. Inspect Ω maps. In *Visualizzatore NTO*, choose *Coppia*, *Solo lacuna*, or
   *Solo elettrone*; use *Salva immagine…* to write the selected view as PNG,
   PDF, or SVG. Export the numerical results from *File → Esporta risultati*.

The summary CSV adds two columns per fragment named
`hole_localization[fragment]` and `electron_localization[fragment]`. Their
values are fractions between 0 and 1; each family sums to 1 for every state.
They are respectively the row and column marginal populations of the
normalised Ω matrix. Here “electron” and CP2K “particle” denote the same NTO
role.

Version 2 projects (`*.theodore-cp2k.json`) store paths, manual cube
associations, fragment definitions, and every completed analysis: the
normalised Omega matrix, hole/particle populations, all analysed descriptors,
state character, dominant channel, NTO weights, integration stride, method
flag, and warnings. Saved Omega maps are therefore available immediately when
the project is reopened. Version 1 project files remain supported and simply
open without cached analyses.

Changing cube assignments or fragment definitions in the application
invalidates all restored analyses. If an input file is replaced externally at
the same path after a project was saved, rerun the analysis before using the
stored snapshot.

## Scientific scope and limitations

Standard TheoDORE charge-transfer numbers are population analyses of a
one-particle transition density matrix in an AO basis (for example Lowdin or
Mulliken). A set of independently written NTO cube files does not contain the AO
overlap matrix or a uniquely recoverable relative phase between different NTO
pairs. Therefore this extension does **not** label its cube result as a Lowdin or
Mulliken Ω.

For each NTO `k`, the program obtains real-space fragment populations by
assigning each sampled voxel to its nearest atom (Voronoi partition):

```text
P_h,k(A) = integral over fragment A of |h_k(r)|²
P_e,k(B) = integral over fragment B of |e_k(r)|²
```

It then computes the positive NTO-diagonal approximation

```text
Ω_AB = sum_k λ_k P_h,k(A) P_e,k(B),
```

and normalises the displayed matrix to unit sum. With one NTO pair, this is the
separable electron-hole probability on the chosen real-space partition. With
multiple pairs, interference terms between pairs are omitted and the GUI marks
the result as approximate. The CP2K NTO weight captured by the supplied pairs is
reported as `Σλ`; the fraction of the CP2K-printed NTO weight for which both cube
files were actually loaded is reported separately, with a warning below 90%.

CP2K's own `d_eh`, `sigma_e`, `sigma_h`, `d_exc`, and `R_eh` values are parsed
from the output and shown separately. Those descriptors come from CP2K's TDDFPT
transition-density treatment and should be preferred over cube-derived centroid
estimates when available.

Changing the fragmentation can change the state label. Fragment definitions are
a chemical modelling choice, not an observable; always report them together with
the Ω map and integration stride.

## Headless CLI

Inspect a file:

```bash
python -m theodore.cp2k_cube.cli inspect-output calculation.out
python -m theodore.cp2k_cube.cli inspect-cube project-NTO_00301_Hole_State.cube
```

Analyse files with standard CP2K names:

```bash
python -m theodore.cp2k_cube.cli analyze \
  --out calculation.out \
  --cube project-NTO_00301_Hole_State.cube \
  --cube project-NTO_00301_Particle_State.cube \
  --fragments fragments.json \
  --stride 2
```

The command writes `cp2k_cube_summary.csv`, `cp2k_cube_results.json`, and
`OmFrag.txt` unless different paths are supplied.

To reuse manual associations and fragments saved by the GUI:

```bash
python -m theodore.cp2k_cube.cli analyze-project analysis.theodore-cp2k.json --stride 2
```

## References

- F. Plasser, *TheoDORE: A toolbox for a detailed and automated analysis of
  electronic excited state computations*, J. Chem. Phys. **152**, 084108
  (2020), <https://doi.org/10.1063/1.5143076>.
- R. L. Martin, *Natural transition orbitals*, J. Chem. Phys. **118**, 4775
  (2003), <https://doi.org/10.1063/1.1558471>.
- CP2K `NTO_ANALYSIS` input reference:
  <https://manual.cp2k.org/trunk/CP2K_INPUT/FORCE_EVAL/PROPERTIES/TDDFPT/PRINT/NTO_ANALYSIS.html>.
