#!/bin/sh
dir=$(dirname "$0")
inpnexson="${1}"
if ! test -f "${inpnexson}"
then
    echo "The first arg should be a NeXSON instance doc. ${inpnexson} does not exist"
    exit 1
fi
if which validate-nexml >/dev/null
then
    do_schema_validation="1"
else
    do_schema_validation="0"
    echo '"validate-nexml" was not found on the path. Validation against schema will be skipped.'
fi
if ! test "$2" = "-o"
then
    if test -f .1.xml -o -f .2.json
    then
        echo "file .1.xml or .2.json files in the way and the -o was not used as the 2nd arg"
        exit 1
    fi
fi
# 1. to NeXML
if ! python "$dir/nexson_nexml.py" "${inpnexson}" .1.xml
then
    echo "Conversion of \"${inpnexson}\" to JSON failed"
    exit 1
fi

# 2. validate NeXML
if test ${do_schema_validation} -eq "1"
then
    if ! validate-nexml .1.xml >/dev/null 2>&1
    then
        echo "XML written to .1.xml was not valid NeXML"
        if test $inpwasvalid -eq 1
        then
            exit 1
        fi
    fi
fi


# 3. Convert to back to JSON
if ! python "$dir/nexson_nexml.py" .1.xml .2.json
then
    echo "Conversion of .1.xml to JSON failed"
    exit 1
fi

python -c "import json, codecs, sys; o=codecs.open(sys.argv[2], 'w', encoding='utf-8'); json.dump(json.load(codecs.open(sys.argv[1], 'rU', encoding='utf-8')), o, indent=0, sort_keys=True); o.write('\n')" "${inpnexson}" .1.json
# 4. Verify that the input is valid NeXML
if ! diff .2.json .1.json
then
    echo "Did not roundtrip"
    exit 1
fi

if test "$2" = "-o"
then
    rm .1.xml .2.json 2>/dev/null
fi

