import struct

def struct_le(fn, *entries):
    return _struct(fn, entries, endian='<')

def struct_be(fn, *entries):
    return _struct(fn, entries, endian='>')

def _struct(fn, entries, endian):
    fmt_string = [endian]
    names = []

    if not entries:
        entries = fn.__doc__.split()

    for e in entries:
        e = e.strip()
        if not e:
            continue
        fmt, name = e.split(':', 1)
        fmt_string.append(fmt)
        names.append(name)

    _fmt = ''.join(fmt_string)
    _names = names
    _size = struct.calcsize(_fmt)

    @classmethod
    def parse_blob(cls, blob):
        r = cls()
        toks = struct.unpack(_fmt, bytes(blob[:_size]))
        for tok, name in zip(toks, _names):
            setattr(r, name, tok)
        return r

    @classmethod
    def parse(cls, fin):
        chunks = []
        to_read = _size
        while to_read:
           s = fin.read(to_read)
           if not s:
               raise RuntimeError('premature end of file')
           to_read -= len(s)
           chunks.append(s)

        r = cls()
        toks = struct.unpack(_fmt, b''.join(chunks))
        for tok, name in zip(toks, _names):
            setattr(r, name, tok)
        return r

        return parse_blob(grope.wrap_file(fin))

    def pack(self):
        return struct.pack(_fmt, *(getattr(self, name) for name in _names))

    _old_init = fn.__init__

    def __init__(self, **kw):
        for k in kw:
            if k not in _names:
                raise AttributeError('struct has no attribute {}'.format(k))
            setattr(self, k, kw[k])

        for name in _names:
            if name not in kw:
                setattr(self, name, None)

        _old_init(self)

    def __repr__(self):
        return '{}({})'.format(type(self).__name__, ', '.join('{}={}'.format(name, getattr(self, name)) for name in _names))

    fn.parse = parse
    fn.parse_blob = parse_blob
    fn.pack = pack
    fn.size = _size
    fn.__init__ = __init__
    fn.__repr__ = __repr__
    return fn
