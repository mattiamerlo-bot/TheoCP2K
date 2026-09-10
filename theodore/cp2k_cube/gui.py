"""Tk desktop application for TheoDORE-style CP2K cube analysis."""

from __future__ import annotations

import argparse
import queue
import threading
import traceback
from pathlib import Path

import numpy as np

from .cube import read_preview_volume
from .errors import AnalysisCancelled, CP2KCubeError
from .export import export_json, export_omfrag, export_summary_csv
from .fragments import FragmentSet
from .icon import TK_WINDOW_CLASS, apply_window_icon
from .plotting import draw_molecule, draw_nto, draw_nto_pair, draw_omega
from .preview_cache import NTOPreviewCache
from .project import CP2KCubeProject


def _fmt(value, digits=4, missing="—"):
    if value is None:
        return missing
    try:
        if not np.isfinite(value):
            return missing
    except TypeError:
        pass
    return ("%%.%df" % digits) % value


class AssociationDialog:
    def __init__(self, parent, assignment, state_indices):
        import tkinter as tk
        from tkinter import ttk

        self.result = None
        window = self.window = tk.Toplevel(parent)
        window.title("Associazione cube")
        window.transient(parent)
        window.grab_set()
        window.resizable(False, False)

        frame = ttk.Frame(window, padding=16)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text=assignment.path.name, font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        ttk.Label(frame, text="Stato elettronico").grid(row=1, column=0, sticky="w", pady=4)
        self.state = tk.StringVar(value=str(assignment.state_index or (state_indices[0] if state_indices else 1)))
        state_box = ttk.Combobox(frame, textvariable=self.state, values=[str(v) for v in state_indices], width=12)
        state_box.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(frame, text="Coppia NTO").grid(row=2, column=0, sticky="w", pady=4)
        self.pair = tk.IntVar(value=assignment.pair_index or 1)
        ttk.Spinbox(frame, from_=1, to=999, textvariable=self.pair, width=12).grid(
            row=2, column=1, sticky="ew", pady=4
        )
        ttk.Label(frame, text="Ruolo").grid(row=3, column=0, sticky="w", pady=4)
        self.role = tk.StringVar(value=assignment.role if assignment.role in ("hole", "particle") else "hole")
        ttk.Combobox(frame, textvariable=self.role, values=("hole", "particle"), state="readonly", width=12).grid(
            row=3, column=1, sticky="ew", pady=4
        )
        ttk.Label(
            frame,
            text="Nel titolo CP2K, “State n” è l'indice della coppia NTO;\nlo stato elettronico proviene dal nome file.",
            foreground="#555555",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 12))
        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Annulla", command=self._cancel).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", self._cancel)
        window.bind("<Return>", lambda event: self._ok())
        window.bind("<Escape>", lambda event: self._cancel())
        window.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 2
        window.geometry("+%d+%d" % (max(0, x), max(0, y)))
        parent.wait_window(window)

    def _ok(self):
        try:
            state = int(self.state.get())
            pair = int(self.pair.get())
            if state < 1 or pair < 1:
                raise ValueError
        except ValueError:
            from tkinter import messagebox

            messagebox.showerror("Valori non validi", "Stato e coppia devono essere interi positivi.", parent=self.window)
            return
        self.result = state, pair, self.role.get()
        self.window.destroy()

    def _cancel(self):
        self.window.destroy()


class CP2KCubeApp:
    def __init__(self, root, initial_output=None, initial_cubes=None):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.project = CP2KCubeProject()
        self.worker = None
        self.worker_kind = None
        self.worker_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.nto_preview_cache = NTOPreviewCache()
        self.nto_redraw_pending = False

        root.title("TheoDORE · CP2K Cube")
        root.geometry("1380x860")
        root.minsize(1050, 680)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"), padding=(12, 6))
        style.configure("Treeview", rowheight=25)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 9, "bold"))

        self.status = tk.StringVar(value="Caricare un output CP2K e le coppie NTO cube.")
        self.stride = tk.IntVar(value=2)
        self.map_state = tk.StringVar()
        self.nto_state = tk.StringVar()
        self.nto_pair = tk.StringVar()
        self.nto_view = tk.StringVar(value="pair")
        self.nto_level = tk.DoubleVar(value=12.0)
        self.nto_resolution = tk.IntVar(value=90)

        self._build_menu()
        self._build_toolbar()
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self._build_states_tab()
        self._build_fragments_tab()
        self._build_map_tab()
        self._build_nto_tab()
        self._build_cubes_tab()
        self._build_statusbar()
        self._refresh_all()

        if initial_output:
            try:
                self.project.load_output(initial_output)
                if initial_cubes:
                    self.project.add_cubes(initial_cubes)
                self._refresh_all()
            except Exception as exc:
                self._show_error(exc)

    def _build_menu(self):
        import tkinter as tk

        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Nuovo progetto", command=self._new_project, accelerator="Ctrl+N")
        file_menu.add_separator()
        file_menu.add_command(label="Apri output CP2K…", command=self._open_output, accelerator="Ctrl+O")
        file_menu.add_command(label="Aggiungi cube…", command=self._add_cubes, accelerator="Ctrl+Shift+O")
        file_menu.add_command(label="Aggiungi cartella di cube…", command=self._add_cube_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Apri progetto…", command=self._load_project, accelerator="Ctrl+L")
        file_menu.add_command(label="Salva progetto…", command=self._save_project, accelerator="Ctrl+S")
        file_menu.add_command(label="Esporta risultati…", command=self._export_results, accelerator="Ctrl+E")
        file_menu.add_separator()
        file_menu.add_command(label="Esci", command=self.root.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        analyse_menu = tk.Menu(menu, tearoff=False)
        analyse_menu.add_command(label="Analizza stato selezionato", command=lambda: self._run_analysis(False))
        analyse_menu.add_command(label="Analizza tutti gli stati completi", command=lambda: self._run_analysis(True))
        analyse_menu.add_command(label="Annulla operazione", command=self._cancel_worker)
        menu.add_cascade(label="Analisi", menu=analyse_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Metodo e limiti", command=self._show_method)
        help_menu.add_command(label="Informazioni", command=self._show_about)
        menu.add_cascade(label="Aiuto", menu=help_menu)
        self.root.config(menu=menu)
        self.root.bind("<Control-n>", lambda event: self._new_project())
        self.root.bind("<Control-o>", lambda event: self._open_output())
        self.root.bind("<Control-O>", lambda event: self._add_cubes())
        self.root.bind("<Control-l>", lambda event: self._load_project())
        self.root.bind("<Control-s>", lambda event: self._save_project())
        self.root.bind("<Control-e>", lambda event: self._export_results())

    def _build_toolbar(self):
        from tkinter import ttk

        bar = ttk.Frame(self.root, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="1  Apri .out", command=self._open_output).pack(side="left")
        ttk.Button(bar, text="2  Aggiungi cube", command=self._add_cubes).pack(side="left", padx=6)
        ttk.Button(bar, text="3  Modifica frammenti", command=lambda: self.notebook.select(self.fragments_tab)).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bar, text="Stride griglia").pack(side="left")
        ttk.Spinbox(bar, from_=1, to=10, width=4, textvariable=self.stride).pack(side="left", padx=(5, 10))
        self.analyse_button = ttk.Button(
            bar, text="Analizza stati completi", style="Accent.TButton", command=lambda: self._run_analysis(True)
        )
        self.analyse_button.pack(side="left")
        self.cancel_button = ttk.Button(bar, text="Annulla", command=self._cancel_worker, state="disabled")
        self.cancel_button.pack(side="left", padx=6)
        ttk.Label(bar, text="righe Ω = hole · colonne Ω = particle", foreground="#555555").pack(side="right")

    def _build_states_tab(self):
        import tkinter as tk
        from tkinter import ttk

        self.states_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.states_tab, text="Stati")
        pane = ttk.Panedwindow(self.states_tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        table_frame = ttk.Frame(pane)
        pane.add(table_frame, weight=4)
        columns = ("energy", "osc", "nto", "cubes", "character", "ct", "deh")
        self.states_tree = ttk.Treeview(table_frame, columns=columns, show="tree headings", selectmode="browse")
        self.states_tree.heading("#0", text="Stato")
        headings = {
            "energy": "Energia / eV", "osc": "Osc. strength", "nto": "Σ λ NTO",
            "cubes": "Coppie cube", "character": "Carattere", "ct": "CT", "deh": "dₑₕ / Å",
        }
        widths = {"energy": 105, "osc": 110, "nto": 90, "cubes": 105, "character": 270, "ct": 70, "deh": 90}
        self.states_tree.column("#0", width=75, anchor="center", stretch=False)
        for column in columns:
            self.states_tree.heading(column, text=headings[column])
            self.states_tree.column(column, width=widths[column], anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.states_tree.yview)
        self.states_tree.configure(yscrollcommand=scrollbar.set)
        self.states_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.states_tree.bind("<<TreeviewSelect>>", self._on_state_select)
        self.states_tree.bind("<Double-1>", lambda event: self._run_analysis(False))

        detail_frame = ttk.LabelFrame(pane, text="Dettagli dello stato", padding=6)
        pane.add(detail_frame, weight=2)
        self.state_details = tk.Text(detail_frame, height=9, wrap="word", relief="flat", background="#FAFAFA")
        detail_scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.state_details.yview)
        self.state_details.configure(yscrollcommand=detail_scroll.set)
        self.state_details.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")

    def _build_fragments_tab(self):
        from tkinter import ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure

        self.fragments_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.fragments_tab, text="Frammenti e geometria")
        pane = ttk.Panedwindow(self.fragments_tab, orient="horizontal")
        pane.pack(fill="both", expand=True)

        left = ttk.Frame(pane)
        pane.add(left, weight=2)
        controls = ttk.Frame(left)
        controls.pack(fill="x", pady=(0, 6))
        ttk.Button(controls, text="Nuovo da selezione", command=self._new_fragment).pack(side="left")
        ttk.Button(controls, text="Assegna a…", command=self._assign_fragment).pack(side="left", padx=4)
        ttk.Button(controls, text="Rinomina", command=self._rename_fragment).pack(side="left")
        ttk.Button(controls, text="Unisci…", command=self._merge_fragment).pack(side="left", padx=4)
        ttk.Button(controls, text="Auto", command=self._auto_fragments).pack(side="left")

        columns = ("element", "x", "y", "z", "fragment")
        self.atoms_tree = ttk.Treeview(left, columns=columns, show="tree headings", selectmode="extended")
        self.atoms_tree.heading("#0", text="#")
        for column, title, width in (
            ("element", "Elemento", 75), ("x", "x / Å", 90), ("y", "y / Å", 90),
            ("z", "z / Å", 90), ("fragment", "Frammento", 160),
        ):
            self.atoms_tree.heading(column, text=title)
            self.atoms_tree.column(column, width=width, anchor="center")
        self.atoms_tree.column("#0", width=55, anchor="center", stretch=False)
        atom_scroll = ttk.Scrollbar(left, orient="vertical", command=self.atoms_tree.yview)
        self.atoms_tree.configure(yscrollcommand=atom_scroll.set)
        self.atoms_tree.pack(side="left", fill="both", expand=True)
        atom_scroll.pack(side="right", fill="y")
        self.atoms_tree.bind("<<TreeviewSelect>>", lambda event: self._draw_geometry())

        right = ttk.Frame(pane)
        pane.add(right, weight=3)
        self.geometry_figure = Figure(figsize=(6, 5), dpi=100, constrained_layout=True)
        self.geometry_ax = self.geometry_figure.add_subplot(111, projection="3d")
        self.geometry_canvas = FigureCanvasTkAgg(self.geometry_figure, master=right)
        NavigationToolbar2Tk(self.geometry_canvas, right, pack_toolbar=True)
        self.geometry_canvas.get_tk_widget().pack(fill="both", expand=True)
        bottom = ttk.Frame(right)
        bottom.pack(fill="x", pady=(5, 0))
        ttk.Button(bottom, text="Salva frammenti…", command=self._save_fragments).pack(side="right")
        ttk.Button(bottom, text="Carica frammenti…", command=self._load_fragments).pack(side="right", padx=5)
        ttk.Label(
            bottom,
            text="Selezione multipla: Ctrl/Cmd o Shift. I colori rappresentano i frammenti.",
            foreground="#555555",
        ).pack(side="left")

    def _build_map_tab(self):
        import tkinter as tk
        from tkinter import ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure

        self.map_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.map_tab, text="Mappa hole–particle Ω")
        top = ttk.Frame(self.map_tab)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Stato").pack(side="left")
        self.map_state_box = ttk.Combobox(top, textvariable=self.map_state, state="readonly", width=10)
        self.map_state_box.pack(side="left", padx=6)
        self.map_state_box.bind("<<ComboboxSelected>>", lambda event: self._draw_map())
        ttk.Button(top, text="Salva PNG…", command=self._save_map).pack(side="left")
        ttk.Label(
            top,
            text="Ω_AB: probabilità hole sul frammento A e particle sul frammento B",
            foreground="#555555",
        ).pack(side="right")

        pane = ttk.Panedwindow(self.map_tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        figure_frame = ttk.Frame(pane)
        pane.add(figure_frame, weight=3)
        self.map_figure = Figure(figsize=(7, 6), dpi=100, constrained_layout=True)
        self.map_canvas = FigureCanvasTkAgg(self.map_figure, master=figure_frame)
        NavigationToolbar2Tk(self.map_canvas, figure_frame, pack_toolbar=True)
        self.map_canvas.get_tk_widget().pack(fill="both", expand=True)
        detail_frame = ttk.LabelFrame(pane, text="Descrittori", padding=6)
        pane.add(detail_frame, weight=1)
        self.map_details = tk.Text(detail_frame, width=42, wrap="word", relief="flat", background="#FAFAFA")
        self.map_details.pack(fill="both", expand=True)

    def _build_nto_tab(self):
        from tkinter import ttk
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        from matplotlib.figure import Figure

        self.nto_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.nto_tab, text="Visualizzatore NTO")
        controls = ttk.Frame(self.nto_tab)
        controls.pack(fill="x", pady=(0, 4))
        ttk.Label(controls, text="Stato").pack(side="left")
        self.nto_state_box = ttk.Combobox(controls, textvariable=self.nto_state, state="readonly", width=9)
        self.nto_state_box.pack(side="left", padx=(5, 10))
        self.nto_state_box.bind("<<ComboboxSelected>>", lambda event: self._refresh_nto_pairs())
        ttk.Label(controls, text="Coppia NTO").pack(side="left")
        self.nto_pair_box = ttk.Combobox(controls, textvariable=self.nto_pair, state="readonly", width=8)
        self.nto_pair_box.pack(side="left", padx=(5, 10))
        ttk.Label(controls, text="Isolivello relativo %").pack(side="left")
        ttk.Spinbox(controls, from_=1, to=60, width=5, textvariable=self.nto_level).pack(
            side="left", padx=(5, 10)
        )
        ttk.Label(controls, text="Max punti/asse").pack(side="left")
        ttk.Spinbox(controls, from_=30, to=160, increment=10, width=5, textvariable=self.nto_resolution).pack(
            side="left", padx=(5, 10)
        )

        actions = ttk.Frame(self.nto_tab)
        actions.pack(fill="x", pady=(0, 6))
        ttk.Label(actions, text="Vista").pack(side="left")
        for label, value in (("Coppia", "pair"), ("Solo lacuna", "hole"), ("Solo elettrone", "particle")):
            ttk.Radiobutton(
                actions, text=label, value=value, variable=self.nto_view, command=self._on_nto_view_change
            ).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Visualizza", style="Accent.TButton", command=self._render_nto).pack(
            side="left", padx=(14, 4)
        )
        ttk.Button(actions, text="Salva immagine…", command=self._save_nto).pack(side="left")
        ttk.Label(
            actions, text="blu/rosso = hole · arancio/verde = particle/elettrone", foreground="#555555"
        ).pack(side="right")

        self.nto_figure = Figure(figsize=(8, 6), dpi=100, constrained_layout=True)
        self.nto_ax = self.nto_figure.add_subplot(111, projection="3d")
        self.nto_canvas = FigureCanvasTkAgg(self.nto_figure, master=self.nto_tab)
        NavigationToolbar2Tk(self.nto_canvas, self.nto_tab, pack_toolbar=True)
        self.nto_canvas.get_tk_widget().pack(fill="both", expand=True)
        self.nto_ax.text2D(0.5, 0.5, "Scegliere uno stato e una coppia NTO", transform=self.nto_ax.transAxes, ha="center")
        self.nto_canvas.draw_idle()

    def _build_cubes_tab(self):
        import tkinter as tk
        from tkinter import ttk

        self.cubes_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.cubes_tab, text="File cube")
        top = ttk.Frame(self.cubes_tab)
        top.pack(fill="x", pady=(0, 6))
        ttk.Button(top, text="Aggiungi file…", command=self._add_cubes).pack(side="left")
        ttk.Button(top, text="Aggiungi cartella…", command=self._add_cube_directory).pack(side="left", padx=4)
        ttk.Button(top, text="Modifica associazione…", command=self._edit_cube).pack(side="left")
        ttk.Button(top, text="Rimuovi", command=self._remove_cube).pack(side="left", padx=4)

        pane = ttk.Panedwindow(self.cubes_tab, orient="vertical")
        pane.pack(fill="both", expand=True)
        tree_frame = ttk.Frame(pane)
        pane.add(tree_frame, weight=4)
        columns = ("state", "pair", "role", "grid", "file", "status")
        self.cubes_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="extended")
        for column, title, width in (
            ("state", "Stato elettronico", 120), ("pair", "Coppia NTO", 95), ("role", "Ruolo", 90),
            ("grid", "Griglia", 120), ("file", "File", 430), ("status", "Stato", 260),
        ):
            self.cubes_tree.heading(column, text=title)
            self.cubes_tree.column(column, width=width, anchor="w" if column in ("file", "status") else "center")
        cube_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.cubes_tree.yview)
        self.cubes_tree.configure(yscrollcommand=cube_scroll.set)
        self.cubes_tree.pack(side="left", fill="both", expand=True)
        cube_scroll.pack(side="right", fill="y")
        self.cubes_tree.bind("<Double-1>", lambda event: self._edit_cube())
        self.cubes_tree.bind("<<TreeviewSelect>>", self._show_cube_details)
        detail = ttk.LabelFrame(pane, text="Header / rilevamento", padding=6)
        pane.add(detail, weight=1)
        self.cube_details = tk.Text(detail, height=7, wrap="word", relief="flat", background="#FAFAFA")
        self.cube_details.pack(fill="both", expand=True)

    def _build_statusbar(self):
        from tkinter import ttk

        frame = ttk.Frame(self.root, padding=(10, 3, 10, 8))
        frame.pack(fill="x")
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100, length=240)
        self.progress.pack(side="right")
        ttk.Label(frame, textvariable=self.status).pack(side="left", fill="x", expand=True)

    def _new_project(self):
        from tkinter import messagebox

        if not self._idle_or_warn():
            return
        if (self.project.output or self.project.assignments) and not messagebox.askyesno(
            "Nuovo progetto", "Azzerare il progetto corrente?", parent=self.root
        ):
            return
        self.project = CP2KCubeProject()
        self.nto_preview_cache.clear()
        self._refresh_all()
        self.status.set("Nuovo progetto.")

    def _open_output(self):
        from tkinter import filedialog

        if not self._idle_or_warn():
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Output TDDFPT di CP2K", filetypes=(("Output CP2K", "*.out *.log"), ("Tutti i file", "*"))
        )
        if not path:
            return
        try:
            run = self.project.load_output(path)
            self.nto_preview_cache.clear()
            self._refresh_all()
            self.status.set("Caricati %d stati TDDFPT da %s." % (len(run.states), Path(path).name))
        except Exception as exc:
            self._show_error(exc)

    def _add_cubes(self):
        from tkinter import filedialog

        paths = filedialog.askopenfilenames(
            parent=self.root, title="NTO cube CP2K", filetypes=(("Gaussian cube", "*.cube *.cub"), ("Tutti i file", "*"))
        )
        if paths:
            self._import_cubes(paths)

    def _add_cube_directory(self):
        from tkinter import filedialog, messagebox

        directory = filedialog.askdirectory(parent=self.root, title="Cartella con NTO cube")
        if not directory:
            return
        paths = sorted(set(Path(directory).glob("*.cube")).union(Path(directory).glob("*.cub")))
        if not paths:
            messagebox.showinfo("Nessun cube", "La cartella non contiene file .cube o .cub.", parent=self.root)
            return
        if len(paths) > 100 and not messagebox.askyesno(
            "Molti file", "Importare %d cube? Verranno letti solo gli header." % len(paths), parent=self.root
        ):
            return
        self._import_cubes(paths)

    def _import_cubes(self, paths):
        if not self._idle_or_warn():
            return
        try:
            added = self.project.add_cubes(paths)
            self._refresh_all()
            self.status.set("Aggiunti %d cube; controllare le associazioni evidenziate." % len(added))
            unknown = [item for item in added if item.state_index is None or item.role == "unknown"]
            if unknown:
                self.notebook.select(self.cubes_tab)
        except Exception as exc:
            self._show_error(exc)

    def _load_project(self):
        from tkinter import filedialog

        if not self._idle_or_warn():
            return
        path = filedialog.askopenfilename(
            parent=self.root, title="Apri progetto", filetypes=(("Progetto TheoDORE CP2K", "*.theodore-cp2k.json *.json"),)
        )
        if not path:
            return
        try:
            self.project = CP2KCubeProject.load(path)
            self.nto_preview_cache.clear()
            self._refresh_all()
            self.status.set(
                "Progetto caricato: %s · %d mappe Omega ripristinate."
                % (Path(path).name, len(self.project.analyses))
            )
        except Exception as exc:
            self._show_error(exc)

    def _save_project(self):
        from tkinter import filedialog

        initial = self.project.project_path.name if self.project.project_path else "analisi.theodore-cp2k.json"
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Salva progetto", initialfile=initial,
            defaultextension=".theodore-cp2k.json", filetypes=(("Progetto TheoDORE CP2K", "*.theodore-cp2k.json"),)
        )
        if path:
            try:
                self.project.save(path)
                self.status.set(
                    "Progetto salvato: %s · %d mappe Omega e relativi descrittori."
                    % (Path(path).name, len(self.project.analyses))
                )
            except Exception as exc:
                self._show_error(exc)

    def _export_results(self):
        from tkinter import filedialog, messagebox

        if not self._idle_or_warn():
            return
        directory = filedialog.askdirectory(parent=self.root, title="Cartella per i risultati")
        if not directory:
            return
        try:
            target = Path(directory)
            export_summary_csv(self.project, target / "cp2k_cube_summary.csv")
            export_json(self.project, target / "cp2k_cube_results.json")
            export_omfrag(self.project, target / "OmFrag.txt")
            map_dir = target / "omega_maps"
            map_dir.mkdir(exist_ok=True)
            from matplotlib.figure import Figure

            for state_index, analysis in sorted(self.project.analyses.items()):
                figure = Figure(figsize=(6.4, 5.4), dpi=160, constrained_layout=True)
                image = draw_omega(figure.add_subplot(111), analysis)
                figure.colorbar(image, ax=figure.axes[0], label="Ω_AB")
                figure.savefig(map_dir / ("S%d_omega.png" % state_index), dpi=160)
            messagebox.showinfo(
                "Esportazione completata",
                "Creati CSV, JSON, OmFrag.txt e %d mappe PNG." % len(self.project.analyses),
                parent=self.root,
            )
            self.status.set("Risultati esportati in %s." % target)
        except Exception as exc:
            self._show_error(exc)

    def _edit_cube(self):
        if not self._idle_or_warn():
            return
        selected = self.cubes_tree.selection()
        if not selected:
            return
        index = int(selected[0])
        assignment = self.project.assignments[index]
        dialog = AssociationDialog(self.root, assignment, self.project.state_indices)
        if dialog.result is not None:
            try:
                self.project.update_assignment(assignment.path, *dialog.result)
                self._refresh_all()
            except Exception as exc:
                self._show_error(exc)

    def _remove_cube(self):
        if not self._idle_or_warn():
            return
        selected = sorted((int(item) for item in self.cubes_tree.selection()), reverse=True)
        for index in selected:
            self.project.remove_assignment(self.project.assignments[index].path)
        if selected:
            self.nto_preview_cache.clear()
        self._refresh_all()

    def _show_cube_details(self, event=None):
        selected = self.cubes_tree.selection()
        self.cube_details.configure(state="normal")
        self.cube_details.delete("1.0", "end")
        if selected:
            assignment = self.project.assignments[int(selected[0])]
            header = assignment.header
            text = (
                "File: %s\nTitolo 1: %s\nTitolo 2: %s\nGriglia: %s (%d valori)\n"
                "Origine [bohr]: %s\nVolume voxel [bohr³]: %.8g\nRilevamento: %s"
                % (
                    assignment.path, header.comment_1, header.comment_2,
                    " × ".join(map(str, header.shape)), header.n_values,
                    np.array2string(header.origin_bohr, precision=5), header.voxel_volume_bohr3,
                    assignment.detection_note,
                )
            )
            self.cube_details.insert("1.0", text)
        self.cube_details.configure(state="disabled")

    def _selected_atom_indices(self):
        return [int(item) for item in self.atoms_tree.selection()]

    def _new_fragment(self):
        from tkinter import simpledialog

        if not self._idle_or_warn():
            return
        atoms = self._selected_atom_indices()
        if not atoms or self.project.fragments is None:
            return
        name = simpledialog.askstring("Nuovo frammento", "Nome:", parent=self.root)
        if not name:
            return
        try:
            self.project.fragments.add(name, atoms)
            self.project.invalidate_analyses()
            self._refresh_all()
        except Exception as exc:
            self._show_error(exc)

    def _assign_fragment(self):
        from tkinter import simpledialog

        if not self._idle_or_warn():
            return
        atoms = self._selected_atom_indices()
        fragments = self.project.fragments
        if not atoms or fragments is None:
            return
        name = simpledialog.askstring(
            "Assegna atomi", "Frammento di destinazione:\n%s" % ", ".join(fragments.names), parent=self.root
        )
        if not name:
            return
        try:
            target = fragments.names.index(name)
            fragments.assign(atoms, target)
            self.project.invalidate_analyses()
            self._refresh_all()
        except Exception as exc:
            self._show_error(exc)

    def _rename_fragment(self):
        from tkinter import simpledialog

        if not self._idle_or_warn():
            return
        atoms = self._selected_atom_indices()
        fragments = self.project.fragments
        if not atoms or fragments is None:
            return
        fragment_index = fragments.fragment_for_atom(atoms[0])
        old = fragments.fragments[fragment_index].name
        name = simpledialog.askstring("Rinomina frammento", "Nuovo nome:", initialvalue=old, parent=self.root)
        if name:
            try:
                fragments.rename(fragment_index, name)
                self.project.invalidate_analyses()
                self._refresh_all()
            except Exception as exc:
                self._show_error(exc)

    def _merge_fragment(self):
        from tkinter import simpledialog

        if not self._idle_or_warn():
            return
        atoms = self._selected_atom_indices()
        fragments = self.project.fragments
        if not atoms or fragments is None or len(fragments.fragments) < 2:
            return
        source = fragments.fragment_for_atom(atoms[0])
        candidates = [name for index, name in enumerate(fragments.names) if index != source]
        name = simpledialog.askstring(
            "Unisci frammento", "Unire '%s' in:\n%s" % (fragments.names[source], ", ".join(candidates)), parent=self.root
        )
        if not name:
            return
        try:
            target = fragments.names.index(name)
            fragments.merge_into(source, target)
            self.project.invalidate_analyses()
            self._refresh_all()
        except Exception as exc:
            self._show_error(exc)

    def _auto_fragments(self):
        from tkinter import messagebox

        if not self._idle_or_warn():
            return
        if not self.project.atoms:
            return
        if not messagebox.askyesno(
            "Frammenti automatici", "Ricreare i frammenti dalle componenti molecolari connesse?", parent=self.root
        ):
            return
        self.project.fragments = FragmentSet.from_connected_components(self.project.atoms)
        self.project.invalidate_analyses()
        self._refresh_all()

    def _save_fragments(self):
        from tkinter import filedialog

        if self.project.fragments is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Salva frammenti", initialfile="fragments.json",
            defaultextension=".json", filetypes=(("JSON", "*.json"),)
        )
        if path:
            try:
                self.project.fragments.save(path)
                self.status.set("Frammenti salvati: %s" % Path(path).name)
            except Exception as exc:
                self._show_error(exc)

    def _load_fragments(self):
        from tkinter import filedialog

        if not self._idle_or_warn():
            return
        if not self.project.atoms:
            return
        path = filedialog.askopenfilename(parent=self.root, title="Carica frammenti", filetypes=(("JSON", "*.json"),))
        if path:
            try:
                self.project.fragments = FragmentSet.load(path, expected_n_atoms=len(self.project.atoms))
                self.project.invalidate_analyses()
                self._refresh_all()
            except Exception as exc:
                self._show_error(exc)

    def _run_analysis(self, all_states):
        if self.worker is not None:
            return
        try:
            stride = int(self.stride.get())
            if stride < 1:
                raise ValueError("Lo stride deve essere positivo.")
            if all_states:
                states = self.project.available_complete_states()
            else:
                selected = self.states_tree.selection()
                if not selected:
                    raise CP2KCubeError("Selezionare uno stato.")
                states = [int(selected[0])]
            if not states:
                raise CP2KCubeError("Nessuno stato possiede coppie hole/particle complete.")
            if self.project.fragments is None:
                raise CP2KCubeError("Definire prima i frammenti.")
            self.project.fragments.validate()
        except Exception as exc:
            self._show_error(exc)
            return

        def work(progress):
            output = []
            for state_number, state_index in enumerate(states):
                if self.cancel_event.is_set():
                    raise AnalysisCancelled("Analisi annullata.")

                def state_progress(fraction, message, offset=state_number):
                    progress((offset + fraction) / len(states), "S%d · %s" % (state_index, message))

                output.append(
                    self.project.analyze_state(
                        state_index, stride=stride, progress=state_progress, cancel_event=self.cancel_event
                    )
                )
            return output

        self._start_worker("analysis", work, "Analisi di %d stato/i…" % len(states))

    def _on_nto_view_change(self):
        self._refresh_nto_pairs()
        if self.worker is not None:
            if self.worker_kind == "nto":
                self.nto_redraw_pending = True
                self.status.set("La vista NTO cambierà appena termina il precaricamento…")
            return
        self._render_nto(silent_invalid=True)

    def _render_nto(self, save_path=None, silent_invalid=False):
        if self.worker is not None:
            return False
        try:
            state_index = int(self.nto_state.get().lstrip("S"))
            pair_index = int(self.nto_pair.get())
            roles = self.project.pairs_for_state(state_index)[pair_index]
            view = self.nto_view.get()
            if view not in ("pair", "hole", "particle"):
                raise ValueError("vista non riconosciuta")
            required_roles = ("hole", "particle") if view == "pair" else (view,)
            missing_roles = [role for role in required_roles if role not in roles]
            if missing_roles:
                raise ValueError("cube %s non disponibile" % "/".join(missing_roles))
            resolution = int(self.nto_resolution.get())
            level = float(self.nto_level.get()) / 100.0
            if not (0.0 < level < 1.0):
                raise ValueError("L'isolivello deve essere tra 1 e 99%.")
        except Exception as exc:
            if not silent_invalid:
                self._show_error(CP2KCubeError("Selezione NTO non valida: %s" % exc))
            return False

        previews = {}
        missing = []
        # Preload both members when available: every subsequent view switch is
        # then a pure redraw and never rereads a large cube.
        for role in ("hole", "particle"):
            if role not in roles:
                continue
            preview = self.nto_preview_cache.get(roles[role], resolution)
            if preview is None:
                missing.append(role)
            else:
                previews[role] = preview

        destination = Path(save_path) if save_path else None
        if not missing:
            self._display_nto(state_index, pair_index, level, view, previews, destination, cached=True)
            return True

        def work(progress):
            role_count = len(missing)
            for role_number, role in enumerate(missing):
                assignment = roles[role]
                preview = read_preview_volume(
                    assignment.header,
                    max_axis_points=resolution,
                    progress=lambda fraction, message, offset=role_number: progress(
                        (offset + fraction) / role_count, message
                    ),
                    cancel_event=self.cancel_event,
                )
                self.nto_preview_cache.put(assignment, resolution, preview)
                previews[role] = preview
            return state_index, pair_index, level, view, previews, destination

        self._start_worker(
            "nto", work,
            "Precaricamento NTO %s…" % " + ".join("lacuna" if role == "hole" else "elettrone" for role in missing),
        )
        return True

    def _display_nto(self, state, pair, level, view, previews, save_path=None, cached=False):
        if view == "pair":
            draw_nto_pair(self.nto_ax, previews["hole"], previews["particle"], relative_level=level)
            view_label = "hole + particle"
        else:
            draw_nto(self.nto_ax, previews[view], role=view, relative_level=level)
            view_label = "lacuna (hole)" if view == "hole" else "elettrone (particle)"
        self.nto_ax.set_title("S%d · coppia NTO %d · %s" % (state, pair, view_label))
        self.nto_canvas.draw_idle()
        if save_path is not None:
            try:
                self.nto_figure.savefig(save_path, dpi=200)
            except Exception as exc:
                self._show_error(exc)
            else:
                self.status.set("NTO salvata: %s" % save_path.name)
        else:
            source = " · cache" if cached else ""
            self.status.set("NTO visualizzata: S%d, coppia %d, %s%s." % (state, pair, view_label, source))

    def _start_worker(self, kind, function, message):
        self.cancel_event.clear()
        self.worker_kind = kind
        self.status.set(message)
        self.progress["value"] = 0
        self.analyse_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        def progress(fraction, text):
            self.worker_queue.put(("progress", max(0.0, min(1.0, float(fraction))), text))

        def runner():
            try:
                result = function(progress)
                self.worker_queue.put(("done", kind, result))
            except AnalysisCancelled as exc:
                self.worker_queue.put(("cancelled", kind, str(exc)))
            except Exception as exc:
                self.worker_queue.put(("error", kind, exc, traceback.format_exc()))

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()
        self.root.after(80, self._poll_worker)

    def _poll_worker(self):
        try:
            while True:
                message = self.worker_queue.get_nowait()
                if message[0] == "progress":
                    self.progress["value"] = message[1] * 100.0
                    self.status.set(message[2])
                elif message[0] == "done":
                    self._finish_worker()
                    if message[1] == "analysis":
                        self._refresh_all()
                        self.status.set("Analisi completata per %d stato/i." % len(message[2]))
                        if message[2]:
                            self.map_state.set("S%d" % message[2][0].state_index)
                            self._draw_map()
                    elif message[1] == "nto":
                        state, pair, level, view, previews, save_path = message[2]
                        if self.nto_redraw_pending and save_path is None:
                            self.nto_redraw_pending = False
                            self._render_nto(silent_invalid=True)
                        else:
                            self._display_nto(state, pair, level, view, previews, save_path)
                            if self.nto_redraw_pending:
                                self.nto_redraw_pending = False
                                self._render_nto(silent_invalid=True)
                elif message[0] == "cancelled":
                    self._finish_worker()
                    if message[1] == "nto":
                        self.nto_redraw_pending = False
                    self.status.set(message[2])
                elif message[0] == "error":
                    self._finish_worker()
                    if message[1] == "nto":
                        self.nto_redraw_pending = False
                    self._show_error(message[2], detail=message[3])
        except queue.Empty:
            pass
        if self.worker is not None:
            self.root.after(80, self._poll_worker)

    def _finish_worker(self):
        self.worker = None
        self.worker_kind = None
        self.progress["value"] = 0
        self.analyse_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")

    def _cancel_worker(self):
        if self.worker is not None:
            self.cancel_event.set()
            self.status.set("Annullamento richiesto…")

    def _idle_or_warn(self):
        if self.worker is None:
            return True
        self.root.bell()
        self.status.set("Attendere o annullare l'operazione in corso.")
        return False

    def _refresh_all(self):
        self._refresh_states()
        self._refresh_fragments()
        self._refresh_cubes()
        state_values = ["S%d" % value for value in self.project.state_indices]
        self.map_state_box["values"] = state_values
        self.nto_state_box["values"] = state_values
        if state_values:
            if self.map_state.get() not in state_values:
                self.map_state.set(state_values[0])
            if self.nto_state.get() not in state_values:
                self.nto_state.set(state_values[0])
        else:
            self.map_state.set("")
            self.nto_state.set("")
        self._refresh_nto_pairs()
        self._draw_map()

    def _refresh_states(self):
        selected = self.states_tree.selection()
        selected_value = selected[0] if selected else None
        self.states_tree.delete(*self.states_tree.get_children())
        if self.project.output is None:
            self.state_details.configure(state="normal")
            self.state_details.delete("1.0", "end")
            self.state_details.insert("1.0", "Aprire un output CP2K TDDFPT.")
            self.state_details.configure(state="disabled")
            return
        for state in self.project.output.states:
            pairs = self.project.pairs_for_state(state.index)
            complete = sum("hole" in roles and "particle" in roles for roles in pairs.values())
            expected = len(state.nto_eigenvalues) if state.nto_eigenvalues else (len(pairs) or 1)
            analysis = self.project.analyses.get(state.index)
            self.states_tree.insert(
                "", "end", iid=str(state.index), text=state.name,
                values=(
                    _fmt(state.energy_ev, 5), "%.5e" % state.oscillator_strength,
                    _fmt(state.nto_sum, 4) if state.nto_eigenvalues else "—",
                    "%d / %d" % (complete, expected), analysis.character if analysis else "non analizzato",
                    _fmt(analysis.descriptors.get("CT"), 3) if analysis else "—",
                    _fmt(state.exciton.get("d_eh"), 3),
                ),
            )
        if selected_value and self.states_tree.exists(selected_value):
            self.states_tree.selection_set(selected_value)
        elif self.states_tree.get_children():
            self.states_tree.selection_set(self.states_tree.get_children()[0])
        self._on_state_select()

    def _on_state_select(self, event=None):
        selected = self.states_tree.selection()
        self.state_details.configure(state="normal")
        self.state_details.delete("1.0", "end")
        if not selected or self.project.output is None:
            self.state_details.configure(state="disabled")
            return
        state = self.project.output.state(int(selected[0]))
        lines = [
            "%s   energia %.6f eV   oscillator strength %.7g" % (state.name, state.energy_ev, state.oscillator_strength),
            "Dipolo di transizione [a.u.]: (%s)" % ", ".join(_fmt(value, 5) for value in state.transition_dipole_au),
        ]
        if state.nto_eigenvalues:
            lines.append(
                "Autovalori NTO: %s   ·   PRNTO=%s   ·   Σλ=%s"
                % (", ".join(_fmt(value, 5) for value in state.nto_eigenvalues), _fmt(state.pr_nto, 3), _fmt(state.nto_sum, 5))
            )
        if state.exciton:
            lines.append(
                "Descrittori CP2K esatti: dₑₕ=%s Å, σₑ=%s Å, σₕ=%s Å, d_exc=%s Å, Rₑₕ=%s"
                % tuple(_fmt(state.exciton.get(key), 4) for key in ("d_eh", "sigma_e", "sigma_h", "d_exc", "R_eh"))
            )
        if state.transitions:
            leading = state.transitions[:6]
            lines.append(
                "Contributi principali: "
                + "; ".join("%d→%d (%+.4f)" % (item.occupied, item.virtual, item.amplitude) for item in leading)
            )
        analysis = self.project.analyses.get(state.index)
        if analysis:
            lines.extend(
                [
                    "Carattere cube: %s; canale dominante %s" % (analysis.character, analysis.dominant_channel),
                    "CT=%s, LE=%s, PR=%s, d_centroid(cube)=%s Å, d_exc(diag)=%s Å"
                    % tuple(
                        _fmt(analysis.descriptors.get(key), 4)
                        for key in ("CT", "LE", "PR", "d_centroid_cube", "d_exc_cube_diag")
                    ),
                    "Avvertenze: " + " | ".join(analysis.warnings),
                ]
            )
        self.state_details.insert("1.0", "\n".join(lines))
        self.state_details.configure(state="disabled")
        self.map_state.set(state.name)
        self.nto_state.set(state.name)
        self._refresh_nto_pairs()

    def _refresh_fragments(self):
        selected = set(self._selected_atom_indices())
        self.atoms_tree.delete(*self.atoms_tree.get_children())
        fragments = self.project.fragments
        for atom in self.project.atoms:
            fragment_name = "—"
            if fragments is not None:
                index = fragments.fragment_for_atom(atom.index)
                if index is not None:
                    fragment_name = fragments.fragments[index].name
            xyz = atom.position_angstrom
            self.atoms_tree.insert(
                "", "end", iid=str(atom.index), text=str(atom.index),
                values=(atom.symbol, _fmt(xyz[0], 5), _fmt(xyz[1], 5), _fmt(xyz[2], 5), fragment_name),
            )
        for atom_index in selected:
            if self.atoms_tree.exists(str(atom_index)):
                self.atoms_tree.selection_add(str(atom_index))
        self._draw_geometry()

    def _draw_geometry(self):
        draw_molecule(
            self.geometry_ax, self.project.atoms, fragments=self.project.fragments,
            selected=self._selected_atom_indices(), labels=len(self.project.atoms) <= 120,
        )
        self.geometry_canvas.draw_idle()

    def _refresh_cubes(self):
        self.cubes_tree.delete(*self.cubes_tree.get_children())
        issues = self.project.assignment_issues()
        for index, assignment in enumerate(self.project.assignments):
            issue = issues.get(assignment.path)
            self.cubes_tree.insert(
                "", "end", iid=str(index),
                values=(
                    assignment.state_index if assignment.state_index is not None else "?",
                    assignment.pair_index if assignment.pair_index is not None else "?",
                    assignment.role,
                    "×".join(map(str, assignment.header.shape)),
                    assignment.path.name,
                    issue or "OK",
                ),
                tags=("error",) if issue else (),
            )
        self.cubes_tree.tag_configure("error", background="#FFE5E5")

    def _refresh_nto_pairs(self):
        try:
            state_index = int(self.nto_state.get().lstrip("S"))
        except ValueError:
            pairs = []
        else:
            view = self.nto_view.get()
            pairs = [
                str(index) for index, roles in sorted(self.project.pairs_for_state(state_index).items())
                if (
                    (view == "pair" and "hole" in roles and "particle" in roles)
                    or (view in ("hole", "particle") and view in roles)
                )
            ]
        self.nto_pair_box["values"] = pairs
        if pairs and self.nto_pair.get() not in pairs:
            self.nto_pair.set(pairs[0])
        elif not pairs:
            self.nto_pair.set("")

    def _save_nto(self):
        from tkinter import filedialog

        if not self._idle_or_warn():
            return
        try:
            state = self.nto_state.get()
            pair = int(self.nto_pair.get())
            view = self.nto_view.get()
            suffix = {"pair": "pair", "hole": "hole", "particle": "electron"}[view]
            if not state:
                raise ValueError("selezionare uno stato")
        except (KeyError, ValueError) as exc:
            self._show_error(CP2KCubeError("Selezione NTO non valida: %s" % exc))
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Salva NTO %s" % ("lacuna" if view == "hole" else "elettrone" if view == "particle" else "coppia"),
            initialfile="%s_NTO%02d_%s.png" % (state, pair, suffix),
            defaultextension=".png",
            filetypes=(("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")),
        )
        if path:
            self._render_nto(save_path=path)

    def _draw_map(self):
        self.map_figure.clear()
        ax = self.map_figure.add_subplot(111)
        self.map_details.configure(state="normal")
        self.map_details.delete("1.0", "end")
        try:
            state_index = int(self.map_state.get().lstrip("S"))
            analysis = self.project.analyses[state_index]
        except (ValueError, KeyError):
            ax.text(0.5, 0.5, "Analizzare lo stato per generare Ω", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
        else:
            image = draw_omega(ax, analysis)
            self.map_figure.colorbar(image, ax=ax, label="Ω_AB")
            state = self.project.output.state(state_index)
            descriptor = analysis.descriptors
            lines = [
                "%s · %.5f eV · f = %.6g" % (state.name, state.energy_ev, state.oscillator_strength),
                "",
                "Carattere: %s" % analysis.character,
                "Canale dominante: %s" % analysis.dominant_channel,
                "",
                "CT       %s" % _fmt(descriptor.get("CT"), 5),
                "LE       %s" % _fmt(descriptor.get("LE"), 5),
                "PR       %s" % _fmt(descriptor.get("PR"), 5),
                "PRi      %s" % _fmt(descriptor.get("PRi"), 5),
                "PRf      %s" % _fmt(descriptor.get("PRf"), 5),
                "COH      %s" % _fmt(descriptor.get("COH"), 5),
                "PRNTO    %s" % _fmt(descriptor.get("PRNTO"), 5),
                "Σλ usata %s" % _fmt(descriptor.get("captured_NTO_weight"), 5),
                "Copertura coppie stampate %s%%" % _fmt(100.0 * descriptor.get("loaded_NTO_fraction", 1.0), 1),
                "",
                "dₑₕ CP2K     %s Å" % _fmt(state.exciton.get("d_eh"), 4),
                "d_exc CP2K   %s Å" % _fmt(state.exciton.get("d_exc"), 4),
                "Rₑₕ CP2K     %s" % _fmt(state.exciton.get("R_eh"), 4),
                "d centroid cube %s Å" % _fmt(descriptor.get("d_centroid_cube"), 4),
                "",
                "Metodo: partizione Voronoi su atomi; Ω NTO-diagonale; stride %s."
                % "×".join(map(str, analysis.grid_stride)),
                "Righe = hole; colonne = particle/elettrone.",
                "",
                "Nota: i descrittori eccitonici marcati CP2K provengono dalla 1TDM e sono esatti nel calcolo; Ω cube non è una popolazione AO Lowdin/Mulliken.",
            ]
            self.map_details.insert("1.0", "\n".join(lines))
        self.map_details.configure(state="disabled")
        self.map_canvas.draw_idle()

    def _save_map(self):
        from tkinter import filedialog

        if not self.map_state.get():
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Salva mappa Ω", initialfile="%s_omega.png" % self.map_state.get(),
            defaultextension=".png", filetypes=(("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg"))
        )
        if path:
            try:
                self.map_figure.savefig(path, dpi=200)
                self.status.set("Mappa salvata: %s" % Path(path).name)
            except Exception as exc:
                self._show_error(exc)

    def _show_method(self):
        from tkinter import messagebox

        messagebox.showinfo(
            "Metodo e limiti",
            "Il percorso CP2K-cube integra |NTO|² su domini atomici Voronoi e aggrega gli atomi nei frammenti scelti.\n\n"
            "Per una singola coppia, Ω_AB = P_h(A) P_e(B). Per più coppie usa Σ_k λ_k P_h,k(A) P_e,k(B). "
            "I termini di interferenza tra coppie non sono ricostruiti, perché i cube separati non conservano in modo affidabile la fase relativa.\n\n"
            "Questa Ω è quindi diversa dalle popolazioni AO Lowdin/Mulliken della 1TDM in TheoDORE. Energia, oscillator strength, autovalori NTO e descrittori eccitonici d_eh/d_exc/R_eh sono letti direttamente dall'output CP2K.",
            parent=self.root,
        )

    def _show_about(self):
        from tkinter import messagebox
        from . import __version__

        messagebox.showinfo(
            "TheoDORE · CP2K Cube",
            (
                "TheoCP2K %s\n"
                "Estensione GUI per TheoDORE\n"
                "Parser CP2K TDDFPT + NTO cube streaming\n\n"
                "TheoDORE è distribuito con licenza GNU GPL v3."
            )
            % __version__,
            parent=self.root,
        )

    def _show_error(self, error, detail=None):
        from tkinter import messagebox

        self.status.set("Errore: %s" % error)
        messagebox.showerror("Errore", str(error), detail=detail, parent=self.root)


def build_argument_parser():
    parser = argparse.ArgumentParser(description="GUI TheoDORE per NTO cube CP2K")
    parser.add_argument("--out", help="Output CP2K da aprire all'avvio")
    parser.add_argument("--cube", action="append", default=[], help="Cube da aggiungere all'avvio")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv=None):
    args = build_argument_parser().parse_args(argv)
    try:
        import tkinter as tk
    except (ImportError, OSError) as exc:
        import sys

        print(
            "Impossibile avviare la GUI Tk: %s\n"
            "Installare il supporto Tk per Python (ad esempio python3-tk su Debian/Ubuntu)." % exc,
            file=sys.stderr,
        )
        return 2
    try:
        root = tk.Tk(className=TK_WINDOW_CLASS)
        root.tk.call("tk", "appname", "TheoCP2K")
        apply_window_icon(root, strict=args.smoke_test)
    except tk.TclError as exc:
        import sys

        print("Impossibile aprire una finestra grafica: %s" % exc, file=sys.stderr)
        return 2
    CP2KCubeApp(root, initial_output=args.out, initial_cubes=args.cube)
    if args.smoke_test:
        root.update_idletasks()
        actual_class = root.winfo_class()
        if actual_class != TK_WINDOW_CLASS:
            raise RuntimeError(
                "La WM_CLASS della finestra è %r invece di %r."
                % (actual_class, TK_WINDOW_CLASS)
            )
        if len(getattr(root, "_theocp2k_icons", ())) != 3:
            raise RuntimeError("L'icona runtime non è stata applicata alla finestra Tk.")
        root.destroy()
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
