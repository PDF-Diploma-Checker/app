"""Fail when the CUDA library of llama.cpp has no code for common NVIDIA GPUs.

llama.cpp built with -DGGML_CUDA=on and no architecture list compiles only for the GPU of the build machine. Such a
library runs on that GPU family alone, and on any other card every analysis in the detailed mode crashes.

Usage: python tools/check_cuda_archs.py <ggml-cuda.dll | libggml-cuda.so> [required arch ...]
"""
import struct
import sys

FATBIN_MAGIC = b"\x50\xed\x55\xba"
PTX, ELF = 1, 2
# Turing, Ampere (RTX 30xx) and Ada (RTX 40xx): most cards with enough VRAM for the models
REQUIRED = (75, 86, 89)


def fatbin_archs(data):
    """{(kind, arch)} of the code in all fatbins of a library: kind PTX (compiled at run time) or ELF (machine code)."""
    found = set()
    pos = data.find(FATBIN_MAGIC)
    while pos >= 0:
        _version, header_size, size = struct.unpack_from("<HHQ", data, pos + 4)
        entry, end = pos + header_size, pos + header_size + size
        while entry + 32 <= end:
            kind, _unknown, entry_header, payload = struct.unpack_from("<HHIQ", data, entry)
            arch = struct.unpack_from("<I", data, entry + 28)[0]
            if kind in (PTX, ELF):
                found.add((kind, arch))
            if not entry_header:
                break
            entry += entry_header + payload
        pos = data.find(FATBIN_MAGIC, pos + 4)
    return found


def missing_archs(found, required=REQUIRED):
    """Required archs a GPU of which could not run: no machine code for it and no PTX at or below it."""
    machine = {arch for kind, arch in found if kind == ELF}
    ptx = [arch for kind, arch in found if kind == PTX]
    # machine code runs on the same major version with an equal or higher minor one (sm_86 code on sm_89)
    return [arch for arch in required
            if not any(code // 10 == arch // 10 and code <= arch for code in machine)
            and not any(code <= arch for code in ptx)]


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    with open(argv[1], "rb") as f:
        found = fatbin_archs(f.read())
    required = tuple(int(arch) for arch in argv[2:]) or REQUIRED
    names = sorted(f"{'sm' if kind == ELF else 'compute'}_{arch}" for kind, arch in found)
    print(f"{argv[1]}: {', '.join(names) or 'no CUDA code'}")
    missing = missing_archs(found, required)
    if missing:
        print(f"No code for GPU architectures: {', '.join(f'sm_{arch}' for arch in missing)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
