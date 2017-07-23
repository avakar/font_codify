import grope, six, math, struct
from grope import rope
from .struct2 import struct_be
from .cmap import OtfCmapTable
from .adv_typo import OtfGsubTable

@struct_be
class _OTF_OFFSET_TABLE:
    '''
    I:sfntVersion
    H:numTables
    H:searchRange
    H:entrySelector
    H:rangeShift
    '''

@struct_be
class _OTF_TABLE_RECORD:
    '''
    4s:tag
    I:checkSum
    I:offset
    I:length
    '''

@struct_be
class _OTF_head:
    '''
    H:majorVersion
    H:minorVersion
    I:fontRevision
    I:checkSumAdjustment
    I:magicNumber
    H:flags
    H:unitsPerEm
    Q:created
    Q:modified
    h:xMin
    h:yMin
    h:xMax
    h:yMax
    H:macStyle
    H:lowestRecPPEM
    h:fontDirectionHint
    h:indexToLocFormat
    h:glyphDataFormat
    '''

def _align4(v):
    return (v + 3) & ~3

def _pad4(v):
    return b'\0' * (_align4(v) - v)

class OtfUnparsedTable:
    def __init__(self, name, blob):
        self.name = name
        self.blob = blob

    def pack(self):
        return self.blob

    def __repr__(self):
        return 'OtfUnparsedTable(name={!r}, blob={!r})'.format(self.name, self.blob)

class OtfUnparsableTable:
    def __init__(self, name, blob):
        self.name = name
        self.blob = blob

    def pack(self):
        return self.blob

class OtfHeadTable:
    def __init__(self, name, blob):
        self.name = name
        self._data = _OTF_head.parse_blob(blob)

    def pack(self, checksum=0):
        self._data.checkSumAdjustment = checksum
        return self._data.pack()

_table_parsers = {
    b'head': OtfHeadTable,
    b'cmap': OtfCmapTable,
    b'GSUB': OtfGsubTable,
    }

def _otf_table_checksum(b):
    r = 0
    while b:
        chunk_len = min(len(b), 16*1024)
        if chunk_len < 4:
            item,  = struct.unpack('>I', bytes(b) + _pad4(len(b)))
            r += item
            break

        chunk_len = chunk_len & ~3
        items = struct.unpack('>{}I'.format(chunk_len // 4), bytes(b[:chunk_len]))

        r = (r + sum(items)) & 0xffffffff
        b = b[chunk_len:]

    return r & 0xffffffff

class OpenTypeFont:
    def __init__(self, tables):
        self._tables = tables
        self._head = self.get(b'head')

    @staticmethod
    def parse(fin):
        fin.seek(0)

        hdr = _OTF_OFFSET_TABLE.parse(fin)
        table_hdrs = [_OTF_TABLE_RECORD.parse(fin) for i in six.moves.range(hdr.numTables)]
        table_hdrs.sort(key=lambda tab: tab.offset)

        blob = grope.wrap_io(fin)
        tables = [OtfUnparsedTable(tab.tag, blob[tab.offset:tab.offset + tab.length]) for tab in table_hdrs]
        return OpenTypeFont(tables)

    def get(self, table_name):
        for i, table in enumerate(self._tables):
            if table.name == table_name:
                break
        else:
            return None

        if isinstance(table, OtfUnparsedTable):
            table = _table_parsers.get(table_name, OtfUnparsableTable)(table_name, table.blob)
            self._tables[i] = table

        return table

    def inv_glyphs(self, gids):
        cmap = self.get(b'cmap')
        return cmap.inv(gids)

    def get_glyphs(self, chars):
        cmap = self.get(b'cmap')
        gids = [cmap[ch] for ch in chars]

        gsub = self.get(b'GSUB')
        subber = gsub.make_subber(lambda name: False)
        return subber.sub(gids)

    def save(self):
        log_num_tables = int(math.floor(math.log2(len(self._tables))))

        hdr = _OTF_OFFSET_TABLE(
            sfntVersion=0x10000,
            numTables=len(self._tables),
            searchRange=2**log_num_tables * 16,
            entrySelector=log_num_tables,
            rangeShift=(len(self._tables) - 2**log_num_tables) * 16)

        table_blobs = [tab.pack() for tab in self._tables]
        table_hdrs = []

        blobs_with_pad = []

        head_offset = None

        data_offset = _OTF_OFFSET_TABLE.size + _OTF_TABLE_RECORD.size * len(self._tables)
        for tab, blob in zip(self._tables, table_blobs):
            if tab.name == b'head':
                head_offset = data_offset

            table_hdrs.append((tab.name, _OTF_TABLE_RECORD(tag=tab.name, checkSum=_otf_table_checksum(blob), offset=data_offset, length=len(blob)).pack()))
            blobs_with_pad.append(blob)
            blobs_with_pad.append(_pad4(len(blob)))
            data_offset += _align4(len(blob))

        table_hdrs.sort()

        pre_full_checksum = rope(
            hdr.pack(),
            *(blob for name, blob in table_hdrs),
            *blobs_with_pad)

        full_checksum = _otf_table_checksum(pre_full_checksum)
        head_blob = self._head.pack(checksum=(0x1b1b0afba - full_checksum) & 0xffffffff)

        return rope(pre_full_checksum[:head_offset], head_blob, pre_full_checksum[head_offset + len(head_blob):])
