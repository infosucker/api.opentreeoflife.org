#!/bin/sh
total=2
passed=0
if sh run_round_trip_nexson_tests.sh
then
    passed=$(expr $passed + 1)
else
    echo "NexSON -> NeXML -> NexSON tests failed"
fi

if sh run_round_trip_nexml_tests.sh
then
    passed=$(expr $passed + 1)
else
    echo "NeXML -> NexSON -> NeXML tests failed"
fi

if test $passed -eq $total
then
    echo "round-trip tests passed"
    exit 0
else
    echo "some round-trip tests failed"
    exit 1
fi 