from .struct2 import struct_be, parse, parse_array
from grope import BlobIO
import six, grope

@struct_be
class OTF_tag_hdr:
    '''
    H:count
    '''

@struct_be
class OTF_tag_offset:
    '''
    4s:tag
    H:offset
    '''

    @classmethod
    def pair(cls, fin):
        obj = cls.parse(fin)
        return obj.tag, obj.offset

def load_taglist(fin):
    hdr = OTF_tag_hdr.parse(fin)
    return [OTF_tag_offset.pair(fin) for i in six.moves.range(hdr.count)]

@struct_be
class GSUB_hdr:
    '''
    H:majorVersion
    H:minorVersion
    H:scriptListOffset
    H:featureListOffset
    H:lookupListOffset
    '''

@struct_be
class OTF_script_table:
    '''
    H:defaultLangSys
    '''

@struct_be
class OTF_langsys:
    '''
    H:lookupOrder
    H:requiredFeatureIndex
    H:featureIndexCount
    '''

@struct_be
class OTF_feature_index:
    '''
    H:index
    '''

class LangSys:
    def __init__(self, lookup_order, req_feature, features):
        self.lookup_order = lookup_order
        self.req_feature = req_feature
        self.features = features

class Script:
    def __init__(self, default, langs):
        self.default = default
        self.langs = langs

class Feature:
    def __init__(self, tag, params, lookups):
        self.tag = tag
        self.params = params
        self.lookups = lookups

def parse_langsys(blob, features):
    fin = BlobIO(blob)
    hdr = OTF_langsys.parse(fin)
    selected_features = [features[OTF_feature_index.parse(fin).index] for i in six.moves.range(hdr.featureIndexCount)]
    return LangSys(hdr.lookupOrder, hdr.requiredFeatureIndex, selected_features)

def parse_script(blob, features):
    fin = BlobIO(blob)
    hdr = OTF_script_table.parse(fin)
    langsys_list = load_taglist(fin)

    langs = {}
    if hdr.defaultLangSys != 0:
        langs[None] = parse_langsys(blob[hdr.defaultLangSys:], features)

    for lang, offset in langsys_list:
        langs[lang] = parse_langsys(blob[offset:], features)
    return Script(hdr.defaultLangSys, langs)

def parse_scriptlist(blob, features):
    scripts = load_taglist(BlobIO(blob))
    return { tag: parse_script(blob[offset:], features) for tag, offset in scripts }

def parse_feature(blob, tag, lookups):
    fin = BlobIO(blob)
    feature_params, lookup_index_count = parse(fin, '>HH')
    lookup_indices = parse_array(fin, '>H', lookup_index_count)

    return Feature(tag, feature_params, [lookup for idx in lookup_indices for lookup in lookups[idx]])

def parse_feature_list(blob, lookups):
    fin = BlobIO(blob)
    features = load_taglist(fin)
    return [parse_feature(blob[offs:], tag, lookups) for tag, offs in features]

@struct_be
class _cov_range_rec:
    '''
    H:start_gid
    H:end_gid
    H:start_covidx
    '''

def parse_coverage(blob):
    fin = BlobIO(blob)
    format, = parse(fin, '>H')
    if format == 1:
        glyph_count, = parse(fin, '>H')
        glyph_array = parse_array(fin, '>H', glyph_count)
        def cov1(gids, idx):
            try:
                return glyph_array.index(gids[idx])
            except ValueError:
                return None
        return cov1

    if format == 2:
        range_count, = parse(fin, '>H')
        ranges = [_cov_range_rec.parse(fin) for i in six.moves.range(range_count)]
        def cov2(gids, idx):
            gid = gids[idx]
            for range in ranges:
                if range.start_gid <= gid <= range.end_gid:
                    return range.start_covidx + gid - range.start_gid
            return None
        return cov2

    raise RuntimeError('unknown coverage format')

def parse_gsub_lookup1(blob):
    fin = BlobIO(blob)
    format, = parse(fin, '>H')
    if format == 1:
        coverage_offs, delta_glyph_id = parse(fin, '>Hh')
        coverage = parse_coverage(blob[coverage_offs:])
        def sub1(gids, idx):
            if coverage(gids, idx) is not None:
                gids[idx] += delta_glyph_id
        return sub1
    elif format == 2:
        coverage_offs, glyph_count = parse(fin, '>HH')
        substitute_gids = parse_array(fin, '>H', glyph_count)
        coverage = parse_coverage(blob[coverage_offs:])
        def sub2(gids, idx):
            cov_idx = coverage(gids, idx)
            if cov_idx is not None:
                gids[idx] = substitute_gids[cov_idx]
        return sub2

    else:
        raise RuntimeError('unknown subtable format')

def parse_liga(blob):
    fin = BlobIO(blob)
    target_gid, component_count = parse(fin, '>HH')
    components = parse_array(fin, '>H', component_count - 1)
    return components, target_gid

def parse_ligaset(blob):
    fin = BlobIO(blob)
    count, = parse(fin, '>H')
    liga_offsets = parse_array(fin, '>H', count)
    return [parse_liga(blob[offs:]) for offs in liga_offsets]

def parse_gsub_lookup4(blob):
    fin = BlobIO(blob)
    format, cov_offset, ligaset_count = parse(fin, '>HHH')
    if format != 1:
        raise RuntimeError('unknown ligature format')
    coverage = parse_coverage(blob[cov_offset:])
    ligasets = [parse_ligaset(blob[offs:]) for offs in parse_array(fin, '>H', ligaset_count)]

    def sub_liga(gids, idx):
        cov_idx = coverage(gids, idx)
        if cov_idx is None:
            return
        for components, target in ligasets[cov_idx]:
            if gids[idx+1:idx+1+len(components)] == components:
                gids[idx:idx+1+len(components)] = [target]
                break

    return sub_liga

_gsub_lookups = {
    1: parse_gsub_lookup1,
    4: parse_gsub_lookup4,
    }

def parse_lookup(blob):
    fin = BlobIO(blob)
    lookup_type, lookup_flag, subtable_count = parse(fin, '>HHH')
    subtable_offsets = parse_array(fin, '>H', subtable_count)
    mark_filtering_set = parse(fin, '>H')

    assert lookup_type in (1, 3, 4, 6)

    parse_fn = _gsub_lookups.get(lookup_type)
    if parse_fn:
        subbers = [parse_fn(blob[offs:]) for offs in subtable_offsets]
    else:
        subbers = []

    return subbers

def parse_lookup_list(blob):
    fin = BlobIO(blob)
    count, = parse(fin, '>H')
    lookup_offsets = parse_array(fin, '>H', count)

    lookups = []
    for offs in lookup_offsets:
        lookups.append(parse_lookup(blob[offs:]))

    return lookups

class _Subber:
    def __init__(self, lookups):
        self._lookups = lookups

    def sub(self, gids):
        gids = list(gids)

        i = 0
        while i < len(gids):
            for lookup in self._lookups:
                new_i = lookup(gids, i)
                if new_i is not None:
                    i = new_i
                    break
            else:
                i += 1
        
        return gids

class OtfGsubTable:
    def __init__(self, name, blob):
        hdr = GSUB_hdr.parse_blob(blob)

        if (hdr.majorVersion, hdr.minorVersion) != (1, 0):
            raise RuntimeError('unknown GSUB table version')

        lookups = parse_lookup_list(blob[hdr.lookupListOffset:])
        features = parse_feature_list(blob[hdr.featureListOffset:], lookups)
        scripts = parse_scriptlist(blob[hdr.scriptListOffset:], features)

        self.name = name
        self._scripts = scripts

    def make_subber(self, enabled_features, script=b'DFLT', langsys=None):
        lookups = []
        for feature in self._scripts[script].langs[langsys].features:
            if not enabled_features(feature.tag):
                continue
            lookups.extend(feature.lookups)

        return _Subber(lookups)
