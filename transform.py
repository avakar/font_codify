import sys, grope, argparse, six, math, os
from otf_tools import OpenTypeFont

def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input', type=argparse.FileType('rb'))
    ap.add_argument('output', nargs='?')
    args = ap.parse_args()

    if not args.output:
        base, ext = os.path.splitext(args.input.name)
        args.output = '{}-out{}'.format(base, ext)
    
    font = OpenTypeFont.parse(args.input)

    cmap = font.get(b'cmap')

    import string
    for ch in string.ascii_lowercase:
        cmap[ch] = cmap[chr(ord(ch) + 1)]

    out_blob = font.save()

    with open(args.output, 'wb') as fout:
        grope.dump(out_blob, fout)

    return 0

if __name__ == '__main__':
    sys.exit(_main())
