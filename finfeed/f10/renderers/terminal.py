import sys


class ColorScheme:
    R = "\033[0m"
    B = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GRN = "\033[32m"
    YEL = "\033[33m"
    BLU = "\033[34m"
    MAG = "\033[35m"
    CYN = "\033[36m"
    WHT = "\033[37m"
    BG = "\033[44m"
    BCYN = "\033[96m"
    BYEL = "\033[93m"
    BMAG = "\033[95m"
    BGRN = "\033[92m"
    BBLU = "\033[94m"
    BRED = "\033[91m"
    BWHT = "\033[97m"
    GRAY = "\033[90m"
    BGRAY = "\033[37m"
    ERROR = "\033[91m"
    WARN = "\033[93m"
    INFO = "\033[96m"
    SUCCESS = "\033[92m"
    MUTED = "\033[90m"
    ACCENT = "\033[95m"

    def disable(self):
        for _a in dir(self):
            if not _a.startswith("_") and not callable(getattr(self, _a)):
                setattr(self, _a, "")


C = ColorScheme()


def supports_color():
    return sys.stdout.isatty()


def disable_color():
    C.disable()


if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

if not supports_color():
    disable_color()
