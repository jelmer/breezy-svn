# Copyright (C) 2007-2009 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
"""Stores per-repository settings."""

from bzrlib import (
        osutils,
        urlutils,
        trace,
        )
from bzrlib.config import (
        ConfigObj,
        IniBasedConfig,
        config_dir,
        ensure_config_dir_exists,
        GlobalConfig,
        LocationConfig,
        Config,
        STORE_BRANCH,
        STORE_GLOBAL,
        STORE_LOCATION,
        )
from bzrlib.errors import (
        BzrError,
        )

import os

from subvertpy import SubversionException, properties

# Settings are stored by UUID. 
# Data stored includes default branching scheme and locations the repository 
# was seen at.

def subversion_config_filename():
    """Return per-user configuration ini file filename."""
    return osutils.pathjoin(config_dir(), 'subversion.conf')


class SvnRepositoryConfig(IniBasedConfig):
    """Per-repository settings."""

    def __init__(self, uuid):
        name_generator = subversion_config_filename
        super(SvnRepositoryConfig, self).__init__(name_generator)
        self.uuid = uuid
        if not self.uuid in self._get_parser():
            self._get_parser()[self.uuid] = {}

    def set_branching_scheme(self, scheme, guessed_scheme, mandatory=False):
        """Change the branching scheme.

        :param scheme: New branching scheme.
        :param guessed_scheme: Guessed scheme.
        """
        self.set_user_option('branching-scheme', str(scheme))
        if (guessed_scheme != scheme or 
            self.get_user_option('branching-scheme-guess') is not None):
            self.set_user_option('branching-scheme-guess', 
                                 guessed_scheme or scheme)
        if (mandatory or 
            self.get_user_option('branching-scheme-mandatory') is not None):
            self.set_user_option('branching-scheme-mandatory', str(mandatory))

    def get_layout(self):
        return self._get_user_option("layout", use_global=False)

    def set_layout(self, layout):
        return self.set_user_option("layout", str(layout))

    def get_branches(self):
        branches_str = self._get_user_option("branches", use_global=False)
        if branches_str is None:
            return None
        return [b.encode("utf-8") for b in branches_str.split(";") if b != ""]

    def get_tags(self):
        tags_str = self._get_user_option("tags", use_global=False)
        if tags_str is None:
            return None
        return [t.encode("utf-8") for t in tags_str.split(";") if t != ""]

    def _get_user_option(self, name, use_global=True):
        try:
            return self._get_parser()[self.uuid][name]
        except KeyError:
            if not use_global:
                return None
            return GlobalConfig()._get_user_option(name)

    def get_reuse_revisions(self):
        ret = self._get_user_option("reuse-revisions")
        if ret is None:
            return "other-branches"
        assert ret in ("none", "other-branches", "removed-branches")
        return ret

    def get_branching_scheme(self):
        """Get the branching scheme.

        :return: BranchingScheme instance.
        """
        from bzrlib.plugins.svn.mapping3.scheme import BranchingScheme
        schemename = self._get_user_option("branching-scheme", use_global=False)
        if schemename is not None:
            return BranchingScheme.find_scheme(schemename.encode('ascii'))
        return None

    def get_default_mapping(self):
        """Get the default mapping.

        :return Mapping name.
        """
        return self._get_user_option("default-mapping", use_global=True)

    def get_guessed_branching_scheme(self):
        """Get the guessed branching scheme.

        :return: BranchingScheme instance.
        """
        from bzrlib.plugins.svn.mapping3.scheme import BranchingScheme
        schemename = self._get_user_option("branching-scheme-guess", 
                                           use_global=False)
        if schemename is not None:
            return BranchingScheme.find_scheme(schemename.encode('ascii'))
        return None

    def get_supports_change_revprop(self):
        """Check whether or not the repository supports changing existing 
        revision properties."""
        try:
            return self._get_parser().get_bool(self.uuid, "supports-change-revprop")
        except KeyError:
            return None

    def get_use_cache(self):
        parser = self._get_parser()
        try:
            if parser.get_bool(self.uuid, "use-cache"):
                return set(["log", "fileids", "revids"])
            return set()
        except ValueError:
            val = parser.get_value(self.uuid, "use-cache")
            if not isinstance(val, list):
                ret = set([val])
            else:
                ret = set(val)
            if len(ret - set(["log", "fileids", "revids"])) != 0:
                raise BzrError("Invalid setting 'use-cache': %r" % val)
            return ret
        except KeyError:
            return None

    def get_log_strip_trailing_newline(self):
        """Check whether or not trailing newlines should be stripped in the 
        Subversion log message (where support by the bzr<->svn mapping used)."""
        try:
            return self._get_parser().get_bool(self.uuid, "log-strip-trailing-newline")
        except KeyError:
            return False

    def branching_scheme_is_mandatory(self):
        """Check whether or not the branching scheme for this repository 
        is mandatory.
        """
        try:
            return self._get_parser().get_bool(self.uuid, "branching-scheme-mandatory")
        except KeyError:
            return False

    def get_override_svn_revprops(self):
        """Check whether or not bzr-svn should attempt to override Subversion revision 
        properties after committing."""
        def get_list(parser, section):
            try:
                if parser.get_bool(section, "override-svn-revprops"):
                    return [properties.PROP_REVISION_DATE, properties.PROP_REVISION_AUTHOR]
                return []
            except ValueError:
                val = parser.get_value(section, "override-svn-revprops")
                if not isinstance(val, list):
                    return [val]
                return val
            except KeyError:
                return None
        ret = get_list(self._get_parser(), self.uuid)
        if ret is not None:
            return ret
        global_config = GlobalConfig()
        return get_list(global_config._get_parser(), global_config._get_section())

    def get_append_revisions_only(self):
        """Check whether it is possible to remove revisions from the mainline.
        """
        try:
            return self._get_parser().get_bool(self.uuid, "append_revisions_only")
        except KeyError:
            return None

    def get_locations(self):
        """Find the locations this repository has been seen at.

        :return: Set with URLs.
        """
        val = self._get_user_option("locations", use_global=False)
        if val is None:
            return set()
        return set(val.split(";"))

    def get_push_merged_revisions(self):
        """Check whether merged revisions should be pushed."""
        try:
            return self._get_parser().get_bool(self.uuid, "push_merged_revisions")
        except KeyError:
            return None

    def add_location(self, location):
        """Add a location for this repository.

        :param location: URL of location to add.
        """
        locations = self.get_locations()
        locations.add(location.rstrip("/"))
        self.set_user_option('locations', ";".join(list(locations)))

    def set_user_option(self, name, value):
        """Change a user option.

        :param name: Name of the option.
        :param value: Value of the option.
        """
        conf_dir = os.path.dirname(self._get_filename())
        ensure_config_dir_exists(conf_dir)
        self._get_parser()[self.uuid][name] = value
        f = open(self._get_filename(), 'wb')
        self._get_parser().write(f)
        f.close()


class BranchConfig(Config):
    def __init__(self, branch):
        super(BranchConfig, self).__init__()
        self._location_config = None
        self._repository_config = None
        self.branch = branch
        self.option_sources = (self._get_location_config, 
                               self._get_repository_config)

    def _get_location_config(self):
        if self._location_config is None:
            self._location_config = LocationConfig(self.branch.base)
        return self._location_config

    def _get_repository_config(self):
        if self._repository_config is None:
            self._repository_config = SvnRepositoryConfig(self.branch.repository.uuid)
        return self._repository_config

    def get_log_strip_trailing_newline(self):
        return self._get_repository_config().get_log_strip_trailing_newline()

    def get_override_svn_revprops(self):
        return self._get_repository_config().get_override_svn_revprops()

    def _get_user_option(self, option_name):
        """See Config._get_user_option."""
        for source in self.option_sources:
            value = source()._get_user_option(option_name)
            if value is not None:
                return value
        return None

    def get_append_revisions_only(self):
        return self.get_user_option("append_revision_only")

    def _get_user_id(self):
        """Get the user id from the 'email' key in the current section."""
        return self._get_user_option('email')

    def get_option(self, key, section=None):
        return None

    def set_user_option(self, name, value, store=STORE_LOCATION,
        warn_masked=False):
        if store == STORE_GLOBAL:
            self._get_global_config().set_user_option(name, value)
        elif store == STORE_BRANCH:
            raise NotImplementedError("Saving in branch config not supported for Subversion branches")
        else:
            self._get_location_config().set_user_option(name, value, store)
        if not warn_masked:
            return
        if store in (STORE_GLOBAL, STORE_BRANCH):
            mask_value = self._get_location_config().get_user_option(name)
            if mask_value is not None:
                trace.warning('Value "%s" is masked by "%s" from'
                              ' locations.conf', value, mask_value)
            else:
                if store == STORE_GLOBAL:
                    branch_config = self._get_branch_data_config()
                    mask_value = branch_config.get_user_option(name)
                    if mask_value is not None:
                        trace.warning('Value "%s" is masked by "%s" from'
                                      ' branch.conf', value, mask_value)

    def get_push_merged_revisions(self):
        """Check whether merged revisions should be pushed."""
        return self._get_repository_config().get_push_merged_revisions()


class PropertyConfig(object):
    """ConfigObj-like class that looks at Subversion file ids."""

    def __init__(self, tree, path):
        self.properties = tree.get_file_properties(tree.path2id(path), path)

    def __getitem__(self, option_name):
        return self.properties[option_name]

    def __setitem__(self, option_name, value):
        raise NotImplementedError(self.set_user_option) # Should be setting the property..

    def __contains__(self, option_name):
        return option_name in self.properties


class SubversionBuildPackageConfig(object):
    """Configuration object that behaves similar to svn-buildpackage when it reads its config."""

    def __init__(self, tree):
        if (isinstance(tree, SvnWorkingTree) and 
            os.path.exists(os.path.join(tree.local_abspath("."), ".svn", "svn-layout"))):
            self.wt_layout_path = os.path.join(tree.local_abspath("."), ".svn", "svn-layout")
            self.option_source = ConfigObj(self.wt_layout_path, encoding="utf-8")
        elif tree.has_filename("debian/svn-layout"):
            self.option_source = ConfigObj(tree.get_file_byname("debian/svn-layout"), encoding="utf-8")
        elif isinstance(tree, SubversionTree) and tree.has_filename("debian"):
            self.option_source = PropertyConfig(tree, "debian")
        else:
            self.option_source = None

    def _get_user_option(self, option_name):
        if self.option_source is None:
            return None
        return self.option_source.get(option_name)
