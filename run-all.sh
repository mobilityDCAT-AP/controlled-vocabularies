#!/bin/bash

for file in "./base"/*; do
  if [ -f "$file" ]; then
    filename=$(basename "$file")
    filename_no_ext="${filename%.*}"
    sh run.sh ''$filename_no_ext'' 0.1.0
  fi
done
