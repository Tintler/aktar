"""CI: unittest ciktisindaki her FAIL/ERROR blogunu GitHub Actions hata notu (annotation) olarak yazar.

Herkese acik depolarda is loglari oturum acmadan okunamaz; notlar ise ozet sayfasinda ve API'de gorunur.
Kullanim: python tools/ci_annotate.py test-output.txt
"""
import re
import sys
from pathlib import Path

SEPARATOR = '=' * 70


def blocks(text):
    for part in text.split(SEPARATOR)[1:]:
        part = part.split('-' * 70 + '\nRan ')[0].strip()
        if re.match(r'(FAIL|ERROR):', part):
            yield part


def escape(text):
    return text.replace('%', '%25').replace('\r', '').replace('\n', '%0A')


def main(path):
    sys.stdout.reconfigure(encoding='utf-8')   # Windows konsolu cp1252; Turkce harfler cokertmesin
    text = Path(path).read_text(encoding='utf-8', errors='replace')
    found = list(blocks(text))
    for block in found[:10]:
        title, _, body = block.partition('\n')
        body = body.lstrip('-\n')
        print(f'::error title={escape(title[:200]).replace(",", "%2C").replace(":", "%3A")}::{escape(body[-6000:])}')
    if not found:
        print('::error title=Testler::' + escape(text[-6000:]))


if __name__ == '__main__':
    main(sys.argv[1])
