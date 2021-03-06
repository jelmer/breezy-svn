# Copyright (C) 2006-2009 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Subversion server implementation."""

from __future__ import absolute_import

from breezy.sixish import text_type

from breezy.plugins.svn import lazy_check_versions
lazy_check_versions()

import os
import subvertpy
from subvertpy import properties
from subvertpy.ra_svn import (
    SVN_PORT,
    SVNServer,
    TCPSVNServer,
    )
from subvertpy.server import (
    ServerBackend,
    ServerRepositoryBackend,
    )
import sys
import time

from breezy import (
    trace,
    urlutils,
    )
from breezy.branch import Branch

from breezy.plugins.svn.commit import dir_editor_send_changes


def determine_changed_paths(repository, branch_path, rev, revno):
    assert isinstance(branch_path, text_type)
    def fixpath(p):
        return u"%s/%s" % (branch_path, p)
    changes = {}
    changes[branch_path] = ("M", None, -1) # Always changes
    delta = repository.get_revision_delta(rev.revision_id)
    for (path, id, kind) in delta.added:
        changes[fixpath(path)] = ("A", None, -1)
    for (path, id, kind) in delta.removed:
        changes[fixpath(path)] = ("D", None, -1)
    for (oldpath, newpath, id, kind, text_modified, meta_modified) in delta.renamed:
        changes[fixpath(newpath)] = ("A", fixpath(oldpath), revno-1)
        changes[fixpath(oldpath)] = ("D", None, -1)
    for (path, id, kind, text_modified, meta_modified) in delta.modified:
        changes[fixpath(path)] = ("M", None, -1)
    return changes


class RepositoryBackend(ServerRepositoryBackend):

    def __init__(self, branch):
        self.branch = branch

    def get_uuid(self):
        config = self.branch.get_config()
        uuid = config.get_user_option('svn_uuid')
        if uuid is None:
            import uuid
            uuid = uuid.uuid4()
            config.set_user_option('svn_uuid', uuid)
        return str(uuid)

    def get_latest_revnum(self):
        return self.branch.revno()

    def _get_revid(self, revnum):
        """Find the revision id and branch path a particular revnum refers to."""
        return "/trunk", self.branch.get_rev_id(revnum)

    def log(self, send_revision, target_path, start_rev, end_rev, report_changed_paths,
            strict_node, limit):
        i = 0
        revno = start_rev
        self.branch.repository.lock_read()
        try:
            # FIXME: check whether start_rev and end_rev actually exist
            while revno != end_rev:
                #TODO: Honor target_path, strict_node, changed_paths
                if end_rev > revno:
                    revno+=1
                else:
                    revno-=1
                if limit != 0 and i == limit:
                    break
                if revno > 0:
                    (path, revid) = self._get_revid(revno)
                    rev = self.branch.repository.get_revision(revid)
                    if report_changed_paths:
                        changes = determine_changed_paths(self.branch.repository, path, rev, revno)
                    else:
                        changes = None
                    send_revision(revno,
                            rev.committer, time.strftime("%Y-%m-%dT%H:%M:%S.00000Z", time.gmtime(rev.timestamp)),
                            rev.message, changed_paths=changes)
        finally:
            self.branch.repository.unlock()

    def rev_proplist(self, revnum):
        path, revid = self._get_revid(revnum)
        rev = self.branch.repository.get_revision(revid)
        ret = {
                properties.PROP_REVISION_AUTHOR: rev.committer,
                properties.PROP_REVISION_DATE: time.strftime("%Y-%m-%dT%H:%M:%S.00000Z", time.gmtime(rev.timestamp)),
                properties.PROP_REVISION_LOG: rev.message
                }
        return ret

    def update(self, editor, revnum, target_path, recurse=True):
        if revnum is None:
            revnum = self.get_latest_revnum()
        path, revid = self._get_revid(revnum)
        relpath = None # FIXME
        editor.set_target_revision(revnum)
        root = editor.open_root()
        self.branch.repository.lock_read()
        try:
            new_tree = self.branch.repository.revision_tree(revid)
            modified_files = {}
            visit_dirs = set()
            for path, ie in new_tree.iter_entries_by_dir():
                if ie.kind == "directory":
                    visit_dirs.add(ie.file_id)
                elif ie.kind == 'file':
                    modified_files[ie.file_id] = new_tree.get_file_text(path)
                elif ie.kind == 'symlink':
                    modified_files[ie.file_id] = "link %s" % ie.symlink_target

            dir_editor_send_changes(None, new_tree, "",
                    new_tree.get_root_id(),
                    root, "svn://localhost/", revnum-1, relpath,
                                modified_files, visit_dirs)
            root.close()
            editor.close()
        finally:
            self.branch.repository.unlock()

    def check_path(self, path, revnum):
        return subvertpy.NODE_DIR

    def get_locations(self, path, peg_revnum, revnums):
        if path.strip() in ("trunk", ""):
            return dict([(rev, path) for rev in revnums])
        raise NotImplementedError

    def stat(self, path, revnum):
        if revnum is None:
            revnum = self.get_latest_revnum()
        branch_path, revid = self._get_revid(revnum)
        tree = self.branch.repository.revision_tree(revid)
        tree_path = path[len(branch_path):].strip("/")
        if not tree.is_versioned(tree_path):
            return None
        ret = { "name": urlutils.basename(path) }
        if tree.kind(tree_path) == "directory":
            ret["kind"] = subvertpy.NODE_DIR
            ret["size"] = 0
        else:
            ret["kind"] = subvertpy.NODE_FILE
            ret["size"] = tree.get_file_size(tree_path)
        ret["has-props"] = True
        ret["created-rev"] = 0 # FIXME
        ret["created-date"] = "" # FIXME
        ret["last-author"] = "" # FIXME

        return ret


class BzrServerBackend(ServerBackend):

    def __init__(self, rootdir):
        self.rootdir = rootdir

    def open_repository(self, path):
        (branch, relpath) = Branch.open_containing(os.path.join(self.rootdir, path))
        return RepositoryBackend(branch), relpath


def serve_svn(transport, host=None, port=None, inet=False):
    trace.warning("server support in bzr-svn is experimental.")

    if transport.base.startswith("readonly+"):
        url = transport.base[len("readonly+"):]
    path = urlutils.local_path_from_url(url)

    backend = BzrServerBackend(path)
    if inet:
        def send_fn(data):
            sys.stdout.write(data)
            sys.stdout.flush()
        server = SVNServer(backend, sys.stdin.read, send_fn)
    else:
        if port is None:
            port = SVN_PORT
        if host is None:
            host = '0.0.0.0'
        server = TCPSVNServer(backend, (host, port))
    server.serve()
