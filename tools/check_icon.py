"""يتأكد أن أيقونة التطبيق المدمجة داخل GuardApp.exe هي نفسها assets/icon.ico (وليست أيقونة بايثون/PyInstaller)."""
import struct, sys
from pathlib import Path
import pefile

root = Path(__file__).resolve().parent.parent
exe = Path(sys.argv[1] if len(sys.argv) > 1 else root / "dist/GuardApp/GuardApp.exe")
ico = (root / "assets/icon.ico").read_bytes()

count = struct.unpack("<H", ico[4:6])[0]
want = {struct.unpack("<I", ico[6 + 16 * i + 8: 6 + 16 * i + 12])[0] for i in range(count)}

pe = pefile.PE(str(exe), fast_load=True)
pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
have = set()
for e in getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None).entries:
    if e.id == pefile.RESOURCE_TYPE["RT_ICON"]:
        for ident in e.directory.entries:
            for lang in ident.directory.entries:
                have.add(lang.data.struct.Size)

missing = want - have
print(f"icon.ico images: {sorted(want)}\nexe icon images: {sorted(have)}")
if missing:
    raise SystemExit(f"ICON CHECK FAILED: exe does not contain icon.ico images {sorted(missing)}")
print("ICON CHECK OK")
