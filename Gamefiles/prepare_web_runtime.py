"""Fetch the Pygame wheel expected by the web loader and refresh web.zip."""

from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "build" / "web"
WHEEL_RELATIVE = Path(
    "archives/repo/cp312/pygame_static-1.0-cp312-cp312-wasm32_bi_emscripten.whl"
)
WHEEL_URL = "https://pygame-web.github.io/" + WHEEL_RELATIVE.as_posix()


def main():
    wheel = WEB_ROOT / WHEEL_RELATIVE
    wheel.parent.mkdir(parents=True, exist_ok=True)
    if not wheel.exists() or wheel.stat().st_size < 10_000:
        print(f"Downloading browser runtime: {WHEEL_URL}")
        urlretrieve(WHEEL_URL, wheel)

    archive = ROOT / "build" / "web.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(WEB_ROOT.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(WEB_ROOT))
    print(f"Browser archive refreshed: {archive}")


if __name__ == "__main__":
    main()
