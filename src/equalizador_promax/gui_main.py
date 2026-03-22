import sys

from equalizador_promax.cli import main
from equalizador_promax.gui import launch_gui


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(main(sys.argv[1:]))
    launch_gui()
