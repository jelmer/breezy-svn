# Copyright (C) 2006-2007 Jelmer Vernooij <jelmer@samba.org>

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

"""Remote access tests."""

from bzrlib.bzrdir import BzrDir, format_registry
from bzrlib.errors import (NoRepositoryPresent, NotBranchError, NotLocalUrl,
                           NoWorkingTree)

import svn

from format import SvnFormat
from tests import TestCaseWithSubversionRepository
from transport import SvnRaTransport

class TestRemoteAccess(TestCaseWithSubversionRepository):
    def test_clone(self):
        repos_url = self.make_client("d", "dc")
        self.build_tree({"dc/foo": None})
        self.client_add("dc/foo")
        self.client_commit("dc", "msg")
        x = self.open_checkout_bzrdir("dc")
        self.assertRaises(NotImplementedError, x.clone, "dir")

    def test_open_workingtree(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url)
        self.assertRaises(NoWorkingTree, x.open_workingtree)

    def test_open_workingtree_recommend_arg(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url)
        self.assertRaises(NoWorkingTree, lambda: x.open_workingtree(recommend_upgrade=True))

    def test_create_workingtree(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url)
        self.assertRaises(NotLocalUrl, x.create_workingtree)

    def test_create_branch_top(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url)
        b = x.create_branch()
        self.assertEquals(repos_url, b.base)

    def test_create_branch_nested(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url+"/trunk")
        b = x.create_branch()
        self.assertEquals(repos_url+"/trunk", b.base)
        transport = SvnRaTransport(repos_url)
        self.assertEquals(svn.core.svn_node_dir, 
                transport.check_path("trunk", 1))

    def test_bad_dir(self):
        repos_url = self.make_client("d", "dc")
        self.build_tree({"dc/foo": None})
        self.client_add("dc/foo")
        self.client_commit("dc", "msg")
        self.assertRaises(NotBranchError, BzrDir.open, repos_url+"/foo")

    def test_create(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url)
        self.assertTrue(hasattr(x, 'svn_root_url'))

    def test_open_repos_root(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url)
        repos = x.open_repository()
        self.assertTrue(hasattr(repos, 'uuid'))

    def test_find_repos_nonroot(self):
        repos_url = self.make_client("d", "dc")
        self.build_tree({'dc/trunk': None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "data")
        x = BzrDir.open(repos_url+"/trunk")
        repos = x.find_repository()
        self.assertTrue(hasattr(repos, 'uuid'))

    def test_find_repos_root(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url)
        repos = x.find_repository()
        self.assertTrue(hasattr(repos, 'uuid'))

    def test_open_repos_nonroot(self):
        repos_url = self.make_client("d", "dc")
        self.build_tree({'dc/trunk': None})
        self.client_add("dc/trunk")
        self.client_commit("dc", "data")
        x = BzrDir.open(repos_url+"/trunk")
        self.assertRaises(NoRepositoryPresent, x.open_repository)

    def test_needs_format_upgrade_other(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url+"/trunk")
        self.assertTrue(x.needs_format_conversion(format_registry.make_bzrdir("dirstate-with-subtree")))

    def test_needs_format_upgrade_default(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url+"/trunk")
        self.assertTrue(x.needs_format_conversion())

    def test_needs_format_upgrade_self(self):
        repos_url = self.make_client("d", "dc")
        x = BzrDir.open(repos_url+"/trunk")
        self.assertTrue(x.needs_format_conversion(SvnFormat()))

