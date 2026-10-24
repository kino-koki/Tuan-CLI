"""Generate a simple solid-blue placeholder .ico without third-party deps."""
import struct
from pathlib import Path

SIZES = [16, 32, 48, 64, 128, 256]
BLUE = (0xFF, 0xA8, 0x1A)  # BGR for #1a88ff


def bmp_image(size: int) -> bytes:
    # BITMAPINFOHEADER (height doubled for AND mask), BGRA pixels, AND mask
    header = struct.pack(
        '<IiiHHIIiiII',
        40, size, size * 2, 1, 32, 0, size * size * 4, 0, 0, 0, 0,
    )
    px = bytes(BLUE) + bytes((255,))
    pixels = px * (size * size)
    mask_row = ((size + 31) // 32) * 4
    mask = bytes(mask_row * size)
    return header + pixels + mask


def main(out: Path) -> None:
    images = [(s, bmp_image(s)) for s in SIZES]
    header = struct.pack('<HHH', 0, 1, len(images))
    entries = b''
    offset = 6 + 16 * len(images)
    blobs = b''
    for size, data in images:
        w = 0 if size >= 256 else size
        entries += struct.pack('<BBBBHHII', w, w, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(header + entries + blobs)
    print('wrote', out)


if __name__ == '__main__':
    # 相对脚本位置解析：scripts/ -> 仓库根 -> Tuan-App/src-tauri/icons/
    main(Path(__file__).resolve().parents[1] / 'Tuan-App' / 'src-tauri' / 'icons' / 'icon.ico')
