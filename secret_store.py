"""Sifreler icin isletim sistemi deposu (F89): config.json'a sifre yazilmaz.

Windows: Kimlik Bilgileri Yoneticisi (CredWrite/CredRead, 'Genel kimlik bilgileri').
Linux: Secret Service (`secret-tool`, KDE Wallet / GNOME Keyring). Anahtar adlari
'Aktar/...' ile baslar; kullanici Windows'ta Denetim Masasi'ndan da gorup silebilir.
"""
from __future__ import annotations

import os
import shutil
import subprocess

PREFIX = 'Aktar/'


class SecretStoreError(RuntimeError):
    pass


def _target(key):
    return PREFIX + str(key)


# --- Windows -----------------------------------------------------------------
def _win():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                    ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                    ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                    ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD),
                    ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                    ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]

    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, CREDENTIAL, advapi


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


def _win_set(key, value):
    ctypes, CREDENTIAL, advapi = _win()
    blob = value.encode('utf-16-le')
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob) if blob else None
    credential = CREDENTIAL(Type=CRED_TYPE_GENERIC, TargetName=_target(key), UserName='Aktar',
                            CredentialBlobSize=len(blob), Persist=CRED_PERSIST_LOCAL_MACHINE,
                            CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    if not advapi.CredWriteW(ctypes.byref(credential), 0):
        raise SecretStoreError(f'Şifre Windows Kimlik Bilgileri\'ne yazılamadı (hata {ctypes.get_last_error()}).')


def _win_get(key):
    ctypes, CREDENTIAL, advapi = _win()
    pointer = ctypes.POINTER(CREDENTIAL)()
    if not advapi.CredReadW(_target(key), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == ERROR_NOT_FOUND:
            return ''
        raise SecretStoreError(f'Şifre Windows Kimlik Bilgileri\'nden okunamadı (hata {ctypes.get_last_error()}).')
    try:
        size = pointer.contents.CredentialBlobSize
        return bytes(pointer.contents.CredentialBlob[:size]).decode('utf-16-le') if size else ''
    finally:
        advapi.CredFree(pointer)


def _win_delete(key):
    ctypes, _credential, advapi = _win()
    if not advapi.CredDeleteW(_target(key), CRED_TYPE_GENERIC, 0) \
            and ctypes.get_last_error() != ERROR_NOT_FOUND:
        raise SecretStoreError(f'Şifre silinemedi (hata {ctypes.get_last_error()}).')


# --- Linux (Secret Service) ---------------------------------------------------
def _tool():
    tool = shutil.which('secret-tool')
    if not tool:
        raise SecretStoreError('Şifre deposu bulunamadı: "secret-tool" kurun '
                               '(Debian: sudo apt install libsecret-tools).')
    return tool


def _run(args, text=None):
    try:
        return subprocess.run([_tool(), *args], input=text, capture_output=True, text=True,
                              timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SecretStoreError('Şifre deposuna ulaşılamadı: ' + str(error)) from error


def _attrs(key):
    return ['application', 'aktar', 'key', str(key)]


# --- genel --------------------------------------------------------------------
def set_secret(key, value):
    """Sifreyi saklar; bos deger kaydi siler."""
    if not value:
        delete_secret(key)
        return
    if os.name == 'nt':
        _win_set(key, str(value))
        return
    result = _run(['store', '--label', _target(key), *_attrs(key)], str(value))
    if result.returncode:
        raise SecretStoreError('Şifre saklanamadı: ' + (result.stderr.strip() or 'bilinmeyen hata'))


def get_secret(key):
    """Kayitli sifre ya da ''."""
    if os.name == 'nt':
        return _win_get(key)
    result = _run(['lookup', *_attrs(key)])
    return result.stdout if result.returncode == 0 else ''


def delete_secret(key):
    if os.name == 'nt':
        _win_delete(key)
        return
    _run(['clear', *_attrs(key)])
