#!/bin/sh
dir=$(dirname "$0")
inpnexml="${1}"
if ! test -f "${inpnexml}"
then
    echo "The first arg should be a nexml instance doc. ${inpnexml} does not exist"
    exit 1
fi
nexmlschemafp="${2}"
if ! test -f "${nexmlschemafp}"
then
    echo "Second arg should be the nexml schema. ${nexmlschemafp} does not exist"
    exit 1
fi


if test $3 = "-o"
then
    echo "dot files may be overwritten"
else
    if test -f .1.xml -o -f .1.json -o -f .2.xml -o -f .pp2.xml -o -f .pp2.xml
    then
        echo "file .# or .pp# files in the way and the -o was not used as the 3rd arg"
        exit 1
    fi
fi

# 1. Verify that the input is valid NeXML

# an apparent bug in xmllint
#   see http://sourceforge.net/mailarchive/message.php?msg_id=31798087
# necessitates some hacky expunging of attributes from a characters block...
cat "${inpnexml}" | sed -e 's/<characters\(.*\) xml:base="[^"]*" */<characters\1 /' > .1.xml

inpwasvalid=1
if ! xmllint --schema "${nexmlschemafp}" .1.xml >/dev/null 2>&1
then
    echo "${inpnexml} is not a valid NeXML file"
    inpwasvalid=0
fi

# 2. Convert to JSON
if ! python "$dir/xml2json-badgerfish.py" nj .1.xml > .1.json
then
    echo "Conversion of .1.xml to JSON failed"
    exit 1
fi

# 3. Convert back to NeXML
if ! python "$dir/xml2json-badgerfish.py" jn .1.json > .2.xml
then
    echo "Conversion of .1.json to JSON failed"
    exit 1
fi

# 4. validate NeXML
if ! xmllint --schema "${nexmlschemafp}" .2.xml >/dev/null 2>&1
then
    echo "XML written to .2.xml was not valid NeXML"
    if test $inpwasvalid -eq 1
    then
        exit 1
    fi
fi

# 5. very that after pretty printing and culling of unstable aspects of the file
# the input and output are identical
# pretty print
xmllint --format .1.xml > .pp1.xml || exit
xmllint --format .2.xml > .pp2.xml || exit

# pretty print
saxon-xslt .pp1.xml "${dir}/sortattr.xslt" > .s1.xml || exit
saxon-xslt .pp2.xml "${dir}/sortattr.xslt" > .s2.xml || exit

# clean by getting rid of hard-to-standardize xml decl and generator field in top element
sed -e '/<\?xml version/d' .s1.xml | sed -e 's/<nex\(.*\)generator="[^"]*"/<nex\1/' > .cpp1.xml
sed -e '/<\?xml version/d' .s2.xml | sed -e 's/<nex\(.*\)generator="[^"]*"/<nex\1/' > .cpp2.xml


if ! diff .cpp1.xml .cpp2.xml 
then
    echo "Did not roundtrip"
    exit 1
fi

if test $3 = "-o"
then
    rm .1.json .1.xml .2.xml .cpp1.xml .cpp2.xml .pp1.xml .pp2.xml .s1.xml .s2.xml 2>/dev/null
fi