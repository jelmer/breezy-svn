# Copyright (C) 2006-2009 Jelmer Vernooij <jelmer@samba.org>

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
"""Generation of file-ids."""

from bzrlib import ui
from bzrlib.errors import RevisionNotPresent
from bzrlib.knit import make_file_factory
from bzrlib.revision import NULL_REVISION
from bzrlib.trace import mutter
from bzrlib.versionedfile import ConstantMapper

from collections import defaultdict
import urllib

from bzrlib.plugins.svn import (
        changes, 
        errors,
        )
from bzrlib.plugins.svn.revmeta import (
        iter_with_mapping,
        )

# idmap: dictionary mapping unicode paths to tuples with file id and revision id
# idmap delta: dictionary mapping unicode paths to new file id assignments
# text revision map: dictionary mapping unicode paths to text revisions (usually revision ids)

def idmap_lookup(idmap, path):
    """Lookup a path in an idmap.

    :param idmap: The idmap to look up in.
    :param path: Path to look up
    :return: Tuple with file id and text revision
    """
    return idmap[path]


def determine_text_revisions(changes, default_revid, specific_revids):
    """Create a text revision map.

    :param changes: Local changes dictionary
    :param default_revid: Default revision id, if none is explicitly specified
    :param specific_revids: Dictionary with explicit text revisions to use
    :return: text revision map
    """
    ret = {}
    ret.update(specific_revids)
    for p, data in changes.iteritems():
        assert isinstance(p, unicode)
        if data[0] in ('A', 'R', 'M') and p not in ret:
            ret[p] = default_revid
    return ret


def apply_idmap_delta(map, text_revisions, delta, changes, default_revid):
    """Update a file id map.

    :param map: Existing file id map that needs to be updated
    :param text_revisions: Text revisions for the map
    :param delta: Id map delta.
    :param changes: Changes for the revision in question.
    """
    for p, data in changes.iteritems():
        if data[0] in ('D', 'R') and not p in delta:
            del map[p]
            for xp in map.keys():
                if xp.startswith(u"%s/" % p) and not xp in delta:
                    del map[xp]

    for x in sorted(text_revisions.keys() + delta.keys()):
        assert isinstance(x, unicode)
        if (# special case - we change metadata in svn at the branch root path
            # but that's not reflected as a bzr metadata change in bzr
            (x != "" or not "" in map or map[x][1] == NULL_REVISION)):
            map[x] = (delta.get(x) or map[x][0], text_revisions.get(x) or default_revid)


def get_local_changes(paths, branch, mapping, layout, generate_revid):
    """Obtain all of the changes relative to a particular path
    (usually a branch path).

    :param paths: Changes
    :param branch: Path under which to select changes
    :param mapping: Mapping to use to determine what are valid branch paths
    :param layout: Layout to use 
    :param generate_revid: Function for generating revision id from svn revnum
    """
    if (branch in paths and 
        paths[branch][0] == 'A' and 
        paths[branch][1] is None):
        # Avoid finding all file ids
        return {}
    new_paths = {}
    for p in sorted(paths.keys(), reverse=False):
        if not changes.path_is_child(branch, p):
            continue
        data = paths[p]
        new_p = p[len(branch):].strip("/")
        if data[1] is not None:
            try:
                (pt, proj, cbp, crp) = layout.parse(data[1])

                # Branch copy
                if (crp == "" and new_p == ""):
                    data = ('M', None, None)
                else:
                    data = (data[0], crp, generate_revid(
                                  data[2], cbp, mapping))
            except errors.NotSvnBranchPath:
                # Copied from outside of a known branch
                # Make it look like the files were added in this revision
                data = (data[0], None, -1)

        new_paths[new_p.decode("utf-8")] = data
    return new_paths


FILEIDMAP_VERSION = 2

def simple_apply_changes(new_file_id, changes):
    """Simple function that generates a dictionary with file id changes.
    
    Does not track renames. """
    delta = {}
    for p in sorted(changes.keys(), reverse=False):
        data = changes[p]
        assert isinstance(p, unicode)
        if data[0] in ('A', 'R'):
            delta[p] = new_file_id(p)
            if data[1] is not None:
                mutter('%r copied from %r:%s', p, data[1], data[2])
    return delta 


class FileIdMap(object):
    """File id store. 

    Keeps a map

    revnum -> branch -> path -> fileid
    """
    def __init__(self, apply_changes_fn, repos):
        self.apply_changes_fn = apply_changes_fn
        self.repos = repos

    def get_idmap_delta(self, changes, revmeta, mapping):
        """Change file id map to incorporate specified changes.

        :param revmeta: RevisionMetadata object for revision with changes
        :param renames: List of renames (known file ids for particular paths)
        :param mapping: Mapping
        """
        foreign_revid = revmeta.get_foreign_revid()
        def new_file_id(x):
            return mapping.generate_file_id(foreign_revid, x)
         
        idmap = self.apply_changes_fn(new_file_id, changes)
        idmap.update(revmeta.get_fileid_map(mapping))
        return idmap

    def update_idmap(self, map, revmeta, mapping):
        local_changes = get_local_changes(revmeta.get_paths(mapping), 
                    revmeta.branch_path, mapping,
                    self.repos.get_layout(),
                    self.repos.generate_revision_id)
        idmap = self.get_idmap_delta(local_changes, revmeta, 
                mapping)
        revid = revmeta.get_revision_id(mapping)
        text_revisions = determine_text_revisions(local_changes, revid, 
                revmeta.get_text_revisions(mapping))
        apply_idmap_delta(map, text_revisions, idmap, local_changes, revid)

    def get_map(self, foreign_revid, mapping):
        """Make sure the map is up to date until revnum."""
        (uuid, branch, revnum) = foreign_revid
        # First, find the last cached map
        if revnum == 0:
            assert branch == ""
            return {"": (mapping.generate_file_id(foreign_revid, u""), 
              self.repos.generate_revision_id(0, "", mapping))}

        todo = []
        next_parent_revs = []
        if mapping.is_branch(""):
            map = {u"": (mapping.generate_file_id((uuid, "", 0), u""), NULL_REVISION)}
        else:
            map = {}

        # No history -> empty map
        todo = self.repos.get_mainline(branch, revnum, mapping)
        pb = ui.ui_factory.nested_progress_bar()
        try:
            for i, (revmeta, mapping) in enumerate(reversed(todo)):
                pb.update('generating file id map', i, len(todo))
                if revmeta.is_hidden(mapping):
                    continue
                self.update_idmap(map, revmeta, mapping)
        finally:
            pb.finished()
        return map


class FileIdMapCache(object):

    def __init__(self, cache_transport):
        mapper = ConstantMapper("fileidmap-v%d" % FILEIDMAP_VERSION)
        self.idmap_knit = make_file_factory(True, mapper)(cache_transport)

    def save(self, revid, parent_revids, _map):
        mutter('saving file id map for %r', revid)

        for path, (id, created_revid)  in _map.iteritems():
            assert isinstance(path, unicode)
            assert isinstance(id, str)
            assert isinstance(created_revid, str)

        self.idmap_knit.add_lines((revid,), [(r, ) for r in parent_revids], 
                ["%s\t%s\t%s\n" % (urllib.quote(filename.encode("utf-8")), urllib.quote(_map[filename][0]), 
                                        urllib.quote(_map[filename][1])) for filename in sorted(_map.keys())])

    def load(self, revid):
        map = {}
        for ((create_revid,), line) in self.idmap_knit.annotate((revid,)):
            (filename, id, create_revid) = line.rstrip("\n").split("\t", 3)
            map[urllib.unquote(filename).decode("utf-8")] = (urllib.unquote(id), urllib.unquote(create_revid))
            assert isinstance(map[urllib.unquote(filename).decode("utf-8")][0], str)

        return map


class CachingFileIdMap(object):
    """A file id map that uses a cache."""
    def __init__(self, cache_transport, actual):
        self.cache = FileIdMapCache(cache_transport)
        self.actual = actual
        self.repos = actual.repos
        self.get_idmap_delta = actual.get_idmap_delta

    def get_map(self, (uuid, branch, revnum), mapping):
        """Make sure the map is up to date until revnum."""
        # First, find the last cached map
        if revnum == 0:
            return self.actual.get_map((uuid, branch, revnum), mapping)

        todo = []
        next_parent_revs = []

        # No history -> empty map
        try:
            pb = ui.ui_factory.nested_progress_bar()
            for revmeta, mapping in iter_with_mapping(self.repos._revmeta_provider.iter_reverse_branch_changes(branch, revnum, to_revnum=0), mapping):
                pb.update("fetching changes for file ids", revnum-revmeta.revnum, revnum)
                if revmeta.is_hidden(mapping):
                    continue
                revid = revmeta.get_revision_id(mapping)
                try:
                    map = self.cache.load(revid)
                    # found the nearest cached map
                    next_parent_revs = [revid]
                    break
                except RevisionNotPresent:
                    todo.append((revmeta, mapping))
        finally:
            pb.finished()
       
        # target revision was present
        if len(todo) == 0:
            return map

        if len(next_parent_revs) == 0:
            if mapping.is_branch(""):
                map = {u"": (mapping.generate_file_id((uuid, "", 0), u""), NULL_REVISION)}
            else:
                map = {}

        pb = ui.ui_factory.nested_progress_bar()

        try:
            for i, (revmeta, mapping) in enumerate(reversed(todo)):
                pb.update('generating file id map', i, len(todo))
                revid = revmeta.get_revision_id(mapping)
                self.actual.update_idmap(map, revmeta, mapping)
                parent_revs = next_parent_revs
                self.cache.save(revid, parent_revs, map)
                next_parent_revs = [revid]
        finally:
            pb.finished()
        return map

