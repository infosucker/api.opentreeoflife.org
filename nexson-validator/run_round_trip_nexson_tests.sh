#!/bin/sh
total=0
passed=0
for f in $(ls tests/nexson/*.nexson)
do
    total=$(expr $total + 1)
    if sh scripts/check_nexson_roundtrip.sh "$f" "${NEXML_SCHEMA}" -o
    then
        passed=$(expr $passed + 1)
    fi
done

if test $passed -eq $total
then
    echo "round-trip NexSON tests passed"
    exit 0
else
    echo "some round-trip NexSON tests failed"
    exit 1
fi 
