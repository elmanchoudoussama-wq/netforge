"""
xform.generator
---------------
Produces candidate scalars either from a file or by sequential generation.
Supports pure numeric ranges and simple alphanumeric of fixed length.
"""
import itertools
import string


def numeric_range_generator(start: int, end: int, width: int = 0):
    """
    Yields string representations of integers from start to end (inclusive).
    If width > 0, zero-pads to that width (e.g. 00000001).
    """
    for i in range(start, end + 1):
        if width > 0:
            yield f"{i:0{width}d}"
        else:
            yield str(i)


def charset_generator(length: int, charset: str = None):
    """
    Yields all combinations of given length from charset.
    Default charset = lowercase + digits (36 symbols).
    WARNING: length 8 already = 36^8 ≈ 2.8 trillion — use only for short lengths or testing.
    """
    if charset is None:
        charset = string.ascii_lowercase + string.digits
    for combo in itertools.product(charset, repeat=length):
        yield "".join(combo)


def file_generator(path: str, start_line: int = 0):
    """Yield lines from a text file, optionally skipping the first start_line lines."""
    with open(path, "r", encoding="latin-1", errors="ignore") as f:
        for i, line in enumerate(f):
            if i < start_line:
                continue
            s = line.rstrip("\r\n")
            if s:
                yield s


def estimate_count(mode: str, **kwargs) -> int:
    if mode == "numeric":
        return max(0, kwargs.get("end", 0) - kwargs.get("start", 0) + 1)
    if mode == "charset":
        length = kwargs.get("length", 8)
        charset = kwargs.get("charset") or (string.ascii_lowercase + string.digits)
        return len(charset) ** length
    if mode == "file":
        # unknown without reading whole file
        return -1
    return 0
