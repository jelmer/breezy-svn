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

"""Remote access tests."""

import os
import subvertpy

from breezy import osutils
from breezy.branch import Branch
from breezy.controldir import (
    ControlDir,
    format_registry,
    )
from breezy.errors import (
    AlreadyBranchError,
    NotBranchError,
    NoRepositoryPresent,
    NoWorkingTree,
    UnsupportedOperation,
    )
from breezy.tests import TestCase

from breezy.plugins.svn.layout.standard import RootLayout, TrunkLayout
from breezy.plugins.svn.remote import SvnRemoteFormat
from breezy.plugins.svn.tests import SubversionTestCase
from breezy.plugins.svn.transport import SvnRaTransport

class TestRemoteAccess(SubversionTestCase):

    def test_clone(self):
        old_tree = self.make_svn_branch_and_tree("d", "dc")

        dc = self.get_commit_editor(old_tree.branch.base)
        dc.add_dir("foo")
        dc.close()

        old_tree.update()

        x = ControlDir.open("dc")
        dir = x.clone("ec")
        new_tree = dir.open_workingtree()
        self.assertEquals(old_tree.branch.base, new_tree.branch.base)
        self.assertEquals(set([".svn", "foo"]), set(os.listdir("ec")))

    def test_break_lock(self):
        repos_url = self.make_svn_repository("d")

        x = ControlDir.open(repos_url)
        x.break_lock()

    def test_too_much_slashes(self):
        repos_url = self.make_svn_repository("d")

        repos_url = repos_url[:-1] + "///d"

        ControlDir.open(repos_url)

    def test_open_workingtree(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url)
        self.assertRaises(NoWorkingTree, x.open_workingtree)

    def test_open_workingtree_recommend_arg(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url)
        self.assertRaises(NoWorkingTree,
                x.open_workingtree, recommend_upgrade=True)

    def test_create_workingtree(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url)
        self.assertRaises(UnsupportedOperation, x.create_workingtree)

    def test_create_branch(self):
        repos_url = self.make_repository("d")
        x = ControlDir.open(repos_url)
        # The default layout is "trunk"
        b = x.create_branch()
        self.assertEquals(repos_url+"/trunk", b.base)

    def test_create_branch_top(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url)
        x.open_repository().store_layout(RootLayout())
        b = x.create_branch()
        self.assertEquals(repos_url, b.base)

    def test_create_branch_top_already_branch(self):
        repos_url = self.make_svn_repository("d")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bla").modify("contents")
        dc.close()
        x = ControlDir.open(repos_url)
        self.assertRaises(AlreadyBranchError, x.create_branch)

    def test_create_branch_nested(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url+"/trunk")
        b = x.create_branch()
        self.assertEquals(repos_url+"/trunk", b.base)
        transport = SvnRaTransport(repos_url)
        self.assertEquals(subvertpy.NODE_DIR,
                transport.check_path("trunk", 1))

    def test_destroy_branch(self):
        repos_url = self.make_svn_repository("d")

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        x = ControlDir.open(repos_url+"/trunk")
        x.destroy_branch()
        self.assertRaises(NotBranchError, x.open_branch)

    def test_bad_dir(self):
        repos_url = self.make_svn_repository("d")

        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo")
        dc.close()

        ControlDir.open(repos_url+"/foo")

    def test_create(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url)
        self.assertTrue(hasattr(x, 'svn_root_url'))

    def test_import_branch(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url+"/trunk")
        origb = ControlDir.create_standalone_workingtree("origb")
        self.build_tree({'origb/twin': 'bla', 'origb/peaks': 'bloe'})
        origb.add(["twin", "peaks"])
        origb.commit("Message")
        b = x.import_branch(source=origb.branch)
        self.assertEquals(origb.branch.last_revision_info(), b.last_revision_info())
        self.assertEquals(origb.branch.last_revision_info(),
                Branch.open(repos_url+"/trunk").last_revision_info())

    def test_open_repos_root(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url)
        repos = x.open_repository()
        self.assertTrue(hasattr(repos, 'uuid'))

    def test_find_repos_nonroot(self):
        repos_url = self.make_svn_repository("d")

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        x = ControlDir.open(repos_url+"/trunk")
        repos = x.find_repository()
        self.assertTrue(hasattr(repos, 'uuid'))

    def test_find_repos_root(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url)
        repos = x.find_repository()
        self.assertTrue(hasattr(repos, 'uuid'))

    def test_open_repos_nonroot(self):
        repos_url = self.make_svn_repository("d")

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        x = ControlDir.open(repos_url+"/trunk")
        self.assertRaises(NoRepositoryPresent, x.open_repository)

    def test_needs_format_upgrade_default(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url+"/trunk")
        self.assertTrue(x.needs_format_conversion(
            format_registry.make_controldir("default")))

    def test_needs_format_upgrade_self(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url+"/trunk")
        self.assertFalse(x.needs_format_conversion(SvnRemoteFormat()))

    def test_find_repository_not_found(self):
        repos_url = self.make_client('d', 'dc')
        osutils.rmtree("d")
        self.assertRaises(NoRepositoryPresent,
                lambda: ControlDir.open("dc").find_repository())

    def test_create_branch_named(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url)
        x.open_repository().store_layout(TrunkLayout())
        b = x.create_branch("foo")
        self.assertEquals(repos_url+"/branches/foo", b.base)

    def test_list_branches_trunk(self):
        repos_url = self.make_svn_repository("d")
        x = ControlDir.open(repos_url)
        x.open_repository().store_layout(TrunkLayout())
        b1 = x.create_branch("foo")
        b2 = x.create_branch("bar")
        self.assertEquals(
            set([b1.base, b2.base]),
            set([b.base for b in x.list_branches()]))


class SvnRemoteFormatTests(TestCase):

    def test_eq(self):
        self.assertEquals(SvnRemoteFormat(), SvnRemoteFormat())
        self.assertNotEquals(SvnRemoteFormat(), "bla")
