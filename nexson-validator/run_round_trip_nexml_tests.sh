#!/bin/sh
total=0
passed=0
if ! test -z "${NEXML_SCHEMA}"
then
    if test -f "${NEXML_SCHEMA}"
    then
        for f in $(ls tests/nexml/*.xml)
        do
            total=$(expr $total + 1)
            if sh scripts/check_nexml_roundtrip.sh "$f" "${NEXML_SCHEMA}" -o
            then
                passed=$(expr $passed + 1)
            fi
        done
    else 
        echo "NeXML roundtrip tests skipped because ${NEXML_SCHEMA} does not exist"
    fi
else
    echo "NeXML roundtrip tests skipped because the NEXML_SCHEMA environmental variable is not set"
fi

if test $passed -eq $total
then
    echo "NeXML round-trip tests passed"
    exit 0
else
    echo "some NeXML round-trip tests failed"
    exit 1
fi 