# Copyright (C) 2005-2009 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import

from functools import partial

import subvertpy

from breezy import urlutils
from breezy.sixish import text_type
from breezy.plugins.svn import errors as svn_errors
from breezy.plugins.svn.layout import (
    RepositoryLayout,
    get_root_paths,
    wildcard_matches,
    )

class TrunkLayout(RepositoryLayout):

    def __init__(self, level=None):
        assert level is None or isinstance(level, int)
        self.level = level

    def get_tag_path(self, name, project=u""):
        """Return the path at which the tag with specified name should be found.

        :param name: Name of the tag.
        :param project: Optional name of the project the tag is for. Can include slashes.
        :return: Path of the tag.
        """
        subpath = urlutils.join(u"tags", name.strip(u"/"))
        if project in (None, u""):
            return subpath
        return urlutils.join(project, subpath)

    def is_branch_parent(self, path, project=u""):
        parts = path.strip(u"/").split(u"/")
        return (self.level is None or
                len(parts) <= self.level or
                (len(parts) == self.level+1 and parts[-1] == u"branches"))

    def is_tag_parent(self, path, project=u""):
        parts = path.strip(u"/").split(u"/")
        return (self.level is None or
                len(parts) <= self.level or
                (len(parts) == self.level+1 and parts[-1] == u"tags"))

    def get_tag_name(self, path, project=u""):
        """Determine the tag name from a tag path.

        :param path: Path inside the repository.
        """
        return urlutils.basename(path).strip(u"/")

    def push_merged_revisions(self, project=u""):
        """Determine whether or not right hand side (merged) revisions should be pushed.

        Defaults to False.

        :param project: Name of the project.
        """
        return True

    def get_branch_name(self, path, project=u""):
        name = urlutils.split(path)[-1]
        if name == u"trunk":
            return u""
        return name

    def get_branch_path(self, name, project=""):
        """Return the path at which the branch with specified name should be found.

        :param name: Name of the branch.
        :param project: Optional name of the project the branch is for. Can include slashes.
        :return: Path of the branch.
        """
        if name == u"":
            return urlutils.join(project, u"trunk").strip(u"/")
        else:
            return urlutils.join(project, u"branches", name).strip(u"/")

    def parse(self, path):
        """Parse a path.

        :return: Tuple with type ('tag', 'branch'), project name, branch path and path
            inside the branch
        """
        assert isinstance(path, text_type)
        path = path.strip(u"/")
        parts = path.split(u"/")
        for i, p in enumerate(parts):
            if (i > 0 and parts[i-1] in (u"branches", u"tags")) or p == u"trunk":
                if i > 0 and parts[i-1] == u"tags":
                    t = "tag"
                    j = i-1
                elif i > 0 and parts[i-1] == u"branches":
                    t = "branch"
                    j = i-1
                else:
                    t = "branch"
                    j = i
                if self.level in (j, None):
                    return (t,
                        u"/".join(parts[:j]).strip(u"/"),
                        u"/".join(parts[:i+1]).strip(u"/"),
                        u"/".join(parts[i+1:]).strip(u"/"))
        raise svn_errors.NotSvnBranchPath(path, self)

    def _add_project(self, path, project=None):
        if project is None:
            return path
        return urlutils.join(project, path)

    def get_branches(self, repository, revnum, project=None):
        """Retrieve a list of paths that refer to branches in a specific revision.

        :return: Iterator over tuples with (project, branch path, has_props, revnum)
        """
        return get_root_paths(repository,
             [self._add_project(x, project) for x in [u"branches/*", u"trunk"]],
             revnum, self.is_branch, project)

    def get_tags(self, repository, revnum, project=None):
        """Retrieve a list of paths that refer to tags in a specific revision.

        :return: Iterator over tuples with (project, branch path, has_props, revnum)
        """
        return get_root_paths(repository, [self._add_project(u"tags/*", project)],
                revnum, self.is_tag, project)

    def __repr__(self):
        if self.level is None:
            return "%s()" % self.__class__.__name__
        else:
            return "%s(%d)" % (self.__class__.__name__, self.level)

    def __str__(self):
        if self.level is None:
            return "trunk-variable"
        else:
            return "trunk%d" % self.level


TrunkLayoutVariable = partial(TrunkLayout, None)
TrunkLayout0 = partial(TrunkLayout, 0)
TrunkLayout1 = partial(TrunkLayout, 1)
TrunkLayout2 = partial(TrunkLayout, 2)
TrunkLayout3 = partial(TrunkLayout, 3)
TrunkLayout4 = partial(TrunkLayout, 4)


class RootLayout(RepositoryLayout):
    """Layout where the root of the repository is a branch."""

    def __init__(self):
        pass

    def supports_tags(self):
        return False

    def get_tag_path(self, name, project=""):
        """Return the path at which the tag with specified name should be found.

        :param name: Name of the tag.
        :param project: Optional name of the project the tag is for. Can include slashes.
        :return: Path of the tag."
        """
        raise svn_errors.NoLayoutTagSetSupport(self,
            "the root layout does not support tags")

    def get_tag_name(self, path, project=""):
        """Determine the tag name from a tag path.

        :param path: Path inside the repository.
        """
        raise AssertionError("should never be reached, there can't be any tag paths in this layout")

    def get_branch_path(self, name, project=u""):
        """Return the path at which the branch with specified name should be found.

        :param name: Name of the branch.
        :param project: Optional name of the project the branch is for. Can include slashes.
        :return: Path of the branch.
        """
        if name != u"" or project:
            raise svn_errors.NoCustomBranchPaths(self)
        return u""

    def get_branch_name(self, path, project=u""):
        if path != u"":
            raise svn_errors.NoCustomBranchPaths(self)
        return u""

    def parse(self, path):
        """Parse a path.

        :return: Tuple with type ('tag', 'branch'), project name, branch path and path
            inside the branch
        """
        assert isinstance(path, text_type)
        return ('branch', u'', u'', path)

    def is_branch_path(self, bp, project=None):
        return (bp == u"")

    def is_tag_path(self, tp, project=None):
        return False

    def get_branches(self, repository, revnum, project=None):
        """Retrieve a list of paths that refer to branches in a specific revision.

        :return: Iterator over tuples with (project, branch path)
        """
        return [(u"", u"", u"trunk", None, revnum)]

    def get_tags(self, repository, revnum, project=None):
        """Retrieve a list of paths that refer to tags in a specific revision.

        :return: Iterator over tuples with (project, branch path, branch name, has_props)
        """
        return []

    def __repr__(self):
        return "%s()" % self.__class__.__name__

    def __str__(self):
        return "root"


class CustomLayout(RepositoryLayout):

    def __init__(self, branches=[], tags=[]):
        self.branches = [b.strip(u"/") for b in branches]
        self.tags = [t.strip(u"/") for t in tags]
        assert all([isinstance(b, text_type) for b in self.branches + self.tags])

    def supports_tags(self):
        return (self.tags != [])

    def get_tag_path(self, name, project=u""):
        """Return the path at which the tag with specified name should be found.

        :param name: Name of the tag.
        :param project: Optional name of the project the tag is for. Can include slashes.
        :return: Path of the tag.
        """
        raise svn_errors.NoLayoutTagSetSupport(self)

    def get_tag_name(self, path, project=u""):
        """Determine the tag name from a tag path.

        :param path: Path inside the repository.
        """
        return None

    def get_branch_name(self, path, project=u""):
        return u""

    def parse(self, path):
        """Parse a path.

        :return: Tuple with type ('tag', 'branch'), project name, branch path and path
            inside the branch
        """
        assert isinstance(path, text_type)
        path = path.strip(u"/")
        for bp in sorted(self.branches):
            if path.startswith(u"%s/" % bp) or bp == path:
                return ("branch", bp, bp, path[len(bp):].strip(u"/"))

        for tp in sorted(self.tags):
            if path.startswith(u"%s/" % tp) or tp == path:
                return ("tag", tp, tp, path[len(tp):].strip(u"/"))

        raise svn_errors.NotSvnBranchPath(path)

    def _get_paths(self, entries, project, repository, revnum):
        ret = []
        for b in entries:
            try:
                r = repository.svn_transport.get_dir(b, revnum)[1]
            except subvertpy.SubversionException as e:
                msg, num = e.args
                if num in (subvertpy.ERR_FS_NOT_DIRECTORY,
                           subvertpy.ERR_FS_NOT_FOUND,
                           subvertpy.ERR_RA_DAV_PATH_NOT_FOUND,
                           subvertpy.ERR_RA_DAV_FORBIDDEN):
                    continue
                raise
            ret.append((project, b, b.split("/")[-1], None, r))
        return ret

    def get_branches(self, repository, revnum, project=None):
        """Retrieve a list of paths that refer to branches in a specific revision.

        :return: Iterator over tuples with (project, branch path)
        """
        return self._get_paths(self.branches, project, repository, revnum)

    def get_tags(self, repository, revnum, project=None):
        """Retrieve a list of paths that refer to tags in a specific revision.

        :return: Iterator over tuples with (project, branch path)
        """
        return self._get_paths(self.tags, project, repository, revnum)

    def __repr__(self):
        return "%s(%r,%r)" % (self.__class__.__name__, self.branches, self.tags)

    def _is_prefix(self, prefixes, path, project=None):
        for branch in prefixes:
            if branch.startswith(u"%s/" % path):
                return True
        return False

    def is_branch_parent(self, path, project=None):
        return self._is_prefix(self.branches, path, project)

    def is_tag_parent(self, path, project=None):
        return self._is_prefix(self.tags, path, project)


class WildcardLayout(RepositoryLayout):

    def __init__(self, branches=[], tags=[]):
        self.branches = [b.strip(u"/") for b in branches]
        self.tags = [t.strip(u"/") for t in tags]
        assert all([isinstance(b, text_type) for b in self.branches + self.tags])

    def supports_tags(self):
        return (self.tags != [])

    def get_tag_path(self, name, project=u""):
        """Return the path at which the tag with specified name should be found.

        :param name: Name of the tag.
        :param project: Optional name of the project the tag is for. Can include slashes.
        :return: Path of the tag."
        """
        if project:
            raise svn_errors.NoLayoutTagSetSupport(self)
        if len(self.tags) == 0:
            raise svn_errors.NoLayoutTagSetSupport(self,
                "no tag paths set")
        if self.tags[0].count(u"*") == 0:
            raise svn_errors.NoLayoutTagSetSupport(self,
                "no asterisk in tag path")
        if self.tags[0].count(u"*") > 1:
            raise svn_errors.NoLayoutTagSetSupport(self,
                "can only handle a single asterisk in tag path")
        return self.tags[0].replace(u"*", name)

    def get_item_name(self, possibilities, path, project=u""):
        for p in possibilities:
            if wildcard_matches(path, p):
                for a, wc in zip(path.split(u"/"), p.split(u"/")):
                    if u"*" in wc:
                        return a
                return path.split(u"/")[-1]
        return None

    def get_tag_name(self, path, project=""):
        """Determine the tag name from a tag path.

        :param path: Path inside the repository.
        """
        return self.get_item_name(self.tags, path, project)

    def get_branch_name(self, path, project=u""):
        """Determine the tag name from a branch path.

        :param path: Path inside the repository.
        """
        return self.get_item_name(self.branches, path, project)

    def is_branch(self, path, project=None):
        for bp in self.branches:
            if wildcard_matches(path, bp):
                return True
        return False

    def is_tag(self, path, project=None):
        for tp in self.tags:
            if wildcard_matches(path, tp):
                return True
        return False

    def parse(self, path):
        """Parse a path.

        :return: Tuple with type ('tag', 'branch'), project name, branch path
            and path inside the branch
        """
        assert isinstance(path, text_type)
        path = path.strip(u"/")
        parts = path.split(u"/")
        for i in range(len(parts)+1):
            bp = u"/".join(parts[:i])
            if self.is_branch(bp):
                return ("branch", bp, bp, path[len(bp):].strip(u"/"))
            if self.is_tag(bp):
                return ("tag", bp, bp, path[len(bp):].strip(u"/"))

        raise svn_errors.NotSvnBranchPath(path)

    def get_branches(self, repository, revnum, project=None):
        """Retrieve a list of paths that refer to branches in a specific revision.

        :return: Iterator over tuples with (project, branch path)
        """
        return get_root_paths(repository, self.branches,
             revnum, self.is_branch, project)

    def get_tags(self, repository, revnum, project=None):
        """Retrieve a list of paths that refer to tags in a specific revision.

        :return: Iterator over tuples with (project, branch path)
        """
        return get_root_paths(
                repository, self.tags, revnum, self.is_tag, project)

    def __repr__(self):
        return "%s(%r,%r)" % (
                self.__class__.__name__, self.branches, self.tags)


class InverseTrunkLayout(RepositoryLayout):

    def __init__(self, level):
        assert isinstance(level, int)
        assert level > 0
        self.level = level

    def get_tag_path(self, name, project=""):
        """Return the path at which the tag with specified name should be found.

        :param name: Name of the tag.
        :param project: Optional name of the project the tag is for. Can
            include slashes.
        :return: Path of the tag."
        """
        return urlutils.join("tags", project, name.strip("/"))

    def get_tag_name(self, path, project=""):
        """Determine the tag name from a tag path.

        :param path: Path inside the repository.
        """
        return urlutils.basename(path).strip("/")

    def get_branch_path(self, name, project=""):
        """Return the path at which the branch with specified name should be found.

        :param name: Name of the branch.
        :param project: Optional name of the project the branch is for. Can
            include slashes.
        :return: Path of the branch.
        """
        return urlutils.join("branches", project, name).strip("/")

    def get_branch_name(self, path, project=""):
        return urlutils.basename(path).strip("/")

    def parse(self, path):
        """Parse a path.

        :return: Tuple with type ('tag', 'branch'), project name, branch path and path
            inside the branch
        """
        assert isinstance(path, text_type)
        path = path.strip(u"/")
        parts = path.split(u"/")
        if len(parts) == 0:
            raise svn_errors.NotSvnBranchPath(path)
        if parts[0] == u"trunk":
            if len(parts) < (self.level + 1):
                raise svn_errors.NotSvnBranchPath(path)
            return ("branch",
                    u"/".join(parts[1:self.level+2]),
                    u"/".join(parts[:self.level+1]),
                    u"/".join(parts[self.level+1:]))
        elif parts[0] in (u"branches", u"tags"):
            if len(parts) < (self.level + 2):
                raise svn_errors.NotSvnBranchPath(path)
            if parts[0] == u"branches":
                t = "branch"
            else:
                t = "tag"
            return (t,
                    u"/".join(parts[1:self.level+1]),
                    u"/".join(parts[:self.level+2]),
                    u"/".join(parts[self.level+2:]))
        raise svn_errors.NotSvnBranchPath(path)

    def _add_project(self, path, project=None):
        if project is None:
            project = u"*/" * self.level
        if path == u"trunk":
            return urlutils.join(path, project)
        else:
            return urlutils.join(urlutils.join(path, project), u"*")

    def get_branches(self, repository, revnum, project=None):
        """Return a list of paths that refer to branches in a specific revision.

        :return: Iterator over tuples with (project, branch path)
        """
        return get_root_paths(repository,
             [self._add_project(x, project) for x in ["branches", "trunk"]],
             revnum, self.is_branch, project)

    def get_tags(self, repository, revnum, project=None):
        """Retrieve a list of paths that refer to tags in a specific revision.

        :return: Iterator over tuples with (project, branch path)
        """
        return get_root_paths(repository,
                [self._add_project("tags", project)], revnum, self.is_tag,
                project)

    def __repr__(self):
        return "%s(%d)" % (self.__class__.__name__, self.level)

    def __str__(self):
        return "itrunk%d" % self.level

    def get_project_prefixes(self, project):
        return None

InverseTrunkLayout1 = partial(InverseTrunkLayout, 1)
InverseTrunkLayout2 = partial(InverseTrunkLayout, 2)
InverseTrunkLayout3 = partial(InverseTrunkLayout, 3)
InverseTrunkLayout4 = partial(InverseTrunkLayout, 4)

