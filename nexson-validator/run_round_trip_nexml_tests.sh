#!/bin/sh
total=0
passed=0
for f in $(ls tests/nexml/*.xml)
do
   total=$(expr $total + 1)
   if sh scripts/check_nexml_roundtrip.sh "$f" -o
   then
        passed=$(expr $passed + 1)
   fi
done

if test $passed -eq $total
then
    echo "NeXML round-trip tests passed"
    exit 0
else
    echo "some NeXML round-trip tests failed"
    exit 1
fi 
