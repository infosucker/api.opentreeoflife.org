#!/usr/bin/env python
from cStringIO import StringIO
import xml.dom.minidom
import datetime
import platform
import logging
import codecs
import json
import uuid
import sys
import re

VERSION = '0.0.2a'


###############################################################################
# Code for honeybadgerfish conversion of TreeBase XML to NexSON
###############################################################################

##########################################
# env-sentive logging for easier debugging
##########################################
import os
_LOGGING_LEVEL_ENVAR="NEXSON_LOGGING_LEVEL"
_LOGGING_FORMAT_ENVAR="NEXSON_LOGGING_FORMAT"

def get_logging_level():
    if _LOGGING_LEVEL_ENVAR in os.environ:
        if os.environ[_LOGGING_LEVEL_ENVAR].upper() == "NOTSET":
            level = logging.NOTSET
        elif os.environ[_LOGGING_LEVEL_ENVAR].upper() == "DEBUG":
            level = logging.DEBUG
        elif os.environ[_LOGGING_LEVEL_ENVAR].upper() == "INFO":
            level = logging.INFO
        elif os.environ[_LOGGING_LEVEL_ENVAR].upper() == "WARNING":
            level = logging.WARNING
        elif os.environ[_LOGGING_LEVEL_ENVAR].upper() == "ERROR":
            level = logging.ERROR
        elif os.environ[_LOGGING_LEVEL_ENVAR].upper() == "CRITICAL":
            level = logging.CRITICAL
        else:
            level = logging.NOTSET
    else:
        level = logging.NOTSET
    return level

def get_logger(name="nexson"):
    """
    Returns a logger with name set as given, and configured
    to the level given by the environment variable _LOGGING_LEVEL_ENVAR.
    """

#     package_dir = os.path.dirname(module_path)
#     config_filepath = os.path.join(package_dir, _LOGGING_CONFIG_FILE)
#     if os.path.exists(config_filepath):
#         try:
#             logging.config.fileConfig(config_filepath)
#             logger_set = True
#         except:
#             logger_set = False
    logger = logging.getLogger(name)
    if not hasattr(logger, 'is_configured'):
        logger.is_configured = False
    if not logger.is_configured:
        level = get_logging_level()
        rich_formatter = logging.Formatter("[%(asctime)s] %(filename)s (%(lineno)d): %(levelname) 8s: %(message)s")
        simple_formatter = logging.Formatter("%(levelname) 8s: %(message)s")
        raw_formatter = logging.Formatter("%(message)s")
        default_formatter = None
        logging_formatter = default_formatter
        if _LOGGING_FORMAT_ENVAR in os.environ:
            if os.environ[_LOGGING_FORMAT_ENVAR].upper() == "RICH":
                logging_formatter = rich_formatter
            elif os.environ[_LOGGING_FORMAT_ENVAR].upper() == "SIMPLE":
                logging_formatter = simple_formatter
            elif os.environ[_LOGGING_FORMAT_ENVAR].upper() == "NONE":
                logging_formatter = None
            else:
                logging_formatter = default_formatter
        else:
            logging_formatter = default_formatter
        if logging_formatter is not None:
            logging_formatter.datefmt='%H:%M:%S'
        logger.setLevel(level)
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(logging_formatter)
        logger.addHandler(ch)
        logger.is_configured = True
    return logger
_LOG = get_logger()
##########################################
# end env-sentive logging
##########################################

# unused cruft. Useful if we decide that some ot:... attributes should always map to arrays.
_PLURAL_META_TO_ATT_KEYS_LIST = ('@ot:candidateTreeForSynthesis', '@ot:tag', )
_PLURAL_META_TO_ATT_KEYS_SET = frozenset(_PLURAL_META_TO_ATT_KEYS_LIST)

def _debug_dump_dom(el):
    '''Debugging helper. Prints out `el` contents.'''
    s = [el.nodeName]
    att_container = el.attributes
    for i in xrange(att_container.length):
        attr = att_container.item(i)
        s.append('  @{a}="{v}"'.format(a=attr.name, v=attr.value))
    for c in el.childNodes:
        if c.nodeType == xml.dom.minidom.Node.TEXT_NODE:
            s.append('  {a} type="TEXT" data="{d}"'.format(a=c.nodeName, d=c.data))
        else:
            s.append('  {a} child'.format(a=c.nodeName))
    return '\n'.join(s)

def _add_value_to_dict_bf(d, k, v):
    '''Adds the `k`->`v` mapping to `d`, but if a previous element exists it changes
    the value of for the key to list. 

    This is used in the BadgerFish mapping convention.

    This is a simple multi-dict that is only suitable when you know that you'll never
    store a list or `None` as a value in the dict.
    '''
    prev = d.get(k)
    if prev is None:
        d[k] = v
    elif isinstance(prev, list):
        prev.append(v)
    else:
        d[k] = [prev, v]

def _extract_text_and_child_element_list(minidom_node):
    '''Returns a pair of the "child" content of minidom_node:
        the first element of the pair is a concatenation of the text content
        the second element is a list of non-text nodes.

    The string concatenation strips leading and trailing whitespace from each
    bit of text found and joins the fragments (with no separator between them).
    '''
    tl = []
    ntl = []
    for c in minidom_node.childNodes:
        if c.nodeType == xml.dom.minidom.Node.TEXT_NODE:
            tl.append(c)
        else:
            ntl.append(c)
    try:
        tl = [i.data.strip() for i in tl]
        text_content = ''.join(tl)
    except:
        text_content = ''
    return text_content, ntl


class ATT_TRANSFORM_CODE:
    PREVENT_TRANSFORMATION, IN_FULL_OBJECT, HANDLED, CULL = range(4)
_SUBELEMENTS_OF_LITERAL_META_AS_ATT = frozenset(['content', 'datatype', 'property', 'xsi:type', 'id'])
_HANDLED_SUBELEMENTS_OF_LITERAL_META_AS_ATT = frozenset(['content', 'datatype', 'property', 'xsi:type'])
def _literal_meta_att_decision_fn(name):
    if name in _HANDLED_SUBELEMENTS_OF_LITERAL_META_AS_ATT:
        return ATT_TRANSFORM_CODE.HANDLED, None
    return ATT_TRANSFORM_CODE.IN_FULL_OBJECT, '@' + name


_SUBELEMENTS_OF_RESOURCE_META_AS_ATT = frozenset(['href', 'xsi:type', 'rel', 'id'])
_HANDLED_SUBELEMENTS_OF_RESOURCE_META_AS_ATT = frozenset(['xsi:type', 'rel'])
_OBJ_PROP_SUBELEMENTS_OF_RESOURCE_META_AS_ATT = frozenset(['href', 'id'])
def _resource_meta_att_decision_fn(name):
    if name in _HANDLED_SUBELEMENTS_OF_RESOURCE_META_AS_ATT:
        return ATT_TRANSFORM_CODE.HANDLED, None
    return ATT_TRANSFORM_CODE.IN_FULL_OBJECT, '@' + name

class NexmlTypeError(Exception):
    def __init__(self, m):
        self.m = m
    def __str__(self):
        return self.m

def _coerce_literal_val_to_primitive(datatype, str_val):
    _TYPE_ERROR_MSG_FORMAT = 'Expected meta property {p} to have type {t}, but found "{v}"'
    if datatype == 'xsd:string':
        return str_val
    if datatype in frozenset(['xsd:int', 'xsd:integer', 'xsd:long']):
        try:
            return int(str_val)
        except:
            raise NexmlTypeError(_TYPE_ERROR_MSG_FORMAT.format(p=att_key, t=datatype, v=str_val))
    elif datatype == frozenset(['xsd:float', 'xsd:double']):
        try:
            return float(str_val)
        except:
            raise NexmlTypeError(_TYPE_ERROR_MSG_FORMAT.format(p=att_key, t=datatype, v=str_val))
    elif datatype == 'xsd:boolean':
        if str_val.lower() in frozenset(['1', 'true']):
            return True
        elif str_val.lower() in frozenset(['0', 'false']):
            return False
        else:
            raise NexmlTypeError(_TYPE_ERROR_MSG_FORMAT.format(p=att_key, t=datatype, v=str_val))
    else:
        _LOG.debug('unknown xsi:type {t}'.format(t=datatype))
        return None # We'll fall through to here when we encounter types we do not recognize

def _literal_transform_meta_key_value(minidom_meta_element):
    att_key = None
    dt = minidom_meta_element.getAttribute('datatype') or 'xsd:string'
    att_str_val = minidom_meta_element.getAttribute('content')
    att_key = minidom_meta_element.getAttribute('property')
    full_obj = {}
    if att_key is None:
        _LOG.debug('"property" missing from literal meta')
        return None
    el_id = None
    att_container = minidom_meta_element.attributes
    for i in xrange(att_container.length):
        attr = att_container.item(i)
        handling_code, new_name = _literal_meta_att_decision_fn(attr.name)
        if handling_code == ATT_TRANSFORM_CODE.IN_FULL_OBJECT:
            full_obj[new_name] = attr.value
        else:
            assert (handling_code == ATT_TRANSFORM_CODE.HANDLED)
            
    if not att_str_val:
        att_str_val, ntl = _extract_text_and_child_element_list(minidom_meta_element)
        if len(ntl) > 0: # #TODO: the case of len(ntl) == 1, is a nested meta, and should be handled.
            _LOG.debug('Nested meta elements are not legal for LiteralMeta (offending property={p}'.format(p=att_key))
            return None
    att_key = '^' + att_key
    trans_val = _coerce_literal_val_to_primitive(dt, att_str_val)
    if trans_val is None:
        return None
    if full_obj:
        full_obj['$'] = trans_val
        return att_key, full_obj
    return att_key, trans_val

def _resource_transform_meta_key_value(minidom_meta_element):
    rel = minidom_meta_element.getAttribute('rel')
    if rel is None:
        _LOG.debug('"rel" missing from ResourceMeta')
        return None
    full_obj = {}
    el_id = None
    att_container = minidom_meta_element.attributes
    for i in xrange(att_container.length):
        attr = att_container.item(i)
        handling_code, new_name = _resource_meta_att_decision_fn(attr.name)
        if handling_code == ATT_TRANSFORM_CODE.IN_FULL_OBJECT:
            full_obj[new_name] = attr.value
        else:
            assert (handling_code == ATT_TRANSFORM_CODE.HANDLED)
    rel = '^' + rel
    att_str_val, ntl = _extract_text_and_child_element_list(minidom_meta_element)
    if att_str_val:
        _LOG.debug('text content of ResourceMeta of rel="{r}"'.format(r=rel))
        return None
    if ntl:
        sys.exit('handling nested metas is a TODO\n')
    if not full_obj:
        _LOG.debug('ResourceMeta of rel="{r}" without condents ("href" attribute or nested meta)'.format(r=rel))
        return None
    return rel, full_obj

def _transform_meta_key_value(minidom_meta_element):
    '''Checks if the minidom_meta_element can be represented as a
        key/value pair in a object.

    Returns (key, value) ready for JSON serialization, OR
            `None` if the element can not be treated as simple pair.
    If `None` is returned, then more literal translation of the 
        object may be required.
    '''
    xt = minidom_meta_element.getAttribute('xsi:type')
    if xt == 'nex:LiteralMeta':
        return _literal_transform_meta_key_value(minidom_meta_element)
    elif xt == 'nex:ResourceMeta':
        return _resource_transform_meta_key_value(minidom_meta_element)
    else:
        _LOG.debug('xsi:type attribute not LiteralMeta or ResourceMeta')
        return None


def _gen_hbf_el(x):
    '''
    Builds a dictionary from the ElementTree element x
    The function
    Uses as hacky splitting of attribute or tag names using {}
        to remove namespaces.
    returns a pair of: the tag of `x` and the honeybadgerfish
        representation of the subelements of x
    '''
    obj = {}
    # grab the tag of x
    el_name = x.nodeName
    assert el_name is not None
    # add the attributes to the dictionary
    att_container = x.attributes
    ns_obj = {}
    for i in xrange(att_container.length):
        attr = att_container.item(i)
        n = attr.name
        t = None
        if n.startswith('xmlns'):
            if n == 'xmlns':
                t = '$'
            elif n.startswith('xmlns:'):
                t = n[6:] # strip off the xmlns:
        if t is None:
            obj['@' + n] = attr.value
        else:
            ns_obj[t] = attr.value
    if ns_obj:
        obj['@xmlns'] = ns_obj

    x.normalize()
    # store the text content of the element under the key '$'
    text_content, ntl = _extract_text_and_child_element_list(x)
    if text_content:
        obj['$'] = text_content
    # accumulate a list of the children names in ko, and 
    #   the a dictionary of tag to xml elements.
    # repetition of a tag means that it will map to a list of
    #   xml elements
    cd = {}
    ko = []
    ks = set()
    for child in ntl:
        k = child.nodeName
        if k == 'meta':
            matk, matv = _transform_meta_key_value(child)
            _add_value_to_dict_bf(obj, matk, matv)
        else:
            if k not in ks:
                ko.append(k)
                ks.add(k)
            _add_value_to_dict_bf(cd, k, child)

    # Converts the child XML elements to dicts by recursion and
    #   adds these to the dict.
    for k in ko:
        v = cd[k]
        if not isinstance(v, list):
            v = [v]
        dcl = []
        ct = None
        for xc in v:
            ct, dc = _gen_hbf_el(xc)
            dcl.append(dc)
        # this assertion will trip is the hacky stripping of namespaces
        #   results in a name clash among the tags of the children
        assert ct not in obj
        obj[ct] = dcl
    return el_name, obj

def to_honeybadgerfish_dict(src, encoding=u'utf8'):
    '''Takes either:
            (1) a file_object, or
            (2) (if file_object is None) a filepath and encoding
    Returns a dictionary with the keys/values encoded according to the honeybadgerfish convention
    See https://github.com/OpenTreeOfLife/api.opentreeoflife.org/wiki/HoneyBadgerFish

    Caveats/bugs:
        
    '''
    if isinstance(src, str):
        src = codecs.open(src, 'rU', encoding=encoding)
    doc = xml.dom.minidom.parse(src)
    root = doc.documentElement
    key, val = _gen_hbf_el(root)
    return {key: val}

def _python_instance_to_nexml_meta_datatype(v):
    if isinstance(v, int) or isinstance(v, long):
        return 'xsd:int'
    if isinstance(v, float):
        return 'xsd:float'
    if isinstance(v, bool):
        return 'xsd:boolean'
    return 'xsd:string'

# based on http://www.w3.org/TR/xmlschema-2
# xsd:string is considered the default...
_OT_META_PROP_TO_DATATYPE = {
    'ot:focalClade': 'xsd:int',
    'ot:isLeaf': 'xsd:boolean',
    'ot:notIntendedForSynthesis': 'xsd:boolean',
    'ot:notUsingRootedTrees': 'xsd:boolean',
    'ot:ottid': 'xsd:int',
    'ot:studyYear' : 'xsd:int',
    }
_XSD_TYPE_TO_VALID_PYTHON_TYPES = {
    'numeric': set([float, int, long]),
    'xsd:int': set([int, long]),
    'xsd:float': set([float]),
    'xsd:boolean': set([bool]),
    'xsd:string': set([str, unicode]),
}
_XSD_TYPE_COERCION = {
    'numeric': float,
    'xsd:int': int,
    'xsd:float': float,
    'xsd:boolean': lambda x: x.lower() == 'true',
    'xsd:string': unicode,
}


def _create_sub_el(doc, parent, tag, attrib, data=None):
    el = doc.createElement(tag)
    if attrib:
        for att_key, att_value in attrib.items():
            el.setAttribute(att_key, att_value)
    if parent:
        parent.appendChild(el)
    if data:
        el.appendChild(doc.createTextNode(unicode(data)))
    return el

def _add_nested_resource_meta(doc, parent, name, value, att_dict):
    # assuming the @href holds "value" so we don't actually use the value arg currently.
    raise NotImplementedError('Nested Meta')
    tatts = {'xsi:type':  'nex:ResourceMeta',
             'rel': name}
    for k, v in att_dict.items():
        assert(k.startswith('@'))
        real_att = k[1:]
        tatts[real_att] = v
    m = _create_sub_el(doc, parent, 'meta', tatts)
def _add_href_resource_meta(doc, parent, name, value, att_dict):
    # assuming the @href holds "value" so we don't actually use the value arg currently.
    tatts = {'xsi:type':  'nex:ResourceMeta',
             'rel': name}
    for k, v in att_dict.items():
        assert(k.startswith('@'))
        real_att = k[1:]
        tatts[real_att] = v
    m = _create_sub_el(doc, parent, 'meta', tatts)
def _add_literal_meta(doc, parent, name, value, att_dict):
    # assuming the @href holds "value" so we don't actually use the value arg currently.
    tatts = {'xsi:type':  'nex:LiteralMeta',
             'datatype': _python_instance_to_nexml_meta_datatype(value),
             'property': name
             }
    for k, v in att_dict.items():
        if k in ['@content', '$']:
            continue
        assert(k.startswith('@'))
        real_att = k[1:]
        tatts[real_att] = v
    m = _create_sub_el(doc, parent, 'meta', tatts, value)


def _add_meta_value_to_xml_doc(doc, parent, key, value):
    if isinstance(value, dict):
        href = value.get('@href')
        if href is None:
            content = value['$']
            if isinstance(content, dict):
                _add_nested_resource_meta(doc, parent, name=key, value=content, att_dict=value)
            else:
                _add_literal_meta(doc, parent, name=key, value=content, att_dict=value)
        else:
            _add_href_resource_meta(doc, parent, name=key, value=href, att_dict=value)
    else:
        _add_literal_meta(doc, parent, name=key, value=value, att_dict={})

def _add_meta_xml_element(doc, parent, meta_dict):
    '''
    assert key != u'meta':
            if 'datatype' not in ca:
                dsv = _OT_META_PROP_TO_DATATYPE.get(ca.get('property'))
                if dsv is None:
                    dsv = _python_instance_to_nexml_meta_datatype(cd)
                ca['datatype'] = dsv
            cel = _create_sub_el(doc, parent, u'meta', ca, cd)
    '''
    if not meta_dict:
        return
    meta_el = _create_sub_el(doc, parent, 'meta', None, None)
    for key, value in meta_dict.items():
        if isinstance(value, list):
            for el in value:
                _add_meta_value_to_xml_doc(doc, meta_el, key, el)
        else:
            _add_meta_value_to_xml_doc(doc, meta_el, key, value)

def _add_child_list_to_xml_doc_subtree(doc, parent, child_list, key, key_order):
    if not isinstance(child_list, list):
        child_list = [child_list]
    for child in child_list:
        ca, cd, cc, mc = _break_keys_by_hbf_type(child)
        cel = _create_sub_el(doc, parent, key, ca, cd)
        _add_meta_xml_element(doc, cel, mc)
        _add_xml_doc_subtree(doc, cel, cc, key_order)

def _add_xml_doc_subtree(doc, parent, children_dict, key_order=None):
    written = set()
    if key_order:
        for t in key_order:
            k, next_order_el = t
            assert(next_order_el is None or isinstance(next_order_el, tuple))
            if k in children_dict:
                child_list = children_dict[k]
                written.add(k)
                _add_child_list_to_xml_doc_subtree(doc, parent, child_list, k, next_order_el)
    ksl = children_dict.keys()
    ksl.sort()
    for k in ksl:
        child_list = children_dict[k]
        if k not in written:
            _add_child_list_to_xml_doc_subtree(doc, parent, child_list, k, None)


def _break_keys_by_hbf_type(o):
    '''Breaks o into a triple two dicts and text data by key type:
        attrib keys (start with '@'),
        text (value associated with the '$' or None),
        child element keys (all others)
    '''
    ak = {}
    tk = None
    ck = {}
    mc = {}
    for k, v in o.items():
        if k.startswith('@'):
            if k == '@xmlns':
                ak['xmlns'] = v['$']
                for nsk, nsv in v.items():
                    if nsk != '$':
                        ak['xmlns:' + nsk] = nsv
            else:
                s = k[1:]
                ak[s] = unicode(v)
        elif k == '$':
            tk = v
        elif k.startswith('^'):
            s = k[1:]
            mc[s] = v
        else:
            ck[k] = v
    return ak, tk, ck, mc

def get_ot_study_info_from_nexml(src, encoding=u'utf8'):
    '''Converts an XML doc to JSON using the honeybadgerfish convention (see to_honeybadgerfish_dict)
    and then prunes elements not used by open tree of life study curartion.

    Currently:
        removes nexml/characters @TODO: should replace it with a URI for 
            where the removed character data can be found.
    '''
    o = to_honeybadgerfish_dict(src)
    try:
        if ('nexml' in o) and ('characters' in o['nexml']):
            del o['nexml']['characters']
    except:
        pass
    return o

def get_ot_study_info_from_treebase_nexml(src, encoding=u'utf8'):
    '''Just a stub at this point. Intended to normalize treebase-specific metadata 
    into the locations where open tree of life software that expects it. 

    `src` can be a string (filepath) or a input file object.
    @TODO: need to investigate which metadata should move or be copied
    '''
    o = get_ot_study_info_from_nexml(src, encoding=encoding)
    return o


def _nex_obj_2_nexml_doc(doc, obj_dict, root_atts=None):
    base_keys = obj_dict.keys()
    assert(len(base_keys) == 1)
    root_name = base_keys[0]
    root_obj = obj_dict[root_name]
    atts, data, children, meta_children = _break_keys_by_hbf_type(root_obj)
    atts['generator'] = 'org.opentreeoflife.api.nexonvalidator.json2xml'
    if not 'version' in atts:
        atts['version'] = '0.9'
    if root_atts:
        for k, v in root_atts.items():
            atts[k] = v
    r = _create_sub_el(doc, doc, root_name, atts, data)
    _add_meta_xml_element(doc, r, meta_children)
    nexml_key_order = (('meta', None),
                       ('otus', (('meta', None),
                                 ('otu', None)
                                )
                       ),
                       ('characters', (('meta', None),
                                       ('format',(('meta', None),
                                                  ('states', (('state', None),
                                                              ('uncertain_state_set', None),
                                                             )
                                                  ),
                                                  ('char', None)
                                                 ),
                                       ),
                                       ('matrix', (('meta', None),
                                                   ('row', None),
                                                  )
                                       ),
                                      ),
                       ),
                       ('trees', (('meta', None),
                                  ('tree', (('meta', None),
                                            ('node', None),
                                            ('edge', None)
                                           )
                                  )
                                 )
                       )
                      )
    _add_xml_doc_subtree(doc, r, children, nexml_key_order)


def write_obj_as_nexml(obj_dict, file_obj, addindent='', newl=''):
    root_atts = {
        "xmlns:nex": "http://www.nexml.org/2009",
        "xmlns": "http://www.nexml.org/2009",
        "xmlns:xsd": "http://www.w3.org/2001/XMLSchema#",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xmlns:ot": "http://purl.org/opentree/nexson",
    }
    extra = {
        "xmlns:dc": "http://purl.org/dc/elements/1.1/",
        "xmlns:dcterms": "http://purl.org/dc/terms/",
        "xmlns:prism": "http://prismstandard.org/namespaces/1.2/basic/",
        "xmlns:rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "xmlns:rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "xmlns:skos": "http://www.w3.org/2004/02/skos/core#",
        "xmlns:tb": "http://purl.org/phylo/treebase/2.0/terms#",
    }
    doc = xml.dom.minidom.Document()
    _nex_obj_2_nexml_doc(doc, obj_dict, root_atts=root_atts)
    doc.writexml(file_obj, addindent=addindent, newl=newl)


################################################################################
# End of honeybadgerfish...
################################################################################

def create_validation_nexson(obj, warning_codes_to_skip, retain_deprecated=True):
    '''Creates a validatation logger and then creates an object of type NexSON
    Returns the pair:
        validatation_log, NexSON object
    Note that obj can be modified if retain_deprecated is not True.
    Also note that the "raw" dict within the returned NexSON object will hold
        references to parts of `obj`
    '''
    if warning_codes_to_skip:
        v = FilteringLogger(codes_to_skip=list(warning_codes_to_skip), store_messages=True)
    else:
        v = ValidationLogger(store_messages=True)
    v.retain_deprecated = retain_deprecated
    if retain_deprecated:
        v.warn_about_fixed = True
    n = NexSON(obj, v)
    return v, n

def create_annotation_blob(ann_event, agent, messages):
    '''Returns a JSON-serializable blob that could be inserted into a study-level meta object
    if messages are being put into that location. (this is not the recommended place for new
    annotations)
    '''
    return [{
                '@property': 'ot:annotationEvents',
                '@xsi:type': 'nex:ResourceMeta',
                'annotation': [
                    ann_event
                ],
            }, {
                '@property': 'ot:agents',
                '@xsi:type': 'nex:ResourceMeta',
                'agent': [
                    agent
                ],
            }, {
                '@property': 'ot:messages',
                '@xsi:type': 'nex:ResourceMeta',
                'message': messages,
            },
    ]

def append_messages_to_obj(obj, message_list, meta=None, ot_messages=None):
    if not message_list:
        return
    if ot_messages is None:
        ot_messages = {
            '@property': 'ot:messages',
            '@xsi:type': 'nex:ResourceMeta',
            'message': [],
            }
        if meta is None:
            if isinstance(obj, list):
                meta = obj
            else:
                meta = obj.setdefault('meta', [])
            if not isinstance(meta, list):
                meta = [meta]
                obj['meta'] = meta
        meta.append(ot_messages)
    ot_messages['message'].extend(message_list)

def finalize_message_list(message_list):
    for m in message_list:
        embed_refers_to_in_message(m)

def embed_refers_to_in_message(m):
    try:
        address = m[' _address'] #@TEMP hack
        del m[' _address'] #@TEMP hack
        m['refersTo'] = convert_dict_to_honeybadgerfish_att_dict(address.path)
    except:
        pass

def add_or_replace_annotation(obj, annotation_event, agent, message_list, rich_logger):
    '''Takes a nexson object `obj` and an annotation_event, agent, message_list as 
        created by prepare_annotation

    This function will remove all annotations from obj that:
        1. were produced by the same agent (based on agent['@id'], and
        2. have no messages that are flagged as messages to be preserved (values for 'preserve' that evaluate to true)
    '''
    id2obj = None
    if rich_logger:
        id2obj = rich_logger.id2obj
    nexml_obj = obj['nexml']
    former_meta = nexml_obj.setdefault('meta', [])
    if not isinstance(former_meta, list):
        former_meta = [former_meta]
        nexml_obj['meta'] = former_meta
    event_ids_to_remove = []
    need_to_add_agent_meta = True
    matching_agent_id = agent['@id']
    ot_annotation_events = None
    ot_agents = None
    ot_messages = None
    for meta_el in former_meta:
        p = meta_el.get('@property', '')
        if p == 'ot:messages':
            ot_messages = meta_el
        elif p == 'ot:agents':
            ot_agents = meta_el
            try:
                if meta_el['agent']['@id'] == matching_agent_id:
                    need_to_add_agent_meta = False
            except:
                pass
        if p != 'ot:annotationEvents':
            continue
        ot_annotation_events = meta_el
        indices_to_pop = []
        annotation_list = meta_el.get('annotation', [])
        for ai, el in enumerate(annotation_list):
            try:
                if el.get('@wasAssociatedWithAgentId') == agent['@id']:
                    event_ids_to_remove.append(el['@id'])
                    indices_to_pop.append(ai)
            except:
                # different annotation structures could yield IndexErrors or other exceptions.
                # these are not the annotations that you are looking for....
                pass
        if len(indices_to_pop) > 0:
            # walk backwards so pops won't change the meaning of stored indices
            for annotation_ind in indices_to_pop[-1::-1]:
                annotation_list.pop(annotation_ind)
    if ot_annotation_events is None:
        ot_annotation_events = {
            "@property": "ot:annotationEvents", 
            "@xsi:type": "nex:ResourceMeta", 
            "annotation": [],
            }
        former_meta.append(ot_annotation_events)
    ot_annotation_events['annotation'].append(annotation_event)
    if need_to_add_agent_meta:
        if ot_agents is None:
            ot_agents = {
                "@property": "ot:agents", 
                "@xsi:type": "nex:ResourceMeta", 
                "agent": [],
                }
            former_meta.append(ot_agents)
        ot_agents['agent'].append(agent)
    for m in message_list:
        sub_m_list = [m]
        address = m[' _address'] #@TEMP hack
        del m[' _address'] #@TEMP hack
        try:
            tl = find_target_of_nexpath(nexml_obj, address, id2obj)
            if not isinstance(tl, list):
                tl = [tl]
        except:
            tl = [nexml_obj]
        for target in tl:
            append_messages_to_obj(target, sub_m_list)
    
        #append_messages_to_obj(nexml_obj, message_list, meta=former_meta, ot_messages=ot_messages)
    
def prepare_annotation(validation_logger, 
                       author_name='',
                       invocation=tuple(),
                       annotation_label='',
                       author_version=VERSION,
                       url='https://github.com/OpenTreeOfLife/api.opentreeoflife.org',
                       description="validator of NexSON constraints as well as constraints that would allow a study to be imported into the Open Tree of Life's phylogenetic synthesis tools"
                       ):
    '''Returns AnnotationEvent object, Agent object, and list of message objects.
    ''' 
    checks_performed = list(WarningCodes.numeric_codes_registered)
    for code in validation_logger.codes_to_skip:
        try:
            checks_performed.remove(code)
        except:
            pass
    checks_performed = [WarningCodes.facets[i] for i in checks_performed]
    nuuid = 'meta-' + str(uuid.uuid1())
    agent_id = author_name #@TODO should verify uniqueness of this ID...
    annotation_event = {
        '@id': nuuid,
        '@description': description,
        '@wasAssociatedWithAgentId': agent_id,
        '@dateCreated': datetime.datetime.utcnow().isoformat(),
        '@passedChecks': (len(validation_logger.errors) == 0) and (len(validation_logger.warnings) == 0),
        '@preserve': False,
        }
    agent = {
        '@id': agent_id,
        '@name': author_name,
        '@url': url,
        '@description': description,
        '@version': author_version,
        'invocation': {
            'commandLine': [{'$' : i } for i in invocation],
            'checksPerformed': [{'$' : i } for i in checks_performed],
            'otherProperty' : [
                {
                    'name': 'pythonVersion',
                    'value': 'STRING',
                    '$': platform.python_version(),
                },
                {
                    'name': 'pythonImplementation',
                    'value': 'STRING',
                    '$': platform.python_implementation(),
                },
                ]
            }
        }
    message_list = []
    for m in validation_logger.errors:
        d = m.as_honeybadgerfish()
        d['@severity'] = 'ERROR'
        message_list.append(d)
    for m in validation_logger.warnings:
        d = m.as_honeybadgerfish()
        d['@severity'] = 'WARNING'
        message_list.append(d)
    for message_count, d in enumerate(message_list):
        d['@preserve'] = False
        d['@wasGeneratedById'] = nuuid
        d['@id'] = '{p}m{i:d}'.format(p=nuuid, i=message_count)
        
    return annotation_event, agent, message_list

class NexSONError(Exception):
    def __init__(self, v):
        self.value = v
    def __str__(self):
        return repr(self.v)

################################################################################
# Warning codes and message types...
# Each type of Warning/Error should have its own
################################################################################

# An enum of WARNING_CODES
class WarningCodes():
    '''Enumeration of Warning/Error types. For internal use.

    WarningCodes.facets maps int -> warning name.
    Each of these names will also be an attribute of WarningCodes.
    WarningCodes.numeric_codes_registered is (after some mild monkey-patching)
        a set of the integers registered.
    '''
    facets = ('MISSING_MANDATORY_KEY',
              'MISSING_OPTIONAL_KEY',
              'UNRECOGNIZED_KEY',
              'MISSING_LIST_EXPECTED',
              'DUPLICATING_SINGLETON_KEY',
              'REFERENCED_ID_NOT_FOUND',
              'REPEATED_ID',
              'MULTIPLE_ROOT_NODES',
              'NO_ROOT_NODE',
              'MULTIPLE_EDGES_FOR_NODES',
              'CYCLE_DETECTED',
              'DISCONNECTED_GRAPH_DETECTED',
              'INCORRECT_ROOT_NODE_LABEL',
              'TIP_WITHOUT_OTU',
              'TIP_WITHOUT_OTT_ID',
              'MULTIPLE_TIPS_MAPPED_TO_OTT_ID',
              'NON_MONOPHYLETIC_TIPS_MAPPED_TO_OTT_ID',
              'INVALID_PROPERTY_VALUE',
              'PROPERTY_VALUE_NOT_USEFUL',
              'UNRECOGNIZED_PROPERTY_VALUE',
              'MULTIPLE_TREES',
              'UNVALIDATED_ANNOTATION',
              'UNRECOGNIZED_TAG',
              'CONFLICTING_PROPERTY_VALUES',
              'NO_TREES',
              'DEPRECATED_PROPERTY',
              'UNNECESSARY_ATTRIBUTE',
              'UNEXPECTED_META_DATATYPE',
              'INCORRECT_META_DATATYPE_SPECIFIED',
              'INCORRECT_META_DATATYPE_FOUND',
              'METADATA_TYPE_COERCION',
              'INCOMPATIBLE_META_DATATYPE_FOUND',
              )
    numeric_codes_registered = []
# monkey-patching WarningCodes...
for _n, _f in enumerate(WarningCodes.facets):
    setattr(WarningCodes, _f, _n)
    WarningCodes.numeric_codes_registered.append(_n)
WarningCodes.numeric_codes_registered = set(WarningCodes.numeric_codes_registered)
# End of WarningCodes enum

class SeverityCodes(object):
    '''An enum of Warning/Error severity
    '''
    ERROR, WARNING = range(2)
    facets = ['ERROR', 'WARNING']
    numeric_codes_registered = set(range(len(facets)))

class NexsonAddress(object):
    '''Encapsulates a reference to an addressable object in a NexSON blob.
    A class is needed because the reference is encoded in multiple fields:
    '''
    def __init__(self, container, subelement=None, property_name=None):
        '''
        `container` is the NexSON element that generated the warning, if
            that element has an ID.
        `subelement` is used to provide and address (container.subelement)
            for elements (such as meta elements) that do not have IDs.
        `property_name` is used when the error is associated with a property of
            a meta element
        '''
        self._container = container
        self._subelement = subelement
        if property_name:
            assert subelement == 'meta'
            self._property_name = property_name
        else:
            self._property_name = None
    def get_property_name(self):
        return self._property_name
    property_name = property(get_property_name)
    def get_path_dict(self):
        p = self._container.get_path_dict(self._subelement, self._property_name)
        if False:
            p['idref'] = self._container.nexson_id
        return p
    path = property(get_path_dict)
    def write_path_suffix_str(self, out):
        if self._subelement:
            out.write(' in "{el}"'.format(el=self._subelement))
        if self._container is not None:
            out.write(' in "{el}"'.format(el=self._container.get_tag_context()))
        out.write('\n')

def find_target_of_nexpath(d, nexson_address, id2obj):
    '''Finds the object referred to by nexson_address.
    Assumes that `d` is the top level (nexml object) and
    id2obj is a dictionary mapping any object nexson id to that object.
    '''
    p = nexson_address.path
    t = p['top']
    el = None
    is_meta = False
    if t == 'meta':
        annotation_id = p.get('annotationID')
        if annotation_id:
            el = id2obj[annotation_id]
        else:
            message_id = p.get('messageID')
            if message_id:
                el = id2obj[message_id]
            else:
                meta_id = p.get('metaID')
                if meta_id:
                    el = id2obj[metaID]
                else:
                    el = d['meta']
                    is_meta = True
    elif t == 'otus':
        otu_id = p.get('otuID')
        if otu_id is not None:
            el = id2obj[otu_id]
        else:
            otus_id = p['otusID']
            el = id2obj[otus_id]
    elif t == 'trees':
        edge_id = p.get('edgeID')
        if edge_id is not None:
            el = id2obj[edge_id]
        else:
            node_id = p.get('nodeID')
            if node_id is not None:
                el = id2obj[node_id]
            else:
                tree_id = p.get('treeID')
                if tree_id is not None:
                    el = id2obj[tree_id]
                else:
                    trees_id = p['treesID']
                    el = id2obj[trees_id]
    elif t == 'nexml':
        el = id2obj[p['nexsonID']]
    else:
        assert t in ['meta', 'otus', 'trees', 'nexml']
    if p.get('inMeta'):
        prop = p['property']
        #sys.stderr.write('property in target="{p}"\n'.format(p=prop))
        #sys.stderr.write('el="{p}"\n'.format(p=str(el)))
        assert(el is not None)
        found = False
        
        if isinstance(el, list):
            el_list = el
        else:
            el_list = [el]
        matching_el_list = []
        for el in el_list:
            if not is_meta:
                mel = el.get('meta', tuple())
            elif not isinstance(el, list):
                mel = [el]
            else:
                mel = el
            for e in mel:
                if e['@property'] == prop:
                    matching_el_list.append(e)
        #sys.stderr.write('matching_el_list="{p}"\n'.format(p=str(matching_el_list)))
        return matching_el_list
    return el

def convert_dict_to_honeybadgerfish_dict(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = convert_dict_to_honeybadgerfish_dict(v)
        else:
            out[k] = {'$': v}
    return out

def convert_dict_to_honeybadgerfish_att_dict(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = convert_dict_to_honeybadgerfish_dict(v)
        else:
            out['@' + k] = v
    return out

################################################################################
# In a burst of over-exuberant OO-coding, MTH added a class for 
#   each class of Warning/Error.
# 
# Each subclass typically tweaks the writing of the message and the payload
#   that constitutes the "data" blob in the JSON.
################################################################################
class WarningMessage(object):
    '''This base class provides the basic functionality of keeping
    track of the "address" of the element that triggered the warning, 
    the severity code, and methods for writing to free text stream or JSON.
    '''
    def __init__(self,
                 warning_code,
                 data,
                 address,
                 severity=SeverityCodes.WARNING):
        '''
            `warning_code` should be a facet of WarningCodes
            `data` is an object whose details depend on the specific subclass
                of warning that is being created
            `address` is a NexsonAddress offending element

            `severity` is either SeverityCodes.WARNING or SeverityCodes.ERROR
        '''
        self.warning_code = warning_code
        assert warning_code in WarningCodes.numeric_codes_registered
        self.warning_data = data
        self.severity = severity
        assert severity in SeverityCodes.numeric_codes_registered
        self.address = address
    def __unicode__(self, prefix=''):
        b = StringIO()
        ci = codecs.lookup('utf8')
        s = codecs.StreamReaderWriter(b, ci.streamreader, ci.streamwriter)
        self.write(s, prefix)
        return s.getvalue()
    def getvalue(self, prefix=''):
        return self.__unicode__(prefix=prefix)
    def as_dict(self):
        d = {
            'severity': SeverityCodes.facets[self.severity],
            'code': WarningCodes.facets[self.warning_code],
            'humanMessage': self.__unicode__(),
            'refersTo': self.address.path
        }
        dd = self.convert_data_for_json(),
        if dd:
            d['data'] = dd
        return d
    def as_honeybadgerfish(self):
        '''Hiding a ' _address' attribute in this object so that refersTo or the obj
        can be used later #@TEMP hack.'''
        return {
            '@severity': SeverityCodes.facets[self.severity],
            '@code': WarningCodes.facets[self.warning_code],
            '@humanMessage': self.__unicode__(),
            ' _address': self.address #@TEMP hack
        }
        dd = self.convert_data_for_json(),
        if dd:
            d['data'] = convert_dict_to_honeybadgerfish_dict(dd)
        return d
    def convert_data_for_json(self):
        wc = self.warning_code
        data = self.warning_data
        return data
    def _write_message_suffix(self, out):
        self.address.write_path_suffix_str(out)

class MissingExpectedListWarning(WarningMessage):
    def __init__(self, data, address, severity=SeverityCodes.ERROR):
        WarningMessage.__init__(self, WarningCodes.MISSING_LIST_EXPECTED, data=data, address=address, severity=severity)
    def write(self, outstream, prefix):
        outstream.write('{p}Expected a list found "{k}"'.format(p=prefix, k=type(self.data)))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return type(self.data)

class UnrecognizedKeyWarning(WarningMessage):
    def __init__(self, key, address, severity=SeverityCodes.WARNING):
        WarningMessage.__init__(self, WarningCodes.UNRECOGNIZED_KEY, data=key, address=address, severity=severity)
        self.key = key
    def write(self, outstream, prefix):
        outstream.write('{p}Unrecognized key "{k}"'.format(p=prefix, k=self.key))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.key

class MissingOptionalKeyWarning(WarningMessage):
    def __init__(self, key, address, severity=SeverityCodes.WARNING):
        WarningMessage.__init__(self, WarningCodes.MISSING_OPTIONAL_KEY, data=key, address=address, severity=severity)
        self.key = key
    def write(self, outstream, prefix):
        if self.key:
            outstream.write('{p}Missing optional key "{k}"'.format(p=prefix, k=self.key))
        else:
            outstream.write('{p}Missing optional key "@property={k}"'.format(p=prefix, k=self.address.property_name)) # MTH hack to get tests to pass
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        if self.key:
            return self.key
        else:
            return "@property={k}".format(k=self.address.property_name) # MTH hack to get tests to pass

class DuplicatingSingletonKeyWarning(WarningMessage):
    def __init__(self, address, severity=SeverityCodes.ERROR):
        WarningMessage.__init__(self, WarningCodes.DUPLICATING_SINGLETON_KEY, data=None, address=address, severity=severity)
        self.key = address.property_name
    def write(self, outstream, prefix):
        outstream.write('{p}Multiple instances found for a key ("{k}") which was expected to be found once'.format(p=prefix, k=self.key))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.key
class DeprecatedMetaPropertyWarning(WarningMessage):
    def __init__(self, address, severity=SeverityCodes.WARNING):
        WarningMessage.__init__(self, WarningCodes.DEPRECATED_PROPERTY, data=None, address=address, severity=severity)
        self.key = address.property_name
    def write(self, outstream, prefix):
        outstream.write('{p}Found a deprecated a property ("{k}")'.format(p=prefix, k=self.key))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.key


class RepeatedIDWarning(WarningMessage):
    def __init__(self, identifier, address, severity=SeverityCodes.ERROR):
        WarningMessage.__init__(self, WarningCodes.REPEATED_ID, data=identifier, address=address, severity=severity)
        self.identifier = identifier
    def write(self, outstream, prefix):
        outstream.write('{p}An ID ("{k}") was repeated'.format(p=prefix, k=self.identifier))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.identifier

class ReferencedIDNotFoundWarning(WarningMessage):
    def __init__(self, key, identifier, address, severity=SeverityCodes.ERROR):
        d = {'key': key, 'value': identifier}
        WarningMessage.__init__(self, WarningCodes.REFERENCED_ID_NOT_FOUND, data=d, address=address, severity=severity)
        self.key = key
        self.identifier = identifier
    def write(self, outstream, prefix):
        outstream.write('{p}An ID Reference did not match a previous ID ("{k}": "{v}")'.format(p=prefix, k=self.key, v=self.identifier))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.warning_data

class MultipleRootNodesWarning(WarningMessage):
    def __init__(self, nd_id, address, severity=SeverityCodes.ERROR):
        WarningMessage.__init__(self, WarningCodes.MULTIPLE_ROOT_NODES, data=nd_id, address=address, severity=severity)
        self.nd_id = nd_id
    def write(self, outstream, prefix):
        outstream.write('{p}Multiple nodes in a tree were flagged as being the root node ("{k}" was not the first)'.format(p=prefix, k=self.nd_id))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.warning_data

class MissingMandatoryKeyWarning(WarningMessage):
    def __init__(self, key, address, severity=SeverityCodes.WARNING):
        WarningMessage.__init__(self, WarningCodes.MISSING_MANDATORY_KEY, data=key, address=address, severity=severity)
        self.key = key
    def write(self, outstream, prefix):
        outstream.write('{p}Missing required key "{k}"'.format(p=prefix, k=self.key))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.key

class UnrecognizedTagWarning(WarningMessage):
    def __init__(self, tag, address, severity=SeverityCodes.WARNING):
        WarningMessage.__init__(self, WarningCodes.UNRECOGNIZED_TAG, data=tag, address=address, severity=severity)
        self.tag = tag
    def write(self, outstream, prefix):
        outstream.write(u'{p}Unrecognized value for a tag: "{s}"'.format(p=prefix, s=self.tag))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.tag

class NoRootNodeWarning(WarningMessage):
    def __init__(self, address, severity=SeverityCodes.ERROR):
        WarningMessage.__init__(self, WarningCodes.NO_ROOT_NODE, data=None, address=address, severity=severity)
    def write(self, outstream, prefix):
        outstream.write('{p}No node in a tree was flagged as being the root node'.format(p=prefix))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None

class MultipleTreesWarning(WarningMessage):
    def __init__(self, trees_list, address, severity=SeverityCodes.WARNING):
        WarningMessage.__init__(self, WarningCodes.MULTIPLE_TREES, data=trees_list, address=address, severity=severity)
        self.trees_list = trees_list
    def write(self, outstream, prefix):
        outstream.write('{p}Multiple trees were found without an indication of which tree is preferred'.format(p=prefix))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None

class NoTreesWarning(WarningMessage):
    def __init__(self, address, severity=SeverityCodes.WARNING):
        WarningMessage.__init__(self, WarningCodes.NO_TREES, data=None, address=address, severity=severity)
    def write(self, outstream, prefix):
        outstream.write('{p}No trees were found, or all trees were flagged for deletion'.format(p=prefix))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None

class TipWithoutOTUWarning(WarningMessage):
    def __init__(self, tip_node, address, severity=SeverityCodes.ERROR):
        WarningMessage.__init__(self, WarningCodes.TIP_WITHOUT_OTU, data=None, address=address, severity=severity)
        self.tip_node = tip_node
    def write(self, outstream, prefix):
        outstream.write('{p}Tip node ("{n}") without a valid @otu value'.format(p=prefix, n=self.tip_node.nexson_id))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None

class PropertyValueNotUsefulWarning(WarningMessage):
    def __init__(self, value, address, severity=SeverityCodes.WARNING):
        d = {'key': address.property_name, 'value': value}
        WarningMessage.__init__(self, WarningCodes.PROPERTY_VALUE_NOT_USEFUL, data=d, address=address, severity=severity)
        self.key = address.property_name
        self.value = value
    def write(self, outstream, prefix):
        outstream.write('{p}Unhelpful or deprecated value "{v}" for property "{k}"'.format(p=prefix, k=self.key, v=self.value))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.warning_data

class UnrecognizedPropertyValueWarning(WarningMessage):
    def __init__(self, value, address, severity=SeverityCodes.WARNING):
        d = {'key': address.property_name, 'value': value}
        WarningMessage.__init__(self, WarningCodes.UNRECOGNIZED_PROPERTY_VALUE, data=d, address=address, severity=severity)
        self.key = address.property_name
        self.value = value
    def write(self, outstream, prefix):
        outstream.write('{p}Unrecognized value "{v}" for property "{k}"'.format(p=prefix, k=self.key, v=self.value))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.warning_data

class InvalidPropertyValueWarning(WarningMessage):
    def __init__(self, value, address, severity=SeverityCodes.ERROR):
        d = {'key': address.property_name, 'value': value}
        WarningMessage.__init__(self, WarningCodes.INVALID_PROPERTY_VALUE, data=d, address=address, severity=severity)
        self.key = address.property_name
        self.value = value
    def write(self, outstream, prefix):
        outstream.write('{p}Invalid value "{v}" for property "{k}"'.format(p=prefix, k=self.key, v=self.value))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.warning_data

class UnvalidatedAnnotationWarning(WarningMessage):
    def __init__(self, value, address, severity=SeverityCodes.WARNING):
        d = {'key': address.property_name, 'value': value}
        WarningMessage.__init__(self, WarningCodes.UNVALIDATED_ANNOTATION, data=d, address=address, severity=severity)
        self.key = address.property_name
        self.value = value
    def write(self, outstream, prefix):
        outstream.write(u'{p}Annotation found, but not validated: "{k}" -> "{v}"'.format(p=prefix, k=self.key, v=self.value))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.warning_data

class ConflictingPropertyValuesWarning(WarningMessage):
    def __init__(self, key_value_list, address, severity=SeverityCodes.ERROR):
        WarningMessage.__init__(self, WarningCodes.CONFLICTING_PROPERTY_VALUES, data=key_value_list, address=address, severity=severity)
        self.key_value_list = key_value_list
    def write(self, outstream, prefix):
        s = u", ".join([u'"{k}"="{v}"'.format(k=i[0], v=i[1]) for i in self.key_value_list])
        outstream.write('{p}Conflicting values for properties: {s}'.format(p=prefix, s=s))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.warning_data

class MultipleTipsMappedToOTTIDWarning(WarningMessage):
    def __init__(self, ott_id, node_list, address, severity=SeverityCodes.WARNING):
        data = {'ott_id':ott_id, 'node_list': node_list}
        WarningMessage.__init__(self, WarningCodes.MULTIPLE_TIPS_MAPPED_TO_OTT_ID, data=data, address=address, severity=severity)
        self.ott_id = ott_id
        self.node_list = node_list
        self.id_list = [i.nexson_id for i in self.node_list]
        self.id_list.sort()
    def write(self, outstream, prefix):
        s = u', '.join([u'"{i}"'.format(i=i) for i in self.id_list])
        outstream.write('{p}Multiple nodes ({s}) are mapped to the OTT ID "{o}"'.format(p=prefix, 
                                                                                        s=s,
                                                                                        o=self.ott_id))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return {'nodes': self.id_list}

class NonMonophyleticTipsMappedToOTTIDWarning(WarningMessage):
    def __init__(self, ott_id, clade_list, address, severity=SeverityCodes.WARNING):
        data = {'ott_id':ott_id, 'node_list': clade_list}
        WarningMessage.__init__(self, WarningCodes.NON_MONOPHYLETIC_TIPS_MAPPED_TO_OTT_ID, data=data, address=address, severity=severity)
        self.ott_id = ott_id
        self.clade_list = clade_list
        sl = [(i[0].nexson_id, i) for i in clade_list]
        sl.sort()
        id_list = []
        for el in sl:
            id_list.append([i.nexson_id for i in el[1]])
        self.id_list = id_list
    def write(self, outstream, prefix):
        str_list = []
        for sub_list in self.id_list:
            s = '", "'.join([str(i) for i in sub_list])
            str_list.append('"{s}"'.format(s=s))
        s = ' +++ '.join([i for i in str_list])
        outstream.write('{p}Multiple nodes that do not form the tips of a clade are mapped to the OTT ID "{o}". The clades are {s}'.format(p=prefix,
                                                                            s=s,
                                                                            o=self.ott_id,
                                                                            ))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return {'nodes': self.id_list}

class TipsWithoutOTTIDWarning(WarningMessage):
    def __init__(self, tip, address, severity=SeverityCodes.WARNING):
        WarningMessage.__init__(self, WarningCodes.TIP_WITHOUT_OTT_ID, data=tip, address=address, severity=severity)
        self.tip = tip
    def write(self, outstream, prefix):
        outstream.write('{p}Tip node mapped to an OTU ("{o}") which does not have an OTT ID'.format(p=prefix, 
                                                        n=self.tip.nexson_id,
                                                        o=self.tip._otu.nexson_id))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None

class MultipleEdgesPerNodeWarning(WarningMessage):
    def __init__(self, node, edge, address, severity=SeverityCodes.ERROR):
        data = {'node': node, 'edge': edge}
        WarningMessage.__init__(self, WarningCodes.MULTIPLE_EDGES_FOR_NODES, data=data, address=address, severity=severity)
        self.node = node
        self.edge = edge
    def write(self, outstream, prefix):
        outstream.write('{p}A node ("{n}") has multiple edges to parents ("{f}" and "{s}")'.format(p=prefix,
                                                                                n=self.node.nexson_id,
                                                                                f=self.node._edge.nexson_id,
                                                                                s=self.edge.nexson_id))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None

class IncorrectRootNodeLabelWarning(WarningMessage):
    def __init__(self, tagged_node, node_without_parent, address, severity=SeverityCodes.ERROR):
        data = {'tagged': tagged_node, 'node_without_parent': node_without_parent}
        WarningMessage.__init__(self, WarningCodes.INCORRECT_ROOT_NODE_LABEL, data=data, address=address, severity=severity)
        self.tagged_node = tagged_node
        self.node_without_parent = node_without_parent
    def write(self, outstream, prefix):
        outstream.write('{p}The node flagged as the root ("{t}") is not the node without a parent ("{r}")'.format(p=prefix,
                                                                            t=self.tagged_node.nexson_id,
                                                                            r=self.node_without_parent.nexson_id))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None

class UnnecessaryAttributeWarning(WarningMessage):
    def __init__(self, att, address, severity=SeverityCodes.ERROR):
        data = {'attribute': att}
        WarningMessage.__init__(self, WarningCodes.UNNECESSARY_ATTRIBUTE, data=data, address=address, severity=severity)
        self.att = att
    def write(self, outstream, prefix):
        outstream.write('{p}Unnecessary attribute "{a}"'.format(p=prefix, a=self.att))
        self._write_message_suffix(outstream)
class UnexpectedMetaDatatypeWarning(WarningMessage):
    def __init__(self, t, address, severity=SeverityCodes.ERROR):
        data = {'stated_type': t}
        WarningMessage.__init__(self, WarningCodes.UNEXPECTED_META_DATATYPE, data=data, address=address, severity=severity)
        self.stated_type = t
    def write(self, outstream, prefix):
        outstream.write('{p}Unnecessary (redundant) indication of the type of data ({t}) found in meta'.format(p=prefix, t=self.stated_type))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None
class IncorrectMetaDatatypeSpecifiedWarning(WarningMessage):
    def __init__(self, t, address, severity=SeverityCodes.ERROR):
        data = {'stated_type': t}
        WarningMessage.__init__(self, WarningCodes.INCORRECT_META_DATATYPE_SPECIFIED, data=data, address=address, severity=severity)
        self.stated_type = t
    def write(self, outstream, prefix):
        outstream.write('{p}Unexpected datatype specified ({t}) for meta'.format(p=prefix, t=self.stated_type))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None
class IncorrectMetaDatatypeFoundWarning(WarningMessage):
    def __init__(self, found, expected, address, severity=SeverityCodes.ERROR):
        data = {'type_found': found, 'type_expected': expected}
        WarningMessage.__init__(self, WarningCodes.INCORRECT_META_DATATYPE_FOUND, data=data, address=address, severity=severity)
        self.found = found
        self.expected = expected
    def write(self, outstream, prefix):
        outstream.write('{p}Unexpected type of data ({f}) found in meta. Expeceted {e}'.format(p=prefix, f=self.found, e=self.expected))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None
class MetaDatatypeCoercionWarning(WarningMessage):
    def __init__(self, value, expected_type, address, severity=SeverityCodes.ERROR):
        data = {'value':value, 'expected_type': expected_type}
        WarningMessage.__init__(self, WarningCodes.METADATA_TYPE_COERCION, data=data, address=address, severity=severity)
        self.expected = expected_type
    def write(self, outstream, prefix):
        outstream.write('{p}Metadata value was coerced to type {t}'.format(p=prefix, t=self.expected))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None
class IncompatibleMetaDatatypeFoundWarning(WarningMessage):
    def __init__(self, found, expected, address, severity=SeverityCodes.ERROR):
        data = {'type_found': found, 'type_expected': expected}
        WarningMessage.__init__(self, WarningCodes.INCOMPATIBLE_META_DATATYPE_FOUND, data=data, address=address, severity=severity)
        self.found = found
        self.expected = expected
    def write(self, outstream, prefix):
        outstream.write('{p}Incompatible type of data ({f}) found in meta. Expeceted {e}'.format(p=prefix, f=self.found, e=self.expected))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None


class TreeCycleWarning(WarningMessage):
    def __init__(self, node, address, severity=SeverityCodes.ERROR):
        WarningMessage.__init__(self, WarningCodes.CYCLE_DETECTED, data=node, address=address, severity=severity)
        self.node = node
    def write(self, outstream, prefix):
        outstream.write('{p}Cycle in a tree detected passing througn node "{n}"'.format(p=prefix, n=self.node.nexson_id))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return self.node.nexson_id

class DisconnectedTreeWarning(WarningMessage):
    def __init__(self, root_node_list, address, severity=SeverityCodes.ERROR):
        WarningMessage.__init__(self, WarningCodes.DISCONNECTED_GRAPH_DETECTED, data=root_node_list, address=address, severity=severity)
        self.root_node_list = root_node_list
    def write(self, outstream, prefix):
        outstream.write('{p}Disconnected graph found instead of tree including root nodes:'.format(p=prefix))
        for index, el in enumerate(self.root_node_list):
            if index ==0:
                outstream.write('"{i}"'.format(i=el.nexson_id))
            else:
                outstream.write(', "{i}"'.format(i=el.nexson_id))
        self._write_message_suffix(outstream)
    def convert_data_for_json(self):
        return None

################################################################################
# Warning/error logger types...
################################################################################
class DefaultRichLogger(object):
    '''This is misnamed - it logs the error and warning, but also has some
    configuration variables for validation. It is a scratchspace for notes and 
    configuration of the validation action (passed in to every function involved
    in the creation of a NexSON object)
    
    Config properties:
        retain_deprecated (default = False) if True tells the validator to leave
            old properties alone.
        warn_about_fixed (default False) if True, warnings are issued even for
            aspcets of the NexSON blob that have been fixed by the validator.
        retain_type_hints (default False) if True the meta @datatype and @xsd:type will be retained.
        coerce_meta (default True) if True, then coercion of the value of a meta element will be 
            attempted if the element does not have the appropriate type.
    '''
    def __init__(self, store_messages=False):
        self.out = sys.stderr
        self.store_messages_as_obj = store_messages
        self.warnings = []
        self.errors = []
        self.prefix = ''
        self.retain_deprecated = False
        self.warn_about_fixed = False
        self.retain_type_hints = False
        self.coerce_meta = True 
        self.id2obj = {}
        self.annotation_event_ids_to_store = []
        self.flagged_messages = {} # id to (message obj., parent of meta)
    def warn(self, warning_code, data, address):
        m = WarningMessage(warning_code, data, address, severity=SeverityCodes.WARNING)
        self.warning(m)
    def warning(self, m):
        if self.store_messages_as_obj:
            self.warnings.append(m)
        else:
            m.write(self.out, self.prefix)
    def error(self, warning_code, address, subelement=''):
        m = WarningMessage(warning_code, data, address)
        self.emit_error(m)
    def emit_error(self, m):
        m.severity = SeverityCodes.ERROR
        if self.store_messages_as_obj:
            self.errors.append(m)
        else:
            raise NexSONError(m.getvalue(self.prefix))

class ValidationLogger(DefaultRichLogger):
    def __init__(self, store_messages=False):
        DefaultRichLogger.__init__(self, store_messages=store_messages)
    def warning(self, m):
        if not self.store_messages_as_obj:
            m = m.getvalue(self.prefix)
        self.warnings.append(m)
    def emit_error(self, m):
        m.severity = SeverityCodes.ERROR
        if not self.store_messages_as_obj:
            m = m.getvalue(self.prefix)
        self.errors.append(m)

class FilteringLogger(ValidationLogger):
    def __init__(self, codes_to_register=None, codes_to_skip=None, store_messages=False):
        ValidationLogger.__init__(self, store_messages=store_messages)
        self.codes_to_skip = set()
        if codes_to_register:
            self.registered = set(codes_to_register)
            if codes_to_skip:
                for el in codes_to_skip:
                    self.codes_to_skip.add(el)
                    assert el not in self.registered
        else:
            assert codes_to_skip
            self.registered = set(WarningCodes.numeric_codes_registered)
            for el in codes_to_skip:
                self.codes_to_skip.add(el)
                self.registered.remove(el)

    def warning(self, m):
        if m.warning_code in self.codes_to_skip:
            return
        if m.warning_code in self.registered:
            ValidationLogger.warning(self, m)
    def emit_error(self, m):
        m.severity = SeverityCodes.ERROR
        if m.warning_code in self.codes_to_skip:
            return
        if m.warning_code in self.registered:
            ValidationLogger.emit_error(self, m)

def check_key_presence(d, container, rich_logger):
    '''Issues errors if `d` does not contain keys in the container.PERMISSIBLE_KEYS iterable,
    warnings if `d` lacks keys listed in container.EXPECETED_KEYS, or if `d` contains
    keys not listed in container.PERMISSIBLE_KEYS.
    container.get_tag_context() is used to tag any warning/errors
    '''
    for k in d.keys():
        if k not in container.PERMISSIBLE_KEYS:
            rich_logger.warning(UnrecognizedKeyWarning(k, address=container.address))
    for k in container.EXPECETED_KEYS:
        if k not in d:
            rich_logger.warning(MissingOptionalKeyWarning(k, address=container.address))
    for k in container.REQUIRED_KEYS:
        if k not in d:
            rich_logger.emit_error(MissingMandatoryKeyWarning(k, address=container.address))


################################################################################
# Wrappers around the entities that we care about in a NexSON file. The
#   first argument in the constructor of each is the dict (presumably
#   directly from a json load operation) that represents the object.
#   each class simply provides the validation logic for elements of the
#   corresponding type.
################################################################################


class NexsonDictWrapper(object):
    '''Base class adding the nexson_id property'''
    REQUIRED_KEYS = tuple()
    EXPECETED_KEYS = tuple()
    PERMISSIBLE_KEYS = tuple()
    TAG_CONTEXT = ''
    def __init__(self, o, rich_logger=None, container=None):
        self._raw = o
        self._container = container
        if rich_logger is None:
            self._logger = DefaultRichLogger()
        else:
            self._logger = rich_logger
    def setdefault(self, k, v):
        try:
            return getattr(self, k)
        except:
            setattr(self, k, v)
            return v
    def get_path_dict(self, subelement, property_name):
        assert False
    def get_nexson_id(self):
        return self._raw.get('@id')
    nexson_id = property(get_nexson_id)
    def get_address(self):
        if not hasattr(self, '_address'):
            self._address = NexsonAddress(container=self)
        return self._address
    address = property(get_address)
    def get_address_of_meta(self):
        if not hasattr(self, '_address_of_meta'):
            self._address_of_meta = NexsonAddress(container=self, subelement='meta')
        return self._address_of_meta
    address_of_meta = property(get_address_of_meta)
    def address_of_meta_key(self, key):
        return NexsonAddress(container=self, subelement='meta', property_name=key)
    
    def get_tag_context(self):
        return '{f}(id={i})'.format(f=self.TAG_CONTEXT, i=self.nexson_id)

    def _consume_meta(self, o, rich_logger=None, expected_keys=None):
        '''Looks for a `meta` key to list in `o` (warns if not a list, but does not warn if absent)
        Converts each meta object to a Meta instance.
        adds 3 attributes to "self"
            _meta_list  - list of all Meta objects (in input order)
            _meta2value - dict mapping property_name  to value or property_name to MetaValueList of MetaValueList
            _meta2list  - dict mapping property_name to list of Meta items
             
        '''
        ml, mv, mld = _read_meta_list(o, self, self._logger)
        assert(not getattr(self, '_meta_list', None))
        assert(not getattr(self, '_meta2value', None))
        assert(not getattr(self, '_meta2list', None))
        self._meta_list = ml
        self._meta2value = mv
        self._meta2list = mld
        if (expected_keys is not None) and (rich_logger is not None):
            for k, v in mv.iteritems():
                if k not in expected_keys:
                    rich_logger.warning(UnvalidatedAnnotationWarning(v, self.address_of_meta_key(k)))
        if rich_logger is not None and rich_logger.id2obj is not None:
            id2obj = rich_logger.id2obj
            annotation_events = mv.get('ot:annotationEvents')
            if annotation_events:
                try:
                    for e in annotation_events['annotation']:
                        try:
                            _add_value_to_dict_bf(id2obj, e['@id'], e)
                        except:
                            pass
                except:
                    pass
            agents = mv.get('ot:agents')
            if agents:
                try:
                    for e in agents['agent']:
                        try:
                            _add_value_to_dict_bf(id2obj, e['@id'], e)
                        except:
                            pass
                except:
                    pass
            messages = mv.get('ot:messages')
            if messages:
                try:
                    for e in messages['message']:
                        try:
                            _add_value_to_dict_bf(id2obj, e['@id'], e)
                        except:
                            pass
                        if rich_logger.annotation_event_ids_to_store \
                          and e.get('@wasGeneratedById') in rich_logger.annotation_event_ids_to_store:
                            try:
                                _add_value_to_dict_bf(rich_logger.flagged_messages, e['@id'], (e, self))
                            except:
                                pass
                except:
                    pass

    def get_singelton_meta(self, property_name, default=None, warn_if_missing=True):
        v = self._meta2value.get(property_name)
        if v is None:
            if warn_if_missing:
                self._logger.warning(MissingOptionalKeyWarning(key=None, address=self.address_of_meta_key(property_name)))
            v = default
        elif isinstance(v, MetaValueList):
            self._logger.emit_error(DuplicatingSingletonKeyWarning(self.address_of_meta_key(property_name)))
        return v
    def add_meta(self, key, value):
        md = {"$": value, 
              "@property": key, 
              "@xsi:type": "nex:LiteralMeta"}
        if isinstance(value, bool):
            md["@datatype"] = "xsd:boolean"
        rm = self._raw.setdefault('meta', []).append(md)
    def del_meta(self, key):
        ml = self._raw.get('meta', [])
        to_del = []
        for ind, el in enumerate(ml):
            if el['@property'] == key:
                to_del.append(ind)
        to_del.reverse()
        for ind in to_del:
            ml.pop(ind)
    def replace_meta_property_name(self, old_name, new_name):
        meta_el_list = self._meta2list.get(old_name)
        if not bool(meta_el_list):
            return False
        for meta_el in meta_el_list:
            v = self._meta2value[old_name]
            if isinstance(v, MetaValueList):
                v.remove(meta_el.value)
            else:
                del self._meta2value[old_name]
            v = self._meta2list[old_name]
            v.remove(meta_el)
            if len(v) == 0:
                del self._meta2list[old_name]
            meta_el.property_name = new_name
            _add_meta_to_structs(meta_el, self._meta2value, self._meta2list)
            return True
    def get_list_meta(self, property_name, warn_if_missing=True):
        v = self._meta2value.get(property_name)
        if v is None:
            if warn_if_missing:
                self._logger.warning(MissingOptionalKeyWarning(key=None, address=self.address_of_meta_key(property_name)))
            v = []
        return v
    def consume_meta_and_check_keys(self, d, rich_logger):
        '''calls check_key_presence and _consume_meta
        '''
        check_key_presence(d, self, rich_logger)
        if rich_logger and (rich_logger.id2obj is not None) and '@id' in self.PERMISSIBLE_KEYS and '@id' in d:
            _add_value_to_dict_bf(rich_logger.id2obj, d['@id'], d)
        self._consume_meta(d, rich_logger, self.EXPECTED_META_KEYS)

class MetaValueList(list):
    '''Thin wrapper for a list created to distinguish:
        (1) a list of meta values with the same key for the 
            same NexSON object; from
        (2) a meta values that is a list (in the JSON)
    Simply used in isinstance calls
    '''
    pass

class Meta(NexsonDictWrapper):
    REQUIRED_KEYS = ('$', '@property', '@xsi.type')
    EXPECETED_KEYS = tuple()
    PERMISSIBLE_KEYS = REQUIRED_KEYS
    def __init__(self, o, rich_logger, container=None):
        #
        keep_deprecated = rich_logger and rich_logger.retain_type_hints
        p = o.get('@property')
        if ('@xsi:type' in o):
            warn_t = True
            if not keep_deprecated:
                # As per MTH email of Jan 27, 2014: purge the xsi:type be default
                del o['@xsi:type']
                if rich_logger and (not rich_logger.warn_about_fixed):
                    warn_t = False
            if warn_t:
                rich_logger.warning(UnnecessaryAttributeWarning('@xsi:type', address=container.address_of_meta_key(p)))
        # using presence of 'rel' attribute rather that xsi:type = nex:ResourceMeta
        self._data_in_href = ('@rel' in o) and ('@href' in o)
        expected_datatype = _OT_META_PROP_TO_DATATYPE.get(p, 'xsd:string')
        stated_datatype = o.get('@datatype')
        if stated_datatype:
            if stated_datatype == expected_datatype:
                warn_redundant = True
                if keep_deprecated:
                    del o['@datatype']
                    if rich_logger and (not rich_logger.warn_about_fixed):
                        warn_redundant = False
                if rich_logger and warn_redundant:
                    rich_logger.warning(UnnecessaryAttributeWarning('@datatype', address=container.address_of_meta_key(p)))
            elif rich_logger:
                rich_logger.warning(UnexpectedMetaDatatypeWarning(stated_datatype, address=container.address_of_meta_key(p)))
        NexsonDictWrapper.__init__(self, o, rich_logger, container)
        v = self.value
        if type(v) in _XSD_TYPE_TO_VALID_PYTHON_TYPES[expected_datatype]:
            if stated_datatype != expected_datatype and rich_logger:
                rich_logger.warning(IncorrectMetaDatatypeSpecifiedWarning(stated_datatype, address=container.address_of_meta_key(p)))
        else:
            if (rich_logger is None) or (not rich_logger.coerce_meta) or self._data_in_href:
                rich_logger.error(IncorrectMetaDatatypeFoundWarning(type(v), expected_datatype, address=container.address_of_meta_key(p)))
            else:
                try:
                    c = _XSD_TYPE_COERCION[expected_datatype](v)
                    self._raw['$'] = c
                    if rich_logger and rich_logger.warn_about_fixed:
                        rich_logger.warning(MetaDatatypeCoercionWarning(v, expected_datatype, address=container.address_of_meta_key(p)))
                except:
                    if rich_logger:
                        rich_logger.error(IncompatibleMetaDatatypeFoundWarning(type(v), expected_datatype, address=container.address_of_meta_key(p)))
    def get_property_name(self):
        return self._raw.get('@property')
    def set_property_name(self, v):
        self._raw['@property'] = v
    property_name = property(get_property_name, set_property_name)
    def get_property_value(self):
        if self._data_in_href:
            return self._raw.get('@href') # does not deal with nested meta
        return self._raw.get('$')
    value = property(get_property_value)

OTUMeta = Meta

def _add_meta_to_structs(meta_el, to_meta_value, to_meta_list):
    mk = meta_el.property_name
    v = meta_el.value
    cv = to_meta_value.setdefault(mk, v)
    if cv is not v:
        if not isinstance(cv, MetaValueList):
            to_meta_value[mk] = MetaValueList([cv, v])
        else:
            to_meta_value[mk].append(v)
    to_meta_list.setdefault(mk, []).append(meta_el)

def _read_meta_list(o, container, rich_logger):
    '''Looks for a `meta` key to list in `o` (warns if not a list, but does not warn if absent)
    Converts each meta object to a Meta instance.
    returns a tuple of 3 elements:
        list of all Meta objects (in input order)
        dict mapping property_name  to value or property_name to MetaValueList of MetaValueList
        dict mapping property_name to list of Meta items
         
    '''
    meta_list = []
    to_meta_value = {}
    to_meta_list = {}
    m = o.get('meta', [])
    if isinstance(m, dict):
        m = [m]
    if not isinstance(m, list):
        rich_logger.emit_error(MissingExpectedListWarning(m, address=container.address_of_meta))
    else:
        for el in m:
            meta_el = Meta(el, rich_logger, container=container)
            meta_list.append(meta_el)
            _add_meta_to_structs(meta_el, to_meta_value, to_meta_list)
    return (meta_list, to_meta_value, to_meta_list)

class OTU(NexsonDictWrapper):
    REQUIRED_KEYS = ('@id',)
    EXPECETED_KEYS = ('@id',)
    PERMISSIBLE_KEYS = ('@id', '@about', '@label', 'meta')
    EXPECTED_META_KEYS = ('ot:ottid', 'ot:ottolid','ot:originalLabel')
    TAG_CONTEXT = 'otu'

    def __init__(self, o, rich_logger, container=None):
        NexsonDictWrapper.__init__(self, o, rich_logger, container)
        self.consume_meta_and_check_keys(o, rich_logger)
        self._ott_id = self.get_singelton_meta('ot:ottid', warn_if_missing=False)
        if self._ott_id is None:
            self._ott_id = self.get_singelton_meta('ot:ottolid', warn_if_missing=False)
            if self._ott_id is not None:
                if (rich_logger is None or (not rich_logger.retain_deprecated)):
                    self.replace_meta_property_name('ot:ottolid', 'ot:ottid')
                else:
                    rich_logger.warning(DeprecatedMetaPropertyWarning(address=self.address))
        if self._ott_id is None:
            self.get_singelton_meta('ot:ottid') # trigger a warning
        self._original_label = self.get_singelton_meta('ot:originalLabel')
        self._label = o.get('@label', None)
    def get_path_dict(self, subelement, property_name):
        d = {
            'top': 'otus',
            'otusID': self._container.nexson_id,
            'otuID': self.nexson_id,
            'inMeta': False,
        }
        if subelement:
            assert subelement == 'meta'
            d['inMeta'] = True
        if property_name:
            d['property'] = property_name
        return d
    def get_ott_id(self):
        return self._ott_id
    ott_id = property(get_ott_id)
    def get_original_label(self):
        return self._original_label
    original_label = property(get_original_label)
    def get_current_label(self):
        return self._label
    current_label = property(get_current_label)

class Edge(NexsonDictWrapper):
    REQUIRED_KEYS = ('@id', '@source', '@target')
    EXPECETED_KEYS = tuple()
    PERMISSIBLE_KEYS = tuple(['@length'] + list(REQUIRED_KEYS) + ['@about']) 
    EXPECTED_META_KEYS = tuple()
    TAG_CONTEXT = 'edge'
    def __init__(self, o, rich_logger, nodes, container=None):
        NexsonDictWrapper.__init__(self, o, rich_logger, container)
        self.consume_meta_and_check_keys(o, rich_logger)
        self._source = None
        self._target = None
        sid = o.get('@source')
        if sid is not None:
            self._source = nodes.get(sid)
            if self._source is None:
                rich_logger.emit_error(ReferencedIDNotFoundWarning('@source', sid, address=self.address))
            else:
                self._source._children.append(self)
        tid = o.get('@target')
        if tid is not None:
            self._target = nodes.get(tid)
            if self._target is None:
                rich_logger.emit_error(ReferencedIDNotFoundWarning('@target', tid, address=self.address))
            elif self._target._edge is not None:
                rich_logger.emit_error(MultipleEdgesPerNodeWarning(self._target, self, address=self.address))
            else:
                self._target._edge = self
    def get_path_dict(self, subelement, property_name):
        d = {
            'top': 'trees',
            'treesID': self._container._container.nexson_id,
            'treeID': self._container.nexson_id,
            'edgeID': self.nexson_id,
            'inMeta': False,
        }
        if subelement:
            assert subelement == 'meta'
            d['inMeta'] = True
        if property_name:
            d['property'] = property_name
        return d


class Node(NexsonDictWrapper):
    REQUIRED_KEYS = ('@id',)
    EXPECETED_KEYS = tuple()
    PERMISSIBLE_KEYS = ('@id', '@otu', '@root', 'meta', '@about')
    EXPECTED_META_KEYS = tuple()
    TAG_CONTEXT = 'node'
    def get_path_dict(self, subelement, property_name):
        d = {
            'top': 'trees',
            'treesID': self._container._container.nexson_id,
            'treeID': self._container.nexson_id,
            'nodeID': self.nexson_id,
            'inMeta': False,
        }
        if subelement:
            assert subelement == 'meta'
            d['inMeta'] = True
        if property_name:
            d['property'] = property_name
        return d
    def __init__(self, o, rich_logger, otu_dict, container=None):
        NexsonDictWrapper.__init__(self, o, rich_logger, container)
        self.consume_meta_and_check_keys(o, rich_logger)
        self._is_root = o.get('@root', False)
        self._edge = None
        self._children = []
        self._otu = None
        v = o.get('@otu')
        if v is not None:
            self._otu = otu_dict.get(v)
            if self._otu is None:
                rich_logger.emit_error(ReferencedIDNotFoundWarning('@otu', v, address=self.address))
    def get_parent(self):
        e = self._edge
        if e is None:
            return None
        return e._source
    def get_clade_if_tips_contained(self, avoid_child, tips_set):
        '''Returns bool, list of nodes in the clade
        True, list of all nodes in the clade (if all tips are in tip_set)
        False, None
        '''
        #@TEMP should not use recursion, here...
        if len(self._children) == 0:
            if self in tips_set:
                return True, [self]
            return False, None
        r = []
        for el in self._children:
            if el._target != avoid_child:
                b, c = el._target.get_clade_if_tips_contained(None, tips_set)
                if b:
                    r.extend(c)
                else:
                    return False, None
        r.append(self)
        return True, r
    def construct_path_to_root(self, encountered_nodes):
        n = self
        p = []
        s = set()
        while n:
            if n in s:
                return n, p
            if n in encountered_nodes:
                return None, []
            p.append(n)
            s.add(n)
            encountered_nodes.add(n)
            if n._edge:
                n = n._edge._source
            else:
                break
        return None, p
    def get_newick_edge_info(self):
        if self._edge:
            el = str(self._edge._raw.get('@length',''))
            if el:
                return ':{e}'.format(e=el)
        return ''
    def get_original_label(self):
        try:
            return self._otu.original_label
        except:
            None
    def get_ott_id(self):
        try:
            return self._otu.ott_id
        except:
            None
    def get_current_label(self):
        try:
            return self._otu.current_label
        except:
            None

class LabelUsing:
    '''An enumeration of ways for labeling entities for export into a terser format (such as newick)
    currently defined for values used as tip labels.
    Used as an argument to get_newick:
        ORIGINAL_LABEL, OTT_ID, OTT_LABEL
    '''
    ORIGINAL_LABEL = 0
    OTT_ID = 1
    CURRENT_LABEL = 2
    NAMES = ('original', 'ottid', 'current')
    @staticmethod
    def get_node_label_fn(label_type):
        if label_type == LabelUsing.ORIGINAL_LABEL:
            return lambda nd : nd.get_original_label() or u''
        elif label_type == LabelUsing.OTT_ID:
            return lambda nd : unicode(nd.get_ott_id() or '')
        else:
            assert(label_type == LabelUsing.CURRENT_LABEL)
            return lambda nd : nd.get_current_label() or u''
    @staticmethod
    def encode(s):
        sl = s.lower()
        return LabelUsing.NAMES.index(sl)


_NEWICK_TOKEN_BREAKER = re.compile(r'[^a-zA-Z0-9]')
def escape_for_newick(s):
    if _NEWICK_TOKEN_BREAKER.search(s):
        qs = s.split("'")
        return "'{s}'".format(s="''".join(qs))
    return s

def write_newick(out, nd, label_using):
    n = nd
    avuncular_stack = []
    ancestor_stack = []
    moving_rootward = False

    label_fn = LabelUsing.get_node_label_fn(label_using)

    while True:
        if moving_rootward:
            s = n.get_newick_edge_info()
            label = escape_for_newick(label_fn(n))
            out.write('){l}{s}'.format(l=label, s=s))
            next_nd = None
        else:
            c = [i._target for i in n._children]
            if len(c) > 0:
                out.write('(')
                ancestor_stack.append(n)
                next_nd = c[0]
                sibs = c[1:]
                avuncular_stack.append(sibs)
            else:
                s = n.get_newick_edge_info()
                label = escape_for_newick(label_fn(n))
                out.write('{l}{s}'.format(l=label, s=s))
                next_nd = None
        moving_rootward = False
        if next_nd is None:
            if len(avuncular_stack) > 0:
                p = avuncular_stack[-1]
                if len(p) > 0:
                    out.write(',')
                    next_nd = p.pop(0)
                else:
                    avuncular_stack.pop()
                    next_nd = ancestor_stack.pop()
                    moving_rootward = True
            else:
                break
        n = next_nd

class Tree(NexsonDictWrapper):
    REQUIRED_KEYS = ('@id', 'edge', 'node')
    EXPECETED_KEYS = ('@id',)
    PERMISSIBLE_KEYS = ('@id', '@about', 'node', 'edge', 'meta')
    EXPECTED_META_KEYS = ('ot:inGroupClade', 'ot:branchLengthMode', 'ot:tag')
    DELETE_ME_TAGS = ('delete', 'del', 'delet', 'delete', 'delete me', 'do not use')
    USE_ME_TAGS = ('choose me',)
    EXPECTED_TAGS = tuple(list(DELETE_ME_TAGS) + list(USE_ME_TAGS))
    TAG_CONTEXT = 'tree'
    def get_path_dict(self, subelement, property_name):
        d = {
            'top': 'trees',
            'treesID': self._container.nexson_id,
            'treeID': self.nexson_id,
            'inMeta': False,
        }
        if subelement == 'meta':
            d['inMeta'] = True
        if property_name:
            d['property'] = property_name
        return d
    def __init__(self, o, rich_logger, container=None):
        NexsonDictWrapper.__init__(self, o, rich_logger, container)
        self.consume_meta_and_check_keys(o, rich_logger)
        self._ingroup= self.get_singelton_meta('ot:inGroupClade')
        k = 'ot:branchLengthMode'
        self._branch_len_mode = self.get_singelton_meta(k, warn_if_missing=False)
        if self._branch_len_mode is not None:
            if self._branch_len_mode not in ['ot:substitutionCount',
                                             'ot:changesCount',
                                             'ot:time',
                                             'ot:bootstrapValues',
                                             'ot:posteriorSupport']:
                if self._branch_len_mode in ['ot:other', 'ot:undefined']:
                    rich_logger.warning(PropertyValueNotUsefulWarning(self._branch_len_mode, address=self.address_of_meta_key(k)))
                else:
                    rich_logger.emit_error(UnrecognizedPropertyValueWarning(self._branch_len_mode, address=self.address_of_meta_key(k)))
        self._tag_list = self.get_list_meta('ot:tag', warn_if_missing=False)
        if isinstance(self._tag_list, str) or isinstance(self._tag_list, unicode):
            self._tag_list = [self._tag_list]
        unexpected_tags = [i for i in self._tag_list if i.lower() not in self.EXPECTED_TAGS]
        for tag in unexpected_tags:
            rich_logger.warning(UnrecognizedTagWarning(tag, address=self.address_of_meta_key('ot:tag')))
        self._tagged_for_deletion = False
        self._tagged_for_inclusion = False # is there a tag meaning "use this tree?"
        tl = [i.lower() for i in self._tag_list]
        del_tag, inc_tag = None, None
        for t in Tree.DELETE_ME_TAGS:
            if t in tl:
                self._tagged_for_deletion = True
                del_tag = self._tag_list[tl.index(t)]
        for t in Tree.USE_ME_TAGS:
            if t in tl:
                self._tagged_for_inclusion = True
                inc_tag = self._tag_list[tl.index(t)]
        if self._tagged_for_inclusion and self._tagged_for_deletion:
            rich_logger.warning(ConflictingPropertyValuesWarning([('ot:tag', del_tag), 
                                                                  ('ot:tag', inc_tag)],
                                                                 address=self.address_of_meta_key('ot:tag')))
        self._node_dict = {}
        self._node_list = []
        self._edge_dict = {}
        self._edge_list = []
        otu_collection = None
        if container is not None:
            otu_collection = container._otu_collection
        if otu_collection is None:
            otu_dict = {}
        else:
            otu_dict = otu_collection._as_dict
        v = o.get('node', [])
        self._root_node = None
        if not isinstance(v, list):
            rich_logger.emit_error(MissingExpectedListWarning(v, NexsonAddress(container=self, subelement='node')))
        else:
            for el in v:
                n_node = Node(el, rich_logger, otu_dict, container=self)
                nid = n_node.nexson_id
                if nid is not None:
                    if nid in self._node_dict:
                        rich_logger.emit_error(RepeatedIDWarning(nid, NexsonAddress(container=self, subelement='node')))
                    else:
                        self._node_dict[nid] = n_node
                self._node_list.append(n_node)
                if n_node._is_root:
                    if self._root_node is None:
                        self._root_node = n_node
                    else:
                        rich_logger.emit_error(MultipleRootNodesWarning(nid, NexsonAddress(container=self, subelement='node')))
        if self._root_node is None:
            rich_logger.warning(NoRootNodeWarning(address=self.address))
        v = o.get('edge', [])
        if not isinstance(v, list):
            rich_logger.emit_error(MissingExpectedListWarning(v, NexsonAddress(container=self, subelement='edge')))
        else:
            for el in v:
                n_edge = Edge(el, rich_logger, nodes=self._node_dict, container=self)
                eid = n_edge.nexson_id
                if eid is not None:
                    if eid in self._edge_dict:
                        rich_logger.emit_error(RepeatedIDWarning(eid, NexsonAddress(container=self, subelement='edge')))
                    else:
                        self._edge_dict[eid] = n_edge
                self._edge_list.append(n_edge)
        # check the tree structure...
        lowest_node_set = set()
        encountered_nodes = set()
        ott_id2node = {}
        multi_labelled_ott_id = set()
        valid_tree = True
        for nd in self._node_list:
            cycle_node, path_to_root = nd.construct_path_to_root(encountered_nodes)
            if cycle_node:
                valid_tree = False
                rich_logger.emit_error(TreeCycleWarning(cycle_node, address=self.address))
            if path_to_root:
                lowest_node_set.add(path_to_root[-1])
            is_flagged_as_leaf = nd.get_singelton_meta('ot:isLeaf', warn_if_missing=False)
            if len(nd._children) == 0:
                if nd._otu is None:
                    rich_logger.emit_error(TipWithoutOTUWarning(nd, address=nd.address))
                elif nd._otu._ott_id is None:
                    rich_logger.warning(TipsWithoutOTTIDWarning(nd, address=nd.address))
                else:
                    nl = ott_id2node.setdefault(nd._otu._ott_id, [])
                    if len(nl) == 1:
                        multi_labelled_ott_id.add(nd._otu._ott_id)
                    nl.append(nd)
                if not is_flagged_as_leaf:
                    add_warning = True
                    if not rich_logger.retain_deprecated:
                        nd.add_meta('ot:isLeaf', True)
                        if not rich_logger.warn_about_fixed:
                            add_warning = False
                    if add_warning:
                        rich_logger.warning(MissingOptionalKeyWarning(key=None, address=nd.address_of_meta_key('ot:isLeaf')))
                    
            elif is_flagged_as_leaf:
                add_warning = True
                if not rich_logger.retain_deprecated:
                    nd.del_meta('ot:isLeaf') # Non const. Fixing.
                    if not rich_logger.warn_about_fixed:
                        add_warning = False
                if add_warning:
                    rich_logger.emit_error(InvalidPropertyValueWarning(True, address=nd.address_of_meta_key('ot:isLeaf')))
        for ott_id in multi_labelled_ott_id:
            tip_list = ott_id2node.get(ott_id)
            rich_logger.warning(MultipleTipsMappedToOTTIDWarning(ott_id, tip_list, address=self.address))
        if len(lowest_node_set) > 1:
            valid_tree = False
            lowest_node_set = [(i.nexson_id, i) for i in lowest_node_set]
            lowest_node_set.sort()
            lowest_node_set = [i[1] for i in lowest_node_set]
            rich_logger.emit_error(DisconnectedTreeWarning(lowest_node_set, address=self.address))
        elif len(lowest_node_set) == 1:
            ln = list(lowest_node_set)[0]
            if self._root_node is not None and self._root_node is not ln:
                rich_logger.emit_error(IncorrectRootNodeLabelWarning(self._root_node, ln, address=self.address))
        if valid_tree:
            for ott_id in multi_labelled_ott_id:
                tip_list = ott_id2node.get(ott_id)
                clade_tips = self.break_by_clades(tip_list)
                if len(clade_tips) > 1:
                    rich_logger.warning(NonMonophyleticTipsMappedToOTTIDWarning(ott_id, clade_tips, address=self.address))
    def break_by_clades(self, tip_list):
        '''Takes a list of nodes. returns a list of lists. 
        Each sub list is a set of leaves in the tree that form the tips of a clade on the tree..
        '''
        c = list(tip_list)
        cs = set(c)
        if len(tip_list) < 2:
            return [c]
        clade_lists = []
        while len(c) > 0:
            n = c.pop(0)
            p = n.get_parent()
            assert p is not None
            next_el = [n]
            while p is not None:
                all_in_cs, des_nodes = p.get_clade_if_tips_contained(n, cs)
                if all_in_cs:
                    next_el.extend(des_nodes)
                    for d in des_nodes:
                        if d in cs:
                            c.remove(d)
                else:
                    break
                n = p
                p = p.get_parent()
            clade_lists.append(next_el)
        return clade_lists

    def get_newick(self, label_using=LabelUsing.ORIGINAL_LABEL):
        b = StringIO()
        ci = codecs.lookup('utf8')
        s = codecs.StreamReaderWriter(b, ci.streamreader, ci.streamwriter)
        write_newick(s, self._root_node, label_using)
        return s.getvalue()


class OTUCollection(NexsonDictWrapper):
    REQUIRED_KEYS = ('@id', 'otu')
    EXPECETED_KEYS = tuple()
    PERMISSIBLE_KEYS = ('@id', 'otu')
    EXPECTED_META_KEYS = tuple()
    TAG_CONTEXT = 'otus'
    def get_path_dict(self, subelement, property_name):
        d = {
            'top': 'otus',
            'otusID': self.nexson_id,
        }
        if subelement == 'meta':
            d['inMeta'] = True
        if property_name:
            d['property'] = property_name
        return d
    def __init__(self, o, rich_logger, container):
        NexsonDictWrapper.__init__(self, o, rich_logger, container)
        self._as_list = []
        self._as_dict = {}
        self.consume_meta_and_check_keys(o, rich_logger)
        v = o.get('otu', [])
        if not isinstance(v, list):
            rich_logger.emit_error(MissingExpectedListWarning(v, address=NexsonAddress(self, subelement='otu')))
        else:
            for el in v:
                n_otu = OTU(el, rich_logger, container=self)
                nid = n_otu.nexson_id
                if nid is not None:
                    if nid in self._as_dict:
                        rich_logger.emit_error(RepeatedIDWarning(nid, address=NexsonAddress(self, subelement='otu')))
                    else:
                        self._as_dict[nid] = n_otu
                self._as_list.append(n_otu)

class TreeCollection(NexsonDictWrapper):
    REQUIRED_KEYS = ('@id', 'tree', '@otus')
    EXPECETED_KEYS = tuple()
    PERMISSIBLE_KEYS = ('@id', 'tree', '@otus')
    EXPECTED_META_KEYS = tuple()
    TAG_CONTEXT = 'trees'
    def get_path_dict(self, subelement, property_name):
        d = {
            'top': 'trees',
            'treesID': self.nexson_id,
            'inMeta': False,
        }
        if subelement == 'meta':
            d['inMeta'] = True
        if property_name:
            d['property'] = property_name
        return d
    def __init__(self, o, rich_logger, container):
        NexsonDictWrapper.__init__(self, o, rich_logger, container)
        self._as_list = []
        self._as_dict = {}
        self.consume_meta_and_check_keys(o, rich_logger)
        self._otu_collection = None
        v = o.get('@otus')
        if v is not None:
            if container is None \
               or container.otus is None \
               or v != container.otus.nexson_id:
                rich_logger.emit_error(ReferencedIDNotFoundWarning('@otus', v, address=self.address))
            else:
                self._otu_collection = container.otus
        v = o.get('tree', [])
        if not isinstance(v, list):
            rich_logger.emit_error(MissingExpectedListWarning(v, address=NexsonAddress(self, subelement='tree')))
        else:
            for el in v:
                tree = Tree(el, rich_logger, container=self)
                tid = tree.nexson_id
                if tid is not None:
                    if tid in self._as_dict:
                        rich_logger.emit_error(RepeatedIDWarning(nid, address=NexsonAddress(self, subelement='tree')))
                    else:
                        self._as_dict[tid] = tree
                self._as_list.append(tree)

class NexSON(NexsonDictWrapper):
    REQUIRED_KEYS = ('@id',)
    EXPECETED_KEYS = ('@id', 'otus', 'trees', 'meta')
    PERMISSIBLE_KEYS = ('@id',
                     '@about',
                     '@generator',
                     '@nexmljson',
                     '@version',
                     '@xmlns',
                     'otus',
                     'trees',
                     'meta',
                     )
    EXPECTED_META_KEYS = ('ot:studyId', 
                          'ot:focalClade',
                          'ot:studyPublication',
                          'ot:studyYear',
                          'ot:curatorName', 
                          'ot:studyPublicationReference', 
                          'ot:dataDeposit',
                          'ot:tag')
    EXPECTED_TAGS = tuple()
    TAG_CONTEXT = 'nexml'
    def get_path_dict(self, subelement, property_name):
        if subelement == 'meta':
            d = {
                'top': 'meta',
                'inMeta': True,
            }
        else: 
            d = {'top': 'nexml',
                 'inMeta': False}
        if property_name:
            d['property'] = property_name
        d['nexsonID'] = self.nexson_id
        return d
    def __init__(self, o, rich_logger=None):
        '''Creates an object that validates `o` as a dictionary
        that represents a valid NexSON object.
        Warnings are errors will be passed to rich_logger (or 
        as new DefaultRichLogger if None is passed in)
        '''
        if rich_logger is None:
            rich_logger = DefaultRichLogger()
        self.otus = None
        self.trees = None
        NexsonDictWrapper.__init__(self, o, rich_logger, None)
        for k in o.keys():
            if k not in ['nexml']:
                rich_logger.warning(UnrecognizedKeyWarning(k, address=self.address))
        self._nexml = None
        if 'nexml' not in o:
            rich_logger.emit_error(MissingMandatoryKeyWarning('nexml', address=self.address))
            return ## EARLY EXIT!!
        self._nexml = o['nexml']
        NexsonDictWrapper.__init__(self, self._nexml, rich_logger, None)
        if rich_logger and (rich_logger.id2obj is not None) and '@id' in self._nexml:
            _add_value_to_dict_bf(rich_logger.id2obj, self._nexml['@id'], self)
        
        check_key_presence(self._nexml, self, rich_logger)
        self._consume_meta(self._nexml, rich_logger, self.EXPECTED_META_KEYS)
        self._study_id = self.get_singelton_meta('ot:studyId')
        self._focal_clade_id = self.get_singelton_meta('ot:focalClade')
        self._study_publication = self.get_singelton_meta('ot:studyPublication')
        self._study_year = self.get_singelton_meta('ot:studyYear')
        self._curator_name = self.get_singelton_meta('ot:curatorName')
        self._data_deposit = self.get_singelton_meta('ot:dataDeposit')
        self._study_publication_reference = self.get_singelton_meta('ot:studyPublicationReference')
        self._tags = self.get_list_meta('ot:tag', warn_if_missing=False)
        if isinstance(self._tags, str) or isinstance(self._tags, unicode):
            self._tags = [self._tags]
        unexpected_tags = [i for i in self._tags if i not in self.EXPECTED_TAGS]
        for tag in unexpected_tags:
            rich_logger.warning(UnrecognizedTagWarning(tag, address=self.address_of_meta_key('ot:tag')))
        v = self._nexml.get('otus')
        if v is None:
            rich_logger.emit_error(MissingMandatoryKeyWarning('otus', address=self.address))
        else:
            self.otus = OTUCollection(v, rich_logger, container=self)
        v = self._nexml.get('trees')
        if v is None:
            rich_logger.emit_error(MissingMandatoryKeyWarning('tree', address=self.address))
        else:
            self.trees = TreeCollection(v, rich_logger, container=self)
            possible_trees = [t for t in self.trees._as_list if t._tagged_for_inclusion or (not t._tagged_for_deletion)]
            if len(possible_trees) > 1:
                rich_logger.warning(MultipleTreesWarning(self.trees._as_list, address=self.trees.address))
            elif len(possible_trees) == 0:
                rich_logger.warning(NoTreesWarning(address=self.trees.address))


def indented_keys(out, o, indentation='', indent=2):
    next_indentation = indentation + (' '*indent)
    if isinstance(o, dict):
        key_list = o.keys()
        key_list.sort()
        #out.write('{i}{{\n'.format(i=indentation))
        for k in key_list:
            v = o[k]
            if isinstance(v, dict):
                out.write('{i}{k} :\n'.format(i=indentation, k=k))
                indented_keys(out, v, next_indentation, indent)
                out.write('{i}\n'.format(i=indentation))
            elif isinstance(v, list) or isinstance(v, tuple):
                out.write('{i}{k} :\n'.format(i=indentation, k=k))
                indented_keys(out, v, next_indentation, indent)
            else:
                if k == '@property':
                    out.write('{i}{k} : {v}\n'.format(i=indentation, k=k, v=v))
                else:
                    out.write('{i}{k}\n'.format(i=indentation, k=k))
        #out.write('{i}}}\n'.format(i=indentation))
    else:
        assert isinstance(o, list) or isinstance(o, tuple)
        has_sub_list = False
        sk = set()
        for el in o:
            if isinstance(el, list) or isinstance(el, tuple):
                has_sub_list = True
            else:
                sk.update(el.keys())
        key_list = list(sk)
        key_list.sort()
        out.write('{i}[\n'.format(i=indentation))
        if has_sub_list:
            for el in o:
                if isinstance(el, list) or isinstance(el, tuple):
                    indented_keys(out, el, next_indentation, indent)
        for k in key_list:
            out.write('{i}{k}\n'.format(i=next_indentation, k=k))
        out.write('{i}]\n'.format(i=indentation))
        

