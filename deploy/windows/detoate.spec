# Rețeta PyInstaller pentru detoate.exe: backend-ul Python + interfața construită
# (frontend/dist), într-un singur fișier. Se folosește din build-exe.bat.
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

a = Analysis(
    [os.path.join(ROOT, "backend", "detoate_exe.py")],
    pathex=[os.path.join(ROOT, "backend")],
    datas=[(os.path.join(ROOT, "frontend", "dist"), "frontend_dist")],
    # importate doar în funcții, la nevoie: căutarea porturilor COM (tremol_check)
    hiddenimports=["serial.tools.list_ports", "serial.tools.list_ports_windows"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="detoate",
    console=True,  # fereastra „detoate - server”: închiderea ei oprește aplicația
    upx=False,     # UPX face antivirusurile mai bănuitoare
)
