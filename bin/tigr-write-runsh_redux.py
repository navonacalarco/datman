#!/usr/bin/env python
"""
Reads from yml config file and export info to determine what to put in run.sh for this project.
Then writes run.sh file.

Usage:
    tigr-write-runsh.py [options] <config.yml>

Arguments:
    <config.yml>             Configuration file in yml format

Options:
    --outputpath <path>      Full path to top of output tree
    --quiet                  Don't print warnings
    --verbose                Print warnings
    --help                   Print help


DETAILS

Reads from yml config file and export info to determine what to put in run.sh for this project.
Then writes run.sh file.

"""
from docopt import docopt
import datman as dm
import datman.utils
import datman.scanid
import yaml
import os
import sys


import filecmp
import difflib

arguments       = docopt(__doc__)
config_yml      = arguments['<config.yml>']
outputpath      = arguments['--outputpath']
VERBOSE         = arguments['--verbose']
QUIET           = arguments['--quiet']

## Read in the configuration yaml file
if not os.path.isfile(config_yml):
    sys.exit("configuration file not found. Try again.")

## load the yml file
with open(config_yml, 'r') as stream:
    config = yaml.load(stream)

## check that the expected keys are there
ExpectedKeys = ['PipelineSettings', 'Projects', 'ExportSettings']
diffs = set(ExpectedKeys) - set(config.keys())
if len(diffs) > 0:
    sys.exit("configuration file missing {}".format(diffs))

PipelineSettings = config['PipelineSettings']
ExportSettings = config['ExportSettings']

for Project in config['Projects'].keys():
    ProjectSettings = config['Projects'][Project]
    ## check that the projectdir exists
    projectdir =  os.path.normpath(ProjectSettings['PROJECTDIR'])
    if not os.path.exists(projectdir):
        print("WARNING: PROJECTDIR {} does not exist".format(projectdir))

    ## read in the site names as a list
    SiteNames = []
    for site in ProjectSettings['Sites']:
        SiteNames.append(site.keys()[0])

    ## sets some variables using defaults if not given
    if 'XNAT_PROJECT' in ProjectSettings.keys():
        XNAT_PROJECT = ProjectSettings['XNAT_PROJECT']
    else:
        XNAT_PROJECT = Project

    if 'PREFIX' in ProjectSettings.keys():
        PREFIX = config['PREFIX']
    else:
        PREFIX = Project

    if 'MRUSER' in ProjectSettings.keys():
        MRUSER = ProjectSettings['MRUSER']
    else:
        MRUSER = Project

    if 'MRFOLDER' in ProjectSettings.keys():
        MRFOLDER = ProjectSettings['MRFOLDER']
    else:
        MRFOLDER = '${MRUSER}*/*'

    ## read export info
    ScanTypes = ProjectSettings['ExportInfo'].keys()

    ## unless an outputfile is specified, set the output to ${PROJECTDIR}/bin/run.sh
    if outputpath == None:
        ouputfile = os.path.join(projectdir,'bin','run.sh')
    else:
        projectoutput = os.path.join(outputpath,Project)
        dm.utils.makedirs(projectoutput)
        outputfile = os.path.join(projectoutput,'run.sh')

    #open file for writing
    runsh = open(outputfile,'w')

    runsh.write('#!/bin/bash\n')
    runsh.write('#!/# Runs pipelines like a bro\n#!/#\n')

    runsh.write('#!/# Usage:\n')
    runsh.write('#!/#   run.sh [options]\n')
    runsh.write('#!/#\n')
    runsh.write('#!/# Options:\n')
    runsh.write('#!/#   --quiet     Do not be chatty (does nnt apply to pipeline stages)\n')
    runsh.write('#!/#\n#!/#\n')

    ## write the top bit
    runsh.write('export STUDYNAME=' + Project + '     # Data archive study name\n')
    runsh.write('export XNAT_PROJECT=' + XNAT_PROJECT + '  # XNAT project name\n')
    runsh.write('export MRUSER=' + MRUSER +'         # MR Unit FTP user\n')
    runsh.write('export MRFOLDER="'+ MRFOLDER +'"         # MR Unit FTP folder\n')
    runsh.write('export PROJECTDIR='+ projectdir +'\n')

    ## write the export from XNAT
    for siteinfo in ProjectSettings['Sites']:
        site = siteinfo.keys()[0]
        xnat = siteinfo[site]['XNAT_Archive']
        runsh.write('export XNAT_ARCHIVE_' + site + '=' + xnat + '\n')

    ## write the gold standard info
    if len(SiteNames) == 1:
        runsh.write('export ' + site + '_STANDARD=')
        runsh.write(projectdir + '/metadata/gold_standards/\n')
    else:
        for site in SiteNames:
            runsh.write('export ' + site + '_STANDARD=')
            runsh.write(projectdir + '/metadata/gold_standards/' + site + '\n')

    ## set some settings and load datman module
    runsh.write('args="$@"                           # commence ugly opt handling\n')
    runsh.write('DATESTAMP=$(date +%Y%m%d)\n\n')
    runsh.write('source /etc/profile\n')
    runsh.write('module load /archive/data-2.0/code/datman.module\n')
    runsh.write('export PATH=$PATH:${PROJECTDIR}/bin\n')

    ## define the message function
    runsh.write('function message () { [[ "$args" =~ "--quiet" ]] || echo "$(date): $1"; }\n')

    ## start running stuff
    runsh.write('{\n')
    runsh.write('  message "Running pipelines for study: $STUDYNAME"\n')

    ## get the scans from the camh server
    for cmd in PipelineSettings:
        cmdname = cmd.keys()[0]
        if 'runif' in cmd[cmdname].keys():
            if not eval(cmd[cmdname]['runif']): continue
        if 'message' in cmd[cmdname].keys():
            runsh.write('\n  message "'+ cmd[cmdname]['message']+ '..."\n')
        if 'modules' in cmd[cmdname].keys():
            runsh.write('  module load '+ cmd[cmdname]['modules']+'\n')
        fullcmd = '  ' + cmdname + ' ' + ' '.join(cmd[cmdname]['arguments']) + '\n'
        if 'SiteSpecificSettings' in cmd[cmdname].keys():
            for site in SiteNames:
                thiscmd = fullcmd.replace('<site>',site)
                runsh.write(thiscmd)
        else:
            runsh.write(fullcmd)
        if 'modules' in cmd[cmdname].keys():
            runsh.write('  module unload '+ cmd[cmdname]['modules']+'\n')

## pushing stuff to git hub
runsh.write('  message "Pushing QC documents to github..."\n')
runsh.write('  ( # subshell invoked to handle directory change\n')
runsh.write('    cd ${PROJECTDIR}\n')
runsh.write('    git add qc/\n')
runsh.write('    git add metadata/checklist.csv\n')
runsh.write('    git diff --quiet HEAD || git commit -m "Autoupdating QC documents"\n')
runsh.write('    git push --quiet\n')
runsh.write('  )\n\n')

## pushing website ness
if config['PipelineSettings'] != None:
    if 'qc-phantom.py' in config['PipelineSettings'].keys():
        runsh.write('  message "Pushing website data to github..."\n')
        runsh.write('  (  \n')
        runsh.write('    cd ${PROJECTDIR}/website\n')
        runsh.write('    git add .\n')
        runsh.write('    git commit -m "Updating QC plots"\n')
        runsh.write('    git push --quiet\n')
        runsh.write('  )\n\n')

### tee out a log
runsh.write('  message "Done."\n')
runsh.write('} | tee -a ${PROJECTDIR}/logs/run-all-${DATESTAMP}.log\n')

## close the file
runsh.close()
#
# ### change anything that needs to be changed with Find and Replace
# if config['FindandReplace'] != None :
#     with open (outputfile,'r') as runsh:
#         allrun = runsh.read()
#     for block in config['FindandReplace']:
#         toFind = block['Find']
#         toReplace = block['Replace']
#         if block['Find'] in allrun:
#             allrun = allrun.replace(block['Find'],block['Replace'])
#         else:
#             print('WARNING: could not find {} in run.sh file'.format(block['Find']))
#     with open (outputfile,'w') as runsh:
#         runsh.write(allrun)
