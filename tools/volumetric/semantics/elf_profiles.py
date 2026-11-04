"""Collision profile names that the native projectile constructors of the Squad dedicated server assign.

Reads only the owner's installed SquadGameServer (ELF, non-PIE, no symbols except the dynamic table). Method:
  1. ``nm -D`` gives the address of ``vtable for <class>``; a constructor stores ``vtable+0x10`` into ``[this]``
     with ``mov qword ptr [reg], imm32``, so the 4-byte immediate is searched in .text.
  2. Every ``call`` to the FBodyInstance profile setter (``--setter``) is listed with the NUL-terminated
     strings loaded by ``mov esi, imm32`` in the 300 bytes before it (FName construction arguments).

Usage: elf_profiles.py <SquadGameServer> ctor <Class> [<Class> ...]
       elf_profiles.py <SquadGameServer> setter <hex address of the setter>
"""
import mmap
import re
import struct
import subprocess
import sys


class Elf:
    """Memory-mapped ELF with the .text segment and the first (read-only) LOAD segment of a non-PIE executable."""

    def __init__(self, path):
        sections = subprocess.run(["readelf", "-SW", path], capture_output=True, text=True, check=True).stdout
        text = re.search(r"\.text\s+PROGBITS\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)", sections)
        self.text_va, self.text_off, self.text_size = (int(g, 16) for g in text.groups())
        loads = subprocess.run(["readelf", "-lW", path], capture_output=True, text=True, check=True).stdout
        first = re.search(r"LOAD\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)", loads)
        self.ro_delta = int(first.group(2), 16) - int(first.group(1), 16)
        self.path = path
        self.file = open(path, "rb")
        self.map = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)

    def string_at(self, va, limit=60):
        """ASCII or UTF-16LE NUL-terminated string at a virtual address of the read-only segment."""
        raw = self.map[va - self.ro_delta:va - self.ro_delta + limit]
        ascii_text = raw.split(b"\0")[0]
        if len(ascii_text) > 1:
            return ascii_text.decode("latin1")
        wide = b""
        for i in range(0, len(raw) - 1, 2):
            if raw[i:i + 2] == b"\0\0":
                break
            wide += raw[i:i + 2]
        return wide.decode("utf-16le", "replace")

    def vtable(self, cls):
        out = subprocess.run(["nm", "-D", "-C", self.path], capture_output=True, text=True, check=True).stdout
        match = re.search(rf"^([0-9a-f]+) \w vtable for {re.escape(cls)}$", out, re.M)
        return int(match.group(1), 16) if match else None

    def immediate_refs(self, value):
        pattern = struct.pack("<I", value)
        pos = self.text_off
        while (pos := self.map.find(pattern, pos, self.text_off + self.text_size)) >= 0:
            yield self.text_va + pos - self.text_off
            pos += 1

    def call_sites(self, target):
        text = self.map[self.text_off:self.text_off + self.text_size]
        for hit in re.finditer(rb"\xe8", text):
            i = hit.start()
            if i + 5 > len(text):
                continue
            rel = struct.unpack_from("<i", text, i + 1)[0]
            if self.text_va + i + 5 + rel == target:
                yield self.text_va + i, text[max(0, i - 300):i]

    def strings_before(self, window):
        found = []
        for hit in re.finditer(rb"\xbe(....)", window, re.S):
            va = struct.unpack("<I", hit.group(1))[0]
            if 0x400000 <= va < self.text_va:
                text = self.string_at(va)
                if len(text) > 2 and text.isprintable():
                    found.append(text)
        return found


def main(argv):
    elf = Elf(argv[1])
    if argv[2] == "ctor":
        for cls in argv[3:]:
            vt = elf.vtable(cls)
            refs = [hex(a) for a in elf.immediate_refs(vt + 0x10)] if vt else None
            print(f"{cls}: vtable={hex(vt) if vt else None} constructor-stores-at={refs}")
    elif argv[2] == "setter":
        for va, window in elf.call_sites(int(argv[3], 16)):
            print(hex(va), elf.strings_before(window)[-2:])


if __name__ == "__main__":
    main(sys.argv)
