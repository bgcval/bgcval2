#!/usr/bin/env python
#####!/usr/bin/python

#
# Copyright 2015, Plymouth Marine Laboratory
#
# This file is part of the bgc-val library.
#
# bgc-val is free software: you can redistribute it and/or modify it
# under the terms of the Revised Berkeley Software Distribution (BSD) 3-clause license.

# bgc-val is distributed in the hope that it will be useful, but
# without any warranty; without even the implied warranty of merchantability
# or fitness for a particular purpose. See the revised BSD license for more details.
# You should have received a copy of the revised BSD license along with bgc-val.
# If not, see <http://opensource.org/licenses/BSD-3-Clause>.
#
# Address:
# Plymouth Marine Laboratory
# Prospect Place, The Hoe
# Plymouth, PL1 3DH, UK
#
# Email:
# ledm@pml.ac.uk
#
"""
.. module:: analysis_timeseries
   :platform: Unix
   :synopsis: A script to produce analysis for time series.

.. moduleauthor:: Lee de Mora <ledm@pml.ac.uk>

"""
import argparse
import matplotlib as mpl

mpl.use('Agg')

#####
# Load Standard Python modules:
from sys import exit
from os.path import exists
from calendar import month_name
from socket import gethostname
from glob import glob
from scipy.interpolate import interp1d
import numpy as np
import os, sys
import getpass
import itertools
import yaml
import importlib
import pathlib

#####
# Load specific local code:
from bgcval2 import UKESMpython as ukp
from bgcval2.timeseries import timeseriesAnalysis
from bgcval2.timeseries import profileAnalysis
from bgcval2.timeseries import timeseriesTools as tst

from bgcval2.bgcvaltools.mergeMonthlyFiles import mergeMonthlyFiles, meanDJF
from bgcval2.bgcvaltools.AOU import AOU
from bgcval2.bgcvaltools.dataset import dataset
from bgcval2._runtime_config import get_run_configuration
from bgcval2.functions.standard_functions import std_functions

#####
# User defined set of paths pointing towards the datasets.
from bgcval2.Paths.paths import paths_setter


def listModelDataFiles(jobID, filekey, datafolder, annual):
    print("listing model data files:\njobID:\t", jobID, '\nfile key:\t',
         filekey, '\ndata folder:\t', datafolder, '\nannual flag:\t', annual)
    if annual:
        print("listing model data files:",
               datafolder + jobID + "/" + jobID + "o_1y_*_" + filekey + ".nc")
        datafolder = os.path.join(datafolder, jobID)
        model_files = sorted(
            glob(datafolder + "/" + jobID + "o_1y_*_" + filekey +
                 ".nc"))
    else:
        print("listing model data files:",
               datafolder + jobID + "/" + jobID + "o_1m_*_" + filekey + ".nc")
        datafolder = os.path.join(datafolder, jobID)
        model_files = sorted(
            glob(datafolder + "/" + jobID + "o_1m_*_" + filekey +
                 ".nc"))

    return model_files


def list_input_files(files_path, key_dict, paths):
    """
    Generate a list of files from a path, which may include
    several $PATH values.
    """
    #####
    # Replace some values for $FLAGS in the path:
    flags = ['USERNAME','basedir_model', 'basedir_obs','PATHS_GRIDFILE', 'PATHS_BGCVAL2']
    flag_values = [getpass.getuser(), paths.ModelFolder_pref, paths.ObsFolder, paths.orcaGridfn, paths.bgcval2_repo]

    for flag in ['jobID', 'model', 'years','year', 'scenario', 'name']:
        if key_dict.get(flag, False):
            flags.append(flag.upper())
            flag_values.append(key_dict[flag])

    for flag, flag_value in zip(flags, flag_values):
        files_path = findReplaceFlag(files_path, flag, flag_value)

    basedir = os.path.dirname(files_path)
    if not os.path.exists(basedir):
        raise OSError(f"Base {basedir} is not a valid directory.")
    input_files = sorted(glob(files_path))
    if not input_files:
        raise FileNotFoundError(f"Data dir {basedir} does not contain and file "
                                f"that matches pattern {files_path}, {flag}")
    return input_files


def build_list_of_suite_keys(suites, debug=True):
    """
    Generate a list of keys from a list of suites.

    """
    print('analysis_timeseries: Calling build_list_of_suite_keys to build list of keys')
    paths_dir = os.path.dirname(os.path.realpath(__file__))
    key_lists_dir = os.path.join(os.path.dirname(paths_dir), 'key_lists')

    print(f'analysis_timeseries: Directory where keys are stored: {key_lists_dir}')
    analysis_keys = {}
    for suite in suites:
        if not suite or suite in [' ', ',']: 
            continue

        # look for a list in keys_list directory:
        suite_yml = os.path.join(key_lists_dir, ''.join([suite.lower(),'.yml']))
        if debug:
            print('build_list_of_suite_keys:\tlooking for suite yaml:', suite_yml)

        if not os.path.exists(suite_yml):
            print(f'analysis_timeseries: build_list_of_suite_keys:\tERROR: suite yaml: {suite_yml} file does not exist')
            sys.exit(1)

        # Open yml file:
        with open(suite_yml, 'r') as openfile:
            suite_dict = yaml.safe_load(openfile)

        if not suite_dict or not isinstance(suite_dict, dict):
            print(f"Configuration file {suite_yml} "
                  "is either empty or corrupt, please check its contents")
            sys.exit(1)

        keys_dict = suite_dict.get('keys', {})

        for key, keybool in keys_dict.items():
            if debug and key in analysis_keys:
                print(f'build_list_of_suite_keys:\tKey {key} exists in multiple suites:')

            if key in analysis_keys and keybool != analysis_keys[key]:
                print(f'build_list_of_suite_keys:\tERROR: conflict in input yamls: {key}, {keybool} != {analysis_keys[key]}')
                sys.exit(1)

            if keybool:
                if debug:
                    print('build_list_of_suite_keys:\tAdding key:', key)

                analysis_keys[key] = keybool
    analysis_keys = [key for key in analysis_keys.keys()]
    return analysis_keys


def get_kwargs_from_dict(convert_dict, avoids = ['path', 'function']):
    """
    Get the KWARGS fromn a dict
    """
    kwargs = {}
    for key, value in convert_dict.items():
        if key in avoids:
            continue
        kwargs[key] = value
    return kwargs


def load_function(convert):
    """
    Using the named function in the key yaml, load that function and return it and it kwargs.
    """
    # function is listed as a standard function string
    if isinstance(convert, str) and convert in std_functions:
        print( "Standard Function Found:", convert)
        return std_functions[convert], {}

    functionname = convert.get('function', False)
    if not functionname:
        raise KeyError(f'Function name not provided in convert dict: {convert}')

    # function is listed as a standard function string with kwargs:
    if functionname in std_functions:
        print( "Standard Function Found:", functionname)
        kwargs = get_kwargs_from_dict(convert)
        return std_functions[functionname], kwargs

    func_path = convert.get('path', False)
    if not func_path:
        raise KeyError(f'No path provided in {str(convert)} dictionary')

    if func_path[:7] == 'bgcval2':
        # path is relative to bgcval2 repo.
        repo_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        func_path = os.path.join(repo_dir, func_path)

    if not os.path.exists(func_path):
        raise FileNotFoundError(f'Path {func_path} to custom function file not found.')

    # load function from Python file in path
    modulename = os.path.splitext(os.path.basename(func_path))[0]
    loader = importlib.machinery.SourceFileLoader(modulename, func_path)
    module = loader.load_module()
    func = getattr(module, functionname)

    kwargs = get_kwargs_from_dict(convert)

    print('Successfully loaded function:', functionname, 'from', func_path, 'with kwargs:', kwargs)
    return func, kwargs


def findReplaceFlag(filepath, flag, new_value):
    """
    Looking for $FLAG in the filepath.
    If found, we replace $FLAG with new_value
    """
    lookingFor = ''.join(['$', flag.upper()])
    if filepath.find(lookingFor) == -1:
        print('NOT Changing FLAG:', lookingFor, 'to', new_value, 'in', filepath)

        return filepath
    print('Changing FLAG:', lookingFor, 'to', new_value, 'in', filepath)
    filepath = filepath.replace(lookingFor, new_value)
    return filepath


def parse_list_from_string(list1):
    """
    This tool takes a string and returns it as a list.
    """
    if isinstance(list1, list):
       return list1
    list1 = list1.replace('\t', ' ').replace(',', ' ').replace('  ', ' ')
    list1 = list1.replace('\'', '').replace('\"', '').replace(';', '')
    while list1.count('  ')>0:
        list1 = list1.replace('  ', ' ')
    #if len(list1)==0: return []
    return list1.split(' ')


def load_key_file(key, paths, jobID):
    """
    load_key_file:
        takes an input file from key_files directory
        and outputs a dictionary.
    """
    output_dict = {}
    print('load_key_file: checking {key}', key)
    key_yml_path = os.path.join(os.path.join(paths.bgcval2_repo, 'key_files', ''.join([key.lower(),'.yml'])))
    if os.path.exists(key_yml_path):
        print('key_yml_path exists:', key_yml_path)
    else:
        raise FileNotFoundError(f'{key_yml_path} does not exist')

    # Open yml file:
    with open(key_yml_path, 'r') as openfile:
        key_dict = yaml.safe_load(openfile)

    if not key_dict or not isinstance(key_dict, dict):
        print(f"Key Yaml file {key_yml_path} "
              "is either empty or corrupt, please check its contents")
        sys.exit(1)

    # add jobID to dict:
    key_dict['jobID'] = jobID

    # Load basic fields:
    for field in ['name', 'units', 'dimensions', 'modelgrid']:
        output_dict[field] = key_dict.get(field, None)
        print('Adding', field,':', output_dict[field])

    # Lists:
    for field in ['layers', 'regions', ]:
        output_dict[field] = key_dict.get(field, '')
        output_dict[field] = parse_list_from_string(output_dict[field])
        print('Adding', field,':', output_dict[field])

    # Metrics
    if key_dict['dimensions'] in  [1,]:
        metricList = ['metricless',]
    else:
        metricList = ['mean', ] #'median', '10pc','20pc','30pc','40pc','50pc','60pc','70pc','80pc','90pc','min','max']
    output_dict['metrics'] = key_dict.get('metrics', metricList)
    output_dict['metrics'] = parse_list_from_string(output_dict['metrics'])

    # Load Grid:
    gridFile = key_dict.get('gridFile', paths.orcaGridfn)
    output_dict['gridFile'] = list_input_files(gridFile, key_dict, paths)[0]

    # load model or data specific parts:
    for model_or_data in ['model', 'data']:
        md_vars = key_dict.get(''.join([model_or_data, '_vars']), False)
        if model_or_data == 'data' and md_vars is False:
            # Some analyses don't have observational data.
            continue

        if model_or_data == 'model' and md_vars is False:
            raise KeyError(f'What are you trying to analyse: model_vars {md_vars} is empty in yml_file: {key_yml_path}')

        md_vars = parse_list_from_string(md_vars)
        md_convert = key_dict[''.join([model_or_data, '_convert'])]
        convert_func, kwargs = load_function(md_convert)

        output_dict[''.join([model_or_data, 'details'])] = {
            'name': key_dict['name'],
            'vars': md_vars ,
            'convert': convert_func,
            'units': key_dict['units'],
            }
        for kwarg, kwarg_value in kwargs.items():
            if isinstance(kwarg_value, str) and kwarg.lower().find('file')>-1:
                output_dict[''.join([model_or_data,'details'])][kwarg] = list_input_files(kwarg_value, key_dict, paths)
            else:
                output_dict[''.join([model_or_data,'details'])][kwarg] = kwarg_value

        if model_or_data == 'model':
            file_path = key_dict[''.join([model_or_data, 'Files'])]
            mdfile = list_input_files(file_path, key_dict, paths)
            output_dict[''.join([model_or_data, 'Files'])] = mdfile
        else:
            # get data file path
            file_path = key_dict[''.join([model_or_data, 'File'])]
            mdfile = list_input_files(file_path, key_dict, paths)
            if isinstance(mdfile, list) and len(mdfile) == 1:
                mdfile = mdfile[0]

        output_dict[''.join([model_or_data, 'Files'])] = mdfile

        coords = ukp.load_coords_from_netcdf(mdfile)
        output_dict[''.join([model_or_data, 'coords'])] = {
            'tdict': ukp.tdicts[key_dict.get('tdict', 'ZeroToZero')],
            }
        for coord, value in coords.items():
            # Coordinate names are guessed, but can be over-written in the yaml.

            coord_in_yml = ''.join([model_or_data, '_', coord])
            if  coord_in_yml in key_dict:
                value = key_dict[coord_in_yml]
            output_dict[''.join([model_or_data, 'coords'])][coord] = value
    return output_dict


def analysis_timeseries(
    jobID="u-ab671",
    suites=['all', ],
    regions='all',
    clean=0,
    annual=True,
    strictFileCheck=True,
    config_user=None
):
    """
	The role of this code is to produce time series analysis.
	The jobID is the monsoon/UM job id and it looks for files with a specific format

	The clean flag allows you to start the analysis without loading previous data.

	The annual flag means that we look at annual (True) or monthly (False) data.

	The strictFileCheck switch checks that the data/model netcdf files exist.
	It fails if the switch is on and the files no not exist.

	suites chooses a set of fields to look at.

	regions selects a list of regions, default is 'all', which is the list supplied by Andy Yool.

	:param jobID: the jobID
	:param clean: deletes old images if true
	:param annual: Flag for monthly or annual model data.
	:param strictFileCheck: CStrickt check for model and data files. Asserts if no files are found.
	:param suites: Which data to analyse, ie level1, physics only, debug, etc
	:param regions:

	"""

    print('-----------------------')
    print('Starting analysis_timeseries')
    print('jobID:', jobID)
    print('suites:', suites)
    print('regions:', regions)
    print(f'clean: {clean},  annual: {annual}, strictFileCheck: {strictFileCheck}')
    print('config_user:', config_user)

    # get runtime configuration
    if config_user:
        paths_dict, config_user = get_run_configuration(config_user)
    else:
        paths_dict, config_user = get_run_configuration("defaults")

    # filter paths dict into an object that's usable below
    paths = paths_setter(paths_dict)

    #####
    # Switches:
    # These are some booleans that allow us to choose which analysis to run.
    # This lets up give a list of keys one at a time, or in parrallel.
    #if type(suites) == type(['Its', 'A', 'list!']):
    if isinstance(suites, str):
        suites = suites.replace(',', ' ').replace('\'', '').replace('"', '')
        suites = suites.split(' ')

    analysisKeys = build_list_of_suite_keys(suites, debug=True)
    print('analysisKeys', analysisKeys)

    #####
    # Some lists of region.
    # This are pre-made lists of regions that can be investigated.
    # Note that each analysis below can be given its own set of regions.
    layerList = [
        'Surface',
    ]  #'500m','1000m',]
    metricList = [
        'mean',
    ]  #'median', '10pc','20pc','30pc','40pc','50pc','60pc','70pc','80pc','90pc','min','max']

    if regions == 'all':
        regionList = [
            'Global',
            'ignoreInlandSeas',
            'SouthernOcean',
            'ArcticOcean',
            'AtlanticSOcean',
            'Equator10',
            'Remainder',
            'NorthernSubpolarAtlantic',
            'NorthernSubpolarPacific',
        ]
    if regions == 'short':
        regionList = [
            'Global',
            'SouthernHemisphere',
            'NorthernHemisphere',
        ]

    if regions in ['debug', 'Global', 'spinup']:
        regionList = ['Global', ]

        metricList = [
            'mean',
        ]

    # Regions from Pierce 1995 - https://doi.org/10.1175/1520-0485(1995)025<2046:CROHAF>2.0.CO;2
    PierceRegions = [
        'Enderby',
        'Wilkes',
        'Ross',
        'Amundsen',
        'Weddel',
    ]
    OMZRegions = [
        'EquatorialPacificOcean', 'IndianOcean', 'EquatorialAtlanticOcean'
    ]  #'Ross','Amundsen','Weddel',]

    #if analysisSuite.lower() in ['debug',]:
    #        regionList      = ['Global', 'ArcticOcean',]

    #####
    # The z_component custom command:
    # This flag sets a list of layers and metrics.
    # It's not advised to run all the metrics and all the layers, as it'll slow down the analysis.
    # if z_component in ['SurfaceOnly',]:

    #	if z_component in ['FullDepth',]:
    #		layerList = [0,2,5,10,15,20,25,30,35,40,45,50,55,60,70,]
    #		metricList = ['mean','median',]

    #####
    # Location of images directory
    # the imagedir is where the analysis images will be saved.

    #####
    # Location of shelves folder
    # The shelve directory is where the intermediate processing files are saved in python's shelve format.
    # This allows us to put away a python open to be re-opened later.
    # This means that we can interupt the analysis without loosing lots of data and processing time,
    # or we can append new simulation years to the end of the analysis without starting from scratch each time.
    #shelvedir 	= ukp.folder('shelves/timeseries/'+jobID)

    #####
    # Location of data files.
    # The first thing that this function does is to check which machine it is being run.
    # This is we can run the same code on multiple machines withouht having to make many copies of this file.
    # So far, this has been run on the following machines:
    #	PML
    #	JASMIN
    #	Charybdis (Julien's machine at NOCS)
    #
    # Feel free to add other macihines onto this list, if need be.

    shelvedir = ukp.folder([paths.shelvedir, "timeseries", jobID])
    imagedir = ukp.folder([paths.imagedir, jobID, 'timeseries'])

    if annual: WOAFolder = paths.WOAFolder_annual
    else: WOAFolder = paths.WOAFolder

    #####
    # PML
    hostname = gethostname()

    if hostname.find('pmpc') > -1:
        print("analysis_timeseries:\tBeing run at PML on ", gethostname())

    #####
    # JASMIN
    if hostname.find('ceda.ac.uk') > -1 or hostname.find(
            'jasmin') > -1 or hostname.find('jc.rl.ac.uk') > -1:
        print("analysis_timeseries:\tBeing run at CEDA on ", hostname)

    #####
    # Unable to find location of files/data.
    if not paths.machinelocation:
        print(
            "analysis_timeseries:\tFATAL:\tWas unable to determine location of host: ",
            gethostname())
        print("Please set up paths.py, based on Paths/paths_template.py")
        #FIXME this is just for local testing by V
        if gethostname() == "valeriu-PORTEGE-Z30-C":
            assert True
        else:
            assert False

    #####
    # Because we can never be sure someone won't randomly rename the
    # time dimension without saying anything.
    try:
        tmpModelFiles = listModelDataFiles(jobID, 'grid_T',
                                           paths.ModelFolder_pref, annual)
    except:
        print(
            "No grid_T Model files available to figure out what naming convention is used."
        )
        tmpModelFiles = []
    ukesmkeys = {}
    if len(tmpModelFiles):
        nctmp = dataset(tmpModelFiles[0], 'r')
        nctmpkeys = list(nctmp.variables.keys())
        nctmp.close()
        if 'votemper' in nctmpkeys:
            ukesmkeys['time'] = 'time_counter'
            ukesmkeys['temp3d'] = 'votemper'
            ukesmkeys['sst'] = ''
            ukesmkeys['sal3d'] = 'vosaline'
            ukesmkeys['sss'] = ''
            ukesmkeys['v3d'] = 'vomecrty'
            ukesmkeys['u3d'] = 'vozocrtx'
            ukesmkeys['e3u'] = 'e3u'
            ukesmkeys['w3d'] = 'vovecrtz'
            ukesmkeys['MLD'] = 'ssomxl010'
        elif 'thetao_con' in nctmpkeys: # Added keys for UKESM2.
            ukesmkeys['time'] = 'time_counter'
            ukesmkeys['temp3d'] = 'thetao_con'
            ukesmkeys['sst'] = 'tos_con'
            ukesmkeys['sal3d'] = 'so_abs'
            ukesmkeys['sss'] = 'sos_abs'
            ukesmkeys['v3d'] = 'vo'
            ukesmkeys['u3d'] = 'uo'
            ukesmkeys['e3u'] = 'thkcello'
            ukesmkeys['w3d'] = 'wo'
            ukesmkeys['MLD'] = 'somxzint1'
        else:
            ukesmkeys['time'] = 'time_centered'
            ukesmkeys['temp3d'] = 'thetao'
            ukesmkeys['sst'] = 'tos'
            ukesmkeys['sal3d'] = 'so'
            ukesmkeys['sss'] = 'sos'
            ukesmkeys['v3d'] = 'vo'
            ukesmkeys['u3d'] = 'uo'
            ukesmkeys['e3u'] = 'thkcello'
            ukesmkeys['w3d'] = 'wo'
            ukesmkeys['MLD'] = 'ssomxl010'


#####
# Coordinate dictionary
# These are python dictionairies, one for each data source and model.
# This is because each data provider seems to use a different set of standard names for dimensions and time.
# The 'tdict' field is short for "time-dictionary".
#	This is a dictionary who's indices are the values on the netcdf time dimension.
#	The tdict indices point to a month number in python numbering (ie January = 0)
# 	An example would be, if a netcdf uses the middle day of the month as it's time value:
#		tdict = {15:0, 45:1 ...}

    #	def listModelDataFiles(jobID, filekey, datafolder, annual):
    #		print "listing model data files:\njobID:\t",jobID, '\nfile key:\t',filekey,'\ndata folder:\t', datafolder, '\nannual flag:\t',annual
    #		if annual:
    #			print "listing model data files:",datafolder+jobID+"/"+jobID+"o_1y_*_"+filekey+".nc"
    #			return sorted(glob(datafolder+jobID+"/"+jobID+"o_1y_*_"+filekey+".nc"))
    #		else:
    #                        print "listing model data files:",datafolder+jobID+"/"+jobID+"o_1m_*_"+filekey+".nc"
    #			return sorted(glob(datafolder+jobID+"/"+jobID+"o_1m_*_"+filekey+".nc"))

    masknc = dataset(paths.orcaGridfn, 'r')
    tlandmask = masknc.variables['tmask'][:]
    masknc.close()

    def applyLandMask(nc, keys):
        #### works like no change, but applies a mask.
        return np.ma.masked_where(tlandmask == 0,
                                  nc.variables[keys[0]][:].squeeze())

    def applySurfaceMask(nc, keys):
        #### works like no change, but applies a mask.
        return np.ma.masked_where(tlandmask[0, :, :] == 0,
                                  nc.variables[keys[0]][:].squeeze())

    def applyLandMask1e3(nc, keys):
        return applyLandMask(nc, keys) * 1000.

#####
# The analysis settings:
# Below here is a list of analysis settings.
# The settings are passed to timeseriesAnalysis using a nested dictionary (called an autovivification, here).
#
# These analysis were switched on or off at the start of the function.
# Each analysis requires:
#	model files
#	data files
#	model and data coordinate dictionaries, (defines above)
#	model and data details (a set of instructions of what to analyse:
#		name: 		field name
#		vars:		variable names in the netcdf
#		convert: 	a function to manipuate the data (ie change units, or add two fields together.
#				There are some standard ones in UKESMPython.py, but you can write your own here.
#		units: 		the units after the convert function has been applied.
#		layers:		which vertical layers to look at (ie, surface, 100m etc...)
#		regions:	which regions to look at. Can be speficied here, or use a pre-defined list (from above)
#		metrics:	what metric to look at:  mean, median or sum
#		model and data source: 	the name of source of the model/data (for plotting)
#		model grid: 	the model grid, usually eORCA1
#		the model grid file: 	the file path for the model mesh file (contains cell area/volume/masks, etc)
#
#	Note that the analysis can be run with just the model, it doesn't require a data file.
#	If so, just set to data file to an empty string:
#		av[name]['dataFile']  = ''

    # NEW STYLE keys from file:
    av = ukp.AutoVivification()
    for key in analysisKeys:
        av[key] = load_key_file(key, paths, jobID)

    # OLD STYLE way:
    if 'Chl_pig' in analysisKeys:
        name = 'Chlorophyll_pig'
        av[name]['modelFiles'] = sorted(
            glob(paths.ModelFolder_pref + jobID + "/" + jobID +
                 "o_1y_*_ptrc_T.nc"))
        av[name][
            'dataFile'] = paths.MAREDATFolder + "MarEDat20121001Pigments.nc"

        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = maredatCoords

        av[name]['modeldetails'] = {
            'name': name,
            'vars': ['CHN', 'CHD'],
            'convert': ukp.sums,
            'units': 'mg C/m^3'
        }
        av[name]['datadetails'] = {
            'name': name,
            'vars': [
                'Chlorophylla',
            ],
            'convert': ukp.div1000,
            'units': 'ug/L'
        }

        av[name]['layers'] = layerList
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList

        av[name]['datasource'] = 'MAREDAT'
        av[name]['model'] = 'MEDUSA'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 3

    if 'Chl_CCI' in analysisKeys:
        name = 'Chlorophyll_cci'
        #####
        # Not that this is the 1 degree resolution dataset, but higher resolution data are also available.

        av[name]['modelFiles'] = listModelDataFiles(jobID, 'ptrc_T',
                                                    paths.ModelFolder_pref,
                                                    annual)
        if annual:
            av[name][
                'dataFile'] = paths.CCIDir + "ESACCI-OC-L3S-OC_PRODUCTS-CLIMATOLOGY-16Y_MONTHLY_1degree_GEO_PML_OC4v6_QAA-annual-fv2.0.nc"
            print(paths.ModelFolder_pref + "/" + jobID + "o_1y_*_ptrc_T.nc")
        else:
            av[name][
                'dataFile'] = paths.CCIDir + 'ESACCI-OC-L3S-OC_PRODUCTS-CLIMATOLOGY-16Y_MONTHLY_1degree_GEO_PML_OC4v6_QAA-all-fv2.0.nc'

        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = cciCoords

        av[name]['modeldetails'] = {
            'name': name,
            'vars': ['CHN', 'CHD'],
            'convert': ukp.sums,
            'units': 'mg C/m^3'
        }
        av[name]['datadetails'] = {
            'name': name,
            'vars': [
                'chlor_a',
            ],
            'convert': ukp.NoChange,
            'units': 'mg C/m^3'
        }

        av[name]['layers'] = [
            'Surface',
        ]  # CCI is surface only, it's a satellite product.
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList  #['mean','median', ]

        av[name]['datasource'] = 'CCI'
        av[name]['model'] = 'MEDUSA'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 2

    if 'CHD' in analysisKeys or 'CHN' in analysisKeys:
        for name in [
                'CHD',
                'CHN',
        ]:
            if name not in analysisKeys: continue

            av[name]['modelFiles'] = listModelDataFiles(
                jobID, 'ptrc_T', paths.ModelFolder_pref, annual)
            av[name]['dataFile'] = ''

            av[name]['modelcoords'] = medusaCoords
            av[name]['datacoords'] = ''

            av[name]['modeldetails'] = {
                'name': name,
                'vars': [
                    name,
                ],
                'convert': ukp.NoChange,
                'units': 'mg C/m^3'
            }
            av[name]['datadetails'] = {'name': '', 'units': ''}

            av[name]['layers'] = [
                'Surface',
            ]  #'100m',] 	# CCI is surface only, it's a satellite product.
            av[name]['regions'] = regionList
            av[name]['metrics'] = metricList  #['mean','median', ]

            av[name]['datasource'] = ''
            av[name]['model'] = 'MEDUSA'

            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 3

    for name in [
            'CHL_JJA', 'CHL_DJF', 'CHL_SON', 'CHL_MAM', 'GC_CHL_JJA',
            'GC_CHL_DJF', 'GC_CHL_SON', 'GC_CHL_MAM'
    ]:
        if name not in analysisKeys: continue

        if name in ['CHL_MAM', 'GC_CHL_MAM']:
            monthlyFiles = glob(paths.ModelFolder_pref + '/' + jobID +
                                '/monthlyCHL/' + jobID +
                                'o_1m_????0[345]*_ptrc_T.nc')
        if name in [
                'CHL_JJA',
                'GC_CHL_JJA',
        ]:
            monthlyFiles = glob(paths.ModelFolder_pref + '/' + jobID +
                                '/monthlyCHL/' + jobID +
                                'o_1m_????0[678]*_ptrc_T.nc')
        if name in [
                'CHL_SON',
                'GC_CHL_SON',
        ]:
            monthlyFiles = []
            for month in ['09', '10', '11']:
                monthlyFiles.extend(
                    glob(paths.ModelFolder_pref + '/' + jobID +
                         '/monthlyCHL/' + jobID + 'o_1m_????' + month +
                         '*_ptrc_T.nc'))
        if name in ['CHL_DJF', 'GC_CHL_DJF']:
            monthlyFiles = []
            for month in ['12', '01', '02']:
                monthlyFiles.extend(
                    glob(paths.ModelFolder_pref + '/' + jobID +
                         '/monthlyCHL/' + jobID + 'o_1m_????' + month +
                         '*_ptrc_T.nc'))

        if len(monthlyFiles):
            if name in [
                    'CHL_JJA', 'CHL_SON', 'CHL_MAM', 'GC_CHL_JJA',
                    'GC_CHL_SON', 'GC_CHL_MAM'
            ]:
                chlfiles = mergeMonthlyFiles(monthlyFiles,
                                             outfolder='',
                                             cal=medusaCoords['cal'],
                                             timeAverage=True,
                                             expectedNumberOfFiles=3)
            if name in [
                    'CHL_DJF',
                    'GC_CHL_DJF',
            ]:
                chlfiles = meanDJF(monthlyFiles,
                                   outfolder='',
                                   cal=medusaCoords['cal'],
                                   timeAverage=True)

            def CHL_MODEL(nc, keys):
                chl = nc.variables[keys[0]][:, 0] + nc.variables[keys[1]][:, 0]
                chl = np.ma.array(chl)
                chl = np.ma.masked_where(chl.mask + (chl > 10E10), chl)
                return chl

            def CHLMAM_Data(nc, keys):
                chl = nc.variables[keys[0]][2:5].mean(0).squeeze()
                chl = np.ma.array(chl)
                chl = np.ma.masked_where(chl.mask + (chl > 10E10), chl)
                return chl

            def CHLJJA_Data(nc, keys):
                chl = nc.variables[keys[0]][5:8].mean(0).squeeze()
                chl = np.ma.array(chl)
                chl = np.ma.masked_where(chl.mask + (chl > 10E10), chl)
                return chl

            def CHLSON_Data(nc, keys):
                chl = nc.variables[keys[0]][8:11].mean(0)
                chl = np.ma.masked_where(chl.mask + (chl > 10E10), chl)
                return chl

            def CHLDJF_Data(nc, keys):
                chl = []
                chl.append(nc.variables[keys[0]][0])
                chl.append(nc.variables[keys[0]][1])
                chl.append(nc.variables[keys[0]][11])
                chl = np.ma.array(chl).mean(0)
                chl = np.ma.masked_where(chl.mask + (chl > 10E10), chl)
                return chl

            av[name]['modelFiles'] = chlfiles
            av[name]['modelcoords'] = medusaCoords

            if name[:2] == 'GC':
                av[name][
                    'dataFile'] = paths.ObsFolder + 'MO-GlobColour/qrclim_globcolour_masked.sea.nc'
                av[name]['datacoords'] = mogcCoords
                av[name]['datasource'] = 'MO-GlobColour'
                chldatakey = 'chl'
            else:
                av[name][
                    'dataFile'] = paths.CCIDir + 'ESACCI-OC-L3S-OC_PRODUCTS-CLIMATOLOGY-16Y_MONTHLY_1degree_GEO_PML_OC4v6_QAA-all-fv2.0.nc'
                av[name]['datacoords'] = cciCoords
                av[name]['datasource'] = 'CCI'
                chldatakey = 'chlor_a'

            av[name]['modeldetails'] = {
                'name': name,
                'vars': ['CHN', 'CHD'],
                'convert': CHL_MODEL,
                'units': 'mg C/m^3'
            }

            if name in ['CHL_MAM', 'GC_CHL_MAM']:
                av[name]['datadetails'] = {
                    'name': name,
                    'vars': [
                        chldatakey,
                    ],
                    'convert': CHLMAM_Data,
                    'units': 'mg C/m^3'
                }
                av[name]['regions'] = [
                    'Equator10',
                    'Remainder',
                    'NorthernSubpolarAtlantic',
                    'NorthernSubpolarPacific',
                    'Global',
                    'SouthernOcean',
                ]  #'CCI_MAM']
            if name in [
                    'CHL_JJA',
                    'GC_CHL_JJA',
            ]:
                av[name]['datadetails'] = {
                    'name': name,
                    'vars': [
                        chldatakey,
                    ],
                    'convert': CHLJJA_Data,
                    'units': 'mg C/m^3'
                }
                av[name]['regions'] = [
                    'Equator10',
                    'Remainder',
                    'NorthernSubpolarAtlantic',
                    'NorthernSubpolarPacific',
                    'CCI_JJA',
                    'Global',
                    'SouthernOcean',
                ]

            if name in [
                    'CHL_SON',
                    'GC_CHL_SON',
            ]:
                av[name]['datadetails'] = {
                    'name': name,
                    'vars': [
                        chldatakey,
                    ],
                    'convert': CHLSON_Data,
                    'units': 'mg C/m^3'
                }
                av[name]['regions'] = [
                    'Equator10',
                    'Remainder',
                    'NorthernSubpolarAtlantic',
                    'NorthernSubpolarPacific',
                    'Global',
                    'CCI_SON',
                    'SouthernOcean',
                ]

            if name in ['CHL_DJF', 'GC_CHL_DJF']:
                av[name]['datadetails'] = {
                    'name': name,
                    'vars': [
                        chldatakey,
                    ],
                    'convert': CHLDJF_Data,
                    'units': 'mg C/m^3'
                }
                av[name]['regions'] = [
                    'Equator10',
                    'Remainder',
                    'NorthernSubpolarAtlantic',
                    'NorthernSubpolarPacific',
                    'CCI_DJF',
                    'Global',
                    'SouthernOcean',
                ]

            av[name]['layers'] = [
                'Surface',
            ]

            av[name]['metrics'] = metricList

            av[name]['model'] = 'NEMO'

            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 2

        else:
            print("No monthly CHL files found")

    if 'DTC' in analysisKeys:
        for name in [
                'DTC',
        ]:
            if name not in analysisKeys: continue

            av[name]['modelFiles'] = listModelDataFiles(
                jobID, 'ptrc_T', paths.ModelFolder_pref, annual)
            av[name]['dataFile'] = ''

            av[name]['modelcoords'] = medusaCoords
            av[name]['datacoords'] = ''

            av[name]['modeldetails'] = {
                'name': name,
                'vars': [
                    name,
                ],
                'convert': ukp.mul1000,
                'units': 'umol-C/m3'
            }
            av[name]['datadetails'] = {'name': '', 'units': ''}

            av[name]['layers'] = [
                '3000m',
            ]  #'100m',]         # CCI is surface only, it's a satellite product.
            av[name]['regions'] = regionList
            av[name]['metrics'] = metricList  #['mean','median', ]

            av[name]['datasource'] = ''
            av[name]['model'] = 'MEDUSA'

            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 3

    if 'DiaFrac' in analysisKeys:

        name = 'DiaFrac'

        def caldiafrac(nc, keys):
            chd = applyLandMask(nc, [
                keys[0],
            ]).squeeze()
            chn = applyLandMask(nc, [
                keys[1],
            ]).squeeze()
            return 100. * chd / (chd + chn)

        av[name]['modelFiles'] = listModelDataFiles(jobID, 'ptrc_T',
                                                    paths.ModelFolder_pref,
                                                    annual)
        av[name]['dataFile'] = ''

        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = ''

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                'CHD',
                'CHN',
            ],
            'convert': caldiafrac,
            'units': '%'
        }
        av[name]['datadetails'] = {'name': '', 'units': ''}

        av[name]['layers'] = [
            'Surface',
            '100m',
        ]  # CCI is surface only, it's a satellite product.
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList  #['mean','median', ]

        av[name]['datasource'] = ''
        av[name]['model'] = 'MEDUSA'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 3



    if 'OMZMeanDepth' in analysisKeys:
        if annual:
            av['OMZMeanDepth']['modelFiles'] = sorted(
                glob(paths.ModelFolder_pref + jobID + "/" + jobID +
                     "o_1y_*_ptrc_T.nc"))
            av['OMZMeanDepth']['dataFile'] = WOAFolder + 'woa13_all_o00_01.nc'
        else:
            print("OMZ Thickness not implemented for monthly data")
            assert 0

        nc = dataset(paths.orcaGridfn, 'r')
        depths = np.abs(nc.variables['gdepw'][:])
        tmask = nc.variables['tmask'][:]
        nc.close()

        omzthreshold = 20.

        def modelMeanOMZdepth(nc, keys):
            o2 = np.ma.array(nc.variables[keys[0]][:].squeeze())
            meandepth = np.ma.masked_where(
                (o2 > omzthreshold) + o2.mask + (tmask == 0), depths).mean(0)
            if meandepth.max() in [0., 0]: return np.array([
                    0.,
            ])
            return np.ma.masked_where(meandepth == 0., meandepth)

        def woaMeanOMZdepth(nc, keys):
            o2 = np.ma.array(nc.variables[keys[0]][:].squeeze() * 44.661)
            pdepths = np.zeros_like(o2)
            lons = nc.variables['lon'][:]
            lats = nc.variables['lat'][:]
            wdepths = np.abs(nc.variables['depth'][:])

            for y, lat in enumerate(lats):
                for x, lon in enumerate(lons):
                    pdepths[:, y, x] = wdepths
            wmeanDepth = np.ma.masked_where((o2 > omzthreshold) + o2.mask,
                                            pdepths).mean(0).data
            print("woaMeanOMZdepth", wmeanDepth.min(), wmeanDepth.mean(),
                   wmeanDepth.max())
            #assert 0

            if wmeanDepth.max() in [0., 0]: return np.array([
                    1000.,
            ])
            return np.ma.masked_where(wmeanDepth == 0., wmeanDepth)

        av['OMZMeanDepth']['modelcoords'] = medusaCoords
        av['OMZMeanDepth']['datacoords'] = woaCoords

        av['OMZMeanDepth']['modeldetails'] = {
            'name': 'OMZMeanDepth',
            'vars': [
                'OXY',
            ],
            'convert': modelMeanOMZdepth,
            'units': 'm'
        }
        av['OMZMeanDepth']['datadetails'] = {
            'name': 'OMZMeanDepth',
            'vars': [
                'o_an',
            ],
            'convert': woaMeanOMZdepth,
            'units': 'm'
        }

        av['OMZMeanDepth']['layers'] = [
            'layerless',
        ]
        av['OMZMeanDepth']['regions'] = regionList
        av['OMZMeanDepth']['metrics'] = metricList

        av['OMZMeanDepth']['datasource'] = 'WOA'
        av['OMZMeanDepth']['model'] = 'MEDUSA'

        av['OMZMeanDepth']['modelgrid'] = 'eORCA1'
        av['OMZMeanDepth']['gridFile'] = paths.orcaGridfn
        av['OMZMeanDepth']['dimensions'] = 2

    if 'OMZThickness' in analysisKeys or 'OMZThickness50' in analysisKeys:
        if 'OMZThickness' in analysisKeys and 'OMZThickness50' in analysisKeys:
            print("Only run one of these at a time")
            assert 0

        if annual:
            av['OMZThickness']['modelFiles'] = sorted(
                glob(paths.ModelFolder_pref + jobID + "/" + jobID +
                     "o_1y_*_ptrc_T.nc"))
            av['OMZThickness']['dataFile'] = WOAFolder + 'woa13_all_o00_01.nc'
        else:
            print("OMZ Thickness not implemented for monthly data")
            assert 0

        nc = dataset(paths.orcaGridfn, 'r')
        thickness = nc.variables['e3t'][:]
        tmask = nc.variables['tmask'][:]
        nc.close()

        if 'OMZThickness' in analysisKeys: omzthreshold = 20.
        if 'OMZThickness50' in analysisKeys: omzthreshold = 50.

        def modelOMZthickness(nc, keys):
            o2 = np.ma.array(nc.variables[keys[0]][:].squeeze())
            totalthick = np.ma.masked_where(
                (o2 > omzthreshold) + o2.mask + (tmask == 0),
                thickness).sum(0).data
            if totalthick.max() in [0., 0]: return np.array([
                    0.,
            ])

            return np.ma.masked_where(totalthick == 0., totalthick)
            #return np.ma.masked_where((arr>omzthreshold) + (arr <0.) + arr.mask,thickness).sum(0)

        def woaOMZthickness(nc, keys):
            o2 = nc.variables[keys[0]][:].squeeze() * 44.661
            pthick = np.zeros_like(o2)
            lons = nc.variables['lon'][:]
            lats = nc.variables['lat'][:]
            zthick = np.abs(nc.variables['depth_bnds'][:, 0] -
                            nc.variables['depth_bnds'][:, 1])

            for y, lat in enumerate(lats):
                for x, lon in enumerate(lons):
                    pthick[:, y, x] = zthick
            totalthick = np.ma.masked_where((o2 > omzthreshold) + o2.mask,
                                            pthick).sum(0).data

            if totalthick.max() in [0., 0]: return np.array([
                    0.,
            ])
            return np.ma.masked_where(totalthick == 0., totalthick)

        av['OMZThickness']['modelcoords'] = medusaCoords
        av['OMZThickness']['datacoords'] = woaCoords

        av['OMZThickness']['modeldetails'] = {
            'name': 'OMZThickness',
            'vars': [
                'OXY',
            ],
            'convert': modelOMZthickness,
            'units': 'm'
        }
        av['OMZThickness']['datadetails'] = {
            'name': 'OMZThickness',
            'vars': [
                'o_an',
            ],
            'convert': woaOMZthickness,
            'units': 'm'
        }

        av['OMZThickness']['layers'] = [
            'layerless',
        ]
        av['OMZThickness']['regions'] = regionList
        av['OMZThickness']['metrics'] = metricList

        av['OMZThickness']['datasource'] = 'WOA'
        av['OMZThickness']['model'] = 'MEDUSA'

        av['OMZThickness']['modelgrid'] = 'eORCA1'
        av['OMZThickness']['gridFile'] = paths.orcaGridfn
        av['OMZThickness']['dimensions'] = 2

    if 'TotalOMZVolume' in analysisKeys or 'TotalOMZVolume50' in analysisKeys:
        if 'TotalOMZVolume' in analysisKeys and 'TotalOMZVolume50' in analysisKeys:
            print("Only run one of these at a time")
            assert 0
        if annual:
            tomzv_dir = os.path.join(paths.ModelFolder_pref, jobID)
            av['TotalOMZVolume']['modelFiles'] = sorted(
                glob(tomzv_dir + "/" + jobID +
                     "o_1y_*_ptrc_T.nc"))
            av['TotalOMZVolume'][
                'dataFile'] = WOAFolder + 'woa13_all_o00_01.nc'
        else:
            print("OMZ volume not implemented for monthly data")
            assert 0

        nc = dataset(paths.orcaGridfn, 'r')
        try:
            pvol = nc.variables['pvol'][:]
            tmask = nc.variables['tmask'][:]
        except:
            tmask = nc.variables['tmask'][:]
            area = nc.variables['e2t'][:] * nc.variables['e1t'][:]
            pvol = nc.variables['e3t'][:] * area
            pvol = np.ma.masked_where(tmask == 0, pvol)
        nc.close()

        if 'TotalOMZVolume' in analysisKeys: omzthreshold = 20.
        if 'TotalOMZVolume50' in analysisKeys: omzthreshold = 50.

        def modelTotalOMZvol(nc, keys):
            arr = np.ma.array(nc.variables[keys[0]][:].squeeze())
            return np.ma.masked_where(
                (arr > omzthreshold) + pvol.mask + arr.mask, pvol).sum()

        def woaTotalOMZvol(nc, keys):
            arr = np.ma.array(nc.variables[keys[0]][:].squeeze() * 44.661)
            #area = np.zeros_like(arr[0])
            pvol = np.zeros_like(arr)
            #np.ma.masked_wjhere(arr.mask + (arr <0.)+(arr >1E10),np.zeros_like(arr))
            lons = nc.variables['lon'][:]
            lats = nc.variables['lat'][:]
            #lonbnds = nc.variables['lon_bnds'][:]
            latbnds = nc.variables['lat_bnds'][:]
            zthick = np.abs(nc.variables['depth_bnds'][:, 0] -
                            nc.variables['depth_bnds'][:, 1])

            for y, lat in enumerate(lats):
                area = ukp.Area([latbnds[y, 0], 0.], [latbnds[y, 1], 1.])
                for z, thick in enumerate(zthick):
                    pvol[z, y, :] = np.ones_like(lons) * area * thick

            return np.ma.masked_where(
                arr.mask + (arr > omzthreshold) + (arr < 0.), pvol).sum()

        av['TotalOMZVolume']['modelcoords'] = medusaCoords
        av['TotalOMZVolume']['datacoords'] = woaCoords

        av['TotalOMZVolume']['modeldetails'] = {
            'name': 'TotalOMZVolume',
            'vars': [
                'OXY',
            ],
            'convert': modelTotalOMZvol,
            'units': 'm^3'
        }
        av['TotalOMZVolume']['datadetails'] = {
            'name': 'TotalOMZVolume',
            'vars': [
                'o_an',
            ],
            'convert': woaTotalOMZvol,
            'units': 'm^3'
        }

        av['TotalOMZVolume']['layers'] = [
            'layerless',
        ]
        av['TotalOMZVolume']['regions'] = [
            'regionless',
        ]
        av['TotalOMZVolume']['metrics'] = [
            'metricless',
        ]

        av['TotalOMZVolume']['datasource'] = 'WOA'
        av['TotalOMZVolume']['model'] = 'MEDUSA'

        av['TotalOMZVolume']['modelgrid'] = 'eORCA1'
        av['TotalOMZVolume']['gridFile'] = paths.orcaGridfn
        av['TotalOMZVolume']['dimensions'] = 1

    if 'VolumeMeanOxygen' in analysisKeys:
        name = 'VolumeMeanOxygen'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'ptrc_T',
                                                    paths.ModelFolder_pref,
                                                    annual)
        av[name]['dataFile'] = ''
        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = woaCoords

        nc = dataset(paths.orcaGridfn, 'r')
        try:
            pvol = nc.variables['pvol'][:]
            area = nc.variables['area'][:]
            gmttmask = nc.variables['tmask'][:]
        except:
            gmttmask = nc.variables['tmask'][:]
            area = nc.variables['e2t'][:] * nc.variables['e1t'][:]
            pvol = nc.variables['e3t'][:] * area
            pvol = np.ma.masked_where(gmttmask == 0, pvol)
        nc.close()

        def sumMeanLandMask(nc, keys):
            #### works like no change, but applies a mask.
            ox = np.ma.array(nc.variables[keys[0]][:].squeeze())
            ox = np.ma.masked_where((gmttmask == 0) + (ox.mask), ox)

            try:
                vol = np.ma.masked_where(
                    ox.mask,
                    nc('thkcello')[:].squeeze() *
                    nc('area')[:])  # preferentially use in file volume.
            except:
                vol = np.ma.masked_where(ox.mask, pvol)

            return ((ox * vol).sum(0) / vol.sum(0))  #*(area/area.sum())

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                'OXY',
            ],
            'convert': sumMeanLandMask,
            'units': 'mmol O2/m^3'
        }
        av[name]['datadetails'] = {'name': '', 'units': ''}
        #av[name]['datadetails']  	= {'name': name, 'vars':['t_an',], 'convert': ukp.NoChange,'units':'degrees C'}

        oxregions = [
            'Global',
            'ignoreInlandSeas',
            'Equator10',
            'AtlanticSOcean',
            'SouthernOcean',
            'ArcticOcean',
            'Remainder',
            'NorthernSubpolarAtlantic',
            'NorthernSubpolarPacific',
        ]  #'WeddelSea']
        oxregions.extend(OMZRegions)

        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = oxregions
        av[name]['metrics'] = [
            'wcvweighted',
        ]
        av[name]['datasource'] = ''
        av[name]['model'] = 'NEMO'
        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 2

    if 'AOU' in analysisKeys:
        name = 'AOU'
        if annual:
            av[name]['modelFiles'] = listModelDataFiles(
                jobID, 'ptrc_T', paths.ModelFolder_pref, annual)
            av[name]['dataFile'] = ''  #WOAFolder+'woa13_all_o00_01.nc'

        def modelAOU(nc, keys):
            o2 = nc.variables[keys[0]][:]

            ncpath = nc.filename
            print(ncpath)

            newpath = ncpath.replace('ptrc_T', 'grid_T')

            print("modelAOU:", ncpath, newpath)
            nc2 = dataset(newpath, 'r')
            print("Loaded", newpath)
            temp = nc2.variables[ukesmkeys['temp3d']][:]
            sal = nc2.variables[ukesmkeys['sal3d']][:]
            return AOU(temp, sal, o2)

        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = woaCoords

        av[name]['modeldetails'] = {
            'name': name,
            'vars': ['OXY', ukesmkeys['temp3d'], ukesmkeys['sal3d']],
            'convert': modelAOU,
            'units': 'mmol O2/m^3'
        }
        av[name]['datadetails'] = {
            'name': '',
            'units': '',
        }

        av[name]['layers'] = layerList
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList

        av[name]['datasource'] = ''
        av[name]['model'] = 'MEDUSA'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 3

    if 'GlobalExportRatio' in analysisKeys:

        def calcExportRatio(nc, keys):
            a = (nc.variables['SDT__100'][:] +
                 nc.variables['FDT__100'][:]).sum() / (
                     nc.variables['PRD'][:] + nc.variables['PRN'][:]).sum()
            #a = np.ma.masked_where(a>1.01, a)
            return a

        name = 'ExportRatio'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'diad_T',
                                                    paths.ModelFolder_pref,
                                                    annual)

        av[name]['dataFile'] = ""
        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = maredatCoords
        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                'SDT__100',
                'FDT__100',
                'PRD',
                'PRN',
            ],
            'convert': calcExportRatio,
            'units': ''
        }
        av[name]['datadetails'] = {
            'name': '',
            'units': '',
        }
        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = [
            'regionless',
        ]
        av[name]['metrics'] = [
            'metricless',
        ]
        av[name]['datasource'] = ''
        av[name]['model'] = 'MEDUSA'
        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 1

    if 'LocalExportRatio' in analysisKeys:

        def calcExportRatio(nc, keys):
            a = (nc.variables['SDT__100'][:] + nc.variables['FDT__100'][:]) / (
                nc.variables['PRD'][:] + nc.variables['PRN'][:])
            a = np.ma.masked_where(a > 1.01, a)
            return a

        name = 'LocalExportRatio'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'diad_T',
                                                    paths.ModelFolder_pref,
                                                    annual)

        av[name]['dataFile'] = ""
        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = maredatCoords
        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                'SDT__100',
                'FDT__100',
                'PRD',
                'PRN',
            ],
            'convert': calcExportRatio,
            'units': ''
        }
        av[name]['datadetails'] = {
            'name': '',
            'units': '',
        }
        av[name]['layers'] = [
            'layerless',
        ]  #'100m','200m','Surface - 1000m','Surface - 300m',]#'depthint']
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList
        av[name]['datasource'] = ''
        av[name]['model'] = 'MEDUSA'
        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 2


    if 'GlobalMeanTemperature_700' in analysisKeys:
        name = 'GlobalMeanTemperature_700'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_T',
                                                    paths.ModelFolder_pref,
                                                    annual)

        #av[name]['modelFiles']  = listModelDataFiles(jobID, 'grid_T', paths.ModelFolder_pref, annual)
        av[name]['dataFile'] = ''
        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = woaCoords

        nc = dataset(paths.orcaGridfn, 'r')
        try:
            pvol = nc.variables['pvol'][:]
            gmttmask = nc.variables['tmask'][:]
        except:
            gmttmask = nc.variables['tmask'][:]
            area = nc.variables['e2t'][:] * nc.variables['e1t'][:]
            pvol = nc.variables['e3t'][:] * area
            pvol = np.ma.masked_where(gmttmask == 0, pvol)
        nc.close()

        def sumMeanLandMask(nc, keys):
            #### works like no change, but applies a mask.
            temp = np.ma.array(nc.variables[keys[0]][:].squeeze())
            temp = np.ma.masked_where((gmttmask == 0) + (temp.mask), temp)
            temp.mask[43:, :, :] = True
            #epth = nc.variables[medusaCoords['z']]
            vol = np.ma.masked_where(
                temp.mask,
                nc('thkcello')[:].squeeze() *
                nc('area')[:])  # preferentially use in file volume.
            return (temp * vol).sum() / (vol.sum())

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                ukesmkeys['temp3d'],
            ],
            'convert': sumMeanLandMask,
            'units': 'degrees C'
        }
        av[name]['datadetails'] = {'name': '', 'units': ''}
        #av[name]['datadetails']        = {'name': name, 'vars':['t_an',], 'convert': ukp.NoChange,'units':'degrees C'}

        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = [
            'regionless',
        ]
        av[name]['metrics'] = [
            'metricless',
        ]
        av[name]['datasource'] = ''
        av[name]['model'] = 'NEMO'
        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 1

    if 'GlobalMeanTemperature_2000' in analysisKeys:
        name = 'GlobalMeanTemperature_2000'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_T',
                                                    paths.ModelFolder_pref,
                                                    annual)

        #av[name]['modelFiles']  = listModelDataFiles(jobID, 'grid_T', paths.ModelFolder_pref, annual)
        av[name]['dataFile'] = ''
        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = woaCoords

        nc = dataset(paths.orcaGridfn, 'r')
        try:
            pvol = nc.variables['pvol'][:]
            gmttmask = nc.variables['tmask'][:]
        except:
            gmttmask = nc.variables['tmask'][:]
            area = nc.variables['e2t'][:] * nc.variables['e1t'][:]
            pvol = nc.variables['e3t'][:] * area
            pvol = np.ma.masked_where(gmttmask == 0, pvol)
        nc.close()

        def sumMeanLandMask(nc, keys):
            #### works like no change, but applies a mask.
            temp = np.ma.array(nc.variables[keys[0]][:].squeeze())
            temp = np.ma.masked_where((gmttmask == 0) + (temp.mask), temp)
            temp.mask[54:, :, :] = True
            #epth = nc.variables[medusaCoords['z']]
            vol = np.ma.masked_where(
                temp.mask,
                nc('thkcello')[:].squeeze() *
                nc('area')[:])  # preferentially use in file volume.
            return (temp * vol).sum() / (vol.sum())

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                ukesmkeys['temp3d'],
            ],
            'convert': sumMeanLandMask,
            'units': 'degrees C'
        }
        av[name]['datadetails'] = {'name': '', 'units': ''}
        #av[name]['datadetails']        = {'name': name, 'vars':['t_an',], 'convert': ukp.NoChange,'units':'degrees C'}

        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = [
            'regionless',
        ]
        av[name]['metrics'] = [
            'metricless',
        ]
        av[name]['datasource'] = ''
        av[name]['model'] = 'NEMO'
        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 1

    if 'VolumeMeanTemperature' in analysisKeys:
        name = 'VolumeMeanTemperature'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_T',
                                                    paths.ModelFolder_pref,
                                                    annual)
        av[name]['dataFile'] = ''
        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = woaCoords

        nc = dataset(paths.orcaGridfn, 'r')
        try:
            pvol = nc.variables['pvol'][:]
            area = nc.variables['area'][:]
            gmttmask = nc.variables['tmask'][:]
        except:
            gmttmask = nc.variables['tmask'][:]
            area = nc.variables['e2t'][:] * nc.variables['e1t'][:]
            pvol = nc.variables['e3t'][:] * area
            pvol = np.ma.masked_where(gmttmask == 0, pvol)
        nc.close()

        def sumMeanLandMask(nc, keys):
            #### works like no change, but applies a mask.
            temp = np.ma.array(nc.variables[keys[0]][:].squeeze())
            temp = np.ma.masked_where((gmttmask == 0) + (temp.mask), temp)

            #try:
            vol = np.ma.masked_where(
                temp.mask,
                nc('thkcello')[:].squeeze() *
                nc('area')[:])  # preferentially use in file volume.
            #except: vol = np.ma.masked_where(temp.mask, pvol)

            #vol = np.ma.masked_where(temp.mask, pvol)
            return ((temp * vol).sum(0) / vol.sum(0))  #*(area/area.sum())
            #return (((temp*vol).sum(0)/(vol.sum(0))) * (vol.sum(0)/vol.sum()))#.sum()

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                ukesmkeys['temp3d'],
            ],
            'convert': sumMeanLandMask,
            'units': 'degrees C'
        }
        av[name]['datadetails'] = {'name': '', 'units': ''}
        #av[name]['datadetails']  	= {'name': name, 'vars':['t_an',], 'convert': ukp.NoChange,'units':'degrees C'}

        vmtregions = [
            'Global', 'ignoreInlandSeas', 'Equator10', 'AtlanticSOcean',
            'SouthernOcean', 'ArcticOcean', 'Remainder',
            'NorthernSubpolarAtlantic', 'NorthernSubpolarPacific', 'WeddelSea'
        ]
        vmtregions.extend(PierceRegions)

        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = vmtregions
        av[name]['metrics'] = [
            'wcvweighted',
        ]
        av[name]['datasource'] = ''
        av[name]['model'] = 'NEMO'
        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 2

    if 'scvoltot' in analysisKeys:
        name = 'scvoltot'
        files = listModelDataFiles(jobID, 'scalar', paths.ModelFolder_pref,
                                   annual)
        if len(files) > 0:
            av[name]['modelFiles'] = files
            av[name]['dataFile'] = ''
            av[name]['modelcoords'] = {
                'lat': False,
                'lon': False,
                'z': False,
                't': 'time_centered',
            }
            av[name]['datacoords'] = woaCoords
            av[name]['modeldetails'] = {
                'name': name,
                'vars': [
                    'scvoltot',
                ],
                'convert': ukp.NoChange,
                'units': 'm3'
            }
            av[name]['datadetails'] = {'name': '', 'units': ''}
            av[name]['layers'] = [
                'layerless',
            ]
            av[name]['regions'] = [
                'regionless',
            ]
            av[name]['metrics'] = [
                'metricless',
            ]
            av[name]['datasource'] = ''
            av[name]['model'] = 'NEMO'
            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 1

    if 'soga' in analysisKeys:
        name = 'soga'
        files = listModelDataFiles(jobID, 'scalar', paths.ModelFolder_pref,
                                   annual)
        if len(files) > 0:
            av[name]['modelFiles'] = files
            av[name]['dataFile'] = ''
            av[name]['modelcoords'] = {
                'lat': False,
                'lon': False,
                'z': False,
                't': 'time_centered',
            }
            av[name]['datacoords'] = woaCoords
            av[name]['modeldetails'] = {
                'name': name,
                'vars': [
                    'soga',
                ],
                'convert': ukp.NoChange,
                'units': 'psu'
            }
            av[name]['datadetails'] = {'name': '', 'units': ''}
            av[name]['layers'] = [
                'layerless',
            ]
            av[name]['regions'] = [
                'regionless',
            ]
            av[name]['metrics'] = [
                'metricless',
            ]
            av[name]['datasource'] = ''
            av[name]['model'] = 'NEMO'
            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 1

    if 'thetaoga' in analysisKeys:
        name = 'thetaoga'
        files = listModelDataFiles(jobID, 'scalar', paths.ModelFolder_pref,
                                   annual)
        if len(files) > 0:
            av[name]['modelFiles'] = files
            av[name]['dataFile'] = ''
            av[name]['modelcoords'] = {
                'lat': False,
                'lon': False,
                'z': False,
                't': 'time_centered',
            }
            av[name]['datacoords'] = woaCoords
            av[name]['modeldetails'] = {
                'name': name,
                'vars': [
                    'thetaoga',
                ],
                'convert': ukp.NoChange,
                'units': 'degrees C'
            }
            av[name]['datadetails'] = {'name': '', 'units': ''}
            av[name]['layers'] = [
                'layerless',
            ]
            av[name]['regions'] = [
                'regionless',
            ]
            av[name]['metrics'] = [
                'metricless',
            ]
            av[name]['datasource'] = ''
            av[name]['model'] = 'NEMO'
            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 1

    if 'scalarHeatContent' in analysisKeys:
        name = 'scalarHeatContent'
        files = listModelDataFiles(jobID, 'scalar', paths.ModelFolder_pref,
                                   annual)

        def scalarFunction(nc, keys):
            rau0 = 1026.  #kg / m3	#		volume reference mass,
            rcp = 3991.8679571196299  #J / (K * kg)	ocean specific heat capacity
            thetaoga = nc(
                'thetaoga'
            )[:]  #		global average seawater potential temperature
            scvoltot = nc('scvoltot')[:]  # m3		ocean volume
            #                	print nc('time_centered'), thetaoga ,scvoltot , rau0 , rcp, thetaoga * scvoltot * rau0 * rcp
            #			assert 0
            return thetaoga * scvoltot * rau0 * rcp * 1e-24

        if len(files) > 0:
            av[name]['modelFiles'] = files
            av[name]['dataFile'] = ''
            av[name]['modelcoords'] = {
                'lat': False,
                'lon': False,
                'z': False,
                't': 'time_centered',
            }
            av[name]['datacoords'] = woaCoords
            av[name]['modeldetails'] = {
                'name': name,
                'vars': [
                    'thetaoga',
                    'scvoltot',
                ],
                'convert': scalarFunction,
                'units': 'YottaJoules'
            }
            av[name]['datadetails'] = {'name': '', 'units': ''}
            av[name]['layers'] = [
                'layerless',
            ]
            av[name]['regions'] = [
                'regionless',
            ]
            av[name]['metrics'] = [
                'metricless',
            ]
            av[name]['datasource'] = ''
            av[name]['model'] = 'NEMO'
            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 1

    if 'HeatFlux' in analysisKeys:
        name = 'HeatFlux'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_T',
                                                    paths.ModelFolder_pref,
                                                    annual)
        av[name]['dataFile'] = ''
        av[name]['modelcoords'] = medusaCoords
        #av[name]['datacoords']          = takahashiCoords
        av[name]['modeldetails'] = {
            'name': 'HeatFlux',
            'vars': [
                'hfds',
            ],
            'convert': ukp.NoChange,
            'units': 'W/m2'
        }
        av[name]['datadetails'] = {'name': '', 'units': ''}
        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList
        av[name]['datasource'] = ''
        av[name]['model'] = 'MEDUSA'
        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 2

    if 'TotalHeatFlux' in analysisKeys:
        name = 'TotalHeatFlux'
        nc = dataset(paths.orcaGridfn, 'r')
        try:
            ncarea = nc.variables['area'][:]
            surfmask = nc.variables['tmask'][:]
        except:
            surfmask = nc.variables['tmask'][0]
            ncarea = nc.variables['e2t'][:] * nc.variables['e1t'][:]
        nc.close()

        def areatotal(nc, keys):
            if 'area' in list(nc.variables.keys()):
                area = nc.variables['area'][:]
            else:
                area = ncarea
            flux = np.ma.array(nc.variables[keys[0]][:].squeeze()) * ncarea
            flux = np.ma.masked_where((surfmask == 0) + (flux.mask), flux)
            return flux.sum() * 1e-12

        av[name]['modelcoords'] = medusaCoords
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_T',
                                                    paths.ModelFolder_pref,
                                                    annual)
        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                'hfds',
            ],
            'convert': areatotal,
            'units': 'TW'
        }
        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = [
            'regionless',
        ]
        av[name]['metrics'] = [
            'metricless',
        ]
        av[name]['model'] = 'NEMO'
        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 2
        av[name]['datacoords'] = {'name': '', 'units': ''}
        av[name]['datadetails'] = {'name': '', 'units': ''}
        av[name]['dataFile'] = ''
        av[name]['datasource'] = ''

    if 'ERSST' in analysisKeys:
        name = 'ERSST'
        av[name]['modelFiles'] = [
            "/group_workspaces/jasmin4/esmeval/example_data/bgc/ERSST.v4/sst.mnmean.v4.nc",
        ]
        av[name]['dataFile'] = ''

        ERSSTCoords = {
            't': 'time',
            'z': '',
            'lat': 'lat',
            'lon': 'lon',
            'cal': 'standard',
            'tdict': ['ZeroToZero']
        }

        av[name]['modelcoords'] = ERSSTCoords
        av[name]['datacoords'] = woaCoords

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                'sst',
            ],
            'convert': ukp.NoChange,
            'units': 'degrees C'
        }
        av[name]['datadetails'] = {'name': name, 'vars': [], 'units': ''}

        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList

        av[name]['datasource'] = ''
        av[name]['model'] = 'ERSST'

        av[name]['modelgrid'] = 'ERSST_2g'
        av[name][
            'gridFile'] = '/group_workspaces/jasmin4/esmeval/example_data/bgc/ERSST.v4/ERSST_sst_grid.nc'
        av[name]['dimensions'] = 2

    if 'IcelessMeanSST' in analysisKeys:
        name = 'IcelessMeanSST'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_T',
                                                    paths.ModelFolder_pref,
                                                    annual)
        av[name]['dataFile'] = ''

        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = woaCoords

        nc = dataset(paths.orcaGridfn, 'r')
        icetmask = nc.variables['tmask'][:]
        area_full = nc.variables['e2t'][:] * nc.variables['e1t'][:]
        nc.close()

        def calcIcelessMeanSST(nc, keys):
            #### works like no change, but applies a mask.
            icecov = nc.variables['soicecov'][:].squeeze()
            sst = np.ma.array(nc.variables[ukesmkeys['temp3d']][:,
                                                                0, ].squeeze())
            sst = np.ma.masked_where(
                (icetmask[0] == 0) + (icecov > 0.15) + sst.mask, sst)
            area = np.ma.masked_where(sst.mask, area_full)
            val = (sst * area).sum() / (area.sum())
            print("calcIcelessMeanSST", sst.shape, area.shape, val)
            return val

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                'soicecov',
                ukesmkeys['temp3d'],
            ],
            'convert': calcIcelessMeanSST,
            'units': 'degrees C'
        }
        av[name]['datadetails'] = {'name': '', 'units': ''}
        #av[name]['datadetails']  	= {'name': name, 'vars':['t_an',], 'convert': ukp.NoChange,'units':'degrees C'}

        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = [
            'regionless',
        ]
        av[name]['metrics'] = [
            'metricless',
        ]

        av[name]['datasource'] = ''
        av[name]['model'] = 'NEMO'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 1

        if 'quickSST' in analysisKeys:
            name = 'quickSST'
            av[name]['modelFiles'] = listModelDataFiles(
                jobID, 'grid_T', paths.ModelFolder_pref, annual)

            nc = dataset(paths.orcaGridfn, 'r')
            ssttmask = nc.variables['tmask'][0]
            area = nc.variables['e2t'][:] * nc.variables['e1t'][:]
            area = np.ma.masked_where(ssttmask == 0, area)
            nc.close()

            def meanLandMask(nc, keys):
                #### works like no change, but applies a mask.
                #print "meanLandMask:",ssttmask.shape,nc.variables[keys[0]][0,0].shape
                temperature = np.ma.masked_where(
                    ssttmask == 0, nc.variables[keys[0]][0, 0].squeeze())
                print("meanLandMask:", nc.variables['time_counter'][:],
                       temperature.mean(),
                       (temperature * area).sum() / (area.sum()))
                return (temperature * area).sum() / (area.sum())

            if annual:
                #av[name]['modelFiles']  	= sorted(glob(paths.ModelFolder_pref+jobID+"/"+jobID+"o_1y_*_grid_T.nc"))
                av[name]['dataFile'] = ''  #WOAFolder+'woa13_decav_t00_01v2.nc'
            else:
                #av[name]['modelFiles']  	= sorted(glob(paths.ModelFolder_pref+jobID+"/"+jobID+"o_1m_*_grid_T.nc"))
                av[name][
                    'dataFile'] = ''  #WOAFolder+'temperature_monthly_1deg.nc'

            av[name]['modelcoords'] = medusaCoords
            av[name]['datacoords'] = woaCoords

            av[name]['modeldetails'] = {
                'name': name,
                'vars': [
                    ukesmkeys['temp3d'],
                ],
                'convert': meanLandMask,
                'units': 'degrees C'
            }
            av[name]['datadetails'] = {'name': '', 'units': ''}

            av[name]['layers'] = [
                'layerless',
            ]
            av[name]['regions'] = [
                'regionless',
            ]
            av[name]['metrics'] = [
                'metricless',
            ]

            av[name]['datasource'] = ''
            av[name]['model'] = 'NEMO'

            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 1


    if 'ZonalCurrent' in analysisKeys:
        name = 'ZonalCurrent'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_U',
                                                    paths.ModelFolder_pref,
                                                    annual)
        if annual:
            av[name]['dataFile'] = paths.GODASFolder + 'ucur.clim.nc'

        av[name]['modelcoords'] = medusaUCoords
        av[name]['datacoords'] = godasCoords
        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                ukesmkeys['u3d'],
            ],
            'convert': applyLandMask1e3,
            'units': 'mm/s'
        }
        av[name]['datadetails'] = {
            'name': name,
            'vars': [
                'ucur',
            ],
            'convert': ukp.NoChange,
            'units': 'mm/s'
        }

        av[name]['layers'] = layerList
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList

        av[name]['datasource'] = 'GODAS'
        av[name]['model'] = 'NEMO'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = os.path.join(paths.bgcval2_repo, 'bgcval2/data/eORCA1_gridU_mesh.nc')
        av[name]['dimensions'] = 3

    if 'MeridionalCurrent' in analysisKeys:
        name = 'MeridionalCurrent'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_V',
                                                    paths.ModelFolder_pref,
                                                    annual)
        if annual:
            av[name]['dataFile'] = paths.GODASFolder + 'vcur.clim.nc'

        av[name]['modelcoords'] = medusaVCoords
        av[name]['datacoords'] = godasCoords

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                ukesmkeys['v3d'],
            ],
            'convert': applyLandMask1e3,
            'units': 'mm/s'
        }
        av[name]['datadetails'] = {
            'name': name,
            'vars': [
                'vcur',
            ],
            'convert': ukp.NoChange,
            'units': 'mm/s'
        }

        av[name]['layers'] = layerList
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList

        av[name]['datasource'] = 'GODAS'
        av[name]['model'] = 'NEMO'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = os.path.join(paths.bgcval2_repo, 'bgcval2/data/eORCA1_gridV_mesh.nc')
        av[name]['dimensions'] = 3

    if 'VerticalCurrent' in analysisKeys:
        name = 'VerticalCurrent'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_W',
                                                    paths.ModelFolder_pref,
                                                    annual)
        if annual:
            av[name]['dataFile'] = paths.GODASFolder + 'dzdt.clim.nc'

        av[name]['modelcoords'] = medusaWCoords
        av[name]['datacoords'] = godasCoords

        def applyLandMask1e6(nc, keys):
            return applyLandMask(nc, keys) * 1000000.

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                ukesmkeys['w3d'],
            ],
            'convert': applyLandMask1e6,
            'units': 'um/s'
        }
        av[name]['datadetails'] = {
            'name': name,
            'vars': [
                'dzdt',
            ],
            'convert': ukp.NoChange,
            'units': 'um/s'
        }

        vregions = regionList
        #                vregions.extend(['NordicSea', 'LabradorSea', 'NorwegianSea'])

        av[name]['layers'] = layerList
        av[name]['regions'] = vregions
        av[name]['metrics'] = metricList

        av[name]['datasource'] = 'GODAS'
        av[name]['model'] = 'NEMO'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = os.path.join(paths.bgcval2_repo, 'bgcval2/data/eORCA1_gridW_mesh.nc')
        av[name]['dimensions'] = 3

    if 'WindStress' in analysisKeys:
        name = 'WindStress'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_U',
                                                    paths.ModelFolder_pref,
                                                    annual)
        av[name]['dataFile'] = ''

        #paths.GODASFolder+'ucur.clim.nc'

        def calcwind(nc, keys):
            taux = applySurfaceMask(nc, [
                'sozotaux',
            ])

            ncpath = nc.filename
            newpath = ncpath.replace('grid_U', 'grid_V')

            nc2 = dataset(newpath, 'r')
            print("Loaded", newpath)
            tauy = applySurfaceMask(nc2, [
                'sometauy',
            ])

            return np.ma.sqrt(taux * taux + tauy * tauy)

        av[name]['modelcoords'] = medusaUCoords
        av[name]['datacoords'] = godasCoords

        av[name]['modeldetails'] = {
            'name': name,
            'vars': ['sozotaux', 'sometauy'],
            'convert': calcwind,
            'units': 'N/m2'
        }
        av[name]['datadetails'] = {'name': '', 'units': ''}

        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList

        av[name]['datasource'] = ''
        av[name]['model'] = 'NEMO'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = os.path.join(paths.bgcval2_repo, 'bgcval2./data/eORCA1_gridU_mesh.nc')
        av[name]['dimensions'] = 2

    #####
    # North Atlantic Salinity
    #sowaflup = "Net Upward Water Flux" ;
    #sohefldo = "Net Downward Heat Flux" ;
    #sofmflup = "Water flux due to freezing/melting" ;
    #sosfldow = "Downward salt flux" ;

    naskeys = [
        'sowaflup',
        'sohefldo',
        'sofmflup',
        'sosfldow',
        'soicecov',
        'sossheig',
    ]
    if len(set(naskeys).intersection(set(analysisKeys))):
        for name in naskeys:
            if name not in analysisKeys: continue

            #nc = dataset(paths.orcaGridfn,'r')
            #area = nc.variables['e2t'][:] * nc.variables['e1t'][:]
            #tmask = nc.variables['tmask'][0,:,:]
            #lat = nc.variables['nav_lat'][:,:]
            #nc.close()

            nas_files = listModelDataFiles(jobID, 'grid_T',
                                           paths.ModelFolder_pref, annual)
            nc = dataset(nas_files[0], 'r')
            if name not in list(nc.variables.keys()):
                print("analysis_timeseries.py:\tWARNING: ", name,
                       "is not in the model file.")
                continue
            av[name]['modelFiles'] = nas_files
            av[name]['dataFile'] = ''

            av[name]['modelcoords'] = medusaCoords
            av[name]['datacoords'] = medusaCoords

            nasUnits = {
                'sowaflup': "kg/m2/s",
                'sohefldo': "W/m2",
                'sofmflup': "kg/m2/s",
                'sosfldow': "PSU/m2/s",
                'soicecov': '',
                'sossheig': 'm',
            }

            av[name]['modeldetails'] = {
                'name': name[:],
                'vars': [
                    name[:],
                ],
                'convert': applySurfaceMask,
                'units': nasUnits[name][:]
            }

            #av[name]['regions'] 		=  ['NordicSea', 'LabradorSea', 'NorwegianSea','Global', ]
            av[name]['regions'] = [
                'Global',
            ]

            av[name]['datadetails'] = {
                'name': '',
                'units': '',
            }
            av[name]['layers'] = [
                'layerless',
            ]
            av[name]['metrics'] = metricList
            av[name]['datasource'] = ''
            av[name]['model'] = 'NEMO'
            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 2

    naskeys = [
        'max_soshfldo',
    ]  #'sohefldo','sofmflup','sosfldow','soicecov']
    if len(set(naskeys).intersection(set(analysisKeys))):
        for name in naskeys:
            if name not in analysisKeys: continue

            cutname = name[:].replace('max_', '')
            #nc = dataset(paths.orcaGridfn,'r')
            #area = nc.variables['e2t'][:] * nc.variables['e1t'][:]
            #tmask = nc.variables['tmask'][0,:,:]
            #lat = nc.variables['nav_lat'][:,:]
            #nc.close()

            nas_files = listModelDataFiles(jobID, 'grid_T',
                                           paths.ModelFolder_pref, annual)
            nc = dataset(nas_files[0], 'r')
            if cutname not in list(nc.variables.keys()):
                print("analysis_timeseries.py:\tWARNING: ", cutname,
                       "is not in the model file.")
                continue
            av[name]['modelFiles'] = nas_files
            av[name]['dataFile'] = ''

            av[name]['modelcoords'] = medusaCoords
            av[name]['datacoords'] = medusaCoords

            maxUnits = {
                'max_soshfldo': "W/m2",
            }

            def getMax(nc, keys):
                return applySurfaceMask(nc, keys).max()

            av[name]['modeldetails'] = {
                'name': name[:],
                'vars': [
                    cutname,
                ],
                'convert': getMax,
                'units': maxUnits[name][:]
            }

            av[name]['regions'] = [
                'Global',
            ]  # 'LabradorSea', 'NorwegianSea', ]

            av[name]['datadetails'] = {
                'name': '',
                'units': '',
            }
            av[name]['layers'] = [
                'layerless',
            ]
            av[name]['metrics'] = [
                'metricless',
            ]
            av[name]['datasource'] = ''
            av[name]['model'] = 'NEMO'
            av[name]['modelgrid'] = 'eORCA1'
            av[name]['gridFile'] = paths.orcaGridfn
            av[name]['dimensions'] = 1

    if 'FreshwaterFlux' in analysisKeys:

        #ficeberg + friver + fsitherm + pr + prsn - evs

        adds = ['ficeberg', 'friver', 'fsitherm', 'pr', 'prsn']  # - evs

        def calcFreshflux(nc, keys):
            total = -1. * nc.variables['evs'][:]
            for a in adds:
                total += nc.variables[a][:]
            #a = (nc.variables['SDT__100'][:] +nc.variables['FDT__100'][:])/ (nc.variables['PRD'][:] +nc.variables['PRN'][:] )
            #a = np.ma.masked_where(a>1.01, a)
            return total * 1000000.

        name = 'FreshwaterFlux'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'grid_T',
                                                    paths.ModelFolder_pref,
                                                    annual)

        av[name]['dataFile'] = ""
        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = maredatCoords
        av[name]['modeldetails'] = {
            'name': name,
            'vars': ['ficeberg', 'friver', 'fsitherm', 'pr', 'prsn', 'evs'],
            'convert': calcFreshflux,
            'units': 'mg/m2/s'
        }
        av[name]['datadetails'] = {
            'name': '',
            'units': '',
        }
        av[name]['layers'] = [
            'layerless',
        ]  #'100m','200m','Surface - 1000m','Surface - 300m',]#'depthint']

        freshregions = [
            'Global',
            'ignoreInlandSeas',
            'Equator10',
            'AtlanticSOcean',
            'SouthernOcean',
            'ArcticOcean',
            'Remainder',
            'NorthernSubpolarAtlantic',
            'NorthernSubpolarPacific',
        ]
        freshregions.extend(PierceRegions)
        av[name]['regions'] = freshregions
        av[name]['metrics'] = metricList
        av[name]['datasource'] = ''
        av[name]['model'] = 'MEDUSA'
        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 2

    if 'MaxMonthlyMLD' in analysisKeys or 'MinMonthlyMLD' in analysisKeys:

        #/group_workspaces/jasmin2/ukesm/BGC_data/u-ad371/monthlyMLD/MetOffice_data_licence.325210916
        monthlyFiles = glob(paths.ModelFolder_pref + '/' + jobID +
                            '/monthlyMLD/' + jobID + 'o_1m_*_grid_T.nc')
        if len(monthlyFiles):
            maxmldfiles = mergeMonthlyFiles(monthlyFiles,
                                            outfolder='',
                                            cal=medusaCoords['cal'])

            for name in ['MaxMonthlyMLD', 'MinMonthlyMLD']:
                if name not in analysisKeys: continue

                def mldapplymask(nc, keys):
                    mld = np.ma.array(nc.variables[keys[0]][:]).max(0)
                    mld = np.ma.masked_where((nc.variables[keys[1]][:] == 0.) +
                                             mld.mask + (mld == 1.E9), mld)
                    return mld

                def mldmonthlymask(nc, keys):
                    mld = np.ma.array(np.ma.abs(
                        nc.variables[keys[0]][:])).max(0)
                    mld = np.ma.masked_where(mld.mask + (mld.data > 1.E10),
                                             mld)
                    return mld

                def mldapplymask_min(nc, keys):
                    mld = np.ma.array(nc.variables[keys[0]][:]).min(0)
                    mld = np.ma.masked_where((nc.variables[keys[1]][:] == 0.) +
                                             mld.mask + (mld == 1.E9), mld)
                    return mld

                def mldmonthlymask_min(nc, keys):
                    mld = np.ma.array(np.ma.abs(
                        nc.variables[keys[0]][:])).min(0)
                    mld = np.ma.masked_where(mld.mask + (mld.data > 1.E10),
                                             mld)
                    return mld

                av[name][
                    'modelFiles'] = maxmldfiles  #listModelDataFiles(jobID, 'grid_T', paths.ModelFolder_pref, annual)
                av[name][
                    'dataFile'] = paths.MLDFolder + "mld_DT02_c1m_reg2.0.nc"  #mld_DT02_c1m_reg2.0.nc"

                av[name]['modelcoords'] = medusaCoords
                av[name]['datacoords'] = mldCoords

                if name == 'MaxMonthlyMLD':
                    av[name]['modeldetails'] = {
                        'name': 'mld',
                        'vars': [
                            'somxl010',
                        ],
                        'convert': mldmonthlymask,
                        'units': 'm'
                    }
                    av[name]['datadetails'] = {
                        'name': 'mld',
                        'vars': [
                            'mld',
                            'mask',
                        ],
                        'convert': mldapplymask,
                        'units': 'm'
                    }
                if name == 'MinMonthlyMLD':
                    av[name]['modeldetails'] = {
                        'name': 'mld',
                        'vars': [
                            'somxl010',
                        ],
                        'convert': mldmonthlymask_min,
                        'units': 'm'
                    }
                    av[name]['datadetails'] = {
                        'name': 'mld',
                        'vars': [
                            'mld',
                            'mask',
                        ],
                        'convert': mldapplymask_min,
                        'units': 'm'
                    }

                av[name]['layers'] = [
                    'layerless',
                ]

                av[name]['regions'] = regionList
                av[name]['metrics'] = metricList

                av[name]['datasource'] = 'IFREMER'
                av[name]['model'] = 'NEMO'

                av[name]['modelgrid'] = 'eORCA1'
                av[name]['gridFile'] = paths.orcaGridfn
                av[name]['dimensions'] = 2

        else:
            print("No monthly MLD files found")

    if 'DMS_ARAN' in analysisKeys:
        name = 'DMS'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'diad_T',
                                                    paths.ModelFolder_pref,
                                                    annual)[:]
        if annual:
            av[name]['dataFile'] = paths.DMSDir + 'DMSclim_mean.nc'
        else:
            av[name]['dataFile'] = ''

        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = dmsCoords

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                'DMS_ARAN',
            ],
            'convert': ukp.NoChange,
            'units': 'nmol/L'
        }
        av[name]['datadetails'] = {
            'name': name,
            'vars': [
                'DMS',
            ],
            'convert': ukp.NoChange,
            'units': 'umol/m3'
        }

        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList

        av[name]['datasource'] = 'Lana'
        av[name]['model'] = 'MEDUSA'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 2

    if 'DMS_ANDR' in analysisKeys:
        name = 'DMS'
        av[name]['modelFiles'] = listModelDataFiles(jobID, 'diad_T',
                                                    paths.ModelFolder_pref,
                                                    annual)[:]
        if annual:
            av[name]['dataFile'] = paths.DMSDir + 'DMSclim_mean.nc'
        else:
            av[name]['dataFile'] = ''

        av[name]['modelcoords'] = medusaCoords
        av[name]['datacoords'] = dmsCoords

        av[name]['modeldetails'] = {
            'name': name,
            'vars': [
                'DMS_ANDR',
            ],
            'convert': ukp.NoChange,
            'units': 'nmol/L'
        }
        av[name]['datadetails'] = {
            'name': name,
            'vars': [
                'DMS',
            ],
            'convert': ukp.NoChange,
            'units': 'umol/m3'
        }

        av[name]['layers'] = [
            'layerless',
        ]
        av[name]['regions'] = regionList
        av[name]['metrics'] = metricList

        av[name]['datasource'] = 'Lana'
        av[name]['model'] = 'MEDUSA'

        av[name]['modelgrid'] = 'eORCA1'
        av[name]['gridFile'] = paths.orcaGridfn
        av[name]['dimensions'] = 2



    #####
    # Calling timeseriesAnalysis
    # This is where the above settings is passed to timeseriesAnalysis, for the actual work to begin.
    # We loop over all fiels in the first layer dictionary in the autovificiation, av.
    #
    # Once the timeseriesAnalysis has completed, we save all the output shelves in a dictionary.
    # At the moment, this dictioary is not used, but we could for instance open the shelve to highlight specific data,
    #	(ie, andy asked to produce a table showing the final year of data.

    shelves = {}
    shelves_insitu = {}
    for name in list(av.keys()):
        print("---------------------------------------------------------------")
        print("analysis_timeseries:\tBeginning timeseriesAnalysis:", name)

        if 'modelFiles' not in av[name]:
            print(
                "analysis_timeseries:\tWARNING:\tmodel files are not found:",
                name, av[name]['modelFiles'])
            if strictFileCheck:
                raise FileNotFoundError(f'Model files are not provided for {name}')

        modelfilesexists = [os.path.exists(f) for f in av[name]['modelFiles']]
        if False in modelfilesexists:
            print(
                "analysis_timeseries:\tWARNING:\tModel files do not all exist:",
                av[name]['modelFiles'])
            missing_files = []
            for f in av[name]['modelFiles']:
                if os.path.exists(f):
                    continue
                print(f, 'does not exist')
                missing_files.append(f)
            if strictFileCheck:
                raise FileNotFoundError(f'Model files are provided but not found for {name} : {missing_files}')

        if 'dataFile' in av[name]:
            print(name, 'dataFile', av[name]['dataFile'])
            if not os.path.exists(av[name]['dataFile']):
                print(
                    "analysis_timeseries:\tWARNING:\tdata file is not found:",
                    av[name]['dataFile'])
                if strictFileCheck:
                    raise FileNotFoundError(f'Obs data files are provided but not found for {name} : {av[name]["dataFile"]}')

        tsa = timeseriesAnalysis(
            av[name]['modelFiles'],
            av[name].get('dataFile', None),
            dataType=name,
            modelcoords=av[name]['modelcoords'],
            modeldetails=av[name]['modeldetails'],
            datacoords=av[name].get('datacoords', None),
            datadetails=av[name].get('datadetails', None),
            datasource=av[name].get('datasource', None),
            model=av[name].get('model', None),
            jobID=jobID,
            layers=av[name]['layers'],
            regions=av[name]['regions'],
            metrics=av[name]['metrics'],
            workingDir=shelvedir,
            imageDir=imagedir,
            grid=av[name]['modelgrid'],
            gridFile=av[name]['gridFile'],
            clean=clean,
        )

        #####
        # Profile plots
        if av[name]['dimensions'] == 3:
            continue
            profa = profileAnalysis(
                av[name]['modelFiles'],
                av[name]['dataFile'],
                dataType=name,
                modelcoords=av[name]['modelcoords'],
                modeldetails=av[name]['modeldetails'],
                datacoords=av[name]['datacoords'],
                datadetails=av[name]['datadetails'],
                datasource=av[name]['datasource'],
                model=av[name]['model'],
                jobID=jobID,
                layers=list(
                    np.arange(102)
                ),  # 102 because that is the number of layers in WOA Oxygen
                regions=av[name]['regions'],
                metrics=[
                    'mean',
                ],
                workingDir=shelvedir,
                imageDir=imagedir,
                grid=av[name]['modelgrid'],
                gridFile=av[name]['gridFile'],
                clean=False,
            )


def singleTimeSeriesProfile(jobID, key):

    FullDepths = [
        'T',
        'S',
        'Chl_pig',
        'N',
        'Si',
        'O2',
        'Alk',
        'DIC',
        'Iron',
    ]
    if key in FullDepths:
        analysis_timeseries(
            jobID=jobID,
            suites=[
                key,
            ],
        )


def singleTimeSeries(
    jobID,
    key,
):
    #	try:
    analysis_timeseries(jobID=jobID,
                        suites=[
                            key,
                        ],
                        strictFileCheck=False)  #clean=1)


def get_args():
    """Parse command line arguments. """
    accepted_keys = ['kmf', 'physics','bgc', 'debug', 'spinup', 'salinity', 'fast', 'level1', 'level3', ]

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-j',
                        '--jobID',
                        nargs='+',
                        type=str,
                        default=None,
                        help='One or more UKESM Job IDs (automatically generated by the cylc/rose suite).',
                        required=True,
                        )

    parser.add_argument('-k',
                        '--keys',
                        default=['kmf', 'level1',],
                        nargs='+',
                        type=str,
                        help=''.join(['Runtime keys - each key links to a pre-determined list of variables to analyse. ',
                                      'Keys are: ', ', '.join( accepted_keys)]),
                        required=False,
                        )

    parser.add_argument('-c',
                        '--config-file',
                        default=os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                             'default-bgcval2-config.yml'),
                        help='User configuration file (for paths).',
                        required=False)

    args = parser.parse_args()
    return args


def main():
    """
    Main function that does all the heavy lifting.
    """
    args = get_args()
    jobIDs = args.jobID
    keys = args.keys
    print('Running analysis_imerseries.\tjobID:', jobIDs, '\tkeys:', keys)

    accepted_keys = ['kmf', 'physics','bgc', 'debug', 'spinup', 'salinity', 'fast', 'level1', 'level3', ]
    good_keys = True
    for key in keys:
        if key not in accepted_keys:
            print('Key Argument [',key,'] nor recognised. Accepted keys are:', accepted_keys)
            good_keys= False
    if not good_keys:
        sys.exit(1)

    if os.path.isfile(args.config_file):
        config_user = args.config_file
        print(f"analysis_timeseries: Using user config file {config_user}")
    else:
        print(f"analysis_timeseries: Could not find configuration file {config_user}."
              "Will proceed with defaults.")
        config_user = None

    for jobID in jobIDs:
        analysis_timeseries(
            jobID=jobID,
            suites=keys,
            config_user=config_user
        )


if __name__ == "__main__":
    from ._version import __version__
    print(f'BGCVal2: {__version__}')
    main()
