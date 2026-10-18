"""Windows .exe surum bilgisi (F155): src/version.py'den PyInstaller --version-file dosyasi uretir.

Kullanim: py -3 tools/version_info.py build/version_info.txt
Explorer'da Aktar.exe → Ozellikler → Ayrintilar'da dosya ve urun surumu olarak gorunur.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from version import NAME, VERSION, version_tuple  # noqa: E402

TEMPLATE = '''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041f04b0', [
      StringStruct('CompanyName', 'Aktar contributors'),
      StringStruct('FileDescription', '{name}'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [0x041f, 1200])])
  ]
)
'''


def render():
    numbers = version_tuple() + (0,) * (4 - len(version_tuple()))
    return TEMPLATE.format(numbers=numbers, name=NAME, version=VERSION)


if __name__ == '__main__':
    target = Path(sys.argv[1] if len(sys.argv) > 1 else 'build/version_info.txt')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(), encoding='utf-8')
    print(f'{target}: {NAME} {VERSION}')
