#!/bin/bash

VOCABULARY="$1"
RELEASE="$2"

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
	java -jar tools/widoco.jar -excludeIntroduction -noPlaceHolderText -ontFile './'$VOCABULARY'/'$VOCABULARY'.ttl' -outFolder './'$VOCABULARY'/latest' -lang en

	# Move files
	mv './'$VOCABULARY'/latest/index-en.html' './'$VOCABULARY'/latest/index.html'

	for EXT in "jsonld" "nt" "owl" "ttl" ; do
		mv './'$VOCABULARY'/latest/ontology.'$EXT './'$VOCABULARY'/latest/'$VOCABULARY'.'$EXT
		sed -i 's/ontology.'$EXT'/'$VOCABULARY'.'$EXT'/g' './'$VOCABULARY'/latest/index.html'
	done

	# Keep sections if folder exists
	if [ -e ./$VOCABULARY/sections ]; then
    	cp -r './'$VOCABULARY'/sections/'* './'$VOCABULARY'/latest/sections'
	fi

	# Keep both extensions for rdf/xml
	cp './'$VOCABULARY'/latest/'$VOCABULARY'.owl' './'$VOCABULARY'/latest/'$VOCABULARY'.rdf'
	
	rm './'$VOCABULARY'/latest/'*'.md'
	cp -r './'$VOCABULARY'/latest/'* './'$VOCABULARY'/'$RELEASE
fi