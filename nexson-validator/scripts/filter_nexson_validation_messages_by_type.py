#!/usr/bin/env python
import sys
SCRIPT_NAME = __name__  #@TODO replace with logger...
ERR_STREAM = sys.stderr #@TODO replace with logger...
from nexson_validator import NexSON, NexSONError, FilteringLogger, WarningCodes

def error(msg):
    global SCRIPT_NAME, ERR_STREAM
    ERR_STREAM.write('{n}: ERROR: {m}'.format(n=SCRIPT_NAME,
                                                m=msg))
    if not msg.endswith('\n'):
        ERR_STREAM.write('\n')

def warn(msg):
    global SCRIPT_NAME, ERR_STREAM
    ERR_STREAM.write('{n}: WARNING: {m}'.format(n=SCRIPT_NAME,
                                                m=msg))
    if not msg.endswith('\n'):
        ERR_STREAM.write('\n')

def info(msg):
    global SCRIPT_NAME, ERR_STREAM
    ERR_STREAM.write('{n}: {m}'.format(n=SCRIPT_NAME,
                                                m=msg))
    if not msg.endswith('\n'):
        ERR_STREAM.write('\n')

if __name__ == '__main__':
    import json
    import os
    import codecs
    import argparse
    parser = argparse.ArgumentParser(description='Validate a json file as Open Tree of Life NexSON')
    parser.add_argument('--verbose', dest='verbose', action='store_true', default=False, help='verbose output')
    parser.add_argument('--filter', dest='filter', type=str, default='', help='type of Warning Code to emit')
    parser.add_argument('input', metavar='filepath', type=unicode, nargs=1, help='filename')
    args = parser.parse_args()
    c = list(WarningCodes.facets)
    c.sort()

    if not args.filter:
        m = 'The --filter option must be used to specify a warning code which should be one of:\n {x}'.format(x='\n '.join(c))
        sys.exit(m)
    SCRIPT_NAME = os.path.split(sys.argv[0])[-1]
    try:
        inp_filepath = args.input[0]
    except:
        sys.exit('Expecting a filepath to a NexSON file as the only argument.\n')
    inp = codecs.open(inp_filepath, 'rU', encoding='utf-8')
    try:
        obj = json.load(inp)
    except ValueError as vx:
        error('Not valid JSON.')
        if args.verbose:
            raise vx
        else:
            sys.exit(1)
    v = FilteringLogger([WarningCodes.facets.index(args.filter)])
    try:
        n = NexSON(obj, v)
    except NexSONError as nx:
        error(nx.value)
        sys.exit(1)
    if v.errors:
        for el in v.errors:
            error(el)
    else:
        for el in v.warnings:
            warn(el)
