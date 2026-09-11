# ABOUT
# Qt Translation processing for Artisan
# Parses artisan.pro file.  Format of the .pro file:  Must have SOURCES and TRANSLATIONS files
# each on its own line, no blank lines.  A blank line must separate SOURCES and TRANSLATIONS.
#
# LICENSE
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 2 of the License, or
# version 3 of the License, or (at your option) any later versison. It is
# provided for educational purposes and is distributed in the hope that
# it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
# the GNU General Public License for more details.
#
# AUTHOR
# Dave Baxter, Marko Luther 2023
# modernized by Tilau 2026

import os
import subprocess
import sys
from typing import List, Set  #for Python >= 3.9: can remove 'List' since type hints can now use the generic 'list'
from pathlib import Path
import re

def extract_files(content:str, key:str)->List[str]:
    # Regex pour capturer tout ce qui suit KEY = jusqu'à une ligne vide
    match = re.search(rf"{key}\s*=\s*(.*?)(?=\n\n|\Z)", content, re.DOTALL)
    if not match:
        return []
    # Nettoyage des backslashes et des retours à la ligne
    raw_list = match.group(1).replace("\\\n", "").split()
    return [str(s.strip()) for s in raw_list if s.strip()]

try:
    print("** pylupdate6pro.py is executing")
#    print("os.environ: ",os.environ)

    # read the artisan.pro project file
    current_path = Path(__file__).parent
    file_path = current_path / 'artisan.pro'
    file_content = file_path.read_text(encoding='utf-8')
#    with open(current_path / 'artisan.pro', encoding='utf-8') as f:
#        file_content = f.read()

    # grab content from SOURCES to a blank line
    #start:int = file_content.index(r"SOURCES = ") +len("SOURCES = ") +3  #get past the backslash
    #end:int = file_content.find("\n\n", start)  #find will not raise an exception if it runs to the end of the file
    #if end == -1:
    #    end = len(file_content)
    #sources:List[str] = ['./' + s.strip().rstrip("\\") for s in file_content[start:end].split("\n") if s.strip()]
    # distill to the unique top directories
    #unique_top_dirs:list = set([os.path.split(source)[0] for source in sources])
    #unique_top_dirs:Set[str] = {os.path.split(source)[0] for source in sources}
    print("Looking for sources")
    sources = extract_files(file_content, "SOURCES")
    print("Looking for translations")
    translations = extract_files(file_content, "TRANSLATIONS")
    unique_top_dirs = {str(Path(s).parent) if str(Path(s).parent) != '.' else '.' for s in sources}
    # grab content from TRANSLATIONS to a blank line
    print (f"Unique top directories: {unique_top_dirs}")
    # Build the pylupdate6 command line
    cmdline:List[str] = ['pylupdate6']
    cmdline.extend(unique_top_dirs)
    for t in translations:
        cmdline.extend(['--ts', t])
    cmdline.append('--verbose')
    # run pylupdate6
    completed_process = subprocess.run(cmdline, capture_output=True, text=True, check=False)

    # prints are used to make entries in the Appveyor log (or on the console))
    if completed_process.returncode == 0:
        print("*** pylupdate6pro.py completed successfully")
        sys.exit(0)
    else:
        print(f"*** pylupdate6pro.py returned an error: {completed_process.stderr}")
        sys.exit(1)
except Exception as e:   #pylint: disable=broad-except
    print("*** pylupdate6pro.py got an exception")
    print(f"{e} line:{sys.exc_info()[2].tb_lineno}") #type: ignore
    sys.exit(1)
