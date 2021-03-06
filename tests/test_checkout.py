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

"""Checkout tests."""

from breezy.branch import Branch
from breezy.controldir import (
    ControlDir,
    format_registry,
    )
from breezy.errors import (
    NoRepositoryPresent,
    UninitializableFormat,
    )
from breezy.tests import TestCase

from breezy.plugins.svn.workingtree import (
    SvnWorkingTreeDirFormat,
    SvnWorkingTreeFormat,
    )
from breezy.plugins.svn.tests import SubversionTestCase

class TestWorkingTreeFormat(TestCase):

    def setUp(self):
        super(TestWorkingTreeFormat, self).setUp()
        self.format = SvnWorkingTreeFormat(4)

    def test_get_format_desc(self):
        self.assertEqual("Subversion Working Copy (version 4)",
                         self.format.get_format_description())

    def test_initialize(self):
        self.assertRaises(NotImplementedError, self.format.initialize, None)

    def test_open(self):
        self.assertRaises(NotImplementedError, self.format.open, None)


class TestCheckoutFormat(TestCase):

    def setUp(self):
        super(TestCheckoutFormat, self).setUp()
        self.format = SvnWorkingTreeDirFormat()

    def test_get_converter(self):
        convert = self.format.get_converter(
            format_registry.make_controldir('default'))

    def test_initialize(self):
        self.assertRaises(UninitializableFormat,
                          self.format.initialize_on_transport, None)


class TestCheckout(SubversionTestCase):

    def test_not_for_writing(self):
        self.make_svn_branch_and_tree("d", "dc")
        x = ControlDir.create_branch_convenience("dc/foo")
        self.assertFalse(hasattr(x.repository, "uuid"))

    def test_open_repository(self):
        self.make_svn_branch_and_tree("d", "dc")
        x = ControlDir.open("dc")
        self.assertRaises(NoRepositoryPresent, x.open_repository)

    def test_create_repository(self):
        self.make_svn_branch_and_tree("d", "dc")
        x = ControlDir.open("dc")
        self.assertRaises(UninitializableFormat, x.create_repository)

    def test_find_repository(self):
        self.make_svn_branch_and_tree("d", "dc")
        x = ControlDir.open("dc")
        self.assertRaises(NoRepositoryPresent, x.find_repository)

    def test__find_repository(self):
        self.make_svn_branch_and_tree("d", "dc")
        x = ControlDir.open("dc")
        self.assertTrue(hasattr(x._find_repository(), "uuid"))

    def test_needs_format_conversion_default(self):
        self.make_svn_branch_and_tree("d", "dc")
        x = ControlDir.open("dc")
        self.assertTrue(x.needs_format_conversion(
            format_registry.make_controldir('default')))

    def test_needs_format_conversion_self(self):
        self.make_svn_branch_and_tree("d", "dc")
        x = ControlDir.open("dc")
        self.assertFalse(x.needs_format_conversion(SvnWorkingTreeDirFormat()),
                "%r vs %r" % (x._format.__class__, SvnWorkingTreeDirFormat))

    def test_checkout_checkout(self):
        """Test making a checkout of a checkout."""
        self.make_svn_branch_and_tree("d", "dc")
        x = Branch.open("dc")
        x.create_checkout("de", lightweight=True)

    def test_checkout_branch(self):
        repos_url = self.make_client("d", "dc")

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        self.client_update("dc")
        x = ControlDir.open("dc/trunk")
        self.assertEquals(repos_url+"/trunk", x.open_branch().base)
