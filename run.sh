#!/bin/bash

VOCABULARY="$1"
RELEASE="$2"
LANGUAGES="${3:-en}"
TREE_VOCABULARIES=("mobility-theme" "energy-fuel-type")

if [ "$VOCABULARY" = "" ] || [ "$RELEASE" = "" ]; then
    echo "Provide the name of a vocabulary as first argument and a version number x.y.z as the second one"
    exit 1
fi

if [ -d './'$VOCABULARY'/'$RELEASE ]; then
    echo "The provided version already exists."
    exit 1
else
	mkdir './'$VOCABULARY''
	cp './base/'$VOCABULARY'.xlsx' './'$VOCABULARY'/'$VOCABULARY'.xlsx'
	
	# From Excel to RDF
	java -jar tools/xls2rdf.jar convert -i './'$VOCABULARY'/'$VOCABULARY'.xlsx' -o './'$VOCABULARY'/'$VOCABULARY'.ttl' -l en
	sed -i "/a skos:ConceptScheme/ a\  a owl:Ontology;" "./$VOCABULARY/$VOCABULARY.ttl"

	sleep 10

	# Clean /latest and create folders
	rm -r './'$VOCABULARY'/latest'
	mkdir './'$VOCABULARY'/latest'
	mkdir './'$VOCABULARY'/'$RELEASE

	# Create serialisations and documentation
	java -jar tools/widoco.jar -excludeIntroduction -noPlaceHolderText -ontFile './'$VOCABULARY'/'$VOCABULARY'.ttl' -outFolder './'$VOCABULARY'/latest' -lang $LANGUAGES

	# Move files
	mv './'$VOCABULARY'/latest/index-en.html' './'$VOCABULARY'/latest/index.html'

	for EXT in "jsonld" "nt" "owl" "ttl" ; do
		mv './'$VOCABULARY'/latest/ontology.'$EXT './'$VOCABULARY'/latest/'$VOCABULARY'.'$EXT
		sed -i 's/ontology.'$EXT'/'$VOCABULARY'.'$EXT'/g' './'$VOCABULARY'/latest/index.html'
	done

	# Update description tree from workbook only for selected vocabularies
	APPLY_TREE="false"
	for TREE_VOCABULARY in "${TREE_VOCABULARIES[@]}"; do
		if [ "$VOCABULARY" = "$TREE_VOCABULARY" ]; then
			APPLY_TREE="true"
			break
		fi
	done

	if [ "$APPLY_TREE" = "true" ]; then
		TREE_SCRIPT="./generate_description_en_tree.py"
		if [ -f "$TREE_SCRIPT" ]; then
			PYTHON_BIN=""
			if [ -x "./.venv/bin/python" ]; then
				PYTHON_BIN="./.venv/bin/python"
			elif [ -x "./.venv/Scripts/python.exe" ]; then
				PYTHON_BIN="./.venv/Scripts/python.exe"
			elif command -v python3 >/dev/null 2>&1; then
				PYTHON_BIN="python3"
			elif command -v python >/dev/null 2>&1; then
				PYTHON_BIN="python"
			fi

			if [ "$PYTHON_BIN" = "" ]; then
				echo "Warning: Python not found, skipping description tree generation for $VOCABULARY"
			else
				"$PYTHON_BIN" "$TREE_SCRIPT" --xlsx "./$VOCABULARY/$VOCABULARY.xlsx"
			fi
		fi
	fi

	# Keep sections if folder exists
	if [ -e ./$VOCABULARY/sections ]; then
    	cp -r './'$VOCABULARY'/sections/'* './'$VOCABULARY'/latest/sections'
	fi

	# Keep both extensions for rdf/xml
	cp './'$VOCABULARY'/latest/'$VOCABULARY'.owl' './'$VOCABULARY'/latest/'$VOCABULARY'.rdf'
	
	rm './'$VOCABULARY'/latest/'*'.md'
	cp -r './'$VOCABULARY'/latest/'* './'$VOCABULARY'/'$RELEASE
fi