#!/usr/bin/env python
from nexson_validator import get_ot_study_info_from_nexml, write_obj_as_nexml


if __name__ == '__main__':
    import sys, codecs, json, os
    _HELP_MESSAGE = '''nexml_nexson converter. Expects an input filepath and optional ouputfilepath:

nexml_nexson.py <input_filepath> [output_filepath]

If no output_filepath is specified, standard output will be used.

UTF-8 encoding is used (for input and output)

Environmental variables NEXSON_INDENTATION_SETTING and NEXML_INDENTATION_SETTING set the
    indentation level (default is 0).
'''
    try:
        inpfn = sys.argv[1]
    except:
        sys.exit(_HELP_MESSAGE)
    
    if inpfn.lower() in ['-h', '-help', '--help']:
        sys.exit(_HELP_MESSAGE)
    
    outfn = None
    if len(sys.argv) > 2:
        outfn = sys.argv[2]
        if len(sys.argv) != 3:
            sys.exit(_HELP_MESSAGE)

    try:
        inp = codecs.open(inpfn, mode='rU', encoding='utf-8')
    except:
        sys.exit('nexson_nexml: Could not open file "{fn}"\n'.format(fn=inpfn))
    try:
        while True:
            c = inp.read(1).strip()
            if c == '<':
                mode = 'xj'
                break
            elif c in '{[':
                mode = 'jx'
                break
            elif c:
                raise ValueError('Expecting input to start with <, {, or [')
    except:
        raise
        sys.exit('nexson_nexml: First character of "{fn}" was not <, {, or [\nInput does not appear to be NeXML or NexSON\n'.format(fn=inpfn))
    inp.seek(0)
    
    if mode == 'xj':
        indentation = int(os.environ.get('NEXSON_INDENTATION_SETTING', 0))
    else:
        indentation = int(os.environ.get('NEXML_INDENTATION_SETTING', 0))
    
    if outfn is not None:
        try:
            out = codecs.open(outfn, mode='w', encoding='utf-8')
        except:
            sys.exit('nexson_nexml: Could not open output filepath "{fn}"\n'.format(fn=outfn))
    else:
        out = codecs.getwriter('utf-8')(sys.stdout)

    if mode == 'xj':
        o = get_ot_study_info_from_nexml(inp)
        json.dump(o, out, indent=indentation, sort_keys=True)
        out.write('\n')
    else:
        o = json.load(inp)
        if indentation > 0:
            indent = ' '*indentation
        else:
            indent = ''
        newline = '\n'
        write_obj_as_nexml(o, out, addindent=indent, newl=newline)

