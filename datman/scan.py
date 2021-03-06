"""
A class to make access to all information about a single scan easy
and uniform.


    WARNING: This class currently assumes the contents of the directories
    does not change after the object is created. Certain attribute values may
    become out of date if this is not true.


    Both Scan and Series inherit from DatmanNamed and have the following
    attributes:

        full_id         A datman style id of the form STUDY_SITE_ID_TIMEPOINT
        id_plus_session The same ID as above, except with the session number
                        joined to the end. (Default: "_01")
        study           The 'study' portion of full_id
        site            The 'site' portion of full_id
        subject         The 'ID' portion of full_id
        timepoint       The 'timepoint' portion of full_id
        session         The session number (Default: "_01")

    In addition each 'Series' instance has the following attributes:

        tag             The tag for this series (e.g. T1, DTI60-1000, etc.)
        series_num      The number of this series in the scan session.
        description     The description found in the original dicom headers
        path            The full path to this particular file
        ext             The extension of this file

    Finally, each 'Scan' instance has the following attributes and methods:

    Attributes:

        is_phantom      True if the subject id used to create this instance
                        belongs to a phantom, false otherwise.
        nii_path        The path to this subject's nifti data.
        dcm_path        The path to this subject's dicom data.
        qc_path         The path to this subject's generated qc outputs.
        resource_path   The path to all resources (non-scan data) associated
                        with this scan.
        niftis          A list of 'Series' instances for each nifti in nii_path.
                        Returns an empty list if none are found.
        dicoms          A list of 'Series' instances for each dicom in dcm_path.
                        Returns an empty list if none are found.
        nii_tags        A list of all tags for all niftis found in nii_path.
        dcm_tags        A list of all tags for all dicoms found in dcm_path.

    Methods:

        get_tagged_nii(tag)     Returns a list of 'Series' instances for each
                                nifti in nii_path that has the given tag.
                                If no niftis are found with this tag, returns
                                an empty list.

        get_tagged_dcm(tag)     Returns a list of 'Series' instances for each
                                dicom in dcm_path with the given tag. If none
                                are found returns an empty list.
"""
import os
import glob
import logging

import datman.utils
import datman.scanid as scanid

try:
    # Only one function uses dashboard, and it may not always be setup in the
    # user's environment. So, configured as an optional feature
    import datman.dashboard
except:
    dash_available = False
else:
    dash_available = True

class DatmanNamed(object):
    """
    A parent class for all classes that will obey the datman naming scheme

        ident:      A datman.scanid.Identifier instance
    """
    def __init__(self, ident):
        self.full_id = ident.get_full_subjectid_with_timepoint()
        self.id_plus_session = ident.get_full_subjectid_with_timepoint_session()
        self.study = ident.study
        self.site = ident.site
        self.subject = ident.subject
        self.timepoint = ident.timepoint
        self.session = ident.session

class Series(DatmanNamed):
    """
    Holds all information about a series file of any format (e.g. nifti).

        path:       The absolute path to a single file.

    May raise a ParseException if the given file name does not match the
    datman naming convention.
    """
    def __init__(self, path):
        self.path = path
        self.ext = datman.utils.get_extension(path)
        self.file_name = os.path.basename(self.path)

        path_minus_ext = path.replace(self.ext, "")

        try:
            ident, tag, series, description = scanid.parse_filename(path_minus_ext)
        except datman.scanid.ParseException:
            # re-raise the exception with a more descriptive message
            message = "{} does not match datman convention".format(path_minus_ext)
            raise datman.scanid.ParseException(message)
        DatmanNamed.__init__(self, ident)

        self.tag = tag
        self.series_num = series
        self.description = description

    def __str__(self):
        return self.file_name

    def __repr__(self):
        return "<datman.scan.Series: {}>".format(self.path)

class Scan(DatmanNamed):
    """
    Holds all information for a single scan (session).

        subject_id:     A subject id of the format STUDY_SITE_ID_TIMEPOINT
                        _SESSION may be included, but will be set to the
                        default _01 if missing.
        config:         A config object made from a project_settings.yml file

    May raise a ParseException if the given subject_id does not match the
    datman naming convention
    """
    def __init__(self, subject_id, config):

        self.is_phantom = True if '_PHA_' in subject_id else False

        subject_id = self.__check_session(subject_id)

        try:
            ident = scanid.parse(subject_id)
        except datman.scanid.ParseException:
            message = "{} does not match datman convention".format(subject_id)
            raise datman.scanid.ParseException(message)

        try:
            self.project = config.map_xnat_archive_to_project(subject_id)
        except Exception as e:
            message = 'Failed getting project from config: {}'.format(str(e))
            raise Exception(message)

        DatmanNamed.__init__(self, ident)

        self.nii_path = self.__get_path('nii', config)
        self.dcm_path = self.__get_path('dcm', config)
        self.qc_path = self.__get_path('qc', config)
        self.resource_path = self.__get_path('resources', config, session=True)

        self.niftis = self.__get_series(self.nii_path, ['.nii', '.nii.gz'])
        self.dicoms = self.__get_series(self.dcm_path, ['.dcm'])

        self.__nii_dict = self.__make_dict(self.niftis)
        self.__dcm_dict = self.__make_dict(self.dicoms)

        self.nii_tags = self.__nii_dict.keys()
        self.dcm_tags = self.__dcm_dict.keys()

    def get_tagged_nii(self, tag):
        try:
            matched_niftis = self.__nii_dict[tag]
        except KeyError:
            matched_niftis = []
        return matched_niftis

    def get_tagged_dcm(self, tag):
        try:
            matched_dicoms = self.__dcm_dict[tag]
        except KeyError:
            matched_dicoms = []
        return matched_dicoms

    def get_db_object(self):
        """
        Returns the dashboard database object representing the scan (session)
        """
        if not dash_available:
            raise ImportError("Scan.get_db_object requires the dashboard be "
                    "installed")
        db = datman.dashboard.dashboard(self.project)
        try:
            db_session = db.get_add_session(self.full_id)
        except:
            db_session = None
        return db_session

    def __check_session(self, id_str):
        """
        Adds a default session number of "_01" if it's missing and the id
        doesn't belong to a phantom
        """
        fields = id_str.split("_")
        if len(fields) == 4 and not self.is_phantom:
            # Fill in missing session number with the default
            id_str = id_str + "_01"
        return id_str

    def __get_path(self, key, config, session=False):
        folder_name = self.full_id
        if session:
            folder_name = self.id_plus_session
        path = os.path.join(config.get_path(key), folder_name)
        return path

    def __get_series(self, path, ext_list):
        """
        This method will generate a ParseException if any files are not named
        according to the datman naming convention.
        """
        glob_path = os.path.join(path, "*")
        series_list = []
        badly_named = []
        for item in glob.glob(glob_path):
            if datman.utils.get_extension(item) in ext_list:
                try:
                    series = Series(item)
                except datman.scanid.ParseException:
                    badly_named.append(item)
                    continue
                series_list.append(series)
        if badly_named:
            message = "File(s) misnamed: {}".format(', '.join(badly_named))
            raise datman.scanid.ParseException(message)
        return series_list

    def __make_dict(self, series_list):
        tag_dict = {}
        for series in series_list:
            tag = series.tag
            try:
                tag_dict[tag].append(series)
            except KeyError:
                tag_dict[tag] = [series]
        return tag_dict

    def __str__(self):
        return self.full_id

    def __repr__(self):
        return "<datman.scan.Scan: {}>".format(self.full_id)
