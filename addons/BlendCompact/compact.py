# SPDX-License-Identifier: GPL-3.0-or-later
"""Background worker. Operates only on files and never imports bpy."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading

try:
    from compression import zstd
except ImportError:
    zstd = None
    import zstandard

BLOCK = 24 * 1024**2
MAGIC = 0x8F92EAB1
SKIP = 0x184D2A5E
THREAD = threading.local()


def compress(data):
    if zstd is not None:
        return zstd.compress(data, level=8)
    if not hasattr(THREAD, "encoder"):
        THREAD.encoder = zstandard.ZstdCompressor(level=8)
    return THREAD.encoder.compress(data)


def read_blocks(stream):
    prefix = stream.read(7)
    stream.seek(0)
    if prefix == b"BLENDER":
        while chunk := stream.read(BLOCK):
            yield chunk
        return
    if prefix.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=stream) as reader:
            while chunk := reader.read(BLOCK):
                yield chunk
        return
    stream.seek(-9, os.SEEK_END)
    count, flags, magic = struct.unpack("<IBI", stream.read(9))
    if not count or magic != MAGIC or flags not in (0, 128):
        raise ValueError("无法识别 Blender 文件索引")
    entry = struct.Struct("<III" if flags else "<II")
    size = count * entry.size + 9
    start = stream.tell() - size - 8
    if start < 0:
        raise ValueError("文件索引不完整")
    stream.seek(start)
    if struct.unpack("<II", stream.read(8)) != (SKIP, size):
        raise ValueError("文件索引损坏")
    table = stream.read(size - 9)
    if sum(row[0] for row in entry.iter_unpack(table)) != start:
        raise ValueError("文件长度与索引不符")
    stream.seek(0)
    decoder = None if zstd else zstandard.ZstdDecompressor()
    for packed, plain, *_ in entry.iter_unpack(table):
        if max(packed, plain) > 256 * 1024**2:
            raise ValueError("数据块超过支持范围")
        frame = stream.read(packed)
        if zstd:
            decoder_std = zstd.ZstdDecompressor()
            chunk = decoder_std.decompress(frame, max_length=plain + 1)
            if not decoder_std.eof or decoder_std.unused_data:
                raise ValueError("无效的 Zstandard 数据块")
        else:
            frame_size = zstandard.frame_content_size(frame)
            if frame_size >= 0 and frame_size != plain:
                raise ValueError("数据块长度与索引不符")
            chunk = decoder.decompress(frame, max_output_size=max(1, plain), allow_extra_data=False)
        if len(chunk) != plain:
            raise ValueError("数据块解压长度不符")
        yield chunk


def grouped(stream, digest):
    pieces = []
    size = 0
    first = True
    for chunk in read_blocks(stream):
        if first and not chunk.startswith(b"BLENDER"):
            raise ValueError("缺少 Blender 文件头")
        first = False
        digest.update(chunk)
        pieces.append(chunk)
        size += len(chunk)
        if size >= BLOCK:
            yield b"".join(pieces)
            pieces.clear()
            size = 0
    if first:
        raise ValueError("空文件")
    if pieces:
        yield b"".join(pieces)


def write_frames(source, output, digest):
    workers = min(4, max(1, (os.process_cpu_count() or 2) - 1))
    queue = deque()
    entries = bytearray()

    def emit():
        length, future = queue.popleft()
        frame = future.result()
        output.write(frame)
        entries.extend(struct.pack("<II", len(frame), length))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for chunk in grouped(source, digest):
            queue.append((len(chunk), pool.submit(compress, chunk)))
            if len(queue) >= workers:
                emit()
        while queue:
            emit()
    count = len(entries) // 8
    entries.extend(struct.pack("<IBI", count, 0, MAGIC))
    output.write(struct.pack("<II", SKIP, len(entries)))
    output.write(entries)


def compact(path):
    if path.suffix.lower() != ".blend":
        raise ValueError("请选择 .blend 工程")
    temp = None
    try:
        with path.open("rb") as source, tempfile.NamedTemporaryFile(
            dir=path.parent, suffix=".partial", delete=False
        ) as output:
            temp = Path(output.name)
            original = os.fstat(source.fileno())
            digest = hashlib.sha256()
            write_frames(source, output, digest)
        verified = hashlib.sha256()
        with temp.open("rb") as stream:
            for chunk in read_blocks(stream):
                verified.update(chunk)
        if verified.digest() != digest.digest():
            raise ValueError("副本校验失败")
        current = path.stat()
        if (not os.path.samestat(original, current)
                or original.st_size != current.st_size
                or original.st_mtime_ns != current.st_mtime_ns):
            raise ValueError("压缩期间源文件有更新，请重试")
        for index in range(1, 10000):
            suffix = "_compact" if index == 1 else f"_compact_{index}"
            dest = path.with_stem(path.stem + suffix)
            try:
                if os.name == "nt":
                    temp.rename(dest)
                else:
                    os.link(temp, dest)
            except FileExistsError:
                continue
            return dest
        raise ValueError("同名副本过多")
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        source_path = Path(sys.argv[1]).resolve()
        output_path = compact(source_path)
        print(f"{source_path.stat().st_size / 1e6:.1f} MB → {output_path.stat().st_size / 1e6:.1f} MB")
        print(output_path)
    except Exception as error:
        sys.exit(str(error))
