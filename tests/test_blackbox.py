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
"""Blackbox tests."""

import os
import sys

from bzrlib.bzrdir import format_registry
import bzrlib.gpg
from bzrlib.repository import Repository
from bzrlib.tests.blackbox import ExternalBase
from bzrlib.tests import KnownFailure

from bzrlib.plugins.svn.convert import load_dumpfile
from bzrlib.plugins.svn.layout.standard import RootLayout
from bzrlib.plugins.svn.tests import SubversionTestCase


class TestBranch(SubversionTestCase, ExternalBase):

    def setUp(self):
        SubversionTestCase.setUp(self)
        SubversionTestCase.tearDown(self)
        ExternalBase.setUp(self)

    def tearDown(self):
        ExternalBase.tearDown(self)

    def test_branch_empty(self):
        repos_url = self.make_repository('d')
        self.run_bzr("branch %s dc" % repos_url)

    def commit_something(self, repos_url):
        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify("bar")
        dc.close()

    def test_branch_onerev(self):
        repos_url = self.make_client('d', 'de')
        self.commit_something(repos_url)
        self.run_bzr("branch %s dc" % repos_url)
        self.check_output("2\n", "revno de")

    def test_branch_onerev_stacked(self):
        repos_url = self.make_client('d', 'de')
        self.commit_something(repos_url)
        self.run_bzr("branch --stacked %s dc" % repos_url, retcode=3)
        
    def test_log_empty(self):
        repos_url = self.make_repository('d')
        self.run_bzr('log %s' % repos_url)

    def test_info_verbose(self):
        repos_url = self.make_repository('d')
        self.run_bzr('info -v %s' % repos_url)

    def test_pack(self):
        repos_url = self.make_repository('d')
        self.run_bzr('pack %s' % repos_url)

    def test_push_create_prefix(self):
        repos_url = self.make_repository('d')
        
        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/foo").modify()
        dc.close()

        self.run_bzr("branch %s/trunk dc" % repos_url)
        self.build_tree({"dc/foo": "blaaaa"})
        self.run_bzr("commit -m msg dc")
        self.run_bzr_error([
             'ERROR: Prefix missing for branches\\/mybranch; please create it before pushing.'],
             ["push", "-d", "dc", "%s/branches/mybranch" % repos_url])
        self.run_bzr("push --create-prefix -d dc %s/branches/mybranch" % repos_url)

    def test_push(self):
        repos_url = self.make_repository('d')
        
        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.close()

        self.run_bzr("branch %s dc" % repos_url)
        self.build_tree({"dc/foo": "blaaaa"})
        self.run_bzr("commit -m msg dc")
        self.run_bzr("push -d dc %s" % repos_url)
        self.check_output("", "status dc")

    def test_push_empty_existing(self):
        repos_url = self.make_repository('d')
        
        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        self.run_bzr("init dc")
        self.build_tree({"dc/foo": "blaaaa"})
        self.run_bzr("add dc/foo")
        self.run_bzr("commit -m msg dc")
        self.run_bzr_error([
            # Ideally this should say:
            # ['ERROR: Empty branch already exists at /trunk. Specify --overwrite or remove it before pushing.\n'
             'ERROR: These branches have diverged.  See "bzr help diverged-branches" for more information.\n'
            ], ["push", "-d", "dc", "%s/trunk" % repos_url])

    def test_dpush_empty_existing(self):
        repos_url = self.make_repository('d')
        
        dc = self.get_commit_editor(repos_url)
        dc.add_dir("trunk")
        dc.close()

        self.run_bzr("init dc")
        self.build_tree({"dc/foo": "blaaaa"})
        self.run_bzr("add dc/foo")
        self.run_bzr("commit -m msg dc")
        self.run_bzr_error(
            ['ERROR: Empty branch already exists at /trunk. Specify --overwrite or remove it before pushing.\n'],
            ["dpush", "-d", "dc", "%s/trunk" % repos_url])

    def test_push_verbose(self):
        repos_url = self.make_repository('d')
        self.run_bzr("init dc")
        self.build_tree({"dc/foo": "blaaaa"})
        self.run_bzr("add dc/foo")
        self.run_bzr("commit -m msg dc")
        self.run_bzr("push -v -d dc %s/trunk" % repos_url)
        self.build_tree({"dc/foo": "blaaaaa"})
        self.run_bzr("commit -m msg dc")
        self.run_bzr("push -v -d dc %s/trunk" % repos_url)

    def test_reconcile(self):
        repos_url = self.make_repository('d')

        output, err = self.run_bzr("reconcile %s" % repos_url, retcode=0)
        self.assertContainsRe(output, "Reconciliation complete.\n")

    def test_missing(self):
        repos_url = self.make_repository('d')
        
        self.run_bzr("init dc")

        os.chdir("dc")
        output, err = self.run_bzr("missing %s" % repos_url, retcode=1)
        self.assertContainsRe(output, "You are missing 1 revision\\(s\\):")

        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir('trunk')
        trunk.add_file("trunk/foo").modify()
        dc.close()

        output, err = self.run_bzr("missing %s" % repos_url, retcode=1)
        self.assertContainsRe(output, "You are missing 2 revision\\(s\\):")

    def test_push_overwrite(self):
        repos_url = self.make_repository('d')
        
        dc = self.get_commit_editor(repos_url)
        trunk = dc.add_dir('trunk')
        trunk.add_file("trunk/foo").modify()
        dc.close()

        self.run_bzr("init dc")
        self.build_tree({"dc/bar": "blaaaa"})
        self.run_bzr("add dc/bar")
        self.run_bzr("commit -m msg dc")
        self.run_bzr("push --overwrite -d dc %s/trunk" % repos_url)
        self.check_output("", "status dc")

    def test_dpush_empty(self):
        repos_url = self.make_repository('dp')
        self.run_bzr("init --default-rich-root dc")
        os.chdir("dc")
        self.run_bzr("dpush %s" % repos_url)

    def test_dpush(self):
        repos_url = self.make_repository('d')
        
        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.close()

        self.run_bzr("branch %s dc" % repos_url)
        self.build_tree({"dc/foo": "blaaaa"})
        self.run_bzr("commit -m msg dc")
        self.run_bzr("dpush -d dc %s" % repos_url)
        self.check_output("", "status dc")

    def test_dpush_new(self):
        repos_url = self.make_repository('d')
        
        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.close()

        self.run_bzr("branch %s dc" % repos_url)
        self.build_tree({"dc/foofile": "blaaaa"})
        self.run_bzr("add dc/foofile")
        self.run_bzr("commit -m msg dc")
        self.run_bzr("dpush -d dc %s" % repos_url)
        self.check_output("3\n", "revno dc")
        self.check_output("", "status dc")

    def test_dpush_wt_diff(self):
        repos_url = self.make_repository('d')
        
        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify()
        dc.close()

        self.run_bzr("branch %s dc" % repos_url)
        self.build_tree({"dc/foofile": "blaaaa"})
        self.run_bzr("add dc/foofile")
        self.run_bzr("commit -m msg dc")
        self.build_tree({"dc/foofile": "blaaaal"})
        self.run_bzr("dpush -d dc %s" % repos_url)
        self.check_output('modified:\n  foofile\n', "status dc")

    def test_info_workingtree(self):
        repos_url = self.make_client('d', 'dc')
        self.run_bzr('info -v dc')

    def test_dumpfile(self):
        filename = os.path.join(self.test_dir, "dumpfile")
        uuid = "606c7b1f-987c-4826-b37d-eb456ceb87e1"
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
        self.check_output("", 'svn-import --layout=none %s dc' % filename)
        load_dumpfile(filename, "realrepo")
        svnrepo = Repository.open("realrepo")
        self.assertEquals(uuid, svnrepo.uuid)
        svnrepo.set_layout(RootLayout())
        mapping = svnrepo.get_mapping()
        newrepos = Repository.open("dc")
        self.assertTrue(newrepos.has_revision(
            mapping.revision_id_foreign_to_bzr((uuid, "", 5))))
        self.assertTrue(newrepos.has_revision(
            mapping.revision_id_foreign_to_bzr((uuid, "", 1))))
        inv1 = newrepos.get_inventory(
                mapping.revision_id_foreign_to_bzr((uuid, "", 1)))
        inv2 = newrepos.get_inventory(
                mapping.revision_id_foreign_to_bzr((uuid, "", 5)))
        self.assertNotEqual(inv1.path2id("y"), inv2.path2id("y"))

    def test_svn_import_bzr_branch(self):
        self.run_bzr('init foo')
        self.run_bzr_error(['bzr: ERROR: Source repository is not a Subversion repository.\n'], 
                           ['svn-import', 'foo', 'dc'])

    def test_svn_import_bzr_repo(self):
        self.run_bzr('init-repo foo')
        self.run_bzr('init foo/bar')
        self.run_bzr_error(['bzr: ERROR: Source repository is not a Subversion repository.\n'],
                           ['svn-import', 'foo/bar', 'dc'])

    def test_list(self):
        repos_url = self.make_repository("a")
        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify("test")
        dc.add_file("bla").modify("ha")
        dc.close()
        self.check_output("a/bla\na/foo\n", "ls a")

    def test_info_remote(self):
        repos_url = self.make_repository("a")
        dc = self.get_commit_editor(repos_url)
        dc.add_file("foo").modify("test")
        dc.add_file("bla").modify("ha")
        dc.close()
        self.check_output(
                "Repository branch (format: subversion)\nLocation:\n  shared repository: a\n  repository branch: a\n", 'info a')

    def test_lightweight_checkout_lightweight_checkout(self):
        repos_url = self.make_client("a", "dc")
        self.build_tree({'dc/foo': "test", 'dc/bla': "ha"})
        self.client_add("dc/foo")
        self.client_add("dc/bla")
        self.client_commit("dc", "Msg")
        self.run_bzr("checkout --lightweight dc de")

    def test_commit(self):
        repos_url = self.make_client('d', 'de')
        self.build_tree({'de/foo': 'bla'})
        self.run_bzr("add de/foo")
        self.run_bzr("commit -m test de")
        self.check_output("2\n", "revno de")

    # this method imported from bzrlib.tests.test_msgeditor:
    def make_fake_editor(self, message='test message from fed\\n'):
        """Set up environment so that an editor will be a known script.

        Sets up BZR_EDITOR so that if an editor is spawned it will run a
        script that just adds a known message to the start of the file.
        """
        f = file('fed.py', 'wb')
        f.write('#!%s\n' % sys.executable)
        f.write("""\
# coding=utf-8
import sys
if len(sys.argv) == 2:
    fn = sys.argv[1]
    f = file(fn, 'rb')
    s = f.read()
    f.close()
    f = file(fn, 'wb')
    f.write('%s')
    f.write(s)
    f.close()
""" % (message, ))
        f.close()
        if sys.platform == "win32":
            # [win32] make batch file and set BZR_EDITOR
            f = file('fed.bat', 'w')
            f.write("""\
@echo off
"%s" fed.py %%1
""" % sys.executable)
            f.close()
            os.environ['BZR_EDITOR'] = 'fed.bat'
        else:
            # [non-win32] make python script executable and set BZR_EDITOR
            os.chmod('fed.py', 0755)
            os.environ['BZR_EDITOR'] = './fed.py'

    def test_set_branching_scheme_local(self):
        self.make_fake_editor()
        repos_url = self.make_repository("a")
        self.check_output("", 'svn-branching-scheme --set %s' % repos_url)

    def test_set_branching_scheme_global(self):
        self.make_fake_editor()
        repos_url = self.make_repository("a")
        self.check_output("", 'svn-branching-scheme --repository-wide --set %s' % repos_url)

    def monkey_patch_gpg(self):
        """Monkey patch the gpg signing strategy to be a loopback.

        This also registers the cleanup, so that we will revert to
        the original gpg strategy when done.
        """
        self._oldstrategy = bzrlib.gpg.GPGStrategy

        # monkey patch gpg signing mechanism
        bzrlib.gpg.GPGStrategy = bzrlib.gpg.LoopbackGPGStrategy

        self.addCleanup(self._fix_gpg_strategy)

    def _fix_gpg_strategy(self):
        bzrlib.gpg.GPGStrategy = self._oldstrategy

    def test_sign_my_commits(self):
        repos_url = self.make_repository('dc')
        self.commit_something(repos_url)

        self.monkey_patch_gpg()
        self.run_bzr('sign-my-commits')

    def test_pull_old(self):
        svn_url = self.make_repository('d')

        dc = self.get_commit_editor(svn_url)
        trunk = dc.add_dir("trunk")
        trunk.add_file("trunk/foo").modify("bar1")
        dc.close()

        dc = self.get_commit_editor(svn_url)
        trunk = dc.open_dir("trunk")
        trunk.open_file("trunk/foo").modify("bar2")
        dc.close()

        self.run_bzr('branch %s/trunk trunk' % svn_url)
        self.run_bzr('pull -d trunk -r1 %s/trunk' % svn_url)

    def test_knit_corruption(self):
        cwd = os.getcwd()
        svn_url = self.make_client('d', 'wc')

        os.chdir('wc')
        for d in ['trunk', 'branches', 'tags']:
           os.mkdir(d)
        f = open('trunk/file', 'wb')
        f.write('Hi\n')
        f.close()
        self.client_add("trunk")
        self.client_add("tags")
        self.client_add("branches")
        self.client_commit(".", "initial check-in")
        self.client_update(".")
        os.chdir(cwd)

        self.run_bzr('init-repo --default-rich-root --no-trees shared')
        os.chdir('shared')
        self.run_bzr('branch %s/trunk trunk' % svn_url)
        os.chdir(cwd)

        self.run_bzr('branch shared/trunk bzr-branch')
        os.chdir('bzr-branch')
        f = open('file', 'ab')
        f.write('Bye\n')
        f.close()
        self.run_bzr('ci -m "Add bye."')
        f = open('file', 'ab')
        f.write('Good riddance.\n')
        f.close()
        self.run_bzr('ci -m "Add good riddance."')

        output, err = self.run_bzr('push %s/branches/my-branch' % svn_url)
        self.assertEquals(output, '')
        self.assertEquals(err, 'Created new branch at /branches/my-branch.\n')
        os.chdir(cwd)

        self.run_bzr('co %s/trunk bzr-trunk' % svn_url)
        os.chdir('bzr-trunk')
        self.run_bzr('merge %s/branches/my-branch' % svn_url)
        self.run_bzr('nick my-branch')
        self.run_bzr('ci -m "Merge my-branch"')

        os.chdir(cwd)
        os.chdir('shared/trunk')
        self.run_bzr('pull')
