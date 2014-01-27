#!/usr/bin/env python
from nexson_validator import to_badgerfish_dict, get_ot_study_info_from_nexml, \
        write_obj_as_xml, write_obj_as_nexml

if __name__ == '__main__':
    import sys, codecs, json
    mode_list = ['xj', 'jx', 'nj', 'jn']
    try:
        mode = sys.argv[1].lower()
        assert(mode in mode_list)
    except:
        opts = '", "'.join(mode_list)
        msg = 'Expecing the first argument to be one of:\n "{o}"'.format(o=opts)
        sys.exit(msg)
    try:
        inp = sys.argv[2]
    except:
        inp = sys.stdin
    out = codecs.getwriter('utf-8')(sys.stdout)
    
    if mode in ['xj', 'nj']:
        if mode == 'xj':
            o = to_badgerfish_dict(inp)
        else:
            o = get_ot_study_info_from_nexml(inp)
        json.dump(o, out, indent=0, sort_keys=True)
        out.write('\n')
    elif mode in ['jx', 'jn']:
        o = json.load(codecs.open(inp, 'rU', 'utf-8'))
        if mode == 'jx':
            write_obj_as_xml(o, out)
        else:
            write_obj_as_nexml(o, out)
        
