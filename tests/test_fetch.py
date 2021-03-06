# Copyright (C) 2007-2009 Jelmer Vernooij <jelmer@samba.org>
# *-* coding: utf-8 *-*

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


"""Subversion fetch tests."""

import os
import shutil
import sys

from subvertpy import NODE_DIR, NODE_FILE

from breezy.branch import (
    Branch,
    )
from breezy.controldir import (
    ControlDir,
    )
from breezy.osutils import (
    sha_string,
    )
from breezy.repository import (
    Repository,
    )
from breezy.revision import (
    NULL_REVISION,
    )
from breezy.tests import (
    KnownFailure,
    TestCase,
    TestSkipped,
    )
from breezy.tests.features import (
    SymlinkFeature,
    )
from breezy.trace import (
    mutter,
    )

from breezy.plugins.svn import (
    remote,
    )
from breezy.plugins.svn.convert import (
    load_dumpfile,
    )
from breezy.plugins.svn.errors import (
    InvalidFileName,
    SymlinkTargetContainsNewline,
    )
from breezy.plugins.svn.fetch import (
   FetchRevisionFinder,
   InterFromSvnToInventoryRepository,
   check_filename,
   chunks_start_with_link,
   )
from breezy.plugins.svn.layout.standard import (
    RootLayout,
    TrunkLayout,
    )
from breezy.plugins.svn.mapping import (
    SVN_REVPROP_BZR_MAPPING_VERSION,
    SVN_REVPROP_BZR_ROOT,
    )
from breezy.plugins.svn.tests import (
    SubversionTestCase,
    )
from breezy.plugins.svn.transport import (
    SvnRaTransport,
    )


class FetchTestCase(SubversionTestCase):

    def get_inter(self, source, target):
        return InterFromSvnToInventoryRepository(source, target)

    def copy_content(self, source, target, revision_id=None):
        inter = self.get_inter(source, target)
        return inter.copy_content(revision_id=revision_id)

    def fetch(self, source, target, revision_id=None):
        inter = self.get_inter(source, target)
        return inter.fetch(revision_id=revision_id)


class TestFetchWorks(FetchTestCase):

    def test_fetch_trunk1(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        proj1 = dc.add_dir("proj1")
        trunk = proj1.add_dir("proj1/trunk")
        trunk.add_file("proj1/trunk/file").modify("data")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(1))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_replace_from_branch(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        t = dc.add_dir("trunk")
        ch = t.add_dir("trunk/check")
        ch.add_dir("trunk/check/debian")
        ch.add_file("trunk/check/stamp-h.in").modify("foo")
        dc.add_dir("tags")
        dc.close() #1

        dc = self.get_commit_editor(repos_url)
        t = dc.open_dir("trunk")
        ch = t.open_dir("trunk/check")
        deb = ch.open_dir("trunk/check/debian")
        deb.add_file("trunk/check/debian/pl").modify("bar")
        dc.close() #2

        dc = self.get_commit_editor(repos_url)
        t = dc.open_dir("trunk")
        ch = t.open_dir("trunk/check")
        deb = ch.open_dir("trunk/check/debian")
        deb.add_file("trunk/check/debian/voo").modify("bar")
        dc.close() #3

        dc = self.get_commit_editor(repos_url)
        t = dc.open_dir("trunk")
        ch = t.open_dir("trunk/check")
        deb = ch.open_dir("trunk/check/debian")
        deb.add_file("trunk/check/debian/blie").modify("oeh")
        dc.close() #4

        dc = self.get_commit_editor(repos_url)
        t = dc.open_dir("trunk")
        ch = t.open_dir("trunk/check")
        deb = ch.open_dir("trunk/check/debian")
        deb.add_file("trunk/check/debian/bar").modify("oeh")
        ch.add_file("trunk/check/bar").modify("bla")
        dc.close() #5

        self.make_checkout(repos_url, "dc")
        self.client_copy("dc/trunk", "dc/tags/R_0_9_2", revnum=2)
        self.client_delete("dc/tags/R_0_9_2/check/debian")
        shutil.rmtree("dc/tags/R_0_9_2/check/debian")
        self.client_copy("dc/trunk/check/debian", "dc/tags/R_0_9_2/check/debian",
                         revnum=5)
        self.client_delete("dc/tags/R_0_9_2/check/stamp-h.in")
        self.client_copy("dc/trunk/check/stamp-h.in", "dc/tags/R_0_9_2/check/stamp-h.in",
                         revnum=4)
        self.build_tree({"dc/tags/R_0_9_2/check/debian/blie": "oehha"})
        self.client_update("dc")
        self.client_commit("dc", "strange revision") # 6
        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_backslash(self):
        if sys.platform == 'win32':
            raise TestSkipped("Unable to create filenames with backslash on Windows")
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/file\\part").modify("data")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.assertRaises(InvalidFileName, self.copy_content, oldrepos,
                newrepos)

    def test_fetch_null(self):
        repos_url = self.make_svn_repository('d')
        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(1))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos, NULL_REVISION)

    def test_fetch_copy_remove_old(self):
        repos_url = self.make_client('d', 'dc')
        self.build_tree({'dc/trunk/afile': 'foo', 'dc/tags': None,
                         'dc/branches': None})
        self.client_add("dc/trunk")
        self.client_add("dc/tags")
        self.client_add("dc/branches")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        self.client_copy("dc/trunk", "dc/branches/blal")
        self.build_tree({'dc/branches/blal/afile': "bar"})
        self.client_commit("dc", "Msg")
        self.client_update("dc")
        self.client_copy("dc/trunk", "dc/tags/bla")
        self.client_delete("dc/tags/bla/afile")
        self.client_copy("dc/branches/blal/afile", "dc/tags/bla/afile")
        self.client_commit("dc", "My Message")
        self.client_update("dc")
        oldrepos = Repository.open(repos_url)
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_special_char(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file(u"trunk/f\x2cle".encode("utf-8")).modify("data")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_signature(self):
        repos_url = self.make_svn_repository('d')
        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/bar").modify("data")
        dc.close()
        self.client_set_revprop(repos_url, 1, "bzr:gpg-signature", "SIGNATURE")
        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        self.assertEquals("SIGNATURE", newrepos.get_signature_text(oldrepos.generate_revision_id(1, u"trunk", oldrepos.get_mapping())))

    def test_fetch_invalid_svk_rev(self):
        repos_url = self.make_svn_repository('d')

        uuid = SvnRaTransport(repos_url).get_uuid()

        dc = self.get_commit_editor(repos_url)
        branches = dc.add_dir("branches")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/bar").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.change_prop("svk:merge", "%s:/branches/trunk:1\n" % uuid)
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        rf = FetchRevisionFinder(oldrepos, newrepos)
        rm = oldrepos._revmeta_provider.get_revision(u"trunk", 3)
        mapping = oldrepos.get_mapping()
        self.assertEquals((uuid, u"trunk", 3), rm.metarev.get_foreign_revid())
        self.assertEquals(
            (mapping.revision_id_foreign_to_bzr((uuid, u"branches/trunk", 1)), ),
            rm.get_rhs_parents(mapping, rm.get_lhs_parent_revmeta(mapping)))
        self.assertEquals([], list(rf.find_rhs_parents([(rm, mapping)])))

    def test_fetch_file_branch(self):
        repos_url = self.make_svn_repository('d')
        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_file("trunk")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_special_char_edit(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_dir(u'trunk/IöC'.encode("utf-8"))
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.add_file(u'trunk/IöC/bar'.encode("utf-8")).modify("more data")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_special_char_child(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        raardir = trunk.add_dir(u"trunk/é".encode("utf-8"))
        raardir.add_file(u'trunk/é/f\x2cle'.encode("utf-8")).modify("data")
        dc.close()
        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_special_char_modify(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file(u"trunk/€\x2c".encode("utf-8")).modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        dc.open_file(u"trunk/€\x2c".encode("utf-8")).modify("bar")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_delete(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        foo = dc.add_dir("foo")
        foo.add_file("foo/bla").modify("data")
        dc.close()
        oldrepos = Repository.open(repos_url)
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

        dc = self.get_commit_editor(repos_url)
        foo = dc.open_dir("foo")
        foo.delete('foo/bla')
        dc.close()

        newrepos = Repository.open("f")
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(oldrepos.has_revision(oldrepos.generate_revision_id(2, u"", mapping)))

    def test_fetch_delete_recursive(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        foo = dc.add_dir("foo")
        foo.add_file("foo/bla").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.delete('foo')
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        tree = newrepos.revision_tree(oldrepos.generate_revision_id(1, u"", mapping))
        self.assertEquals(3, len(tree.all_file_ids()))
        tree = newrepos.revision_tree(oldrepos.generate_revision_id(2, u"", mapping))
        self.assertEquals(1, len(tree.all_file_ids()))

    def test_fetch_local(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        foo = dc.add_dir("foo")
        foo.add_file("foo/bla").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        foo = dc.open_dir("foo")
        foo.add_file("foo/blo").modify("data2")
        foo.open_file("foo/bla").modify("data")
        bar = dc.add_dir("bar")
        bar.add_file("bar/foo").modify("data3")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(2, u"", mapping)))
        with newrepos.lock_read():
            tree = newrepos.revision_tree(
                    oldrepos.generate_revision_id(2, u"", mapping))
            self.assertTrue(tree.has_filename("foo/bla"))
            self.assertTrue(tree.has_filename("foo"))
            self.assertEqual("data", tree.get_file_text("foo/bla"))

    def test_fetch_mapping_upgrade(self):
        from breezy.plugins.svn.mapping3.base import BzrSvnMappingv3
        from breezy.plugins.svn.mapping3.scheme import TrunkBranchingScheme
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        br1 = dc.add_dir("trunk")
        br2 = br1.add_dir("trunk/bloe")
        br2.add_file("trunk/bloe/README").modify("BLA")
        dc.close()

        old_mapping = BzrSvnMappingv3(TrunkBranchingScheme(0))
        self.client_set_revprop(repos_url, 1, SVN_REVPROP_BZR_MAPPING_VERSION, old_mapping.name)
        self.client_set_revprop(repos_url, 1, SVN_REVPROP_BZR_ROOT, "trunk")

        dc = self.get_commit_editor(repos_url)
        dc.open_dir("trunk").add_file("trunk/a").modify("LA")
        dc.close()

        oldrepos = Repository.open(repos_url)
        to_controldir = ControlDir.create("f")
        repo = to_controldir.create_repository()
        revfinder = FetchRevisionFinder(oldrepos, repo)
        new_mapping = oldrepos.get_mapping()
        revfinder.find_all(new_mapping, TrunkLayout())
        self.assertEquals(
            [("trunk", 1, old_mapping), ("trunk", 2, new_mapping)],
            [(rm.metarev.branch_path, rm.metarev.revnum, mapping) for (rm, mapping) in revfinder.needed])

    def test_fetch_move_root(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        br1 = dc.add_dir("branch1")
        br2 = br1.add_dir("branch1/bloe")
        br2.add_file("branch1/bloe/README").modify("BLA")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("branch2", "branch1")
        dc.delete("branch1")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        br1 = dc.open_dir("branch2")
        bloe = br1.open_dir("branch2/bloe")
        bloe.open_file("branch2/bloe/README").modify("TEST")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        to_controldir = ControlDir.create("f")
        repo = to_controldir.create_repository()
        last_rev = oldrepos.generate_revision_id(3, u"branch2",
            oldrepos.get_mapping())
        self.fetch(oldrepos, repo, last_rev)
        self.assertEquals(repo.revision_tree(last_rev).get_root_id(),
            oldrepos.get_mapping().generate_file_id(
                (oldrepos.uuid, "branch1", 1), u""))


    def test_fetch_replace(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bla").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.delete('bla')
        dc.add_file("bla").modify("data2")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(2, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        tree2 = newrepos.revision_tree(
                oldrepos.generate_revision_id(2, u"", mapping))
        self.assertNotEqual(tree1.path2id("bla"), tree2.path2id("bla"))

    def test_fetch_copy_subdir(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        mydir = trunk.add_dir("trunk/mydir")
        mydir.add_file("trunk/mydir/a").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.add_dir("branches")
        branches.add_dir("branches/tmp")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.open_dir("branches")
        tmp = branches.open_dir("branches/tmp")
        tmp.add_dir("branches/tmp/abranch", "trunk/mydir")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_replace_nordic(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 606c7b1f-987c-4826-b37d-eb556ceb87e1

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-26T00:04:55.850520Z
PROPS-END

Revision-number: 1
Prop-content-length: 103
Content-length: 103

K 7
svn:log
V 3
add
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:15.504335Z
PROPS-END

Node-path: x\xc3\xa1
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Node-path: u\xc3\xa1
Node-path: bla
Node-kind: file
Node-action: add
Prop-content-length: 10
Text-content-length: 5
Text-content-md5: 49803c8f7913948eb3e30bae749ae6bd
Content-length: 15

PROPS-END
bloe


Revision-number: 2
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
readd
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:43.584249Z
PROPS-END

Node-path: x\xc3\xa1
Node-action: delete

""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        self.assertTrue(tree1.has_filename(u"x\xe1"))

    def test_fetch_replace_with_subreplace(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 606c7b1f-987c-4826-b37d-eb456ceb87e1

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-26T00:04:55.850520Z
PROPS-END

Revision-number: 1
Prop-content-length: 103
Content-length: 103

K 7
svn:log
V 3
add
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:15.504335Z
PROPS-END

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Node-path: x/t
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Node-path: u
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END

Revision-number: 2
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
readd
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:43.584249Z
PROPS-END

Node-path: x
Node-action: delete

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 3
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: x
Node-action: delete

Node-path: y
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x

Node-path: y/t
Node-action: delete

Node-path: y/t
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: u


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        tree2 = newrepos.revision_tree(
                oldrepos.generate_revision_id(3, u"", mapping))

    def test_fetch_replace_self(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 6dcc86fc-ac21-4df7-a3a3-87616123c853

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-25T04:27:54.633666Z
PROPS-END

Revision-number: 1
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Add dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:17.503039Z
PROPS-END

Node-path: bla
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 117
Content-length: 117

K 7
svn:log
V 16
Add another dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:30.160663Z
PROPS-END

Node-path: blie
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
Copy

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:44.996894Z
PROPS-END

Node-path: bloe
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: bla


Revision-number: 4
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: bla
Node-action: delete


Node-path: bla
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 2
Node-copyfrom-path: bla


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        tree2 = newrepos.revision_tree(
                oldrepos.generate_revision_id(3, u"", mapping))
        self.assertEqual(tree1.path2id("bla"), tree2.path2id("bla"))

    def test_fetch_replace_backup(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 6dcc86fc-ac21-4df7-a3a3-87616123c853

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-25T04:27:54.633666Z
PROPS-END

Revision-number: 1
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Add dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:17.503039Z
PROPS-END

Node-path: bla
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 117
Content-length: 117

K 7
svn:log
V 16
Add another dir

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:30.160663Z
PROPS-END

Node-path: blie
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
Copy

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:28:44.996894Z
PROPS-END

Node-path: bloe
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: bla


Revision-number: 4
Prop-content-length: 112
Content-length: 112

K 7
svn:log
V 11
Change bla

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T23:51:09.678679Z
PROPS-END

Node-path: bla
Node-kind: dir
Node-action: change
Prop-content-length: 28
Content-length: 28

K 3
foo
V 5
bloe

PROPS-END


Revision-number: 5
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: bla
Node-action: delete


Node-path: bla
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: bla


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        tree2 = newrepos.revision_tree(
                oldrepos.generate_revision_id(3, u"", mapping))
        self.assertEqual(tree1.path2id("bla"), tree2.path2id("bla"))

    def test_fetch_replace_unrelated(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 606c7b1f-987c-4826-b37d-eb456ceb87e1

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-26T00:04:55.850520Z
PROPS-END

Revision-number: 1
Prop-content-length: 103
Content-length: 103

K 7
svn:log
V 3
add
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:15.504335Z
PROPS-END

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 102
Content-length: 102

K 7
svn:log
V 2
rm
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:30.775369Z
PROPS-END

Node-path: x
Node-action: delete


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
readd
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:43.584249Z
PROPS-END

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 4
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: x
Node-action: delete


Node-path: x
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(4, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        tree2 = newrepos.revision_tree(
                oldrepos.generate_revision_id(4, u"", mapping))
        self.assertNotEqual(tree1.path2id("x"), tree2.path2id("x"))

    def test_fetch_replace_related(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        open(filename, 'w').write("""SVN-fs-dump-format-version: 2

UUID: 606c7b1f-987c-4826-b37d-eb456ceb87e1

Revision-number: 0
Prop-content-length: 56
Content-length: 56

K 8
svn:date
V 27
2006-12-26T00:04:55.850520Z
PROPS-END

Revision-number: 1
Prop-content-length: 103
Content-length: 103

K 7
svn:log
V 3
add
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:15.504335Z
PROPS-END

Node-path: x
Node-kind: dir
Node-action: add
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 2
Prop-content-length: 102
Content-length: 102

K 7
svn:log
V 2
rm
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:30.775369Z
PROPS-END

Node-path: x
Node-action: delete


Revision-number: 3
Prop-content-length: 105
Content-length: 105

K 7
svn:log
V 5
readd
K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-26T00:05:43.584249Z
PROPS-END

Node-path: y
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x
Prop-content-length: 10
Content-length: 10

PROPS-END


Revision-number: 4
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END

Node-path: y
Node-action: delete


Revision-number: 5
Prop-content-length: 108
Content-length: 108

K 7
svn:log
V 8
Replace

K 10
svn:author
V 6
jelmer
K 8
svn:date
V 27
2006-12-25T04:30:06.383777Z
PROPS-END


Node-path: y
Node-kind: dir
Node-action: add
Node-copyfrom-rev: 1
Node-copyfrom-path: x


""")
        os.mkdir("old")

        load_dumpfile("dumpfile", "old")
        oldrepos = Repository.open("old")
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(5, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        tree2 = newrepos.revision_tree(
                oldrepos.generate_revision_id(5, u"", mapping))
        self.assertNotEqual(tree1.path2id("y"), tree2.path2id("y"))

    def test_fetch_dir_replace_self(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("branches")
        trunk = dc.add_dir("trunk")
        dir1 = trunk.add_dir("trunk/dir1")
        dir2 = dir1.add_dir("trunk/dir1/dir2")
        dir3 = dir2.add_dir("trunk/dir1/dir2/dir3")
        file = dir3.add_file("trunk/dir1/dir2/dir3/file.txt")
        file.modify()
        file = dir1.add_file("trunk/dir1/file.txt")
        file.modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        dir1 = trunk.open_dir("trunk/dir1")
        dir1.open_file("trunk/dir1/file.txt").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        dir1 = trunk.open_dir("trunk/dir1")
        dir2 = dir1.open_dir("trunk/dir1/dir2")
        dir3 = dir1.open_dir("trunk/dir1/dir2/dir3")
        dir3.open_file("trunk/dir1/dir2/dir3/file.txt").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.open_dir("branches")
        branch1 = branches.add_dir("branches/1.0", "trunk", 3)
        branch1.delete("branches/1.0/dir1")
        branch1.add_dir("branches/1.0/dir1", "trunk/dir1", 2)
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        lastrevid = oldrepos.generate_revision_id(4, u"branches/1.0", oldrepos.get_mapping())
        tree = newrepos.revision_tree(lastrevid)
        self.assertTrue(tree.path2id("dir1/file.txt") is not None)

    def test_fetch_dir_upgrade(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        lib = trunk.add_dir("trunk/lib")
        lib.add_file("trunk/lib/file").modify('data')
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.add_dir("branches")
        branches.add_dir("branches/mybranch", "trunk/lib")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

        branch = Branch.open("%s/branches/mybranch" % repos_url)
        mapping = oldrepos.get_mapping()
        self.assertEqual(oldrepos.generate_revision_id(2, u"branches/mybranch", mapping),
                         branch.last_revision())

    def test_fetch_dir_from_non_branch(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        old_trunk = dc.add_dir("old-trunk")
        lib = old_trunk.add_dir("old-trunk/lib")
        lib.add_file("old-trunk/lib/file").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_dir("trunk/lib", "old-trunk/lib")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

        branch = Branch.open("%s/trunk" % repos_url)
        self.assertEqual(oldrepos.generate_revision_id(2, u"trunk", oldrepos.get_mapping()),
                         branch.last_revision())

    def test_fetch_from_non_branch(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        ot = dc.add_dir("old-trunk")
        lib = ot.add_dir("old-trunk/lib")
        lib.add_file("old-trunk/lib/file").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk", "old-trunk")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

        branch = Branch.open("%s/trunk" % repos_url)
        self.assertEqual(
            oldrepos.generate_revision_id(2, u"trunk", oldrepos.get_mapping()),
            branch.last_revision())

    def test_fetch_branch_downgrade(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/file").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.add_dir("branches")
        mybranch = branches.add_dir("branches/mybranch")
        mybranch.add_dir("branches/mybranch/lib", "trunk")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_all(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/hosts").modify('hej1')
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir('trunk')
        trunk.open_file('trunk/hosts').modify('hej2')
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir('trunk')
        trunk.open_file('trunk/hosts').modify('hej3')
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.add_dir("branches")
        foobranch = branches.add_dir("branches/foobranch")
        foobranch.add_file("branches/foobranch/file").modify('foohosts')
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

        mapping = oldrepos.get_mapping()

        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"trunk", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(2, u"trunk", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(3, u"trunk", mapping)))
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(4, u"branches/foobranch", mapping)))
        self.assertFalse(newrepos.has_revision(
            oldrepos.generate_revision_id(4, u"trunk", mapping)))
        self.assertFalse(newrepos.has_revision(
            oldrepos.generate_revision_id(2, u"", mapping)))

    def test_fetch_copy_root_id_kept(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir('trunk')
        trunk.add_file("trunk/hosts").modify("hej1")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("branches")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.open_dir("branches")
        branches.add_dir("branches/foobranch", "trunk")
        dc.close()

        repos = remote.SvnRemoteAccess(SvnRaTransport(repos_url),
                remote.SvnRemoteFormat()).find_repository()
        repos.set_layout(TrunkLayout(0))

        mapping = repos.get_mapping()

        tree = repos.revision_tree(
             repos.generate_revision_id(3, u"branches/foobranch", mapping))

        self.assertEqual(
            mapping.generate_file_id((repos.uuid, "trunk", 1), u""),
            tree.get_root_id())

    def test_fetch_odd(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/hosts").modify('hej1')
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.open_file("trunk/hosts").modify("hej2")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.open_file("trunk/hosts").modify("hej3")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("branches")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.open_dir("branches").add_dir("branches/foobranch", "trunk")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.open_dir("branches")
        foobranch = branches.open_dir("branches/foobranch")
        foobranch.open_file("branches/foobranch/hosts").modify('foohosts')
        dc.close()

        repos = remote.SvnRemoteAccess(SvnRaTransport(repos_url), remote.SvnRemoteFormat()).find_repository()
        repos.set_layout(TrunkLayout(0))

        mapping = repos.get_mapping()

        tree = repos.revision_tree(
             repos.generate_revision_id(6, u"branches/foobranch", mapping))

    def test_fetch_consistent(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        f = dc.add_file("bla")
        f.modify("data")
        f.change_prop("svn:executable", "*")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir1 = ControlDir.create("f")
        dir2 = ControlDir.create("g")
        newrepos1 = dir1.create_repository()
        newrepos2 = dir2.create_repository()
        self.copy_content(oldrepos, newrepos1)
        self.copy_content(oldrepos, newrepos2)
        mapping = oldrepos.get_mapping()
        tree1 = newrepos1.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        tree2 = newrepos2.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        self.assertFalse(tree1.changes_from(tree2).has_changed())

    def test_fetch_executable(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        bla = dc.add_file("bla")
        bla.modify('data')
        bla.change_prop("svn:executable", "*")
        blie = dc.add_file("blie")
        blie.modify("data2")
        blie.change_prop("svn:executable", "")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        self.assertTrue(tree1.is_executable("bla"))
        self.assertTrue(tree1.is_executable("blie"))

    def test_fetch_executable_persists(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        bla = dc.add_file("bla")
        bla.modify('data')
        bla.change_prop("svn:executable", "*")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.open_file("bla").modify("data2")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        self.assertTrue(tree1.is_executable("bla"))
        tree2 = newrepos.revision_tree(
                oldrepos.generate_revision_id(2, u"", mapping))
        self.assertTrue(tree2.is_executable("bla"))

    def test_fetch_symlink(self):
        self.requireFeature(SymlinkFeature)
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bla").modify("data")
        l = dc.add_file("mylink")
        l.modify("link bla")
        l.change_prop("svn:special", "*")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        file_id = tree1.path2id("mylink")
        self.assertEqual('symlink', tree1.kind('mylink'))
        self.assertEqual('bla', tree1.get_symlink_target('mylink'))
        self.assertEquals(None, tree1.get_file_sha1('mylink'))
        key = (file_id, tree1.get_file_revision('mylink'))
        with newrepos.lock_read():
            self.assertEquals(sha_string(""),
                newrepos.texts.get_sha1s([key])[key])

    def test_fetch_symlink_with_newlines(self):
        self.requireFeature(SymlinkFeature)
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bla").modify("data")
        l = dc.add_file("mylink")
        l.modify("link bla\nbar\nbla")
        l.change_prop("svn:special", "*")
        dc.close()

        oldrepos = Repository.open(repos_url)
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        try:
            self.copy_content(oldrepos, newrepos)
        except SymlinkTargetContainsNewline:
            raise KnownFailure(
                "Bazaar doesn't support newlines in symlink targets (#219832)")
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        self.assertEqual('symlink', tree1.kind("mylink"))
        self.assertEqual('bla\nbar\nbla',
            tree1.get_symlink_target("mylink"))

    def test_fetch_special_non_symlink(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        l = dc.add_file("mylink")
        l.modify("")
        l.change_prop("svn:special", "*")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        self.assertEqual('file', tree1.kind("mylink"))

    def test_fetch_special_unbecomes_symlink(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        l = dc.add_file("mylink")
        l.modify("link bla")
        l.change_prop("svn:special", "*")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        l = dc.open_file("mylink")
        l.modify("bloebla")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(2, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(2, u"", mapping))
        self.assertEqual('file', tree1.kind("mylink"))

        # Now test the same thing again as two separate copy_content calls, to
        # check it also works if the symlink's "text" is not in the fetch
        # text_cache.
        dir2 = ControlDir.create("f2")
        newrepos2 = dir2.create_repository()
        self.copy_content(oldrepos, newrepos2,
              oldrepos.generate_revision_id(1, u"", mapping))
        self.copy_content(oldrepos, newrepos2)
        self.assertTrue(newrepos2.has_revision(
            oldrepos.generate_revision_id(2, u"", mapping)))
        tree2 = newrepos2.revision_tree(
                oldrepos.generate_revision_id(2, u"", mapping))
        self.assertEqual('file', tree2.kind("mylink"))

    def test_fetch_special_becomes_symlink(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        l = dc.add_file("mylink")
        l.change_prop("svn:special", "*")
        l.modify("bloebla")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        l = dc.open_file("mylink")
        l.modify("link bla")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(2, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(2, u"", mapping))
        self.expectFailure(
            "not allowing svn:special invalid files to be restored to symlinks "
            "yet",
            self.assertEqual,
            'symlink', tree1.kind("mylink"))

    def test_fetch_symlink_kind_change(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bla").modify("data")
        dc.add_file("mylink").modify("link bla")
        dc.close()
        ra = SvnRaTransport(repos_url)
        dc = self.get_commit_editor(repos_url)
        dc.open_file("mylink").change_prop("svn:special", "*")
        dc.close()
        oldrepos = Repository.open(repos_url)
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        oldrepos.set_layout(RootLayout())
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        tree2 = newrepos.revision_tree(
                oldrepos.generate_revision_id(2, u"", mapping))
        self.assertEqual('file', tree1.kind("mylink"))
        self.assertEqual('symlink', tree2.kind("mylink"))
        self.assertEqual('bla', tree2.get_symlink_target("mylink"))

    def test_fetch_executable_separate(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        dc.add_file("bla").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.open_file("bla").change_prop("svn:executable", "*")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(
            oldrepos.generate_revision_id(1, u"", mapping)))
        tree1 = newrepos.revision_tree(
                oldrepos.generate_revision_id(1, u"", mapping))
        self.assertFalse(tree1.is_executable("bla"))
        tree2 = newrepos.revision_tree(
                oldrepos.generate_revision_id(2, u"", mapping))
        self.assertTrue(tree2.is_executable("bla"))
        self.assertEqual(oldrepos.generate_revision_id(2, u"", mapping),
                         tree2.get_file_revision("bla"))

    def test_fetch_hidden(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/bla").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.add_dir("branches")
        branch = branches.add_dir("branches/brancha", "trunk")
        dc.close()

        self.client_set_revprop(repos_url, 2, "bzr:hidden", "")
        self.client_set_revprop(repos_url, 2, "bzr:root", "branches/brancha")

        dc = self.get_commit_editor(repos_url)
        branches = dc.open_dir("branches")
        brancha = branches.open_dir("branches/brancha")
        brancha.add_file("branches/brancha/lala")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

        mapping = oldrepos.get_mapping()
        self.assertTrue(newrepos.has_revision(mapping.revision_id_foreign_to_bzr((oldrepos.uuid, u"branches/brancha", 3))))
        self.assertTrue(newrepos.has_revision(mapping.revision_id_foreign_to_bzr((oldrepos.uuid, u"trunk", 1))))
        self.assertFalse(newrepos.has_revision(mapping.revision_id_foreign_to_bzr((oldrepos.uuid, "branches/brancha", 2))))

    def test_fetch_svk_merge(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/bla").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        branches = dc.add_dir("branches")
        foo = branches.add_dir("branches/foo", "trunk")
        foo.open_file("branches/foo/bla").modify("more data")
        dc.close()

        oldrepos = Repository.open(repos_url)

        dc = self.get_commit_editor(repos_url)
        dc.open_dir("trunk").change_prop("svk:merge",
                             "%s:/branches/foo:2\n" % oldrepos.uuid)
        dc.close()

        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

        mapping = oldrepos.get_mapping()

        rev = newrepos.get_revision(oldrepos.generate_revision_id(3, u"trunk", mapping))
        mutter('parent ids: %r' % rev.parent_ids)
        self.assertTrue(oldrepos.generate_revision_id(2, u"branches/foo", mapping) in rev.parent_ids)

    def build_intertwined(self):
        repos_url = self.make_svn_repository('d')
        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.change_prop("bzr:revision-id:v3-trunk0", "1 revid1\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.change_prop("bzr:revision-id:v3-trunk0", "1 revid1\n"
                                                       "2 revid2\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.change_prop("bzr:revision-id:v4", "3 revid3\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.change_prop("bzr:revision-id:v3-trunk0", "1 revid1\n"
                                                       "2 revid2\n"
                                                       "4 revid4\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.change_prop("bla", "bloe")
        dc.close()

        return repos_url

    def test_fetch_intertwined_mappings_old(self):
        repos_url = self.build_intertwined()
        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos, "revid4")
        from breezy.plugins.svn.mapping3.base import BzrSvnMappingv3
        from breezy.plugins.svn.mapping3.scheme import TrunkBranchingScheme
        revid3 = oldrepos.generate_revision_id(3, u"trunk",
                BzrSvnMappingv3(TrunkBranchingScheme(0)))
        self.assertEquals(set(["revid1", "revid2", revid3, "revid4"]),
                set(newrepos.all_revision_ids()))

    def test_fetch_intertwined_mappings_new(self):
        repos_url = self.build_intertwined()
        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        from breezy.plugins.svn.mapping4 import BzrSvnMappingv4
        revid5 = oldrepos.generate_revision_id(5, u"trunk", BzrSvnMappingv4())
        self.copy_content(oldrepos, newrepos, revid5)
        from breezy.plugins.svn.mapping3.base import BzrSvnMappingv3
        from breezy.plugins.svn.mapping3.scheme import TrunkBranchingScheme
        revid3 = oldrepos.generate_revision_id(3, u"trunk",
                BzrSvnMappingv3(TrunkBranchingScheme(0)))
        self.assertEquals(set(["revid1", "revid2", revid3, "revid4", revid5]),
                set(newrepos.all_revision_ids()))

    def test_fetch_property_change_only(self):
        repos_url = self.make_svn_repository('d')
        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/bla").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("some:property", "some data\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("some2:property", "some data\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.change_prop("some:property", "some data4\n")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(RootLayout())
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertEquals(set([
            oldrepos.generate_revision_id(0, u"", mapping),
            oldrepos.generate_revision_id(1, u"", mapping),
            oldrepos.generate_revision_id(2, u"", mapping),
            oldrepos.generate_revision_id(3, u"", mapping),
            oldrepos.generate_revision_id(4, u"", mapping),
            ]), set(newrepos.all_revision_ids()))

    def test_fetch_property_change_only_trunk(self):
        repos_url = self.make_svn_repository('d')
        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/bla").modify("data")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.change_prop("some:property", "some data\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.change_prop("some2:property", "some data\n")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.change_prop("some:property", "some data3\n")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)
        mapping = oldrepos.get_mapping()
        self.assertEquals(set([
            oldrepos.generate_revision_id(1, u"trunk", mapping),
            oldrepos.generate_revision_id(2, u"trunk", mapping),
            oldrepos.generate_revision_id(3, u"trunk", mapping),
            oldrepos.generate_revision_id(4, u"trunk", mapping),
            ]), set(newrepos.all_revision_ids()))

    def test_fetch_replace_self_open(self):
        # Not actually a replace, merely just an open. Bug #308353
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        adir = trunk.add_dir("trunk/adir")
        adir.add_file("trunk/adir/afile").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("otherbranch")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.delete("trunk/adir")
        newdir = trunk.add_dir("trunk/adir", "trunk/adir", 2)
        newdir.add_file("trunk/adir/foofile").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        adir = trunk.open_dir("trunk/adir")
        adir.open_file("trunk/adir/afile").modify()
        dc.close()

        oldrepos = Repository.open(repos_url)
        self.assertChangedPathsEquals({
            'trunk/adir': (u'R', 'trunk/adir', 2, NODE_DIR),
            'trunk/adir/foofile': (u'A', None, -1, NODE_FILE)},
              oldrepos._revmeta_provider.get_revision(u"trunk", 3).metarev.paths)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_replace_self_open_older(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        adir = trunk.add_dir("trunk/adir")
        adir.add_file("trunk/adir/afile").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.open_dir("trunk/adir").add_dir("trunk/adir/cdir")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        trunk.delete("trunk/adir")
        newdir = trunk.add_dir("trunk/adir", "trunk/adir", 1)
        newdir.add_file("trunk/adir/foofile").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.open_dir("trunk")
        adir = trunk.open_dir("trunk/adir")
        adir.open_file("trunk/adir/afile").modify()
        dc.close()

        oldrepos = Repository.open(repos_url)
        self.assertChangedPathsEquals({
            'trunk/adir': (u'R', 'trunk/adir', 1, NODE_DIR),
            'trunk/adir/foofile': (u'A', None, -1, NODE_FILE)},
              oldrepos._revmeta_provider.get_revision(u"trunk", 3).metarev.paths)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        self.copy_content(oldrepos, newrepos)

    def test_fetch_crosscopy(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        adir = trunk.add_dir("trunk/adir")
        adir.add_file("trunk/adir/afile").modify("data")
        adir.add_dir("trunk/adir/stationary")
        dc.add_dir("branches").add_dir("branches/abranch")
        dc.close()

        # copyrev
        dc = self.get_commit_editor(repos_url)
        abranch = dc.open_dir("branches").open_dir("branches/abranch")
        abranch.add_dir("branches/abranch/bdir", "trunk/adir")
        dc.close()

        # prevrev
        dc = self.get_commit_editor(repos_url)
        bdir = dc.open_dir("branches").open_dir("branches/abranch").open_dir("branches/abranch/bdir")
        bdir.open_file("branches/abranch/bdir/afile").modify("otherdata")
        dc.close()

        # lastrev
        dc = self.get_commit_editor(repos_url)
        bdir = dc.open_dir("branches").open_dir("branches/abranch").open_dir("branches/abranch/bdir")
        bdir.add_file("branches/abranch/bdir/bfile").modify("camel")
        stationary = bdir.open_dir("/branches/abranch/bdir/stationary")
        stationary.add_file("branches/abranch/bdir/stationary/traveller").modify("data")
        dc.close()

        oldrepos = Repository.open(repos_url)
        oldrepos.set_layout(TrunkLayout(0))
        dir = ControlDir.create("f")
        newrepos = dir.create_repository()
        mapping = oldrepos.get_mapping()
        copyrev = oldrepos.generate_revision_id(2, u"branches/abranch", mapping)
        prevrev = oldrepos.generate_revision_id(3, u"branches/abranch", mapping)
        lastrev = oldrepos.generate_revision_id(4, u"branches/abranch", mapping)
        self.copy_content(oldrepos, newrepos, lastrev)

        tree = newrepos.revision_tree(lastrev)
        self.assertEqual(prevrev,
                         tree.get_file_revision("bdir/afile"))

        tree = newrepos.revision_tree(prevrev)
        self.assertEqual(copyrev,
                         tree.get_file_revision("bdir/stationary"))

    def test_fetch_different_parent_path(self):
        repos_url = self.make_svn_repository('d')

        dc = self.get_commit_editor(repos_url)
        myproj = dc.add_dir("myproj")
        trunk = myproj.add_dir("myproj/trunk")
        trunk.add_file("myproj/trunk/afile").modify()
        dc.close()

        dc = self.get_commit_editor(repos_url)
        dc.add_dir("oldlayout")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        oldlayout = dc.open_dir("oldlayout")
        oldlayout.add_dir("oldlayout/myproj", "myproj")
        dc.delete("myproj")
        dc.close()

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_dir("trunk/myproj", "oldlayout/myproj/trunk")
        oldlayout = dc.open_dir("oldlayout")
        myproj = oldlayout.open_dir("oldlayout/myproj")
        myproj.delete("oldlayout/myproj/trunk")
        dc.close()

        oldbranch = ControlDir.open(repos_url+"/trunk/myproj")
        oldbranch.sprout("dc")


class ChunksStartWithLinkTests(TestCase):

    def test_simple(self):
        vf = ["not", "a link"]
        self.assertFalse(chunks_start_with_link(vf))
        vf = ["link a link"]
        self.assertTrue(chunks_start_with_link(vf))
        vf = ["link", " a", " link"]
        self.assertTrue(chunks_start_with_link(vf))
        vf = ["li", "nk", " a", " link"]
        self.assertTrue(chunks_start_with_link(vf))


class TestCheckFilename(TestCase):

    def test_valid(self):
        check_filename(u"foo/bar")

    def test_backspace(self):
        self.assertRaises(InvalidFileName, check_filename, u"foo\\bar")
