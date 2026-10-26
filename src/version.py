"""Aktar surumu (F155): tek kaynak.

Surum MAJOR.MINOR.PATCH bicimindedir. Yeni ozellik MINOR'u, yalnizca duzeltme PATCH'i artirir.
Degistirirken ayni numarayi CHANGELOG.md'nin en ustune ve web/package.json'a da yazin
(tests/test_version.py uc yerin ayni oldugunu denetler). Windows .exe'nin dosya surumu
tools/version_info.py ile buradan uretilir.
"""
VERSION = '2.35.0'
NAME = 'Aktar'


def version_tuple():
    return tuple(int(part) for part in VERSION.split('.'))
