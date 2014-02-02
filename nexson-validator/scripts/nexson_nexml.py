#!/usr/bin/env python
from nexson_validator import get_ot_study_info_from_nexml, write_obj_as_nexml

if __name__ == '__main__':
    import sys, codecs, json
    mode_list = ['xj', 'jx']
    try:
        mode = sys.argv[1].lower()
        assert(mode in mode_list)
    except:
        opts = '", "'.join(mode_list)
        msgf = 'Expecing the first argument to be one of:\n "{o}"'
        msg = msgf.format(o=opts)
        sys.exit(msg)
    try:
        inp = sys.argv[2]
    except:
        inp = sys.stdin
    out = codecs.getwriter('utf-8')(sys.stdout)
    if mode == 'xj':
        o = get_ot_study_info_from_nexml(inp)
        json.dump(o, out, indent=0, sort_keys=True)
        out.write('\n')
    else:
        o = json.load(codecs.open(inp, 'rU', 'utf-8'))
        write_obj_as_nexml(o, out)

