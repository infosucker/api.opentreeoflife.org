#!/bin/sh
total=0
passed=0

total=$(expr $total + 1)
if sh run_single_file_tests.sh
then
    passed=$(expr $passed + 1)
fi


total=$(expr $total + 1)
if python test_nexson_validator.py
then
    passed=$(expr $passed + 1)
fi

if ! test -z "${NEXML_SCHEMA}"
then
    if test -f "${NEXML_SCHEMA}"
    then
        total=$(expr $total + 1)
        if ! sh run_round_trip_tests.sh
        then
            passed=$(expr $passed + 1)
        fi
    else 
        echo "NeXML roundtrip tests skipped because ${NEXML_SCHEMA} does not exist"
    fi
else
    echo "NeXML roundtrip tests skipped because the NEXML_SCHEMA environmental variable is not set"
fi

if test $passed -eq $total
then
    echo "tests passed"
    exit 0
else
    echo "some tests failed"
    exit 1
fi 