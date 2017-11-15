import os
import sys
import numpy as np
from collections import OrderedDict

from .mfbase import PackageContainer, ExtFileAction, PackageContainerType, MFFileMgmt
from .data import mfstructure, mfdatautil, mfdata
from .data import mfdataarray, mfdatalist, mfdatascalar
from .coordinates import modeldimensions


class MFBlockHeader(object):
    """
    Represents the header of a block in a MF6 input file

    Parameters
    ----------
    name : string
        block name
    variable_strings : list
        list of strings that appear after the block name
    comment : MFComment
        comment text in the block header

    Attributes
    ----------
    name : string
        block name
    variable_strings : list
        list of strings that appear after the block name
    comment : MFComment
        comment text in the block header
    data_items : list
        list of MFVariable of the variables contained in this block

    Methods
    -------
    write_header : (fd : file object)
        writes block header to file object 'fd'
    write_footer : (fd : file object)
        writes block footer to file object 'fd'
    set_number_of_variables : (num_variables : int)
        sets the number of expected block header variables.  any text found in the block header
        not associated with a block header variable will be assumed to be a comment
    """
    def __init__(self, name, variable_strings, comment, simulation_data=None, path=None):
        self.name = name
        self.variable_strings = variable_strings
        assert((simulation_data is None and path is None) or \
               (simulation_data is not None and path is not None))
        if simulation_data is None:
            self.comment = comment
            self.simulation_data = None
            self.path = None
            self.comment_path = None
        else:
            self.connect_to_dict(simulation_data, path, comment)
        # TODO: Get data_items from dictionary
        self.data_items = []

    def build_header_variables(self, simulation_data, block_header_structure, block_path, data, dimensions):
        self.data_items = []
        #for data_index, header_variable_struct in zip(range(0,len(block_header_structure)), block_header_structure):
        #   var_path = block_path + (header_variable_struct.name,)
        #    if len(data) > data_index:
        #        scalar_data = data[data_index]
        #    else:
        #        scalar_data = None
        #new_scalar = mfdatascalar.MFScalar(simulation_data, header_variable_struct,
            #                                   scalar_data, True, var_path, dimensions)
        var_path = block_path + (block_header_structure[0].name,)

        # fix up data
        fixed_data = []
        if block_header_structure[0].data_item_structures[0].type == 'keyword':
            keyword_name = block_header_structure[0].data_item_structures[0].name
            #if len(self.variable_strings) == 0:
            #    self.variable_strings.append(keyword_name)
            fixed_data.append(keyword_name)
        if type(data) == tuple:
            data = list(data)
        if type(data) == list:
            fixed_data = fixed_data + data
        else:
            fixed_data.append(data)
        if len(fixed_data) > 0:
            fixed_data = [tuple(fixed_data)]
        # create data object
        new_data = MFBlock.data_factory(simulation_data, block_header_structure[0], True, var_path,
                                        dimensions, fixed_data)
        self.data_items.append(new_data)

    def is_same_header(self, block_header):
        if len(self.data_items) == 0 or len(block_header.variable_strings) == 0:
            return True
        if self.data_items[0].structure.data_item_structures[0].type_obj == int or \
          self.data_items[0].structure.data_item_structures[0].type_obj == float:
            if self.variable_strings[0] == block_header.variable_strings[0]:
                return True
            else:
                return False
        else:
            return True

    def get_comment(self):
        if self.simulation_data is None:
            return self.comment
        else:
            return self.simulation_data.mfdata[self.comment_path]

    def connect_to_dict(self, simulation_data, path, comment=None):
        self.simulation_data = simulation_data
        self.path = path
        self.comment_path = path + ('blk_hdr_comment',)
        if comment is None:
            simulation_data.mfdata[self.comment_path] = self.comment
        else:
            simulation_data.mfdata[self.comment_path] = comment
        self.comment = None

    def write_header(self, fd):
        fd.write('BEGIN {}'.format(self.name))
        if len(self.data_items) > 0:
            if isinstance(self.data_items[0], mfdatascalar.MFScalar):
                is_one_based = self.data_items[0].structure.type == 'integer'
                fd.write('{}'.format(self.data_items[0].get_file_entry(values_only=True,
                                                                       one_based=is_one_based).rstrip()))
            else:
                fd.write('{}'.format(self.data_items[0].get_file_entry().rstrip()))
            if len(self.data_items) > 1:
                for data_item in self.data_items[1:]:
                    fd.write('%s' % (data_item.get_file_entry(values_only=True).rstrip()))
        if self.get_comment().text:
            fd.write(' ')
            self.get_comment().write(fd)
        fd.write('\n')

    def write_footer(self, fd):
        fd.write('END {}'.format(self.name))
        if len(self.data_items) > 0:
            is_one_based = self.data_items[0].structure.type == 'integer'
            if isinstance(self.data_items[0], mfdatascalar.MFScalar):
                fd.write('{}'.format(self.data_items[0].get_file_entry(values_only=True,
                                                                       one_based=is_one_based)))
            else:
                fd.write('{}'.format(self.data_items[0].get_file_entry().rstrip()))
        fd.write('\n')

    def set_number_of_variables(self, num_variables):
        # sets a number of variables, moving the rest to the comments section
        self.get_comment().text = ' '.join(self.variable_strings[num_variables:]) + self.get_comment().text
        self.variable_strings = self.variable_strings[:num_variables]

    def get_transient_key(self):
        transient_key = None
        for index in range(0, len(self.data_items)):
            if self.data_items[index].structure.type != 'keyword':
                transient_key = self.data_items[index].get_data()
                if isinstance(transient_key, np.recarray):
                    key_index = self.data_items[index].structure.first_non_keyword_index()
                    assert key_index is not None and len(transient_key[0]) > key_index
                    transient_key = transient_key[0][key_index]
                break
        return transient_key


class MFBlock(object):
    """
    Represents a block in a MF6 input file


    Parameters
    ----------
    simulation_data : MFSimulationData
        data specific to this simulation
    dimensions : MFDimensions
        describes model dimensions including model grid and simulation time
    block_name : string
        name of the block
    structure : MFVariableStructure
        structure describing block
    path : tuple
        unique path to block

    Attributes
    ----------
    block_headers : MFBlockHeaderIO
        block header text (BEGIN/END), header variables, comments in the header
    structure : MFBlockStructure
        structure describing block
    path : tuple
        unique path to block
    datasets : OrderDict
        dictionary of dataset objects with keys that are the name of the dataset
    datasets_keyword : dict
        dictionary of dataset objects with keys that are key words to identify start of dataset
    enabled : boolean
        block is being used

    Methods
    -------
    get_block_header_info : (line : string, path : tuple)
        static method that parses a line as a block header and returns a MFBlockHeader class
        representing the block header in that line
    load : (block_header : MFBlockHeader, fd : file, strict : boolean)
        loads block from file object.  file object must be advanced to beginning of block before calling
    write : (fd : file)
        writes block to a file object
    is_valid : ()
        returns true of the block is valid

    See Also
    --------

    Notes
    -----

    Examples
    --------

    """

    def __init__(self, simulation_data, dimensions, structure, path, model_or_sim, container_package=None):
        self._simulation_data = simulation_data
        self._dimensions = dimensions
        self._model_or_sim = model_or_sim
        self._container_package = container_package
        self.block_headers = [MFBlockHeader(structure.name, [], mfdata.MFComment('', path, simulation_data, 0), \
                                            simulation_data, path)]
        self.structure = structure
        self.path = path
        self.datasets = OrderedDict()
        self.datasets_keyword = {}
        self.blk_trailing_comment_path = path + ('blk_trailing_comment',)
        self.blk_post_comment_path = path + ('blk_post_comment',)
        if not self.blk_trailing_comment_path in simulation_data.mfdata:
            simulation_data.mfdata[self.blk_trailing_comment_path] = mfdata.MFComment('', '', simulation_data, 0)
        if not self.blk_post_comment_path in simulation_data.mfdata:
            simulation_data.mfdata[self.blk_post_comment_path] = mfdata.MFComment('\n', '', simulation_data, 0)
        self.enabled = structure.number_non_optional_data() > 0 # initially disable if optional
        self.loaded = False
        self.external_file_name = None
        self._structure_init()

    # return an MFScalar, MFList, or MFArray
    @staticmethod
    def data_factory(sim_data, structure, enable, path, dimensions, data=None):
        data_type = structure.get_datatype()
        # examine the data structure and determine the data type
        if data_type == mfstructure.DataType.scalar_keyword or \
          data_type == mfstructure.DataType.scalar:
            return mfdatascalar.MFScalar(sim_data, structure, data, enable, path, dimensions)
        elif data_type == mfstructure.DataType.scalar_keyword_transient or \
          data_type == mfstructure.DataType.scalar_transient:
            trans_scalar = mfdatascalar.MFScalarTransient(sim_data, structure, enable, path, dimensions)
            if data is not None:
                trans_scalar.set_data(data, key=0)
            return trans_scalar
        elif data_type == mfstructure.DataType.array:
            return mfdataarray.MFArray(sim_data, structure, data, enable, path, dimensions)
        elif data_type == mfstructure.DataType.array_transient:
            trans_array = mfdataarray.MFTransientArray(sim_data, structure, enable, path, dimensions)
            if data is not None:
                trans_array.set_data(data, key=0)
            return trans_array
        elif data_type == mfstructure.DataType.list:
            return mfdatalist.MFList(sim_data, structure, data, enable, path, dimensions)
        elif data_type == mfstructure.DataType.list_transient:
            trans_list = mfdatalist.MFTransientList(sim_data, structure, enable, path, dimensions)
            if data is not None:
                trans_list.set_data(data, key=0, autofill=True)
            return trans_list
        elif data_type == mfstructure.DataType.list_multiple:
            mult_list = mfdatalist.MFMultipleList(sim_data, structure, enable, path, dimensions)
            if data is not None:
                mult_list.set_data(data, key=0, autofill=True)
            return mult_list

    def _structure_init(self):
        # load datasets keywords into dictionary
        for key, dataset_struct in self.structure.data_structures.items():
            for keyword in dataset_struct.get_keywords():
                self.datasets_keyword[keyword] = dataset_struct
        # load block header data items into dictionary
        for dataset in self.structure.block_header_structure:
            self._new_dataset(dataset.name, dataset, True, None)

    def _structure_clear(self):
        for key, dataset in self.datasets.items():
            dataset.new_simulation(self._simulation_data)
        for block_header in self.block_headers:
            for key, dataitem in block_header.data_items:
                dataitem.new_simulation(self._simulation_data)

    def add_dataset(self, dataset_struct, data, var_path):
        self.datasets[var_path[-1]] = self.data_factory(self._simulation_data, dataset_struct, True,
                                                        var_path, self._dimensions, data)
        self._simulation_data.mfdata[var_path] = self.datasets[var_path[-1]]
        if dataset_struct.get_datatype() == mfstructure.DataType.list_transient or \
          dataset_struct.get_datatype() == mfstructure.DataType.list_multiple or \
          dataset_struct.get_datatype() == mfstructure.DataType.array_transient:
            # build repeating block header(s)
            if isinstance(data, dict):
                # Add block headers for each dictionary key
                for index in data:
                    self._build_repeating_header([index])
            elif isinstance(data, list):
                # Add a single block header of value 0
                self._build_repeating_header([0])
            elif dataset_struct.get_datatype() != mfstructure.DataType.list_multiple and data is not None:
                self._build_repeating_header([[0]])

        return self.datasets[var_path[-1]]

    def _build_repeating_header(self, header_data):
        if self._header_exists(header_data[0]):
            return
        if len(self.block_headers[-1].data_items) == 1 and self.block_headers[-1].data_items[0].get_data() is not None:
            block_header_path = self.path + (len(self.block_headers) + 1,)
            self.block_headers.append(MFBlockHeader(self.structure.name, [],
                                                    mfdata.MFComment('', self.path, self._simulation_data, 0),
                                                    self._simulation_data,
                                                    block_header_path))
        else:
            block_header_path = self.path + (len(self.block_headers),)
        self.block_headers[-1].build_header_variables(self._simulation_data,
                                                      self.structure.block_header_structure,
                                                      block_header_path,
                                                      header_data,
                                                      self._dimensions)

    def _new_dataset(self, key, dataset_struct, block_header=False, initial_val=None):
        dataset_path = self.path + (key,)
        if block_header:
            if dataset_struct.type == 'integer' and initial_val is not None and len(initial_val) >= 1 and \
              dataset_struct.get_record_size()[0] == 1:
               # stress periods are stored 0 based
               initial_val = int(initial_val[0]) - 1
            if isinstance(initial_val, list):
                initial_val = [tuple(initial_val)]
            new_data = MFBlock.data_factory(self._simulation_data, dataset_struct, True, dataset_path,
                                            self._dimensions, initial_val)
            self.block_headers[-1].data_items.append(new_data)
        else:
            self.datasets[key] = self.data_factory(self._simulation_data, dataset_struct, True,
                                                   dataset_path, initial_val, self._dimensions)
        for keyword in dataset_struct.get_keywords():
            self.datasets_keyword[keyword] = dataset_struct

    def is_empty(self):
        for key, dataset in self.datasets.items():
            has_data = dataset.has_data()
            if has_data is not None and has_data:
                return False
        return True

    def load(self, block_header, fd, strict=True):
        # verify number of header variables
        if len(block_header.variable_strings) < self.structure.number_non_optional_block_header_data():
            warning_str = 'WARNING: Block header for block "{}" does not contain the correct number of ' \
                          'variables {}'.format(block_header.name, self.path)
            print(warning_str)
            return

        if self.loaded:
            # verify header has not already been loaded
            for bh_current in self.block_headers:
                if bh_current.is_same_header(block_header):
                    warning_str = 'WARNING: Block header for block "{}" is not a unique block header ' \
                                  '{}'.format(block_header.name, self.path)
                    print(warning_str)
                    return

        # init
        self.enabled = True
        if not self.loaded:
            self.block_headers = []
        self.block_headers.append(block_header)

        # process any header variable
        #for var_string, dataset in zip(self.block_headers[-1].variable_strings, self.structure.block_header_structure):
        if len(self.structure.block_header_structure) > 0:
            dataset = self.structure.block_header_structure[0]
            self._new_dataset(dataset.name, dataset, True, self.block_headers[-1].variable_strings)

        # handle special readasarrays case
        if self._container_package.structure.read_as_arrays:
            # auxiliary variables may appear with aux variable name as keyword
            aux_vars = self._container_package.auxiliary.get_data()
            if aux_vars is not None:
                for var_name in list(aux_vars[0])[1:]:
                    self.datasets_keyword[(var_name,)] = self._container_package.aux.structure

        comments = []

        # capture any initial comments
        initial_comment = mfdata.MFComment('', '', 0)
        fd_block = fd
        line = fd_block.readline()
        arr_line = mfdatautil.ArrayUtil.split_data_line(line)
        while mfdata.MFComment.is_comment(line, True):
            initial_comment.add_text(line)
            line = fd_block.readline()
            arr_line = mfdatautil.ArrayUtil.split_data_line(line)

        if not (len(arr_line[0]) > 2 and arr_line[0][:3].upper() == 'END'):   # if block not empty
            if arr_line[0].lower() == 'open/close':
                # open block contents from external file
                fd_block.readline()
                fd_path, filename = os.path.split(os.path.realpath(fd_block.name))
                self.external_file_name = arr_line[1]
                fd_block = open(os.path.join(fd_path, self.external_file_name), 'r')
                # read first line of external file
                line = fd_block.readline()
                arr_line = mfdatautil.ArrayUtil.split_data_line(line)
            if len(self.structure.data_structures) <= 1:
                # load a single data set
                dataset = self.datasets[next(iter(self.datasets))]
                next_line = dataset.load(line, fd_block, self.block_headers[-1], initial_comment)

                package_info_list = self._get_package_info(dataset)
                if package_info_list is not None:
                    for package_info in package_info_list:
                        self._model_or_sim.load_package(package_info[0], package_info[1], package_info[1], True,
                                                        package_info[2], package_info[3], self._container_package)

                if next_line[1] is not None:
                    arr_line = mfdatautil.ArrayUtil.split_data_line(next_line[1])
                else:
                    arr_line = ''
                # capture any trailing comments
                post_data_comments = mfdata.MFComment('', '', self._simulation_data, 0)
                dataset.post_data_comments = post_data_comments
                while arr_line and (len(next_line[1]) <= 2 or arr_line[0][:3].upper() != 'END'):
                    next_line[1] = fd_block.readline().strip()
                    arr_line = mfdatautil.ArrayUtil.split_data_line(next_line[1])
                    if arr_line and (len(next_line[1]) <= 2 or arr_line[0][:3].upper() != 'END'):
                        post_data_comments.add_text(' '.join(arr_line))
            else:
                # look for keyword and store line as data or comment
                try:
                    key, results = self._find_data_by_keyword(line, fd_block, initial_comment)
                except mfstructure.MFInvalidTransientBlockHeaderException as e:
                    warning_str = 'WARNING: {}'.format(e)
                    print(warning_str)
                    self.block_headers.pop()
                    return

                self._save_comments(arr_line, line, key, comments)
                if results[1] is None or results[1][:3].upper() != 'END':
                    # block consists of unordered datasets
                    # load the data sets out of order based on initial constants
                    line = ' '
                    while line != '':
                        line = fd_block.readline()
                        arr_line = mfdatautil.ArrayUtil.split_data_line(line)
                        if arr_line:
                            # determine if at end of block
                            if len(arr_line[0]) > 2 and arr_line[0][:3].upper() == 'END':
                                break
                            # look for keyword and store line as data or comment
                            key, results = self._find_data_by_keyword(line, fd_block, initial_comment)
                            self._save_comments(arr_line, line, key, comments)
                            if results[1] is not None and results[1][:3].upper() == 'END':
                                break

        self._simulation_data.mfdata[self.blk_trailing_comment_path].text = comments
        self.loaded = True
        self.is_valid()

    def _find_data_by_keyword(self, line, fd, initial_comment):
        first_key = None
        nothing_found = False
        next_line = [True, line]
        while next_line[0] and not nothing_found:
            arr_line = mfdatautil.ArrayUtil.split_data_line(next_line[1])
            key = mfdatautil.find_keyword(arr_line, self.datasets_keyword)
            if key is not None:
                ds_name = self.datasets_keyword[key].name
                next_line = self.datasets[ds_name].load(next_line[1], fd, self.block_headers[-1], initial_comment)
                # see if first item's name indicates a reference to another package
                package_info_list = self._get_package_info(self.datasets[ds_name])
                if package_info_list is not None:
                    for package_info in package_info_list:
                        self._model_or_sim.load_package(package_info[0], package_info[1], package_info[1], True,
                                                        package_info[2], package_info[3], self._container_package)
                if first_key is None:
                    first_key = key
                nothing_found = False
            elif arr_line[0].lower() == 'readasarrays' and self.path[-1].lower() == 'options' and \
              self._container_package.structure.read_as_arrays == False:
                error_msg = 'ERROR: Attempting to read a ReadAsArrays package as a non-ReadAsArrays package {}'.format(
                  self.path)
                raise mfstructure.ReadAsArraysException(error_msg)
            else:
                nothing_found = True

        if first_key is None:
            # look for recarrays.  if there is a lone recarray in this block, use it by default
            recarrays = self.structure.get_all_recarrays()
            if len(recarrays) != 1:
                return key, [None, None]
            ds_result = self.datasets[recarrays[0].name].load(line, fd, self.block_headers[-1], initial_comment)

            # see if first item's name indicates a reference to another package
            package_info_list = self._get_package_info(self.datasets[recarrays[0].name])
            if package_info_list is not None:
                for package_info in package_info_list:
                    self._model_or_sim.load_package(package_info[0], package_info[1], None,
                                                    True, package_info[2], package_info[3], self._container_package)

            return recarrays[0].keyword, ds_result
        else:
            return first_key, next_line

    def _get_package_info(self, dataset):
        if not dataset.structure.file_data:
            return None
        for index in range(0, len(dataset.structure.data_item_structures)):
            if dataset.structure.data_item_structures[index].type == 'keyword' or \
              dataset.structure.data_item_structures[index].type == 'string':
                item_name = dataset.structure.data_item_structures[index].name
                package_type = item_name[:-1]
                if PackageContainer.package_factory(package_type,
                                                           self._model_or_sim.structure.model_type) is not None:
                    data = dataset.get_data()
                    file_locations = []
                    if isinstance(data, np.recarray):
                        # get the correct part of the recarray
                        for entry in data:
                            file_locations.append(entry[index])
                    else:
                        file_locations.append(data)
                    package_info_list = []
                    for file_location in file_locations:
                        file_path, file_name = os.path.split(file_location)
                        dict_package_name = '{}_{}'.format(package_type, self.path[-2])
                        package_info_list.append((package_type, file_name, file_path, dict_package_name))
                    return package_info_list
                return None
        return None

    def _save_comments(self, arr_line, line, key, comments):
        # FIX: Save these comments somewhere in the data set
        if not key in self.datasets_keyword:
            if mfdata.MFComment.is_comment(key, True):
                if comments:
                    comments.append('\n')
                comments.append(arr_line)

    def write(self, fd, ext_file_action=ExtFileAction.copy_relative_paths):
        # never write an empty block
        is_empty = self.is_empty()
        if is_empty and self.structure.name.lower() != 'exchanges' and \
          self.structure.name.lower() != 'options':
            return
        if self.structure.repeating():
            repeating_datasets = self._find_repeating_datasets()
            for repeating_dataset in repeating_datasets:
                # resolve any missing block headers
                self._add_missing_block_headers(repeating_dataset)
            if len(repeating_datasets) > 0:
                # loop through all block headers
                for block_header in self.block_headers:
                    self._write_block(fd, block_header, ext_file_action)
            else:
                # write out block
                self._write_block(fd, self.block_headers[0], ext_file_action)

        else:
            self._write_block(fd, self.block_headers[0], ext_file_action)

    def _add_missing_block_headers(self, repeating_dataset):
        for key in repeating_dataset.get_active_key_list():
            if not self._header_exists(key[0]):
                self._build_repeating_header([key[0]])

    def _header_exists(self, key):
        if not isinstance(key, list):
            comp_key_list = [key]
        else:
            comp_key_list = key
        for block_header in self.block_headers:
            transient_key = block_header.get_transient_key()
            for comp_key in comp_key_list:
                if transient_key is not None and transient_key == comp_key:
                    return True
        return False

    def _find_repeating_datasets(self):
        repeating_datasets = []
        for key, dataset in self.datasets.items():
            if dataset.repeating:
                repeating_datasets.append(dataset)
        return repeating_datasets

    def _write_block(self, fd, block_header, ext_file_action):
        # write block header
        block_header.write_header(fd)
        transient_key = None
        if len(block_header.data_items) > 0:
            transient_key = block_header.get_transient_key()

        if self.external_file_name is not None:
            # write block contents to external file
            fd.write('{}open/close {}\n'.format(self._simulation_data.indent_string, self.external_file_name))
            fd_main = fd
            fd_path, filename = os.path.split(os.path.realpath(fd.name))
            fd = open(os.path.join(fd_path, self.external_file_name), 'w')

        # write data sets
        for key, dataset in self.datasets.items():
            if transient_key is None:
                fd.write(dataset.get_file_entry(ext_file_action=ext_file_action))
            else:
                if dataset.repeating:
                    fd.write(dataset.get_file_entry(transient_key, ext_file_action=ext_file_action))
                else:
                    fd.write(dataset.get_file_entry(ext_file_action=ext_file_action))

        # write trailing comments
        self._simulation_data.mfdata[self.blk_trailing_comment_path].write(fd)

        if self.external_file_name is not None:
            # switch back writing to package file
            fd.close()
            fd = fd_main

        # write block footer
        block_header.write_footer(fd)

        # write post block comments
        self._simulation_data.mfdata[self.blk_post_comment_path].write(fd)

        # write extra line if comments are off
        if not self._simulation_data.comments_on:
            fd.write('\n')

    def is_allowed(self):
        if self.structure.variable_dependant_path:
            # fill in empty part of the path with the current path
            if len(self.structure.variable_dependant_path) == 3:
                dependant_var_path = (self.path[0],) + self.structure.variable_dependant_path
            elif len(self.structure.variable_dependant_path) == 2:
                dependant_var_path = (self.path[0], self.path[1]) + self.structure.variable_dependant_path
            elif len(self.structure.variable_dependant_path) == 1:
                dependant_var_path = (self.path[0], self.path[1], self.path[2]) + self.structure.variable_dependant_path
            else:
                dependant_var_path = None

            # get dependency
            dependant_var = None
            if dependant_var_path in self._simulation_data.mfdata:
                dependant_var = self._simulation_data.mfdata[dependant_var_path]

            # resolve dependency
            if self.structure.variable_value_when_active[0] == 'Exists':
                if dependant_var and self.structure.variable_value_when_active[1].lower() == 'true':
                    return True
                elif not dependant_var and self.structure.variable_value_when_active[1].lower() == 'false':
                    return True
                else:
                    return False
            elif not dependant_var:
                return False
            elif self.structure.variable_value_when_active[0] == '>':
                if dependant_var > float(self.structure.variable_value_when_active[1]):
                    return True
                else:
                    return False
            elif self.structure.variable_value_when_active[0] == '<':
                if dependant_var < float(self.structure.variable_value_when_active[1]):
                    return True
                else:
                    return False
        return True

    def is_valid(self):
        # check data sets
        for key, dataset in self.datasets.items():
            # Non-optional datasets must be enabled
            if not dataset.structure.optional and not dataset.enabled:
                return False
            # Enabled blocks must be valid
            if dataset.enabled and not dataset.is_valid:
                return False
        # check variables
        for block_header in self.block_headers:
            for dataset in block_header.data_items:
                # Non-optional datasets must be enabled
                if not dataset.structure.optional and not dataset.enabled:
                    return False
                # Enabled blocks must be valid
                if dataset.enabled and not dataset.is_valid():
                    return False


class MFPackage(PackageContainer):
    """
    Provides an interface for the user to specify data to build a package.

    Parameters
    ----------
    model_or_sim : MFModel of MFSimulation
        the parent model or simulation containing this package
    package_type : string
        string defining the package type
    filename : string
        filename of file where this package is stored
    pname : string
        package name
    add_to_package_list : bool
        whether or not to add this package to the parent container's package list during initialization
    parent_file : MFPackage
        parent package that contains this package

    Attributes
    ----------
    blocks : OrderedDict
        dictionary of blocks contained in this package by block name
    path : tuple
        data dictionary path to this package
    structure : PackageStructure
        describes the blocks and data contain in this package
    dimensions : PackageDimension
        resolves data dimensions for data within this package

    Methods
    -------
    build_mfdata : (var_name : variable name, data : data contained in this object) : MFData subclass
        Returns the appropriate data type object (mfdatalist, mfdataarray, or mfdatascalar) giving that object
        the appropriate structure (looked up based on var_name) and any data supplied
    load : (strict : bool) : bool
        Loads the package from file
    is_valid : bool
        Returns whether or not this package is valid
    write
        Writes the package to a file
    get_file_path : string
        Returns the package file's path

    See Also
    --------

    Notes
    -----

    Examples
    --------


    """
    def __init__(self, model_or_sim, package_type, filename=None, pname=None,
                 add_to_package_list=True, parent_file=None):
        self._init_in_progress = True
        self._model_or_sim = model_or_sim
        self.package_type = package_type
        if model_or_sim.type == 'Model' and package_type.lower() != 'nam':
            self._sr = model_or_sim.sr
            self.model_name = model_or_sim.name
        else:
            self._sr = None
            self.model_name = None
        super(MFPackage, self).__init__(model_or_sim.simulation_data, self.model_name)
        self._simulation_data = model_or_sim.simulation_data
        self.parent_file = parent_file
        self.blocks = OrderedDict()
        self.container_type = []
        if pname is not None:
            self.package_name = pname.lower()
        else:
            self.package_name = None

        if filename is None:
            self.filename = MFFileMgmt.string_to_file_path('{}.{}'.format(self._model_or_sim.name, package_type))
        else:
            self.filename = MFFileMgmt.string_to_file_path(filename)

        self.path, self.structure = model_or_sim.register_package(self, add_to_package_list,
                                                                  pname is None, filename is None)
        self.dimensions = self.create_package_dimensions()

        if self.path is None:
            print('WARNING: Package type {} failed to register property. {}'.format(self.package_type, self.path))
        if parent_file is not None:
            self.container_type.append(PackageContainerType.package)
        # init variables that may be used later
        self._unresolved_text = None
        self.post_block_comments = None
        self.last_error = None

    def __setattr__(self, name, value):
        if hasattr(self, name):
            attribute = object.__getattribute__(self, name)
            if attribute is not None and isinstance(attribute, mfdata.MFData):
                attribute.set_data(value)
                return
        super(MFPackage, self).__setattr__(name, value)

    def _get_block_header_info(self, line, path):
        # init
        header_variable_strs = []
        arr_clean_line = line.strip().split()
        header_comment = mfdata.MFComment('', path + (arr_clean_line[1],), self._simulation_data, 0)
        # break header into components
        if len(arr_clean_line) < 2:
            except_str = 'ERROR: Block header does not contain a name {}'.format(line)
            print(except_str)
            raise mfstructure.MFFileParseException(except_str)
        elif len(arr_clean_line) == 2:
            return MFBlockHeader(arr_clean_line[1], header_variable_strs, header_comment)
        else:
            # process text after block name
            comment = False
            for entry in arr_clean_line[2:]:
                # if start of comment
                if mfdata.MFComment.is_comment(entry.strip()[0]):
                    comment = True
                if comment:
                    header_comment.text = ' '.join([header_comment.text, entry])
                else:
                    header_variable_strs.append(entry)
            return MFBlockHeader(arr_clean_line[1], header_variable_strs, header_comment)

    def build_mfdata(self, var_name, data=None):
        for key, block in self.structure.blocks.items():
            if var_name in block.data_structures:
                if block.name not in self.blocks:
                    self.blocks[block.name] = MFBlock(self._simulation_data, self.dimensions,
                                                      block, self.path + (key,), self._model_or_sim, self)
                dataset_struct = block.data_structures[var_name]
                var_path = self.path + (key, var_name)
                return self.blocks[block.name].add_dataset(dataset_struct, data, var_path)

        except_message = 'Unable to find variable "{}" in package "{}".'.format(var_name, self.package_type)
        raise mfstructure.MFDataException(except_message)

    def load(self, strict=True):
        # open file
        try:
            fd_input_file = open(self.get_file_path(), 'r')
        except OSError as e:
            if e.errno == errno.ENOENT:
                excpt_str = 'File {} of type {} could not be opened. {}'.format(self.get_file_path(),
                                                                            self.package_type,
                                                                            self.path)
                print(excpt_str)
                raise mfstructure.MFFileParseException(excpt_str)

        try:
            self._load_blocks(fd_input_file, strict)
        except mfstructure.ReadAsArraysException as err:
            fd_input_file.close()
            raise mfstructure.ReadAsArraysException(err)
        # close file
        fd_input_file.close()

        # return validity of file
        return self.is_valid()

    def is_valid(self):
        # Check blocks
        for key, block in self.blocks.items():
            # Non-optional blocks must be enabled
            if block.structure.number_non_optional_data() > 0 and not block.enabled and block.is_allowed():
                self.last_error = 'Required block "{}" not enabled'.format(block.block_header.name)
                return False
            # Enabled blocks must be valid
            if block.enabled and not block.is_valid:
                self.last_error = 'Invalid block "{}"'.format(block.block_header.name)
                return False

        return True

    def _load_blocks(self, fd_input_file, strict=True, max_blocks=sys.maxsize):
        # init
        self._unresolved_text = []
        self._simulation_data.mfdata[self.path + ('pkg_hdr_comments',)] = mfdata.MFComment('', self.path,
                                                                                           self._simulation_data)
        self.post_block_comments = mfdata.MFComment('', self.path, self._simulation_data)

        blocks_read = 0
        found_first_block = False
        line = ' '
        while line != '':
            line = fd_input_file.readline()
            clean_line = line.strip()
            # If comment or empty line
            if mfdata.MFComment.is_comment(clean_line, True):
                self._store_comment(line, found_first_block)
            elif len(clean_line) > 4 and clean_line[:5].upper() == 'BEGIN':
                # parse block header
                try:
                    block_header_info = self._get_block_header_info(line, self.path)
                except mfstructure.MFFileParseException:
                    raise mfstructure.MFFileParseException('Invalid block header {} ({})'.format(line, self.package_type))

                # if there is more than one possible block with the same name, resolve the correct block to use
                block_key = block_header_info.name.lower()
                block_num = 1
                possible_key = '{}-{}'.format(block_header_info.name.lower(), block_num)
                if possible_key in self.blocks:
                    block_key = possible_key
                    while block_key in self.blocks and not self.blocks[block_key].is_allowed():
                        block_key = '{}-{}'.format(block_header_info.name.lower(), block_num)
                        block_num += 1

                if block_key not in self.blocks:
                    # block name not recognized, load block as comments and issue a warning
                    warning_str = 'WARNING: Block "{}" is not a valid block name for file type ' \
                                  '{}.'.format(block_key, self.package_type)
                    print(warning_str)
                    self._store_comment(line, found_first_block)
                    while line != '':
                        line = fd_input_file.readline()
                        self._store_comment(line, found_first_block)
                        arr_line = mfdatautil.ArrayUtil.split_data_line(line)
                        if arr_line and (len(arr_line[0]) <= 2 or arr_line[0][:3].upper() == 'END'):
                            break
                else:
                    found_first_block = True
                    self.post_block_comments = mfdata.MFComment('', self.path, self._simulation_data)
                    skip_block = False
                    if self.blocks[block_key].loaded:
                        # Only blocks defined as repeating are allowed to have multiple entries
                        if not self.structure.blocks[block_header_info.name.lower()].repeating():
                            # warn and skip block
                            warning_str = 'WARNING: Block "{}" has multiple entries and is not intended to be a ' \
                                          'repeating block ({} package)'.format(block_header_info.name, self.package_type)
                            print(warning_str)
                            skip_block = True

                    if not skip_block:
                        self.blocks[block_key].load(block_header_info, fd_input_file, strict)
                        self._simulation_data.mfdata[self.blocks[block_key].blk_post_comment_path] = \
                            self.post_block_comments

                        blocks_read += 1
                        if blocks_read >= max_blocks:
                            break
            else:
                if not (len(clean_line) == 0 or (len(line) > 2 and line[:3].upper() == 'END')):
                    # Record file location of beginning of unresolved text
                    # treat unresolved text as a comment for now
                    self._store_comment(line, found_first_block)

    def write(self, ext_file_action=ExtFileAction.copy_relative_paths):
        # create any folders in path
        package_file_path = self.get_file_path()
        package_folder = os.path.split(package_file_path)[0]
        if package_folder and not os.path.isdir(package_folder):
            os.makedirs(os.path.split(package_file_path)[0])

        # open file
        fd = open(package_file_path, 'w')

        # write blocks
        self._write_blocks(fd, ext_file_action)

        fd.close()

    def create_package_dimensions(self):
        model_dims = None
        if self.container_type[0] == PackageContainerType.model:
            model_dims = [modeldimensions.ModelDimensions(self.path[0], self._simulation_data)]
        else:
            # this is a simulation file that does not coorespond to a specific model.  need to figure out which
            # model to use and return a dimensions object for that model
            if self.structure.file_type == 'gwfgwf':
                exchange_rec_array = self._simulation_data.mfdata[('nam', 'exchanges', 'exchangerecarray')].get_data()
                if exchange_rec_array is None:
                    return None
                for exchange in exchange_rec_array:
                    if exchange[1].lower() == self.filename.lower():
                        model_dims = [modeldimensions.ModelDimensions(exchange[2], self._simulation_data),
                                      modeldimensions.ModelDimensions(exchange[3], self._simulation_data)]
                        break
            elif self.parent_file is not None:
                model_dims = []
                for md in self.parent_file.dimensions.model_dim:
                    model_name = md.model_name
                    model_dims.append(modeldimensions.ModelDimensions(model_name, self._simulation_data))
            else:
                model_dims = [modeldimensions.ModelDimensions(None, self._simulation_data)]
        return modeldimensions.PackageDimensions(model_dims, self.structure, self.path)

    def _store_comment(self, line, found_first_block):
        # Store comment
        if found_first_block:
            self.post_block_comments.text += line
        else:
            self._simulation_data.mfdata[self.path + ('pkg_hdr_comments',)].text += line

    def _write_blocks(self, fd, ext_file_action):
        # verify that all blocks are valid
        if not self.is_valid():
            excpt_str = 'Unable to write out model file "{}" due to the following error: ' \
                        '{} ({})'.format(self.filename, self.last_error, self.path)
            print(excpt_str)
            raise mfstructure.MFFileWriteException(excpt_str)

        # write initial comments
        pkg_hdr_comments_path = self.path + ('pkg_hdr_comments',)
        if pkg_hdr_comments_path in self._simulation_data.mfdata:
            self._simulation_data.mfdata[self.path + ('pkg_hdr_comments',)].write(fd, False)

        # loop through blocks
        block_num = 1
        for index, block in self.blocks.items():
            # write block
            block.write(fd, ext_file_action=ext_file_action)
            block_num += 1

    def get_file_path(self):
        if self.path[0] in self._simulation_data.mfpath.model_relative_path:
            return os.path.join(self._simulation_data.mfpath.get_model_path(self.path[0]), self.filename)
        else:
            return os.path.join(self._simulation_data.mfpath.get_sim_path(), self.filename)