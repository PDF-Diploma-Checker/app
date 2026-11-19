import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from check_cuda_archs import ELF, PTX, fatbin_archs, missing_archs


def _fatbin(*entries):
    """A fatbin as nvcc writes it: a header, then entries of a 64-byte header and a payload."""
    body = b""
    for kind, arch in entries:
        payload = b"\0" * 16
        header = struct.pack("<HHIQIIHHI", kind, 0x101, 64, len(payload), len(payload), 0, 7, 1, arch)
        body += header.ljust(64, b"\0") + payload
    return b"\x50\xed\x55\xba" + struct.pack("<HHQ", 1, 16, len(body)) + body


class CudaArchsTest(unittest.TestCase):
    def test_library_built_for_the_build_machine_only_is_caught(self):
        data = b"MZ" + _fatbin((ELF, 75)) + b"\0" * 8 + _fatbin((ELF, 75))
        self.assertEqual(fatbin_archs(data), {(ELF, 75)})
        self.assertEqual(missing_archs(fatbin_archs(data)), [86, 89])

    def test_library_with_a_list_of_architectures_passes(self):
        data = _fatbin((ELF, 61), (ELF, 75), (ELF, 86), (ELF, 89), (PTX, 89))
        self.assertEqual(missing_archs(fatbin_archs(data)), [])

    def test_ptx_of_an_older_architecture_runs_on_newer_cards(self):
        self.assertEqual(missing_archs({(PTX, 70)}), [])

    def test_machine_code_runs_only_within_its_major_version(self):
        self.assertEqual(missing_archs({(ELF, 80)}), [75])
        self.assertEqual(missing_archs({(ELF, 86), (ELF, 75)}), [])


if __name__ == "__main__":
    unittest.main()
