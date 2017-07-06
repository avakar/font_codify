from .struct2 import struct_be
from grope import rope, BlobIO
import six, struct, math

@struct_be
class _cmap_header:
    '''
    H:version
    H:numTables
    '''

@struct_be
class _cmap_encodingRecord:
    '''
    H:platformID
    H:encodingID
    I:offset
    '''

@struct_be
class _cmap_fmt4_header:
    '''
    H:format
    H:length
    H:language
    H:segCountX2
    H:searchRange
    H:entrySelector
    H:rangeShift
    '''

def _load_array(fin, num, fmt):
    size = struct.calcsize(fmt)
    fmt = '>{{}}{}'.format(fmt)

    r = []
    while num:
        chunk = min(num, 8*1024)
        b = fin.read(chunk*size)
        r.extend(struct.unpack(fmt.format(chunk), b))
        num -= chunk
    return r

def _parse_format4(blob, offs):
    length, = struct.unpack('>H', bytes(blob[offs+2:offs+4]))

    blob = blob[offs:offs+length]
    fin = BlobIO(blob)
    hdr = _cmap_fmt4_header.parse(fin)
    seg_count = hdr.segCountX2 // 2

    glyph_id_count = length - (hdr.size + seg_count * 8 + 2)
    if glyph_id_count < 0 or glyph_id_count % 2 != 0:
        raise RuntimeError('corrupted character map subtable')

    glyph_id_count //= 2

    end_count = _load_array(fin, seg_count, 'H')
    fin.seek(2, 1)
    start_count = _load_array(fin, seg_count, 'H')
    id_delta = _load_array(fin, seg_count, 'H')
    id_range_offset = _load_array(fin, seg_count, 'H')

    glyph_ids = _load_array(fin, glyph_id_count, 'H')

    cmap = [0] * 0x10000

    for sid in six.moves.range(seg_count):
        if id_range_offset[sid] == 0:
            for cid in six.moves.range(start_count[sid], end_count[sid] + 1):
                cmap[cid] = (cid + id_delta[sid])  % 0x10000
        else:
            adj = start_count[sid] + seg_count - sid - id_range_offset[sid] // 2
            for cid in six.moves.range(start_count[sid], end_count[sid] + 1):
                glyph = glyph_ids[cid - adj]
                if glyph != 0:
                    glyph += id_delta[sid]
                cmap[cid] = glyph % 0x10000

    return cmap

_table_formats = {
    4: _parse_format4,
    }

class OtfCmapTable:
    def __init__(self, name, blob):
        self.name = name

        fin = BlobIO(blob)

        hdr = _cmap_header.parse(fin)
        if hdr.version != 0:
            raise RuntimeError('unknown cmap table version, expected 0, found {}'.format(hdr.version))

        enc_records = [_cmap_encodingRecord.parse(fin) for i in six.moves.range(hdr.numTables)]

        self._map = None
        for enc in enc_records:
            if enc.platformID != 3 or enc.encodingID != 1:
                continue

            format, = struct.unpack('>H', bytes(blob[enc.offset:enc.offset+2]))

            parser = _table_formats.get(format)
            if parser is None:
                raise RuntimeError('unknown table format')

            self._map = parser(blob, enc.offset)
            break

    def pack(self):
        segments = []

        seg_cid = None
        seg_gid = None
        for cid, gid in enumerate(self._map):
            if seg_cid is not None and (gid == 0 or cid - seg_cid + seg_gid != gid):
                segments.append((seg_cid, seg_gid, cid - seg_cid))
                seg_cid = None

            if seg_cid is None and gid != 0:
                seg_cid = cid
                seg_gid = gid

        if seg_cid is not None:
                segments.append((seg_cid, seg_gid, cid - seg_cid))

        segments.append((0xffff, 0, 1))

        seg_words = []
        seg_words.extend(cid + length - 1 for cid, gid, length in segments)
        seg_words.append(0)
        seg_words.extend(cid for cid, gid, length in segments)
        seg_words.extend((gid - cid) & 0xffff for cid, gid, length in segments)
        seg_words.extend(0 for cid, gid, length in segments)

        seg_spec = struct.pack('>{}H'.format(len(seg_words)), *seg_words)

        hdr = _cmap_header(version=0, numTables=1).pack()
        record = _cmap_encodingRecord(platformID=3, encodingID=1, offset=_cmap_header.size + _cmap_encodingRecord.size).pack()

        entry_selector = int(math.floor(math.log2(len(segments))))
        search_range = 2 * (2**entry_selector)

        subheader = _cmap_fmt4_header(format=4, length=len(seg_spec) + _cmap_fmt4_header.size, language=0,
            segCountX2=len(segments) * 2,
            searchRange=search_range,
            entrySelector=entry_selector,
            rangeShift=len(segments) * 2 - search_range
            ).pack()

        return rope(hdr, record, subheader, seg_spec)

    def __getitem__(self, key):
        return self._map[ord(key)]

    def __setitem__(self, key, value):
        self._map[ord(key)] = value
