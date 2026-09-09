"""Streaming Gaussian-cube reader with CP2K NTO filename discovery."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable, Iterator, Optional, Tuple

import numpy as np

from .chemistry import symbol_for_atomic_number
from .errors import AnalysisCancelled, CubeCompatibilityError, CubeFormatError
from .models import Atom, BOHR_TO_ANGSTROM, CubeAssignment, CubeHeader, PreviewVolume


def _decode(line: bytes) -> str:
    return line.decode("utf-8", errors="replace").rstrip("\r\n")


def _float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def read_cube_header(path) -> CubeHeader:
    """Read a cube header without loading its volumetric data."""

    source = Path(path).expanduser().resolve()
    try:
        handle = source.open("rb")
    except OSError as exc:
        raise CubeFormatError("Impossibile aprire il cube %s: %s" % (source.name, exc)) from exc

    with handle:
        comment_1 = _decode(handle.readline())
        comment_2 = _decode(handle.readline())
        if not comment_1 and not comment_2:
            raise CubeFormatError("%s non contiene un header cube." % source.name)

        origin_line = _decode(handle.readline()).split()
        if len(origin_line) < 4:
            raise CubeFormatError("Riga numero-atomi/origine non valida in %s." % source.name)
        try:
            signed_natoms = int(origin_line[0])
            raw_origin = np.asarray([_float(value) for value in origin_line[1:4]], dtype=float)
        except ValueError as exc:
            raise CubeFormatError("Origine cube non numerica in %s." % source.name) from exc

        signed_shape = []
        raw_axes = []
        for axis_index in range(3):
            words = _decode(handle.readline()).split()
            if len(words) < 4:
                raise CubeFormatError("Asse %d non valido in %s." % (axis_index + 1, source.name))
            try:
                signed_shape.append(int(words[0]))
                raw_axes.append([_float(value) for value in words[1:4]])
            except ValueError as exc:
                raise CubeFormatError("Asse cube non numerico in %s." % source.name) from exc

        if any(value == 0 for value in signed_shape):
            raise CubeFormatError("La griglia di %s contiene una dimensione nulla." % source.name)
        unit_signs = {int(math.copysign(1, value)) for value in signed_shape}
        if len(unit_signs) != 1:
            raise CubeFormatError("Segni delle dimensioni cube incoerenti in %s." % source.name)
        original_units = "angstrom" if signed_shape[0] < 0 else "bohr"
        to_bohr = 1.0 / BOHR_TO_ANGSTROM if original_units == "angstrom" else 1.0

        atoms = []
        for atom_index in range(abs(signed_natoms)):
            words = _decode(handle.readline()).split()
            if len(words) < 5:
                raise CubeFormatError("Atomo %d incompleto in %s." % (atom_index + 1, source.name))
            try:
                atomic_number = int(float(words[0]))
                charge = _float(words[1])
                position = np.asarray([_float(value) for value in words[2:5]], dtype=float) * to_bohr
            except ValueError as exc:
                raise CubeFormatError("Atomo %d non numerico in %s." % (atom_index + 1, source.name)) from exc
            atoms.append(
                Atom(
                    index=atom_index + 1,
                    atomic_number=atomic_number,
                    symbol=symbol_for_atomic_number(atomic_number),
                    position_bohr=position,
                    charge=charge,
                )
            )

        dataset_ids = []
        if signed_natoms < 0:
            # Gaussian orbital cubes put: N_IDS id_1 ... after the atoms.  The
            # list may continue onto additional lines.
            words = _decode(handle.readline()).split()
            if not words:
                raise CubeFormatError("Lista dataset mancante in %s." % source.name)
            try:
                n_ids = int(words[0])
                dataset_ids.extend(int(value) for value in words[1:])
                while len(dataset_ids) < n_ids:
                    dataset_ids.extend(int(value) for value in _decode(handle.readline()).split())
            except ValueError as exc:
                raise CubeFormatError("Lista dataset non valida in %s." % source.name) from exc
            dataset_ids = dataset_ids[:n_ids]

        data_offset = handle.tell()

    return CubeHeader(
        path=source,
        comment_1=comment_1,
        comment_2=comment_2,
        origin_bohr=raw_origin * to_bohr,
        shape=tuple(abs(value) for value in signed_shape),
        axes_bohr=np.asarray(raw_axes, dtype=float) * to_bohr,
        atoms=atoms,
        data_offset=data_offset,
        dataset_ids=dataset_ids,
        original_units=original_units,
    )


_CP2K_TDDFPT_NAME = re.compile(
    r"NTO_(?P<state>\d{3})(?P<pair>\d{2})_(?P<role>Hole|Particle)_State",
    re.I,
)
_CP2K_BSE_NAME = re.compile(
    r"_NEXC_(?P<state>\d+)_NTO_(?P<pair>\d+)_(?P<role>Hole|Particle)_State",
    re.I,
)
_GENERIC_STATE = re.compile(r"(?:^|[_-])(?:state|exc|s)[_-]?(\d+)(?:[_-]|$)", re.I)
_GENERIC_PAIR = re.compile(r"(?:^|[_-])(?:nto|pair)[_-]?(\d+)(?:[_-]|$)", re.I)
_TITLE = re.compile(r"Natural\s+Transition\s+Orbital\s+(Hole|Particle)\s+State\s+(\d+)", re.I)


def discover_cube(path) -> CubeAssignment:
    """Parse a cube and infer CP2K state/pair/role metadata.

    CP2K's comment title uses ``State`` for the *NTO pair index*.  The actual
    electronic-state index is only present in the generated filename.  This is
    why the title value is never used as ``state_index`` here.
    """

    header = read_cube_header(path)
    filename = header.path.name
    state_index = None
    pair_index = None
    role = "unknown"
    note_parts = []

    match = _CP2K_BSE_NAME.search(filename) or _CP2K_TDDFPT_NAME.search(filename)
    if match:
        state_index = int(match.group("state"))
        pair_index = int(match.group("pair"))
        role = match.group("role").lower()
        note_parts.append("associazione CP2K rilevata dal nome file")
    else:
        state_match = _GENERIC_STATE.search(filename)
        pair_match = _GENERIC_PAIR.search(filename)
        if state_match:
            state_index = int(state_match.group(1))
        if pair_match:
            pair_index = int(pair_match.group(1))
        lower_name = filename.lower()
        if "hole" in lower_name:
            role = "hole"
        elif "particle" in lower_name or "electron" in lower_name:
            role = "particle"
        note_parts.append("nome file non standard: verificare l'associazione")

    title_match = _TITLE.search("%s %s" % (header.comment_1, header.comment_2))
    if title_match:
        title_role = title_match.group(1).lower()
        title_pair = int(title_match.group(2))
        if role == "unknown":
            role = title_role
        elif role != title_role:
            note_parts.append("ruolo nel titolo diverso dal nome file")
        if pair_index is None:
            pair_index = title_pair
        elif pair_index != title_pair:
            note_parts.append("indice NTO nel titolo diverso dal nome file")

    if state_index is None:
        note_parts.append("stato elettronico da assegnare manualmente")
    if pair_index is None:
        note_parts.append("coppia NTO da assegnare manualmente")
    if role == "unknown":
        note_parts.append("ruolo hole/particle da assegnare manualmente")

    return CubeAssignment(
        path=header.path,
        role=role,
        state_index=state_index,
        pair_index=pair_index,
        header=header,
        detection_note="; ".join(note_parts),
    )


class CubeValueStream:
    """Read ASCII cube values in fixed-size NumPy blocks.

    The implementation avoids loading 450^3 grids into RAM.  A small byte tail
    is retained so a floating-point token split at an I/O boundary remains
    valid.
    """

    def __init__(self, header: CubeHeader, read_bytes: int = 4 * 1024 * 1024):
        self.header = header
        self._handle = header.path.open("rb")
        self._handle.seek(header.data_offset)
        self._read_bytes = int(read_bytes)
        self._tail = b""
        self._pending = np.empty(0, dtype=float)
        self._eof = False
        self.values_read = 0

    def close(self):
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def _read_more(self):
        if self._eof:
            return
        chunk = self._handle.read(self._read_bytes)
        if not chunk:
            body = self._tail
            self._tail = b""
            self._eof = True
        else:
            data = self._tail + chunk
            split_at = max(data.rfind(b" "), data.rfind(b"\n"), data.rfind(b"\t"), data.rfind(b"\r"))
            if split_at < 0:
                self._tail = data
                return
            body = data[: split_at + 1]
            self._tail = data[split_at + 1 :]
        if body.strip():
            try:
                parsed = np.fromstring(
                    body.replace(b"D", b"E").replace(b"d", b"e").decode("ascii"),
                    sep=" ",
                    dtype=float,
                )
            except (UnicodeDecodeError, ValueError) as exc:
                raise CubeFormatError("Dati volumetrici non validi in %s." % self.header.path.name) from exc
            if parsed.size:
                self._pending = np.concatenate((self._pending, parsed))

    def read(self, count: int) -> np.ndarray:
        count = int(count)
        while self._pending.size < count and not self._eof:
            self._read_more()
        take = min(count, self._pending.size)
        result = self._pending[:take]
        self._pending = self._pending[take:]
        self.values_read += take
        return result

    def iter_blocks(self, block_values: int = 262144) -> Iterator[np.ndarray]:
        remaining = self.header.n_values
        while remaining:
            values = self.read(min(block_values, remaining))
            if values.size == 0:
                raise CubeFormatError(
                    "%s termina dopo %d valori; ne erano attesi %d."
                    % (self.header.path.name, self.values_read, self.header.n_values)
                )
            remaining -= values.size
            yield values


def assert_compatible(reference: CubeHeader, candidate: CubeHeader, tolerance: float = 1.0e-7):
    if tuple(reference.shape) != tuple(candidate.shape):
        raise CubeCompatibilityError(
            "Griglie incompatibili: %s ha %s, %s ha %s."
            % (reference.path.name, reference.shape, candidate.path.name, candidate.shape)
        )
    if not np.allclose(reference.origin_bohr, candidate.origin_bohr, atol=tolerance, rtol=0.0):
        raise CubeCompatibilityError("Origini cube incompatibili.")
    if not np.allclose(reference.axes_bohr, candidate.axes_bohr, atol=tolerance, rtol=0.0):
        raise CubeCompatibilityError("Vettori di griglia cube incompatibili.")
    if len(reference.atoms) != len(candidate.atoms):
        raise CubeCompatibilityError("Numero di atomi diverso nei cube.")
    for left, right in zip(reference.atoms, candidate.atoms):
        if left.atomic_number != right.atomic_number or not np.allclose(
            left.position_bohr, right.position_bohr, atol=2.0e-5, rtol=0.0
        ):
            raise CubeCompatibilityError("Geometrie atomiche incompatibili nei cube.")


def _sampling_stride(shape: Tuple[int, int, int], max_axis_points: int) -> Tuple[int, int, int]:
    return tuple(max(1, int(math.ceil(size / float(max_axis_points)))) for size in shape)


def read_preview_volume(
    path_or_header,
    max_axis_points: int = 90,
    progress: Optional[Callable[[float, str], None]] = None,
    cancel_event=None,
) -> PreviewVolume:
    """Read a memory-bounded, regularly sampled volume for 3-D display."""

    header = path_or_header if isinstance(path_or_header, CubeHeader) else read_cube_header(path_or_header)
    stride = _sampling_stride(header.shape, max_axis_points)
    out_shape = tuple((size + step - 1) // step for size, step in zip(header.shape, stride))
    output = np.zeros(out_shape, dtype=np.float32)
    ny, nz = header.shape[1], header.shape[2]
    flat_start = 0

    with CubeValueStream(header) as stream:
        for block in stream.iter_blocks():
            if cancel_event is not None and cancel_event.is_set():
                raise AnalysisCancelled("Lettura NTO annullata.")
            flat = np.arange(flat_start, flat_start + block.size, dtype=np.int64)
            ix = flat // (ny * nz)
            remainder = flat % (ny * nz)
            iy = remainder // nz
            iz = remainder % nz
            mask = (ix % stride[0] == 0) & (iy % stride[1] == 0) & (iz % stride[2] == 0)
            output[ix[mask] // stride[0], iy[mask] // stride[1], iz[mask] // stride[2]] = block[mask]
            flat_start += block.size
            if progress is not None:
                progress(flat_start / header.n_values, "Lettura %s" % header.path.name)

    return PreviewVolume(
        values=output,
        origin_bohr=np.asarray(header.origin_bohr),
        axes_bohr=np.asarray(header.axes_bohr),
        sampling_stride=stride,
        atoms=header.atoms,
    )
