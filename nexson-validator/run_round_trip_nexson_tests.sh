#!/bin/sh
total=0
passed=0
if ! test -z "${NEXML_SCHEMA}"
then
    if test -f "${NEXML_SCHEMA}"
    then
        for f in $(ls tests/nexson/*.nexson)
        do
            total=$(expr $total + 1)
            if sh scripts/check_nexson_roundtrip.sh "$f" "${NEXML_SCHEMA}" -o
            then
                passed=$(expr $passed + 1)
            fi
        done
    else 
        echo "NexSON roundtrip tests skipped because ${NEXML_SCHEMA} does not exist"
    fi
else
    echo "NexSON roundtrip tests skipped because the NEXML_SCHEMA environmental variable is not set"
fi

if test $passed -eq $total
then
    echo "round-trip NexSON tests passed"
    exit 0
else
    echo "some round-trip NexSON tests failed"
    exit 1
fi 