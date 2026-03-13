# -*- coding: utf-8 -*-

# Key derivation for Bambu Lab filament RFID tags.
# Adapted from https://github.com/Bambu-Research-Group/RFID-Tag-Guide/blob/main/deriveKeys.py
# Original authors: thekakester and Vinyl Da.i'gyu-Kazotetsu, 2024

from Cryptodome.Protocol.KDF import HKDF
from Cryptodome.Hash import SHA256


def derive_sector_keys(uid: bytes) -> list[bytes]:
    """
    Derive the 16 MIFARE sector A-keys for a filament spool tag from its UID.

    Tags use HKDF with a shared master key to generate per-tag sector keys.
    Each key is 6 bytes (standard MIFARE key length).

    Args:
        uid: 4-byte tag UID (first 4 bytes of block 0)

    Returns:
        List of 16 x 6-byte keys, one per sector.
    """
    master = bytes([
        0x9a, 0x75, 0x9c, 0xf2, 0xc4, 0xf7, 0xca, 0xff,
        0x22, 0x2c, 0xb9, 0x76, 0x9b, 0x41, 0xbc, 0x96
    ])
    return HKDF(uid, 6, master, SHA256, 16, context=b"RFID-A\0")
