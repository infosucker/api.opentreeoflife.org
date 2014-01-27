#!/bin/sh
dir=$(dirname "$0")
inpnexson="${1}"
if ! test -f "${inpnexson}"
then
    echo "The first arg should be a NeXSON instance doc. ${inpnexson} does not exist"
    exit 1
fi
nexmlschemafp="${2}"
if ! test -f "${nexmlschemafp}"
then
    echo "Second arg should be the nexml schema. ${nexmlschemafp} does not exist"
    exit 1
fi

if ! test $3 = "-o"
then
    if test -f .1.xml -o -f .2.json
    then
        echo "file .1.xml or .2.json files in the way and the -o was not used as the 3rd arg"
        exit 1
    fi
fi
set -x
# 1. to NeXML
if ! python "$dir/xml2json-badgerfish.py" jn "${inpnexson}" > .1.xml
then
    echo "Conversion of ${inpnexson} to NeXML failed"
    exit 1
fi


# 2. validate NeXML
if ! xmllint --schema "${nexmlschemafp}" .1.xml
then
    echo "XML written to .1.xml was not valid NeXML"
    if false
    then
        exit 1
    fi
fi


# 3. Convert to JSON
if ! python "$dir/xml2json-badgerfish.py" nj .1.xml > .2.json
then
    echo "Conversion of .1.xml to JSON failed"
    exit 1
fi


# 4. Verify that the input is valid NeXML
if ! diff .2.json "${inpnexson}" 
then
    echo "Did not roundtrip"
    exit 1
fi

if test $3 = "-o"
then
    rm .1.xml .2.json 2>/dev/null
fi