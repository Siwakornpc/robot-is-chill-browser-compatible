# check_sprites.py | run from the repo root (the folder that contains `data/`).

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("data")
WOBBLES = (1, 2, 3)


def read_toml(path: Path) -> dict:
    """Parse one TOML file with whichever reader is installed:
    tomllib (Python 3.11+), then tomli, then tomlkit."""

    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError:
            tomllib = None  # type: ignore

    if tomllib is not None:
        with open(path, "rb") as fp:
            return tomllib.load(fp)
        
    try:
        import tomlkit  # type: ignore
    except ModuleNotFoundError:
        sys.exit("No TOML reader found. Run: pip install tomli")
    with open(path, encoding="utf-8") as fp:
        return tomlkit.load(fp).unwrap()

def load_tiles():
    """Yield (tile_name, source, sprite_name, tiling) for every toml entry."""

    for path in sorted((ROOT / "custom").glob("*.toml")):
        stem = path.stem
        data = read_toml(path)
        for name, obj in data.items():
            if not isinstance(obj, dict) or "sprite" not in obj:
                continue
            yield name, obj.get("source", stem), obj["sprite"], obj.get("tiling", "none")

def expected_files(sprite, tiling):
    """Files the renderer needs for the default (variant 0) look."""
    if tiling == "icon":
        return [f"{sprite}_1.png"]
    return [f"{sprite}_0_{w}.png" for w in WOBBLES]

def main(argv):
    list_all = "--list" in argv
    argv = [a for a in argv if a != "--list"]
    only_tiles = None

    if "--tiles" in argv:
        i = argv.index("--tiles")
        only_tiles, argv = set(argv[i + 1:]), argv[:i]

    only_sources = set(argv)

    if not (ROOT / "custom").is_dir():
        sys.exit("Run this from the repo root: data/custom/ was not found.")

    stats = defaultdict(lambda: [0, 0])
    missing = []
    for name, source, sprite, tiling in load_tiles():
        if only_sources and source not in only_sources:
            continue

        if only_tiles is not None and name not in only_tiles:
            continue

        folder = ROOT / "sprites" / source
        gone = [f for f in expected_files(sprite, tiling) if not (folder / f).is_file()]

        if gone:
            stats[source][1] += 1
            missing.extend(f"{source}/{f}  (tile: {name})" for f in gone)
        else:
            stats[source][0] += 1

    if only_tiles is not None:
        found = {n for n, *_ in load_tiles()}
        for n in sorted(only_tiles - found):
            print(f"! tile '{n}' is not in any toml file")

    print(f"{'source':28} {'ok':>6} {'broken':>7}  folder")

    for source in sorted(stats):
        ok, bad = stats[source]
        has = "yes" if (ROOT / "sprites" / source).is_dir() else "MISSING"
        print(f"{source:28} {ok:>6} {bad:>7}  {has}")

    Path("missing_sprites.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")
    
    print(f"\n{len(missing)} missing files written to missing_sprites.txt")
    
    if list_all or only_tiles is not None:
        print("\n".join(missing))


if __name__ == "__main__":
    main(sys.argv[1:])