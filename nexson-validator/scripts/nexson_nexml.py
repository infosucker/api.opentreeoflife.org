#!/usr/bin/env python
from nexson_validator import get_ot_study_info_from_nexml, write_obj_as_nexml


if __name__ == '__main__':
    import sys, codecs, json, os
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
        indentation = int(os.environ.get('NEXSON_INDENTATION_SETTING', 0))
        o = get_ot_study_info_from_nexml(inp)
        json.dump(o, out, indent=indentation, sort_keys=True)
        out.write('\n')
    else:
        o = json.load(codecs.open(inp, 'rU', 'utf-8'))
        write_obj_as_nexml(o, out)

