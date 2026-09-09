"""Launch the CP2K NTO-cube desktop interface from the TheoDORE dispatcher."""

from .actions import Action


class CP2KCubeGUI(Action):
    name = "cp2k_cube_gui"
    _colt_description = "GUI for CP2K TDDFPT NTO cube analysis"
    _user_input = ""

    @staticmethod
    def run():
        from ..cp2k_cube.gui import main

        return main([])
