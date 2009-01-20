# Copyright (C) 2005-2009 Jelmer Vernooij <jelmer@samba.org>
 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from bzrlib.repository import Repository
from bzrlib.tests import TestCase

from bzrlib.plugins.svn.logwalker import (
        DictBasedLogWalker,
        )
from bzrlib.plugins.svn.mapping import (
        SVN_REVPROP_BZR_BASE_REVISION,
        SVN_REVPROP_BZR_REPOS_UUID,
        SVN_REVPROP_BZR_ROOT,
        SVN_REVPROP_BZR_MAPPING_VERSION,
        mapping_registry,
        )
from bzrlib.plugins.svn.layout.standard import (
        RootLayout,
        TrunkLayout,
        )
from bzrlib.plugins.svn.revmeta import (
        filter_revisions,
        restrict_prefixes,
        RevisionMetadataBrowser,
        RevisionMetadata,
        )
from bzrlib.plugins.svn.tests import SubversionTestCase

from subvertpy.ra import RemoteAccess
from subvertpy.tests import TestCommitEditor


class TestWithRepository(SubversionTestCase):

    def make_provider(self, repos_url):
        r = Repository.open(repos_url)
        return r._revmeta_provider

    def test_checks_uuid(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("bp")
        dc.close()

        mapping = mapping_registry.get_default()()
        ra = RemoteAccess(repos_url.encode("utf-8"))
        revnum = ra.get_latest_revnum()
        revprops = { SVN_REVPROP_BZR_REPOS_UUID: "otheruuid",
                    "svn:log": "bla",
                    SVN_REVPROP_BZR_ROOT: "bp",
                    SVN_REVPROP_BZR_MAPPING_VERSION: mapping.name,
                    SVN_REVPROP_BZR_BASE_REVISION: "therealbaserevid" }
        dc = TestCommitEditor(ra.get_commit_editor(revprops), ra.url, revnum)
        dc.open_dir("bp").add_file("bp/la").modify()
        dc.close()

        repos = Repository.open(repos_url)

        revmeta2 = repos._revmeta_provider.get_revision("bp", 2)

        self.assertEquals(mapping.revision_id_foreign_to_bzr((repos.uuid, "bp", 1)), revmeta2.get_lhs_parent_revid(mapping))

    def test_get_changed_properties(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("myprop", "data\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("myprop", "newdata\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("myp2", "newdata\n")
        dc.close()

        repos = Repository.open(repos_url)

        revmeta1 = repos._revmeta_provider.get_revision("", 1)
        revmeta2 = repos._revmeta_provider.get_revision("", 2)
        revmeta3 = repos._revmeta_provider.get_revision("", 3)

        self.assertFalse(revmeta1.knows_changed_fileprops())

        self.assertEquals((None, "data\n"),
                          revmeta1.get_changed_fileprops()["myprop"])

        self.assertTrue(revmeta1.knows_changed_fileprops())
        self.assertTrue(revmeta1.knows_fileprops())

        self.assertEquals("data\n",
                          revmeta1.get_fileprops()["myprop"])

        self.assertEquals("newdata\n",
                          revmeta2.get_fileprops()["myprop"])

        self.assertEquals(("data\n","newdata\n"), 
                          revmeta2.get_changed_fileprops()["myprop"])

        self.assertEquals((None, "newdata\n"), 
                          revmeta3.get_changed_fileprops()["myp2"])

    def test_changes_branch_root(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("myprop", "data\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bar").modify("bloe")
        dc.close()

        repos = Repository.open(repos_url)

        revmeta1 = repos._revmeta_provider.get_revision("", 1)
        revmeta2 = repos._revmeta_provider.get_revision("", 2)

        self.assertTrue(revmeta1.changes_branch_root())
        self.assertFalse(revmeta2.changes_branch_root())

    def test_get_paths(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("myprop", "data\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bar").modify("bloe")
        dc.close()

        repos = Repository.open(repos_url)

        revmeta1 = repos._revmeta_provider.get_revision("", 1)
        revmeta2 = repos._revmeta_provider.get_revision("", 2)

        self.assertEquals({"": ("M", None, -1)}, revmeta1.get_paths())
        self.assertEquals({"bar": ("A", None, -1)}, 
                          revmeta2.get_paths())

    def test_foreign_revid(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("myprop", "data\n")
        dc.close()

        provider = self.make_provider(repos_url)

        revmeta1 = provider.get_revision("", 1)

        self.assertEquals((provider.repository.uuid, "", 1), 
                revmeta1.get_foreign_revid())

    def test_get_revprops(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("myprop", "data\n")
        dc.close()

        provider = self.make_provider(repos_url)
        revmeta1 = provider.get_revision("", 1)
        self.assertEquals(set(["svn:date", "svn:author", "svn:log"]),
                          set(revmeta1.get_revprops().keys()))

    def test_is_changes_root(self):
        repos_url = self.make_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("bloe")
        dc.close()

        provider = self.make_provider(repos_url)
        revmeta1 = provider.get_revision("", 1)
        self.assertFalse(revmeta1.is_changes_root())
        revmeta1 = provider.get_revision("bloe", 1)
        self.assertTrue(revmeta1.is_changes_root())


class FilterRevisionsTests(TestCase):

    def test_simple(self):
        self.assertEquals([1, 5],
                list(filter_revisions(iter([("revision", 1), ("branch", None), ("revision", 5)]))))

 
class RestrictPrefixesTests(TestCase):

    def test_root(self):
        self.assertEquals(set(["a", "b/c"]), restrict_prefixes(["a", "b/c"], ""))

    def test_prefix_cuts_off(self):
        self.assertEquals(set(["a"]), restrict_prefixes(["a", "b/c"], "a"))

    def test_prefix_restricts(self):
        self.assertEquals(set(["a/d"]), restrict_prefixes(["a", "b/c"], "a/d"))


class FakeRevision(object):

    def __init__(self, path, revnum):
        self.branch_path = path
        self.revnum = revnum
        self._parent_revmeta_set = False
        self.parent_revmeta = None
        self.children = set()

    def _set_direct_lhs_parent_revmeta(self, revmeta):
        assert not self._parent_revmeta_set or revmeta == self.parent_revmeta, \
                "%r != %r" % (self.parent_revmeta, revmeta)
        self._parent_revmeta_set = True
        self.parent_revmeta = revmeta
        if revmeta is not None:
            revmeta.children.add(self)

    def __repr__(self):
        return "FakeRevision(%r,%r)" % (self.branch_path, self.revnum)

    def __eq__(self, other):
        return (type(self) == type(other) and 
                self.branch_path == other.branch_path and 
                self.revnum == other.revnum)


class MetadataBrowserTests(TestCase):

    def get_revision(self, path, revnum, changes=None, revprops=None,
                     changed_fileprops=None, fileprops=None, metaiterator=None):
        return FakeRevision(path, revnum)

    def get_browser(self, prefixes, from_revnum, to_revnum, layout, paths):
        revprops = {}
        for revnum in paths:
            revprops[revnum] = { "svn:log": "Revision %d" % revnum }
        self._log = DictBasedLogWalker(paths, revprops)
        return RevisionMetadataBrowser(prefixes, from_revnum, to_revnum, layout, self)

    def test_root_layout_simple(self):
        browser = self.get_browser(None, 1, 0, RootLayout(), 
                { 1: { "bla": ('A', None, -1)}})
        rev1 = browser.next()
        self.assertEquals(('revision', FakeRevision('',1)), rev1)
        rev2 = browser.next()
        self.assertEquals(('revision', FakeRevision('',0)), rev2)
        self.assertTrue(rev1[1]._parent_revmeta_set)
        self.assertTrue(rev2[1]._parent_revmeta_set)
        self.assertRaises(StopIteration, browser.next)

    def test_trunk_layout_simple(self):
        browser = self.get_browser(None, 2, 0, TrunkLayout(), 
                { 1: { "trunk": ('A', None, -1)},
                  2: { "trunk": ('M', None, -1)}})
        rev1 = browser.next()
        self.assertEquals(('revision', FakeRevision('trunk',2)), rev1)
        rev2 = browser.next()
        self.assertEquals(('revision', FakeRevision('trunk',1)), rev2)
        self.assertTrue(rev1[1]._parent_revmeta_set)
        self.assertTrue(rev2[1]._parent_revmeta_set)
        self.assertRaises(StopIteration, browser.next)

    def test_trunk_layout_movefrom_non_branch(self):
        browser = self.get_browser(None, 2, 0, TrunkLayout(), 
                { 1: { "old-trunk": ('A', None, -1)},
                  2: { "trunk": ('A', "old-trunk", 1)}})
        rev1 = browser.next()
        self.assertEquals(('revision', FakeRevision('trunk',2)), rev1)
        rev2 = browser.next()
        self.assertEquals(('revision', FakeRevision('old-trunk',1)), rev2)
        self.assertTrue(rev1[1]._parent_revmeta_set)
        self.assertTrue(rev2[1]._parent_revmeta_set)
        self.assertRaises(StopIteration, browser.next)

    def test_trunk_layout_movefrom_oldbranch(self):
        browser = self.get_browser(None, 3, 0, TrunkLayout(), 
                { 1: { "old-trunk": ('A', None, -1)},
                  2: { "old-trunk": ('D', None, -1)},
                  3: { "trunk": ('A', "old-trunk", 1)}})
        rev1 = browser.next()
        self.assertEquals(('revision', FakeRevision('trunk',3)), rev1)
        self.assertEquals(('delete', "old-trunk"), browser.next())
        rev2 = browser.next()
        self.assertEquals(('revision', FakeRevision('old-trunk',1)), rev2)
        self.assertTrue(rev1[1]._parent_revmeta_set)
        self.assertTrue(rev2[1]._parent_revmeta_set)
        self.assertRaises(StopIteration, browser.next)

    def test_trunk_layout_copiedbranch(self):
        browser = self.get_browser(None, 2, 0, TrunkLayout(), 
                { 1: { "trunk": ('A', None, -1)},
                  2: { "branches": ('A', None, -1),
                       "branches/foo": ('A', "trunk", 1)}})
        rev1 = browser.next()
        self.assertEquals(('revision', FakeRevision('branches/foo',2)), rev1)
        rev2 = browser.next()
        self.assertEquals(('revision', FakeRevision('trunk',1)), rev2)
        self.assertTrue(rev1[1]._parent_revmeta_set)
        self.assertTrue(rev2[1]._parent_revmeta_set)
        self.assertRaises(StopIteration, browser.next)

    def test_subdir_becomes_branch_root(self):
        browser = self.get_browser(None, 2, 0, TrunkLayout(), 
                { 1: { "trunk": ('A', None, -1),
                       "trunk/mysubdir": ('A', None, -1),
                       "trunk/mysubdir/myfile": ('A', None, -1)},
                  2: { "trunk": ('R', "trunk/mysubdir", 1) }})
        self.assertEquals(('delete', 'trunk'), browser.next())
        rev1 = browser.next()
        self.assertEquals(('revision', FakeRevision('trunk',2)), rev1)
        rev2 = browser.next()
        self.assertEquals(('revision', FakeRevision('trunk/mysubdir',1)), rev2)
        rev3 = browser.next()
        self.assertEquals(('revision', FakeRevision('trunk',1)), rev3)
        self.assertTrue(rev1[1]._parent_revmeta_set)
        self.assertTrue(rev2[1]._parent_revmeta_set)
        self.assertTrue(rev3[1]._parent_revmeta_set)
        self.assertRaises(StopIteration, browser.next)

    def test_copyfrom_revnum_skipped(self):
        browser = self.get_browser(["python"], 4, 0, TrunkLayout(1), 
                { 1: { "python": ('A', None, -1),
                       "python/tags": ('A', None, -1),
                       "python/trunk": ('A', None, -1)},
                  2: { "foo": ('A', None, -1) },
                  3: { "bar": ('A', None, -1) },
                  4: { "python/tags/bla": ('A', 'python/trunk', 2)}})
        rev1 = browser.next()
        self.assertEquals(('revision', FakeRevision('python/tags/bla',4)), rev1)
        rev2 = browser.next()
        self.assertEquals(('revision', FakeRevision('python/trunk',1)), rev2)
        self.assertRaises(StopIteration, browser.next)
        self.assertTrue(rev1[1]._parent_revmeta_set)
