"""Read shipped assets from a source checkout or the installed application wheel."""

from pathlib import Path


def resource_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Application resource must be relative")
    root = Path(__file__).resolve().parent
    checkout = root.parent / path
    bundled = root / "assets" / path
    if checkout.exists():
        return checkout
    if bundled.exists():
        return bundled
    raise FileNotFoundError("Application resource is not installed")
