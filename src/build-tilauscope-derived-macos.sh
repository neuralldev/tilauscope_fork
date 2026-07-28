#!/bin/bash

echo "build-derived.sh"

PYUIC="${PYUIC:-pyuic6}"
PYLUPDATE="${PYLUPDATE:-./pylupdate6pro.py}"
QTTOOLS=qt6-tools;

# convert help files from .xlsx to .py
echo "************* help files **************"
python3 ../doc/help_dialogs/Script/xlsx_to_artisan_help.py all
if [ $? -ne 0 ]; then exit $?; else echo "** Success"; fi

# ui / uix
echo "************* ui/uic **************"
find ui -iname "*.ui" | while read f
do
    fullfilename=$(basename $f)
    fn=${fullfilename%.*}
    $PYUIC -o uic/${fn}.py -x ui/${fn}.ui
    if [ $? -ne 0 ]; then exit $?; fi
done
echo "** Success"

# translations
echo "************* pylupdate **************"
python3 $PYLUPDATE --verbose
if [ $? -ne 0 ]; then exit $?; else echo "** Success"; fi

echo "************* lrelease **************"
echo "*** compiling translations"
/opt/homebrew/opt/qt/bin/lrelease -verbose translations/*.ts
if [ $? -ne 0 ]; then exit $?; else echo "** Success"; fi

if [ $# != 0 ]; then
    # create a zip with the generated files
    echo "************* zip generated files **************"
    echo "** Argument supplied: $1"
    zip -rq ../generated-$1.zip ../doc/help_dialogs/Output_html/ help/ translations/ uic/
    if [ $? -ne 0 ]; then exit $?; else echo "** Success"; fi
fi
